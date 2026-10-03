import AppKit
import Carbon.HIToolbox
import Foundation
import SwiftUI

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
        let root = AskOverlay(loop: st.loop, vault: st.vault, notes: st.notes) { [weak self] in self?.panel?.orderOut(nil) }
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
            ForEach(Array(Self.classify(text).enumerated()), id: \.offset) { _, line in row(line) }
        }
    }

    /// Marks each line as inside a ``` fence (rendered verbatim, monospaced) or not.
    private static func classify(_ text: String) -> [(raw: String, code: Bool)] {
        var inFence = false
        var out: [(String, Bool)] = []
        for raw in text.components(separatedBy: "\n") {
            if raw.trimmingCharacters(in: .whitespaces).hasPrefix("```") { inFence.toggle(); continue }
            out.append((raw, inFence))
        }
        return out
    }

    @ViewBuilder private func row(_ line: (raw: String, code: Bool)) -> some View {
        let t = line.raw.trimmingCharacters(in: .whitespaces)
        if line.code {
            Text(line.raw).font(.klMono).frame(maxWidth: .infinity, alignment: .leading)
        } else if t.isEmpty {
            Spacer().frame(height: 3)
        } else if let h = ["### ", "## ", "# "].first(where: t.hasPrefix) {
            inline(String(t.dropFirst(h.count))).font(.klHeading).padding(.top, 5)
                .accessibilityAddTraits(.isHeader)
        } else if t.hasPrefix("* ") || t.hasPrefix("- ") || t.hasPrefix("• ") {
            HStack(alignment: .top, spacing: 7) {
                Text("•").font(.klBody).foregroundStyle(.secondary).accessibilityHidden(true)
                inline(String(t.dropFirst(2))).font(.klBody).lineSpacing(3)
                Spacer(minLength: 0)
            }
        } else {
            inline(t).font(.klBody).lineSpacing(3)
        }
    }

    /// Inline markdown; `code` spans get the mono face from the shared scale.
    private func inline(_ s: String) -> Text {
        guard var a = try? AttributedString(
            markdown: s, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))
        else { return Text(s) }
        for run in a.runs where run.inlinePresentationIntent?.contains(.code) == true {
            a[run.range].font = .klMono
        }
        return Text(a)
    }
}

/// The Spotlight-like content: big field on top, answer scrolls below. Reuses ask.py.
struct AskOverlay: View {
    let loop: String
    let vault: String
    var notes = ""
    let onClose: () -> Void
    @State private var query = ""
    @State private var answer = ""
    @State private var status = ""
    @State private var busy = false
    private enum Outcome { case done, failed }
    @State private var outcome: Outcome?
    @State private var clearOutcome: DispatchWorkItem?
    @State private var gapLogged = false
    @State private var answerHeight: CGFloat = 0
    @FocusState private var focused: Bool

    private let maxAnswerHeight: CGFloat = 460

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                PlasmieView(state: busy ? .ask : (outcome == .failed ? .error : (outcome == .done ? .success : .idle)), size: 40)
                TextField(placeholder, text: $query)
                    .textFieldStyle(.plain).font(.klTitle)
                    .focused($focused)
                    .accessibilityLabel("Ask your vault")
                    .onSubmit(run)
            }
            .padding(.horizontal, 18).padding(.vertical, 16)

            // Live status row — shows the pipeline stage streamed from ask.py's stderr.
            if busy || outcome != nil {
                Divider()
                HStack(spacing: 8) {
                    Text(statusLine)
                        .font(.klLabel).foregroundStyle(.secondary)
                        .lineLimit(1).truncationMode(.tail)
                    Spacer()
                }
                .padding(.horizontal, 18).padding(.vertical, 8)
                .accessibilityElement(children: .combine)
                .accessibilityAddTraits(.updatesFrequently)
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
                            .accessibilityAddTraits(busy ? .updatesFrequently : [])
                        if gapLogged && !busy {
                            Text("Tentative: the vault has little on this. The gap was logged so it can be filled.")
                                .klNote()
                        }
                        if !sources.isEmpty {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Sources").font(.klMeta.weight(.semibold))
                                    .foregroundStyle(.secondary)
                                ForEach(Array(sources.enumerated()), id: \.offset) { _, src in
                                    Button { openInObsidian("\(vault)/\(src.path)") } label: {
                                        HStack(spacing: 6) {
                                            Image(systemName: "doc.text").font(.system(size: 10)).accessibilityHidden(true)
                                            Text(src.path).font(.klMeta).underline()
                                            Spacer(minLength: 0)
                                        }
                                    }
                                    .buttonStyle(.plain).foregroundStyle(.blue)
                                    .accessibilityLabel("Open \(src.path) in Obsidian")
                                    .help("Open in Obsidian")
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
                    Text("Esc to close · ⌃⌥⌘K to toggle").font(.klMeta).foregroundStyle(.tertiary)
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

    private var statusLine: String {
        if busy { return status.isEmpty ? "Searching your vault…" : status }
        return outcome == .failed ? "Couldn't get an answer. Try again." : "Answer ready"
    }

    private var placeholder: String {
        let n = Int(notes.trimmingCharacters(in: .whitespaces)) ?? 0
        return n > 0 ? "Ask your vault — \(n) notes" : "Ask your vault"
    }

    /// Spoken once when the stream ends, so VoiceOver users know the answer is complete.
    private func announceDone() {
        guard !answer.isEmpty else { return }
        NSAccessibility.post(element: NSApp as Any, notification: .announcementRequested,
                             userInfo: [.announcement: "Answer ready", .priority: NSAccessibilityPriorityLevel.high.rawValue])
    }

    private func run() {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty, !busy else { return }
        clearOutcome?.cancel(); outcome = nil
        busy = true; answer = ""; status = ""; answerHeight = 0; gapLogged = false
        AskActivity.shared.answering = true
        // The venv holds apple_fm_sdk (on-device answers); system python can't import it.
        let venvPy = "\(loop)/.venv/bin/python3"
        let py = FileManager.default.fileExists(atPath: venvPy) ? venvPy : "/usr/bin/python3"
        runStreaming(py, ["\(loop)/ask.py", q, vault],
                     onStatus: { status = $0; if $0.contains("coverage gap") { gapLogged = true } },
                     onChunk: { answer = $0 },
                     onDone: {
                         busy = false
                         AskActivity.shared.answering = false
                         answer = answer.trimmingCharacters(in: .whitespacesAndNewlines)
                         let failed = answer.isEmpty || status.lowercased().hasPrefix("error")
                         outcome = failed ? .failed : .done
                         if !failed {
                             let w = DispatchWorkItem { outcome = nil }
                             clearOutcome = w
                             DispatchQueue.main.asyncAfter(deadline: .now() + 3, execute: w)
                         }
                         announceDone()
                     })
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

