import AppKit
import SwiftUI

/// Plasmie as a crisp menu-bar TEMPLATE image: the body silhouette with eyes and mouth
/// knocked out, so macOS tints it for light/dark menu bars. Frames are rendered once
/// and cached; the menu bar only swaps cached NSImages (8 fps while a job runs).
enum PlasmieGlyph {
    static let pointSize: CGFloat = 18
    static let cycleFrames = 8
    static let tweenFrames = 3

    private static var cache: [String: NSImage] = [:]

    /// Static pose (also the Reduce Motion pose).
    static func still(_ s: PlasmieState) -> NSImage { frame(s, 0, loop: false) }

    /// Loop frame `i` of a state: a tiny squash cycle (breathing for steady states, a
    /// livelier knead for working ones). Cached per (state, i).
    static func frame(_ s: PlasmieState, _ i: Int, loop: Bool = true) -> NSImage {
        let idx = loop ? i % cycleFrames : 0
        return cached("\(s.rawValue)#\(idx)") {
            let amp: CGFloat = !loop ? 0 : (s == .summarize ? 0.07 : (s.animatesMenuBar ? 0.035 : 0))
            let sq = amp * CGFloat(sin(2 * Double.pi * Double(idx) / Double(cycleFrames)))
            return render(s.anchors, face: s, squash: sq)
        }
    }

    /// Morph tween frame `step` of `tweenFrames` (1...tweenFrames) between two states.
    static func tween(from a: PlasmieState, to b: PlasmieState, step: Int) -> NSImage {
        let t = CGFloat(step) / CGFloat(tweenFrames)
        let e = 1 - pow(1 - t, 2)                       // ease-out
        return cached("\(a.rawValue)>\(b.rawValue)#\(step)") {
            render(PlasmieSpline.lerp(a.anchors, b.anchors, e), face: t < 0.5 ? a : b, squash: 0)
        }
    }

    private static func cached(_ key: String, _ make: () -> NSImage) -> NSImage {
        if let hit = cache[key] { return hit }
        let img = make()
        cache[key] = img
        return img
    }

    /// Silhouette + knocked-out face, drawn at 4x and wrapped as an 18pt template NSImage.
    static func render(_ anchors: [CGPoint], face state: PlasmieState, squash: CGFloat,
                       pointSize P: CGFloat = pointSize) -> NSImage {
        let px = 4 * P
        var pts = anchors
        let b0 = PlasmieSpline.bounds(pts)
        pts = pts.map { CGPoint(x: $0.x, y: b0.maxY - (b0.maxY - $0.y) * (1 + squash)) }   // squash about the floor
        let box = PlasmieSpline.bounds(pts)
        let fit = P * 0.94
        let s = min(fit / box.width, fit / box.height)
        let tx = (P - box.width * s) / 2 - box.minX * s
        let ty = (P - box.height * s) / 2 - box.minY * s
        let toPt = CGAffineTransform(a: s, b: 0, c: 0, d: s, tx: tx, ty: ty)

        let n = Int(px)
        guard let ctx = CGContext(data: nil, width: n, height: n, bitsPerComponent: 8, bytesPerRow: 0,
                                  space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return NSImage() }
        ctx.translateBy(x: 0, y: px)
        ctx.scaleBy(x: 4, y: -4)                         // y-down, in points
        ctx.setShouldAntialias(true)
        ctx.setFillColor(CGColor(gray: 0, alpha: 1))
        ctx.addPath(PlasmieSpline.path(pts).applying(toPt).cgPath)
        ctx.fillPath()

        ctx.setBlendMode(.clear)
        let face = state.face
        let marks = PlasmieFaceArt.marks(face, layout: face.layout, box: box, eye: 1.4, line: 1.2)
        for m in marks where m.tone == .ink {
            let path = m.path.applying(toPt).cgPath
            if let w = m.stroke {
                ctx.setLineWidth(max(w * s, 1.25)); ctx.setLineCap(.round); ctx.setLineJoin(.round)
                ctx.addPath(path); ctx.strokePath()
            } else {
                ctx.addPath(path); ctx.fillPath()
            }
        }
        guard let cg = ctx.makeImage() else { return NSImage() }
        let img = NSImage(cgImage: cg, size: NSSize(width: P, height: P))
        img.isTemplate = true
        return img
    }
}
