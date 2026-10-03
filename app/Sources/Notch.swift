import AppKit
import Combine
import SwiftUI

// EXPERIMENTAL: Plasmie in the notch. A black island that grows out of the hardware notch
// (or a small pill at top-centre on a Mac without one), shows Plasmie's shape and status,
// and opens a compact island on hover. The menu-bar icon stays; this is an extra surface.
// Toggle: UserDefaults "plasmie.notch" (Settings + the panel's Maintain group).

enum NotchPrefs {
    static let key = "plasmie.notch"
    static func register() { UserDefaults.standard.register(defaults: [key: true]) }
    static var isOn: Bool { UserDefaults.standard.bool(forKey: key) }
}

// MARK: - geometry

struct NotchGeometry: Equatable {
    var notchW: CGFloat
    var notchH: CGFloat
    var hasNotch: Bool

    static let fallback = NotchGeometry(notchW: 96, notchH: 24, hasNotch: false)
    /// As measured on the owner's 14" MacBook Pro (used by previews/renders).
    static let measured = NotchGeometry(notchW: 185, notchH: 32, hasNotch: true)

    /// The screen with a notch (auxiliary areas present), else the main screen as a pill.
    static func find() -> (screen: NSScreen?, geo: NotchGeometry) {
        for s in NSScreen.screens {
            if let l = s.auxiliaryTopLeftArea, let r = s.auxiliaryTopRightArea, s.safeAreaInsets.top > 0 {
                return (s, NotchGeometry(notchW: s.frame.width - l.width - r.width,
                                         notchH: s.safeAreaInsets.top, hasNotch: true))
            }
        }
        return (NSScreen.main ?? NSScreen.screens.first, .fallback)
    }
}

enum NotchMode: Equatable { case notch, resting, working, expanded, celebrating }

extension NotchMode {
    /// `tucked` = the brief moment the shape sits exactly on the hardware notch, so every
    /// open starts from the notch (black on black, invisible) and every close returns to it.
    static func resolve(tucked: Bool, hover: Bool, banner: Bool, working: Bool) -> NotchMode {
        tucked ? .notch : hover ? .expanded : banner ? .celebrating : working ? .working : .resting
    }
    func size(_ g: NotchGeometry) -> CGSize {
        // flush with the hardware notch, ONE ear on the left for the character: the right side
        // of the menu bar stays free, and no dot that could pass for the camera indicator
        let rest = CGSize(width: g.notchW + (g.hasNotch ? Self.ear : 0), height: g.notchH + (g.hasNotch ? 0 : 2))
        switch self {
        case .notch:       return CGSize(width: g.notchW, height: g.notchH)
        case .resting:     return rest
        case .working:     return CGSize(width: g.notchW + 2 * Self.ear + 140, height: rest.height)
        case .expanded:    return CGSize(width: 460, height: 210)
        case .celebrating: return CGSize(width: 360, height: 70)
        }
    }
    static let ear: CGFloat = 46
    /// Horizontal offset of the shape's centre from the notch's centre (resting leans left).
    func shift(_ g: NotchGeometry) -> CGFloat { self == .resting && g.hasNotch ? -Self.ear / 2 : 0 }
    var topRadius: CGFloat { self == .notch ? 6 : self == .resting || self == .working ? 9 : 12 }
    var bottomRadius: CGFloat { self == .notch ? 9 : self == .expanded ? 22 : self == .celebrating ? 18 : 12 }
}

/// Concave "shoulders" at the top corners (like the real notch), rounded bottom corners.
struct NotchShape: Shape {
    var top: CGFloat
    var bottom: CGFloat
    var animatableData: AnimatablePair<CGFloat, CGFloat> {
        get { AnimatablePair(top, bottom) }
        set { top = newValue.first; bottom = newValue.second }
    }
    func path(in r: CGRect) -> Path {
        let t = min(top, r.height / 2), b = min(bottom, r.height / 2, (r.width - 2 * t) / 2)
        var p = Path()
        p.move(to: CGPoint(x: r.minX, y: r.minY))
        p.addLine(to: CGPoint(x: r.maxX, y: r.minY))
        p.addQuadCurve(to: CGPoint(x: r.maxX - t, y: r.minY + t), control: CGPoint(x: r.maxX - t, y: r.minY))
        p.addLine(to: CGPoint(x: r.maxX - t, y: r.maxY - b))
        p.addQuadCurve(to: CGPoint(x: r.maxX - t - b, y: r.maxY), control: CGPoint(x: r.maxX - t, y: r.maxY))
        p.addLine(to: CGPoint(x: r.minX + t + b, y: r.maxY))
        p.addQuadCurve(to: CGPoint(x: r.minX + t, y: r.maxY - b), control: CGPoint(x: r.minX + t, y: r.maxY))
        p.addLine(to: CGPoint(x: r.minX + t, y: r.minY + t))
        p.addQuadCurve(to: CGPoint(x: r.minX, y: r.minY), control: CGPoint(x: r.minX + t, y: r.minY))
        p.closeSubpath()
        return p
    }
}

// MARK: - plain data in, so the view renders without a live Model

struct NotchInfo {
    var hero: PlasmieState = .idle
    var pipeline: PlasmieState = .idle
    var status = "ok"                 // plasmie-status state: ok / running / pending / error
    var reason = ""
    var stageName: String? = nil
    var accessory: String? = nil
    var fact: FunFact? = nil
    var activity = ""
    var celebrating: String? = nil

    var working: Bool { [.ingest, .summarize, .promote, .ask].contains(pipeline) }
    var word: String {
        switch pipeline {
        case .ingest: return "Catching"
        case .summarize: return "Kneading"
        case .promote: return "Filing"
        default: return "Thinking"
        }
    }
    var dot: Color { status == "error" ? .red : status == "pending" ? .orange : .green }
    var statusWord: String {
        switch status {
        case "error": return "needs attention"
        case "pending": return "needs review"
        case "running": return "working"
        default: return "all flowing"
        }
    }
}

struct NotchActions {
    var ask: () -> Void = {}
    var ingest: () -> Void = {}
    var trophies: () -> Void = {}
    var openFact: () -> Void = {}
}

// MARK: - view

struct NotchView: View {
    let info: NotchInfo
    let geo: NotchGeometry
    let mode: NotchMode
    var actions = NotchActions()
    var panelShift: CGFloat = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    // Width and height animate separately so the island pours DOWN out of the notch first,
    // then spreads OUT; closing narrows first, then rises back up into the notch.
    @State private var w: CGFloat = 0
    @State private var h: CGFloat = 0

    private var size: CGSize { mode.size(geo) }
    // Opening pops out of the notch (fast, a small bounce on halt); closing glides back in
    // (fast-to-slow). Content follows the shape: it grows from the notch a beat later on the
    // way out, and leaves first on the way in, so the island reads as coming out of the notch.
    private var opening: Bool { mode == .expanded || mode == .celebrating }
    private var anim: Animation {
        if reduceMotion { return .easeInOut(duration: 0.15) }
        return opening ? .spring(response: 0.38, dampingFraction: 0.66)
                       : .timingCurve(0.16, 1, 0.3, 1, duration: 0.34)
    }
    private var fromNotch: AnyTransition {
        reduceMotion ? .opacity : .asymmetric(
            insertion: .opacity.combined(with: .scale(scale: 0.4, anchor: .top))
                .animation(.spring(response: 0.38, dampingFraction: 0.7).delay(0.07)),
            removal: .opacity.combined(with: .scale(scale: 0.6, anchor: .top))
                .animation(.easeIn(duration: 0.1)))
    }

    var body: some View {
        ZStack(alignment: .top) {
            switch mode {
            case .notch:       Color.clear                     // exactly the hardware notch: nothing to show
            case .resting:     resting.transition(.opacity)
            case .working:     working.transition(.opacity)
            case .expanded:    expanded.transition(fromNotch)
            case .celebrating: banner.transition(fromNotch)
            }
        }
        .frame(width: w > 0 ? w : size.width, height: h > 0 ? h : size.height, alignment: .top)
        .background(NotchShape(top: mode.topRadius, bottom: mode.bottomRadius).fill(Color.black))
        .clipShape(NotchShape(top: mode.topRadius, bottom: mode.bottomRadius))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Plasmie, \(info.statusWord)")
        .offset(x: mode.shift(geo) - panelShift)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .animation(anim, value: mode)
        .ignoresSafeArea()
        .onAppear { w = size.width; h = size.height }
        .onChange(of: mode) { _ in grow(to: size) }
        .onChange(of: geo) { _ in w = size.width; h = size.height }
    }

    /// Opening: height leads (down from the notch top), width follows a beat later (out).
    /// Closing: width leads (in), then height (back up). Reduce Motion: both at once, briefly.
    private func grow(to t: CGSize) {
        guard !reduceMotion else {
            withAnimation(.easeInOut(duration: 0.15)) { w = t.width; h = t.height }; return
        }
        let growing = t.height > h || t.width > w
        if growing {
            withAnimation(.spring(response: 0.34, dampingFraction: 0.68)) { h = t.height }
            withAnimation(.spring(response: 0.4, dampingFraction: 0.64).delay(0.06)) { w = t.width }
        } else {
            withAnimation(.timingCurve(0.16, 1, 0.3, 1, duration: 0.28)) { w = t.width }
            withAnimation(.timingCurve(0.16, 1, 0.3, 1, duration: 0.3).delay(0.05)) { h = t.height }
        }
    }

    private var ear: CGFloat { (size.width - geo.notchW) / 2 - mode.topRadius }

    // Resting sits beside the notch on the left only: the character (wearing its stage
    // accessory) IS the status: its shape and pose change with the pipeline, so there is no
    // separate status dot (a green dot next to the notch reads as the camera indicator).
    private var resting: some View {
        HStack(spacing: 0) {
            PlasmieView(state: info.hero, size: geo.hasNotch ? 26 : 18, accessory: geo.hasNotch ? info.accessory : nil)
                .frame(width: geo.hasNotch ? NotchMode.ear - mode.topRadius : size.width)
            Spacer(minLength: 0)
        }
        .padding(.leading, geo.hasNotch ? mode.topRadius : 0)
        .frame(height: geo.notchH)
        .accessibilityHidden(true)
    }

    private var working: some View {
        HStack(spacing: 0) {
            PlasmieView(state: info.hero, size: 24).frame(width: ear)
            Spacer(minLength: geo.notchW)
            Text(info.word).font(.klLabel).foregroundStyle(.white).lineLimit(1)
                .minimumScaleFactor(0.8).frame(width: ear)
        }
        .padding(.horizontal, mode.topRadius)
        .frame(height: geo.notchH)
        .accessibilityHidden(true)
    }

    // The band under the notch line (notchH...height) holds the banner.
    private var banner: some View {
        HStack(spacing: 10) {
            PlasmieView(state: .success, size: 32, accessory: info.accessory)
            Text("New trophy: \(info.celebrating ?? "Trophy")")
                .font(.klLabel).foregroundStyle(.white).lineLimit(1).minimumScaleFactor(0.8)
        }
        .padding(.horizontal, 24)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
        .padding(.bottom, 4)
    }

    private var expanded: some View {
        HStack(alignment: .top, spacing: 14) {
            InteractivePlasmie(state: info.hero, size: 72, accessory: info.accessory)
                .help("Click to say hi · drag to pet")
            VStack(alignment: .leading, spacing: 7) {
                HStack(spacing: 6) {
                    Text("Plasmie").font(.klHeading).foregroundStyle(.white)
                    if let st = info.stageName {
                        Text(st).font(.klMeta).foregroundStyle(.white.opacity(0.6)).lineLimit(1)
                    }
                    Spacer(minLength: 4)
                    StatusPill(state: info.status, reason: info.reason).lineLimit(1)
                }
                factView
                HStack(spacing: 6) {
                    NotchChip(title: "Ask", symbol: "sparkle.magnifyingglass", label: "Ask Plasmie", action: actions.ask)
                    NotchChip(title: "Ingest", symbol: "tray.and.arrow.down", label: "Ingest now", action: actions.ingest)
                    NotchChip(title: "Trophies", symbol: "trophy", label: "Open trophies", action: actions.trophies)
                }
            }
        }
        .padding(.horizontal, mode.topRadius + 16)
        .padding(.top, geo.notchH + 8)
        .padding(.bottom, 14)
    }

    @ViewBuilder private var factView: some View {
        if let f = info.fact {
            Button(action: actions.openFact) {
                VStack(alignment: .leading, spacing: 2) {
                    Label { Text(f.kicker ?? "Did you know?").font(.klMeta.weight(.semibold)).foregroundStyle(.white.opacity(0.6)) }
                        icon: { Image(systemName: f.symbol).foregroundStyle(Color.plasmieBlush) }
                    Text(f.text ?? "").font(.klLabel).foregroundStyle(.white)
                        .lineLimit(3).multilineTextAlignment(.leading)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(f.kicker ?? "Fun fact"): \(f.text ?? ""). Opens the note in Obsidian.")
        } else {
            Text(info.activity.isEmpty ? "All quiet." : info.activity)
                .font(.klLabel).foregroundStyle(.white.opacity(0.7)).lineLimit(3)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        Spacer(minLength: 0)
    }
}

private struct NotchChip: View {
    let title: String
    let symbol: String
    let label: String
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Label(title, systemImage: symbol).font(.klMeta).foregroundStyle(.white)
                .padding(.horizontal, 10).padding(.vertical, 5)
        }
        .buttonStyle(NotchChipStyle())
        .accessibilityLabel(label)
    }
}

private struct NotchChipStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        HoverFill(pressed: configuration.isPressed) { configuration.label }
    }
}

private struct HoverFill<Content: View>: View {
    let pressed: Bool
    @ViewBuilder var content: () -> Content
    @State private var hover = false
    var body: some View {
        content()
            .background(Capsule().fill(Color.white.opacity(pressed ? 0.28 : hover ? 0.2 : 0.12)))
            .contentShape(Capsule())
            .onHover { hover = $0 }
    }
}

// MARK: - live wiring

final class NotchModel: ObservableObject {
    @Published var hovering = false
    @Published var banner = false
    @Published var bannerText: String? = nil
    @Published var tucked = false                 // shape sits exactly on the hardware notch
    @Published var panelShift: CGFloat = 0        // panel centre minus notch centre (pt)
    private var collapse: DispatchWorkItem?
    private var bannerEnd: DispatchWorkItem?
    private var phase: DispatchWorkItem?

    static let tuckIn = 0.09                      // resting ears fold into the notch
    static let tuckOut = 0.22                     // island has glided back into the notch

    /// Run `change` starting from the bare notch: fold into the notch (invisible, black on
    /// black), then apply the change so the island grows *out of* the notch. Closing is the
    /// mirror: shrink into the notch first, then let the resting ears come back.
    private func throughNotch(opening: Bool, _ change: @escaping () -> Void) {
        phase?.cancel()
        if opening {
            tucked = true
            let w = DispatchWorkItem { [weak self] in self?.tucked = false; change() }
            phase = w
            DispatchQueue.main.asyncAfter(deadline: .now() + Self.tuckIn, execute: w)
        } else {
            tucked = true; change()
            let w = DispatchWorkItem { [weak self] in self?.tucked = false }
            phase = w
            DispatchQueue.main.asyncAfter(deadline: .now() + Self.tuckOut, execute: w)
        }
    }

    /// Mouse is over the visible shape. Leaving collapses ~0.4 s later (re-entering cancels).
    func pointer(inside: Bool) {
        collapse?.cancel()
        if inside {
            if !hovering { throughNotch(opening: true) { [weak self] in self?.hovering = true } }
            return
        }
        guard hovering else { return }
        let w = DispatchWorkItem { [weak self] in
            self?.throughNotch(opening: false) { self?.hovering = false }
        }
        collapse = w
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4, execute: w)
    }

    func celebrate(_ name: String) {
        bannerText = name
        bannerEnd?.cancel()
        throughNotch(opening: true) { [weak self] in self?.banner = true }
        let w = DispatchWorkItem { [weak self] in
            self?.throughNotch(opening: false) { self?.banner = false }
        }
        bannerEnd = w
        DispatchQueue.main.asyncAfter(deadline: .now() + 4, execute: w)
    }
}

private struct NotchRoot: View {
    @ObservedObject var m: Model
    @ObservedObject var nm: NotchModel
    let geo: NotchGeometry
    let actions: NotchActions
    let onSize: (CGSize, CGFloat) -> Void

    var body: some View {
        let info = NotchInfo(hero: m.heroPlasmie, pipeline: m.plasmie, status: m.s.state, reason: m.s.reason,
                             stageName: m.stage?.name, accessory: m.stage?.accessory, fact: m.funFact,
                             activity: m.s.activity, celebrating: nm.bannerText)
        let mode = NotchMode.resolve(tucked: nm.tucked, hover: nm.hovering, banner: nm.banner, working: info.working)
        NotchView(info: info, geo: geo, mode: mode, actions: actions, panelShift: nm.panelShift)
            .onChange(of: mode) { onSize($0.size(geo), $0.shift(geo)) }
            .onAppear { onSize(mode.size(geo), mode.shift(geo)) }
    }
}

private final class NotchPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
    // Borderless windows are otherwise pushed below the menu bar.
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }
}

/// Hover is tested against the visible shape (the window can briefly be larger while it
/// shrinks), and the first click on a button works without activating the app.
private final class NotchHostingView<Root: View>: NSHostingView<Root> {
    var shape: () -> CGSize = { .zero }
    var shapeOffset: () -> CGFloat = { 0 }    // shape centre − panel centre (pt)
    var pointer: (Bool) -> Void = { _ in }

    required init(rootView: Root) { super.init(rootView: rootView) }
    @objc required dynamic init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    override var safeAreaInsets: NSEdgeInsets { NSEdgeInsets() }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(rect: .zero,
            options: [.mouseEnteredAndExited, .mouseMoved, .activeAlways, .inVisibleRect], owner: self, userInfo: nil))
    }
    private func test(_ e: NSEvent) {
        let p = convert(e.locationInWindow, from: nil), s = shape()
        let fromTop = isFlipped ? p.y : bounds.height - p.y
        pointer(abs(p.x - (bounds.midX + shapeOffset())) <= s.width / 2 && fromTop >= 0 && fromTop <= s.height)
    }
    override func mouseEntered(with e: NSEvent) { test(e) }
    override func mouseMoved(with e: NSEvent) { test(e) }
    override func mouseExited(with e: NSEvent) { pointer(false) }
}

final class NotchController {
    static let shared = NotchController()

    private weak var model: Model?
    private var panel: NotchPanel?
    private var shapeSize = NotchMode.resting.size(.measured)
    private var shapeShift: CGFloat = 0           // shape centre − notch centre
    private var resizeToken = 0
    private let nm = NotchModel()
    private var geo = NotchGeometry.fallback
    private var observers: [NSObjectProtocol] = []
    private var cancellable: AnyCancellable?

    /// Call once with the app's Model (idempotent). The "plasmie.notch" default drives show/hide.
    func start(model: Model) {
        guard self.model == nil else { return }
        self.model = model
        NotchPrefs.register()
        let nc = NotificationCenter.default
        observers = [
            nc.addObserver(forName: UserDefaults.didChangeNotification, object: nil, queue: .main) { [weak self] _ in self?.sync() },
            nc.addObserver(forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main) { [weak self] _ in self?.reposition() },
        ]
        cancellable = model.$celebrating.removeDuplicates().sink { [weak self] name in
            if let name { self?.nm.celebrate(name) }
        }
        sync()
    }

    func stop() {
        panel?.orderOut(nil)
        panel?.contentView = nil
        panel = nil
        nm.pointer(inside: false)
    }

    private func sync() {
        if NotchPrefs.isOn { if panel == nil { show() } } else if panel != nil { stop() }
    }

    private func show() {
        guard let model else { return }
        let found = NotchGeometry.find()
        guard found.screen != nil else { return }
        geo = found.geo
        shapeSize = NotchMode.resting.size(geo)
        shapeShift = NotchMode.resting.shift(geo)
        let p = NotchPanel(contentRect: NSRect(origin: .zero, size: shapeSize),
                           styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        p.level = NSWindow.Level(rawValue: NSWindow.Level.mainMenu.rawValue + 1)   // over the menu bar, under alerts
        p.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]     // no fullScreenAuxiliary: hides over full screen
        p.isOpaque = false; p.backgroundColor = .clear; p.hasShadow = false
        p.hidesOnDeactivate = false; p.isReleasedWhenClosed = false
        p.acceptsMouseMovedEvents = true
        let actions = NotchActions(
            ask: { OverlayController.shared.toggle() },
            ingest: { [weak model] in model?.kick("com.plasmie.dev-ingest", "Ingest") },
            trophies: { [weak model] in if let model { TrophiesController.shared.show(model) } },
            openFact: { [weak model] in
                if let model, let path = model.funFact?.path, !path.isEmpty { openInObsidian("\(model.s.vault)/\(path)") }
            })
        let host = NotchHostingView(rootView: NotchRoot(m: model, nm: nm, geo: geo, actions: actions) { [weak self] in self?.resize($0, $1) })
        host.sizingOptions = []
        host.shape = { [weak self] in self?.shapeSize ?? .zero }
        host.shapeOffset = { [weak self] in (self?.shapeShift ?? 0) - (self?.nm.panelShift ?? 0) }
        host.pointer = { [weak self] in self?.nm.pointer(inside: $0) }
        p.contentView = host
        panel = p
        place(p, rect(shapeSize, shapeShift))
        p.orderFrontRegardless()
    }

    private func reposition() {
        guard let p = panel else { return }
        geo = NotchGeometry.find().geo
        place(p, rect(shapeSize, shapeShift))
    }

    /// The shape's rect in screen coordinates: hung from the top edge, centred on the notch
    /// plus its shift (resting leans left so only one ear covers the menu bar).
    private func rect(_ size: CGSize, _ shift: CGFloat) -> NSRect {
        guard let s = NotchGeometry.find().screen else { return .zero }
        return NSRect(x: s.frame.midX - size.width / 2 + shift, y: s.frame.maxY - size.height,
                      width: size.width, height: size.height)
    }

    private func place(_ p: NSPanel, _ r: NSRect) {
        guard r != .zero, let s = NotchGeometry.find().screen else { return }
        p.setFrame(r, display: true)
        nm.panelShift = r.midX - s.frame.midX          // the view offsets the shape by the difference
    }

    /// Grow the window at once (SwiftUI animates the shape inside it); shrink it after the
    /// spring settles so a collapsed notch only takes events where it is drawn.
    private func resize(_ size: CGSize, _ shift: CGFloat) {
        guard let p = panel else { return }
        shapeSize = size; shapeShift = shift
        resizeToken += 1
        let token = resizeToken
        let target = rect(size, shift)
        let union = p.frame.union(target)
        if union != p.frame { place(p, union) }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            guard let self, token == self.resizeToken, let p = self.panel else { return }
            self.place(p, target)
        }
    }
}
