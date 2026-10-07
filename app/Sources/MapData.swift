import Foundation
import SwiftUI

// Plasmie's map: the data side. plasmie-graph.py prints the vault as JSON (nodes, undirected
// link edges, and suggested edges: text neighbours from related.py, never counted as
// links); this file decodes it defensively and derives what the map needs once:
// each note's kind and colour, its size, how fresh it is, which notes Plasmie grows a vein
// to directly, and how many hops each note is from Plasmie (pulses flow down that slope).

struct GraphReport: Decodable {
    var nodes: [GraphNodeDTO]?
    var edges: [[Int]]?
    var suggested: [[Int]]?
    var error: String?
}

struct GraphNodeDTO: Decodable {
    var id: String
    var title: String?
    var type: String?
    var tags: [String]?
    var date: String?
    var links: Int?
    var hub: Bool?
    var excerpt: String?
}

struct MapNode: Identifiable {
    let id: Int
    let path: String           // vault-relative
    let title: String
    let type: String
    let kind: MapKind
    let tags: [String]
    let dateText: String?
    let links: Int
    let excerpt: String
    let radius: Double         // world units
    let fresh: Double          // 1 = filed today, 0 = half a year or older
    let freshLevel: Int        // fresh quantised to 0...3 (colour buckets)
    let seed: Double           // stable 0...1 per note (breathing phase, vein bend side)
}

struct MapGraph {
    let nodes: [MapNode]
    let edges: [(Int, Int)]
    let suggested: [(Int, Int)]     // drawn faint and dashed; weak springs; not links
    let neighbours: [[Int]]         // real links only (focus, link counts)
    let anchors: [Int]         // notes Plasmie connects to directly
    let depth: [Int]           // hops from Plasmie (anchors = 1)
    let nextHome: [Int]        // the neighbour one hop closer to Plasmie (-1 = Plasmie itself)

    static let plasmieRadius = 40.0
    static let freshDays = 180.0

    var isEmpty: Bool { nodes.isEmpty }

    init(report: GraphReport, today: Date = Date()) {
        let dtos = report.nodes ?? []
        let fmt = DateFormatter()
        fmt.locale = Locale(identifier: "en_US_POSIX")
        fmt.dateFormat = "yyyy-MM-dd"
        var nodes: [MapNode] = []
        nodes.reserveCapacity(dtos.count)
        for (i, d) in dtos.enumerated() {
            let type = (d.type ?? "note").lowercased()
            let kind = MapKind(type: type, hub: d.hub ?? false)
            let links = max(d.links ?? 0, 0)
            let age = d.date.flatMap { fmt.date(from: $0) }.map { today.timeIntervalSince($0) / 86_400 } ?? Self.freshDays
            let fresh = 1 - min(max(age / Self.freshDays, 0), 1)
            // minute beside Plasmie (72 pt): a dust of notes 2-5, maps 5.5-6.5 (+ ring), sqrt of links
            let r = kind == .map ? min(5.5 + 0.08 * Double(links).squareRoot(), 6.5) : min(2 + 0.35 * Double(links).squareRoot(), 5)
            nodes.append(MapNode(id: i, path: d.id, title: d.title ?? d.id, type: type, kind: kind, tags: d.tags ?? [],
                                 dateText: d.date, links: links, excerpt: d.excerpt ?? "", radius: r,
                                 fresh: fresh, freshLevel: min(Int(fresh * 4), 3), seed: MapGraph.hash01(d.id)))
        }
        var nb = Array(repeating: [Int](), count: nodes.count)
        var edges: [(Int, Int)] = []
        for e in report.edges ?? [] where e.count == 2 {
            let a = e[0], b = e[1]
            guard a != b, nodes.indices.contains(a), nodes.indices.contains(b) else { continue }
            edges.append((a, b)); nb[a].append(b); nb[b].append(a)
        }
        // structure (which notes Plasmie reaches directly, and the way home) uses suggestions
        // too: a cluster of related notes hangs together instead of every note floating alone
        var reach = nb
        var sug: [(Int, Int)] = []
        for e in report.suggested ?? [] where e.count == 2 {
            let a = e[0], b = e[1]
            guard a != b, nodes.indices.contains(a), nodes.indices.contains(b) else { continue }
            sug.append((a, b)); reach[a].append(b); reach[b].append(a)
        }
        self.nodes = nodes
        self.edges = edges
        self.suggested = sug
        self.neighbours = nb
        self.anchors = MapGraph.pickAnchors(nodes, reach)
        (self.depth, self.nextHome) = MapGraph.hops(count: nodes.count, anchors: anchors, reach)
    }

    /// Maps (mocs) first; topped up with the most-linked notes so a vault without maps still
    /// has a few veins home; then one note per otherwise-unconnected island, so nothing floats.
    private static func pickAnchors(_ nodes: [MapNode], _ nb: [[Int]]) -> [Int] {
        var picked = nodes.filter { $0.kind == .map }.map(\.id)
        if picked.count < 8 {
            let rest = nodes.filter { $0.kind != .map }.sorted { ($0.links, $1.id) > ($1.links, $0.id) }
            picked += rest.prefix(8 - picked.count).map(\.id)
        }
        var seen = Set(picked)
        var stack = picked
        let roots = nodes.sorted(by: { ($0.links, $1.id) > ($1.links, $0.id) }).map(\.id)
        var r = 0
        while true {
            while let i = stack.popLast() { for j in nb[i] where seen.insert(j).inserted { stack.append(j) } }
            while r < roots.count, seen.contains(roots[r]) { r += 1 }
            guard r < roots.count else { break }
            picked.append(roots[r]); seen.insert(roots[r]); stack = [roots[r]]
        }
        return picked.sorted()
    }

    /// Breadth-first from Plasmie: every note's distance home and its first step back.
    private static func hops(count: Int, anchors: [Int], _ nb: [[Int]]) -> ([Int], [Int]) {
        var depth = Array(repeating: Int.max, count: count)
        var next = Array(repeating: -1, count: count)
        var queue: [Int] = []
        for a in anchors { depth[a] = 1; queue.append(a) }
        var head = 0
        while head < queue.count {
            let i = queue[head]; head += 1
            for j in nb[i] where depth[j] == Int.max {
                depth[j] = depth[i] + 1; next[j] = i; queue.append(j)
            }
        }
        return (depth.map { $0 == Int.max ? 1 : $0 }, next)
    }

    /// FNV-1a of the path -> 0...1. Stable across launches (Swift's hashValue is not).
    static func hash01(_ s: String) -> Double {
        var h: UInt64 = 0xcbf2_9ce4_8422_2325
        for b in s.utf8 { h ^= UInt64(b); h = h &* 0x100_0000_01b3 }
        return Double(h >> 11) / Double(1 << 53)
    }
}

enum MapLoad {
    case loading
    case failed(String)
    case ready(MapGraph)
}

/// Runs plasmie-graph.py off the main thread (bounded) and decodes it.
func loadGraph(timeout: TimeInterval = 60) -> Result<GraphReport, Error> {
    struct Failure: LocalizedError { let errorDescription: String? }
    let out = runCapture(PlasmiePaths.python, [PlasmiePaths.script("plasmie-graph.py")], timeout: timeout)
    guard let start = out.firstIndex(of: "{"), let data = String(out[start...]).data(using: .utf8),
          let r = try? JSONDecoder().decode(GraphReport.self, from: data) else {
        return .failure(Failure(errorDescription: out.isEmpty ? "The map script didn't answer in time."
                                                              : "The map script returned something unreadable."))
    }
    if let e = r.error, (r.nodes ?? []).isEmpty, e != "no vault folder" {
        return .failure(Failure(errorDescription: e))
    }
    return .success(r)
}
