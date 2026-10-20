import AppKit
import SwiftUI

// Plasmie's map: the backdrop. Deep space behind the network (a dusk sky in light
// appearance): a soft nebula wash, then three layers of out-of-focus light at different
// depths. The middle layer holds pinpoint stars and, among them, other Plasmies far away:
// the real body silhouettes (PlasmieShapes anchors, face knocked out as in the menu-bar
// glyph) at star scale, blurred, in a family of cool and warm hues around the brand
// (never Plasmie's own pink: pink is Plasmie's alone). They should read as stars first and
// as Plasmies on a second look.
//
// Cost: every layer is rendered ONCE to a CGImage (seeded, so the sky is the same every
// open) and only composited per frame, as plain image views (Core Animation layers), never
// redrawn. Tiles depend only on the appearance; the nebula on the window size (bucketed),
// both cached. Pan and zoom move far layers less than near ones (parallax); a few pinpoints
// twinkle while the map is awake and settle to their resting glow before it sleeps.
// Reduce Motion: no parallax, no twinkle: the sky stands still.

enum MapSpace {
    struct Layer: Identifiable {
        let id: Int
        let tile: Double        // tile edge, points (different per layer so repeats never line up)
        let res: Double         // pixels per point: blurred layers need few
        let depth: Double       // parallax: share of the camera's movement this layer follows
    }

    static let far = Layer(id: 0, tile: 1180, res: 0.5, depth: 0.05)
    static let stars = Layer(id: 1, tile: 1420, res: 1.0, depth: 0.13)
    static let near = Layer(id: 2, tile: 1660, res: 0.5, depth: 0.28)
    static let layers = [far, stars, near]

    /// A pinpoint that twinkles: where it sits in the `stars` tile (points), its size and clock.
    struct Glint { let x, y, size, phase, period, rest: Double }

    // MARK: colour

    private typealias RGB = (r: Double, g: Double, b: Double)
    private static func rgb(_ h: UInt32) -> RGB {
        (Double((h >> 16) & 0xFF) / 255, Double((h >> 8) & 0xFF) / 255, Double(h & 0xFF) / 255)
    }
    private static func cg(_ c: RGB, _ a: Double) -> CGColor {
        CGColor(srgbRed: c.r, green: c.g, blue: c.b, alpha: a)
    }

    /// The other Plasmies' hues: lavender, periwinkle, peach, aqua, lilac, apricot, ice.
    /// Dark: luminous pastels; light (dusk): the same family, deeper so it shows on a pale sky.
    private static func otherHues(_ dark: Bool) -> [UInt32] {
        dark ? [0xB7A4F5, 0x8EA2FF, 0xFFB38F, 0x7FE0D6, 0xD9A3F0, 0xFFD3A0, 0xC8D8FF]
             : [0x7E6CC9, 0x5E78D6, 0xE08A5E, 0x3FA894, 0xA86FC4, 0xD99A4A, 0x6F8FC9]
    }
    private static func bokehHues(_ dark: Bool) -> [UInt32] {
        dark ? [0x8EA2FF, 0xB7A4F5, 0x6EC5F0, 0xC8D8FF, 0xFFD3A0, 0x7FE0D6]
             : [0xFFFFFF, 0xFFFFFF, 0xFFFFFF, 0xC9C3EE, 0xFBD3BE, 0xBFE0F2]
    }

    // MARK: per-frame placement (cheap: arithmetic only)

    /// The camera the sky follows: the real one, or none under Reduce Motion.
    static func camera(_ scene: MapScene) -> MapCamera { scene.reduceMotion ? MapCamera() : scene.camera }

    /// Where a layer's tile grid sits: its scale (zoom parallax) and the origin of one tile.
    static func placement(_ l: Layer, size: CGSize, camera c: MapCamera) -> (scale: Double, origin: CGPoint) {
        let s = min(max(pow(c.zoom, l.depth), 0.85), 1.6)
        let d = l.tile * s
        // the tile's centre sits at the view's centre when the camera is home
        let cx = size.width / 2 - c.x * c.zoom * l.depth, cy = size.height / 2 - c.y * c.zoom * l.depth
        func wrap(_ v: Double) -> Double { v - ceil(v / d) * d }          // <= 0, > -d
        return (s, CGPoint(x: wrap(cx - d / 2), y: wrap(cy - d / 2)))
    }

    /// The nebula barely moves, and never far: a soft, bounded drift.
    static func nebulaOffset(size: CGSize, camera c: MapCamera) -> CGSize {
        func soft(_ v: Double, _ m: Double) -> Double { m * tanh(v / m) }
        return CGSize(width: soft(-c.x * c.zoom * 0.02, size.width * 0.06),
                      height: soft(-c.y * c.zoom * 0.02, size.height * 0.06))
    }

    // MARK: cache

    private static let lock = NSLock()
    private static var tiles: [String: CGImage] = [:]
    private static var nebulae: [String: CGImage] = [:]
    private static var glintCache: [Bool: [Glint]] = [:]
    private static var spriteCache: [Bool: CGImage] = [:]

    static func tile(_ l: Layer, dark: Bool) -> CGImage? {
        let key = "\(l.id)-\(dark)"
        lock.lock(); defer { lock.unlock() }
        if let t = tiles[key] { return t }
        let (img, g) = renderTile(l, dark: dark)
        tiles[key] = img
        if l.id == stars.id { glintCache[dark] = g }
        return img
    }

    static func glints(dark: Bool) -> [Glint] {
        _ = tile(stars, dark: dark)
        lock.lock(); defer { lock.unlock() }
        return glintCache[dark] ?? []
    }

    /// The nebula for a window size, bucketed to 64 pt so a live resize rarely re-renders.
    /// Drawn 12 % oversize so its drift never shows an edge.
    static func nebula(_ size: CGSize, dark: Bool) -> (CGImage, CGSize)? {
        let w = ceil(size.width * 1.12 / 64) * 64, h = ceil(size.height * 1.12 / 64) * 64
        guard w > 0, h > 0 else { return nil }
        let key = "\(Int(w))x\(Int(h))-\(dark)"
        lock.lock(); defer { lock.unlock() }
        if let n = nebulae[key] { return (n, CGSize(width: w, height: h)) }
        if nebulae.count > 6 { nebulae.removeAll() }
        guard let n = renderNebula(w, h, dark: dark) else { return nil }
        nebulae[key] = n
        return (n, CGSize(width: w, height: h))
    }

    static func glintSprite(dark: Bool) -> CGImage? {
        lock.lock(); defer { lock.unlock() }
        if let s = spriteCache[dark] { return s }
        let px = 48
        guard let ctx = context(px, px) else { return nil }
        let c = dark ? rgb(0xF4F1FF) : rgb(0x6F63B8)
        let mid = CGPoint(x: Double(px) / 2, y: Double(px) / 2)
        radial(ctx, mid, Double(px) / 2, [(0, cg(c, 0.9)), (0.18, cg(c, 0.45)), (0.5, cg(c, 0.08)), (1, cg(c, 0))])
        let s = ctx.makeImage()
        spriteCache[dark] = s
        return s
    }

    /// Render both appearances' tiles off the main thread (the map calls this as it loads).
    static func prewarm() {
        DispatchQueue.global(qos: .utility).async {
            for dark in [true, false] { for l in layers { _ = tile(l, dark: dark) }; _ = glintSprite(dark: dark) }
        }
    }

    // MARK: rendering (once per appearance)

    /// splitmix64: a fixed seed per layer, so the sky is the same every time the map opens.
    private struct RNG {
        var s: UInt64
        mutating func next() -> Double {
            s &+= 0x9E37_79B9_7F4A_7C15
            var z = s
            z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
            z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
            return Double((z ^ (z >> 31)) >> 11) / Double(1 << 53)
        }
        mutating func range(_ a: Double, _ b: Double) -> Double { a + (b - a) * next() }
    }

    private static func context(_ w: Int, _ h: Int) -> CGContext? {
        CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                  space: CGColorSpace(name: CGColorSpace.sRGB) ?? CGColorSpaceCreateDeviceRGB(),
                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
    }

    private static func radial(_ ctx: CGContext, _ c: CGPoint, _ r: Double, _ stops: [(Double, CGColor)]) {
        guard r > 0, let g = CGGradient(colorsSpace: CGColorSpace(name: CGColorSpace.sRGB),
                                        colors: stops.map(\.1) as CFArray,
                                        locations: stops.map { CGFloat($0.0) }) else { return }
        ctx.drawRadialGradient(g, startCenter: c, startRadius: 0, endCenter: c, endRadius: r, options: [])
    }

    /// Calls `draw` at every copy of (x, y) that touches the tile, so the tile wraps seamlessly.
    private static func wrapped(_ x: Double, _ y: Double, _ r: Double, _ t: Double, _ draw: (Double, Double) -> Void) {
        for ox in [-t, 0, t] { for oy in [-t, 0, t] {
            let px = x + ox, py = y + oy
            if px + r < 0 || px - r > t || py + r < 0 || py - r > t { continue }
            draw(px, py)
        } }
    }

    /// An out-of-focus light: soft edge, a slightly brighter rim, as a lens draws it.
    private static func bokeh(_ ctx: CGContext, _ c: CGPoint, _ r: Double, _ col: RGB, _ a: Double) {
        radial(ctx, c, r, [(0, cg(col, a * 0.55)), (0.7, cg(col, a * 0.7)), (0.86, cg(col, a * 0.5)), (1, cg(col, 0))])
    }

    private static func renderTile(_ l: Layer, dark: Bool) -> (CGImage?, [Glint]) {
        let t = l.tile, px = Int((t * l.res).rounded())
        guard let ctx = context(px, px) else { return (nil, []) }
        ctx.translateBy(x: 0, y: Double(px))
        ctx.scaleBy(x: l.res, y: -l.res)                      // points, y down
        var rng = RNG(s: 0x51A5_0000 &+ UInt64(l.id) &* 0x1F3D_5B79)
        var glints: [Glint] = []
        let hues = bokehHues(dark).map(rgb)

        switch l.id {
        case far.id:            // many small, dim discs: the deep field
            for _ in 0..<70 {
                let x = rng.range(0, t), y = rng.range(0, t), r = 3 + 11 * pow(rng.next(), 1.6)
                let col = hues[Int(rng.next() * Double(hues.count)) % hues.count]
                let a = dark ? rng.range(0.07, 0.2) : rng.range(0.16, 0.36)
                wrapped(x, y, r, t) { bokeh(ctx, CGPoint(x: $0, y: $1), r, col, a) }
            }
        case near.id:           // a few big, faint discs drifting past the lens
            for _ in 0..<9 {
                let x = rng.range(0, t), y = rng.range(0, t), r = rng.range(28, 84)
                let col = hues[Int(rng.next() * Double(hues.count)) % hues.count]
                let a = dark ? rng.range(0.05, 0.09) : rng.range(0.14, 0.26)
                wrapped(x, y, r, t) { bokeh(ctx, CGPoint(x: $0, y: $1), r, col, a) }
            }
        default:                // pinpoints, and the far-away Plasmies
            let star = dark ? rgb(0xEEF0FF) : rgb(0x7A72B0)
            for i in 0..<(dark ? 110 : 55) {
                let x = rng.range(0, t), y = rng.range(0, t), r = 0.7 + 1.6 * pow(rng.next(), 2.5)
                let a = dark ? rng.range(0.25, 0.75) : rng.range(0.15, 0.35)
                wrapped(x, y, r * 2, t) { radial(ctx, CGPoint(x: $0, y: $1), r * 2, [(0, cg(star, a)), (0.35, cg(star, a * 0.6)), (1, cg(star, 0))]) }
                if i % 9 == 0 {
                    glints.append(Glint(x: x, y: y, size: 6 + 10 * r, phase: rng.next(), period: rng.range(2.4, 4.2), rest: a * 0.55))
                }
            }
            drawOthers(ctx, t, l.res, dark: dark, rng: &rng)
        }
        return (ctx.makeImage(), glints)
    }

    /// The other Plasmies: a dozen per tile, mostly tiny, a few nearer. Kept clear of the
    /// tile's centre, where the real Plasmie sits when the camera is home.
    private static func drawOthers(_ ctx: CGContext, _ t: Double, _ res: Double, dark: Bool, rng: inout RNG) {
        let poses: [PlasmieState] = [.idle, .idle, .idle, .hi, .success, .ask, .tada]   // the poses that still read when tiny
        let hues = otherHues(dark).map(rgb)
        var placed = 0, tries = 0
        while placed < 13 && tries < 200 {
            tries += 1
            let x = rng.range(0, t), y = rng.range(0, t)
            if hypot(x - t / 2, y - t / 2) < 170 { continue }
            let size = 6 + 18 * pow(rng.next(), 1.8)                    // points, mostly small
            let pose = poses[Int(rng.next() * Double(poses.count)) % poses.count]
            let col = hues[Int(rng.next() * Double(hues.count)) % hues.count]
            let a = (dark ? 0.5 : 0.4) + (dark ? 0.35 : 0.3) * rng.next()
            let blur = (0.35 + 0.035 * size) * res                      // device pixels: soft, still a silhouette
            guard let sprite = otherSprite(pose, size: size, res: res) else { continue }
            placed += 1
            wrapped(x, y, size * 1.8, t) { cx, cy in
                // the glow it sheds, like any star
                radial(ctx, CGPoint(x: cx, y: cy), size * 1.6, [(0, cg(col, a * 0.32)), (0.5, cg(col, a * 0.12)), (1, cg(col, 0))])
                // the body, blurred: drawn off the tile, only its coloured shadow lands
                let away = t + 400                                     // points
                ctx.saveGState()
                ctx.setShadow(offset: CGSize(width: away * res, height: 0), blur: blur, color: cg(col, a))
                ctx.translateBy(x: cx - size / 2 - away, y: cy + size / 2)
                ctx.scaleBy(x: 1, y: -1)                               // images draw y-up; the tile is y-down
                ctx.draw(sprite, in: CGRect(x: 0, y: 0, width: size, height: size))
                ctx.restoreGState()
            }
        }
    }

    /// A body silhouette at star scale. From 11 pt the face is knocked out (the menu-bar
    /// glyph's art, PlasmieGlyph.render); below that it would only be noise, so just the body.
    private static func otherSprite(_ s: PlasmieState, size: Double, res: Double) -> CGImage? {
        if size >= 11 {
            let img = PlasmieGlyph.render(s.anchors, face: s, squash: 0, pointSize: size)
            return img.cgImage(forProposedRect: nil, context: nil, hints: nil)
        }
        let px = max(Int((size * res * 2).rounded()), 4)
        guard let ctx = context(px, px) else { return nil }
        let pts = s.anchors, box = PlasmieSpline.bounds(pts)
        let k = Double(px) * 0.94 / max(box.width, box.height)
        ctx.translateBy(x: 0, y: Double(px)); ctx.scaleBy(x: 1, y: -1)
        ctx.translateBy(x: (Double(px) - box.width * k) / 2 - box.minX * k, y: (Double(px) - box.height * k) / 2 - box.minY * k)
        ctx.scaleBy(x: k, y: k)
        ctx.addPath(PlasmieSpline.path(pts).cgPath)
        ctx.setFillColor(CGColor(gray: 0, alpha: 1))
        ctx.fillPath()
        return ctx.makeImage()
    }

    /// Deep space (dark), or a dusk sky (light): a vertical wash with three soft clouds.
    private static func renderNebula(_ w: Double, _ h: Double, dark: Bool) -> CGImage? {
        let res = 0.5                                                  // smooth gradients need few pixels
        guard let ctx = context(Int(w * res), Int(h * res)) else { return nil }
        ctx.translateBy(x: 0, y: h * res); ctx.scaleBy(x: res, y: -res)
        let (top, bottom) = dark ? (rgb(0x0A0B17), rgb(0x100E1F)) : (rgb(0xE4E5F4), rgb(0xF4ECE8))
        if let g = CGGradient(colorsSpace: CGColorSpace(name: CGColorSpace.sRGB),
                              colors: [cg(top, 1), cg(bottom, 1)] as CFArray, locations: [0, 1]) {
            ctx.drawLinearGradient(g, start: .zero, end: CGPoint(x: 0, y: h), options: [])
        }
        let clouds: [(Double, Double, Double, UInt32, Double)] = dark
            ? [(0.2, 0.28, 0.62, 0x34337E, 0.30), (0.84, 0.78, 0.56, 0x4E2A66, 0.22), (0.72, 0.12, 0.4, 0x1B5068, 0.16)]
            : [(0.2, 0.3, 0.6, 0xD6D2F2, 0.45), (0.82, 0.86, 0.6, 0xF8D6C2, 0.5), (0.76, 0.12, 0.42, 0xD3E7F5, 0.4)]
        for (fx, fy, fr, hex, a) in clouds {
            let c = rgb(hex)
            radial(ctx, CGPoint(x: w * fx, y: h * fy), max(w, h) * fr, [(0, cg(c, a)), (0.55, cg(c, a * 0.4)), (1, cg(c, 0))])
        }
        return ctx.makeImage()
    }
}

// MARK: - the view

/// The backdrop as image views (composited, never redrawn). `now` drives the twinkle;
/// `twinkle` (0...1) is how much of it is showing: the map fades it out before it sleeps.
struct MapSpaceView: View {
    let size: CGSize
    let camera: MapCamera
    let scheme: ColorScheme
    var now = Date.distantPast
    var twinkle = 0.0

    var body: some View {
        let dark = scheme == .dark
        ZStack(alignment: .topLeading) {
            if let neb = MapSpace.nebula(size, dark: dark) {
                let (n, ns) = neb
                let o = MapSpace.nebulaOffset(size: size, camera: camera)
                Image(decorative: n, scale: 0.5).resizable()
                    .frame(width: ns.width, height: ns.height)
                    .offset(x: (size.width - ns.width) / 2 + o.width, y: (size.height - ns.height) / 2 + o.height)
            }
            ForEach(MapSpace.layers) { l in layer(l, dark: dark) }
        }
        .frame(width: size.width, height: size.height, alignment: .topLeading)
        .clipped()
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    @ViewBuilder private func layer(_ l: MapSpace.Layer, dark: Bool) -> some View {
        if let img = MapSpace.tile(l, dark: dark) {
            let (s, o) = MapSpace.placement(l, size: size, camera: camera)
            let d = l.tile * s
            let nx = Int(ceil((size.width - o.x) / d)), ny = Int(ceil((size.height - o.y) / d))
            let image = Image(decorative: img, scale: l.res).resizable().interpolation(.medium)
            ForEach(0..<max(nx * ny, 0), id: \.self) { k in
                image.frame(width: d, height: d)
                    .offset(x: o.x + Double(k % nx) * d, y: o.y + Double(k / nx) * d)
            }
            if l.id == MapSpace.stars.id { glints(o, s, d, nx, ny, dark: dark) }
        }
    }

    /// A few pinpoints breathe brighter and back (only while the map is awake).
    @ViewBuilder private func glints(_ o: CGPoint, _ s: Double, _ d: Double, _ nx: Int, _ ny: Int, dark: Bool) -> some View {
        if let sprite = MapSpace.glintSprite(dark: dark) {
            let gs = MapSpace.glints(dark: dark)
            let t = now.timeIntervalSinceReferenceDate
            let img = Image(decorative: sprite, scale: 1).resizable()
            ForEach(0..<max(nx * ny, 0), id: \.self) { k in
                let tx = o.x + Double(k % nx) * d, ty = o.y + Double(k / nx) * d
                ForEach(gs.indices, id: \.self) { i in
                    let g = gs[i]
                    let x = tx + g.x * s, y = ty + g.y * s
                    if x > -g.size, x < size.width + g.size, y > -g.size, y < size.height + g.size {
                        let wave = 0.5 + 0.5 * sin(2 * .pi * (t / g.period + g.phase))
                        img.frame(width: g.size * s, height: g.size * s)
                            .opacity(min(g.rest * (1 + 1.1 * twinkle * (wave - 0.35)), 1))
                            .blendMode(dark ? .plusLighter : .normal)
                            .offset(x: x - g.size * s / 2, y: y - g.size * s / 2)
                    }
                }
            }
        }
    }
}

extension MapScene {
    /// 0...1: the twinkle's share. Full while the map is lively, easing to 0 over the last
    /// 1.5 s before it sleeps (so the frozen frame is the resting sky); 0 under Reduce Motion.
    func twinkle(_ now: Date) -> Double {
        guard ambient else { return 0 }
        return min(max((Self.ambientSeconds - 1.5 - sinceTouch(now)) / 1.5, 0), 1)
    }
}
