import AppKit
import Carbon.HIToolbox
import Foundation
import SwiftUI

// MARK: - first-run self-install

/// Setup is done once app-setup.sh reaches 100%: it writes `.setup-complete` last.
/// Installs from before that marker existed count once ingest has state (`.loop-state.json`),
/// so updating the app doesn't send a working install back through setup. The answer
/// model is Apple's and managed by macOS, so there is nothing of ours to look for.
func backendReady() -> Bool {
    let fm = FileManager.default
    let home = PlasmiePaths.home
    return fm.isExecutableFile(atPath: "\(home)/venv/bin/python3")
        && (fm.fileExists(atPath: "\(home)/.setup-complete")
            || fm.fileExists(atPath: "\(home)/.loop-state.json"))
}

/// Shows the one-time setup window if the engine isn't installed yet.
final class SetupController {
    static let shared = SetupController()
    private var win: NSWindow?
    func showIfNeeded() {
        guard !backendReady() else { return }
        show()
    }

    /// Also "Run setup again…": idempotent, so it repairs a partial install, adopts the
    /// existing vault, and keeps settings.
    func show() {
        if let w = win { bringForward(w); return }
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 480, height: 300),
                         styleMask: [.titled, .closable], backing: .buffered, defer: false)
        w.title = "Set up Plasmie"
        w.center()
        w.isReleasedWhenClosed = false
        w.level = .floating
        // A hosting controller resizes the window to its content, so a long error grows it.
        w.contentViewController = NSHostingController(rootView: SetupView { [weak self] in self?.win?.orderOut(nil); self?.win = nil })
        w.center()
        win = w
        bringForward(w)
    }
}

/// One prerequisite from `app-setup.sh --check`.
struct SetupCheck: Identifiable, Equatable {
    let id: String
    let ok: Bool
    let required: Bool
    let label: String
    let detail: String

    /// What fixing it looks like: a download page, a settings pane, or Apple's installer.
    var fix: (title: String, run: () -> Void)? {
        switch id {
        case "node":     return ("Download", { openExternal("https://nodejs.org/en/download") })
        case "obsidian": return ("Download", { openExternal("https://obsidian.md/download") })
        case "ai":       return ("Open Settings", { openExternal("x-apple.systempreferences:com.apple.Siri-Settings.extension") })
        case "macos":    return ("Software Update", { openExternal("x-apple.systempreferences:com.apple.Software-Update-Settings.extension") })
        case "clt":      return ("Install", { fireAndForget("/usr/bin/xcode-select", ["--install"]) })
        case "disk":     return ("Storage settings", { openExternal("x-apple.systempreferences:com.apple.settings.Storage") })
        default:         return nil
        }
    }

    static func parse(_ out: String) -> [SetupCheck] {
        out.components(separatedBy: "\n").compactMap { line in
            let f = line.split(separator: ":", maxSplits: 5, omittingEmptySubsequences: false).map(String.init)
            guard f.count == 6, f[0] == "CHECK" else { return nil }
            return SetupCheck(id: f[1], ok: f[2] == "ok", required: f[3] == "required", label: f[4], detail: f[5])
        }
    }
}

/// First run: check prerequisites (with a fix for each one missing), then run the bundled
/// app-setup.sh with friendly progress. The script is idempotent, so "Try again" resumes.
struct SetupView: View {
    let onDone: () -> Void
    private enum Phase { case checking, checklist, vault, choices, installing, done }
    @State private var phase: Phase = .checking
    // A reinstall offers the vault it already knows; a new install, ~/knowledge.
    @State private var vaultPath: String = {
        let v = ConfigStore.read(PlasmiePaths.config)["VAULT_DIR"] ?? ""
        return v.isEmpty ? "\(NSHomeDirectory())/knowledge" : (v as NSString).expandingTildeInPath
    }()
    @State private var openAtLogin = false        // offered, never assumed (owner, 2026-10-04)
    @State private var icloud = false
    @State private var checks: [SetupCheck] = []
    @State private var pct: Double = 0
    @State private var msg = "Preparing…"
    @State private var failed: String?

    private var blocked: Bool { checks.contains { $0.required && !$0.ok } }
    private var res: String { Bundle.main.resourcePath ?? "" }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                InteractivePlasmie(state: phase == .done ? .success : (failed != nil ? .error
                                 : phase == .installing ? .ingest : .idle), size: 72)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(.klTitle)
                    Text(subtitle).klNote()
                }
            }
            switch phase {
            case .checking:
                ProgressView().controlSize(.small)
            case .checklist:
                checklist
            case .vault:
                VaultStep(path: $vaultPath) { _ in phase = .choices }
            case .choices:
                ChoicesStep(openAtLogin: $openAtLogin, icloud: $icloud) { install() }
            case .installing:
                if let f = failed {
                    Text(f).font(.klLabel).foregroundStyle(.red)
                        .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                    HStack {
                        Button("Back to checks") { check() }
                        Spacer()
                        Button("Try again") { install() }.keyboardShortcut(.defaultAction)
                    }
                } else {
                    ProgressView(value: pct, total: 100)
                    Text(msg).font(.klLabel).foregroundStyle(.secondary).lineLimit(1)
                }
            case .done:
                HStack {
                    Spacer()
                    Button("Set up connectors") {
                        onDone(); SettingsController.shared.show(firstRun: true); NotchController.shared.startTour()
                    }
                    Button("Done") { onDone(); NotchController.shared.startTour() }.keyboardShortcut(.defaultAction)
                }
            }
        }
        .padding(20).frame(width: 480, alignment: .topLeading)
        .onAppear { if phase == .checking { check() } }
    }

    private var title: String {
        switch phase {
        case .checking, .checklist, .vault, .choices: return "Hi, I'm Plasmie"
        case .installing: return failed == nil ? "Setting things up" : "Setup hit a snag"
        case .done: return "You're all set"
        }
    }
    private var subtitle: String {
        switch phase {
        case .checking: return "Checking your Mac first…"
        case .checklist: return blocked ? "A few things are needed before I can set up."
                                        : "Your Mac is ready. Setup downloads about 4 GB of search models once; keep working meanwhile."
        case .vault: return "First, where your notes live."
        case .choices: return "Last thing before I set up."
        case .installing: return "One-time setup: search and your notes vault. Answers come from Apple Intelligence, on this Mac."
        case .done: return "Press ⌃⌥⌘K anywhere to ask your notes. I live beside the notch."
        }
    }

    private var checklist: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(checks) { c in
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Image(systemName: c.ok ? "checkmark.circle.fill" : c.required ? "xmark.circle.fill" : "exclamationmark.circle.fill")
                        .foregroundStyle(c.ok ? .green : c.required ? .red : .orange)
                        .accessibilityLabel(c.ok ? "Ready" : c.required ? "Required, missing" : "Recommended, missing")
                    VStack(alignment: .leading, spacing: 1) {
                        HStack(spacing: 6) {
                            Text(c.label).font(.klHeading)
                            if !c.required { Text("Recommended").font(.klMeta).foregroundStyle(.secondary) }
                        }
                        Text(c.detail).klNote()
                    }
                    Spacer(minLength: 8)
                    if !c.ok, let fix = c.fix { Button(fix.title, action: fix.run).controlSize(.small) }
                }
            }
            Divider().padding(.vertical, 2)
            HStack {
                Button("Check again") { check() }
                Spacer()
                Button(blocked ? "Install what's missing first" : "Continue") { phase = .vault }
                    .keyboardShortcut(.defaultAction).disabled(blocked)
            }
        }
    }

    private func check() {
        phase = .checking; failed = nil
        DispatchQueue.global(qos: .userInitiated).async {
            let out = runCapture("/bin/bash", ["\(res)/backend/app-setup.sh", "--check", res])
            let parsed = SetupCheck.parse(out)
            DispatchQueue.main.async {
                checks = parsed.isEmpty
                    ? [SetupCheck(id: "self", ok: false, required: true, label: "Plasmie's setup files",
                                  detail: "Couldn't run the bundled setup check. Reinstall Plasmie from the DMG.")]
                    : parsed
                phase = .checklist
            }
        }
    }

    private func install() {
        phase = .installing; failed = nil; pct = 0; msg = "Preparing…"
        runStreaming("/bin/bash", ["\(res)/backend/app-setup.sh", res, vaultPath],
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
                if failed == nil && pct >= 100 {
                    if openAtLogin { LoginItem.set(true) }                 // the user's choices, now that setup worked
                    if icloud { ICloudSync.shared.set(true) }
                    phase = .done
                }
                else if failed == nil { failed = "Setup ended early. Try again to resume where it stopped." }
            })
    }
}
