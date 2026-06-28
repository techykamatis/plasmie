// Renders the Plasmie app icon (same loop-around-a-node glyph, white on an
// indigo squircle) to a .iconset directory. Run as a script: swift make-logo.swift <out.iconset>
import AppKit

func render(_ size: CGFloat) {
    let margin = size * 0.085
    let rect = CGRect(x: margin, y: margin, width: size - 2 * margin, height: size - 2 * margin)
    let radius = rect.width * 0.2235
    let rr = NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
    rr.addClip()
    NSGradient(colors: [NSColor(srgbRed: 0.36, green: 0.30, blue: 0.86, alpha: 1),
                        NSColor(srgbRed: 0.51, green: 0.31, blue: 0.78, alpha: 1)])!
        .draw(in: rect, angle: -90)

    let c = CGPoint(x: size / 2, y: size / 2)
    let r = size * 0.20
    NSColor.white.set()
    let ring = NSBezierPath()
    ring.appendArc(withCenter: c, radius: r, startAngle: 50, endAngle: 360, clockwise: false)
    ring.lineWidth = size * 0.055
    ring.lineCapStyle = .round
    ring.stroke()
    let tip = CGPoint(x: c.x + r, y: c.y)
    let hl = size * 0.078, hw = size * 0.060
    let head = NSBezierPath()
    head.move(to: CGPoint(x: tip.x, y: tip.y + hl))
    head.line(to: CGPoint(x: tip.x + hw, y: tip.y))
    head.line(to: CGPoint(x: tip.x - hw, y: tip.y))
    head.close()
    head.fill()
    let dr = size * 0.055
    NSBezierPath(ovalIn: CGRect(x: c.x - dr, y: c.y - dr, width: dr * 2, height: dr * 2)).fill()
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

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "AppIcon.iconset"
try? FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true)
for (name, px) in [("icon_16x16", 16), ("icon_16x16@2x", 32), ("icon_32x32", 32), ("icon_32x32@2x", 64),
                   ("icon_128x128", 128), ("icon_128x128@2x", 256), ("icon_256x256", 256),
                   ("icon_256x256@2x", 512), ("icon_512x512", 512), ("icon_512x512@2x", 1024)] {
    png(px, "\(out)/\(name).png")
}
print("wrote iconset -> \(out)")
