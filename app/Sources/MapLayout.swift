import Foundation

// Plasmie's map: the physics. A force-directed layout in the d3-force tradition, sized for
// a few thousand notes:
//   - repulsion between every pair of notes, Barnes-Hut (quadtree, theta 0.9): O(n log n)
//   - spring edges (rest length grows with the blobs' sizes; strength 1/min(degree) with
//     d3's degree bias, so a map with 170 links doesn't crush its notes together)
//   - a spring from Plasmie (pinned at the origin) to each anchor note
//   - gentle gravity toward Plasmie, and a collision pass (grid buckets) so blobs never overlap
// `alpha` cools from 1 toward 0 over ~300 ticks; below `alphaMin` the layout is settled and
// the view stops ticking (no CPU when idle). Dragging reheats it a little. Initial positions
// are seeded from each note's path, and a tick count (not wall time) drives it, so the same
// vault always settles into the same map.

final class MapLayout {
    private(set) var x: [Double]
    private(set) var y: [Double]
    private var vx: [Double]
    private var vy: [Double]
    private let r: [Double]
    private let mass: [Double]
    private let edges: [(Int, Int)]
    private let edgeLen: [Double]
    private let edgeK: [Double]
    private let edgeBias: [Double]
    private let anchors: [Int]
    private let n: Int

    private(set) var alpha = 1.0
    private var alphaTarget = 0.0
    static let alphaMin = 0.003
    private let alphaDecay = 1 - pow(MapLayout.alphaMin, 1.0 / 300)
    private let velocityDecay = 0.42
    private let charge = -46.0
    private let theta2 = 0.81
    private let gravity = 0.035
    private let anchorLen = MapGraph.plasmieRadius + 90

    private(set) var pinned: Int?
    private var pinX = 0.0, pinY = 0.0
    private(set) var ticks = 0

    var settled: Bool { alpha < Self.alphaMin && alphaTarget == 0 }

    init(_ g: MapGraph) {
        n = g.nodes.count
        r = g.nodes.map(\.radius)
        mass = g.nodes.map { 0.6 + $0.radius / 10 }
        // suggested links are springs too, at a third of the strength and a little longer:
        // related notes drift together without pretending to be linked
        let all = g.edges + g.suggested
        let real = g.edges.count
        edges = all
        anchors = g.anchors
        var degs = Array(repeating: 0, count: g.nodes.count)
        for (a, b) in all { degs[a] += 1; degs[b] += 1 }
        let deg = degs.map { max($0, 1) }
        edgeLen = all.enumerated().map { k, e in (k < real ? 18 : 26) + g.nodes[e.0].radius + g.nodes[e.1].radius }
        edgeK = all.enumerated().map { k, e in (k < real ? 1 : 0.35) / Double(min(deg[e.0], deg[e.1])) }
        edgeBias = all.map { Double(deg[$0.0]) / Double(deg[$0.0] + deg[$0.1]) }
        // seeded start: a golden-angle disc, anchors on the inside, each note's angle nudged
        // by its own path hash so a new note doesn't reshuffle everyone else
        let order = g.nodes.indices.sorted { (g.depth[$0], g.nodes[$0].seed) < (g.depth[$1], g.nodes[$1].seed) }
        var px = Array(repeating: 0.0, count: n), py = px
        for (k, i) in order.enumerated() {
            let rad = MapGraph.plasmieRadius + 30 + 14 * Double(k).squareRoot()
            let a = Double(k) * 2.399_963 + g.nodes[i].seed * 0.6
            px[i] = rad * cos(a); py[i] = rad * sin(a)
        }
        x = px; y = py
        vx = Array(repeating: 0, count: n); vy = vx
    }

    // MARK: control

    func reheat(_ a: Double = 0.3) { alpha = max(alpha, a) }

    func pin(_ i: Int, at px: Double, _ py: Double) {
        pinned = i; pinX = px; pinY = py
        alphaTarget = 0.25; reheat(0.25)
    }

    func unpin() { pinned = nil; alphaTarget = 0 }

    /// Ticks until settled (Reduce Motion, and the head start before the first frame).
    func run(maxTicks: Int) { var k = 0; while !settled && k < maxTicks { tick(); k += 1 } }

    // MARK: one step

    func tick() {
        guard n > 0 else { alpha = 0; return }
        alpha += (alphaTarget - alpha) * alphaDecay
        ticks += 1
        repel()
        springs()
        home()
        integrate()
        collide()
    }

    private func springs() {
        for (k, e) in edges.enumerated() {
            let (a, b) = e
            var dx = x[b] + vx[b] - x[a] - vx[a], dy = y[b] + vy[b] - y[a] - vy[a]
            var l = (dx * dx + dy * dy).squareRoot()
            if l < 1e-6 { dx = 1e-3; dy = 0; l = 1e-3 }
            let f = (l - edgeLen[k]) / l * alpha * edgeK[k]
            dx *= f; dy *= f
            let bias = edgeBias[k]
            vx[b] -= dx * bias; vy[b] -= dy * bias
            vx[a] += dx * (1 - bias); vy[a] += dy * (1 - bias)
        }
    }

    /// Anchors spring to Plasmie; everyone feels a little gravity and Plasmie's body.
    private func home() {
        for i in anchors {
            let l = max((x[i] * x[i] + y[i] * y[i]).squareRoot(), 1e-3)
            let f = (l - anchorLen - r[i]) / l * alpha * 0.12
            vx[i] -= x[i] * f; vy[i] -= y[i] * f
        }
        let keepOut = MapGraph.plasmieRadius + 34          // a clearing around Plasmie
        for i in 0..<n {
            vx[i] -= x[i] * gravity * alpha
            vy[i] -= y[i] * gravity * alpha
            let d = max((x[i] * x[i] + y[i] * y[i]).squareRoot(), 1e-3)
            let min = keepOut + r[i]
            if d < min { let push = (min - d) / d * 0.5; vx[i] += x[i] * push; vy[i] += y[i] * push }
        }
    }

    private func integrate() {
        let keep = 1 - velocityDecay
        for i in 0..<n {
            if i == pinned { x[i] = pinX; y[i] = pinY; vx[i] = 0; vy[i] = 0; continue }
            vx[i] *= keep; vy[i] *= keep
            x[i] += vx[i]; y[i] += vy[i]
        }
    }

    // MARK: collision (grid buckets: only near neighbours are checked)

    private func collide() {
        let cell = 2 * (r.max() ?? 10) + 4
        var grid: [Int64: [Int]] = [:]
        grid.reserveCapacity(n)
        func key(_ cx: Int, _ cy: Int) -> Int64 { Int64(cx) << 32 | Int64(UInt32(bitPattern: Int32(cy))) }
        for i in 0..<n { grid[key(Int(floor(x[i] / cell)), Int(floor(y[i] / cell))), default: []].append(i) }
        for i in 0..<n {
            let cx = Int(floor(x[i] / cell)), cy = Int(floor(y[i] / cell))
            for ox in -1...1 { for oy in -1...1 {
                guard let bucket = grid[key(cx + ox, cy + oy)] else { continue }
                for j in bucket where j > i {
                    let dx = x[j] - x[i], dy = y[j] - y[i]
                    let min = r[i] + r[j] + 2.5
                    let d2 = dx * dx + dy * dy
                    guard d2 < min * min else { continue }
                    let d = max(d2.squareRoot(), 1e-3)
                    let push = (min - d) / d * 0.5
                    if i != pinned { x[i] -= dx * push; y[i] -= dy * push }
                    if j != pinned { x[j] += dx * push; y[j] += dy * push }
                }
            } }
        }
    }

    // MARK: Barnes-Hut repulsion

    private struct Cell {
        var x0: Double, y0: Double, size: Double
        var mx = 0.0, my = 0.0, m = 0.0
        var child = -1          // index of the first of 4 children; -1 = leaf
        var body = -1           // a leaf's single body (-1 = empty)
    }
    private var cells: [Cell] = []

    private func repel() {
        var minX = Double.infinity, minY = Double.infinity, maxX = -Double.infinity, maxY = -Double.infinity
        for i in 0..<n { minX = min(minX, x[i]); minY = min(minY, y[i]); maxX = max(maxX, x[i]); maxY = max(maxY, y[i]) }
        let size = max(maxX - minX, maxY - minY) + 1
        cells.removeAll(keepingCapacity: true)
        cells.append(Cell(x0: minX, y0: minY, size: size))
        for i in 0..<n { insert(i, 0, 0) }
        accumulate(0)
        var stack: [Int] = []
        stack.reserveCapacity(64)
        let k = charge * alpha
        for i in 0..<n {
            stack.append(0)
            while let c = stack.popLast() {
                let cell = cells[c]
                guard cell.m > 0 else { continue }
                var dx = cell.mx - x[i], dy = cell.my - y[i]
                var d2 = dx * dx + dy * dy
                if cell.child < 0 || cell.size * cell.size < theta2 * d2 {
                    if cell.child < 0 && cell.body == i { continue }
                    if d2 < 1e-6 { dx = 0.01 * (Double(i % 7) - 3); dy = 0.01; d2 = dx * dx + dy * dy }
                    d2 = max(d2, 9)
                    let f = k * cell.m / d2
                    vx[i] += dx * f; vy[i] += dy * f
                } else {
                    for q in 0..<4 { stack.append(cell.child + q) }
                }
            }
        }
    }

    private func insert(_ i: Int, _ c: Int, _ depth: Int) {
        if cells[c].child < 0 {
            if cells[c].body < 0 { cells[c].body = i; return }
            if depth > 18 { return }                          // coincident points: share the leaf
            let old = cells[c].body
            cells[c].body = -1
            split(c)
            insert(old, quadrant(old, c), depth + 1)
        }
        insert(i, quadrant(i, c), depth + 1)
    }

    private func split(_ c: Int) {
        let h = cells[c].size / 2, x0 = cells[c].x0, y0 = cells[c].y0
        cells[c].child = cells.count
        cells.append(Cell(x0: x0, y0: y0, size: h))
        cells.append(Cell(x0: x0 + h, y0: y0, size: h))
        cells.append(Cell(x0: x0, y0: y0 + h, size: h))
        cells.append(Cell(x0: x0 + h, y0: y0 + h, size: h))
    }

    private func quadrant(_ i: Int, _ c: Int) -> Int {
        let h = cells[c].size / 2
        return cells[c].child + (x[i] >= cells[c].x0 + h ? 1 : 0) + (y[i] >= cells[c].y0 + h ? 2 : 0)
    }

    private func accumulate(_ c: Int) {
        if cells[c].child < 0 {
            if cells[c].body >= 0 { let b = cells[c].body; cells[c].m = mass[b]; cells[c].mx = x[b]; cells[c].my = y[b] }
            return
        }
        var m = 0.0, mx = 0.0, my = 0.0
        for q in 0..<4 {
            let ch = cells[c].child + q
            accumulate(ch)
            m += cells[ch].m; mx += cells[ch].mx * cells[ch].m; my += cells[ch].my * cells[ch].m
        }
        cells[c].m = m
        if m > 0 { cells[c].mx = mx / m; cells[c].my = my / m }
    }
}
