import AppKit
import Carbon.HIToolbox
import Foundation
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let overlay = OverlayController.shared
    private var hotKey: HotKey?
    func applicationDidFinishLaunching(_ notification: Notification) {
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
