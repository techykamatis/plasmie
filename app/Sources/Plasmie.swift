import SwiftUI

// Plasmie — the app's mascot. A soft blob that takes the shape of whatever the pipeline
// is doing. PlasmieView morphs between states (polar anchor blend through PlasmiePose), the
// face is a set of numbers that animate with the body (eyes open/close/curve, mouth
// widens/curls/opens), and one small physics prop plays per state. A state change is:
// anticipation squash -> `Motion.pop` morph that overshoots the new silhouette -> a
// decaying jelly wobble. Reduce Motion: morphs become a short crossfade and every loop
// stops on a static pose.

/// Shared "Ask is answering" flag. The Ask overlay writes it; Model reads it to put Plasmie
/// (and the menu-bar glyph) into the `ask` state.
final class AskActivity: ObservableObject {
    static let shared = AskActivity()
    @Published var answering = false
}

enum PlasmieMotion {
    static let morph = Motion.pop
    static let crossfade = Motion.crossfade
    static let anticipation = 0.08          // seconds of the 1.05 / 0.94 squash before the spring
    static let landing = 0.2                // seconds after a change when the pop first lands
}

/// Test/preview hook: render the frame `t` seconds after a change from `from` to `to`,
/// with the same maths the live view uses (anticipation, pop spring, wobble, props).
struct PlasmieMorphProof {
    var from: PlasmieState
    var to: PlasmieState
    var t: Double
}

// MARK: - body layer (rebuilt only when the pose changes)

/// Body, belly sheen, outline, face. `pose` is the whole animated vector (polar anchors
/// followed by face parameters), interpolated together by SwiftUI.
private struct PlasmieBody: View, Animatable {
    var pose: PlasmieVector
    let scheme: ColorScheme
    var accessory: String? = nil
    var blink: CGFloat = 0

    var animatableData: PlasmieVector {
        get { pose }
        set { pose = newValue }
    }

    var body: some View {
        Canvas { ctx, size in
            let (pts, face) = PlasmiePose.decode(pose)
            guard pts.count >= 3 else { return }
            var c = ctx
            let k = size.width / 100
            c.scaleBy(x: k, y: k)
            let path = PlasmieSpline.path(pts)
            let box = PlasmieSpline.bounds(pts)
            let offW = Double(min(max(face.dim, 0), 1))
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

            // face: parametric, so an expression change is a morph, never a crossfade
            let marks = PlasmieFaceArt.marks(face, box: box, blink: blink)
            for tone in [PlasmieMark.Tone.blush, .ink] {
                let col = tone == .ink ? ink : PlasmieHues.blush.color(scheme).opacity(0.8)
                for m in marks where m.tone == tone {
                    c.drawLayer { l in
                        l.opacity = m.alpha
                        if let w = m.stroke {
                            l.stroke(m.path, with: .color(col),
                                     style: StrokeStyle(lineWidth: w, lineCap: .round, lineJoin: .round))
                        } else {
                            l.fill(m.path, with: .color(col))
                        }
                    }
                }
            }
            if let acc = accessory { PlasmieAccessoryArt.draw(acc, box: box, in: c, scheme: scheme) }
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

/// Prop physics. Everything is a pure function of time (`t` loops, `age` = since the
/// state began), so frames are deterministic. Gravity falls follow y = y0 + (1/2) g t^2
/// (normalised so the fall ends exactly on the landing frame); impacts feed the body
/// squash through `PlasmieView.xform` using the same phase functions below.
private enum PlasmiePropArt {
    static func frac(_ x: Double) -> Double { Motion.frac(x) }

    // ingest: three dots, one lands every third of a second
    static let dotPeriod = 1.0, dotLand = 0.82
    static func dotPhase(_ t: Double, _ i: Int) -> Double { frac(t / dotPeriod + Double(i) / 3) }
    // promote: one card per cycle, lands at `cardLand`
    static let cardPeriod = 1.6, cardLand = 0.4
    // sand: grains fall into the pile
    static let grains = 5, grainPeriod = 1.0

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
            // three source-coloured dots fall under gravity with a slight sideways arc,
            // then plop into the mouth (the body squashes on each plop)
            let cols = [PlasmieHues.slack, PlasmieHues.claude, PlasmieHues.confluence]
            let startX: [CGFloat] = [30, 50, 70]
            let arc: [CGFloat] = [-3, 3, 3]
            for i in 0..<3 {
                let ph = motion ? dotPhase(t, i) : [0.2, 0.5, 0.78][i]
                let s = min(ph / dotLand, 1)
                let x = startX[i] + (50 - startX[i]) * CGFloat(s) + arc[i] * CGFloat(sin(.pi * s))
                let y = 4 + 40 * CGFloat(s * s)
                let sc = ph > dotLand ? max(0, 1 - (ph - dotLand) / 0.12) : 1
                let r = 4.6 * CGFloat(sc)
                guard r > 0.2 else { continue }
                solid(Path(ellipseIn: CGRect(x: x - r, y: y - r, width: 2 * r, height: 2 * r)), cols[i].color(scheme))
            }
        case .card:
            // a note card drops under gravity, straightens, lands in the box with a
            // bounce-on-halt, then tucks away
            let ph = motion ? frac(t / cardPeriod) : 0.3
            let s = min(ph / cardLand, 1)
            let tau = max(0, ph - cardLand) * cardPeriod
            let y = -4 + 36 * CGFloat(s * s) - CGFloat(Motion.bounce(tau, amp: 12))
            let sc = CGFloat(ph > 0.8 ? max(0, (0.95 - ph) / 0.15) : 1)
            var l = c
            l.translateBy(x: 50, y: y)
            l.rotate(by: .degrees(-8 * (1 - s) + 3 * Motion.wobble(tau, freq: 4, decay: 8)))
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
            // the badge hops and lands (|sin| = bounce-on-halt, no float)
            let hop = motion ? 3.2 * CGFloat(abs(sin(.pi * t / 0.9))) : 0
            let cx: CGFloat = 88, cy: CGFloat = 14 - hop
            let badge = Path(ellipseIn: CGRect(x: cx - 7, y: cy - 7, width: 14, height: 14))
            solid(badge, sparkle)
            c.stroke(badge, with: .color(ink), lineWidth: 1.4)
            var bar = Path()
            bar.move(to: CGPoint(x: cx, y: cy - 3.8)); bar.addLine(to: CGPoint(x: cx, y: cy + 0.8))
            c.stroke(bar, with: .color(ink), style: StrokeStyle(lineWidth: 2.1, lineCap: .round))
            solid(Path(ellipseIn: CGRect(x: cx - 1.2, y: cy + 2.6, width: 2.4, height: 2.4)), ink)
        case .sweat:
            // beads on the brow and slides slowly, then lets go and accelerates down
            let ph = motion ? frac(t / 1.6) : 0.3
            let hang = 0.5
            let slide = min(ph / hang, 1)
            let drop = max(0, (ph - hang) / (1 - hang))
            let x: CGFloat = 76 + 1.5 * CGFloat(drop * drop)
            let y = 36 + 7 * CGFloat(slide * slide * (3 - 2 * slide)) + 42 * CGFloat(drop * drop)
            let a = drop > 0.55 ? max(0, 1 - (drop - 0.55) / 0.45) : 1
            let stretch = 1 + 0.35 * CGFloat(drop)               // elongates as it falls
            var d = Path()
            d.move(to: CGPoint(x: x, y: y - 5.5 * stretch))
            d.addCurve(to: CGPoint(x: x + 3.4, y: y + 1.5), control1: CGPoint(x: x + 0.6, y: y - 2.5), control2: CGPoint(x: x + 3.4, y: y - 0.5))
            d.addCurve(to: CGPoint(x: x - 3.4, y: y + 1.5), control1: CGPoint(x: x + 3.4, y: y + 4.6), control2: CGPoint(x: x - 3.4, y: y + 4.6))
            d.addCurve(to: CGPoint(x: x, y: y - 5.5 * stretch), control1: CGPoint(x: x - 3.4, y: y - 0.5), control2: CGPoint(x: x - 0.6, y: y - 2.5))
            c.drawLayer { l in
                l.opacity = a
                l.fill(d, with: .color(PlasmieHues.sweat.color(scheme)))
                l.stroke(d, with: .color(ink), lineWidth: 1.2)
            }
        case .sand:
            // grains accelerate under gravity into the pile; each landing nudges it up
            var bump = 0.0
            for i in 0..<grains {
                let s = motion ? frac(t / grainPeriod + Double(i) / Double(grains)) : Double(i + 1) / Double(grains + 1)
                let x = 50 + [-1.2, 0.9, -0.4, 1.2, 0.1][i % 5]
                let y = 52 + 27 * CGFloat(s * s)
                solid(Path(ellipseIn: CGRect(x: x - 1.5, y: y - 1.5, width: 3, height: 3)), sparkle)
                if motion { bump += 0.8 * exp(-9 * s * grainPeriod) }
            }
            let h: CGFloat = 5.5 + CGFloat(bump)
            var mound = Path()
            mound.move(to: CGPoint(x: 38, y: 84))
            mound.addQuadCurve(to: CGPoint(x: 62, y: 84), control: CGPoint(x: 50, y: 84 - 2 * h))
            mound.closeSubpath()
            solid(mound, sparkle)
        case .zzz:
            // drifting z's, deliberately slow and buoyant (~0.35 cycles per second)
            for i in 0..<3 {
                let ph = motion ? frac(t / 2.85 + Double(i) / 3) : [0.25, 0.6, 0.9][i]
                let s = 3.0 + 3.4 * CGFloat(ph)
                let x = 68 + 12 * CGFloat(ph) + 2.2 * CGFloat(sin(2 * .pi * (ph * 1.4 + Double(i) / 3)))
                let y = 50 - 26 * CGFloat(1 - pow(1 - ph, 1.6))
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
            // a small "hi!" bubble pops in beside the raised hand (overshoots, settles), then fades
            let sc = CGFloat(motion ? 0.3 + 0.7 * Motion.springValue(age) : 1)
            let fade = motion ? min(max((1.9 - age) / 0.35, 0), 1) : 1
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
            // buoyant: a quick lift that slows as it rises, swaying wider as it goes, fading out
            let xs: [CGFloat] = [34, 66, 50]
            for i in 0..<3 {
                let ph = motion ? frac(t / 1.8 + Double(i) / 3) : [0.3, 0.5, 0.7][i]
                let rise = 1 - pow(1 - ph, 2)
                let x = xs[i] + CGFloat(2.5 + 6 * ph) * CGFloat(sin(ph * 6 + Double(i) * 2.1))
                let y = 30 - 28 * CGFloat(rise)
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
            // one burst when Plasmie enters `success`: launched outward with drag, then
            // pulled into gravity arcs while they shrink and fade, ~1s
            if motion {
                let a = age
                guard a >= 0, a < 1.0 else { return }
                let speeds = [110.0, 125, 100, 120, 105, 115]
                let jitter = [15.0, -8, 12, -14, 6, -10]
                for i in 0..<6 {
                    let ang = (-90 + 60 * Double(i) + jitter[i]) * .pi / 180
                    let dist = 14 + speeds[i] / 3 * (1 - exp(-3 * a))
                    let x = 50 + cos(ang) * dist
                    let y = 50 + sin(ang) * dist + 0.5 * 60 * a * a
                    star2(CGPoint(x: x, y: y), CGFloat(1 + 6.5 * pow(1 - a, 0.7)), alpha: 1 - a * a)
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
    /// Evolution accessory id (eggshell, leaf, glasses, mortarboard, wizard-hat, crown); nil = bare.
    var accessory: String? = nil
    /// Proof hook: render the frame `t` seconds into a from -> to change (no timers, no state).
    var morphProof: PlasmieMorphProof? = nil

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.colorScheme) private var scheme
    @State private var shown: PlasmieState
    @State private var f0: PlasmieState          // props crossfade (bodies and faces morph)
    @State private var f1: PlasmieState
    @State private var phase: CGFloat = 1
    @State private var entered = Date()
    @State private var landedAt = Date.distantPast   // wobble clock
    @State private var squash = false
    @State private var hot = false             // 60 fps while a change settles, 30 otherwise

    init(state: PlasmieState, size: CGFloat = 44, frozenAt: Double? = nil, accessory: String? = nil,
         morphProof: PlasmieMorphProof? = nil) {
        self.state = state
        self.size = size
        self.frozenAt = frozenAt
        self.accessory = accessory
        self.morphProof = morphProof
        _shown = State(initialValue: state)
        _f0 = State(initialValue: state)
        _f1 = State(initialValue: state)
    }

    var body: some View {
        Group {
            if let pr = morphProof {
                proofFrame(pr)
            } else if let f = frozenAt {
                composed(PlasmiePose.vector(shown), state: shown, f0: f0, f1: f1, phase: phase,
                         t: f, age: f, wobbleAge: -1, sq: 0)
            } else {
                TimelineView(.animation(minimumInterval: 1.0 / (hot ? 60 : 30), paused: reduceMotion)) { tl in
                    composed(PlasmiePose.vector(shown), state: shown, f0: f0, f1: f1, phase: phase,
                             t: tl.date.timeIntervalSinceReferenceDate,
                             age: tl.date.timeIntervalSince(entered),
                             wobbleAge: tl.date.timeIntervalSince(landedAt) - PlasmieMotion.landing,
                             sq: squash ? 1 : 0)
                }
            }
        }
        .frame(width: size, height: size)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(state.label)
        .onChange(of: state) { morph(to: $0) }
    }

    /// Deterministic frame of a morph: anticipation, then the closed-form pop spring.
    private func proofFrame(_ pr: PlasmieMorphProof) -> some View {
        let a = PlasmiePose.vector(pr.from), b = PlasmiePose.vector(pr.to)
        let tm = pr.t - PlasmieMotion.anticipation
        let s = Motion.springValue(tm)
        var d = b - a
        d.scale(by: s)
        let q: CGFloat = pr.t < PlasmieMotion.anticipation ? CGFloat(pr.t / PlasmieMotion.anticipation) : CGFloat(1 - s)
        let fade = CGFloat(min(max(tm / Motion.glideSeconds, 0), 1))
        return composed(a + d, state: pr.to, f0: pr.from, f1: pr.to, phase: fade,
                        t: pr.t, age: pr.t, wobbleAge: pr.t - PlasmieMotion.landing, sq: q)
    }

    private func composed(_ pose: PlasmieVector, state st: PlasmieState, f0: PlasmieState, f1: PlasmieState,
                          phase: CGFloat, t: Double, age: Double, wobbleAge: Double, sq: CGFloat) -> some View {
        let x = xform(st, t, age: age, wobbleAge: wobbleAge)
        let blink = reduceMotion ? 0 : Self.blink(st, t)
        return ZStack {
            PlasmieBody(pose: pose, scheme: scheme, accessory: accessory, blink: blink)
                .scaleEffect(x: x.sx, y: x.sy, anchor: .bottom)
                .rotationEffect(.degrees(x.rot), anchor: .bottom)
            PlasmieProps(phase: phase, f0: f0, f1: f1, t: t, age: age, motion: !reduceMotion, scheme: scheme)
        }
        .scaleEffect(x: 1 + 0.05 * sq, y: 1 - 0.06 * sq, anchor: .bottom)   // anticipation squash
        .id(reduceMotion ? st.rawValue : "plasmie")          // Reduce Motion: new id = crossfade
        .transition(.opacity)
        .animation(reduceMotion ? PlasmieMotion.crossfade : nil, value: shown)
    }

    /// Occasional blink while resting: one 120 ms close every 3-6 s (stable pseudo-random).
    static func blink(_ s: PlasmieState, _ t: Double) -> CGFloat {
        guard s == .idle || s == .held || s == .ask else { return 0 }
        let slot = 4.5
        let k = Int(floor(t / slot))
        let u = (t - (Double(k) * slot + 1.5 * Motion.hash(k))) / 0.12
        return u >= 0 && u < 1 ? CGFloat(sin(.pi * u)) : 0
    }

    /// One transform for the whole body, from time alone — the path is never rebuilt for it.
    private func xform(_ st: PlasmieState, _ t: Double, age: Double, wobbleAge: Double)
        -> (sx: CGFloat, sy: CGFloat, rot: Double) {
        guard !reduceMotion else { return (1, 1, 0) }
        let w = sin(2 * .pi * t / 2.4)
        var sx = 1.0, sy = 1.0, rot = 0.0
        switch st {
        case .hi:        // wave: ~3 Hz, a damped swing that dies away
            rot = 10 * exp(-1.8 * age) * sin(2 * .pi * 3 * age) * min(1, age / 0.08)
        case .annoyed:   // puffed, tiny fast tremble
            sx = 1 + 0.012 * w; rot = 1.6 * sin(2 * .pi * 9 * t)
        case .petted:    // content little squish-purr
            let k = sin(2 * .pi * t / 0.7); sx = 1 + 0.025 * k; sy = 1 - 0.03 * k
        case .off:       break
        case .summarize: let k = sin(2 * .pi * t / 1.6); sx = 1 + 0.05 * k; sy = 1 - 0.06 * k   // knead
        case .error:     rot = 3 * sin(2 * .pi * t / 0.9)                                        // wobble
        case .quiet:     let b = 0.018 * sin(2 * .pi * t / 3.6); sx = 1 + b; sy = 1 + b
        case .ingest:    // each dot that plops into the mouth gives a tiny jelly squash
            var k = 0.0
            for i in 0..<3 {
                let tau = Motion.frac(PlasmiePropArt.dotPhase(t, i) - PlasmiePropArt.dotLand) * PlasmiePropArt.dotPeriod
                k += min(1, tau / 0.03) * Motion.impulse(tau, freq: 4, decay: 10)
            }
            k *= 0.03; sx = 1 + 0.8 * k; sy = 1 - k
        case .promote:   // the card hits the box: squash, rebound, settle
            let tau = Motion.frac(t / PlasmiePropArt.cardPeriod - PlasmiePropArt.cardLand) * PlasmiePropArt.cardPeriod
            let k = 0.06 * min(1, tau / 0.03) * Motion.impulse(tau, freq: 2.8, decay: 7)
            sx = 1 + 0.8 * k; sy = 1 - k
        default:         let b = 0.018 * w; sx = 1 + b; sy = 1 + b                               // breathe
        }
        // secondary motion after landing in a new shape: damped oscillation of x/y around 1
        let j = 0.07 * Motion.wobble(wobbleAge, freq: 3.4, decay: 5.5)
        return (CGFloat(sx * (1 + j)), CGFloat(sy * (1 - j)), rot)
    }

    private func morph(to new: PlasmieState) {
        entered = Date()
        if reduceMotion {
            withAnimation(PlasmieMotion.crossfade) { shown = new; f0 = new; f1 = new; phase = 1 }
            return
        }
        hot = true
        landedAt = Date().addingTimeInterval(PlasmieMotion.anticipation)
        // anticipation: an 80ms crouch (wider, shorter), then the pop spring overshoots the new silhouette
        withAnimation(.easeOut(duration: PlasmieMotion.anticipation)) { squash = true }
        DispatchQueue.main.asyncAfter(deadline: .now() + PlasmieMotion.anticipation) {
            withAnimation(Motion.pop) {
                squash = false          // the release springs too: a little stretch on take-off
                shown = new             // polar anchors + face parameters morph together
            }
            withAnimation(Motion.glide) {
                if phase == 1 { f0 = new; phase = 0 } else { f1 = new; phase = 1 }   // props cross over
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { hot = false }
    }
}

// MARK: - mouse reactions

/// Horizontal shake driven by an animatable counter: each +1 is one damped oscillation
/// (starts strong, rings down) rather than a constant-amplitude wiggle.
private struct PlasmieShake: GeometryEffect {
    var shakes: CGFloat
    var amount: CGFloat
    var animatableData: CGFloat {
        get { shakes }
        set { shakes = newValue }
    }
    func effectValue(size: CGSize) -> ProjectionTransform {
        let u = Double(shakes - floor(shakes)) * 0.7              // seconds into the burst
        let x = amount * CGFloat(exp(-5 * u) * sin(2 * .pi * 5.5 * u))
        return ProjectionTransform(CGAffineTransform(translationX: x, y: 0))
    }
}

/// PlasmieView plus a transient mouse reaction on top of the real pipeline state.
/// One tap says hi; four quick taps annoy it; click-and-drag pets it. A single
/// DragGesture(minimumDistance: 0) owns both tap and drag, so they cannot double-fire:
/// the release is a tap only if the pointer never travelled past the 3pt threshold.
/// Reactions are timed, never sticky, so the pipeline state always comes back.
/// Physics: while dragging the body trails the pointer on a loose spring and tilts with
/// its velocity; on release it springs back through `Motion.jelly` and wobbles.
struct InteractivePlasmie: View {
    let state: PlasmieState
    var size: CGFloat = 104
    var accessory: String? = nil

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var reaction: PlasmieState?
    @State private var token = 0                 // invalidates stale "return to pipeline" timers
    @State private var taps: [Date] = []
    @State private var annoyedUntil = Date.distantPast
    @State private var petting = false
    @State private var lean: CGSize = .zero
    @State private var tilt: Double = 0          // degrees, from pointer velocity
    @State private var lastX: CGFloat = 0
    @State private var lastTime = Date.distantPast
    @State private var shakes: CGFloat = 0
    @State private var pop = false

    private enum Timing {
        static let hi = 1.6, annoyed = 2.2, extend = 1.2, petLinger = 0.9
        static let burstWindow = 1.5, burstTaps = 4, dragSlop: CGFloat = 3
    }

    var body: some View {
        PlasmieView(state: reaction ?? state, size: size, accessory: accessory)
            .modifier(PlasmieShake(shakes: shakes, amount: size * 0.045))
            .rotationEffect(.degrees(Double(lean.width / max(size, 1)) * 40 + tilt), anchor: .bottom)
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
            lastX = v.translation.width; lastTime = Date()
            react(.petted, for: nil)
        }
        guard !reduceMotion else { return }
        let now = Date()
        let dt = max(now.timeIntervalSince(lastTime), 0.008)
        let vx = Double(v.translation.width - lastX) / dt                    // pt/s
        lastX = v.translation.width; lastTime = now
        let lim = size * 0.12
        let target = CGSize(width: max(-lim, min(lim, v.translation.width * 0.2)),
                            height: max(-lim, min(lim, v.translation.height * 0.2)))
        // loose spring = visible lag behind the pointer; velocity leans the body into the motion
        withAnimation(.interactiveSpring(response: 0.3, dampingFraction: 0.5)) {
            lean = target
            tilt = max(-12, min(12, vx / 90))
        }
    }

    private func dragEnded(_ v: DragGesture.Value) {
        if petting {
            petting = false
            withAnimation(reduceMotion ? Motion.crossfade : Motion.jelly) { lean = .zero; tilt = 0 }
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
                withAnimation(Motion.pop) { pop = false }
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
        withAnimation(.linear(duration: 0.7)) { shakes += 1 }
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
