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

enum NotchMode: Equatable, CaseIterable { case resting, working, expanded, celebrating, asking, answering }

extension NotchMode {
    static func resolve(ask: Bool, answered: Bool, hover: Bool, banner: Bool, working: Bool) -> NotchMode {
        ask ? (answered ? .answering : .asking)
            : hover ? .expanded : banner ? .celebrating : working ? .working : .resting
    }
    func size(_ g: NotchGeometry) -> CGSize {
        // flush with the hardware notch, ONE ear on the left for the character: the right side
        // of the menu bar stays free, and no dot that could pass for the camera indicator
        let rest = CGSize(width: g.notchW + (g.hasNotch ? Self.ear : 0), height: g.notchH + (g.hasNotch ? 0 : 2))
        switch self {
        case .resting:     return rest
        case .working:     return CGSize(width: g.notchW + 2 * Self.ear + 140, height: rest.height)
        case .expanded:    return CGSize(width: 460, height: 210)
        case .celebrating: return CGSize(width: 360, height: 70)
        case .asking:      return CGSize(width: 560, height: g.notchH + 84)
        case .answering:   return CGSize(width: 560, height: 470)
        }
    }
    static let ear: CGFloat = 46
    /// Horizontal offset of the shape's centre from the notch's centre (resting leans left).
    func shift(_ g: NotchGeometry) -> CGFloat { self == .resting && g.hasNotch ? -Self.ear / 2 : 0 }
    /// Content inset for the shoulders; matches what NotchShape draws at each mode's size.
    var topRadius: CGFloat { NotchShape.shoulder(self == .resting || self == .working ? 32 : 210) }
}

/// Concave "shoulders" at the top corners (like the real notch), rounded bottom corners.
/// Radii come from the rect being drawn, not the mode, so mid-animation corners always fit
/// the current size (mode-driven radii snapped small while the shape was still big: a
/// square-cornered black slab on every close).
struct NotchShape: Shape {
    static func shoulder(_ h: CGFloat) -> CGFloat { min(12, 9 + max(0, h - 32) / 12) }
    static func corner(_ h: CGFloat) -> CGFloat { min(22, max(12, 6 + h / 10)) }
    func path(in r: CGRect) -> Path {
        let t = min(Self.shoulder(r.height), r.height / 2)
        let b = min(Self.corner(r.height), r.height / 2, (r.width - 2 * t) / 2)
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
    var pending = 0                   // items held for review
    var loop = "", vault = "", notes = ""

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
    var vault: () -> Void = {}
    var openApp: () -> Void = {}      // the Plasmie window: every other option + settings
    var quit: () -> Void = {}
    var closeAsk: () -> Void = {}
    var answered: (Bool) -> Void = { _ in }
}

// MARK: - view

struct NotchView: View {
    let info: NotchInfo
    let geo: NotchGeometry
    let mode: NotchMode
    var actions = NotchActions()
    var panelShift: CGFloat = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var size: CGSize { mode.size(geo) }
    // One spring on the whole shape, hung from the top edge: it grows down and out of the
    // (black) notch and halts with a small bounce; closing glides back up, fast-to-slow.
    // Content arrives a beat after the shape and leaves with it, scaling toward the notch.
    private var opening: Bool { [.expanded, .celebrating, .asking, .answering].contains(mode) }
    private var anim: Animation {
        if reduceMotion { return .easeInOut(duration: 0.15) }
        return opening ? .spring(response: 0.36, dampingFraction: 0.72)
                       : .timingCurve(0.16, 1, 0.3, 1, duration: 0.3)
    }
    private var fromNotch: AnyTransition {
        reduceMotion ? .opacity : .asymmetric(
            insertion: .opacity.combined(with: .scale(scale: 0.85, anchor: .top))
                .animation(.easeOut(duration: 0.2).delay(0.08)),
            removal: .opacity.combined(with: .scale(scale: 0.85, anchor: .top))
                .animation(.easeIn(duration: 0.14)))
    }

    var body: some View {
        ZStack(alignment: .top) {
            switch mode {
            case .resting:     resting.transition(.opacity)
            case .working:     working.transition(.opacity)
            case .expanded:    expanded.transition(fromNotch)
            case .celebrating: banner.transition(fromNotch)
            case .asking, .answering:                      // one branch: the conversation keeps its state as it grows
                AskOverlay(loop: info.loop, vault: info.vault, notes: info.notes, onClose: actions.closeAsk,
                           inNotch: true, topInset: geo.notchH, onAnswer: actions.answered)
                    .transition(fromNotch)
            }
        }
        .frame(width: size.width, height: size.height, alignment: .top)
        .background(NotchShape().fill(Color.black))
        .clipShape(NotchShape())
        .contentShape(NotchShape())
        .contextMenu {
            Button("Ask Plasmie…", action: actions.ask)
            Button("Open Plasmie…", action: actions.openApp)
            Divider()
            Button("Quit Plasmie", action: actions.quit)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Plasmie, \(info.statusWord)")
        .offset(x: mode.shift(geo) - panelShift)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .animation(anim, value: mode)
        .ignoresSafeArea()
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
                        Button(action: actions.trophies) {
                            Text(st).font(.klMeta).foregroundStyle(.white.opacity(0.6)).lineLimit(1)
                        }
                        .buttonStyle(.plain).help("Open trophies").accessibilityLabel("\(st). Open trophies")
                    }
                    Spacer(minLength: 4)
                    StatusPill(state: info.status, reason: info.reason).lineLimit(1)
                }
                factView
                // the few things worth doing from the notch; everything else is one click away
                HStack(spacing: 6) {
                    NotchChip(title: "Ask", symbol: "sparkle.magnifyingglass", label: "Ask Plasmie", action: actions.ask)
                    if info.pending > 0 {
                        NotchChip(title: "Review \(info.pending)", symbol: "tray.full", label: "Review \(info.pending) held items",
                                  action: actions.openApp)
                    } else {
                        NotchChip(title: "Ingest", symbol: "tray.and.arrow.down", label: "Ingest now", action: actions.ingest)
                    }
                    NotchChip(title: "Vault", symbol: "folder", label: "Open the vault in Obsidian", action: actions.vault)
                    NotchChip(title: "More", symbol: "ellipsis.circle", label: "Open Plasmie: all options and settings",
                              action: actions.openApp)
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
    @Published var panelShift: CGFloat = 0        // panel centre minus notch centre (pt)
    @Published var asking = false                 // Ask is open in the island (sticky: hover can't close it)
    @Published var answered = false               // an answer is on screen: the island grows to hold it
    private var collapse: DispatchWorkItem?
    private var bannerEnd: DispatchWorkItem?

    /// Called on every pointer poll (30 Hz), so it must be idempotent: act only on changes.
    /// Entering opens; leaving collapses ~0.4 s later; re-entering cancels the collapse.
    func pointer(inside: Bool) {
        if inside {
            collapse?.cancel(); collapse = nil
            if !hovering { hovering = true }
            return
        }
        guard hovering, collapse == nil else { return }
        let w = DispatchWorkItem { [weak self] in self?.collapse = nil; self?.hovering = false }
        collapse = w
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4, execute: w)
    }

    func celebrate(_ name: String) {
        bannerText = name
        bannerEnd?.cancel()
        banner = true
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
    let onMode: (NotchMode, CGFloat) -> Void

    var body: some View {
        let info = NotchInfo(hero: m.heroPlasmie, pipeline: m.plasmie, status: m.s.state, reason: m.s.reason,
                             stageName: m.stage?.name, accessory: m.stage?.accessory, fact: m.funFact,
                             activity: m.s.activity, celebrating: nm.bannerText, pending: m.s.pending,
                             loop: m.s.loop, vault: m.s.vault, notes: m.s.notes)
        let mode = NotchMode.resolve(ask: nm.asking, answered: nm.answered, hover: nm.hovering, banner: nm.banner, working: info.working)
        NotchView(info: info, geo: geo, mode: mode, actions: actions, panelShift: nm.panelShift)
            .onChange(of: mode) { onMode($0, $0.shift(geo)) }
            .onAppear { onMode(mode, mode.shift(geo)) }
    }
}

private final class NotchPanel: NSPanel {
    var allowsKey = false                                  // only while Ask needs the keyboard
    override var canBecomeKey: Bool { allowsKey }
    override var canBecomeMain: Bool { false }
    // Borderless windows are otherwise pushed below the menu bar.
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }
}

/// Hover is tested against the visible shape (the window can briefly be larger while it
/// shrinks), and the first click on a button works without activating the app.
private final class NotchHostingView<Root: View>: NSHostingView<Root> {
    required init(rootView: Root) { super.init(rootView: rootView) }
    @objc required dynamic init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    override var safeAreaInsets: NSEdgeInsets { NSEdgeInsets() }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

/// One fixed-size, transparent panel that never resizes: every shape change happens inside
/// SwiftUI. Resizing the window mid-animation caused a black, square-cornered flash (window
/// grown before content was drawn) and hover flicker (tracking areas rebuilt on every resize
/// fired false exits). Hover is geometric instead: the pointer is polled and tested against
/// the shape's TARGET rect, and the panel ignores the mouse whenever the pointer is outside it,
/// so the transparent parts never block the menu bar.
final class NotchController {
    static let shared = NotchController()

    private weak var model: Model?
    private var panel: NotchPanel?
    private let nm = NotchModel()
    private var geo = NotchGeometry.fallback
    private var observers: [NSObjectProtocol] = []
    private var cancellable: AnyCancellable?
    private var poll: Timer?
    private var demo: Timer?
    /// The rect hover is tested against (screen coords): the current mode's target shape.
    private var hitRect: NSRect = .zero

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
        poll?.invalidate(); poll = nil
        demo?.invalidate(); demo = nil
        panel?.orderOut(nil)
        panel?.contentView = nil
        panel = nil
        nm.pointer(inside: false)
    }

    private func sync() {
        if let m = model, m.notchOn != NotchPrefs.isOn { m.notchOn = NotchPrefs.isOn }
        if NotchPrefs.isOn { if panel == nil { show() } } else if panel != nil { stop() }
    }

    private func show() {
        guard let model else { return }
        let found = NotchGeometry.find()
        guard found.screen != nil else { return }
        geo = found.geo
        let frame = panelFrame()
        let p = NotchPanel(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        p.level = NSWindow.Level(rawValue: NSWindow.Level.mainMenu.rawValue + 1)   // over the menu bar, under alerts
        p.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]     // no fullScreenAuxiliary: hides over full screen
        p.isOpaque = false; p.backgroundColor = .clear; p.hasShadow = false
        p.hidesOnDeactivate = false; p.isReleasedWhenClosed = false
        p.ignoresMouseEvents = true                                                // until the pointer is over the shape
        let actions = NotchActions(
            ask: { [weak self] in _ = self?.toggleAsk() },
            ingest: { [weak model] in model?.kick("com.plasmie.dev-ingest", "Ingest") },
            trophies: { [weak model] in if let model { TrophiesController.shared.show(model) } },
            openFact: { [weak model] in
                if let model, let path = model.funFact?.path, !path.isEmpty { openInObsidian("\(model.s.vault)/\(path)") }
            },
            vault: { [weak model] in if let model { openInObsidian(model.s.vault) } },
            openApp: { SettingsController.shared.show() },
            quit: { NSApp.terminate(nil) },
            closeAsk: { [weak self] in self?.closeAsk() },
            answered: { [weak self] in self?.nm.answered = $0 })
        let host = NotchHostingView(rootView: NotchRoot(m: model, nm: nm, geo: geo, actions: actions) { [weak self] in
            self?.target($0, $1)
        })
        host.sizingOptions = []
        p.contentView = host
        panel = p
        p.setFrame(frame, display: true)
        p.orderFrontRegardless()
        target(NotchMode.resting, NotchMode.resting.shift(geo))
        startPointer()
    }

    /// Open or close Ask in the island. Returns false when the island can't host it (notch
    /// off, or hidden on a full-screen Space) so the caller falls back to the floating panel.
    func toggleAsk() -> Bool {
        guard let p = panel else { return false }
        if nm.asking { closeAsk(); return true }
        guard p.occlusionState.contains(.visible) else { return false }
        nm.answered = false; nm.asking = true
        p.allowsKey = true; p.ignoresMouseEvents = false
        NSApp.activate(ignoringOtherApps: true)
        p.makeKeyAndOrderFront(nil)
        return true
    }

    private func closeAsk() {
        nm.asking = false; nm.answered = false
        panel?.resignKey(); panel?.allowsKey = false
        if SettingsController.shared.isOpen == false { NSApp.deactivate() }   // hand focus back to the previous app
    }

    private func reposition() {
        guard let p = panel else { return }
        geo = NotchGeometry.find().geo
        p.setFrame(panelFrame(), display: true)
    }

    /// The union of every state's rect, fixed for the life of the panel.
    private func panelFrame() -> NSRect {
        let u = NotchMode.allCases.map { rect($0.size(geo), $0.shift(geo)) }.reduce(NSRect.null) { $0.union($1) }
        if let s = NotchGeometry.find().screen { nm.panelShift = u.midX - s.frame.midX }
        return u.integral
    }

    /// A state's rect in screen coordinates: hung from the top edge, centred on the notch plus
    /// its shift (resting leans left so only one ear covers the menu bar).
    private func rect(_ size: CGSize, _ shift: CGFloat) -> NSRect {
        guard let s = NotchGeometry.find().screen else { return .zero }
        return NSRect(x: s.frame.midX - size.width / 2 + shift, y: s.frame.maxY - size.height,
                      width: size.width, height: size.height)
    }

    /// The view reports each new mode; hover is tested against its rect.
    private func target(_ mode: NotchMode, _ shift: CGFloat) {
        hitRect = rect(mode.size(geo), shift)
    }

    private func startPointer() {
        if ProcessInfo.processInfo.environment["PLASMIE_NOTCH_DEMO"] == "ask" {  // verification only
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in _ = self?.toggleAsk() }
        }
        if ProcessInfo.processInfo.environment["PLASMIE_NOTCH_DEMO"] == "1" {    // verification only
            var open = false
            demo = Timer.scheduledTimer(withTimeInterval: 2.5, repeats: true) { [weak self] _ in
                open.toggle(); self?.nm.pointer(inside: open)
            }
            return
        }
        poll = Timer.scheduledTimer(withTimeInterval: 1.0 / 30, repeats: true) { [weak self] _ in self?.tick() }
        poll?.tolerance = 0.01
    }

    private func tick() {
        guard let p = panel else { return }
        let inside = hitRect.insetBy(dx: -1, dy: -1).contains(NSEvent.mouseLocation)
        if p.ignoresMouseEvents == inside { p.ignoresMouseEvents = !inside }   // click-through outside the shape
        nm.pointer(inside: inside)
    }
}
