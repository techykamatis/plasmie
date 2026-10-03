// Renders the Plasmie app icon (idle pose, coloured, on a soft rounded-square ground) to a
// .iconset directory. Compiled together with Sources/PlasmieShapes.swift (make-app.sh does
// this) so the icon uses the same anchors as the app:
//   swiftc -parse-as-library -o make-logo make-logo.swift Sources/PlasmieShapes.swift
//   ./make-logo <out.iconset>
import AppKit

func rgb(_ hex: UInt32, _ a: CGFloat = 1) -> CGColor {
    CGColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: a)
}

/// Closed Catmull-Rom through the anchors (same formula as the app's PlasmieSpline).
func spline(_ p: [CGPoint]) -> CGPath {
    let n = p.count
    let path = CGMutablePath()
    path.move(to: p[0])
    for i in 0..<n {
        let p0 = p[(i + n - 1) % n], p1 = p[i], p2 = p[(i + 1) % n], p3 = p[(i + 2) % n]
        path.addCurve(to: p2,
                      control1: CGPoint(x: p1.x + (p2.x - p0.x) / 6, y: p1.y + (p2.y - p0.y) / 6),
                      control2: CGPoint(x: p2.x - (p3.x - p1.x) / 6, y: p2.y - (p3.y - p1.y) / 6))
    }
    path.closeSubpath()
    return path
}

func render(_ size: CGFloat) {
    guard let ctx = NSGraphicsContext.current?.cgContext else { return }
    let margin = size * 0.085
    let rect = CGRect(x: margin, y: margin, width: size - 2 * margin, height: size - 2 * margin)
    let ground = CGPath(roundedRect: rect, cornerWidth: rect.width * 0.2235, cornerHeight: rect.width * 0.2235, transform: nil)
    ctx.saveGState()
    ctx.addPath(ground); ctx.clip()
    ctx.setFillColor(rgb(0xFDEFF3))
    ctx.fill(rect)

    // Plasmie, idle pose: map the 100x100 canvas (y down) so the body fills ~64% of the ground.
    let pts = PlasmieShapes.anchors["idle"] ?? []
    guard pts.count >= 3 else { ctx.restoreGState(); return }
    let minX = pts.map(\.x).min()!, maxX = pts.map(\.x).max()!
    let minY = pts.map(\.y).min()!, maxY = pts.map(\.y).max()!
    let k = rect.width * 0.64 / (maxX - minX)
    let ox = rect.midX - (minX + maxX) / 2 * k
    let oy = rect.midY + (minY + maxY) / 2 * k            // y flip: AppKit is y-up
    func P(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: ox + x * k, y: oy - y * k) }
    let body = spline(pts.map { P($0.x, $0.y) })

    // soft contact shadow
    ctx.setFillColor(rgb(0x3A1430, 0.10))
    ctx.fillEllipse(in: CGRect(x: P((minX + maxX) / 2, 0).x - (maxX - minX) * k * 0.31, y: P(0, maxY).y - 2.2 * k,
                               width: (maxX - minX) * k * 0.62, height: 4.5 * k))
    ctx.setFillColor(rgb(0xF49AB2))
    ctx.addPath(body); ctx.fillPath()

    // belly sheen: a soft ellipse clipped to the body (no gloss)
    ctx.saveGState()
    ctx.addPath(body); ctx.clip()
    let bw = (maxX - minX) * k, bh = (maxY - minY) * k
    ctx.setFillColor(rgb(0xFBC9D6, 0.7))
    ctx.fillEllipse(in: CGRect(x: rect.midX - bw * 0.27, y: P(0, maxY).y + bh * 0.08, width: bw * 0.54, height: bh * 0.26))
    ctx.restoreGState()

    ctx.setStrokeColor(rgb(0x3A1430)); ctx.setLineWidth(2.2 * k); ctx.setLineJoin(.round)
    ctx.addPath(body); ctx.strokePath()

    // face (idle: dot eyes, smile, blush) — mirrors PlasmieFace for .idle
    let cx = (minX + maxX) / 2, w = maxX - minX, h = maxY - minY
    let ey = minY + 0.46 * h, gap = 0.17 * w
    ctx.setFillColor(rgb(0xE8668A, 0.8))
    for sx: CGFloat in [-1, 1] {
        let c = P(cx + sx * (gap + 5.4), ey + 5.6)
        ctx.fillEllipse(in: CGRect(x: c.x - 4.2 * k, y: c.y - 2.6 * k, width: 8.4 * k, height: 5.2 * k))
    }
    ctx.setFillColor(rgb(0x3A1430))
    for sx: CGFloat in [-1, 1] {
        let c = P(cx + sx * gap, ey)
        ctx.fillEllipse(in: CGRect(x: c.x - 3 * k, y: c.y - 3 * k, width: 6 * k, height: 6 * k))
    }
    let m = CGMutablePath()
    m.move(to: P(cx - 4.6, ey + 8))
    m.addQuadCurve(to: P(cx + 4.6, ey + 8), control: P(cx, ey + 13.4))
    ctx.setStrokeColor(rgb(0x3A1430)); ctx.setLineWidth(2.3 * k); ctx.setLineCap(.round)
    ctx.addPath(m); ctx.strokePath()
    ctx.restoreGState()
}

func png(_ px: Int, _ path: String) {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px,
                              bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                              colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    rep.size = NSSize(width: px, height: px)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    render(CGFloat(px))
    NSGraphicsContext.restoreGraphicsState()
    try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: path))
}

@main
struct MakeLogo {
    static func main() {
        let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "AppIcon.iconset"
        try? FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true)
        for (name, px) in [("icon_16x16", 16), ("icon_16x16@2x", 32), ("icon_32x32", 32), ("icon_32x32@2x", 64),
                           ("icon_128x128", 128), ("icon_128x128@2x", 256), ("icon_256x256", 256),
                           ("icon_256x256@2x", 512), ("icon_512x512", 512), ("icon_512x512@2x", 1024)] {
            png(px, "\(out)/\(name).png")
        }
        print("wrote iconset -> \(out)")
    }
}
