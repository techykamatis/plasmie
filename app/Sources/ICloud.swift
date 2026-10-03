import Foundation
import SwiftUI

// iCloud sync: mirror the vault to iCloud Drive (plasmie-icloud.py) so it reads in Obsidian on
// iPhone, iPad and other Macs. The APP runs it, not a launchd job: macOS grants iCloud
// Drive access to the app (one prompt), and its child processes inherit it; background
// jobs can't get that permission. Off by default; the vault on this Mac stays the source
// of truth, and edits made in the iCloud copy are kept, never overwritten.

final class ICloudSync: ObservableObject {
    static let shared = ICloudSync()
    static let key = "plasmie.icloud"
    static let every: TimeInterval = 30 * 60

    @Published private(set) var line = ""          // "Synced 2 min ago" / what went wrong
    @Published private(set) var syncing = false
    private var timer: Timer?

    var isOn: Bool { UserDefaults.standard.bool(forKey: Self.key) }

    func start() {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: Self.every, repeats: true) { [weak self] _ in self?.syncIfOn() }
        refreshLine()
        syncIfOn()
    }

    func set(_ on: Bool) {
        UserDefaults.standard.set(on, forKey: Self.key)
        if on { sync() } else { line = "Off" }
    }

    func syncIfOn() { if isOn { sync() } }

    func sync() {
        guard isOn, !syncing else { return }             // uploading is the user's call, never implicit
        syncing = true; line = "Syncing to iCloud Drive…"
        DispatchQueue.global(qos: .utility).async {
            let out = runCapture(PlasmiePaths.python, [PlasmiePaths.script("plasmie-icloud.py"), "sync", "--user-enabled"])
            DispatchQueue.main.async { self.syncing = false; self.line = Self.describe(out) }
        }
    }

    private func refreshLine() {
        guard isOn else { line = "Off"; return }
        DispatchQueue.global(qos: .utility).async {
            let out = runCapture(PlasmiePaths.python, [PlasmiePaths.script("plasmie-icloud.py"), "status"])
            DispatchQueue.main.async { self.line = Self.describe(out) }
        }
    }

    /// The script's JSON as one plain sentence.
    static func describe(_ json: String) -> String {
        guard let d = json.data(using: .utf8),
              let r = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else {
            return "Couldn't reach iCloud Drive. Is it on in System Settings › Apple Account › iCloud?"
        }
        if r["never"] as? Bool == true { return "Not synced yet" }
        if r["ok"] as? Bool == false {
            let err = r["error"] as? String ?? ""
            return err.contains("not permitted") || err.contains("Permission")
                ? "Plasmie needs access to iCloud Drive: allow it when macOS asks, or in System Settings › Privacy & Security › Files and Folders."
                : (err.isEmpty ? "iCloud sync failed. Copy diagnostics and send them over." : err)
        }
        let kept = (r["kept_edits"] as? [Any])?.count ?? 0
        let held = (r["held_back"] as? [Any])?.count ?? 0
        let heldNote = held > 0 ? " · \(held) note\(held == 1 ? "" : "s") kept off iCloud (looked like a secret)" : ""
        let when = (r["at"] as? String).flatMap { ISO8601DateFormatter.local.date(from: $0) }
            .map { RelativeDateTimeFormatter().localizedString(for: $0, relativeTo: Date()) } ?? "just now"
        return kept > 0
            ? "Synced \(when) · \(kept) note\(kept == 1 ? "" : "s") edited in iCloud kept beside the fresh copy"
            : "Synced \(when) · \(r["files"] as? Int ?? 0) files in iCloud Drive › Plasmie\(heldNote)"
    }
}

private extension ISO8601DateFormatter {
    /// plasmie-icloud writes local time without a zone ("2026-10-04T00:42:10").
    static let local: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withFullDate, .withTime, .withColonSeparatorInTime, .withDashSeparatorInDate]
        f.timeZone = .current
        return f
    }()
}
