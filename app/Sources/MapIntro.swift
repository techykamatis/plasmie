import SwiftUI

// Plasmie's map: the opening (after the hologram burst in Iron Man 2's new-element scene).
// Plasmie fills half the view with the whole web packed out of sight behind it; a beat
// later Plasmie throws both arms open (the .tada body, its "hi" arm on both sides), snaps
// back to size and the web bursts out from behind, spinning, flying a
// little past where it belongs, then settling. One affine pose (spread + spin about
// Plasmie, the world origin) drives the world layer and `screen()`, so veins, labels and
// hit-testing all agree mid-flight. Off under Reduce Motion; any click or scroll skips it.

struct MapIntroPose {
    var spread: Double          // 0 = packed into Plasmie, 1 = the real layout
    var spin: Double            // radians
    var swell = 1.0             // Plasmie inhaling from the loading size up to huge, during the hold
    var snap: Double            // Plasmie: 0 = huge, 1 = its normal size
    var wave: Double?           // 0...1 progress of the shockwave ring, nil outside it
    var tada = false            // Plasmie's body flung into the both-arms-up shape
}

extension MapScene {
    static let introHold = 0.55, introBurst = 1.6, introWave = 0.75
    private static let packed = 0.02, startSpin = -1.2
    private static let flingLead = 0.22      // arms thrown open just before the burst, as Stark does
    private static let tadaUntil = 0.9       // then lowered while the web settles

    func startIntro() { if !reduceMotion { introAt = Date() } }
    func skipIntro() { introAt = .distantPast; introPose = nil }

    /// The pose at `now`, or nil once the opening is over. Called from `advance(to:)`.
    func pose(at now: Date) -> MapIntroPose? {
        let t = now.timeIntervalSince(introAt) - Self.introHold
        guard t < Self.introBurst else { return nil }
        guard t > 0 else {
            let swell = Motion.springValue(t + Self.introHold, response: 0.5, damping: 0.8)
            return MapIntroPose(spread: Self.packed, spin: Self.startSpin, swell: swell, snap: 0, wave: nil,
                                tada: t > -Self.flingLead)
        }
        let out = Motion.springValue(t, response: 0.9, damping: 0.72)          // one soft overshoot: past, then home
        return MapIntroPose(spread: Self.packed + (1 - Self.packed) * out,
                            spin: Self.startSpin * (1 - Motion.glideValue(t / 1.1)),
                            snap: Motion.glideValue(t / 0.38),                  // the sudden zoom out
                            wave: t < Self.introWave ? t / Self.introWave : nil,
                            tada: t < Self.tadaUntil)
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


    /// The burst's shockwave: one thin ring leaving Plasmie's edge, fading as it goes.
    func drawIntroWave(_ ctx: GraphicsContext, _ s: ColorScheme) {
        guard let w = introPose?.wave else { return }
        let o = screen(0, 0), e = Motion.glideValue(w)
        let r = introHugeSize / 2 + (hypot(size.width, size.height) / 2) * e
        let ring = Path(ellipseIn: CGRect(x: o.x - r, y: o.y - r, width: 2 * r, height: 2 * r))
        ctx.stroke(ring, with: .color(MapPalette.glow(s).opacity(0.55 * (1 - w))), lineWidth: 1.5 + 2.5 * (1 - w))
    }
}
