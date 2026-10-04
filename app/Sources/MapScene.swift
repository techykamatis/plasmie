import AppKit
import SwiftUI

// Plasmie's map: the live state. One object owns the graph, the physics, the camera, what
// the pointer is over, and the clock. Every frame starts with `advance(to:)`, which steps
// the physics, the camera glide and the pulses, then decides whether the map may sleep:
// once the layout has settled, the camera has stopped and nobody has touched anything for
// a few seconds, `awake` goes false, the TimelineView pauses and the map costs nothing.

struct MapCamera: Equatable {
    var zoom = 1.0
    var x = 0.0                 // the world point at the centre of the view
    var y = 0.0
    static let minZoom = 0.15, maxZoom = 5.0
}

/// A nutrient pulse: a chain of notes walking downhill to Plasmie, one vein at a time.
struct MapPulse {
    let hops: [Int]             // notes, farthest first; after the last one comes Plasmie
    let start: Date
    static let perVein = 0.6
    var duration: Double { Double(hops.count) * Self.perVein }
}

final class MapScene: ObservableObject {
    @Published var load: MapLoad = .loading
    @Published private(set) var hovered: Int?
    @Published var listFocus: Int? { didSet { if listFocus != oldValue { focusChanged() } } }
    @Published private(set) var match: Int?
    @Published private(set) var cursor: CGPoint = .zero
    @Published private(set) var plasmieHover = false
    @Published private(set) var waveUntil = Date.distantPast
    @Published var search = "" { didSet { if search != oldValue { findMatch() } } }
    @Published var hidden: Set<MapKind> = [] { didSet { if hidden != oldValue { filterChanged() } } }
    @Published var listShown = false
    @Published private(set) var awake = true
    @Published private(set) var kindsPresent = MapKind.allCases   // filter chips: only kinds the vault has

    private(set) var graph: MapGraph?
    private(set) var layout: MapLayout?
    private(set) var camera = MapCamera()
    var size = CGSize(width: 900, height: 640)
    var reduceMotion = false
    var introAt = Date.distantPast             // the opening (MapIntro.swift)
    var introPose: MapIntroPose?
    var vault: () -> String = { NSString(string: "~/knowledge").expandingTildeInPath }

    // clocks
    private var lastTick = Date()
    private var tickDebt = 0.0
    private var lastInteraction = Date()
    private var glide: (from: MapCamera, to: MapCamera, start: Date)?
    private var userMovedCamera = false
    private var autoFitted = false
    private(set) var focusAt = Date.distantPast
    private(set) var focusFrom = 0.0           // dim level when the focus last changed
    private(set) var lastFocus: Int?           // kept while the dim fades out
    private(set) var prevFocus: Int?           // shrinking back while the new focus grows
    private var currentFocus: Int?
    private(set) var matchAt = Date.distantPast
    private(set) var pulses: [MapPulse] = []
    private var nextPulse = Date()
    private var pulseSeed: UInt64 = 0x9E37_79B9_7F4A_7C15

    // pointer
    private enum Grab { case none, node(Int), plasmie, background }
    private var grab = Grab.none
    private var downAt = CGPoint.zero
    private var downCamera = MapCamera()
    private var dragged = false

    let perf = MapPerf(enabled: CommandLine.arguments.contains("--map-perf"))

    // MARK: loading

    func reload() {
        load = .loading
        let reduce = reduceMotion
        DispatchQueue.global(qos: .userInitiated).async {
            let result = loadGraph()
            var built: (MapGraph, MapLayout)?
            if case .success(let r) = result {
                let g = MapGraph(report: r)
                let l = MapLayout(g)
                l.run(maxTicks: reduce ? 2000 : 40)      // Reduce Motion: arrive settled
                built = (g, l)
            }
            DispatchQueue.main.async {
                switch result {
                case .failure(let e): self.load = .failed(e.localizedDescription)
                case .success:
                    guard let (g, l) = built else { return }
                    self.graph = g; self.layout = l
                    self.kindsPresent = MapKind.allCases.filter { k in g.nodes.contains { $0.kind == k } }
                    self.camera = self.fitCamera(padding: 0.82)
                    self.autoFitted = false; self.userMovedCamera = false
                    self.startIntro()
                    self.load = .ready(g)
                    self.wake()
                }
            }
        }
    }

    // MARK: coordinates

    func screen(_ wx: Double, _ wy: Double, _ c: MapCamera? = nil) -> CGPoint {
        let c = c ?? camera
        let (wx, wy) = introApply(wx, wy)
        return CGPoint(x: size.width / 2 + (wx - c.x) * c.zoom, y: size.height / 2 + (wy - c.y) * c.zoom)
    }

    func world(_ p: CGPoint) -> (Double, Double) {
        (camera.x + (p.x - size.width / 2) / camera.zoom, camera.y + (p.y - size.height / 2) / camera.zoom)
    }

    var plasmieSize: Double {
        let normal = min(max(72 * camera.zoom, 56), 132)
        guard let p = introPose else { return normal }
        let huge = Self.loadingSize + (introHugeSize - Self.loadingSize) * p.swell
        return huge + (normal - huge) * p.snap
    }

    func visible(_ i: Int) -> Bool { graph.map { !hidden.contains($0.nodes[i].kind) } ?? false }

    // MARK: the frame clock

    /// Steps everything to `now`. Called at the top of each drawn frame.
    func advance(to now: Date) {
        let t0 = perf.enabled ? CFAbsoluteTimeGetCurrent() : 0
        if let l = layout, !l.settled {
            tickDebt = min(tickDebt + now.timeIntervalSince(lastTick) * 60, 3)
            while tickDebt >= 1 && !l.settled { l.tick(); tickDebt -= 1 }
            if l.settled && !autoFitted && !userMovedCamera { autoFitted = true; glide(to: fitCamera()) }
        }
        lastTick = now
        introPose = pose(at: now)
        let t1 = perf.enabled ? CFAbsoluteTimeGetCurrent() : 0
        if let g = glide {
            let p = now.timeIntervalSince(g.start) / (reduceMotion ? 0.15 : Motion.glideSeconds)
            let e = reduceMotion ? min(p, 1) : Motion.glideValue(p)
            camera = MapCamera(zoom: exp(log(g.from.zoom) + (log(g.to.zoom) - log(g.from.zoom)) * e),
                               x: g.from.x + (g.to.x - g.from.x) * e, y: g.from.y + (g.to.y - g.from.y) * e)
            if p >= 1 { camera = g.to; glide = nil }
        }
        stepPulses(now)
        perf.physics(CFAbsoluteTimeGetCurrent() - t1, total: t1 - t0)
        if !needsFrames(now) { DispatchQueue.main.async { if self.awake && !self.needsFrames(Date()) { self.awake = false } } }
    }

    /// Ambient life (breathing, pulses) lasts this long after the last touch.
    static let ambientSeconds = 8.0

    var ambient: Bool { !reduceMotion && sinceTouch(Date()) < Self.ambientSeconds }

    func sinceTouch(_ now: Date) -> Double { now.timeIntervalSince(lastInteraction) }

    private func needsFrames(_ now: Date) -> Bool {
        if let l = layout, !l.settled { return true }
        if glide != nil || introPose != nil { return true }
        if case .node = grab, dragged { return true }
        if now.timeIntervalSince(focusAt) < 0.6 || now.timeIntervalSince(matchAt) < 2.6 { return true }
        if now < waveUntil { return true }
        return !reduceMotion && (now.timeIntervalSince(lastInteraction) < Self.ambientSeconds || !pulses.isEmpty)
    }

    func wake() {
        lastInteraction = Date()
        if !awake { lastTick = Date(); awake = true }
    }

    // MARK: focus (hover, list, search) and dimming

    var focus: Int? { hovered ?? listFocus ?? match }

    /// 0...1: how far everything outside the focus is dimmed, at `now`.
    func dimLevel(_ now: Date) -> Double {
        let target = focus == nil ? 0.0 : 1.0
        let p = now.timeIntervalSince(focusAt) / (reduceMotion ? 0.15 : Motion.glideSeconds)
        let e = reduceMotion ? min(p, 1) : Motion.glideValue(p)
        return focusFrom + (target - focusFrom) * e
    }

    /// The focused note's grow factor (the `pop` spring, or a short ease under Reduce Motion).
    func grow(_ now: Date, factor: Double) -> Double {
        let t = now.timeIntervalSince(focusAt)
        return 1 + (factor - 1) * (reduceMotion ? min(t / 0.15, 1) : Motion.springValue(t))
    }

    private func focusChanged() {
        let now = Date()
        focusFrom = dimLevel(now)
        focusAt = now
        prevFocus = currentFocus
        currentFocus = focus
        if let f = focus { lastFocus = f }
        wake()
    }

    private func setHovered(_ i: Int?) {
        guard i != hovered else { return }
        hovered = i
        focusChanged()
    }

    // MARK: pointer

    func hit(_ p: CGPoint) -> Int? {
        guard let g = graph, let l = layout else { return nil }
        var best: Int?, bestD = Double.infinity
        for i in g.nodes.indices where visible(i) {
            let s = screen(l.x[i], l.y[i])
            let d = hypot(s.x - p.x, s.y - p.y)
            let reach = max(g.nodes[i].radius * camera.zoom + 4, 10)     // small blobs, generous target
            if d < reach && d < bestD { best = i; bestD = d }
        }
        return best
    }

    func overMascot(_ p: CGPoint) -> Bool {
        let o = screen(0, 0)
        return hypot(p.x - o.x, p.y - o.y) < plasmieSize * 0.45
    }

    func mouseMoved(_ p: CGPoint) {
        cursor = p
        if case .node = grab, dragged { return }
        let onMascot = overMascot(p)
        if onMascot != plasmieHover {
            plasmieHover = onMascot
            if onMascot { waveUntil = Date().addingTimeInterval(1.4) }
        }
        setHovered(onMascot ? nil : hit(p))
        wake()
    }

    func mouseExited() { setHovered(nil); plasmieHover = false }

    func mouseDown(_ p: CGPoint, clicks: Int) {
        skipIntro()
        downAt = p; downCamera = camera; dragged = false
        if overMascot(p) { grab = .plasmie } else if let i = hit(p) { grab = .node(i) } else { grab = .background }
        if clicks == 2, case .background = grab { fit() }
        wake()
    }

    func mouseDragged(_ p: CGPoint) {
        cursor = p
        if !dragged && hypot(p.x - downAt.x, p.y - downAt.y) < 3 { return }
        dragged = true
        switch grab {
        case .node(let i):
            let (wx, wy) = world(p)
            layout?.pin(i, at: wx, wy)
            if hovered != i { setHovered(i) }
        case .background, .plasmie:
            glide = nil; userMovedCamera = true
            camera.x = downCamera.x - (p.x - downAt.x) / camera.zoom
            camera.y = downCamera.y - (p.y - downAt.y) / camera.zoom
        case .none: break
        }
        wake()
    }

    func mouseUp(_ p: CGPoint) {
        defer { grab = .none; dragged = false; wake() }
        if dragged { if case .node = grab { layout?.unpin(); layout?.reheat(0.12) }; return }
        switch grab {
        case .node(let i): open(i)
        case .plasmie:                                  // replay the opening (just a wave under Reduce Motion)
            if reduceMotion { waveUntil = Date().addingTimeInterval(1.4); fit() } else { glide = nil; camera = fitCamera(); startIntro() }
        default: break
        }
    }

    /// Mouse wheel zooms toward the pointer; a trackpad's two-finger scroll pans (pinch
    /// zooms, in `magnify`); holding ⌘ makes a trackpad scroll zoom too.
    func scroll(dx: Double, dy: Double, precise: Bool, command: Bool, at p: CGPoint) {
        skipIntro()
        if precise && !command {
            glide = nil; userMovedCamera = true
            camera.x -= dx / camera.zoom; camera.y -= dy / camera.zoom
        } else {
            zoom(by: min(max(exp(dy * (precise ? 0.01 : 0.04)), 0.8), 1.25), at: p)   // one notch ~ 4%, capped
        }
        wake()
    }

    func magnify(_ m: Double, at p: CGPoint) { skipIntro(); zoom(by: 1 + m, at: p); wake() }

    func zoom(by f: Double, at p: CGPoint? = nil) {
        glide = nil; userMovedCamera = true
        let p = p ?? CGPoint(x: size.width / 2, y: size.height / 2)
        let (wx, wy) = world(p)
        let z = min(max(camera.zoom * f, MapCamera.minZoom), MapCamera.maxZoom)
        camera = MapCamera(zoom: z, x: wx - (p.x - size.width / 2) / z, y: wy - (p.y - size.height / 2) / z)
        wake()
    }

    /// Button / ⌘+ ⌘− zoom: a glide about the centre.
    func zoomStep(_ f: Double) {
        let z = min(max((glide?.to ?? camera).zoom * f, MapCamera.minZoom), MapCamera.maxZoom)
        var to = glide?.to ?? camera
        to.zoom = z
        glide(to: to)
    }

    func fit() { glide(to: fitCamera()) }

    func glide(to c: MapCamera) {
        glide = (camera, c, Date())
        setHovered(nil)                 // the map moves under a still pointer: hover again to see a card
        userMovedCamera = true
        wake()
    }

    func show(_ i: Int) {
        guard let l = layout else { return }
        glide(to: MapCamera(zoom: max(camera.zoom, 1.4), x: l.x[i], y: l.y[i]))
    }

    func fitCamera(padding: Double = 0.88) -> MapCamera {
        guard let g = graph, let l = layout else { return MapCamera() }
        var x0 = -MapGraph.plasmieRadius, x1 = MapGraph.plasmieRadius, y0 = x0, y1 = x1
        for i in g.nodes.indices where visible(i) {
            let r = g.nodes[i].radius
            x0 = min(x0, l.x[i] - r); x1 = max(x1, l.x[i] + r); y0 = min(y0, l.y[i] - r); y1 = max(y1, l.y[i] + r)
        }
        // Plasmie stays the centre of the view: fit the farthest reach on each axis around it
        let z = min(size.width / (2 * max(-x0, x1)), size.height / (2 * max(-y0, y1))) * padding
        return MapCamera(zoom: min(max(z, MapCamera.minZoom), 2), x: 0, y: 0)
    }

    func open(_ i: Int) {
        guard let g = graph else { return }
        openInObsidian("\(vault())/\(g.nodes[i].path)")
    }

    /// Esc: clear the search, then the hover.
    func clear() {
        if !search.isEmpty { search = "" } else { setHovered(nil); listFocus = nil }
    }

    // MARK: search and filters

    private func findMatch() {
        let q = search.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty, let g = graph else { setMatch(nil); return }
        let hits = g.nodes.filter { visible($0.id) && $0.title.lowercased().contains(q) }
        let best = hits.min { a, b in
            let pa = a.title.lowercased().hasPrefix(q), pb = b.title.lowercased().hasPrefix(q)
            return pa != pb ? pa : (a.title.count, a.id) < (b.title.count, b.id)
        }
        setMatch(best?.id)
        if let b = best { show(b.id) }
    }

    private func setMatch(_ i: Int?) {
        guard i != match else { return }
        match = i
        matchAt = Date()
        focusChanged()
    }

    private func filterChanged() {
        if let h = hovered, !visible(h) { setHovered(nil) }
        if let m = match, !visible(m) { setMatch(nil) }
        wake()
    }

    // MARK: pulses (nutrients flowing home)

    private func stepPulses(_ now: Date) {
        pulses.removeAll { now.timeIntervalSince($0.start) > $0.duration }
        guard ambient, let g = graph, !g.isEmpty, now >= nextPulse, pulses.count < 4 else { return }
        nextPulse = now.addingTimeInterval(0.5 + 0.6 * random())
        var i = Int(random() * Double(g.nodes.count)) % g.nodes.count
        var hops = [i]
        while g.nextHome[i] >= 0 && hops.count < 5 { i = g.nextHome[i]; hops.append(i) }
        if hops.allSatisfy(visible) { pulses.append(MapPulse(hops: hops, start: now)) }
    }

    private func random() -> Double {   // splitmix64: cheap, and repeatable per window
        pulseSeed &+= 0x9E37_79B9_7F4A_7C15
        var z = pulseSeed
        z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
        z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
        return Double((z ^ (z >> 31)) >> 11) / Double(1 << 53)
    }
}

/// `--map-perf`: logs frames per second and per-frame costs every two seconds.
final class MapPerf {
    let enabled: Bool
    private var frames = 0, physicsT = 0.0, drawT = 0.0, windowStart = CFAbsoluteTimeGetCurrent()
    init(enabled: Bool) { self.enabled = enabled }
    func physics(_ s: Double, total: Double) { if enabled { physicsT += s + total } }
    func frame(draw s: Double, nodes: Int, edges: Int) {
        guard enabled else { return }
        frames += 1; drawT += s
        let now = CFAbsoluteTimeGetCurrent(), span = now - windowStart
        guard span >= 2 else { return }
        NSLog("map perf: %.1f fps, draw %.2f ms/frame, physics+clock %.2f ms/frame, %d nodes, %d edges",
              Double(frames) / span, drawT / Double(frames) * 1000, physicsT / Double(frames) * 1000, nodes, edges)
        frames = 0; physicsT = 0; drawT = 0; windowStart = now
    }
}
