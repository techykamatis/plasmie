import Foundation

/// Plasmie → Plasmie (ADR 0027). The bundle id changed (com.plasmie.legacy → com.plasmie.app)
/// and the data/log folders were renamed, so an existing install is carried over at launch,
/// before anything reads a path or a preference (PlasmieApp.init).
///
/// Lossless and idempotent:
/// - A folder is renamed only when the new one doesn't exist yet (same volume, so the move
///   is atomic). When both exist, neither is touched: never merge, never overwrite.
/// - `plasmie.*` preferences are copied once from the old domain, never over a value the new
///   domain already has; `plasmie.jobsRegisteredBuild` is left behind so the new bundle's jobs
///   register afresh.
///
/// Foundation only, with no app types, so a test can compile it on its own (test_rename_migration.py).
enum RenameMigration {
    static let legacyHome = "\(NSHomeDirectory())/Library/Application Support/Plasmie"
    static let legacyLogs = "\(NSHomeDirectory())/Library/Logs/Plasmie"
    static let legacyDomain = "com.plasmie.legacy"
    static let defaultsMarker = "plasmie.migratedDefaults"
    static let notCopied: Set<String> = ["plasmie.jobsRegisteredBuild", defaultsMarker]

    enum Outcome: String { case moved, nothingToMove, alreadyMoved, bothExist, failed }

    static func run(home: String, logs: String, defaults: UserDefaults = .standard) {
        for (old, new) in [(legacyHome, home), (legacyLogs, logs)] {
            let r = moveFolder(from: old, to: new)
            if r != .nothingToMove && r != .alreadyMoved {
                NSLog("Plasmie: rename migration %@ -> %@: %@", old, new, r.rawValue)
            }
        }
        copyDefaults(into: defaults)
    }

    static func moveFolder(from old: String, to new: String, fm: FileManager = .default) -> Outcome {
        var isDir: ObjCBool = false
        let hasOld = fm.fileExists(atPath: old, isDirectory: &isDir) && isDir.boolValue
        let hasNew = fm.fileExists(atPath: new)
        switch (hasOld, hasNew) {
        case (false, false): return .nothingToMove
        case (false, true):  return .alreadyMoved
        case (true, true):   return .bothExist
        case (true, false):
            do {
                let parent = (new as NSString).deletingLastPathComponent
                try fm.createDirectory(atPath: parent, withIntermediateDirectories: true)
                try fm.moveItem(atPath: old, toPath: new)
                return .moved
            } catch {
                NSLog("Plasmie: couldn't move %@: %@", old, error.localizedDescription)
                return .failed
            }
        }
    }

    /// The old domain's `plasmie.*` keys that the new domain doesn't have yet.
    static func defaultsToCopy(old: [String: Any], existing: [String: Any]) -> [String: Any] {
        old.filter { k, _ in k.hasPrefix("plasmie.") && !notCopied.contains(k) && existing[k] == nil }
    }

    static func copyDefaults(into d: UserDefaults) {
        guard !d.bool(forKey: defaultsMarker) else { return }
        let old = d.persistentDomain(forName: legacyDomain) ?? [:]
        let existing = Bundle.main.bundleIdentifier.flatMap { d.persistentDomain(forName: $0) } ?? [:]
        for (k, v) in defaultsToCopy(old: old, existing: existing) { d.set(v, forKey: k) }
        d.set(true, forKey: defaultsMarker)
    }
}
