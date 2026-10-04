import SwiftUI

// Plasmie's map: drawing. One Canvas, no view per note. Everything of one look is batched
// into one Path and filled once (all veins; each kind x freshness bucket of blobs), so a
// frame is a few dozen fills however big the vault is. World space (the physics) is drawn
// through one camera transform; labels, pulses and the search ring are drawn in screen
// space so they keep a readable size at every zoom.

private let freshBuckets = 4

extension MapScene {
    func draw(_ ctx: GraphicsContext, now: Date, scheme: ColorScheme) {
        let t0 = CFAbsoluteTimeGetCurrent()
        drawGround(ctx, scheme)
        guard let g = graph, let l = layout, !g.isEmpty else { return }
        let dim = dimLevel(now)
        let shownFocus = focus ?? (dim > 0.001 ? lastFocus : nil)
        var focusSet = Set<Int>()
        if let f = shownFocus { focusSet.insert(f); focusSet.formUnion(g.neighbours[f]) }

        var w = ctx
        w.translateBy(x: size.width / 2 - camera.x * camera.zoom, y: size.height / 2 - camera.y * camera.zoom)
        w.scaleBy(x: camera.zoom, y: camera.zoom)
        if let p = introPose { w.rotate(by: .radians(p.spin)); w.scaleBy(x: p.spread, y: p.spread) }
        let view = worldViewport(margin: 40)
        let breath = breathAmplitude(now)

        w.drawLayer { base in
            base.opacity = 1 - 0.72 * dim
            drawVeins(base, g, l, scheme, view: view, only: nil)
            drawFreshGlow(base, g, l, scheme, view: view)
            drawBlobs(base, g, l, scheme, view: view, only: nil, now: now, breath: breath)
        }
        if dim > 0.001, let f = shownFocus {
            w.drawLayer { top in
                top.opacity = dim
                drawVeins(top, g, l, scheme, view: view, only: f)
                drawBlobs(top, g, l, scheme, view: view, only: focusSet, now: now, breath: breath)
            }
        }
        drawPulses(ctx, g, l, scheme, now: now)
        drawMatchRing(ctx, g, l, scheme, now: now)
        drawLabels(ctx, g, l, scheme, focusSet: dim > 0.3 ? focusSet : [], focus: shownFocus, dim: dim)
        drawIntroWave(ctx, scheme)
        drawIntroArms(ctx, scheme)
        perf.frame(draw: CFAbsoluteTimeGetCurrent() - t0, nodes: g.nodes.count, edges: g.edges.count)
    }

    // MARK: ground

    /// Brand ground plus a faint dot grid that drifts at half the camera's speed (parallax)
    /// and spaces out only gently with zoom.
    private func drawGround(_ ctx: GraphicsContext, _ s: ColorScheme) {
        ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(MapPalette.ground(s)))
        let step = 26 * pow(camera.zoom, 0.3)
        let ox = (-camera.x * camera.zoom * 0.5).truncatingRemainder(dividingBy: step)
        let oy = (-camera.y * camera.zoom * 0.5).truncatingRemainder(dividingBy: step)
        var dots = Path()
        var y = oy - step
        while y < size.height + step {
            var x = ox - step
            while x < size.width + step { dots.addEllipse(in: CGRect(x: x - 1, y: y - 1, width: 2, height: 2)); x += step }
            y += step
        }
        let dot = MapPalette.ink(s).opacity(s == .dark ? 0.09 : 0.08)
        ctx.fill(dots, with: .color(dot))
    }

    private func worldViewport(margin: Double) -> CGRect {
        if introPose != nil { return .infinite }       // mid-burst, off-screen notes fly in
        let (x0, y0) = world(CGPoint(x: -margin, y: -margin))
        let (x1, y1) = world(CGPoint(x: size.width + margin, y: size.height + margin))
        return CGRect(x: x0, y: y0, width: x1 - x0, height: y1 - y0)
    }

    private func breathAmplitude(_ now: Date) -> Double {
        guard ambient else { return 0 }
        return 0.035 * min(max((Self.ambientSeconds - 1.5 - sinceTouch(now)) / 1.5, 0), 1)
    }

    // MARK: veins

    private func halfWidth(_ n: MapNode) -> Double { min(0.22 + 0.03 * Double(n.links).squareRoot(), 0.5) }

    /// A vein's bend: a quadratic Bézier control point, computed from the pair in canonical
    /// order so the vein and a pulse travelling either way share one curve.
    func veinControl(_ a: Int, _ b: Int, _ l: MapLayout, _ g: MapGraph) -> CGPoint {
        let (p, q) = a < b ? (a, b) : (b, a)
        let (px, py) = p < 0 ? (0.0, 0.0) : (l.x[p], l.y[p])
        let (qx, qy) = (l.x[q], l.y[q])
        let side = (p < 0 ? g.nodes[q].seed : (g.nodes[p].seed + g.nodes[q].seed) / 2) < 0.5 ? -1.0 : 1.0
        let bend = (p < 0 ? 0.16 : 0.11) * side
        return CGPoint(x: (px + qx) / 2 - (qy - py) * bend, y: (py + qy) / 2 + (qx - px) * bend)
    }

    /// A tapered vein: the curve offset by half-widths w0 at `a` and w1 at `b`, as one shape.
    private func addVein(_ path: inout Path, _ a: CGPoint, _ c: CGPoint, _ b: CGPoint, _ w0: Double, _ w1: Double) {
        func normal(_ u: CGPoint, _ v: CGPoint) -> CGPoint {
            let dx = v.x - u.x, dy = v.y - u.y, len = max(hypot(dx, dy), 1e-6)
            return CGPoint(x: -dy / len, y: dx / len)
        }
        let n0 = normal(a, c), n1 = normal(c, b), nm = normal(a, b), wm = (w0 + w1) / 2
        path.move(to: CGPoint(x: a.x + n0.x * w0, y: a.y + n0.y * w0))
        path.addQuadCurve(to: CGPoint(x: b.x + n1.x * w1, y: b.y + n1.y * w1),
                          control: CGPoint(x: c.x + nm.x * wm, y: c.y + nm.y * wm))
        path.addLine(to: CGPoint(x: b.x - n1.x * w1, y: b.y - n1.y * w1))
        path.addQuadCurve(to: CGPoint(x: a.x - n0.x * w0, y: a.y - n0.y * w0),
                          control: CGPoint(x: c.x - nm.x * wm, y: c.y - nm.y * wm))
        path.closeSubpath()
    }

    /// All veins (only == nil), or just the ones touching `only`, lit.
    private func drawVeins(_ ctx: GraphicsContext, _ g: MapGraph, _ l: MapLayout, _ s: ColorScheme,
                           view: CGRect, only: Int?) {
        let floorW = 0.22 / camera.zoom
        let k = pow(camera.zoom, -0.4)                     // veins thicken slower than the blobs zoom
        var veins = Path()
        func outside(_ ax: Double, _ ay: Double, _ bx: Double, _ by: Double) -> Bool {
            (ax < view.minX && bx < view.minX) || (ax > view.maxX && bx > view.maxX)
                || (ay < view.minY && by < view.minY) || (ay > view.maxY && by > view.maxY)
        }
        for (a, b) in g.edges {
            if let f = only, a != f && b != f { continue }
            guard visible(a), visible(b), !outside(l.x[a], l.y[a], l.x[b], l.y[b]) else { continue }
            addVein(&veins, CGPoint(x: l.x[a], y: l.y[a]), veinControl(a, b, l, g), CGPoint(x: l.x[b], y: l.y[b]),
                    max(halfWidth(g.nodes[a]) * k, floorW), max(halfWidth(g.nodes[b]) * k, floorW))
        }
        // Plasmie's own veins (to the maps): drawn as their own, stronger layer, so the
        // network visibly grows out of the blob in the middle
        var home = Path()
        for a in g.anchors where visible(a) && (only == nil || only == a) {
            guard !outside(0, 0, l.x[a], l.y[a]) else { continue }
            addVein(&home, .zero, veinControl(-1, a, l, g), CGPoint(x: l.x[a], y: l.y[a]),
                    max(1.8 * k, floorW), max(halfWidth(g.nodes[a]) * k, floorW))
        }
        if only == nil {
            ctx.fill(veins, with: .color(MapPalette.ink(s).opacity(s == .dark ? 0.13 : 0.12)))
            ctx.fill(home, with: .color(MapPalette.ink(s).opacity(s == .dark ? 0.30 : 0.26)))
        } else {
            veins.addPath(home)
            ctx.drawLayer { glow in                               // the vein glow: the one lit effect
                glow.addFilter(.blur(radius: 3 * camera.zoom))
                glow.fill(veins, with: .color(MapPalette.glow(s).opacity(s == .dark ? 0.45 : 0.6)))
            }
            ctx.fill(veins, with: .color(MapPalette.ink(s).opacity(0.7)))
        }
    }

    // MARK: blobs

    /// Hovered blobs grow to ~4x (at most 12 world units), so even a dust mote is easy to see.
    private func hoverFactor(_ i: Int) -> Double {
        guard let g = graph else { return 1 }
        return min(4, max(12 / g.nodes[i].radius, 1.5))
    }

    private func scale(_ i: Int, _ now: Date) -> Double {
        if i == focus { return grow(now, factor: hoverFactor(i)) }
        if i == prevFocus {
            let p = now.timeIntervalSince(focusAt) / (reduceMotion ? 0.15 : Motion.glideSeconds)
            return 1 + (hoverFactor(i) - 1) * (1 - (reduceMotion ? min(p, 1) : Motion.glideValue(p)))
        }
        return 1
    }

    private func drawBlobs(_ ctx: GraphicsContext, _ g: MapGraph, _ l: MapLayout, _ s: ColorScheme,
                           view: CGRect, only: Set<Int>?, now: Date, breath: Double) {
        let kinds = MapKind.allCases.count
        var fills = Array(repeating: Path(), count: kinds * freshBuckets)
        var rims = Array(repeating: Path(), count: kinds)
        var rings = Path(), sheens = Path()
        let tt = now.timeIntervalSinceReferenceDate
        for n in g.nodes {
            let i = n.id
            if let o = only, !o.contains(i) { continue }
            guard visible(i), view.contains(CGPoint(x: l.x[i], y: l.y[i])) else { continue }
            let b = breath * sin(2 * .pi * (tt / 2.6 + n.seed))
            let r = n.radius * scale(i, now)
            let rect = CGRect(x: l.x[i] - r * (1 + b), y: l.y[i] - r * (1 - b), width: 2 * r * (1 + b), height: 2 * r * (1 - b))
            fills[n.kind.rawValue * freshBuckets + n.freshLevel].addEllipse(in: rect)
            rims[n.kind.rawValue].addEllipse(in: rect)
            if n.kind == .map { rings.addEllipse(in: rect.insetBy(dx: -1.6, dy: -1.6)) }
            if r * camera.zoom >= 6 {
                sheens.addEllipse(in: CGRect(x: l.x[i] - r * 0.55, y: l.y[i] - r * 0.62, width: r * 0.55, height: r * 0.36))
            }
        }
        let rimW = max(0.5, 0.5 / camera.zoom)
        if !rings.isEmpty {
            ctx.stroke(rings, with: .color(MapPalette.ring(s)), lineWidth: max(0.9, 0.7 / camera.zoom))
        }
        for k in MapKind.allCases {
            for f in 0..<freshBuckets where !fills[k.rawValue * freshBuckets + f].isEmpty {
                ctx.fill(fills[k.rawValue * freshBuckets + f], with: .color(k.fill(s, fresh: (Double(f) + 0.5) / Double(freshBuckets))))
            }
            if !rims[k.rawValue].isEmpty { ctx.stroke(rims[k.rawValue], with: .color(k.rim(s).opacity(0.7)), lineWidth: rimW) }
        }
        ctx.fill(sheens, with: .color(PlasmieHues.eggshell.color(s).opacity(s == .dark ? 0.35 : 0.5)))
    }

    /// Fresh notes (the newest bucket) glow softly.
    private func drawFreshGlow(_ ctx: GraphicsContext, _ g: MapGraph, _ l: MapLayout, _ s: ColorScheme, view: CGRect) {
        var glow = Array(repeating: Path(), count: MapKind.allCases.count)
        for n in g.nodes where n.freshLevel == freshBuckets - 1 && n.kind.glowsWhenFresh && visible(n.id) {
            let p = CGPoint(x: l.x[n.id], y: l.y[n.id])
            guard view.contains(p) else { continue }
            let r = n.radius * 1.7
            glow[n.kind.rawValue].addEllipse(in: CGRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r))
        }
        guard glow.contains(where: { !$0.isEmpty }) else { return }
        ctx.drawLayer { c in
            c.addFilter(.blur(radius: 5 * camera.zoom))
            for k in MapKind.allCases where !glow[k.rawValue].isEmpty {
                c.fill(glow[k.rawValue], with: .color(k.fill(s, fresh: 1).opacity(0.45)))
            }
        }
    }

    // MARK: pulses, search ring, labels (screen space)

    private func drawPulses(_ ctx: GraphicsContext, _ g: MapGraph, _ l: MapLayout, _ s: ColorScheme, now: Date) {
        guard !pulses.isEmpty else { return }
        var cores = Path(), halos = Path()
        for p in pulses {
            let t = now.timeIntervalSince(p.start) / MapPulse.perVein
            let k = min(Int(t), p.hops.count - 1), u = t - Double(k)
            let a = p.hops[k], b = k + 1 < p.hops.count ? p.hops[k + 1] : -1
            let pa = CGPoint(x: l.x[a], y: l.y[a]), pb = b < 0 ? CGPoint.zero : CGPoint(x: l.x[b], y: l.y[b])
            let c = veinControl(a, b, l, g)
            let v = 1 - u
            let w = CGPoint(x: v * v * pa.x + 2 * v * u * c.x + u * u * pb.x, y: v * v * pa.y + 2 * v * u * c.y + u * u * pb.y)
            let sp = screen(w.x, w.y)
            let fade = min(t / 0.3, 1) * min((p.duration / MapPulse.perVein - t) / 0.3, 1)
            let r = 2.6 * max(fade, 0.2)
            cores.addEllipse(in: CGRect(x: sp.x - r, y: sp.y - r, width: 2 * r, height: 2 * r))
            halos.addEllipse(in: CGRect(x: sp.x - 3 * r, y: sp.y - 3 * r, width: 6 * r, height: 6 * r))
        }
        ctx.drawLayer { c in                                       // the pulse glow
            c.addFilter(.blur(radius: 4))
            c.fill(halos, with: .color(MapPalette.glow(s).opacity(s == .dark ? 0.4 : 0.5)))
        }
        ctx.fill(cores, with: .color(MapPalette.pulse(s)))
    }

    private func drawMatchRing(_ ctx: GraphicsContext, _ g: MapGraph, _ l: MapLayout, _ s: ColorScheme, now: Date) {
        guard let m = match, visible(m) else { return }
        let c = screen(l.x[m], l.y[m])
        let base = g.nodes[m].radius * camera.zoom * scale(m, now) + 6
        let t = now.timeIntervalSince(matchAt)
        let phases = reduceMotion || t > 2.4 ? [0.0] : [Motion.frac(t / 1.2)]
        for p in phases {
            let r = base + 18 * p
            ctx.stroke(Path(ellipseIn: CGRect(x: c.x - r, y: c.y - r, width: 2 * r, height: 2 * r)),
                       with: .color(MapPalette.matchRing(s).opacity(1 - 0.8 * p)), lineWidth: 2)
        }
    }

    private func drawLabels(_ ctx: GraphicsContext, _ g: MapGraph, _ l: MapLayout, _ s: ColorScheme,
                            focusSet: Set<Int>, focus: Int?, dim: Double) {
        let ink = MapPalette.ink(s)
        var picked: [Int] = []
        if !focusSet.isEmpty {
            let near = focusSet.filter { $0 != focus }.sorted { g.nodes[$0].radius > g.nodes[$1].radius }
            picked = (focus.map { [$0] } ?? []) + near.prefix(24)
        } else {
            // titles only on hover, or once you zoom in: maps from 1.4x, every note from 2x
            let all = camera.zoom >= 2
            guard camera.zoom >= 1.4 else { return }
            picked = g.nodes.indices.filter { all || g.nodes[$0].kind == .map }
        }
        var drawn = 0
        var taken: [CGRect] = []                              // greedy: bigger notes keep their label
        if focusSet.isEmpty { picked.sort { g.nodes[$0].radius > g.nodes[$1].radius } }
        for i in picked where visible(i) {
            let n = g.nodes[i]
            let p = screen(l.x[i], l.y[i])
            guard p.x > -80, p.x < size.width + 80, p.y > -20, p.y < size.height + 20 else { continue }
            let title = n.title.count > 32 ? String(n.title.prefix(31)) + "…" : n.title
            let isFocus = i == focus
            let text = Text(title).font(isFocus ? .klLabel.weight(.semibold) : .klMeta)
                .foregroundColor(ink.opacity(isFocus || focusSet.isEmpty ? 0.92 : 0.78))
            let resolved = ctx.resolve(text)
            let sz = resolved.measure(in: CGSize(width: 400, height: 40))
            let at = CGPoint(x: p.x, y: p.y + n.radius * camera.zoom * (isFocus ? hoverFactor(i) : 1) + 4)
            let box = CGRect(x: at.x - sz.width / 2, y: at.y, width: sz.width, height: sz.height).insetBy(dx: -3, dy: -1)
            if !isFocus && taken.contains(where: { $0.intersects(box) }) { continue }
            taken.append(box)
            ctx.draw(resolved, at: at, anchor: .top)
            drawn += 1
            if drawn >= 140 { break }
        }
    }
}
