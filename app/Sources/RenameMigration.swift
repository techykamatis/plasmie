import Foundation

/// Carries an install over from the app's earlier names (Brand.previous: Plasmie, then
/// Plasmie; ADRs 0027 and 0028). Each rename changed the bundle id and the data/log folder
/// names, so this runs at launch, before anything reads a path or a preference
/// (PlasmieApp.init).
///
/// Lossless and idempotent:
/// - Folders: the newest earlier name's folder is renamed to the current one, only when
///   the current one doesn't exist yet (same volume, so the move is atomic). Once it
///   exists, every other old folder is left alone and logged: never merge, never overwrite.
/// - `plasmie.*` preferences are copied once (marker) from the earlier bundle ids, newest
///   first, never over a value the current domain already has; per-build keys stay behind
///   so the new bundle's jobs register afresh.
///
/// Foundation only, plus Brand, so a test can compile it on its own (test_rename_migration.py).
enum RenameMigration {
    static let defaultsMarker = "plasmie.migratedDefaults"
    static let notCopied: Set<String> = ["plasmie.jobsRegisteredBuild", defaultsMarker]

    /// Earlier names and bundle ids, newest first (the order they are tried in).
    static var previousNames: [String] { Brand.previous.reversed().map(\.name) }
    static var previousDomains: [String] { Brand.previous.reversed().map(\.bundleID) }

    static func appSupport(_ name: String) -> String { "\(NSHomeDirectory())/Library/Application Support/\(name)" }
    static func logsFolder(_ name: String) -> String { "\(NSHomeDirectory())/Library/Logs/\(name)" }

    enum Outcome: String { case moved, nothingToMove, alreadyMoved, bothExist, failed }

    static func run(home: String, logs: String, defaults: UserDefaults = .standard) {
        for r in adopt(olds: previousNames.map(appSupport), into: home)
            + adopt(olds: previousNames.map(logsFolder), into: logs)
        where r.outcome != .nothingToMove && r.outcome != .alreadyMoved {
            NSLog("\(Brand.name): rename migration %@ -> %@: %@", r.old, r.new, r.outcome.rawValue)
        }
        copyDefaults(into: defaults)
    }

    /// Walks the old folders (newest first) into `new`: the first one present moves; once
    /// `new` exists, any other old folder reports bothExist and is never touched.
    static func adopt(olds: [String], into new: String) -> [(old: String, new: String, outcome: Outcome)] {
        olds.map { ($0, new, moveFolder(from: $0, to: new)) }
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
                NSLog("\(Brand.name): couldn't move %@: %@", old, error.localizedDescription)
                return .failed
            }
        }
    }

    /// The `plasmie.*` keys to copy from the old domains (newest first) that the current
    /// domain doesn't have yet: a newer domain's value wins over an older one's.
    static func defaultsToCopy(olds: [[String: Any]], existing: [String: Any]) -> [String: Any] {
        var out: [String: Any] = [:]
        for old in olds {
            for (k, v) in old where k.hasPrefix("plasmie.") && !notCopied.contains(k)
                && existing[k] == nil && out[k] == nil {
                out[k] = v
            }
        }
        return out
    }

    static func copyDefaults(into d: UserDefaults) {
        guard !d.bool(forKey: defaultsMarker) else { return }
        let olds = previousDomains.map { d.persistentDomain(forName: $0) ?? [:] }
        let existing = Bundle.main.bundleIdentifier.flatMap { d.persistentDomain(forName: $0) } ?? [:]
        for (k, v) in defaultsToCopy(olds: olds, existing: existing) { d.set(v, forKey: k) }
        d.set(true, forKey: defaultsMarker)
    }
}
