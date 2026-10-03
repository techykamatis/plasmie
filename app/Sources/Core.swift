// Plasmie (Plasmie) — native menu-bar app (macOS 13+ MenuBarExtra, .window style).
// HIG-aligned panel: SF Symbols, system materials, native typography. Actions run
// in-process (no Terminal pop-outs) and show output inline. Reads state via
// ~/.plasmie/plasmie-status.py; shells to the existing python/launchd you run.
import AppKit
import Carbon.HIToolbox
import Combine
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
    @Published var plasmie: PlasmieState = .idle       // what Plasmie is doing, derived from status
    @Published var menuImage: NSImage = PlasmieGlyph.still(.idle)   // menu-bar template glyph
    @Published var runningJobs: Set<String> = []   // labels of launchd jobs we kicked and are following
    private var poll: Timer?            // adaptive state poll (fast while active, slow idle)
    private var anim: Timer?            // 8fps glyph frame swap, alive only while a busy state runs
    private var cancellables = Set<AnyCancellable>()
    private var askActive = false
    private var allOff = false
    private var minSourceAge: Double? = nil    // youngest enabled source's age, hours
    private var successUntil = Date.distantPast
    private var shownGlyph: PlasmieState = .idle
    private var tweenFrom: PlasmieState = .idle
    private var tweenStep = 0                  // 0 = not tweening; 1...tweenFrames in flight
    private var cycle = 0
    private var hintUntil = Date.distantPast   // optimistic "running" right after a click

    // Evolutions and trophies (plasmie-achievements.py), reloaded at most every ~5 minutes
    @Published var ach: Achievements? = nil
    @Published var celebrating: String? = nil      // name of a just-unlocked trophy, for a few seconds
    private var achLoadedAt = Date.distantPast
    private var achLoading = false
    private var celebrated = Set<String>()
    var stage: AchStage? { ach?.stage }
    var trophies: [Trophy] { ach?.trophyList ?? [] }
    var unlockedCount: Int { ach?.unlockedTotal ?? 0 }
    var totalTrophies: Int { ach?.trophyTotal ?? 0 }
    var newly: [String] { ach?.newly ?? [] }
    /// What the panel's hero shows: a brief `success` while a trophy is being celebrated.
    var heroPlasmie: PlasmieState { celebrating != nil ? .success : plasmie }

    /// true whenever real work is happening (or just-kicked) — drives the animation
    var active: Bool { s.state == "running" || busy || Date() < hintUntil }

    init() {
        AskActivity.shared.$answering
            .receive(on: DispatchQueue.main)
            .sink { [weak self] on in self?.askActive = on; self?.recomputePlasmie() }
            .store(in: &cancellables)
        refresh()
        schedulePoll()
    }

    private func schedulePoll() {
        poll?.invalidate()
        poll = Timer.scheduledTimer(withTimeInterval: active ? 3 : 60, repeats: false) { [weak self] _ in
            self?.refresh()
        }
    }

    func refreshAchievements() {
        guard !achLoading, Date().timeIntervalSince(achLoadedAt) > 290 else { return }
        achLoading = true
        DispatchQueue.global(qos: .utility).async {
            let r = loadAchievements()
            DispatchQueue.main.async {
                self.achLoading = false
                guard let r else { return }          // keep the last good report on failure
                self.achLoadedAt = Date()
                self.ach = r
                self.celebrate(r)
            }
        }
    }

    /// New trophy: the hero plays `success` and the stage line names it for ~6s. No modal.
    /// "New" = unlocked but never celebrated by THIS app. The hourly ingest usually records
    /// an unlock first, so the engine's one-shot `newly` list is almost always empty here;
    /// the app keeps its own seen-set instead (seeded silently on first launch).
    private func celebrate(_ r: Achievements) {
        let key = "plasmie.seenTrophies"
        let unlocked = r.trophyList.filter { $0.unlocked == true }.map(\.id)
        guard let seenList = UserDefaults.standard.stringArray(forKey: key) else {
            UserDefaults.standard.set(unlocked, forKey: key)     // first launch: no backlog parade
            return
        }
        let fresh = unlocked.filter { !seenList.contains($0) && !celebrated.contains($0) }
        guard let id = fresh.first else { return }
        celebrated.formUnion(fresh)
        UserDefaults.standard.set(Array(Set(seenList).union(fresh)), forKey: key)
        celebrating = r.trophyList.first { $0.id == id }?.title ?? "Trophy"
        let mine = celebrating
        DispatchQueue.main.asyncAfter(deadline: .now() + 6) { [weak self] in
            if self?.celebrating == mine { self?.celebrating = nil }
        }
    }

    func refresh() {
        refreshAchievements()
        let wasActive = active
        DispatchQueue.global().async {
            let new = loadStatus()
            let off = ConnectorsModel.readOff()
            DispatchQueue.main.async {
                self.s = new
                self.allOff = Connector.all.allSatisfy { off.contains($0.id) }
                self.minSourceAge = Connector.all.filter { !off.contains($0.id) }
                    .compactMap { new.age($0.ageKey) }.min()
                if wasActive && !self.active && new.state != "error" { self.flashSuccess() }
                self.recomputePlasmie()
                self.updateAnimation()
                self.schedulePoll()
            }
        }
    }

    /// A job that just finished OK reads as `success` for ~3s, then settles.
    private func flashSuccess() {
        successUntil = Date().addingTimeInterval(3)
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.1) { [weak self] in self?.recomputePlasmie() }
    }

    private func recomputePlasmie() {
        let new = PlasmieState.derive(status: s, askActive: askActive, inProcess: busy ? note : nil,
                                    allOff: allOff, minSourceAgeHours: minSourceAge,
                                    success: Date() < successUntil)
        guard new != plasmie else { return }
        plasmie = new
        if !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
            tweenFrom = shownGlyph; tweenStep = 1
        }
        updateAnimation()
    }

    /// Menu-bar glyph: swap cached template frames at 8fps while a busy state runs (and for
    /// the few morph-tween frames after a state change); otherwise show the static pose.
    /// Reduce Motion: always static, no tween.
    private func updateAnimation() {
        if NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
            anim?.invalidate(); anim = nil
            tweenStep = 0
            setGlyph(PlasmieGlyph.still(plasmie), plasmie)
            return
        }
        if plasmie.animatesMenuBar || tweenStep > 0 {
            if anim == nil {
                let t = Timer(timeInterval: 1.0 / 8, repeats: true) { [weak self] _ in self?.tick() }
                RunLoop.main.add(t, forMode: .common)
                anim = t
            }
        } else {
            anim?.invalidate(); anim = nil
            setGlyph(PlasmieGlyph.still(plasmie), plasmie)
        }
    }

    private func tick() {
        if tweenStep > 0 {
            setGlyph(PlasmieGlyph.tween(from: tweenFrom, to: plasmie, step: tweenStep), nil)
            if tweenStep >= PlasmieGlyph.tweenFrames { tweenStep = 0; shownGlyph = plasmie; cycle = 0 } else { tweenStep += 1 }
            return
        }
        guard plasmie.animatesMenuBar else { updateAnimation(); return }
        cycle += 1
        setGlyph(PlasmieGlyph.frame(plasmie, cycle), plasmie)
    }

    private func setGlyph(_ img: NSImage, _ settled: PlasmieState?) {
        menuImage = img
        if let settled { shownGlyph = settled }
    }

    private var py: String { "/usr/bin/python3" }

    /// Fire a launchd job (spin immediately, poll fast) and follow it to completion:
    /// the row shows a running state, then a "<label> finished · <summary>" note.
    func kick(_ job: String, _ label: String) {
        guard !runningJobs.contains(label) else { return }
        runningJobs.insert(label)
        note = "\(label) running…"
        hintUntil = Date().addingTimeInterval(8)
        recomputePlasmie(); updateAnimation(); schedulePoll()
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
                    if exit == "0" { self.flashSuccess() }
                    self.note = exit == "0" ? "\(label) finished · \(summary)"
                                            : "\(label) failed (exit \(exit)) · \(summary)"
                } else {
                    self.note = "\(label) still running in background"
                }
                self.recomputePlasmie(); self.updateAnimation(); self.schedulePoll()
            }
        }
    }

    /// run a python command in-process, show its output inline (no Terminal)
    func capture(_ args: [String], _ label: String) {
        busy = true; note = "\(label)…"; output = ""
        recomputePlasmie(); updateAnimation()
        DispatchQueue.global().async {
            let o = runCapture(self.py, args)
            DispatchQueue.main.async {
                self.busy = false
                self.output = o.trimmingCharacters(in: .whitespacesAndNewlines)
                self.note = "\(label) done"
                self.recomputePlasmie(); self.updateAnimation()
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
        busy = true; note = "Approving…"; output = ""; recomputePlasmie(); updateAnimation()
        DispatchQueue.global().async {
            let o = runCapture(self.py, ["\(self.s.loop)/promote-apply.py", hold, "--apply"])
            self.markResolved(hold)
            DispatchQueue.main.async {
                self.busy = false
                self.output = o.trimmingCharacters(in: .whitespacesAndNewlines)
                self.note = "Approved"; self.recomputePlasmie(); self.updateAnimation(); self.refresh()
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

extension PlasmieState {
    /// Maps the pipeline's real status to what Plasmie shows. Order matters: honest status
    /// first (never look happy while ingest is failing), then flavour.
    static func derive(status s: Status, askActive: Bool, inProcess: String?, allOff: Bool,
                       minSourceAgeHours: Double?, success: Bool,
                       quietAfterHours: Double = 24) -> PlasmieState {
        let act = s.activity.lowercased()
        if askActive { return .ask }
        if allOff { return .off }
        if s.state == "running" || inProcess != nil {
            let text = act + " " + (inProcess ?? "").lowercased()
            if text.contains("summar") || text.contains("digest") { return .summarize }
            if text.contains("promot") || text.contains("draft") || text.contains("generating")
                || text.contains("duplicate") || text.contains("auto-apply") || text.contains("approv") { return .promote }
            return .ingest        // ingesting / indexing / anything else running
        }
        if act.contains("busy") { return .busy }     // "Skipped — machine busy": jobs deferred, not failed
        if s.state == "error" { return .error }
        if success { return .success }
        if s.state == "pending" || s.pending > 0 { return .held }
        if let age = minSourceAgeHours, age > quietAfterHours { return .quiet }
        return .idle
    }
}
