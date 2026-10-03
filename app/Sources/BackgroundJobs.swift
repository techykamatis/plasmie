import Foundation
import ServiceManagement

/// Plasmie's five background jobs, owned by the app (goal item 5): registered with
/// SMAppService.agent from Contents/Library/LaunchAgents (made by make-app.sh). They show
/// in System Settings › General › Login Items as Plasmie, survive a restart, run the bundled
/// engine, and stop when the app is deleted.
enum BackgroundJobs {
    static let names = ["ingest", "summarize", "improve", "promote", "snapshot"]
    static func label(_ name: String) -> String { "com.plasmie.\(name)" }
    private static let registeredKey = "plasmie.jobsRegisteredBuild"
    private static func service(_ name: String) -> SMAppService { .agent(plistName: "com.plasmie.\(name).plist") }

    /// Older installs ran com.plasmie.* jobs from ~/Library/LaunchAgents, and Plasmie (the old
    /// bundle id) registered com.plasmie.* that this app can't unregister. Both sets at once
    /// would run ingest twice (it appends), so nothing registers while one is still there;
    /// plasmie-migrate.py retires them first (steps 3 and 4).
    static var legacyPresent: Bool {
        let dir = "\(NSHomeDirectory())/Library/LaunchAgents"
        let files = (try? FileManager.default.contentsOfDirectory(atPath: dir)) ?? []
        return files.contains { $0.hasPrefix("com.plasmie.dev-") || $0.hasPrefix("com.plasmie.mlx-") }
            || plasmieJobsLoaded
    }

    /// Any of Plasmie's com.plasmie.* jobs still loaded in this login session.
    static var plasmieJobsLoaded: Bool {
        names.contains { launchctlStatus(["print", "gui/\(getuid())/com.plasmie.\($0)"]) == 0 }
    }

    private static func launchctlStatus(_ args: [String]) -> Int32 {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        p.arguments = args
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return -1 }
        p.waitUntilExit()
        return p.terminationStatus
    }

    /// macOS asks the user to allow background items the first time (Login Items).
    static var needsApproval: Bool { names.contains { service($0).status == .requiresApproval } }
    static var allEnabled: Bool { names.allSatisfy { service($0).status == .enabled } }

    /// Idempotent: registers whatever isn't yet. Returns the names that failed.
    @discardableResult
    static func ensure() -> [String] {
        guard backendReady(), !legacyPresent else { return [] }
        // launchd keeps the definitions it registered: after an update whose job plists
        // changed, re-register so the new schedule/limits apply.
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? ""
        if UserDefaults.standard.string(forKey: registeredKey) != build {
            unregisterAll()
            UserDefaults.standard.set(build, forKey: registeredKey)
        }
        var failed: [String] = []
        for n in names where service(n).status != .enabled && service(n).status != .requiresApproval {
            do { try service(n).register() } catch {
                NSLog("Plasmie: couldn't register %@: %@", n, error.localizedDescription)
                failed.append(n)
            }
        }
        return failed
    }

    static func unregisterAll() {
        for n in names { try? service(n).unregister() }
    }

    static func openLoginItems() { SMAppService.openSystemSettingsLoginItems() }
}
