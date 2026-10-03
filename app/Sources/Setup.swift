import AppKit
import Carbon.HIToolbox
import Foundation
import SwiftUI

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
                HStack {
                    Spacer()
                    Button("Set up connectors") { onDone(); SettingsController.shared.show(firstRun: true) }
                    Button("Done") { onDone() }.keyboardShortcut(.defaultAction)
                }
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

