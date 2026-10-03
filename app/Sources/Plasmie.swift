import SwiftUI

// Plasmie — the app's mascot. A soft blob that takes the shape of whatever the pipeline
// is doing. PlasmieView morphs between states (anchor blend through PlasmieShape), draws a
// face that follows the body, and plays one small prop loop per state. Reduce Motion:
// morphs become a short crossfade and every loop stops on a static pose.

/// Shared "Ask is answering" flag. The Ask overlay writes it; Model reads it to put Plasmie
/// (and the menu-bar glyph) into the `ask` state.
final class AskActivity: ObservableObject {
    static let shared = AskActivity()
    @Published var answering = false
}

enum PlasmieMotion {
    /// Fast, no visible bounce.
    static let morph = Animation.spring(response: 0.32, dampingFraction: 0.86)
    static let crossfade = Animation.easeInOut(duration: 0.15)
    static let anticipation = 0.07          // seconds of the 0.96 squash before the spring
}

// MARK: - body layer (rebuilt only when the pose changes)

/// Body, belly sheen, outline, face. `pose` = 2N anchor coordinates followed by `phase`
/// (0 -> face of `f0`, 1 -> face of `f1`), all animated together by SwiftUI.
private struct PlasmieBody: View, Animatable {
    var pose: PlasmieVector
    let f0: PlasmieState
    let f1: PlasmieState
    let scheme: ColorScheme

    var animatableData: PlasmieVector {
        get { pose }
        set { pose = newValue }
    }

    var body: some View {
        Canvas { ctx, size in
            let n = (pose.v.count - 1) / 2
            guard n >= 3 else { return }
            var c = ctx
            let k = size.width / 100
            c.scaleBy(x: k, y: k)
            let pts = Array(pose.points.prefix(n))
            let phase = Double(min(max(pose.v[2 * n], 0), 1))
            let path = PlasmieSpline.path(pts)
            let box = PlasmieSpline.bounds(pts)
            let offW = (f0 == .off ? 1 - phase : 0) + (f1 == .off ? phase : 0)
            let ink = PlasmieHues.ink.color(scheme)

            // contact shadow (offset, soft, quiet)
            c.fill(Path(ellipseIn: CGRect(x: box.midX - box.width * 0.31, y: box.maxY - 1.5,
                                          width: box.width * 0.62, height: 4.5)),
                   with: .color(ink.opacity(0.10)))
            c.fill(path, with: .color(PlasmieHues.body.mixed(PlasmieHues.off, offW, scheme)))
            // belly sheen: a soft ellipse clipped to the body
            c.drawLayer { l in
                l.clip(to: path)
                l.addFilter(.blur(radius: 2.5))
                l.opacity = 0.6 * (1 - offW)
                l.fill(Path(ellipseIn: CGRect(x: box.midX - box.width * 0.27, y: box.maxY - box.height * 0.34,
                                              width: box.width * 0.54, height: box.height * 0.26)),
                       with: .color(PlasmieHues.belly.color(scheme)))
            }
            c.stroke(path, with: .color(ink), style: StrokeStyle(lineWidth: 2.2, lineJoin: .round))

            // face(s): one when settled, a crossfade while morphing between two faces
            let a = f0.face, b = f1.face
            let layout = PlasmieLayout.mix(a.layout, b.layout, CGFloat(phase))
            func draw(_ face: PlasmieFace, _ opacity: Double) {
                guard opacity > 0.001 else { return }
                let marks = PlasmieFaceArt.marks(face, layout: layout, box: box)
                c.drawLayer { l in
                    l.opacity = opacity
                    for tone in [PlasmieMark.Tone.blush, .ink] {
                        let col = tone == .ink ? ink : PlasmieHues.blush.color(scheme).opacity(0.8)
                        for m in marks where m.tone == tone {
                            if let w = m.stroke {
                                l.stroke(m.path, with: .color(col),
                                         style: StrokeStyle(lineWidth: w, lineCap: .round, lineJoin: .round))
                            } else {
                                l.fill(m.path, with: .color(col))
                            }
                        }
                    }
                }
            }
            if f0 == f1 { draw(a, 1) } else { draw(a, 1 - phase); draw(b, phase) }
        }
    }
}

// MARK: - props layer (driven by time)

private struct PlasmieProps: View, Animatable {
    var phase: CGFloat
    let f0: PlasmieState
    let f1: PlasmieState
    let t: Double
    let age: Double
    let motion: Bool
    let scheme: ColorScheme

    var animatableData: CGFloat {
        get { phase }
        set { phase = newValue }
    }

    var body: some View {
        Canvas { ctx, size in
            var c = ctx
            let k = size.width / 100
            c.scaleBy(x: k, y: k)
            let p = Double(min(max(phase, 0), 1))
            func draw(_ s: PlasmieState, _ o: Double) {
                guard o > 0.001, let prop = s.face.prop else { return }
                c.drawLayer { l in
                    l.opacity = o
                    PlasmiePropArt.draw(prop, in: l, t: t, age: age, motion: motion, scheme: scheme)
                }
            }
            if f0 == f1 { draw(f0, 1) } else { draw(f0, 1 - p); draw(f1, p) }
        }
        .allowsHitTesting(false)
    }
}

private enum PlasmiePropArt {
    static func frac(_ x: Double) -> Double { x - floor(x) }

    static func star(_ c: CGPoint, _ r: CGFloat) -> Path {
        let q = r * 0.2
        var p = Path()
        p.move(to: CGPoint(x: c.x, y: c.y - r))
        p.addQuadCurve(to: CGPoint(x: c.x + r, y: c.y), control: CGPoint(x: c.x + q, y: c.y - q))
        p.addQuadCurve(to: CGPoint(x: c.x, y: c.y + r), control: CGPoint(x: c.x + q, y: c.y + q))
        p.addQuadCurve(to: CGPoint(x: c.x - r, y: c.y), control: CGPoint(x: c.x - q, y: c.y + q))
        p.addQuadCurve(to: CGPoint(x: c.x, y: c.y - r), control: CGPoint(x: c.x - q, y: c.y - q))
        p.closeSubpath()
        return p
    }

    static func draw(_ prop: PlasmieProp, in c: GraphicsContext, t: Double, age: Double, motion: Bool, scheme: ColorScheme) {
        let ink = PlasmieHues.ink.color(scheme)
        let sparkle = PlasmieHues.sparkle.color(scheme)
        func solid(_ p: Path, _ col: Color) { c.fill(p, with: .color(col)) }
        func line(_ p: Path, _ col: Color, _ w: CGFloat, dash: [CGFloat] = [], phase: CGFloat = 0) {
            c.stroke(p, with: .color(col),
                     style: StrokeStyle(lineWidth: w, lineCap: .round, lineJoin: .round, dash: dash, dashPhase: phase))
        }
        func star2(_ at: CGPoint, _ r: CGFloat, alpha: Double = 1) {
            guard r > 0.3 else { return }
            c.drawLayer { l in
                l.opacity = alpha
                l.fill(star(at, r), with: .color(sparkle))
                l.stroke(star(at, r), with: .color(ink), style: StrokeStyle(lineWidth: 1.2, lineJoin: .round))
            }
        }

        switch prop {
        case .dots:
            // three source-coloured dots fall into the bowl, ~1 cycle per second
            let cols = [PlasmieHues.slack, PlasmieHues.claude, PlasmieHues.confluence]
            let startX: [CGFloat] = [30, 50, 70]
            for i in 0..<3 {
                let ph = motion ? frac(t / 1.0 + Double(i) / 3) : [0.2, 0.5, 0.78][i]
                let x = startX[i] + (50 - startX[i]) * CGFloat(ph * ph)
                let y = 4 + CGFloat(ph) * 40
                let sc = ph > 0.8 ? (1 - ph) / 0.2 : 1
                let r = 4.6 * CGFloat(sc)
                solid(Path(ellipseIn: CGRect(x: x - r, y: y - r, width: 2 * r, height: 2 * r)), cols[i].color(scheme))
            }
        case .card:
            // a note card drops into the box and shrinks away, ~0.8 cycles per second
            let ph = motion ? frac(t / 1.25) : 0.3
            let y = -4 + 36 * CGFloat(pow(ph, 1.5))
            let sc = CGFloat(ph > 0.75 ? (1 - ph) / 0.25 : 1)
            var l = c
            l.translateBy(x: 50, y: y)
            l.rotate(by: .degrees(-8))
            l.scaleBy(x: sc, y: sc)
            let card = Path(roundedRect: CGRect(x: -6.5, y: -8, width: 13, height: 16), cornerRadius: 2.6)
            l.fill(card, with: .color(.white.opacity(0.97)))
            l.stroke(card, with: .color(ink), lineWidth: 1.3)
            var rows = Path()
            rows.move(to: CGPoint(x: -3.4, y: -3)); rows.addLine(to: CGPoint(x: 3.4, y: -3))
            rows.move(to: CGPoint(x: -3.4, y: 1)); rows.addLine(to: CGPoint(x: 1.2, y: 1))
            l.stroke(rows, with: .color(ink.opacity(0.55)), style: StrokeStyle(lineWidth: 1.5, lineCap: .round))
        case .spark:
            // pulsing spark, ~1.2 pulses per second
            let r = 8.5 + (motion ? 2.5 * CGFloat(sin(2 * .pi * t / 0.83)) : 0)
            star2(CGPoint(x: 80, y: 15), r)
            solid(Path(ellipseIn: CGRect(x: 86.5, y: 28.5, width: 4, height: 4)), sparkle)
        case .bang:
            let bob = motion ? 2.2 * CGFloat(sin(2 * .pi * t / 0.9)) : 0
            let cx: CGFloat = 88, cy: CGFloat = 12 + bob
            let badge = Path(ellipseIn: CGRect(x: cx - 7, y: cy - 7, width: 14, height: 14))
            solid(badge, sparkle)
            c.stroke(badge, with: .color(ink), lineWidth: 1.4)
            var bar = Path()
            bar.move(to: CGPoint(x: cx, y: cy - 3.8)); bar.addLine(to: CGPoint(x: cx, y: cy + 0.8))
            line(bar, ink, 2.1)
            solid(Path(ellipseIn: CGRect(x: cx - 1.2, y: cy + 2.6, width: 2.4, height: 2.4)), ink)
        case .sweat:
            let ph = motion ? frac(t / 1.4) : 0.3
            let x: CGFloat = 76, y = 38 + 8 * CGFloat(ph)
            let a = ph > 0.7 ? (1 - ph) / 0.3 : 1
            var d = Path()
            d.move(to: CGPoint(x: x, y: y - 5.5))
            d.addCurve(to: CGPoint(x: x + 3.4, y: y + 1.5), control1: CGPoint(x: x + 0.6, y: y - 2.5), control2: CGPoint(x: x + 3.4, y: y - 0.5))
            d.addCurve(to: CGPoint(x: x - 3.4, y: y + 1.5), control1: CGPoint(x: x + 3.4, y: y + 4.6), control2: CGPoint(x: x - 3.4, y: y + 4.6))
            d.addCurve(to: CGPoint(x: x, y: y - 5.5), control1: CGPoint(x: x - 3.4, y: y - 0.5), control2: CGPoint(x: x - 0.6, y: y - 2.5))
            c.drawLayer { l in
                l.opacity = a
                l.fill(d, with: .color(PlasmieHues.sweat.color(scheme)))
                l.stroke(d, with: .color(ink), lineWidth: 1.2)
            }
        case .sand:
            var stream = Path()
            stream.move(to: CGPoint(x: 50, y: 52)); stream.addLine(to: CGPoint(x: 50, y: 79))
            line(stream, sparkle, 1.9, dash: motion ? [2.4, 3.2] : [], phase: motion ? CGFloat(-t * 22) : 0)
            let h: CGFloat = 5 + (motion ? 3 * CGFloat(sin(2 * .pi * t / 1.6)) : 1)
            var mound = Path()
            mound.move(to: CGPoint(x: 38, y: 84))
            mound.addQuadCurve(to: CGPoint(x: 62, y: 84), control: CGPoint(x: 50, y: 84 - 2 * h))
            mound.closeSubpath()
            solid(mound, sparkle)
        case .zzz:
            // drifting z's, deliberately slow (~0.35 cycles per second)
            for i in 0..<3 {
                let ph = motion ? frac(t / 2.85 + Double(i) / 3) : [0.25, 0.6, 0.9][i]
                let s = 3.0 + 3.4 * CGFloat(ph)
                let x = 68 + 12 * CGFloat(ph), y = 50 - 26 * CGFloat(ph)
                var z = Path()
                z.move(to: CGPoint(x: x - s, y: y - s)); z.addLine(to: CGPoint(x: x + s, y: y - s))
                z.addLine(to: CGPoint(x: x - s, y: y + s)); z.addLine(to: CGPoint(x: x + s, y: y + s))
                c.drawLayer { l in
                    l.opacity = sin(.pi * ph)
                    l.stroke(z, with: .color(PlasmieHues.dream.color(scheme)),
                             style: StrokeStyle(lineWidth: 1.9, lineCap: .round, lineJoin: .round))
                }
            }
        case .hello:
            // a small "hi!" bubble pops in beside the raised hand, then fades
            let pop = motion ? min(max(age / 0.22, 0), 1) : 1
            let fade = motion ? min(max((1.9 - age) / 0.35, 0), 1) : 1
            let sc = CGFloat(0.3 + 0.7 * (1 - pow(1 - pop, 3)))
            guard fade > 0.001 else { return }
            var l = c
            l.translateBy(x: 76, y: 17)
            l.scaleBy(x: sc, y: sc)
            l.opacity = fade
            var bubble = Path(roundedRect: CGRect(x: -15, y: -8.5, width: 30, height: 17), cornerRadius: 8.5)
            bubble.move(to: CGPoint(x: -8, y: 7)); bubble.addLine(to: CGPoint(x: -11.5, y: 13)); bubble.addLine(to: CGPoint(x: -3, y: 8))
            l.fill(bubble, with: .color(.white.opacity(0.97)))
            l.stroke(bubble, with: .color(ink), style: StrokeStyle(lineWidth: 1.3, lineJoin: .round))
            let word = l.resolve(Text("hi!").font(.system(size: 11, weight: .bold, design: .rounded)).foregroundColor(ink))
            l.draw(word, at: .zero, anchor: .center)
        case .vein:
            // the classic anger mark: four short curved strokes, pulsing
            let pulse = motion ? 1 + 0.14 * CGFloat(sin(2 * .pi * t / 0.55)) : 1
            var l = c
            l.translateBy(x: 80, y: 20)
            l.scaleBy(x: pulse, y: pulse)
            var m = Path()
            for q in 0..<4 {
                let a = Double(q) * .pi / 2 + .pi / 4
                let ca = CGFloat(cos(a)), sa = CGFloat(sin(a))
                // each stroke is a bracket whose belly points at the centre, leaving a plus-shaped gap
                let p0 = CGPoint(x: ca * 8 - sa * 4.6, y: sa * 8 + ca * 4.6)
                let p1 = CGPoint(x: ca * 8 + sa * 4.6, y: sa * 8 - ca * 4.6)
                m.move(to: p0)
                m.addQuadCurve(to: p1, control: CGPoint(x: ca * 3.4, y: sa * 3.4))
            }
            l.stroke(m, with: .color(PlasmieHues.blush.color(scheme)),
                     style: StrokeStyle(lineWidth: 2.6, lineCap: .round, lineJoin: .round))
        case .hearts:
            // a few small hearts float up and fade
            let xs: [CGFloat] = [34, 66, 50]
            for i in 0..<3 {
                let ph = motion ? frac(t / 1.6 + Double(i) / 3) : [0.3, 0.5, 0.7][i]
                let x = xs[i] + 4 * CGFloat(sin(ph * 5 + Double(i) * 2))
                let y = 26 - 22 * CGFloat(ph)
                let r = CGFloat(3.4 + 2.6 * sin(.pi * min(ph * 1.6, 1)))
                var h = Path()
                h.move(to: CGPoint(x: x, y: y + 0.85 * r))
                h.addCurve(to: CGPoint(x: x - r, y: y - 0.2 * r), control1: CGPoint(x: x - 0.5 * r, y: y + 0.5 * r), control2: CGPoint(x: x - r, y: y + 0.2 * r))
                h.addCurve(to: CGPoint(x: x, y: y - 0.3 * r), control1: CGPoint(x: x - r, y: y - r), control2: CGPoint(x: x - 0.1 * r, y: y - r))
                h.addCurve(to: CGPoint(x: x + r, y: y - 0.2 * r), control1: CGPoint(x: x + 0.1 * r, y: y - r), control2: CGPoint(x: x + r, y: y - r))
                h.addCurve(to: CGPoint(x: x, y: y + 0.85 * r), control1: CGPoint(x: x + r, y: y + 0.2 * r), control2: CGPoint(x: x + 0.5 * r, y: y + 0.5 * r))
                c.drawLayer { l in
                    l.opacity = motion ? sin(.pi * ph) : 1
                    l.fill(h, with: .color(PlasmieHues.blush.color(scheme)))
                    l.stroke(h, with: .color(ink), style: StrokeStyle(lineWidth: 1, lineJoin: .round))
                }
            }
        case .sparkles:
            // one burst when Plasmie enters `success`, ~0.9s
            if motion {
                let a = age / 0.9
                guard a >= 0, a < 1 else { return }
                let e = 1 - pow(1 - a, 3)
                for i in 0..<6 {
                    let ang = (-90 + 60 * Double(i) + 15) * .pi / 180
                    let r = 16 + 34 * e
                    star2(CGPoint(x: 50 + CGFloat(cos(ang) * r), y: 50 + CGFloat(sin(ang) * r)),
                          CGFloat(1 + 6.5 * pow(1 - a, 0.7)), alpha: 1 - a * a)
                }
            } else {
                for (x, y, r) in [(18.0, 22.0, 5.5), (84.0, 20.0, 6.5), (88.0, 60.0, 4.5)] {
                    star2(CGPoint(x: x, y: y), CGFloat(r))
                }
            }
        }
    }
}

// MARK: - the view

struct PlasmieView: View {
    let state: PlasmieState
    var size: CGFloat = 44
    /// Freeze loops at this many seconds (previews and render proofs); nil = live.
    var frozenAt: Double? = nil

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.colorScheme) private var scheme
    @State private var shown: PlasmieState
    @State private var f0: PlasmieState
    @State private var f1: PlasmieState
    @State private var phase: CGFloat = 1
    @State private var entered = Date()
    @State private var squash = false

    init(state: PlasmieState, size: CGFloat = 44, frozenAt: Double? = nil) {
        self.state = state
        self.size = size
        self.frozenAt = frozenAt
        _shown = State(initialValue: state)
        _f0 = State(initialValue: state)
        _f1 = State(initialValue: state)
    }

    private var pose: PlasmieVector {
        PlasmieVector(v: shown.anchors.flatMap { [$0.x, $0.y] } + [phase])
    }

    var body: some View {
        let bodyLayer = PlasmieBody(pose: pose, f0: f0, f1: f1, scheme: scheme)
        Group {
            if let f = frozenAt {
                composed(bodyLayer, t: f, age: f)
            } else {
                TimelineView(.animation(minimumInterval: 1.0 / 30, paused: reduceMotion)) { tl in
                    composed(bodyLayer, t: tl.date.timeIntervalSinceReferenceDate,
                             age: tl.date.timeIntervalSince(entered))
                }
            }
        }
        .frame(width: size, height: size)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(state.label)
        .onChange(of: state) { morph(to: $0) }
    }

    private func composed(_ bodyLayer: PlasmieBody, t: Double, age: Double) -> some View {
        let x = xform(t, age: age)
        return ZStack {
            bodyLayer
                .scaleEffect(x: x.sx, y: x.sy, anchor: .bottom)
                .rotationEffect(.degrees(x.rot), anchor: .bottom)
            PlasmieProps(phase: phase, f0: f0, f1: f1, t: t, age: age, motion: !reduceMotion, scheme: scheme)
        }
        .scaleEffect(squash ? 0.96 : 1, anchor: .bottom)
        .id(reduceMotion ? shown.rawValue : "plasmie")          // Reduce Motion: new id = crossfade
        .transition(.opacity)
        .animation(reduceMotion ? PlasmieMotion.crossfade : nil, value: shown)
    }

    /// One transform for the whole body, from time alone — the path is never rebuilt for it.
    private func xform(_ t: Double, age: Double) -> (sx: CGFloat, sy: CGFloat, rot: Double) {
        guard !reduceMotion else { return (1, 1, 0) }
        let w = sin(2 * .pi * t / 2.4)
        switch shown {
        case .hi:        // wave: ~3 Hz, ±7°, fading out after ~1.2s
            let env = max(0, min(1, (1.4 - age) / 0.3)) * min(1, age / 0.08)
            return (1, 1, 7 * env * sin(2 * .pi * 3 * age))
        case .annoyed:   // puffed, tiny fast tremble
            return (1 + 0.012 * CGFloat(w), 1, 1.6 * sin(2 * .pi * 9 * t))
        case .petted:    // content little squish-purr
            let k = sin(2 * .pi * t / 0.7); return (1 + 0.025 * k, 1 - 0.03 * k, 0)
        case .off:       return (1, 1, 0)
        case .summarize: let k = sin(2 * .pi * t / 1.6); return (1 + 0.05 * k, 1 - 0.06 * k, 0)   // knead
        case .error:     return (1, 1, 3 * sin(2 * .pi * t / 0.9))                                 // wobble
        case .quiet:     let b = 0.018 * sin(2 * .pi * t / 3.6); return (1 + b, 1 + b, 0)
        default:         let b = 0.018 * w; return (1 + b, 1 + b, 0)                               // breathe
        }
    }

    private func morph(to new: PlasmieState) {
        entered = Date()
        if reduceMotion {
            withAnimation(PlasmieMotion.crossfade) { shown = new; f0 = new; f1 = new; phase = 1 }
            return
        }
        // anticipation: a 70ms dip, then the spring. Never overshoots.
        withAnimation(.easeOut(duration: PlasmieMotion.anticipation)) { squash = true }
        DispatchQueue.main.asyncAfter(deadline: .now() + PlasmieMotion.anticipation) {
            withAnimation(PlasmieMotion.morph) {
                squash = false
                shown = new
                if phase == 1 { f0 = new; phase = 0 } else { f1 = new; phase = 1 }
            }
        }
    }
}

// MARK: - mouse reactions

/// Horizontal shake driven by an animatable counter: each +1 is two quick wiggles.
private struct PlasmieShake: GeometryEffect {
    var shakes: CGFloat
    var amount: CGFloat
    var animatableData: CGFloat {
        get { shakes }
        set { shakes = newValue }
    }
    func effectValue(size: CGSize) -> ProjectionTransform {
        ProjectionTransform(CGAffineTransform(translationX: amount * sin(shakes * 2 * .pi * 2), y: 0))
    }
}

/// PlasmieView plus a transient mouse reaction on top of the real pipeline state.
/// One tap says hi; four quick taps annoy it; click-and-drag pets it. A single
/// DragGesture(minimumDistance: 0) owns both tap and drag, so they cannot double-fire:
/// the release is a tap only if the pointer never travelled past the 3pt threshold.
/// Reactions are timed, never sticky, so the pipeline state always comes back.
struct InteractivePlasmie: View {
    let state: PlasmieState
    var size: CGFloat = 104

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var reaction: PlasmieState?
    @State private var token = 0                 // invalidates stale "return to pipeline" timers
    @State private var taps: [Date] = []
    @State private var annoyedUntil = Date.distantPast
    @State private var petting = false
    @State private var lean: CGSize = .zero
    @State private var shakes: CGFloat = 0
    @State private var pop = false

    private enum Timing {
        static let hi = 1.6, annoyed = 2.2, extend = 1.2, petLinger = 0.9
        static let burstWindow = 1.5, burstTaps = 4, dragSlop: CGFloat = 3
    }

    var body: some View {
        PlasmieView(state: reaction ?? state, size: size)
            .modifier(PlasmieShake(shakes: shakes, amount: size * 0.03))
            .rotationEffect(.degrees(Double(lean.width / max(size, 1)) * 40), anchor: .bottom)
            .scaleEffect(x: 1 + abs(lean.width) / size * 0.5, y: 1 - abs(lean.width) / size * 0.35, anchor: .bottom)
            .offset(x: lean.width, y: lean.height * 0.5)
            .scaleEffect(pop ? 1.05 : 1, anchor: .bottom)
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged(dragChanged).onEnded(dragEnded))
            .accessibilityAction(named: "Say hi") { tap() }
    }

    // MARK: gestures

    private func dragChanged(_ v: DragGesture.Value) {
        guard hypot(v.translation.width, v.translation.height) > Timing.dragSlop else { return }
        if !petting {
            petting = true
            react(.petted, for: nil)
        }
        guard !reduceMotion else { return }
        let lim = size * 0.12
        let target = CGSize(width: max(-lim, min(lim, v.translation.width * 0.2)),
                            height: max(-lim, min(lim, v.translation.height * 0.2)))
        withAnimation(.interactiveSpring(response: 0.25, dampingFraction: 0.8)) { lean = target }
    }

    private func dragEnded(_ v: DragGesture.Value) {
        if petting {
            petting = false
            withAnimation(.spring(response: 0.35, dampingFraction: 0.75)) { lean = .zero }
            react(.petted, for: Timing.petLinger)          // linger, then back to the pipeline
        } else {
            tap()
        }
    }

    private func tap() {
        let now = Date()
        taps = taps.filter { now.timeIntervalSince($0) < Timing.burstWindow } + [now]
        if !reduceMotion {
            withAnimation(.easeOut(duration: 0.08)) { pop = true }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) {
                withAnimation(.spring(response: 0.3, dampingFraction: 0.6)) { pop = false }
            }
        }
        if reaction == .annoyed && now < annoyedUntil {
            // still cross: each extra tap buys a little more time and a shake
            annoyedUntil = now.addingTimeInterval(Timing.extend)
            shake()
            react(.annoyed, for: Timing.extend)
        } else if taps.count >= Timing.burstTaps {
            taps = []
            annoyedUntil = now.addingTimeInterval(Timing.annoyed)
            shake()
            react(.annoyed, for: Timing.annoyed)
        } else {
            react(.hi, for: Timing.hi)
        }
    }

    // MARK: reaction timing

    private func shake() {
        guard !reduceMotion else { return }
        withAnimation(.linear(duration: 0.4)) { shakes += 1 }
    }

    /// Show `s` now; with a duration, hand back to the pipeline state after it.
    private func react(_ s: PlasmieState, for seconds: Double?) {
        token += 1
        let mine = token
        if reaction != s { reaction = s }
        guard let seconds else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds) {
            guard token == mine, !petting else { return }
            reaction = nil
            taps = []
        }
    }
}
