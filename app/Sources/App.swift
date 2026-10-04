import AppKit
import Carbon.HIToolbox
import Foundation
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let overlay = OverlayController.shared
    private var hotKey: HotKey?
    func applicationDidFinishLaunching(_ notification: Notification) {
        // `--map`: a map-only viewer (render checks): no migrations, jobs, notch or hotkey.
        if LaunchMode.mapOnly { MapController.shared.show(.shared); return }
        // Data migrations (versioned, idempotent): an upgrade over an older install brings the
        // data along before anything reads it. Cheap when there's nothing to do.
        // (The Plasmie/Plasmie -> Plasmie folder/preferences move already ran, in PlasmieApp.init.)
        if backendReady() {
            DispatchQueue.global(qos: .utility).async {
                _ = runCapture(PlasmiePaths.python, [PlasmiePaths.script("plasmie-migrate.py")], timeout: 600)
                // An earlier name's jobs (com.plasmie.*, com.plasmie.*) can come back (the old app
                // still installed, at login): retire them again, or the new set stays held off
                // (BackgroundJobs.legacyPresent).
                if BackgroundJobs.legacyJobsLoaded {
                    _ = runCapture(PlasmiePaths.python, [PlasmiePaths.script("plasmie-migrate.py"), "--retire-old-jobs"], timeout: 120)
                }
                DispatchQueue.main.async { BackgroundJobs.ensure() }   // after migrations retired any old jobs
            }
        }
        NotchController.shared.start(model: .shared)   // here, not on the menu-bar label: that is hidden while the notch is on
        ICloudSync.shared.start()                       // off unless turned on in the Plasmie window
        hotKey = HotKey { [weak self] in self?.overlay.toggle() }
        // `open -a "Plasmie" --args --settings` opens straight to the
        // connectors page. Only honoured on a cold start — macOS does not deliver
        // args to an already-running app, which is fine: the menu has Settings.
        if CommandLine.arguments.contains("--setup") {
            SetupController.shared.show()
        } else if CommandLine.arguments.contains("--settings") {
            SettingsController.shared.show()
        } else {
            SetupController.shared.showIfNeeded()
        }
    }
    /// Opening Plasmie again (Finder, Spotlight, `open -a Plasmie`) shows the Plasmie window, so
    /// everything stays reachable even with the menu-bar icon hidden.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        SettingsController.shared.show(); return false
    }
}

@main
struct PlasmieApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @ObservedObject private var m: Model

    init() {
        // Plasmie/Plasmie -> Plasmie, first: Model.shared reads the data folder and preferences as soon
        // as it exists, which is before applicationDidFinishLaunching.
        if !LaunchMode.mapOnly { RenameMigration.run(home: PlasmiePaths.home, logs: PlasmiePaths.logs) }
        _m = ObservedObject(wrappedValue: Model.shared)
    }

    private var tint: Color {
        switch m.s.state {
        case "pending": return .orange
        case "error":   return .red
        case "running": return .secondary
        default:        return .primary
        }
    }

    var body: some Scene {
        // the notch replaces the menu-bar icon; turning the notch off brings the icon back
        MenuBarExtra(isInserted: Binding(get: { !m.notchOn && !LaunchMode.mapOnly }, set: { UserDefaults.standard.set(!$0, forKey: NotchPrefs.key) })) {
            Panel(m: m)
        } label: {
            HStack(spacing: 3) {
                Image(nsImage: m.menuImage)          // Plasmie, template glyph; frames swap while busy
                if m.s.pending > 0 { Text("\(m.s.pending)") }
            }
            .foregroundStyle(tint)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(m.s.pending > 0 ? "\(m.plasmie.label), \(m.s.pending) held" : m.plasmie.label)
        }
        .menuBarExtraStyle(.window)
    }
}
