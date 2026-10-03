// Plasmie — native menu-bar app (macOS 13+ MenuBarExtra, .window style).
// HIG-aligned panel: SF Symbols, system materials, native typography. Actions run
// in-process (no Terminal pop-outs) and show output inline. Reads state via
// ~/.plasmie/plasmie-status.py; shells to the existing python/launchd you run.
import AppKit
import Carbon.HIToolbox
import Foundation
import SwiftUI

struct Status: Codable {
    var state = "healthy"
    var reason = ""          // why we're in `state` (e.g. "ingest: CONF-ERR")
    var pending = 0
    var pendingFile = ""
    var pendingItems = 0
    var notes = "?"
    var recent: [String] = []
    // Added for the connectors page. Optional on purpose: synthesized Decodable
    // throws on a missing non-optional key, which would blank the ENTIRE panel if
    // the installed plasmie-status.py were older than this binary.
    var errorSources: [String]? = nil
    var staleMinutes: Int? = nil
    var sourceAgeHours: [String: Double?]? = nil
    var activity = ""
    var journal = ""
    var vault = ""
    var loop = ""
}

extension Status {
    var errSources: [String] { errorSources ?? [] }
    /// Hours since this source last produced anything; nil = never seen.
    func age(_ key: String) -> Double? { (sourceAgeHours ?? [:])[key] ?? nil }
}

// MARK: - shell helpers

func runCapture(_ launch: String, _ args: [String]) -> String {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: launch)
    p.arguments = args
    let out = Pipe()
    p.standardOutput = out
    p.standardError = out
    do { try p.run() } catch { return "error: \(error.localizedDescription)" }
    let data = out.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return String(data: data, encoding: .utf8) ?? ""
}

/// Run a process and stream it live: stdout chunks via onChunk, stderr lines via
/// onStatus, and onDone at exit. Used by the ask overlay so the answer appears
/// token-by-token and the status row shows what the pipeline is doing.
func runStreaming(_ launch: String, _ args: [String],
                  onStatus: @escaping (String) -> Void,
                  onChunk: @escaping (String) -> Void,
                  onDone: @escaping () -> Void) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: launch)
    p.arguments = args
    let out = Pipe(), err = Pipe()
    p.standardOutput = out
    p.standardError = err
    let oh = out.fileHandleForReading, eh = err.fileHandleForReading

    // Live status: stderr arrives in small lines well before exit, so a readability
    // handler is fine. Decode the whole accumulated buffer (robust to a multibyte
    // char split across reads) and surface the latest non-empty line.
    var errBuf = Data()
    eh.readabilityHandler = { h in
        let d = h.availableData
        if d.isEmpty { return }
        errBuf.append(d)
        guard let s = String(data: errBuf, encoding: .utf8),
              let last = s.split(separator: "\n").last(where: { !$0.trimmingCharacters(in: .whitespaces).isEmpty })
        else { return }
        DispatchQueue.main.async { onStatus(String(last)) }
    }

    // The answer's final tokens arrive in one burst right before exit; a
    // readabilityHandler races terminationHandler and that burst gets dropped
    // (the blank-box bug). Reading stdout to EOF on a dedicated thread captures
    // everything — availableData returns the rest, then empty at EOF — with no
    // handler/terminate race. Decode the full buffer each time for progressive text.
    DispatchQueue.global().async {
        do { try p.run() } catch {
            DispatchQueue.main.async { onStatus("error: \(error.localizedDescription)"); onDone() }
            return
        }
        var outBuf = Data()
        while true {
            let d = oh.availableData
            if d.isEmpty { break }                       // EOF: write end closed
            outBuf.append(d)
            if let s = String(data: outBuf, encoding: .utf8) { DispatchQueue.main.async { onChunk(s) } }
        }
        p.waitUntilExit()
        eh.readabilityHandler = nil
        DispatchQueue.main.async { onDone() }
    }
}

func fireAndForget(_ launch: String, _ args: [String]) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: launch)
    p.arguments = args
    try? p.run()
}

func openExternal(_ path: String) { fireAndForget("/usr/bin/open", [path]) }

/// Open a vault path in Obsidian via the obsidian:// URI (reliably navigates to the
/// file/folder, unlike `open -a` which often just fronts the app). Falls back to open -a.
func openInObsidian(_ path: String) {
    var c = URLComponents()
    c.scheme = "obsidian"
    c.host = "open"
    c.queryItems = [URLQueryItem(name: "path", value: path)]
    if let url = c.url, NSWorkspace.shared.open(url) { return }
    fireAndForget("/usr/bin/open", ["-a", "Obsidian", path])
}
func detectObsidian() -> Bool { NSWorkspace.shared.urlForApplication(withBundleIdentifier: "md.obsidian") != nil }

func loadStatus() -> Status {
    let out = runCapture("/usr/bin/python3", ["\(NSHomeDirectory())/.plasmie/plasmie-status.py"])
    guard let data = out.data(using: .utf8) else { return Status() }
    return (try? JSONDecoder().decode(Status.self, from: data)) ?? Status()
}

// MARK: - model

final class Model: ObservableObject {
    @Published var s = Status()
    @Published var obsidian = detectObsidian()
    @Published var note = ""            // transient status line ("Promote started…")
    @Published var output = ""          // captured output of the last in-process run
    @Published var busy = false         // an in-process python run is underway
    @Published var spin = 0.0           // menu-bar logo rotation, driven only while active
    @Published var runningJobs: Set<String> = []   // labels of launchd jobs we kicked and are following
    private var poll: Timer?            // adaptive state poll (fast while active, slow idle)
    private var anim: Timer?            // 30fps spinner, alive only while active
    private var hintUntil = Date.distantPast   // optimistic "running" right after a click

    /// true whenever real work is happening (or just-kicked) — drives the animation
    var active: Bool { s.state == "running" || busy || Date() < hintUntil }

    init() {
        refresh()
        schedulePoll()
    }

    private func schedulePoll() {
        poll?.invalidate()
        poll = Timer.scheduledTimer(withTimeInterval: active ? 3 : 60, repeats: false) { [weak self] _ in
            self?.refresh()
        }
    }

    func refresh() {
        DispatchQueue.global().async {
            let new = loadStatus()
            DispatchQueue.main.async {
                self.s = new
                self.updateAnimation()
                self.schedulePoll()
            }
        }
    }

    /// start/stop the spinner so it animates exactly while work is happening
    private func updateAnimation() {
        // Reduce Motion: the logo stays static (the tint + status pill still say "working").
        if NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
            anim?.invalidate(); anim = nil
            if spin != 0 { spin = 0 }
            return
        }
        if active, anim == nil {
            anim = Timer.scheduledTimer(withTimeInterval: 1.0 / 30, repeats: true) { [weak self] _ in
                guard let self else { return }
                self.spin = (self.spin + 12).truncatingRemainder(dividingBy: 360)  // ~1 turn/sec
            }
        } else if !active {
            anim?.invalidate(); anim = nil
            withAnimation(.easeOut(duration: 0.2)) { spin = 0 }
        }
    }

    private var py: String { "/usr/bin/python3" }

    /// Fire a launchd job (spin immediately, poll fast) and follow it to completion:
    /// the row shows a running state, then a "<label> finished · <summary>" note.
    func kick(_ job: String, _ label: String) {
        guard !runningJobs.contains(label) else { return }
        runningJobs.insert(label)
        note = "\(label) running…"
        hintUntil = Date().addingTimeInterval(8)
        updateAnimation(); schedulePoll()
        fireAndForget("/bin/launchctl", ["kickstart", "-p", "gui/\(getuid())/\(job)"])
        DispatchQueue.global().async {
            let start = Date()
            let ceiling: TimeInterval = 15 * 60
            var sawRunning = false, exit = "0", finished = false
            while Date().timeIntervalSince(start) < ceiling {
                Thread.sleep(forTimeInterval: 2)
                let out = runCapture("/bin/launchctl", ["list", job])
                let running = out.contains("\"PID\" =")
                if running { sawRunning = true }
                if let r = out.range(of: "\"LastExitStatus\" = ") {
                    exit = String(out[r.upperBound...].prefix(while: { $0.isNumber || $0 == "-" }))
                }
                if !running && (sawRunning || Date().timeIntervalSince(start) > 6) { finished = true; break }
            }
            let fresh = finished ? loadStatus() : nil
            DispatchQueue.main.async {
                self.runningJobs.remove(label)
                if let fresh {
                    self.s = fresh
                    let summary = fresh.activity.isEmpty ? "\(fresh.notes) notes in vault" : fresh.activity
                    self.note = exit == "0" ? "\(label) finished · \(summary)"
                                            : "\(label) failed (exit \(exit)) · \(summary)"
                } else {
                    self.note = "\(label) still running in background"
                }
                self.updateAnimation(); self.schedulePoll()
            }
        }
    }

    /// run a python command in-process, show its output inline (no Terminal)
    func capture(_ args: [String], _ label: String) {
        busy = true; note = "\(label)…"; output = ""
        updateAnimation()
        DispatchQueue.global().async {
            let o = runCapture(self.py, args)
            DispatchQueue.main.async {
                self.busy = false
                self.output = o.trimmingCharacters(in: .whitespacesAndNewlines)
                self.note = "\(label) done"
                self.updateAnimation()
                self.refresh()
            }
        }
    }

    func reindexCheck() { capture(["\(s.loop)/reindex.py", "--check", s.vault], "Reindex") }

    /// ask a natural-language question against the vault (local RAG via ask.py)
    func ask(_ q: String) {
        let query = q.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return }
        capture(["\(s.loop)/ask.py", query, s.vault], "Asking")
    }

    /// mark a held draft resolved so it clears from the pending count
    private func markResolved(_ path: String) {
        if let cur = try? String(contentsOfFile: path, encoding: .utf8) {
            try? (cur + "\n\n✅ resolved\n").write(toFile: path, atomically: true, encoding: .utf8)
        }
    }

    /// approve all held items (apply their suggested action), then resolve the file
    func approveHeld() {
        let hold = s.pendingFile
        guard !hold.isEmpty else { return }
        busy = true; note = "Approving…"; output = ""; updateAnimation()
        DispatchQueue.global().async {
            let o = runCapture(self.py, ["\(self.s.loop)/promote-apply.py", hold, "--apply"])
            self.markResolved(hold)
            DispatchQueue.main.async {
                self.busy = false
                self.output = o.trimmingCharacters(in: .whitespacesAndNewlines)
                self.note = "Approved"; self.updateAnimation(); self.refresh()
            }
        }
    }

    /// dismiss held items without applying (resolve the file as-is)
    func dismissHeld() {
        guard !s.pendingFile.isEmpty else { return }
        markResolved(s.pendingFile)
        note = "Dismissed"; output = ""; refresh()
    }
}

// MARK: - views

let kLogo: NSImage = {
    let s: CGFloat = 16
    let img = NSImage(size: NSSize(width: s, height: s), flipped: false) { _ in
        let c = CGPoint(x: s / 2, y: s / 2)
        let r = s * 0.30
        NSColor.black.set()
        let ring = NSBezierPath()
        ring.appendArc(withCenter: c, radius: r, startAngle: 50, endAngle: 360, clockwise: false)
        ring.lineWidth = 1.7
        ring.lineCapStyle = .round
        ring.stroke()
        let tip = CGPoint(x: c.x + r, y: c.y)
        let head = NSBezierPath()
        head.move(to: CGPoint(x: tip.x, y: tip.y + 3.0))
        head.line(to: CGPoint(x: tip.x + 2.3, y: tip.y))
        head.line(to: CGPoint(x: tip.x - 2.3, y: tip.y))
        head.close()
        head.fill()
        NSBezierPath(ovalIn: CGRect(x: c.x - 2.0, y: c.y - 2.0, width: 4.0, height: 4.0)).fill()
        return true
    }
    img.isTemplate = true
    return img
}()

