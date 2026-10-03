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
        case "running": return ("Working…", .blue)
        // Vocabulary matches the connector cards. reason (from plasmie-status.py) says
        // why; without one the pill just says "Needs attention".
        case "error":   return (reason.isEmpty ? "Needs attention" : reason, .red)
        default:        return ("All flowing", .green)
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
        .motion(Motion.glide, value: spec.0)
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
    var inWindow = false                 // inside the Plasmie window: no Settings row (it's beside it)
    @ObservedObject private var icloud = ICloudSync.shared
    @AppStorage(ICloudSync.key) private var icloudOn = false
    @State private var atLogin = LoginItem.isOn
    private enum Confirm { case approve, dismiss }
    @State private var confirm: Confirm?
    @AppStorage(NotchPrefs.key) private var notchOn = true
    private var working: Bool { m.s.state == "running" || m.busy }

    private func groupLabel(_ t: String) -> some View {
        Text(t).font(.klMeta).foregroundStyle(.tertiary)
            .padding(.horizontal, 12).padding(.top, 6).padding(.bottom, 1)
            .accessibilityAddTraits(.isHeader)
    }

    // Two layouts of one column. Order for both: Plasmie (status) → fun fact → anything that
    // needs attention → Ask → actions → logs and audit-type lines last.
    // The menu (notch off) shows only what's needed so it fits any screen; everything else
    // is one click away in the Plasmie window, whose sidebar is the full column.
    /// "0.9.0 (42)" from the bundle (set from ./VERSION at build time).
    static let version: String = {
        let i = Bundle.main.infoDictionary ?? [:]
        let v = i["CFBundleShortVersionString"] as? String ?? "?"
        let b = i["CFBundleVersion"] as? String ?? ""
        return b.isEmpty || b == v ? v : "\(v) (\(b))"
    }()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            hero
            FunFactCard(m: m)
            attention
            askRow
            Divider().padding(.horizontal, 12)
            if inWindow { fullActions } else { menuActions }
            if inWindow { logs }
            Divider().padding(.horizontal, 12)
            ActionRow(title: "Quit Plasmie", symbol: "power", key: "q", compact: true) { NSApp.terminate(nil) }
                .padding(.horizontal, 6).padding(.vertical, 3)
            Text("Plasmie \(Self.version)").font(.klMeta).foregroundStyle(.tertiary)
                .padding(.horizontal, 12).padding(.bottom, 8)
                .textSelection(.enabled)
        }
        .frame(width: 320)
        // ⌘R: refresh has no row (status auto-refreshes every 60s) but keeps its shortcut;
        // it is surfaced as a hint on the panel.
        .help("Status refreshes every minute · ⌘R to refresh now")
        .background(Button("Refresh") { m.refresh() }.keyboardShortcut("r", modifiers: .command)
            .opacity(0).frame(width: 0, height: 0).accessibilityHidden(true))
    }

    // Plasmie is the hero: its shape is the status. Smaller in the menu, where height is scarce.
    private var hero: some View {
        VStack(spacing: 6) {
            InteractivePlasmie(state: m.heroPlasmie, size: inWindow ? 104 : 72, accessory: m.stage?.accessory)
                .frame(maxWidth: .infinity)
                .help("Click to say hi · drag to pet")
                .padding(.top, inWindow ? 16 : 12)
            Text("Plasmie").font(.klTitle)
            stageLine
            StatusPill(state: m.s.state, reason: m.s.reason)
        }
        .frame(maxWidth: .infinity)
        .padding(.bottom, 12)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color.plasmieBody.opacity(0.12)))
        .padding(.horizontal, 8).padding(.top, 8).padding(.bottom, 8)
    }

    // Only present when something is wrong or waiting.
    @ViewBuilder private var attention: some View {
        if !m.obsidian {
            banner("Obsidian required to view the vault", symbol: "exclamationmark.triangle.fill", tint: .orange) {
                openExternal("https://obsidian.md")
            }
        }
        if m.s.state == "error", !m.s.reason.isEmpty {
            banner(m.s.reason, symbol: "exclamationmark.triangle.fill", tint: .red) { SettingsController.shared.show() }
        }
        if m.s.pending > 0 { held }
        if BackgroundJobs.needsApproval {
            banner(NotchRootText.jobsNotice, symbol: "gearshape.fill", tint: .orange) { BackgroundJobs.openLoginItems() }
        }
        if let n = m.s.notice, !n.isEmpty {
            banner(n, symbol: "key.fill", tint: .orange) { openKeychainAccess() }
        }
    }

    // Opens Ask in the notch (the floating panel when the notch is off).
    private var askRow: some View {
        VStack(spacing: 0) {
            Divider().padding(.horizontal, 12)
            Button { OverlayController.shared.toggle() } label: {
                HStack(spacing: 7) {
                    Image(systemName: "sparkle.magnifyingglass").foregroundStyle(.secondary)
                    Text("Ask your vault").font(.klLabel).foregroundStyle(.secondary)
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
            .help("Ask anything in your vault (⌃⌥⌘K)")
            .padding(.horizontal, 12).padding(.vertical, 9)
        }
    }

    private var ingestRow: some View {
        ActionRow(title: "Ingest now", symbol: "tray.and.arrow.down",
                  detail: "Capture latest Slack & sessions · hourly", key: "i",
                  running: m.runningJobs.contains("Ingest")) { m.kick(BackgroundJobs.label("ingest"), "Ingest") }
    }

    private var vaultRow: some View {
        ActionRow(title: "Vault in Obsidian", symbol: "folder", key: "o") { openInObsidian(m.s.vault) }
    }

    // The menu: the everyday few, then the door to everything else.
    private var menuActions: some View {
        VStack(alignment: .leading, spacing: 1) {
            ingestRow
            vaultRow
            ActionRow(title: "Open Plasmie…", symbol: "macwindow", detail: "Everything else, logs and settings", key: ",") {
                SettingsController.shared.show()
            }
        }
        .padding(.horizontal, 6).padding(.vertical, 4)
    }

    // The window's sidebar: every action, grouped.
    private var fullActions: some View {
        VStack(alignment: .leading, spacing: 1) {
            groupLabel("Run")
            ingestRow
            ActionRow(title: "Promote now", symbol: "arrow.triangle.2.circlepath",
                      detail: "Find new knowledge & auto-file it · nightly", key: "p",
                      running: m.runningJobs.contains("Promote")) { m.kick(BackgroundJobs.label("promote"), "Promote") }

            groupLabel("Open").padding(.top, 4)
            vaultRow
            if !m.s.journal.isEmpty {
                ActionRow(title: "Today's raw log", symbol: "book.closed") { openInObsidian(m.s.journal) }
            }
            ActionRow(title: "Trophies", symbol: "trophy", key: "t") { TrophiesController.shared.show(m) }

            groupLabel("Sync").padding(.top, 4)
            ActionRow(title: "iCloud sync", symbol: icloudOn ? "icloud.fill" : "icloud",
                      detail: icloudOn ? icloud.line : "Off · mirror your vault to iCloud Drive for Obsidian on iPhone",
                      running: icloud.syncing) { icloud.set(!icloudOn) }
            if icloudOn {
                ActionRow(title: "Sync now", symbol: "arrow.triangle.2.circlepath.icloud", compact: true) { icloud.sync() }
            }

            groupLabel("Maintain").padding(.top, 4)
            ActionRow(title: "Reindex check", symbol: "magnifyingglass",
                      detail: "Rebuild catalog & flag dead links · changes nothing") { m.reindexCheck() }
            ActionRow(title: "Copy diagnostics", symbol: "stethoscope",
                      detail: "A report to send when something's wrong · no notes or secrets") { copyDiagnostics() }
            ActionRow(title: "Run setup again…", symbol: "wrench.and.screwdriver",
                      detail: "Repairs a broken install · keeps your notes and settings") { SetupController.shared.show() }
            ActionRow(title: "Reset Plasmie…", symbol: "arrow.counterclockwise",
                      detail: "Remove jobs, settings and logs · your notes stay") { ResetPlasmie.confirmAndRun(vault: m.s.vault) }
            ActionRow(title: "Show the tour", symbol: "sparkles", detail: "Where Plasmie lives and what it can do") {
                NotchController.shared.startTour()
            }
            ActionRow(title: "Open at login", symbol: "power.circle",
                      detail: LoginItem.needsApproval ? "Waiting for approval in System Settings › Login Items"
                            : atLogin ? "On · Plasmie starts when you log in" : "Off") {
                LoginItem.set(!atLogin); atLogin = LoginItem.isOn
            }
            ActionRow(title: "Plasmie in the notch", symbol: "capsule.tophalf.filled",
                      detail: notchOn ? "On · replaces the menu-bar icon" : "Off · using the menu-bar icon") { notchOn.toggle() }
        }
        .padding(.horizontal, 6).padding(.vertical, 4)
    }

    // Audit-type lines live at the bottom: the live activity line, the last runs, the
    // captured output of an in-app run, and the full activity log.
    private var logs: some View {
        VStack(alignment: .leading, spacing: 0) {
            Divider().padding(.horizontal, 12)
            groupLabel("Log").padding(.top, 4)
            if !m.s.activity.isEmpty {
                HStack(spacing: 7) {
                    if working {
                        ProgressView().controlSize(.small).scaleEffect(0.8).frame(width: 14)
                    } else {
                        Image(systemName: "checkmark.circle.fill").foregroundStyle(.green).frame(width: 14)
                    }
                    Text(m.s.activity).font(.klLabel).foregroundStyle(working ? .primary : .secondary)
                        .lineLimit(2).fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 12).padding(.vertical, 4)
            }
            VStack(alignment: .leading, spacing: 5) {
                Label("\(m.s.notes) notes in vault", systemImage: "doc.text")
                    .font(.klLabel).foregroundStyle(.secondary)
                ForEach(m.s.recent.prefix(3), id: \.self) { line in
                    Text(FeedLine.humanize(line)).font(.klMeta).foregroundStyle(.tertiary)
                        .lineLimit(2).fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 6)
            output
            ActionRow(title: "Full activity log", symbol: "doc.plaintext") { openExternal("\(PlasmiePaths.home)/feed.log") }
                .padding(.horizontal, 6).padding(.bottom, 4)
        }
    }

    /// Runs plasmie-diagnostics.py off the main thread and puts the scrubbed report on the clipboard.
    private func copyDiagnostics() {
        m.note = "Gathering diagnostics…"
        DispatchQueue.global(qos: .userInitiated).async {
            let report = runCapture(PlasmiePaths.python, [PlasmiePaths.script("plasmie-diagnostics.py")])
            DispatchQueue.main.async {
                guard !report.isEmpty else { m.note = "Couldn't gather diagnostics. Try again in a moment."; return }
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(report, forType: .string)
                m.note = "Diagnostics copied. Paste them into a message."
            }
        }
    }

    // Transient note + captured output of an in-app run (Reindex check etc.).
    @ViewBuilder private var output: some View {
        if !m.note.isEmpty || !m.output.isEmpty {
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
            .padding(.horizontal, 12).padding(.vertical, 6)
        }
    }

    /// One quiet line under the name: "Scholar · 19 of 32 trophies", or the new trophy for a few
    /// seconds. A button into the Trophies window.
    @ViewBuilder private var stageLine: some View {
        if let st = m.stage?.name {
            let text = m.celebrating.map { "New trophy: \($0)" } ?? "\(st) · \(m.unlockedCount) of \(m.totalTrophies) trophies"
            Button { TrophiesController.shared.show(m) } label: {
                HStack(spacing: 3) {
                    Text(text).font(.klMeta).foregroundStyle(m.celebrating == nil ? .secondary : .primary)
                        .id(text).transition(.opacity.combined(with: .offset(y: 5)))
                    Image(systemName: "chevron.right").font(.system(size: 9, weight: .semibold)).foregroundStyle(.tertiary)
                }
                .contentShape(Rectangle())
                .motion(m.celebrating == nil ? Motion.glide : Motion.pop, value: text)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(m.celebrating.map { "New trophy: \($0). Open trophies" } ?? "\(text). Open trophies")
        }
    }

    private var held: some View {
        VStack(alignment: .leading, spacing: 7) {
            Label("\(m.s.pendingItems) held for review", systemImage: "tray.full.fill")
                .font(.klHeading).foregroundStyle(.orange)
            if let c = confirm {
                Text(c == .approve ? "Approve all \(m.s.pendingItems) held items? They're filed as suggested."
                                   : "Dismiss \(m.s.pendingItems) held items? Nothing is filed; this can't be undone.")
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

/// Turns a raw feed.log line (pipes already replaced by "·" in plasmie-status.py) into
/// "HH:MM · slack 1 convos / 3 msgs · github 2 · confluence, outlook off".
/// Defensive: any line that doesn't parse is shown as-is.
enum FeedLine {
    static func humanize(_ raw: String) -> String {
        let parts = raw.components(separatedBy: " · ").map { $0.trimmingCharacters(in: .whitespaces) }
        guard parts.count > 1, let time = clock(parts[0]) else { return raw }
        var out: [String] = []
        for seg in parts.dropFirst() where !seg.isEmpty {
            if seg.hasPrefix("exit ") {
                if seg != "exit 0" { out.append(seg) }
            } else if seg.hasPrefix("errors ") {
                if seg != "errors 0" { out.append(seg) }
            } else if seg.hasPrefix("off ") {
                let names = seg.dropFirst(4).split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
                if !names.isEmpty { out.append(names.joined(separator: ", ") + " off") }
            } else if seg.contains(where: \.isNumber), !seg.contains(where: { $0.isNumber && $0 != "0" }) {
                continue   // every count is zero: nothing to report
            } else {
                out.append(seg)
            }
        }
        return ([time] + (out.isEmpty ? ["nothing new"] : out)).joined(separator: " · ")
    }

    /// "2026-10-03 21:07:05" -> "21:07"
    private static func clock(_ s: String) -> String? {
        let f = s.split(separator: " ")
        guard f.count == 2, f[1].count >= 5, f[1].dropFirst(2).first == ":" else { return nil }
        return String(f[1].prefix(5))
    }
}
