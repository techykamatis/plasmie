import Foundation

/// Carries an install over from the app's earlier names (Brand.previous, oldest first;
/// ADR 0023). Each rename changed the bundle id and the data/log folder
/// names, and the internal prefixes changed too, so this runs at launch, before anything reads a
/// path, a preference or an env var (PlasmieApp.init).
///
/// Lossless and idempotent:
/// - Folders: the newest earlier name's folder is renamed to the current one, only when
///   the current one doesn't exist yet (same volume, so the move is atomic). Once it
///   exists, every other old folder is left alone and logged: never merge, never overwrite.
/// - Preferences: keys under the old `<old>.` prefix in this app's own domain move to
///   `plasmie.` (a value already under the new key wins), then, once (marker), keys are
///   copied from the earlier bundle ids, newest first, under their new names and never over
///   a value the current domain already has; per-build keys stay behind so the new
///   bundle's jobs register afresh.
/// - Environment: a variable still spelled with an old prefix is copied to its PLASMIE_
///   name (for one release; the twins are paths.adopt_old_env and plasmie-env.sh).
///
/// Every old name and prefix here is assembled from parts (or comes from Brand.previous):
/// the old-names scan (test_old_names.py) fails on one written out anywhere.
/// Foundation only, plus Brand, so a test can compile it on its own (test_rename_migration.py).
enum RenameMigration {
    /// The defaults keys' prefix, now and in older installs (ADR 0023).
    static let defaultsPrefix = "plasmie."
    static let oldDefaultsPrefix = "kl" + "oop."
    static let defaultsMarker = defaultsPrefix + "migratedDefaults"
    static let notCopied: Set<String> = [defaultsPrefix + "jobsRegisteredBuild", defaultsMarker]
    /// Env vars and config.env keys used to start with one of these; now with PLASMIE_.
    static let oldEnvPrefixes = ["KL" + "OOP_", "KL" + "_"]
    static let envPrefix = "PLASMIE_"

    /// Earlier names and bundle ids, newest first (the order they are tried in).
    static var previousNames: [String] { Brand.previous.reversed().map(\.name) }
    static var previousDomains: [String] { Brand.previous.reversed().map(\.bundleID) }

    // MARK: env vars and config.env keys

    /// The PLASMIE_ name for a variable or config key spelled the old way, else nil.
    static func renamedKey(_ k: String) -> String? {
        for p in oldEnvPrefixes where k.hasPrefix(p) && k.count > p.count {
            return envPrefix + k.dropFirst(p.count)
        }
        return nil
    }

    /// `cfg` with every old-prefixed key under its new name; a key already present under the
    /// new name keeps its value. Lets a config.env that plasmie-migrate.py (step 8) hasn't
    /// rewritten yet still be read (ConfigStore.read). Fallback for one release.
    static func withNewNames(_ cfg: [String: String]) -> [String: String] {
        var out = cfg.filter { renamedKey($0.key) == nil }
        for (k, v) in cfg { if let n = renamedKey(k), out[n] == nil { out[n] = v } }
        return out
    }

    /// The variables to set so every old-prefixed one is also under its new name (never
    /// over one that is set already).
    static func oldEnvironment(_ env: [String: String]) -> [String: String] {
        var out: [String: String] = [:]
        for (k, v) in env { if let n = renamedKey(k), env[n] == nil, out[n] == nil { out[n] = v } }
        return out
    }

    /// Before anything reads an env var or spawns a script (which inherits them).
    /// Fallback for one release (ADR 0023).
    static func adoptOldEnvironment() {
        for (k, v) in oldEnvironment(ProcessInfo.processInfo.environment) { setenv(k, v, 0) }
    }

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

    // MARK: preferences

    /// `plasmie.x` for an old-prefixed defaults key, else nil.
    static func newDefaultsKey(_ k: String) -> String? {
        k.hasPrefix(oldDefaultsPrefix) && k.count > oldDefaultsPrefix.count
            ? defaultsPrefix + k.dropFirst(oldDefaultsPrefix.count) : nil
    }

    /// This app's own domain: which new keys to set and which old keys to remove. A value
    /// already under the new key wins; the old key is removed only once its value is under
    /// the new one, so nothing is lost if the app quits half way.
    static func defaultsToRename(_ domain: [String: Any]) -> (set: [String: Any], remove: [String]) {
        var set: [String: Any] = [:], remove: [String] = []
        for (k, v) in domain {
            guard let n = newDefaultsKey(k) else { continue }
            if domain[n] == nil { set[n] = v }
            remove.append(k)
        }
        return (set, remove.sorted())
    }

    static func renameOwnDefaults(_ d: UserDefaults) {
        guard let id = Bundle.main.bundleIdentifier, let domain = d.persistentDomain(forName: id) else { return }
        let (set, remove) = defaultsToRename(domain)
        for (k, v) in set { d.set(v, forKey: k) }
        if !remove.isEmpty, set.keys.allSatisfy({ d.object(forKey: $0) != nil }) {
            for k in remove { d.removeObject(forKey: k) }
        }
    }

    /// The keys to copy from the old domains (newest first), under their new names, that the
    /// current domain doesn't have yet: a newer domain's value wins over an older one's.
    static func defaultsToCopy(olds: [[String: Any]], existing: [String: Any]) -> [String: Any] {
        var out: [String: Any] = [:]
        for old in olds {
            for (k, v) in old {
                guard let n = newDefaultsKey(k) ?? (k.hasPrefix(defaultsPrefix) ? k : nil),
                      !notCopied.contains(n), existing[n] == nil, out[n] == nil else { continue }
                out[n] = v
            }
        }
        return out
    }

    static func copyDefaults(into d: UserDefaults) {
        renameOwnDefaults(d)                                  // the old marker becomes the new one
        guard !d.bool(forKey: defaultsMarker) else { return }
        let olds = previousDomains.map { d.persistentDomain(forName: $0) ?? [:] }
        let existing = Bundle.main.bundleIdentifier.flatMap { d.persistentDomain(forName: $0) } ?? [:]
        for (k, v) in defaultsToCopy(olds: olds, existing: existing) { d.set(v, forKey: k) }
        d.set(true, forKey: defaultsMarker)
    }
}
