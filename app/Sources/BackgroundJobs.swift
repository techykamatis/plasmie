import Foundation
import ServiceManagement

/// Plasmie's five background jobs, owned by the app (goal item 5): registered with
/// SMAppService.agent from Contents/Library/LaunchAgents (made by make-app.sh). They show
/// in System Settings › General › Login Items as Plasmie, survive a restart, run the bundled
/// engine, and stop when the app is deleted.
enum BackgroundJobs {
    static let names = ["ingest", "summarize", "improve", "promote", "snapshot"]
    static func label(_ name: String) -> String { "com.\(Brand.id).\(name)" }
    private static func service(_ name: String) -> SMAppService { .agent(plistName: "com.\(Brand.id).\(name).plist") }

    /// Older installs ran com.plasmie.* jobs from ~/Library/LaunchAgents, and the app under its
    /// earlier names (Plasmie, Plasmie: other bundle ids) registered com.plasmie.* / com.plasmie.*
    /// that this app can't unregister. Two sets at once would run ingest twice (it appends),
    /// so nothing registers while one is still there; plasmie-migrate.py retires them first
    /// (steps 3, 4 and 6).
    static var legacyPresent: Bool {
        let dir = "\(NSHomeDirectory())/Library/LaunchAgents"
        let files = (try? FileManager.default.contentsOfDirectory(atPath: dir)) ?? []
        return files.contains { $0.hasPrefix("com.plasmie.dev-") || $0.hasPrefix("com.plasmie.mlx-") }
            || legacyJobsLoaded
    }

    /// Any earlier name's job (com.plasmie.*, com.plasmie.*) still loaded in this login session.
    static var legacyJobsLoaded: Bool { LegacyJobs.anyLoaded(LegacyJobs.labels(names)) }

    /// macOS asks the user to allow background items the first time (Login Items).
    static var needsApproval: Bool { names.contains { service($0).status == .requiresApproval } }
    static var allEnabled: Bool { names.allSatisfy { service($0).status == .enabled } }

    /// Idempotent: registers whatever isn't yet. Returns the names that failed.
    @discardableResult
    static func ensure() -> [String] {
        guard backendReady(), !legacyPresent else { return [] }
        // Never unregister-then-register in one go: on 2026-10-04 that left all five jobs
        // "partial import" with armed calendar triggers that never fired (they still ran
        // when kickstarted). A plain register() on each launch is the documented path.
        // ponytail: if an update ever changes a job's schedule and macOS keeps the old
        // one, unregister in one launch and register in the next.
        var failed: [String] = []
        for n in names where service(n).status != .enabled && service(n).status != .requiresApproval {
            do { try service(n).register() } catch {
                NSLog("\(Brand.name): couldn't register %@: %@", n, error.localizedDescription)
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
