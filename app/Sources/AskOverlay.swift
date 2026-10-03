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

