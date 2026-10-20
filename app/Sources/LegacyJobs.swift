import Foundation

/// The background jobs older versions of the app registered (Brand.previous):
/// com.<previous>.*. They belong to other bundle ids, so this app can't
/// unregister them; plasmie-migrate.py boots them out, and BackgroundJobs holds the current
/// set off while any is still loaded (ADR 0024).
///
/// Foundation only, plus Brand, so a test can compile it with a fake launchctl
/// (test_migrate.py).
enum LegacyJobs {
    /// Every label older versions registered for these job names, oldest first.
    static func labels(_ jobs: [String]) -> [String] {
        Brand.previous.flatMap { old in jobs.map { "com.\(old.name.lowercased()).\($0)" } }
    }

    /// True when any label is loaded in this login session (`launchctl print` succeeds
    /// only for a loaded one).
    static func anyLoaded(_ labels: [String], launchctl: String = "/bin/launchctl") -> Bool {
        labels.contains { status(launchctl, ["print", "gui/\(getuid())/\($0)"]) == 0 }
    }

    private static func status(_ tool: String, _ args: [String]) -> Int32 {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: tool)
        p.arguments = args
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return -1 }
        p.waitUntilExit()
        return p.terminationStatus
    }
}
