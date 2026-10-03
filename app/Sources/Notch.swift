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

enum NotchMode: Equatable { case resting, working, expanded, celebrating }

extension NotchMode {
    static func resolve(hover: Bool, banner: Bool, working: Bool) -> NotchMode {
        hover ? .expanded : banner ? .celebrating : working ? .working : .resting
    }
    func size(_ g: NotchGeometry) -> CGSize {
        // flush with the hardware notch: the character sits on the left ear, the dot on the right
        let rest = CGSize(width: g.notchW + 84, height: g.notchH + (g.hasNotch ? 0 : 2))
        switch self {
        case .resting:     return rest
        case .working:     return CGSize(width: rest.width + 140, height: rest.height)
        case .expanded:    return CGSize(width: 460, height: 210)
        case .celebrating: return CGSize(width: 360, height: 70)
        }
    }
    var topRadius: CGFloat { self == .resting || self == .working ? 9 : 12 }
    var bottomRadius: CGFloat { self == .expanded ? 22 : self == .celebrating ? 18 : 12 }
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
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

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
            case .resting:     resting.transition(.opacity)
            case .working:     working.transition(.opacity)
            case .expanded:    expanded.transition(fromNotch)
            case .celebrating: banner.transition(fromNotch)
            }
        }
        .frame(width: size.width, height: size.height, alignment: .top)
        .background(NotchShape(top: mode.topRadius, bottom: mode.bottomRadius).fill(Color.black))
        .clipShape(NotchShape(top: mode.topRadius, bottom: mode.bottomRadius))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Plasmie, \(info.statusWord)")
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .animation(anim, value: mode)
        .ignoresSafeArea()
    }

    private var ear: CGFloat { (size.width - geo.notchW) / 2 - mode.topRadius }

    // Resting sits beside the notch, not under it: the character on the left ear
    // (wearing its stage accessory), the status dot on the right ear.
    private var resting: some View {
        HStack(spacing: 0) {
            PlasmieView(state: info.hero, size: geo.hasNotch ? 26 : 18, accessory: geo.hasNotch ? info.accessory : nil)
                .frame(width: ear)
            Spacer(minLength: geo.hasNotch ? geo.notchW : 4)
            Circle().fill(info.dot).frame(width: 6, height: 6).frame(width: ear)
        }
        .padding(.horizontal, mode.topRadius)
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
    private var collapse: DispatchWorkItem?
    private var bannerEnd: DispatchWorkItem?

    /// Mouse is over the visible shape. Leaving collapses ~0.4 s later (re-entering cancels).
    func pointer(inside: Bool) {
        collapse?.cancel()
        if inside { if !hovering { hovering = true }; return }
        guard hovering else { return }
        let w = DispatchWorkItem { [weak self] in self?.hovering = false }
        collapse = w
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4, execute: w)
    }

    func celebrate(_ name: String) {
        bannerText = name; banner = true
        bannerEnd?.cancel()
        let w = DispatchWorkItem { [weak self] in self?.banner = false }
        bannerEnd = w
        DispatchQueue.main.asyncAfter(deadline: .now() + 4, execute: w)
    }
}

private struct NotchRoot: View {
    @ObservedObject var m: Model
    @ObservedObject var nm: NotchModel
    let geo: NotchGeometry
    let actions: NotchActions
    let onSize: (CGSize) -> Void

    var body: some View {
        let info = NotchInfo(hero: m.heroPlasmie, pipeline: m.plasmie, status: m.s.state, reason: m.s.reason,
                             stageName: m.stage?.name, accessory: m.stage?.accessory, fact: m.funFact,
                             activity: m.s.activity, celebrating: nm.bannerText)
        let mode = NotchMode.resolve(hover: nm.hovering, banner: nm.banner, working: info.working)
        NotchView(info: info, geo: geo, mode: mode, actions: actions)
            .onChange(of: mode) { onSize($0.size(geo)) }
            .onAppear { onSize(mode.size(geo)) }
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
        pointer(abs(p.x - bounds.midX) <= s.width / 2 && fromTop >= 0 && fromTop <= s.height)
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
        let host = NotchHostingView(rootView: NotchRoot(m: model, nm: nm, geo: geo, actions: actions) { [weak self] in self?.resize($0) })
        host.sizingOptions = []
        host.shape = { [weak self] in self?.shapeSize ?? .zero }
        host.pointer = { [weak self] in self?.nm.pointer(inside: $0) }
        p.contentView = host
        panel = p
        place(p, size: shapeSize)
        p.orderFrontRegardless()
    }

    private func reposition() {
        guard let p = panel else { return }
        geo = NotchGeometry.find().geo
        place(p, size: p.frame.size)
    }

    private func place(_ p: NSPanel, size: CGSize) {
        guard let s = NotchGeometry.find().screen else { return }
        p.setFrame(NSRect(x: s.frame.midX - size.width / 2, y: s.frame.maxY - size.height,
                          width: size.width, height: size.height), display: true)
    }

    /// Grow the window at once (SwiftUI animates the shape inside it); shrink it after the
    /// spring settles so a collapsed notch only takes events where it is drawn.
    private func resize(_ size: CGSize) {
        guard let p = panel else { return }
        shapeSize = size
        resizeToken += 1
        let token = resizeToken
        let union = CGSize(width: max(p.frame.width, size.width), height: max(p.frame.height, size.height))
        if union != p.frame.size { place(p, size: union) }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            guard let self, token == self.resizeToken, let p = self.panel else { return }
            self.place(p, size: size)
        }
    }
}
