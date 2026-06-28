// Plasmie — native menu-bar app (macOS 13+ MenuBarExtra, .window style).
// HIG-aligned panel: SF Symbols, system materials, native typography. Actions run
// in-process (no Terminal pop-outs) and show output inline. Reads state via
// ~/.plasmie/plasmie-status.py; shells to the existing python/launchd you run.
import AppKit
import Foundation
import SwiftUI

struct Status: Codable {
    var state = "healthy"
    var pending = 0
    var pendingFile = ""
    var pendingBase = ""
    var pendingItems = 0
    var notes = "?"
    var recent: [String] = []
    var activity = ""
    var journal = ""
    var vault = ""
    var loop = ""
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

    /// fire a launchd job; spin immediately (optimistic) and poll fast until it lands
    func kick(_ job: String, _ label: String) {
        note = "\(label)…"
        hintUntil = Date().addingTimeInterval(8)
        updateAnimation(); schedulePoll()
        fireAndForget("/bin/launchctl", ["kickstart", "-p", "gui/\(getuid())/\(job)"])
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { self.note = "\(label) started"; self.refresh() }
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

struct StatusPill: View {
    let state: String
    @State private var pulse = false
    private var spec: (String, Color) {
        switch state {
        case "pending": return ("Needs review", .orange)
        case "running": return ("Working", .blue)
        case "error":   return ("Promote skipped", .red)
        default:        return ("Healthy", .green)
        }
    }
    private var animated: Bool { state == "running" || state == "pending" }
    var body: some View {
        HStack(spacing: 5) {
            Circle()
                .fill(spec.1)
                .frame(width: 6, height: 6)
                .opacity(animated && pulse ? 0.3 : 1)
                .scaleEffect(animated && pulse ? 0.8 : 1)
            Text(spec.0).font(.caption2.weight(.semibold))
        }
        .padding(.horizontal, 8).padding(.vertical, 3)
        .background(Capsule().fill(spec.1.opacity(0.16)))
        .foregroundStyle(spec.1)
        .onAppear {
            guard animated else { return }
            withAnimation(.easeInOut(duration: 0.7).repeatForever(autoreverses: true)) { pulse = true }
        }
    }
}

/// A menu-style row: SF Symbol + label + a small gray caption (what it does / when),
/// full-width, with hover highlight. The caption makes each action self-explanatory.
struct ActionRow: View {
    let title: String
    let symbol: String
    var detail: String = ""
    var tint: Color = .primary
    let action: () -> Void
    @State private var hover = false
    var body: some View {
        Button(action: action) {
            HStack(alignment: .firstTextBaseline, spacing: 9) {
                Image(systemName: symbol).frame(width: 16).foregroundStyle(tint == .primary ? .secondary : tint)
                VStack(alignment: .leading, spacing: 1) {
                    Text(title).font(.system(size: 13)).foregroundStyle(.primary)
                    if !detail.isEmpty {
                        Text(detail).font(.system(size: 10.5)).foregroundStyle(.secondary)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 12).padding(.vertical, 6)
            .contentShape(Rectangle())
            .background(hover ? Color.primary.opacity(0.08) : .clear)
            .clipShape(RoundedRectangle(cornerRadius: 6))
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
    }
}

struct Panel: View {
    @ObservedObject var m: Model
    private var working: Bool { m.s.state == "running" || m.busy }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // header
            HStack(spacing: 7) {
                Image(nsImage: kLogo).foregroundStyle(.primary)
                Text("Plasmie").font(.system(size: 13, weight: .semibold))
                Spacer()
                StatusPill(state: m.s.state)
            }
            .padding(.horizontal, 12).padding(.top, 11).padding(.bottom, 9)

            // live "what's happening" line — the running step's heartbeat
            if !m.s.activity.isEmpty {
                HStack(spacing: 7) {
                    if working {
                        ProgressView().controlSize(.small).scaleEffect(0.8).frame(width: 14)
                    } else {
                        Image(systemName: "checkmark.circle.fill").foregroundStyle(.green).font(.system(size: 12)).frame(width: 14)
                    }
                    Text(m.s.activity).font(.system(size: 12)).foregroundStyle(working ? .primary : .secondary)
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 12).padding(.bottom, 9)
            }

            if !m.obsidian {
                banner("Obsidian required to view the vault", symbol: "exclamationmark.triangle.fill", tint: .orange) {
                    openExternal("https://obsidian.md")
                }
            }

            // held-for-review (the uncertain minority; everything confident was auto-applied)
            if m.s.pending > 0 {
                Divider().padding(.horizontal, 12)
                VStack(alignment: .leading, spacing: 7) {
                    Label("\(m.s.pendingItems) held for review", systemImage: "tray.full.fill")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.orange)
                    Text("Auto-apply was unsure — approve, edit, or dismiss.")
                        .font(.caption).foregroundStyle(.secondary)
                    HStack(spacing: 8) {
                        Button { openInObsidian(m.s.pendingFile) } label: { Label("Review", systemImage: "pencil") }
                            .help("Open the held items in Obsidian to inspect or change their action before applying.")
                        Button { m.approveHeld() } label: { Label("Approve all", systemImage: "checkmark.circle.fill") }
                            .tint(.orange)
                            .help("File all held items using the suggested merge/create, then clear them.")
                        Button { m.dismissHeld() } label: { Label("Dismiss", systemImage: "xmark.circle") }
                            .help("Discard the held items without filing anything.")
                    }
                    .controlSize(.small).buttonStyle(.bordered)
                }
                .padding(.horizontal, 12).padding(.vertical, 9)
            }

            Divider().padding(.horizontal, 12)

            // stats + recent
            VStack(alignment: .leading, spacing: 5) {
                Label("\(m.s.notes) notes in vault", systemImage: "doc.text")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
                ForEach(m.s.recent.prefix(3), id: \.self) { line in
                    Text(line)
                        .font(.system(size: 10.5, design: .monospaced))
                        .foregroundStyle(.tertiary)
                        .lineLimit(1).truncationMode(.middle)
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 9)

            Divider().padding(.horizontal, 12)

            // actions
            VStack(spacing: 1) {
                ActionRow(title: "Run promote now", symbol: "arrow.triangle.2.circlepath",
                          detail: "Find new knowledge & auto-file it · runs nightly") { m.kick("com.plasmie.dev-promote", "Promote") }
                ActionRow(title: "Run ingest now", symbol: "tray.and.arrow.down",
                          detail: "Capture latest Slack & sessions · runs hourly") { m.kick("com.plasmie.dev-ingest", "Ingest") }
                ActionRow(title: "Open vault in Obsidian", symbol: "folder",
                          detail: "Browse & edit all your notes") { openInObsidian(m.s.vault) }
                if !m.s.journal.isEmpty {
                    ActionRow(title: "Open today's journal", symbol: "book.closed",
                              detail: "Today's raw captured activity") { openInObsidian(m.s.journal) }
                }
                ActionRow(title: "Reindex check", symbol: "magnifyingglass",
                          detail: "Recount & flag orphans · changes nothing") { m.reindexCheck() }
                ActionRow(title: "Open activity log", symbol: "doc.plaintext",
                          detail: "History of every ingest & promote run") { openExternal("\(m.s.loop)/feed.log") }
                ActionRow(title: "Refresh", symbol: "arrow.clockwise",
                          detail: "Re-read status now · auto every 60s") { m.refresh() }
            }
            .padding(.horizontal, 6).padding(.vertical, 4)

            // transient note + captured output
            if !m.note.isEmpty || !m.output.isEmpty {
                Divider().padding(.horizontal, 12)
                VStack(alignment: .leading, spacing: 5) {
                    if !m.note.isEmpty {
                        HStack(spacing: 6) {
                            if m.busy { ProgressView().controlSize(.small) }
                            Text(m.note).font(.caption).foregroundStyle(.secondary)
                            Spacer()
                            if !m.output.isEmpty {
                                Button("Clear") { m.output = ""; m.note = "" }
                                    .buttonStyle(.plain).font(.caption).foregroundStyle(.blue)
                            }
                        }
                    }
                    if !m.output.isEmpty {
                        Text(m.output)
                            .font(.system(size: 10.5, design: .monospaced))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .textSelection(.enabled)
                            .lineLimit(24)
                            .padding(7)
                            .background(RoundedRectangle(cornerRadius: 6).fill(Color.primary.opacity(0.05)))
                    }
                }
                .padding(.horizontal, 12).padding(.vertical, 9)
            }

            Divider().padding(.horizontal, 12)
            VStack(spacing: 1) {
                ActionRow(title: "Quit Plasmie", symbol: "power") { NSApp.terminate(nil) }
            }
            .padding(.horizontal, 6).padding(.vertical, 4)
        }
        .frame(width: 320)
    }

    @ViewBuilder func banner(_ text: String, symbol: String, tint: Color, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 7) {
                Image(systemName: symbol).foregroundStyle(tint)
                Text(text).font(.caption).foregroundStyle(.primary)
                Spacer()
                Image(systemName: "arrow.up.forward.square").foregroundStyle(.secondary)
            }
            .padding(.horizontal, 12).padding(.vertical, 7)
            .background(tint.opacity(0.10))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

@main
struct PlasmieApp: App {
    @StateObject private var m = Model()

    private var tint: Color {
        switch m.s.state {
        case "pending": return .orange
        case "error":   return .red
        case "running": return .secondary
        default:        return .primary
        }
    }

    var body: some Scene {
        MenuBarExtra {
            Panel(m: m)
        } label: {
            HStack(spacing: 3) {
                Image(nsImage: kLogo)
                    .rotationEffect(.degrees(m.spin))   // spins ~1 turn/sec while a loop runs
                if m.s.pending > 0 { Text("\(m.s.pending)") }
            }
            .foregroundStyle(tint)
        }
        .menuBarExtraStyle(.window)
    }
}
