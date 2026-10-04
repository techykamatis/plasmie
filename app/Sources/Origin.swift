import AppKit
import SwiftUI

// A hidden easter egg (ADR 0028): where the name comes from, in the mascot's own voice.
// Only for people who go looking: in the app window, click the small version line at the
// very bottom of the sidebar five times in a row. No hint anywhere says so. Opening it
// writes $PLASMIE_HOME/.found-origin (the date, once), which unlocks the secret
// "Origin Story" trophy (plasmie-achievements.py), celebrated like any other.

/// Counts quick clicks on the version line; the fifth in a row opens the card.
struct OriginEgg {
    static let clicksNeeded = 5
    static let maxGap: TimeInterval = 1.5          // a slower click starts the count again
    private(set) var count = 0
    private var last = Date.distantPast

    /// Registers one click; true when this one completes the sequence (the count restarts).
    mutating func click(at now: Date = Date()) -> Bool {
        count = now.timeIntervalSince(last) <= Self.maxGap ? count + 1 : 1
        last = now
        guard count >= Self.clicksNeeded else { return false }
        count = 0
        return true
    }

    static let markerPath = "\(PlasmiePaths.home)/.found-origin"

    /// Writes the marker (the date it was first found; never rewritten) and re-reads the
    /// trophies at once, so the unlock is celebrated now instead of on the next refresh.
    static func found(_ m: Model) {
        let fm = FileManager.default
        if !fm.fileExists(atPath: markerPath) {
            let f = DateFormatter()
            f.locale = Locale(identifier: "en_US_POSIX")
            f.dateFormat = "yyyy-MM-dd"
            try? fm.createDirectory(atPath: PlasmiePaths.home, withIntermediateDirectories: true)
            do {
                try (f.string(from: Date()) + "\n").write(toFile: markerPath, atomically: true, encoding: .utf8)
            } catch {
                NSLog("\(Brand.name): couldn't save the origin marker: %@", error.localizedDescription)
            }
        }
        m.refreshAchievements(force: true)
    }
}

/// "Why Plasmie?": the story, told by the mascot. Warm, short, and a little secret.
struct OriginStoryCard: View {
    @ObservedObject var m: Model
    let close: () -> Void
    @State private var shown = false

    private var trophy: Trophy? { m.trophies.first { $0.id == "origin-story" && $0.isUnlocked } }

    static var story: [String] {
        let name = Brand.name, plural = "\(Brand.id)s"
        return [
            "Hi! You found my secret. My name comes from plasmodium: a slime mold, one soft blob that grows a little network of paths and passes along the good things it finds.",
            "That's what I do with your work: I keep it, one day at a time, and bring back what's useful.",
            "Right now I'm your one \(name), just for you. One day, if you'd like, your \(Brand.id) might wave to your teammates' \(plural), each of us a node, swapping the good stuff we've found, like neighbours trading notes over the fence.",
        ]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 14) {
                PlasmieView(state: .hi, size: 64, accessory: m.stage?.accessory)
                    .frame(width: 64, height: 64)
                    .accessibilityHidden(true)
                Text("Why \(Brand.name)?").font(.klTitle).accessibilityAddTraits(.isHeader)
            }
            ForEach(Self.story, id: \.self) { line in
                Text(line).font(.klBody).fixedSize(horizontal: false, vertical: true)
            }
            if let t = trophy {
                HStack(spacing: 10) {
                    TrophyBadge(trophy: t, width: 26)
                    Text("Trophy: \(t.title)").font(.klLabel).foregroundStyle(.secondary)
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("Trophy unlocked: \(t.title)")
                .transition(.scale(scale: 0.85).combined(with: .opacity))
            }
            HStack {
                Spacer()
                Button("Close", action: close).keyboardShortcut(.defaultAction)
            }
        }
        .padding(22)
        .frame(width: 380)
        .scaleEffect(shown ? 1 : 0.94)
        .opacity(shown ? 1 : 0)
        .motion(Motion.pop, value: shown)                // Reduce Motion: a short crossfade instead
        .motion(Motion.pop, value: trophy?.id)
        .onAppear {
            shown = true
            NSAccessibility.post(element: NSApp as Any, notification: .announcementRequested, userInfo: [
                .announcement: "Why \(Brand.name)? You found a secret.",
                .priority: NSAccessibilityPriorityLevel.high.rawValue,
            ])
        }
    }
}
