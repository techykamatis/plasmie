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

            // ask-anything — not an inline field; opens the Knowledge spotlight overlay
            Divider().padding(.horizontal, 12)
            Button { OverlayController.shared.toggle() } label: {
                HStack(spacing: 7) {
                    Image(systemName: "sparkle.magnifyingglass").foregroundStyle(.secondary).font(.system(size: 12))
                    Text("Ask anything in the vault…").font(.system(size: 12)).foregroundStyle(.secondary)
                    Spacer(minLength: 0)
                    Text("⌃⌥⌘K").font(.system(size: 11, weight: .medium, design: .rounded))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(.quaternary, in: RoundedRectangle(cornerRadius: 5))
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help("Open the Knowledge spotlight to ask anything in your vault (⌃⌥⌘K)")
            .padding(.horizontal, 12).padding(.vertical, 9)

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

// MARK: - global hotkey overlay (⌃⌥⌘-K → Spotlight-like ask panel)

/// Carbon global hotkey. ponytail: Carbon RegisterEventHotKey is the stdlib way
/// to get a system-wide hotkey with zero deps — swap for the KeyboardShortcuts
/// package only if we ever want user-rebindable keys.
final class HotKey {
    private var ref: EventHotKeyRef?
    private var handler: EventHandlerRef?
    private let onFire: () -> Void

    init(onFire: @escaping () -> Void) {
        self.onFire = onFire
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, event, ctx in
            Unmanaged<HotKey>.fromOpaque(ctx!).takeUnretainedValue().onFire()
            return noErr
        }, 1, &spec, Unmanaged.passUnretained(self).toOpaque(), &handler)
        let id = EventHotKeyID(signature: OSType(0x4B4C4F50), id: 1)  // 'KLOP'
        // ⌃⌥⌘-K — the "hyper" chord is collision-proof against macOS/app shortcuts.
        let mods = UInt32(controlKey | optionKey | cmdKey)
        RegisterEventHotKey(UInt32(kVK_ANSI_K), mods, id, GetApplicationEventTarget(), 0, &ref)
    }
    deinit {
        if let ref { UnregisterEventHotKey(ref) }
        if let handler { RemoveEventHandler(handler) }
    }
}

/// Borderless floating panel that can take keyboard focus (NSPanels can't by default).
final class OverlayPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

/// Owns the overlay panel; toggles it open/closed and centers it on the active screen.
final class OverlayController {
    static let shared = OverlayController()   // also reachable from the menu-bar panel
    private var panel: OverlayPanel?

    func toggle() {
        if let p = panel, p.isVisible { p.orderOut(nil); return }
        show()
    }

    private func show() {
        let st = loadStatus()
        let root = AskOverlay(loop: st.loop, vault: st.vault) { [weak self] in self?.panel?.orderOut(nil) }
        let p = panel ?? makePanel()
        panel = p
        p.contentView = NSHostingView(rootView: root)
        if let screen = NSScreen.main {
            let f = p.frame, vis = screen.visibleFrame
            let x = vis.midX - f.width / 2
            let y = vis.midY - f.height / 2 + 120   // sit a touch above center, Spotlight-style
            p.setFrameOrigin(NSPoint(x: x, y: y))
        }
        NSApp.activate(ignoringOtherApps: true)
        p.makeKeyAndOrderFront(nil)
    }

    private func makePanel() -> OverlayPanel {
        let p = OverlayPanel(contentRect: NSRect(x: 0, y: 0, width: 560, height: 80),
                             styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        p.level = .floating
        p.isFloatingPanel = true
        p.hidesOnDeactivate = false      // persist on blur — stays put while you read; Esc or ⌃⌥⌘-K dismisses
        p.isMovableByWindowBackground = true
        p.backgroundColor = .clear
        p.isOpaque = false
        p.hasShadow = true
        return p
    }
}

/// Measures its content's height up through the view tree so a ScrollView can be
/// sized to fit content (up to a cap) — a greedy ScrollView reports ~0 ideal
/// height, which collapses inside the borderless panel's fitting-size layout.
private struct HeightKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = max(value, nextValue()) }
}

/// Minimal block-level markdown: headings (#/##/###), bullets (* / -), blank-line
/// spacing, and inline **bold**/*italic*/`code` via AttributedString. Not a full
/// CommonMark engine — ponytail: covers what the local model actually emits;
/// extend (tables, nested lists) only if answers start using them.
struct MarkdownText: View {
    let text: String
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            let lines = text.components(separatedBy: "\n")
            ForEach(Array(lines.enumerated()), id: \.offset) { _, raw in row(raw) }
        }
    }

    @ViewBuilder private func row(_ raw: String) -> some View {
        let t = raw.trimmingCharacters(in: .whitespaces)
        if t.isEmpty {
            Spacer().frame(height: 3)
        } else if t.hasPrefix("### ") {
            inline(String(t.dropFirst(4))).font(.system(size: 13.5, weight: .semibold)).padding(.top, 4)
        } else if t.hasPrefix("## ") {
            inline(String(t.dropFirst(3))).font(.system(size: 15, weight: .bold)).padding(.top, 5)
        } else if t.hasPrefix("# ") {
            inline(String(t.dropFirst(2))).font(.system(size: 16.5, weight: .bold)).padding(.top, 5)
        } else if t.hasPrefix("* ") || t.hasPrefix("- ") || t.hasPrefix("• ") {
            HStack(alignment: .top, spacing: 7) {
                Text("•").font(.system(size: 12.5)).foregroundStyle(.secondary)
                inline(String(t.dropFirst(2))).font(.system(size: 12.5))
                Spacer(minLength: 0)
            }
        } else {
            inline(t).font(.system(size: 12.5))
        }
    }

    private func inline(_ s: String) -> Text {
        if let a = try? AttributedString(
            markdown: s, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)) {
            return Text(a)
        }
        return Text(s)
    }
}

/// The Spotlight-like content: big field on top, answer scrolls below. Reuses ask.py.
struct AskOverlay: View {
    let loop: String
    let vault: String
    let onClose: () -> Void
    @State private var query = ""
    @State private var answer = ""
    @State private var status = ""
    @State private var busy = false
    @State private var answerHeight: CGFloat = 0
    @FocusState private var focused: Bool

    private let maxAnswerHeight: CGFloat = 460

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "sparkle.magnifyingglass").font(.system(size: 18)).foregroundStyle(.secondary)
                TextField("Ask anything in the vault…", text: $query)
                    .textFieldStyle(.plain).font(.system(size: 20))
                    .focused($focused)
                    .onSubmit(run)
                if busy { ProgressView().controlSize(.small) }
            }
            .padding(.horizontal, 18).padding(.vertical, 16)

            // Live status row — shows the pipeline stage streamed from ask.py's stderr.
            if busy {
                Divider()
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(status.isEmpty ? "Searching your vault…" : status)
                        .font(.system(size: 12)).foregroundStyle(.secondary)
                        .lineLimit(1).truncationMode(.tail)
                    Spacer()
                }
                .padding(.horizontal, 18).padding(.vertical, 12)
            }

            // Answer: rendered markdown + clickable sources in a ScrollView sized to
            // its content up to maxAnswerHeight, then it scrolls. The height is
            // measured (HeightKey) because a ScrollView has no intrinsic height and
            // would otherwise collapse to ~0 in the panel's fitting-size layout.
            if !answer.isEmpty {
                let (body, sources) = Self.split(answer)
                Divider()
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        MarkdownText(text: body)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        if !sources.isEmpty {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Sources").font(.system(size: 11, weight: .semibold))
                                    .foregroundStyle(.secondary)
                                ForEach(Array(sources.enumerated()), id: \.offset) { _, src in
                                    Button { openInObsidian("\(vault)/\(src.path)") } label: {
                                        HStack(spacing: 6) {
                                            Image(systemName: "doc.text").font(.system(size: 10))
                                            Text(src.path).font(.system(size: 11)).underline()
                                            Spacer(minLength: 0)
                                        }
                                    }
                                    .buttonStyle(.plain).foregroundStyle(.blue)
                                }
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(16)
                    .background(GeometryReader { g in
                        Color.clear.preference(key: HeightKey.self, value: g.size.height)
                    })
                }
                .frame(height: min(max(answerHeight, 1), maxAnswerHeight))
                .onPreferenceChange(HeightKey.self) { answerHeight = $0 }
            }

            if !busy && !answer.isEmpty {
                Divider()
                HStack(spacing: 6) {
                    Spacer()
                    Text("Esc to close · ⌃⌥⌘K to toggle").font(.system(size: 10)).foregroundStyle(.tertiary)
                }
                .padding(.horizontal, 18).padding(.vertical, 8)
            }
        }
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(.white.opacity(0.12)))
        .frame(width: 560)
        // Defer to the next runloop tick: onAppear fires before the panel finishes
        // becoming key, and focus set that early doesn't stick. async lands it after.
        .onAppear { DispatchQueue.main.async { focused = true } }
        .onExitCommand(perform: onClose)   // Esc closes
    }

    private func run() {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty, !busy else { return }
        busy = true; answer = ""; status = ""; answerHeight = 0
        runStreaming("/usr/bin/python3", ["\(loop)/ask.py", q, vault],
                     onStatus: { status = $0 },
                     onChunk: { answer = $0 },
                     onDone: { busy = false; answer = answer.trimmingCharacters(in: .whitespacesAndNewlines) })
    }

    /// Split ask.py's output into the markdown body and the parsed source list.
    /// ask.py prints "\nSources:\n  · <relpath> (<score>)" — strip the score and
    /// keep the vault-relative path so each can open in Obsidian.
    static func split(_ full: String) -> (body: String, sources: [(path: String, score: String)]) {
        guard let r = full.range(of: "\nSources:") else { return (full, []) }
        let body = String(full[..<r.lowerBound]).trimmingCharacters(in: .whitespacesAndNewlines)
        var sources: [(String, String)] = []
        for line in full[r.upperBound...].split(separator: "\n") {
            var l = line.trimmingCharacters(in: .whitespaces)
            guard l.hasPrefix("·") else { continue }
            l = l.dropFirst(1).trimmingCharacters(in: .whitespaces)
            var score = ""
            if l.hasSuffix(")"), let p = l.range(of: " (", options: .backwards) {
                score = String(l[l.index(p.lowerBound, offsetBy: 2)..<l.index(before: l.endIndex)])
                l = String(l[..<p.lowerBound])
            }
            sources.append((l, score))
        }
        return (body, sources)
    }
}

// MARK: - first-run self-install

/// The backend (~/.plasmie) is set up once the answer model is present —
/// that's the long pole, so its config.json is a reliable "ready" marker.
func backendReady() -> Bool {
    let h = NSHomeDirectory(), fm = FileManager.default
    return fm.fileExists(atPath: "\(h)/.plasmie/.venv/bin/python3")
        && fm.fileExists(atPath: "\(h)/.plasmie/models/gemma-4-e4b/config.json")
}

/// Shows the one-time setup window if the engine isn't installed yet.
final class SetupController {
    static let shared = SetupController()
    private var win: NSWindow?
    func showIfNeeded() {
        guard !backendReady() else { return }
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 460, height: 250),
                         styleMask: [.titled, .closable], backing: .buffered, defer: false)
        w.title = "Set up Plasmie"
        w.center()
        w.isReleasedWhenClosed = false
        w.level = .floating
        w.contentView = NSHostingView(rootView: SetupView { [weak self] in self?.win?.orderOut(nil) })
        win = w
        NSApp.activate(ignoringOtherApps: true)
        w.makeKeyAndOrderFront(nil)
    }
}

/// Runs app-setup.sh (bundled) and shows friendly progress. Idempotent script,
/// so "Try again" safely resumes a partial setup.
struct SetupView: View {
    let onDone: () -> Void
    @State private var pct: Double = 0
    @State private var msg = "Preparing…"
    @State private var failed: String?
    @State private var running = false
    @State private var done = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                Image(nsImage: kLogo)
                Text(done ? "You're all set" : "Setting up Plasmie")
                    .font(.system(size: 16, weight: .semibold))
            }
            if done {
                Text("Plasmie is ready. Press ⌃⌥⌘K anywhere to ask a question about "
                     + "your notes — look for the brain icon in your menu bar at the top of the screen.")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer()
                HStack { Spacer(); Button("Done") { onDone() }.keyboardShortcut(.defaultAction) }
            } else {
                Text("One-time setup: this installs the local AI and creates your notes vault. "
                     + "It can take several minutes (a large download) — you can keep using your Mac.")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let f = failed {
                    Text(f).font(.system(size: 12)).foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                    Button("Try again") { run() }
                } else {
                    ProgressView(value: pct, total: 100)
                    Text(msg).font(.system(size: 12)).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer()
            }
        }
        .padding(20).frame(width: 460, height: 250)
        .onAppear { if !running { run() } }
    }

    private func run() {
        running = true; failed = nil; pct = 0; msg = "Preparing…"
        guard let res = Bundle.main.resourcePath else { failed = "Missing app resources."; return }
        runStreaming("/bin/bash", ["\(res)/backend/app-setup.sh", res],
            onStatus: { _ in },
            onChunk: { full in                       // full accumulated stdout each call
                for line in full.components(separatedBy: "\n") {
                    if line.hasPrefix("PROGRESS:") {
                        let parts = line.dropFirst("PROGRESS:".count).split(separator: ":", maxSplits: 1)
                        if parts.count == 2, let p = Double(parts[0]) { pct = p; msg = String(parts[1]) }
                    } else if line.hasPrefix("ERROR:") {
                        failed = String(line.dropFirst("ERROR:".count))
                    }
                }
            },
            onDone: {
                running = false
                if failed == nil && pct >= 100 { done = true }   // show success, let the user dismiss
                else if failed == nil { failed = "Setup ended early. Tap Try again." }
            })
    }
}

/// Wires the global hotkey to the overlay at launch (the MenuBarExtra scene stays).
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let overlay = OverlayController.shared
    private var hotKey: HotKey?
    func applicationDidFinishLaunching(_ notification: Notification) {
        hotKey = HotKey { [weak self] in self?.overlay.toggle() }
        SetupController.shared.showIfNeeded()
    }
}

@main
struct PlasmieApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
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
