import ServiceManagement
import SwiftUI

// Launch at login, owned by the app (SMAppService, macOS 13+): it shows up in System
// Settings › General › Login Items as Plasmie, and disappears when the app is deleted.
// On by default once, at first launch; the user can turn it off in the Plasmie window.
enum LoginItem {
    private static let seededKey = "plasmie.loginItemSeeded"

    static var isOn: Bool { SMAppService.mainApp.status == .enabled }
    /// Approval pending in System Settings (macOS asks the user the first time).
    static var needsApproval: Bool { SMAppService.mainApp.status == .requiresApproval }

    static func set(_ on: Bool) {
        do {
            if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
        } catch {
            NSLog("Plasmie login item: %@", error.localizedDescription)
        }
    }

    /// First launch only: register, so Plasmie survives a restart without anyone asking.
    static func seedOnce() {
        guard !UserDefaults.standard.bool(forKey: seededKey) else { return }
        UserDefaults.standard.set(true, forKey: seededKey)
        if !isOn { set(true) }
    }
}
