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

    static let all: [Connector] = [
        Connector(id: "slack", name: "Slack", symbol: "bubble.left.and.bubble.right.fill",
                  ageKey: "slack", errCode: "SLACK", blurb: "Messages you sent and received."),
        Connector(id: "github", name: "GitHub", symbol: "chevron.left.forwardslash.chevron.right",
                  ageKey: "github", errCode: "GH", blurb: "Pull requests and issues you opened or commented on."),
        Connector(id: "git", name: "Local git commits", symbol: "arrow.triangle.branch",
                  ageKey: "git", errCode: "GIT",
                  blurb: "Your own commit messages, from repos cloned on this Mac. Finer-grained than GitHub, and needs no network or token."),
        Connector(id: "confluence", name: "Confluence", symbol: "doc.text.fill",
                  ageKey: "confluence", errCode: "CONF", blurb: "Pages you created or edited."),
        Connector(id: "outlook", name: "Outlook", symbol: "envelope.fill",
                  ageKey: "outlook", errCode: "MAIL", blurb: "Mail and calendar."),
        Connector(id: "claude", name: "Claude Code sessions", symbol: "terminal.fill",
                  ageKey: "sessions", errCode: "", blurb: "What you worked on, from local session logs."),
        Connector(id: "agentcli", name: "AgentCLI sessions", symbol: "terminal",
                  ageKey: "agentcli", errCode: "AGENTCLI", blurb: "What you worked on in AgentCLI, from its local session database."),
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
    return age > 96 ? .quiet : .flowing
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
    func setEnabled(_ id: String, _ on: Bool) {
        var next = ConnectorsModel.readOff()          // re-read: the file may have been hand-edited
        if on { next.remove(id) } else { next.insert(id) }
        ConfigStore.upsert(ConfigStore.configEnv, ["PLASMIE_DISABLED_SOURCES": next.sorted().joined(separator: ",")],
                           exportPrefix: false, quoted: true)
        off = ConnectorsModel.readOff()
        refresh([id])
    }

    private var loop: String { "\(NSHomeDirectory())/.plasmie" }
    private var python: String {
        FileManager.default.fileExists(atPath: "\(loop)/.venv/bin/python3")
            ? "\(loop)/.venv/bin/python3" : "/usr/bin/python3"
    }

    func refresh(_ sources: [String] = []) {
        let keys = sources.isEmpty ? Connector.all.map(\.id) : sources
        checking.formUnion(keys)
        let py = python, script = "\(loop)/plasmie-doctor.py"
        DispatchQueue.global().async {
            let out = runCapture(py, [script] + sources)
            let parsed = (out.data(using: .utf8)).flatMap {
                try? JSONDecoder().decode([String: ConnectorHealth].self, from: $0)
            } ?? [:]
            let st = loadStatus()
            DispatchQueue.main.async {
                for (k, v) in parsed { self.health[k] = v }
                self.status = st
                self.checking.subtract(keys)
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
    @ViewBuilder let fields: () -> Fields

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
            Text(c.blurb).font(.system(size: 11)).foregroundStyle(.secondary)
            if isOff {
                Text("Switched off — nothing is pulled from \(c.name) and it is left out of digests and promotion. Switching it back on resumes from now; the off period is not backfilled.")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                detailLine
                fields()
                controls
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.04)))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(verdict.color.opacity(0.25), lineWidth: 1))
    }

    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: c.symbol).frame(width: 18).foregroundStyle(verdict.color)
            Text(c.name).font(.system(size: 13, weight: .semibold))
            Spacer(minLength: 0)
            HStack(spacing: 5) {
                if isChecking {
                    ProgressView().controlSize(.small).scaleEffect(0.6).frame(width: 10, height: 10)
                } else {
                    Circle().fill(verdict.color).frame(width: 6, height: 6)
                }
                Text(verdict.label).font(.caption2.weight(.semibold))
            }
            .padding(.horizontal, 8).padding(.vertical, 3)
            .background(Capsule().fill(verdict.color.opacity(0.16)))
            .foregroundStyle(verdict.color)
            Toggle("", isOn: onBinding)
                .toggleStyle(.switch).controlSize(.small).labelsHidden()
                .accessibilityLabel("\(c.name) on or off")
                .help(isOff ? "Turn \(c.name) on" : "Turn \(c.name) off")
        }
    }

    @ViewBuilder private var detailLine: some View {
        if let h = health, !h.detail.isEmpty {
            Text(h.detail).font(.system(size: 11)).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
        }
        // The freshness line is the whole point: it separates "quiet" from "broken".
        if health?.configured == true {
            Text("Last new data: " + ageText(m.status.age(c.ageKey)))
                .font(.system(size: 11)).foregroundStyle(.secondary)
        }
        if let h = health, h.ok == false || !h.hint.isEmpty, !h.hint.isEmpty {
            HStack(alignment: .firstTextBaseline, spacing: 5) {
                Image(systemName: "lightbulb.fill").font(.system(size: 9)).foregroundStyle(.orange)
                Text(h.hint).font(.system(size: 11)).foregroundStyle(.primary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(8)
            .background(RoundedRectangle(cornerRadius: 6).fill(Color.orange.opacity(0.12)))
        }
    }

    private var controls: some View {
        HStack(spacing: 8) {
            Button("Test") { m.refresh([c.id]) }.disabled(isChecking)
            if let d = onDisconnect, health?.configured == true {
                Button("Disconnect", role: .destructive, action: d)
            }
            Spacer(minLength: 0)
        }
    }
}

/// Summary bar atop the Connectors page (moved out of SettingsView).
struct ConnectorsSummary: View {
    @ObservedObject var conn: ConnectorsModel

    /// The one-glance answer: how many are actually working, and is the loop running
    /// at all. A connector page that cannot say "3 of 5" makes you open five cards.
    var body: some View {
        let on = Connector.all.filter { !conn.off.contains($0.id) }
        let live = on.filter { conn.health[$0.id]?.ok == true }.count
        let broken = on.filter { conn.health[$0.id]?.ok == false }.count
        let offCount = Connector.all.count - on.count
        return HStack(spacing: 8) {
            Image(systemName: broken > 0 ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
                .foregroundStyle(broken > 0 ? .orange : .green)
            VStack(alignment: .leading, spacing: 1) {
                Text("\(live) of \(on.count) connectors working"
                     + (broken > 0 ? " · \(broken) need attention" : "")
                     + (offCount > 0 ? " · \(offCount) off" : ""))
                    .font(.system(size: 12, weight: .medium))
                if let mins = conn.status.staleMinutes {
                    Text("Last ingest run \(mins) min ago").font(.system(size: 10.5)).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
            Button("Test all") { conn.refresh() }.disabled(!conn.checking.isEmpty)
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.05)))
    }
}
