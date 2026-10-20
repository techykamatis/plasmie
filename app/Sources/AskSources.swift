import Foundation
import SwiftUI

// Ask's sources as pills: a coloured dot, the kind of note in a short lowercase word, and the
// note's own title — "decision  Ship on Thursday". The kinds are the map's (MapKind), so the
// dot is the same blob the map draws, plus the two things a recap can cite that the map never
// shows: the daily digest and a connector's raw day log. Titles come from the note itself:
// frontmatter `title:`, else its first `# ` heading, else the file name tidied up. Only the
// head of the file is read, off the main thread (AskOverlay resolves them in a task).

/// What a source is. Mirrors the map's filter groups, plus digest and log (recap answers).
enum SourceTag: Equatable {
    case kind(MapKind)
    case digest
    case log(String)          // a connector's raw day log: raw/<connector>/YYYY-MM-DD.md

    /// The pill's word: short, lowercase, singular, the map's vocabulary.
    var label: String {
        switch self {
        case .kind(let k): return ["note", "decision", "gotcha", "pattern", "how-to", "map"][k.rawValue]
        case .digest: return "digest"
        case .log: return "log"
        }
    }
}

struct AskSource: Equatable {
    let path: String          // vault-relative, as ask.py printed it
    let title: String
    let tag: SourceTag
    /// The digest's day (meta/digests/YYYY-MM-DD.md), for folding a week into one pill.
    var day: Date? {
        guard tag == .digest, let f = path.split(separator: "/").last, f.hasSuffix(".md") else { return nil }
        return AskSources.isoDate(String(f.dropLast(3)))
    }
}

enum AskSources {
    static let headBytes = 8192

    /// A source from its path and (optionally) the first few KB of the file. Without a head
    /// it is the folder's guess and the tidied file name: the instant, no-I/O first paint.
    static func describe(path: String, head: String?) -> AskSource {
        let parts = path.split(separator: "/").map(String.init)
        let file = parts.last ?? path
        let stem = file.hasSuffix(".md") ? String(file.dropLast(3)) : file
        let folders = parts.dropLast().map { $0.lowercased() }
        let doc = head.map(MDDocument.parse)
        func meta(_ k: String) -> String? {
            guard let v = doc?.meta.first(where: { $0.key == k })?.value, !v.isEmpty else { return nil }
            return v.replacingOccurrences(of: "\\\"", with: "\"").replacingOccurrences(of: "\\\\", with: "\\")
        }
        let type = (meta("type") ?? "").lowercased()
        let tags = (meta("tags") ?? "").lowercased().split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }

        // A connector's day log (a temporal recap reads these): the folder IS its origin.
        if folders.first == "raw", folders.count >= 2, folders[1] != "journal", folders[1] != "inbox" {
            let who = connectorName(folders[1])
            return AskSource(path: path, title: dated(stem).map { "\(who), \($0)" } ?? "\(who), \(pretty(stem))",
                             tag: .log(folders[1]))
        }
        // Daily digests: meta/digests/ (and the legacy raw/journal/). They are written as
        // `type: note` with a `digest` tag, so the folder and tag win over the type here.
        if folders.starts(with: ["meta", "digests"]) || folders.starts(with: ["raw", "journal"])
            || type == "digest" || tags.contains("digest") {
            return AskSource(path: path, title: dated(stem) ?? pretty(stem), tag: .digest)
        }

        let title = meta("title") ?? doc?.blocks.lazy.compactMap { b -> String? in
            if case .heading(1, let t) = b, !t.isEmpty { return t }; return nil
        }.first ?? pretty(stem)
        // Frontmatter type first (plasmie-graph.py's rule: moc/index or under wiki/mocs/ is a map),
        // then the folder for a note that has no type.
        let hub = ["moc", "index"].contains(type) || path.hasPrefix("wiki/mocs/")
        let kind = type.isEmpty && !hub ? folderKind(folders) : MapKind(type: type, hub: hub)
        return AskSource(path: path, title: title, tag: .kind(kind))
    }

    /// Reads just the head of a note: cheap, and never the whole of a long file.
    static func resolve(path: String, vault: String) -> AskSource {
        let url = URL(fileURLWithPath: vault).appendingPathComponent(path)
        guard let fh = try? FileHandle(forReadingFrom: url) else { return describe(path: path, head: nil) }
        defer { try? fh.close() }
        let data = (try? fh.read(upToCount: headBytes)) ?? Data()
        return describe(path: path, head: String(decoding: data, as: UTF8.self))
    }

    /// A user's own folders, when the note has no `type:` (Decisions/, how-tos/, …).
    private static func folderKind(_ folders: [String]) -> MapKind {
        for f in folders.reversed() {
            let w = f.replacingOccurrences(of: "_", with: "-").replacingOccurrences(of: " ", with: "-")
            switch w {
            case "decisions", "decision", "adr", "adrs": return .decision
            case "gotchas", "gotcha": return .gotcha
            case "patterns", "pattern", "conventions": return .pattern
            case "how-tos", "how-to", "howtos", "howto": return .howto
            case "mocs", "maps": return .map
            default: continue
            }
        }
        return .note
    }

    private static func connectorName(_ dir: String) -> String {
        switch dir {
        case "slack": return "Slack"
        case "github": return "GitHub"
        case "git": return "Git"
        case "outlook": return "Outlook"
        case "confluence": return "Confluence"
        case "claude": return "Coding sessions"     // raw/claude holds Claude Code sessions
        default: return dir.prefix(1).uppercased() + dir.dropFirst()
        }
    }

    private static let iso: DateFormatter = {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"; return f
    }()
    private static let dayFmt: DateFormatter = { let f = DateFormatter(); f.dateFormat = "EEE d MMM"; return f }()
    private static let dayYearFmt: DateFormatter = { let f = DateFormatter(); f.dateFormat = "EEE d MMM yyyy"; return f }()

    static func isoDate(_ s: String) -> Date? { s.count == 10 ? iso.date(from: s) : nil }

    /// "2026-10-14" -> "Tue 14 Oct" (the year only when it isn't this one).
    static func dated(_ stem: String) -> String? {
        guard stem.count == 10, let d = iso.date(from: stem) else { return nil }
        let thisYear = Calendar.current.isDate(d, equalTo: Date(), toGranularity: .year)
        return (thisYear ? dayFmt : dayYearFmt).string(from: d)
    }

    /// "ship-on_thursday" -> "Ship on thursday"; a leading date moves to the end, nicely.
    static func pretty(_ stem: String) -> String {
        if let d = dated(stem) { return d }
        var s = stem, when: String?
        if stem.count > 11, let d = dated(String(stem.prefix(10))), "-_ ".contains(stem[stem.index(stem.startIndex, offsetBy: 10)]) {
            s = String(stem.dropFirst(11)); when = d
        }
        s = s.replacingOccurrences(of: "-", with: " ").replacingOccurrences(of: "_", with: " ")
            .split(separator: " ").joined(separator: " ")
        guard let f = s.first else { return when ?? stem }
        s = f.uppercased() + s.dropFirst()
        return when.map { "\(s), \($0)" } ?? s
    }
}

// MARK: - the pill

/// The source's dot: the map's own blob for a map kind; a hollow ring for a digest (a rollup,
/// not a note, and not on the map); the connector's colour for a raw day log.
struct SourceDot: View {
    let tag: SourceTag
    @Environment(\.colorScheme) private var scheme
    var body: some View {
        switch tag {
        case .kind(let k): MapSwatch(kind: k)
        case .digest:
            Circle().strokeBorder(PlasmieHues.mapNote.color(scheme), lineWidth: 1.6)
                .frame(width: 9, height: 9).accessibilityHidden(true)
        case .log(let c):
            Circle().fill(Self.connector(c).color(scheme))
                .overlay(Circle().strokeBorder(Color.primary.opacity(0.25), lineWidth: 0.5))
                .frame(width: 9, height: 9).accessibilityHidden(true)
        }
    }

    static func connector(_ c: String) -> PlasmieHue {
        switch c {
        case "slack": return PlasmieHues.slack
        case "github": return PlasmieHues.github
        case "git": return PlasmieHues.git
        case "outlook": return PlasmieHues.outlook
        case "confluence": return PlasmieHues.confluence
        case "claude": return PlasmieHues.claude
        default: return PlasmieHues.mapNote
        }
    }
}

struct SourcePill: View {
    let source: AskSource
    var showsTag = true       // off inside an opened-out digest week: its pill already says it
    let open: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: open) {
            HStack(spacing: 5) {
                SourceDot(tag: source.tag)
                if showsTag { Text(source.tag.label).font(.klMeta).foregroundStyle(.secondary) }
                Text(source.title).font(.klLabel).foregroundStyle(.primary)
                    .lineLimit(1).truncationMode(.tail)
            }
            .padding(.leading, 7).padding(.trailing, 9).padding(.vertical, 3)
            .background(Capsule().fill(Color.primary.opacity(hover ? 0.11 : 0.06)))
            .overlay(Capsule().strokeBorder(Color.primary.opacity(hover ? 0.2 : 0.12)))
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help(source.path)
        .accessibilityLabel("Read \(source.title)")
        .accessibilityValue(source.tag.label)
        .accessibilityHint(source.path)
    }
}

/// Left-aligned rows that wrap: each child at its ideal width (capped at the row), next to the
/// last while it fits, else on a new line.
struct FlowLayout: Layout {
    var spacing: CGFloat = 6
    var lineSpacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(proposal.width ?? .infinity, subviews)
        let w = rows.map { $0.width }.max() ?? 0
        let h = rows.reduce(0) { $0 + $1.height } + lineSpacing * CGFloat(max(rows.count - 1, 0))
        // Take the offered width when there is one: placing re-arranges in bounds.width, and a
        // bounds as narrow as the widest row would wrap the rows differently.
        if let pw = proposal.width, pw.isFinite { return CGSize(width: pw, height: h) }
        return CGSize(width: w, height: h)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in arrange(bounds.width, subviews) {
            var x = bounds.minX
            for (i, size) in row.items {
                subviews[i].place(at: CGPoint(x: x, y: y + (row.height - size.height) / 2),
                                  proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += row.height + lineSpacing
        }
    }

    private struct Row { var items: [(Int, CGSize)] = []; var width: CGFloat = 0; var height: CGFloat = 0 }

    private func arrange(_ maxWidth: CGFloat, _ subviews: Subviews) -> [Row] {
        var rows: [Row] = [], row = Row()
        for (i, v) in subviews.enumerated() {
            var s = v.sizeThatFits(.unspecified)
            if s.width > maxWidth { s = v.sizeThatFits(ProposedViewSize(width: maxWidth, height: nil)) }
            let w = min(s.width, maxWidth)
            if !row.items.isEmpty && row.width + spacing + w > maxWidth { rows.append(row); row = Row() }
            row.width += (row.items.isEmpty ? 0 : spacing) + w
            row.height = max(row.height, s.height)
            row.items.append((i, CGSize(width: w, height: s.height)))
        }
        if !row.items.isEmpty { rows.append(row) }
        return rows
    }
}

// MARK: - the list

/// One pill per source, except a run of 3+ daily digests (a "last week" recap cites seven),
/// which folds into one pill — "digest  12–18 Oct (7 days)" — that opens out in place.
enum SourceGroup: Equatable {
    case one(AskSource)
    case digests([AskSource])

    static let foldAt = 3

    static func group(_ sources: [AskSource]) -> [SourceGroup] {
        var out: [SourceGroup] = [], run: [AskSource] = []
        func flush() {
            if run.count >= foldAt { out.append(.digests(run)) } else { out += run.map(SourceGroup.one) }
            run = []
        }
        for s in sources {
            if s.day != nil { run.append(s) } else { flush(); out.append(.one(s)) }
        }
        flush()
        return out
    }

    private static let dayOnly: DateFormatter = { let f = DateFormatter(); f.dateFormat = "d"; return f }()
    private static let dayMonth: DateFormatter = { let f = DateFormatter(); f.dateFormat = "d MMM"; return f }()
    private static let longDay: DateFormatter = { let f = DateFormatter(); f.dateFormat = "d MMMM"; return f }()

    /// "12–18 Oct", or "28 Sep – 4 Oct" across a month; long form for VoiceOver.
    static func span(_ days: [Date], long: Bool = false) -> String {
        guard let a = days.min(), let b = days.max() else { return "" }
        if long { return "\(longDay.string(from: a)) to \(longDay.string(from: b))" }
        let sameMonth = Calendar.current.isDate(a, equalTo: b, toGranularity: .month)
        return sameMonth ? "\(dayOnly.string(from: a))–\(dayMonth.string(from: b))"
                         : "\(dayMonth.string(from: a)) – \(dayMonth.string(from: b))"
    }
}

struct SourcePills: View {
    let sources: [AskSource]
    let open: (AskSource) -> Void
    @State private var expanded = false

    var body: some View {
        FlowLayout(spacing: 5, lineSpacing: 5) {
            ForEach(Array(SourceGroup.group(sources).enumerated()), id: \.offset) { _, g in
                switch g {
                case .one(let s):
                    SourcePill(source: s) { open(s) }
                case .digests(let run):
                    DigestRunPill(run: run, expanded: expanded) { expanded.toggle() }
                    if expanded {
                        ForEach(run, id: \.path) { s in
                            SourcePill(source: s, showsTag: false) { open(s) }.transition(.opacity)
                        }
                    }
                }
            }
        }
        .motion(Motion.glide, value: expanded)
    }
}

/// The folded week: the same pill, with a count and a disclosure chevron.
private struct DigestRunPill: View {
    let run: [AskSource]
    let expanded: Bool
    let toggle: () -> Void
    @State private var hover = false

    var body: some View {
        let days = run.compactMap(\.day)
        Button(action: toggle) {
            HStack(spacing: 5) {
                SourceDot(tag: .digest)
                Text("digest").font(.klMeta).foregroundStyle(.secondary)
                Text("\(SourceGroup.span(days)) (\(run.count) days)").font(.klLabel).foregroundStyle(.primary)
                    .lineLimit(1)
                Image(systemName: "chevron.right").font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .rotationEffect(.degrees(expanded ? 90 : 0))
                    .accessibilityHidden(true)
            }
            .padding(.leading, 7).padding(.trailing, 9).padding(.vertical, 3)
            .background(Capsule().fill(Color.primary.opacity(hover ? 0.11 : 0.06)))
            .overlay(Capsule().strokeBorder(Color.primary.opacity(hover ? 0.2 : 0.12)))
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help(expanded ? "Hide the \(run.count) daily digests" : "Show the \(run.count) daily digests")
        .accessibilityLabel("\(run.count) daily digests, \(SourceGroup.span(days, long: true))")
        .accessibilityValue(expanded ? "expanded" : "collapsed")
        .accessibilityHint(expanded ? "Hides them" : "Shows each one")
    }
}
