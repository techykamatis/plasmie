import ServiceManagement
import SwiftUI

// Launch at login, owned by the app (SMAppService, macOS 13+): it shows up in System
// Settings › General › Login Items as Plasmie, and disappears when the app is deleted.
// Never switched on silently: macOS-level behavior is the user's choice, offered in setup
// ("Your choices") and in the Plasmie window (owner, 2026-10-04).
enum LoginItem {
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
}
