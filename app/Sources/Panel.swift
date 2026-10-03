import AppKit
import Carbon.HIToolbox
import Foundation
import SwiftUI

struct StatusPill: View {
    let state: String
    var reason: String = ""
    @State private var pulse = false
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
                StatusPill(state: m.s.state, reason: m.s.reason)
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
                    ActionRow(title: "Open today's raw log", symbol: "book.closed",
                              detail: "Today's raw captured activity") { openInObsidian(m.s.journal) }
                }
                ActionRow(title: "Reindex check", symbol: "magnifyingglass",
                          detail: "Rebuild catalog & flag dead links · changes nothing") { m.reindexCheck() }
                ActionRow(title: "Open activity log", symbol: "doc.plaintext",
                          detail: "History of every ingest & promote run") { openExternal("\(m.s.loop)/feed.log") }
                ActionRow(title: "Settings", symbol: "gearshape",
                          detail: "Vault, connector tokens & On/Off switches") { SettingsController.shared.show() }
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

