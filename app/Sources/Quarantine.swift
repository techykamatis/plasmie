import AppKit
import Darwin

/// Plasmie is ad-hoc signed (no Developer ID, no notarization), so the one Gatekeeper prompt
/// it can't avoid is the first "Open Anyway" for the app itself. Everything after that is ours
/// to keep quiet:
///
/// - A download marks every file in the bundle with `com.apple.quarantine`, and approving the
///   app does not clear it from the nested programs. The first time the app spawned its bundled
///   Python, Gatekeeper judged python3.12 on its own: "python3.12 Not Opened", then setup's
///   "bundled Python runtime is broken". Once the app is running, the person has already
///   approved it, so it clears the flag from its own bundle before running anything inside.
/// - Opened straight from the disk image (or from Downloads without being moved), macOS runs a
///   read-only, randomised copy ("app translocation"): nothing can be cleared, and the
///   background jobs would point at a path that disappears. Plasmie offers to move itself to
///   Applications and reopen from there.
enum Quarantine {
    static let attr = "com.apple.quarantine"
    static var bundleURL: URL { Bundle.main.bundleURL }

    /// Running from a translocated copy or a read-only volume (the mounted DMG).
    static let mustMove: Bool = {
        if bundleURL.path.contains("/AppTranslocation/") { return true }
        let ro = try? bundleURL.resourceValues(forKeys: [.volumeIsReadOnlyKey]).volumeIsReadOnly
        return ro == true
    }()

    private static func hasFlag(_ path: String) -> Bool {
        getxattr(path, attr, nil, 0, 0, XATTR_NOFOLLOW) >= 0
    }

    /// Removes the quarantine flag from every file in `root` (symlinks themselves, never their
    /// targets). Returns how many files still carry it. Cheap when there's nothing to do: the
    /// walk only runs if the bundle or its Python is still flagged.
    @discardableResult
    static func clear(_ root: URL) -> Int {
        let base = root.path
        let python = base + "/Contents/Resources/python/bin/python3.12"
        guard hasFlag(base) || hasFlag(python) else { return 0 }
        var left = 0
        func strip(_ p: String) {
            if removexattr(p, attr, XATTR_NOFOLLOW) != 0 && errno != ENOATTR { left += 1 }
        }
        strip(base)
        if let e = FileManager.default.enumerator(atPath: base) {
            for case let rel as String in e { strip(base + "/" + rel) }
        }
        return left
    }

    /// At launch, before anything in the bundle runs.
    static func clearOwnBundle() {
        guard !mustMove else { return }
        let left = clear(bundleURL)
        if left > 0 { NSLog("\(Brand.name): \(left) file(s) in the app are still quarantined") }
    }

    /// Asks to move to /Applications and relaunch from there. Returns true when this instance
    /// is on its way out (moved and relaunching, or the person chose Quit).
    static func offerMoveIfNeeded() -> Bool {
        guard mustMove else { return false }
        NSApp.activate(ignoringOtherApps: true)
        let a = NSAlert()
        a.messageText = "Move \(Brand.name) to Applications?"
        a.informativeText = "\(Brand.name) is running from the disk image or Downloads, where it can't set itself up. It will copy itself into your Applications folder and reopen from there."
        a.addButton(withTitle: "Move to Applications")
        a.addButton(withTitle: "Quit")
        guard a.runModal() == .alertFirstButtonReturn else { NSApp.terminate(nil); return true }
        do {
            let dest = try moveToApplications()
            NSWorkspace.shared.openApplication(at: dest, configuration: .init()) { _, _ in
                DispatchQueue.main.async { NSApp.terminate(nil) }
            }
        } catch {
            let f = NSAlert()
            f.messageText = "\(Brand.name) couldn't move itself"
            f.informativeText = "Drag \(Brand.name) from the disk image into your Applications folder, then open it from there.\n\n(\(error.localizedDescription))"
            f.runModal()
            NSApp.terminate(nil)
        }
        return true
    }

    private static func moveToApplications() throws -> URL {
        let fm = FileManager.default
        let dest = URL(fileURLWithPath: "/Applications/\(Brand.name).app")
        // an older copy already there: quit it, then put it in the Bin (recoverable)
        if fm.fileExists(atPath: dest.path) {
            let me = ProcessInfo.processInfo.processIdentifier
            for app in NSRunningApplication.runningApplications(withBundleIdentifier: Bundle.main.bundleIdentifier ?? "")
            where app.processIdentifier != me { app.terminate() }
            try fm.trashItem(at: dest, resultingItemURL: nil)
        }
        try fm.copyItem(at: bundleURL, to: dest)
        clear(dest)   // the copy is ours and already approved: it reopens with no prompt at all
        return dest
    }
}
