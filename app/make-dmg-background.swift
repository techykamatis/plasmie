// Renders the DMG window background: the drag arrow between the app and Applications, and
// the first-time steps in plain English underneath. make-dmg.sh compiles and runs this, then
// joins the 1x and 2x PNGs into one TIFF so Finder picks the sharp one on Retina screens.
//   swiftc -o make-dmg-background make-dmg-background.swift
//   ./make-dmg-background <out-dir> <AppName>     # writes bg.png and bg@2x.png
//
// The layout constants here must match the icon positions in make-dmg.sh.
import AppKit

let W: CGFloat = 840, H: CGFloat = 470        // window content size (points)
let appX: CGFloat = 270, appsX: CGFloat = 570, iconY: CGFloat = 160   // icon centres, y from top

func color(_ hex: UInt32, _ a: CGFloat = 1) -> NSColor {
    NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: a)
}
let ground = color(0xFDF1F4), ink = color(0x3A1430), ink2 = color(0x6A3A5A), ink3 = color(0x8E6080)
let rule = color(0xF3D6DF), arrowFill = color(0xF6D3DD), arrowEdge = color(0xE8B4C4), blush = color(0xE8668A)

func font(_ size: CGFloat, _ weight: NSFont.Weight, rounded: Bool = false) -> NSFont {
    let f = NSFont.systemFont(ofSize: size, weight: weight)
    guard rounded, let d = f.fontDescriptor.withDesign(.rounded) else { return f }
    return NSFont(descriptor: d, size: size) ?? f
}

/// Draw text in a box whose top edge is `top` points below the top of the window.
func text(_ s: String, x: CGFloat, top: CGFloat, width: CGFloat, font f: NSFont, color c: NSColor,
          align: NSTextAlignment = .left, lineSpacing: CGFloat = 3) {
    let p = NSMutableParagraphStyle()
    p.alignment = align; p.lineSpacing = lineSpacing
    // **like this** marks the words to press: bold, in the darkest ink.
    let str = NSMutableAttributedString()
    for (i, part) in s.components(separatedBy: "**").enumerated() {
        let bold = i % 2 == 1
        str.append(NSAttributedString(string: part, attributes: [
            .font: bold ? NSFont.systemFont(ofSize: f.pointSize, weight: .bold) : f,
            .foregroundColor: bold ? ink : c, .paragraphStyle: p]))
    }
    let h = str.boundingRect(with: NSSize(width: width, height: 400), options: [.usesLineFragmentOrigin]).height
    str.draw(with: NSRect(x: x, y: H - top - h, width: width, height: h), options: [.usesLineFragmentOrigin])
}

/// A "Step N" pill whose left edge is at x, vertically centred on cy (points from the top).
func badge(_ n: Int, x: CGFloat, cy: CGFloat) {
    let w: CGFloat = 58, h: CGFloat = 22
    blush.setFill()
    NSBezierPath(roundedRect: NSRect(x: x, y: H - cy - h / 2, width: w, height: h), xRadius: h / 2, yRadius: h / 2).fill()
    text("Step \(n)", x: x, top: cy - 8, width: w, font: font(12, .bold, rounded: true), color: .white, align: .center)
}

/// A soft block arrow, like the classic drag-to-install window.
func arrow(from x0: CGFloat, to x1: CGFloat, cy: CGFloat) {
    let y = H - cy, shaft: CGFloat = 15, head: CGFloat = 34, headLen: CGFloat = 46
    let p = NSBezierPath()
    p.move(to: NSPoint(x: x0, y: y + shaft))
    p.line(to: NSPoint(x: x1 - headLen, y: y + shaft))
    p.line(to: NSPoint(x: x1 - headLen, y: y + head))
    p.line(to: NSPoint(x: x1, y: y))
    p.line(to: NSPoint(x: x1 - headLen, y: y - head))
    p.line(to: NSPoint(x: x1 - headLen, y: y - shaft))
    p.line(to: NSPoint(x: x0, y: y - shaft))
    p.close()
    p.lineJoinStyle = .round
    arrowFill.setFill(); p.fill()
    arrowEdge.setStroke(); p.lineWidth = 1.5; p.stroke()
}

func draw(app: String) {
    ground.setFill(); NSRect(x: 0, y: 0, width: W, height: H).fill()

    text("Install \(app)", x: 0, top: 26, width: W, font: font(26, .bold, rounded: true), color: ink, align: .center)
    text("It takes a minute.", x: 0, top: 62, width: W,
         font: font(13, .regular), color: ink3, align: .center)

    // Step 1 sits with the icons it describes.
    arrow(from: appX + 78, to: appsX - 78, cy: iconY)
    badge(1, x: W / 2 - 142, cy: 268)
    text("Drag \(app) onto Applications.", x: W / 2 - 74, top: 259, width: 300,
         font: font(14, .semibold), color: ink)

    rule.setFill(); NSRect(x: 40, y: H - 300, width: W - 80, height: 1).fill()

    // Steps 2 and 3: getting past the "can't check it" warning (the app isn't from the App Store).
    let colX: CGFloat = 110, colW: CGFloat = 392
    text("First time you open it", x: 40, top: 316, width: colW, font: font(12, .bold), color: ink3)
    badge(2, x: 40, cy: 352)
    text("Open \(app) from Applications. When your Mac warns you, click Done.",
         x: colX, top: 343, width: colW, font: font(13, .regular), color: ink2)
    badge(3, x: 40, cy: 410)
    text("Open **System Settings** (on the right), then **Privacy\u{00A0}&\u{00A0}Security**. Click **Open\u{00A0}Anyway** "
         + "and enter your password.",
         x: colX, top: 401, width: colW, font: font(13, .regular), color: ink2)

    // The two guides sit to the right of the steps (positions set in make-dmg.sh).
    text("For Step 3", x: 500, top: 316, width: 120, font: font(12, .bold), color: ink3, align: .center)
    text("More to read", x: 645, top: 316, width: 170, font: font(12, .bold), color: ink3, align: .center)
}

func render(scale: CGFloat, app: String, to url: URL) {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(W * scale), pixelsHigh: Int(H * scale),
                               bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    rep.size = NSSize(width: W, height: H)           // points, so 2x renders at 144 dpi
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    draw(app: app)
    NSGraphicsContext.restoreGraphicsState()
    try! rep.representation(using: .png, properties: [:])!.write(to: url)
}

let args = CommandLine.arguments
guard args.count == 3 else { print("usage: make-dmg-background <out-dir> <AppName>"); exit(2) }
let out = URL(fileURLWithPath: args[1], isDirectory: true)
render(scale: 1, app: args[2], to: out.appendingPathComponent("bg.png"))
render(scale: 2, app: args[2], to: out.appendingPathComponent("bg@2x.png"))
