import AppKit
import Carbon.HIToolbox
import Foundation
import SwiftUI

struct StatusPill: View {
    let state: String
    var reason: String = ""
    @State private var pulse = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    private var spec: (String, Color) {
        switch state {
        case "pending": return ("Needs review", .orange)
        case "running": return ("Working", .blue)
        // reason comes from plasmie-status.py; falling back to the old wording keeps
        // an older status script working, but ingest errors now say so.
        case "error":   return (reason.isEmpty ? "Promote skipped" : reason, .red)
        default:        return ("Healthy", .green)
        }
    }
    private var animated: Bool { (state == "running" || state == "pending") && !reduceMotion }
    var body: some View {
        HStack(spacing: 5) {
            Circle()
                .fill(spec.1)
                .frame(width: 6, height: 6)
                .opacity(animated && pulse ? 0.3 : 1)
                .scaleEffect(animated && pulse ? 0.8 : 1)
            Text(spec.0).font(.klMeta.weight(.semibold))
        }
        .padding(.horizontal, 8).padding(.vertical, 3)
        .background(Capsule().fill(spec.1.opacity(0.16)))
        .foregroundStyle(spec.1)
        .accessibilityElement(children: .combine)
        .onAppear {
            guard animated else { return }
            withAnimation(.easeInOut(duration: 0.7).repeatForever(autoreverses: true)) { pulse = true }
        }
    }
}

private struct CommandShortcut: ViewModifier {
    let key: Character?
    @ViewBuilder func body(content: Content) -> some View {
        if let key { content.keyboardShortcut(KeyEquivalent(key), modifiers: .command) } else { content }
    }
}

/// A menu-style row: SF Symbol + title + quiet detail, trailing shortcut hint.
/// A real Button (keyboard-focusable, visible focus ring), one combined VoiceOver label.
struct ActionRow: View {
    let title: String
    let symbol: String
    var detail: String = ""
    var key: Character? = nil          // ⌘-key equivalent, shown trailing
    var running = false                // job in flight: spinner, disabled
    var compact = false                // demoted footer style
    let action: () -> Void
    @State private var hover = false
    @FocusState private var focused: Bool

    private var shownDetail: String { running ? "Running…" : detail }
    var body: some View {
        Button(action: action) {
            HStack(alignment: .firstTextBaseline, spacing: 9) {
                Image(systemName: symbol).frame(width: 16).foregroundStyle(.secondary)
                VStack(alignment: .leading, spacing: 1) {
                    Text(title).font(compact ? .klLabel : .klBody).foregroundStyle(compact ? .secondary : .primary)
                    if !shownDetail.isEmpty { Text(shownDetail).font(.klMeta).foregroundStyle(.secondary) }
                }
                Spacer(minLength: 0)
                if running {
                    ProgressView().controlSize(.small).scaleEffect(0.8)
                } else if let key {
                    Text("⌘\(String(key).uppercased())").font(.klMeta).foregroundStyle(.tertiary)
                }
            }
            .padding(.horizontal, 12).padding(.vertical, compact ? 4 : 6)
            .contentShape(Rectangle())
            .background(hover || focused ? Color.primary.opacity(0.08) : .clear)
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color.accentColor, lineWidth: focused ? 2 : 0))
        }
        .buttonStyle(.plain)
        .focused($focused)
        .disabled(running)
        .modifier(CommandShortcut(key: key))
        .onHover { hover = $0 }
        .accessibilityLabel(shownDetail.isEmpty ? title : "\(title), \(shownDetail)")
    }
}

struct Panel: View {
    @ObservedObject var m: Model
    private enum Confirm { case approve, dismiss }
    @State private var confirm: Confirm?
    private var working: Bool { m.s.state == "running" || m.busy }

    private func groupLabel(_ t: String) -> some View {
        Text(t).font(.klMeta).foregroundStyle(.tertiary)
            .padding(.horizontal, 12).padding(.top, 6).padding(.bottom, 1)
            .accessibilityAddTraits(.isHeader)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // header
            HStack(spacing: 7) {
                Image(nsImage: kLogo).foregroundStyle(.primary)
                Text("Plasmie").font(.klHeading)
                Spacer()
                StatusPill(state: m.s.state, reason: m.s.reason)
            }
            .padding(.horizontal, 12).padding(.top, 11).padding(.bottom, 9)

            // live "what's happening" line — the running step's heartbeat
            if !m.s.activity.isEmpty {
                HStack(spacing: 7) {
                    if working {
                        ProgressView().controlSize(.small).scaleEffect(0.8).frame(width: 14)
                    } else {
                        Image(systemName: "checkmark.circle.fill").foregroundStyle(.green).frame(width: 14)
                    }
                    Text(m.s.activity).font(.klLabel).foregroundStyle(working ? .primary : .secondary)
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 12).padding(.bottom, 9)
            }

            if !m.obsidian {
                banner("Obsidian required to view the vault", symbol: "exclamationmark.triangle.fill", tint: .orange) {
                    openExternal("https://obsidian.md")
                }
            }

            // held-for-review: a contextual alert, only when something is held
            if m.s.pending > 0 { held }

            // ask-anything — not an inline field; opens the Knowledge spotlight overlay
            Divider().padding(.horizontal, 12)
            Button { OverlayController.shared.toggle() } label: {
                HStack(spacing: 7) {
                    Image(systemName: "sparkle.magnifyingglass").foregroundStyle(.secondary)
                    Text("Ask anything in the vault…").font(.klLabel).foregroundStyle(.secondary)
                    Spacer(minLength: 0)
                    Text("⌃⌥⌘K").font(.klMeta.weight(.medium))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(.quaternary, in: RoundedRectangle(cornerRadius: 5))
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Ask your vault")
            .help("Open the Knowledge spotlight to ask anything in your vault (⌃⌥⌘K)")
            .padding(.horizontal, 12).padding(.vertical, 9)

            Divider().padding(.horizontal, 12)

            // stats + recent
            VStack(alignment: .leading, spacing: 5) {
                Label("\(m.s.notes) notes in vault", systemImage: "doc.text")
                    .font(.klLabel).foregroundStyle(.secondary)
                ForEach(m.s.recent.prefix(3), id: \.self) { line in
                    Text(line).font(.klMono).foregroundStyle(.tertiary)
                        .lineLimit(1).truncationMode(.middle)
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 9)

            Divider().padding(.horizontal, 12)

            // actions, in chunks of <= 4
            VStack(alignment: .leading, spacing: 1) {
                groupLabel("Run")
                ActionRow(title: "Ingest now", symbol: "tray.and.arrow.down",
                          detail: "Capture latest Slack & sessions · hourly", key: "i",
                          running: m.runningJobs.contains("Ingest")) { m.kick("com.plasmie.dev-ingest", "Ingest") }
                ActionRow(title: "Promote now", symbol: "arrow.triangle.2.circlepath",
                          detail: "Find new knowledge & auto-file it · nightly", key: "p",
                          running: m.runningJobs.contains("Promote")) { m.kick("com.plasmie.dev-promote", "Promote") }

                groupLabel("Open").padding(.top, 4)
                ActionRow(title: "Vault in Obsidian", symbol: "folder", key: "o") { openInObsidian(m.s.vault) }
                if !m.s.journal.isEmpty {
                    ActionRow(title: "Today's raw log", symbol: "book.closed") { openInObsidian(m.s.journal) }
                }
                ActionRow(title: "Activity log", symbol: "doc.plaintext") { openExternal("\(m.s.loop)/feed.log") }

                groupLabel("Maintain").padding(.top, 4)
                ActionRow(title: "Reindex check", symbol: "magnifyingglass",
                          detail: "Rebuild catalog & flag dead links · changes nothing") { m.reindexCheck() }
                ActionRow(title: "Settings", symbol: "gearshape", key: ",") { SettingsController.shared.show() }
            }
            .padding(.horizontal, 6).padding(.vertical, 4)

            // transient note + captured output
            if !m.note.isEmpty || !m.output.isEmpty {
                Divider().padding(.horizontal, 12)
                VStack(alignment: .leading, spacing: 5) {
                    if !m.note.isEmpty {
                        HStack(spacing: 6) {
                            if m.busy { ProgressView().controlSize(.small) }
                            Text(m.note).klNote()
                            Spacer()
                            if !m.output.isEmpty {
                                Button("Clear") { m.output = ""; m.note = "" }
                                    .buttonStyle(.plain).font(.klMeta).foregroundStyle(.blue)
                            }
                        }
                    }
                    if !m.output.isEmpty {
                        Text(m.output)
                            .font(.klMono)
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
            ActionRow(title: "Quit Plasmie", symbol: "power", key: "q", compact: true) { NSApp.terminate(nil) }
                .padding(.horizontal, 6).padding(.vertical, 3)
        }
        .frame(width: 320)
        // ⌘R: refresh has no row (status auto-refreshes every 60s) but keeps its shortcut.
        .background(Button("Refresh") { m.refresh() }.keyboardShortcut("r", modifiers: .command)
            .opacity(0).frame(width: 0, height: 0).accessibilityHidden(true))
    }

    private var held: some View {
        VStack(alignment: .leading, spacing: 7) {
            Label("\(m.s.pendingItems) held for review", systemImage: "tray.full.fill")
                .font(.klHeading).foregroundStyle(.orange)
            if let c = confirm {
                Text(c == .approve ? "File all \(m.s.pendingItems) as suggested? This can't be undone."
                                   : "Discard \(m.s.pendingItems) held items without filing? This can't be undone.")
                    .klNote()
                HStack(spacing: 8) {
                    Button("Cancel") { confirm = nil }
                    Button(c == .approve ? "Approve all" : "Dismiss") {
                        if c == .approve { m.approveHeld() } else { m.dismissHeld() }
                        confirm = nil
                    }
                    .tint(c == .approve ? .orange : .red)
                }
                .controlSize(.small).buttonStyle(.bordered)
            } else {
                Text("Auto-apply was unsure — approve, edit, or dismiss.").klNote()
                HStack(spacing: 8) {
                    Button { openInObsidian(m.s.pendingFile) } label: { Label("Review", systemImage: "pencil") }
                        .help("Open the held items in Obsidian to inspect or change their action before applying.")
                    Button { confirm = .approve } label: { Label("Approve all", systemImage: "checkmark.circle.fill") }
                        .tint(.orange)
                        .help("File all held items using the suggested merge/create, then clear them.")
                    Button { confirm = .dismiss } label: { Label("Dismiss", systemImage: "xmark.circle") }
                        .help("Discard the held items without filing anything.")
                }
                .controlSize(.small).buttonStyle(.bordered)
            }
        }
        .padding(.horizontal, 12).padding(.bottom, 9)
    }

    @ViewBuilder func banner(_ text: String, symbol: String, tint: Color, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 7) {
                Image(systemName: symbol).foregroundStyle(tint)
                Text(text).font(.klMeta).foregroundStyle(.primary)
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
