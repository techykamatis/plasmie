import AppKit
import SwiftUI

// Plasmie's evolutions and trophies. The engine is plasmie-achievements.py (JSON on stdout);
// this file decodes it defensively, and draws the Trophies window: Plasmie in its current
// accessory, the six-stage evolution strip, and the trophy shelf.

// MARK: - report model (every field optional: an older/newer script must never blank the UI)

struct Achievements: Decodable {
    var birthday: String?
    var ageDays: Int?
    var stage: AchStage?
    var unlockedCount: Int?
    var total: Int?
    var trophies: [Trophy]?
    var newly: [String]?
    var stages: [AchStageInfo]?
}

/// One evolution and when it was reached (nil = not yet; daysLeft/notesLeft say how far).
struct AchStageInfo: Decodable {
    var id: String?
    var reached: String?
    var days: Int?
    var notes: Int?
    var daysLeft: Int?
    var notesLeft: Int?
}

struct AchStage: Decodable {
    var id: String?
    var name: String?
    var accessory: String?
    var next: AchNext?
}

struct AchNext: Decodable {
    var id: String?
    var name: String?
    var days: Int?
    var notes: Int?
}

struct Trophy: Decodable, Identifiable {
    var id: String
    var name: String?
    var tier: String?
    var description: String?
    var symbol: String?
    var unlocked: Bool?
    var date: String?
    var progress: Double?
    var current: Double?
    var target: Double?

    var title: String { name ?? id }
    var isUnlocked: Bool { unlocked ?? false }
    var tierName: String { ["bronze", "silver", "gold"].contains(tier ?? "") ? tier ?? "bronze" : "bronze" }
    var tierHue: PlasmieHue {
        switch tierName {
        case "gold": return PlasmieHues.gold
        case "silver": return PlasmieHues.silver
        default: return PlasmieHues.bronze
        }
    }
    var fraction: Double { min(max(progress ?? 0, 0), 1) }

    var accessibilityText: String {
        if isUnlocked {
            return "\(title), \(tierName) trophy, unlocked" + (AchDate.long(date).map { " \($0)" } ?? "")
        }
        let c = Int(current ?? 0), t = Int(target ?? 0)
        return "\(title), \(tierName) trophy, locked" + (t > 0 ? ", \(c) of \(t)" : "")
    }
}

enum AchDate {
    private static func fmt(_ pattern: String, posix: Bool = false) -> DateFormatter {
        let f = DateFormatter()
        if posix { f.locale = Locale(identifier: "en_US_POSIX") }
        f.dateFormat = pattern
        return f
    }
    private static let iso = fmt("yyyy-MM-dd", posix: true)
    private static let longFmt = fmt("d MMMM yyyy")
    private static let shortFmt = fmt("d MMM yyyy")
    static func long(_ s: String?) -> String? { s.flatMap { iso.date(from: $0) }.map { longFmt.string(from: $0) } }
    static func short(_ s: String?) -> String? { s.flatMap { iso.date(from: $0) }.map { shortFmt.string(from: $0) } }
}

/// Mirrors STAGES in plasmie-achievements.py (id, name, accessory, min days, min notes).
struct PlasmieStage: Identifiable {
    let id: String, name: String, accessory: String, days: Int, notes: Int
    static let all: [PlasmieStage] = [
        .init(id: "hatchling", name: "Hatchling", accessory: "eggshell", days: 0, notes: 0),
        .init(id: "sprout", name: "Sprout", accessory: "leaf", days: 7, notes: 25),
        .init(id: "thinker", name: "Thinker", accessory: "glasses", days: 30, notes: 100),
        .init(id: "scholar", name: "Scholar", accessory: "mortarboard", days: 90, notes: 250),
        .init(id: "sage", name: "Sage", accessory: "wizard-hat", days: 182, notes: 500),
        .init(id: "elder", name: "Elder Brain", accessory: "crown", days: 365, notes: 1000),
    ]
}

extension Achievements {
    var trophyList: [Trophy] { trophies ?? [] }
    var earned: [Trophy] { trophyList.filter(\.isUnlocked).sorted { ($0.date ?? "") > ($1.date ?? "") } }
    var locked: [Trophy] { trophyList.filter { !$0.isUnlocked }.sorted { $0.fraction > $1.fraction } }
    var unlockedTotal: Int { unlockedCount ?? earned.count }
    var trophyTotal: Int { total ?? trophyList.count }
    var stageIndex: Int { PlasmieStage.all.firstIndex { $0.id == stage?.id } ?? 0 }
    var stageName: String { stage?.name ?? PlasmieStage.all[stageIndex].name }
    var accessory: String? { stage?.accessory ?? PlasmieStage.all[stageIndex].accessory }

    /// "Sage in 79 days and 150 notes"; nil at the last stage.
    var nextLine: String? {
        guard let n = stage?.next, let name = n.name else { return nil }
        var parts: [String] = []
        if let d = n.days, d > 0 { parts.append("\(d) day\(d == 1 ? "" : "s")") }
        if let k = n.notes, k > 0 { parts.append("\(k) note\(k == 1 ? "" : "s")") }
        return parts.isEmpty ? "\(name) is ready to hatch" : "\(name) in " + parts.joined(separator: " and ")
    }

    /// 0...1 toward the next stage: the slower of the time and notes requirements.
    var nextProgress: Double {
        guard let n = stage?.next, let target = PlasmieStage.all.first(where: { $0.id == n.id }) else { return 1 }
        let cur = PlasmieStage.all[stageIndex]
        func frac(_ remaining: Int?, _ goal: Int, _ from: Int) -> Double {
            guard goal > from else { return 1 }
            let have = Double(goal - (remaining ?? 0))
            return min(max((have - Double(from)) / Double(goal - from), 0), 1)
        }
        return min(frac(n.days, target.days, cur.days), frac(n.notes, target.notes, cur.notes))
    }
}

// MARK: - loading

/// Runs plasmie-achievements.py (venv python first, then system) and decodes its stdout.
/// Blocking: call off the main thread. Returns nil on any failure.
func loadAchievements() -> Achievements? {
    let script = PlasmiePaths.script("plasmie-achievements.py")
    guard FileManager.default.fileExists(atPath: script) else { return nil }
    let pythons = [PlasmiePaths.python].filter { FileManager.default.isExecutableFile(atPath: $0) }
    for py in pythons {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: py)
        p.arguments = [script]
        let out = Pipe()
        p.standardOutput = out
        p.standardError = FileHandle.nullDevice
        guard (try? p.run()) != nil else { continue }
        let watchdog = killAfter(p, 120)
        let data = out.fileHandleForReading.readDataToEndOfFile()    // stdout only: stderr must not corrupt the JSON
        p.waitUntilExit()
        watchdog.cancel()
        guard p.terminationStatus == 0, let start = data.firstIndex(of: UInt8(ascii: "{")) else { continue }
        if let r = try? JSONDecoder().decode(Achievements.self, from: data[start...]) { return r }
    }
    return nil
}

// MARK: - window

final class TrophiesController: NSObject, NSWindowDelegate {
    static let shared = TrophiesController()
    private var win: NSWindow?

    func show(_ m: Model) {
        if let w = win { bringForward(w); return }
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 560, height: 640),
                         styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        w.title = "Plasmie Trophies"
        w.center(); w.isReleasedWhenClosed = false
        w.contentMinSize = NSSize(width: 480, height: 480)
        w.delegate = self
        w.contentView = NSHostingView(rootView: TrophiesWindow(m: m) { [weak self] in self?.win?.performClose(nil) })
        win = w
        bringForward(w)
    }

    func windowWillClose(_ notification: Notification) { win = nil }
}

private struct TrophiesWindow: View {
    @ObservedObject var m: Model
    let close: () -> Void
    var body: some View {
        TrophiesContent(report: m.ach, plasmie: m.plasmie)
            // a menu-bar app has no main menu, so Esc and ⌘W are wired here
            .background(Group {
                Button("Close", action: close).keyboardShortcut(.cancelAction)
                Button("Close Window", action: close).keyboardShortcut("w", modifiers: .command)
            }.opacity(0).frame(width: 0, height: 0).accessibilityHidden(true))
    }
}

// MARK: - content

struct TrophiesContent: View {
    let report: Achievements?
    var plasmie: PlasmieState = .idle
    var body: some View {
        ScrollView { inner }
            .frame(minWidth: 480, minHeight: 480)
            .background(Color(nsColor: .windowBackgroundColor))
    }

    /// The scrolled content (also what render proofs draw: ImageRenderer skips ScrollView).
    var inner: some View {
        Group {
            if let r = report {
                VStack(alignment: .leading, spacing: 22) {
                    TrophyHeader(report: r, plasmie: plasmie)
                    EvolutionStrip(current: r.stageIndex, info: r.stages ?? [])
                    shelf("Earned", r.earned)
                    shelf("Still to earn", r.locked)
                }
                .padding(24)
                .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                VStack(spacing: 10) {
                    PlasmieView(state: .quiet, size: 72)
                    Text("No trophies yet").font(.klHeading)
                    Text("Plasmie couldn't read its trophy shelf. It will try again on the next refresh.").klNote()
                        .multilineTextAlignment(.center)
                }
                .padding(40).frame(maxWidth: .infinity)
            }
        }
    }

    @ViewBuilder private func shelf(_ title: String, _ items: [Trophy]) -> some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                Text("\(title) · \(items.count)").font(.klHeading).accessibilityAddTraits(.isHeader)
                Grid(alignment: .topLeading, horizontalSpacing: 20, verticalSpacing: 18) {
                    ForEach(Array(stride(from: 0, to: items.count, by: 2)), id: \.self) { i in
                        GridRow {
                            TrophyTile(trophy: items[i]).transition(.scale(scale: 0.85).combined(with: .opacity))
                            if i + 1 < items.count {
                                TrophyTile(trophy: items[i + 1]).transition(.scale(scale: 0.85).combined(with: .opacity))
                            } else { Color.clear.frame(height: 1) }
                        }
                    }
                }
                .motion(Motion.pop, value: items.count)
            }
        }
    }
}

private struct TrophyHeader: View {
    let report: Achievements
    let plasmie: PlasmieState

    var body: some View {
        HStack(alignment: .center, spacing: 18) {
            InteractivePlasmie(state: plasmie, size: 96, accessory: report.accessory)
                .frame(width: 96, height: 96)
            VStack(alignment: .leading, spacing: 5) {
                Text(report.stageName).font(.klTitle)
                if let d = report.ageDays {
                    Text("Plasmie is \(d) day\(d == 1 ? "" : "s") old").font(.klLabel).foregroundStyle(.secondary)
                }
                if let line = report.nextLine {
                    Text(line).font(.klLabel).padding(.top, 4)
                    SlimBar(value: report.nextProgress, tint: .plasmieBlush)
                        .frame(maxWidth: 300)
                        .accessibilityLabel("Progress to \(report.stage?.next?.name ?? "next stage")")
                        .accessibilityValue("\(Int(report.nextProgress * 100)) percent")
                } else {
                    Text("Fully evolved").font(.klLabel).padding(.top, 4)
                }
                Text("\(report.unlockedTotal) of \(report.trophyTotal) trophies").font(.klMeta).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
    }
}

// Each evolution is a button: pick one to see when Plasmie reached it, or how far away it is.
private struct EvolutionStrip: View {
    let current: Int
    let info: [AchStageInfo]
    @State private var selected: Int?

    private var shown: Int { selected ?? current }

    var body: some View {
        VStack(spacing: 10) {
            HStack(alignment: .top, spacing: 0) {
                ForEach(Array(PlasmieStage.all.enumerated()), id: \.element.id) { i, s in
                    Button { selected = i } label: { chip(i, s) }
                        .buttonStyle(.plain)
                        .frame(maxWidth: .infinity)
                        .accessibilityLabel("\(s.name). \(detail(i))")
                        .accessibilityAddTraits(i == shown ? .isSelected : [])
                }
            }
            Text(detail(shown))
                .font(.klLabel).foregroundStyle(.secondary)
                .frame(maxWidth: .infinity)
                .id(shown).transition(.opacity)
        }
        .motion(Motion.glide, value: shown)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Evolution stages")
    }

    private func chip(_ i: Int, _ s: PlasmieStage) -> some View {
        VStack(spacing: 5) {
            PlasmieView(state: .idle, size: 40, frozenAt: 0.35, accessory: s.accessory)
                .grayscale(i > current ? 1 : 0)
                .opacity(i > current ? 0.35 : 1)
                .padding(4)
                .overlay(Circle().strokeBorder(Color.plasmieBlush, lineWidth: i == current ? 2.5 : 0))
                .background(Circle().fill(Color.primary.opacity(i == shown && i != current ? 0.08 : 0)))
            Text(s.name).font(.klMeta.weight(i == shown ? .semibold : .regular))
                .foregroundStyle(i > current ? .secondary : .primary)
                .lineLimit(1).minimumScaleFactor(0.9)
        }
        .contentShape(Rectangle())
    }

    /// "Reached 20 Sep 2026", or "78 more days and 144 more notes".
    private func detail(_ i: Int) -> String {
        let name = PlasmieStage.all[i].name
        let st = info.first { $0.id == PlasmieStage.all[i].id }
        if let when = AchDate.short(st?.reached) {
            return i == 0 ? "\(name) · hatched \(when)" : "\(name) · reached \(when)\(i == current ? " · Plasmie's stage now" : "")"
        }
        let d = st?.daysLeft ?? 0, n = st?.notesLeft ?? 0
        let parts = [d > 0 ? "\(d) more day\(d == 1 ? "" : "s")" : nil, n > 0 ? "\(n) more note\(n == 1 ? "" : "s")" : nil].compactMap { $0 }
        return parts.isEmpty ? "\(name) · any moment now" : "\(name) · \(parts.joined(separator: " and ")) to go"
    }
}

private struct TrophyTile: View {
    let trophy: Trophy
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            medal
            VStack(alignment: .leading, spacing: 3) {
                Text(trophy.title).font(.klHeading).lineLimit(2)
                if let d = trophy.description {
                    Text(d).font(.klMeta).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                if trophy.isUnlocked {
                    if let when = AchDate.short(trophy.date) { Text(when).font(.klMeta).foregroundStyle(.tertiary) }
                } else {
                    SlimBar(value: trophy.fraction, tint: trophy.tierHue.color(scheme)).padding(.vertical, 3)
                    Text("\(Int(trophy.current ?? 0)) / \(Int(trophy.target ?? 0))").font(.klMeta).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(trophy.accessibilityText)
        .accessibilityHint(trophy.description ?? "")
    }

    private var medal: some View { TrophyBadge(trophy: trophy) }
}

/// A trophy cup in its tier's metal, the achievement's icon engraved on the bowl. Locked:
/// a faint dashed outline of the cup you haven't won yet. Used by the Trophies window
/// and the latest-trophies row in the Plasmie window.
struct TrophyBadge: View {
    let trophy: Trophy
    var width: CGFloat = 46
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        let hue = trophy.tierHue.color(scheme)
        let ink = PlasmieHues.ink.color(scheme)
        let won = trophy.isUnlocked
        let k = width / 46
        return ZStack {
            if won {
                TrophyCup.handles.stroke(hue, style: StrokeStyle(lineWidth: 4.2 * k, lineCap: .round))
                TrophyCup.handles.stroke(ink.opacity(0.85), style: StrokeStyle(lineWidth: 1.4 * k, lineCap: .round))
                TrophyCup.body.fill(hue)
                TrophyCup.sheen.fill(Color.white.opacity(0.38))
                TrophyCup.body.stroke(ink.opacity(0.85), lineWidth: 1.4 * k)
            } else {
                TrophyCup.handles.stroke(Color.secondary.opacity(0.45),
                                         style: StrokeStyle(lineWidth: 1.3 * k, lineCap: .round, dash: [2.5, 2.5]))
                TrophyCup.body.fill(hue.opacity(0.10))
                TrophyCup.body.stroke(Color.secondary.opacity(0.45), style: StrokeStyle(lineWidth: 1.3 * k, dash: [2.5, 2.5]))
            }
            Image(systemName: trophy.symbol ?? "rosette")
                .font(.system(size: 12 * k, weight: .bold))
                .foregroundStyle(won ? ink.opacity(0.8) : Color.secondary.opacity(0.6))
                .offset(y: -9 * k)
        }
        .frame(width: width, height: width * 52 / 46)
        .shadow(color: .black.opacity(won ? 0.2 : 0), radius: 2.5 * k, x: 0, y: 1.5 * k)
        .accessibilityHidden(true)
    }
}

/// The cup, drawn on a 100×100 canvas and scaled to the frame: bowl + stem + stepped base
/// (one filled shape), handles (stroked), and a highlight that reads as polished metal.
private enum TrophyCup {
    static let body = Cup(part: .body)
    static let handles = Cup(part: .handles)
    static let sheen = Cup(part: .sheen)

    struct Cup: Shape {
        enum Part { case body, handles, sheen }
        let part: Part
        func path(in r: CGRect) -> Path {
            let sx = r.width / 100, sy = r.height / 100
            func pt(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: r.minX + x * sx, y: r.minY + y * sy) }
            var p = Path()
            switch part {
            case .body:
                p.move(to: pt(20, 6))                                         // bowl rim
                p.addLine(to: pt(80, 6))
                p.addCurve(to: pt(56, 56), control1: pt(80, 38), control2: pt(68, 52))
                p.addLine(to: pt(54, 70))                                     // stem
                p.addQuadCurve(to: pt(66, 78), control: pt(54, 76))
                p.addLine(to: pt(70, 78))                                     // collar
                p.addLine(to: pt(70, 84))
                p.addLine(to: pt(78, 84))                                     // plinth
                p.addQuadCurve(to: pt(80, 88), control: pt(80, 84))
                p.addLine(to: pt(80, 94))
                p.addLine(to: pt(20, 94))
                p.addLine(to: pt(20, 88))
                p.addQuadCurve(to: pt(22, 84), control: pt(20, 84))
                p.addLine(to: pt(30, 84))
                p.addLine(to: pt(30, 78))
                p.addLine(to: pt(34, 78))
                p.addQuadCurve(to: pt(46, 70), control: pt(46, 76))
                p.addLine(to: pt(44, 56))
                p.addCurve(to: pt(20, 6), control1: pt(32, 52), control2: pt(20, 38))
                p.closeSubpath()
            case .handles:
                p.move(to: pt(21, 14))
                p.addCurve(to: pt(28, 42), control1: pt(2, 12), control2: pt(4, 40))
                p.move(to: pt(79, 14))
                p.addCurve(to: pt(72, 42), control1: pt(98, 12), control2: pt(96, 40))
            case .sheen:
                p.move(to: pt(29, 12))
                p.addCurve(to: pt(38, 44), control1: pt(28, 28), control2: pt(31, 39))
                p.addCurve(to: pt(34, 12), control1: pt(35, 36), control2: pt(33, 24))
                p.closeSubpath()
            }
            return p
        }
    }
}

/// A 5pt rounded progress bar. Drawn, not ProgressView, so it renders the same everywhere.
private struct SlimBar: View {
    let value: Double
    let tint: Color
    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.primary.opacity(0.12))
                Capsule().fill(tint).frame(width: max(5, g.size.width * min(max(value, 0), 1)))
            }
        }
        .frame(height: 5)
        .motion(Motion.glide, value: value)
        .accessibilityElement(children: .ignore)
        .accessibilityValue("\(Int(min(max(value, 0), 1) * 100)) percent")
    }
}
