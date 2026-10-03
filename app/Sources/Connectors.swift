import AppKit
import Carbon.HIToolbox
import Foundation
import SwiftUI

// MARK: - connector health

/// One connector's live reachability, from plasmie-doctor.py.
/// `ok == nil` means "not configured" — unknown, not broken.
struct ConnectorHealth: Codable {
    var configured = false
    var ok: Bool? = nil
    var detail = ""
    var hint = ""
    var enabled: Bool? = nil   // optional: an older plasmie-doctor.py omits it
}

/// Static description of a connector: what to call it, which key it uses in
/// plasmie-doctor.py's output, in plasmie-status.py's sourceAgeHours, and which `*-ERR`
/// token it prints on a feed.log line.
struct Connector: Identifiable {
    let id: String
    let name: String
    let symbol: String
    let ageKey: String
    let errCode: String
    let blurb: String
    /// How often this source normally delivers new data, in hours. One concept
    /// drives both the verdict ("Quiet" = nothing new for 4x this) and the
    /// freshness bar (empty at 4x). Slack/Outlook/Claude: daily. GitHub, local
    /// git, AgentCLI: bursty, every ~3 days. Confluence: weekly.
    let cadenceHours: Double
    let cadenceLabel: String
    /// Hours without new data after which the card reads "Quiet".
    var quietAfterHours: Double { cadenceHours * 4 }

    static let all: [Connector] = [
        Connector(id: "slack", name: "Slack", symbol: "bubble.left.and.bubble.right.fill",
                  ageKey: "slack", errCode: "SLACK", blurb: "Messages you sent and received.",
                  cadenceHours: 24, cadenceLabel: "daily"),
        Connector(id: "github", name: "GitHub", symbol: "chevron.left.forwardslash.chevron.right",
                  ageKey: "github", errCode: "GH", blurb: "Pull requests and issues you opened or commented on.",
                  cadenceHours: 72, cadenceLabel: "every ~3 days"),
        Connector(id: "git", name: "Local git commits", symbol: "arrow.triangle.branch",
                  ageKey: "git", errCode: "GIT",
                  blurb: "Your own commit messages, from repos cloned on this Mac. Finer-grained than GitHub, and needs no network or token.",
                  cadenceHours: 72, cadenceLabel: "every ~3 days"),
        Connector(id: "confluence", name: "Confluence", symbol: "doc.text.fill",
                  ageKey: "confluence", errCode: "CONF", blurb: "Pages you created or edited.",
                  cadenceHours: 168, cadenceLabel: "weekly"),
        Connector(id: "outlook", name: "Outlook", symbol: "envelope.fill",
                  ageKey: "outlook", errCode: "MAIL", blurb: "Mail and calendar.",
                  cadenceHours: 24, cadenceLabel: "daily"),
        Connector(id: "claude", name: "Claude Code sessions", symbol: "terminal.fill",
                  ageKey: "sessions", errCode: "", blurb: "What you worked on, from local session logs.",
                  cadenceHours: 24, cadenceLabel: "daily"),
        Connector(id: "agentcli", name: "AgentCLI sessions", symbol: "sparkles.rectangle.stack",
                  ageKey: "agentcli", errCode: "AGENTCLI", blurb: "What you worked on in AgentCLI, from its local session database.",
                  cadenceHours: 72, cadenceLabel: "every ~3 days"),
    ]
}

/// The verdict shown on a card. Three signals are deliberately NOT collapsed
/// into one:
///   configured — are there credentials at all?
///   ok         — can we reach it right now?          (plasmie-doctor.py, live)
///   age        — when did it last actually produce?  (plasmie-status.py, feed.log)
/// "Reachable but quiet" is a normal state and must not read as a fault —
/// conflating the two is what let a dead Confluence ingest look fine for weeks,
/// and a phantom GitHub error look broken for 43 days.
enum ConnVerdict {
    case off, notSetUp, failing, lastRunFailed, noData, quiet, flowing, checking

    var label: String {
        switch self {
        case .off:            return "Off"
        case .notSetUp:       return "Not set up"
        case .failing:        return "Not working"
        case .lastRunFailed:  return "Failed last run"
        case .noData:         return "No data yet"
        case .quiet:          return "Quiet"
        case .flowing:        return "Flowing"
        case .checking:       return "Checking…"
        }
    }
    /// A distinct shape per verdict, so state never rests on colour alone.
    var symbol: String {
        switch self {
        case .off:            return "pause.circle"
        case .notSetUp:       return "plus.circle"
        case .failing:        return "xmark.octagon.fill"
        case .lastRunFailed:  return "exclamationmark.triangle.fill"
        case .noData:         return "circle.dotted"
        case .quiet:          return "moon.zzz"
        case .flowing:        return "checkmark.circle.fill"
        case .checking:       return "arrow.triangle.2.circlepath"
        }
    }
    /// One line each, for the legend popover.
    var meaning: String {
        switch self {
        case .flowing:        return "Reachable, and new data arrived within 4x its usual interval."
        case .quiet:          return "Reachable, but nothing new for over 4x its usual interval. Normal for some sources."
        case .noData:         return "Reachable, but nothing has been pulled yet."
        case .lastRunFailed:  return "Reachable now, but the most recent ingest run reported an error."
        case .failing:        return "Credentials are set, but the connector cannot be reached."
        case .notSetUp:       return "No credentials yet. Add them on the card to start."
        case .off:            return "Switched off. Nothing is pulled until you turn it back on."
        case .checking:       return "Probing the connector."
        }
    }
    /// Reachable and not failing.
    var isWorking: Bool { self == .flowing || self == .quiet }
    var needsAttention: Bool { self == .failing || self == .lastRunFailed }
    var color: Color {
        switch self {
        case .off, .notSetUp, .quiet: return .secondary
        case .failing:          return .red
        case .lastRunFailed,
             .noData:           return .orange
        case .flowing:          return .green
        case .checking:         return .blue
        }
    }
}

func connVerdict(_ c: Connector, health: ConnectorHealth?, status: Status, checking: Bool, off: Bool = false) -> ConnVerdict {
    if off { return .off }
    if checking { return .checking }
    guard let h = health else { return .checking }
    if !h.configured { return .notSetUp }
    if h.ok == false { return .failing }
    if !c.errCode.isEmpty && status.errSources.contains(c.errCode) { return .lastRunFailed }
    guard let age = status.age(c.ageKey) else { return .noData }
    return age > c.quietAfterHours ? .quiet : .flowing
}

/// "38h ago" / "4d ago" / "never" — the answer to "is this actually feeding me?"
func ageText(_ hours: Double?) -> String {
    guard let h = hours else { return "no data yet" }
    if h < 1 { return "just now" }
    if h < 48 { return "\(Int(h))h ago" }
    return "\(Int(h / 24))d ago"
}

/// Runs plasmie-doctor.py off the main thread — each probe is a real network call
/// with a 15s ceiling, so doing this inline would freeze the window.
final class ConnectorsModel: ObservableObject {
    @Published var health: [String: ConnectorHealth] = [:]
    @Published var checking: Set<String> = []
    @Published var status = Status()
    /// Connectors switched Off — PLASMIE_DISABLED_SOURCES in config.env, read by
    /// paths.disabled_sources() in every job. Off means off: no fetch, and the
    /// watermark keeps moving, so switching back On never backfills the gap.
    @Published var off: Set<String> = ConnectorsModel.readOff()

    static func readOff() -> Set<String> {
        let raw = ConfigStore.read(ConfigStore.configEnv)["PLASMIE_DISABLED_SOURCES"] ?? ""
        return Set(raw.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces).lowercased() }
                      .filter { !$0.isEmpty })
    }

    /// Applies immediately (no Save): a switch that waits for another button lies.
    /// The config write is instant; the doctor probe is coalesced so rapid flips
    /// spawn one process, not one per flip.
    func setEnabled(_ id: String, _ on: Bool) {
        var next = ConnectorsModel.readOff()          // re-read: the file may have been hand-edited
        if on { next.remove(id) } else { next.insert(id) }
        ConfigStore.upsert(ConfigStore.configEnv, ["PLASMIE_DISABLED_SOURCES": next.sorted().joined(separator: ",")],
                           exportPrefix: false, quoted: true)
        off = ConnectorsModel.readOff()
        pending.insert(id)
        checking.insert(id)
        debounce?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self else { return }
            let ids = Array(self.pending)
            self.pending.removeAll()
            self.refresh(ids)
        }
        debounce = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6, execute: work)
    }

    private var pending: Set<String> = []
    private var debounce: DispatchWorkItem?
    /// Latest refresh generation per connector; a result from an older one is stale.
    private var generation: [String: Int] = [:]

    private var python: String { PlasmiePaths.python }

    func refresh(_ sources: [String] = []) {
        let keys = sources.isEmpty ? Connector.all.map(\.id) : sources
        checking.formUnion(keys)
        var mine: [String: Int] = [:]
        for k in keys { generation[k, default: 0] += 1; mine[k] = generation[k] }
        let py = python, script = PlasmiePaths.script("plasmie-doctor.py")
        DispatchQueue.global().async {
            let out = runCapture(py, [script] + sources)
            let parsed = (out.data(using: .utf8)).flatMap {
                try? JSONDecoder().decode([String: ConnectorHealth].self, from: $0)
            } ?? [:]
            let st = loadStatus()
            DispatchQueue.main.async {
                self.status = st
                for k in keys where self.generation[k] == mine[k] {   // drop stale results
                    if let v = parsed[k] { self.health[k] = v }
                    self.checking.remove(k)
                }
            }
        }
    }
}

/// One connector, as a card: verdict, what it pulls, when it last produced,
/// why it is failing (with the fix), its credential fields, and Test/Disconnect.
struct ConnectorCard<Fields: View>: View {
    let c: Connector
    @ObservedObject var m: ConnectorsModel
    let onDisconnect: (() -> Void)?
    let fields: () -> Fields
    /// Explicit when known; nil falls back to "has a non-empty fields builder".
    private let hasFieldsOverride: Bool?
    @State private var confirmDisconnect = false

    init(c: Connector, m: ConnectorsModel, onDisconnect: (() -> Void)?, hasFields: Bool? = nil,
         @ViewBuilder fields: @escaping () -> Fields) {
        self.c = c; self.m = m; self.onDisconnect = onDisconnect
        self.hasFieldsOverride = hasFields; self.fields = fields
    }

    private var health: ConnectorHealth? { m.health[c.id] }
    private var isChecking: Bool { m.checking.contains(c.id) }
    private var isOff: Bool { m.off.contains(c.id) }
    private var verdict: ConnVerdict { connVerdict(c, health: health, status: m.status, checking: isChecking, off: isOff) }
    private var onBinding: Binding<Bool> {
        Binding(get: { !isOff }, set: { m.setEnabled(c.id, $0) })
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            header
            // Off dims the body, not the switch; credentials stay editable so they
            // can be fixed before switching on.
            VStack(alignment: .leading, spacing: 8) {
                Text(c.blurb).klNote()
                if isOff {
                    Text("Switched off — nothing is pulled from \(c.name) and it is left out of digests and promotion. Switching it back on resumes from now; the off period is not backfilled.")
                        .klNote()
                } else {
                    detailLine
                }
                fields()
            }
            .opacity(isOff ? 0.55 : 1)
            if !isOff { controls }
        }
        .confirmationDialog("Disconnect \(c.name)?", isPresented: $confirmDisconnect, titleVisibility: .visible) {
            Button("Disconnect", role: .destructive) { onDisconnect?() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This removes the \(c.name) token from your Keychain. Paste it again to reconnect.")
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.04)))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(verdict.color.opacity(0.25), lineWidth: 1))
        .accessibilityElement(children: .contain)
    }

    private var header: some View {
        HStack(spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: c.symbol).frame(width: 18).foregroundStyle(verdict.color)
                Text(c.name).font(.klHeading)
                Spacer(minLength: 0)
                if !isOff {
                    HStack(spacing: 5) {
                        if isChecking {
                            ProgressView().controlSize(.small).scaleEffect(0.6).frame(width: 12, height: 12)
                        } else {
                            Image(systemName: verdict.symbol).font(.system(size: 10, weight: .semibold))
                        }
                        Text(verdict.label).font(.klMeta.weight(.semibold))
                    }
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(Capsule().fill(verdict.color.opacity(0.16)))
                    .foregroundStyle(verdict.color)
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("\(c.name), \(verdict.label)")
            Toggle(c.name, isOn: onBinding)
                .toggleStyle(.switch).controlSize(.small).labelsHidden()
                .accessibilityLabel(c.name)
                .accessibilityValue(isOff ? "off" : "on")
                .help(isOff ? "Turn \(c.name) on" : "Turn \(c.name) off")
        }
    }

    private var hasFields: Bool { hasFieldsOverride ?? !(Fields.self is EmptyView.Type) }

    @ViewBuilder private var detailLine: some View {
        if verdict == .notSetUp {
            Text(hasFields ? "Add a token below to start" : "Signed in via gh/local — nothing to set up").klNote()
        }
        if let h = health, !h.detail.isEmpty {
            Text(h.detail).klNote().textSelection(.enabled)
        }
        // The freshness line is the whole point: it separates "quiet" from "broken".
        if health?.configured == true {
            let age = m.status.age(c.ageKey)
            HStack(spacing: 8) {
                Text("Last new data: " + ageText(age)).klNote()
                if let age {
                    FreshnessBar(age: age, quietAfter: c.quietAfterHours, tint: verdict.color)
                        .help("How recently \(c.name) delivered, against its usual pace. Full means on schedule.")
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel("Freshness")
                        .accessibilityValue(age > c.quietAfterHours ? "quiet" : age > c.cadenceHours ? "behind" : "on schedule")
                    Text("usual: \(c.cadenceLabel)").klNote()
                }
            }
        }
        if let h = health, !h.hint.isEmpty {
            HStack(alignment: .firstTextBaseline, spacing: 5) {
                Image(systemName: "lightbulb.fill").font(.system(size: 10)).foregroundStyle(.orange)
                Text(h.hint).font(.klMeta).foregroundStyle(.primary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(8)
            .background(RoundedRectangle(cornerRadius: 6).fill(Color.orange.opacity(0.12)))
        }
    }

    private var controls: some View {
        HStack(spacing: 8) {
            Button("Test") { m.refresh([c.id]) }.disabled(isChecking)
            if onDisconnect != nil, health?.configured == true {
                Button("Disconnect", role: .destructive) { confirmDisconnect = true }
            }
            Spacer(minLength: 0)
        }
    }
}

/// Freshness as a thin capsule: full at 0h, empty at the source's Quiet
/// threshold (4x its usual cadence). Sits inline between the age and the
/// "usual: ..." caption so it reads as a gauge, not as loading.
private struct FreshnessBar: View {
    let age: Double
    let quietAfter: Double
    let tint: Color
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var fraction: Double { max(0, min(1, 1 - age / quietAfter)) }

    var body: some View {
        Capsule().fill(Color.primary.opacity(0.1))
            .frame(height: 3)
            .overlay(alignment: .leading) {
                GeometryReader { g in
                    Capsule().fill(tint).frame(width: g.size.width * fraction)
                }
            }
            .frame(width: 80)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.4), value: fraction)
    }
}

/// Summary bar atop the Connectors page (moved out of SettingsView).
struct ConnectorsSummary: View {
    @ObservedObject var conn: ConnectorsModel
    @State private var showLegend = false

    /// The one-glance answer: how many are actually working, and is the loop running
    /// at all. "Working" = reachable and not failing (flowing or quiet).
    var body: some View {
        let on = Connector.all.filter { !conn.off.contains($0.id) }
        let verdicts = on.map {
            connVerdict($0, health: conn.health[$0.id], status: conn.status, checking: conn.checking.contains($0.id))
        }
        let settling = verdicts.contains(.checking)
        let live = verdicts.filter(\.isWorking).count
        let broken = verdicts.filter(\.needsAttention).count
        let offCount = Connector.all.count - on.count
        let head = settling ? "Checking…"
            : "\(live) of \(on.count) connectors working" + (broken > 0 ? " · \(broken) need attention" : "")
        return HStack(spacing: 8) {
            Image(systemName: settling ? "arrow.triangle.2.circlepath" : broken > 0 ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
                .foregroundStyle(settling ? Color.secondary : broken > 0 ? .orange : .green)
            VStack(alignment: .leading, spacing: 1) {
                Text(head + (offCount > 0 ? " · \(offCount) off" : ""))
                    .font(.klLabel.weight(.medium))
                if let mins = conn.status.staleMinutes {
                    Text("Last ingest run \(mins) min ago").klNote()
                }
            }
            Spacer(minLength: 0)
            Button { showLegend.toggle() } label: { Image(systemName: "info.circle") }
                .buttonStyle(.borderless)
                .help("What the statuses mean")
                .accessibilityLabel("What the statuses mean")
                .popover(isPresented: $showLegend, arrowEdge: .bottom) { legend }
            Button("Test all") { conn.refresh() }.disabled(!conn.checking.isEmpty)
                .keyboardShortcut("t", modifiers: .command)
                .help("Re-check every connector (\u{2318}T)")
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.05)))
    }

    private var legend: some View {
        let all: [ConnVerdict] = [.flowing, .quiet, .noData, .lastRunFailed, .failing, .notSetUp, .off]
        return VStack(alignment: .leading, spacing: 8) {
            ForEach(all, id: \.label) { v in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Image(systemName: v.symbol).foregroundStyle(v.color).frame(width: 16)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(v.label).font(.klLabel.weight(.semibold))
                        Text(v.meaning).klNote()
                    }
                }
                .accessibilityElement(children: .combine)
            }
            Divider()
            Text("The thin bar on a card shows freshness against that source's usual pace. Full means on schedule; empty means Quiet.")
                .klNote()
        }
        .padding(12).frame(width: 300)
    }
}
