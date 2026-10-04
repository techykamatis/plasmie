import SwiftUI

// Motion tokens. One vocabulary for every moving thing in the app.
//   glide  fast-to-slow (exponential ease-out): things moving INTO place - panels, size
//          changes, text swaps, collapsing.
//   pop    fast, then a bounce on halt: playful arrivals - Plasmie landing in a shape,
//          celebrations, the "hi!" bubble, trophy tiles, the notch expanding.
//   jelly  low damping, for secondary wobble.
// Reduce Motion: every token resolves to a 0.15s ease (use `.motion(_:value:)` or
// `Motion.resolved`), and the physics helpers below are simply not sampled.

enum Motion {
    static let glideSeconds = 0.42
    static let glide = Animation.timingCurve(0.16, 1, 0.3, 1, duration: glideSeconds)
    static let pop = Animation.spring(response: 0.36, dampingFraction: 0.58)
    static let jelly = Animation.interpolatingSpring(mass: 1, stiffness: 180, damping: 9)
    static let crossfade = Animation.easeInOut(duration: 0.15)

    /// The token itself, or the 0.15s ease under Reduce Motion.
    static func resolved(_ a: Animation, reduce: Bool) -> Animation { reduce ? crossfade : a }

    // MARK: pure physics helpers (functions of time, so frames are deterministic)

    static func frac(_ x: Double) -> Double { x - floor(x) }

    /// Closed-form damped spring step response 0 -> 1 (overshoots when damping < 1);
    /// the same curve as `pop`, for proofs and prop physics.
    static func springValue(_ t: Double, response: Double = 0.36, damping: Double = 0.58) -> Double {
        guard t > 0 else { return 0 }
        let w0 = 2 * Double.pi / response
        let wd = w0 * max(1 - damping * damping, 0.0001).squareRoot()
        return 1 - exp(-damping * w0 * t) * (cos(wd * t) + damping * w0 / wd * sin(wd * t))
    }

    /// The `glide` curve, sampled: progress 0...1 (time / glideSeconds) -> eased 0...1.
    /// The same cubic Bézier (0.16, 1, 0.3, 1), for things a Canvas moves itself (the map camera).
    static func glideValue(_ p: Double) -> Double {
        guard p > 0 else { return 0 }
        guard p < 1 else { return 1 }
        let (x1, y1, x2, y2) = (0.16, 1.0, 0.3, 1.0)
        func bez(_ t: Double, _ a: Double, _ b: Double) -> Double {
            let u = 1 - t
            return 3 * u * u * t * a + 3 * u * t * t * b + t * t * t
        }
        var t = p
        for _ in 0..<8 {                                   // Newton on x(t) = p
            let u = 1 - t
            let dx = 3 * u * u * x1 + 6 * u * t * (x2 - x1) + 3 * t * t * (1 - x2)
            guard abs(dx) > 1e-6 else { break }
            t = min(max(t - (bez(t, x1, x2) - p) / dx, 0), 1)
        }
        return bez(t, y1, y2)
    }

    /// Decaying cosine, 1 at t = 0 (an impact: starts at full squash, rebounds, settles).
    static func impulse(_ t: Double, freq: Double, decay: Double) -> Double {
        t < 0 ? 0 : exp(-decay * t) * cos(2 * .pi * freq * t)
    }

    /// Decaying sine, 0 at t = 0 (secondary wobble after landing).
    static func wobble(_ t: Double, freq: Double, decay: Double) -> Double {
        t < 0 ? 0 : exp(-decay * t) * sin(2 * .pi * freq * t)
    }

    /// Height of a ball bouncing on a floor after landing at t = 0: decaying parabolas.
    static func bounce(_ t: Double, amp: Double, period: Double = 0.22, decay: Double = 7) -> Double {
        t < 0 ? 0 : amp * exp(-decay * t) * abs(sin(.pi * t / period))
    }

    /// Stable 0...1 hash of an integer (blink schedule and other "random but repeatable").
    static func hash(_ k: Int) -> Double { frac(sin(Double(k) * 12.9898 + 78.233) * 43758.5453) }
}

private struct MotionModifier<V: Equatable>: ViewModifier {
    let animation: Animation
    let value: V
    @Environment(\.accessibilityReduceMotion) private var reduce
    func body(content: Content) -> some View {
        content.animation(Motion.resolved(animation, reduce: reduce), value: value)
    }
}

extension View {
    /// `.animation` with a motion token; Reduce Motion swaps in the 0.15s ease.
    func motion<V: Equatable>(_ animation: Animation, value: V) -> some View {
        modifier(MotionModifier(animation: animation, value: value))
    }
}
