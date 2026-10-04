import SwiftUI

// Plasmie's map: the opening (after the hologram burst in Iron Man 2's new-element scene).
// Plasmie fills half the view with the whole web packed out of sight behind it; a beat
// later Plasmie snaps back to size and the web bursts out from behind, spinning, flying a
// little past where it belongs, then settling. One affine pose (spread + spin about
// Plasmie, the world origin) drives the world layer and `screen()`, so veins, labels and
// hit-testing all agree mid-flight. Off under Reduce Motion; any click or scroll skips it.

struct MapIntroPose {
    var spread: Double          // 0 = packed into Plasmie, 1 = the real layout
    var spin: Double            // radians
    var swell = 1.0             // Plasmie inhaling from the loading size up to huge, during the hold
    var snap: Double            // Plasmie: 0 = huge, 1 = its normal size
    var wave: Double?           // 0...1 progress of the shockwave ring, nil outside it
    var armAngle = 0.0          // radians from hanging straight down; ~2.5 = flung up and out
    var armReach = 0.0          // 0 = tucked behind the body, 1 = out
    var hands = 0.0             // 0 = mittens, 1 = fingers spread
}

extension MapScene {
    static let introHold = 0.55, introBurst = 1.6, introWave = 0.75
    private static let packed = 0.02, startSpin = -1.2
    private static let flingLead = 0.18      // arms thrown open just before the burst, as Stark does

    func startIntro() { if !reduceMotion { introAt = Date() } }
    func skipIntro() { introAt = .distantPast; introPose = nil }

    /// The pose at `now`, or nil once the opening is over. Called from `advance(to:)`.
    func pose(at now: Date) -> MapIntroPose? {
        let t = now.timeIntervalSince(introAt) - Self.introHold
        guard t < Self.introBurst else { return nil }
        guard t > 0 else {
            let swell = Motion.springValue(t + Self.introHold, response: 0.5, damping: 0.8)
            return MapIntroPose(spread: Self.packed, spin: Self.startSpin, swell: swell, snap: 0, wave: nil,
                                armAngle: armAngle(t), armReach: swell, hands: hands(t))
        }
        let out = Motion.springValue(t, response: 0.9, damping: 0.72)          // one soft overshoot: past, then home
        return MapIntroPose(spread: Self.packed + (1 - Self.packed) * out,
                            spin: Self.startSpin * (1 - Motion.glideValue(t / 1.1)),
                            snap: Motion.glideValue(t / 0.38),                  // the sudden zoom out
                            wave: t < Self.introWave ? t / Self.introWave : nil,
                            armAngle: armAngle(t),
                            armReach: 1 - Motion.glideValue((t - 0.95) / 0.45),
                            hands: hands(t))
    }

    /// Plasmie's diameter while huge: about half the view.
    var introHugeSize: Double { 0.55 * min(size.width, size.height) }
    static let loadingSize = 96.0              // the "Growing your map…" Plasmie it grows from

    /// World point -> where the opening currently puts it (still world space).
    func introApply(_ wx: Double, _ wy: Double) -> (Double, Double) {
        guard let p = introPose else { return (wx, wy) }
        let c = cos(p.spin), s = sin(p.spin)
        return ((wx * c - wy * s) * p.spread, (wx * s + wy * c) * p.spread)
    }

    /// Hands drawn in during the hold, then flung up and out.
    private func armAngle(_ t: Double) -> Double {
        let f = t + Self.flingLead
        guard f > 0 else { return deg(32 - 20 * Motion.glideValue((t + Self.introHold) / Self.introHold)) }
        return deg(12 + 133 * Motion.springValue(f, response: 0.38, damping: 0.55))
    }
    private func hands(_ t: Double) -> Double { Motion.springValue(t + Self.flingLead - 0.06, response: 0.3, damping: 0.6) }
    private func deg(_ d: Double) -> Double { d * .pi / 180 }

    /// Two stubby arms from behind Plasmie's sides (the canvas sits under the mascot), in
    /// Plasmie's own pink and ink: the one place outside the body that pink is allowed.
    func drawIntroArms(_ ctx: GraphicsContext, _ s: ColorScheme) {
        guard let p = introPose, p.armReach > 0.01 else { return }
        let o = screen(0, 0), d = plasmieSize
        let w = 0.085 * d, ol = 0.022 * d, len = 0.27 * d * p.armReach, hr = 0.058 * d
        let pink = PlasmieHues.body.color(s), ink = PlasmieHues.ink.color(s)
        for side in [-1.0, 1.0] {
            let dir = CGPoint(x: side * sin(p.armAngle), y: cos(p.armAngle))
            let sh = CGPoint(x: o.x + side * 0.31 * d, y: o.y + 0.07 * d)
            let hand = CGPoint(x: sh.x + dir.x * len, y: sh.y + dir.y * len)
            var arm = Path(); arm.move(to: sh); arm.addLine(to: hand)
            var blob = Path(ellipseIn: CGRect(x: hand.x - hr, y: hand.y - hr, width: 2 * hr, height: 2 * hr))
            if p.hands > 0.05 {                              // three fingers fan out, Stark-style
                let base = atan2(dir.y, dir.x), fr = 0.026 * d * min(p.hands, 1.2)
                for k in [-1.0, 0.0, 1.0] {
                    let a = base + k * 0.62 * p.hands, r = hr + fr * 0.6
                    let c = CGPoint(x: hand.x + cos(a) * r, y: hand.y + sin(a) * r)
                    blob.addEllipse(in: CGRect(x: c.x - fr, y: c.y - fr, width: 2 * fr, height: 2 * fr))
                }
            }
            ctx.stroke(arm, with: .color(ink), style: StrokeStyle(lineWidth: w + 2 * ol, lineCap: .round))
            ctx.stroke(blob, with: .color(ink), lineWidth: 2 * ol)
            ctx.stroke(arm, with: .color(pink), style: StrokeStyle(lineWidth: w, lineCap: .round))
            ctx.fill(blob, with: .color(pink))
        }
    }

    /// The burst's shockwave: one thin ring leaving Plasmie's edge, fading as it goes.
    func drawIntroWave(_ ctx: GraphicsContext, _ s: ColorScheme) {
        guard let w = introPose?.wave else { return }
        let o = screen(0, 0), e = Motion.glideValue(w)
        let r = introHugeSize / 2 + (hypot(size.width, size.height) / 2) * e
        let ring = Path(ellipseIn: CGRect(x: o.x - r, y: o.y - r, width: 2 * r, height: 2 * r))
        ctx.stroke(ring, with: .color(MapPalette.glow(s).opacity(0.55 * (1 - w))), lineWidth: 1.5 + 2.5 * (1 - w))
    }
}
