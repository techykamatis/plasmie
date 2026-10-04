import AppKit

// "Reset Plasmie…": remove the background jobs, data, logs, login item and preferences.
// The vault is never touched (plasmie-reset.sh refuses if it sits inside a folder it would
// delete, and takes a vault restore point first). Then Plasmie quits; opening it again
// starts setup from scratch and adopts the existing vault.
enum ResetPlasmie {
    static func confirmAndRun(vault: String) {
        let alert = NSAlert()
        alert.messageText = "Reset \(Brand.name)?"
        alert.informativeText = """
        This removes \(Brand.name)'s background jobs, settings, logs and trophies, then quits. \
        Your notes are not touched: \((vault as NSString).abbreviatingWithTildeInPath) stays exactly as it is. \
        Open \(Brand.name) again to set it up fresh.
        """
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Reset \(Brand.name)").hasDestructiveAction = true
        alert.addButton(withTitle: "Cancel")
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertFirstButtonReturn else { return }

        BackgroundJobs.unregisterAll()                       // stop the jobs before their data goes
        DispatchQueue.global(qos: .userInitiated).async {
            let out = runCapture("/bin/bash", [PlasmiePaths.script("plasmie-reset.sh"), "--yes"], timeout: 120)
            DispatchQueue.main.async {
                guard out.contains("reset done") else {
                    let fail = NSAlert()
                    fail.messageText = "Reset didn't finish"
                    fail.informativeText = "Nothing in your vault was changed. Details:\n\(out.suffix(400))"
                    fail.runModal()
                    return
                }
                LoginItem.set(false)
                if let id = Bundle.main.bundleIdentifier { UserDefaults.standard.removePersistentDomain(forName: id) }
                // and Plasmie's, or the next launch would copy the old preferences back in
                UserDefaults.standard.removePersistentDomain(forName: RenameMigration.legacyDomain)
                NSApp.terminate(nil)
            }
        }
    }
}
