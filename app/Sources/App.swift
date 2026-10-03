import AppKit
import Carbon.HIToolbox
import Foundation
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let overlay = OverlayController.shared
    private var hotKey: HotKey?
    func applicationDidFinishLaunching(_ notification: Notification) {
        NotchController.shared.start(model: .shared)   // here, not on the menu-bar label: that is hidden while the notch is on
        ICloudSync.shared.start()                       // off unless turned on in the Plasmie window
        LoginItem.seedOnce()                            // come back after a restart
        hotKey = HotKey { [weak self] in self?.overlay.toggle() }
        // `open -a "Plasmie" --args --settings` opens straight to the
        // connectors page. Only honoured on a cold start — macOS does not deliver
        // args to an already-running app, which is fine: the menu has Settings.
        if CommandLine.arguments.contains("--settings") {
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
    @ObservedObject private var m = Model.shared

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
        MenuBarExtra(isInserted: Binding(get: { !m.notchOn }, set: { UserDefaults.standard.set(!$0, forKey: NotchPrefs.key) })) {
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
