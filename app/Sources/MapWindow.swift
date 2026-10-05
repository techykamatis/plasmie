import AppKit
import SwiftUI

// Plasmie's map: the window. A toolbar (find, type filters, notes list, zoom), then the map
// itself: one Canvas inside a TimelineView that runs only while something moves, the real
// PlasmieView pinned at the world origin, an AppKit input layer for wheel / pinch / drag /
// hover, and the floating preview card. The notes list (also the VoiceOver route) slides in
// on the left. Opened from the Plasmie window's Open group, the notch's right-click menu,
// or `--map` at launch (a map-only viewer: no jobs, migrations or polling; for render checks).

enum LaunchMode {
    /// `--map`: open just the map and nothing else; quitting with the window.
    static let mapOnly = CommandLine.arguments.contains("--map")
}

final class MapController: NSObject, NSWindowDelegate {
    static let shared = MapController()
    private var win: NSWindow?
    let scene = MapScene()                     // outlives the window, so a note can open into it

    /// Open a note in the reader beside the map (the window opens if it isn't).
    func read(_ path: String) {
        show(.shared)
        scene.read((path as NSString).expandingTildeInPath)
    }

    func show(_ m: Model) {
        if let w = win { bringForward(w); return }
        if LaunchMode.mapOnly && CommandLine.arguments.contains("--dark") { NSApp.appearance = NSAppearance(named: .darkAqua) }
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1040, height: 720),
                         styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
        w.title = "\(Brand.name)'s map"
        w.isReleasedWhenClosed = false
        w.contentMinSize = NSSize(width: 720, height: 520)          // the reader squeezes the map, never the reverse
        w.center()
        if !LaunchMode.mapOnly { w.setFrameAutosaveName("\(Brand.id).map") }   // remembers where you left it
        w.delegate = self
        w.contentView = NSHostingView(rootView: MapWindowView(m: m, scene: scene) { [weak self] in self?.win?.performClose(nil) })
        win = w
        bringForward(w)
    }

    func windowWillClose(_ notification: Notification) {
        win = nil
        if LaunchMode.mapOnly { NSApp.terminate(nil) }
    }
}

struct MapWindowView: View {
    @ObservedObject var m: Model
    @ObservedObject var scene: MapScene
    let close: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduce
    @FocusState private var findFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            MapToolbar(scene: scene, findFocused: $findFocused)
            Divider()
            HStack(spacing: 0) {
                if scene.listShown, case .ready(let g) = scene.load, !g.isEmpty {
                    MapNotesList(scene: scene, graph: g).frame(width: 260)
                        .transition(.move(edge: .leading).combined(with: .opacity))
                    Divider()
                }
                MapArea(m: m, scene: scene)
                if let note = scene.reading {
                    Divider()
                    NoteReaderView(scene: scene, path: note).frame(minWidth: 340, idealWidth: 460, maxWidth: 620)
                        .transition(.move(edge: .trailing).combined(with: .opacity))
                }
            }
            .motion(Motion.glide, value: scene.listShown)
            .motion(Motion.glide, value: scene.reading == nil)
        }
        .frame(minWidth: 720, minHeight: 520)
        .background(shortcuts)
        .onAppear {
            scene.reduceMotion = reduce
            let model = m                                     // the app-lifetime Model.shared
            scene.vault = {
                // status first; before it has loaded (or in --map), the vault setup recorded
                var v = model.s.vault
                if v.isEmpty { v = ConfigStore.read(PlasmiePaths.config)["VAULT_DIR"] ?? "" }
                return NSString(string: v.isEmpty ? "~/knowledge" : v).expandingTildeInPath
            }
            if NSWorkspace.shared.isVoiceOverEnabled { scene.listShown = true }
            DispatchQueue.main.async { findFocused = true }   // type to find, straight away
            scene.reload()
        }
        .onChange(of: reduce) { scene.reduceMotion = $0; scene.wake() }
    }

    /// A menu-bar app has no main menu, so the window's shortcuts are wired here.
    private var shortcuts: some View {
        Group {
            Button("Zoom in") { scene.zoomStep(1.4) }.keyboardShortcut("+", modifiers: .command)
            Button("Zoom in") { scene.zoomStep(1.4) }.keyboardShortcut("=", modifiers: .command)
            Button("Zoom out") { scene.zoomStep(1 / 1.4) }.keyboardShortcut("-", modifiers: .command)
            Button("Fit") { scene.fit() }.keyboardShortcut("0", modifiers: .command)
            Button("Find") { findFocused = true }.keyboardShortcut("f", modifiers: .command)
            Button("Clear") {
                if scene.readerEditing { return }
                if scene.reading != nil && scene.search.isEmpty { scene.closeReader() } else { scene.clear() }
                findFocused = false
            }.keyboardShortcut(.cancelAction)
            Button("Back") { scene.readBack() }.keyboardShortcut("[", modifiers: .command)
            Button("Forward") { scene.readForward() }.keyboardShortcut("]", modifiers: .command)
            Button("Close Window", action: close).keyboardShortcut("w", modifiers: .command)
        }
        .opacity(0).frame(width: 0, height: 0).accessibilityHidden(true)
    }
}

// MARK: - the map area

private struct MapArea: View {
    @ObservedObject var m: Model
    @ObservedObject var scene: MapScene
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        GeometryReader { geo in
            ZStack {
                Rectangle().fill(PlasmieHues.mapGround.adaptive)
                switch scene.load {
                case .loading:
                    message(.ask, "Growing your map…", nil)
                case .failed(let why):
                    message(.error, "Couldn't draw your map", why, retry: true)
                case .ready(let g):
                    if g.isEmpty {
                        message(m.plasmie, "Nothing here yet — I'll grow a map as your notes arrive", nil)
                    } else {
                        live(g)
                    }
                }
            }
            .onAppear { scene.size = geo.size }
            .onChange(of: geo.size) { scene.size = $0; scene.wake() }
        }
    }

    private func message(_ state: PlasmieState, _ title: String, _ detail: String?, retry: Bool = false) -> some View {
        VStack(spacing: 12) {
            PlasmieView(state: state, size: MapScene.loadingSize, accessory: m.ach?.accessory)
            Text(title).font(.klHeading).multilineTextAlignment(.center)
            if let detail { Text(detail).klNote().multilineTextAlignment(.center).frame(maxWidth: 360) }
            if retry { Button("Try again") { scene.reload() }.keyboardShortcut(.defaultAction) }
        }
        .padding(32)
    }

    private var plasmieState: PlasmieState {
        if scene.introPose?.tada == true { return .tada }
        return scene.plasmieHover || Date() < scene.waveUntil ? .hi : m.plasmie
    }

    private func live(_ g: MapGraph) -> some View {
        ZStack(alignment: .topLeading) {
            TimelineView(.animation(minimumInterval: nil, paused: !scene.awake)) { tl in
                let _ = scene.advance(to: tl.date)
                ZStack(alignment: .topLeading) {
                    Canvas { ctx, _ in scene.draw(ctx, now: tl.date, scheme: scheme) }
                    PlasmieView(state: plasmieState, size: scene.plasmieSize,
                              frozenAt: scene.awake ? nil : 0, accessory: m.ach?.accessory)
                        .position(scene.screen(0, 0))
                        .allowsHitTesting(false)
                }
            }
            MapInput(scene: scene)
            card(g)
            footer(g)
        }
        .motion(Motion.pop, value: scene.hovered)
        .clipped()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Map of \(g.nodes.count) notes and \(g.edges.count) links")
        .accessibilityHint("Use Show notes list in the toolbar to browse and open notes")
    }

    @ViewBuilder private func card(_ g: MapGraph) -> some View {
        if let h = scene.hovered, g.nodes.indices.contains(h) {
            let w = 290.0, estH = 150.0
            let c = scene.cursor
            let x = c.x + 18 + w > scene.size.width ? c.x - w - 14 : c.x + 18
            let y = c.y + 20 + estH > scene.size.height ? max(c.y - estH - 10, 8) : c.y + 20
            MapCard(node: g.nodes[h])
                .frame(width: w, alignment: .leading)
                .offset(x: max(x, 8), y: y)
                .allowsHitTesting(false)
                .transition(.scale(scale: 0.92, anchor: .topLeading).combined(with: .opacity))
                .id(h)
        }
    }

    private func footer(_ g: MapGraph) -> some View {
        VStack {
            Spacer()
            HStack {
                Text("\(g.nodes.count) notes · \(g.edges.count) links")
                Spacer()
                Text("Scroll or pinch to zoom · drag to pan · click a note to read it")
            }
            .font(.klMeta).foregroundStyle(.secondary)
            .padding(.horizontal, 14).padding(.vertical, 10)
        }
        .allowsHitTesting(false)
    }
}

// MARK: - input (AppKit: wheel, pinch, hover and drag aren't all reachable from SwiftUI on 13)

private struct MapInput: NSViewRepresentable {
    let scene: MapScene
    func makeNSView(context: Context) -> MapInputView { let v = MapInputView(); v.scene = scene; return v }
    func updateNSView(_ v: MapInputView, context: Context) { v.scene = scene }
}

private final class MapInputView: NSView {
    weak var scene: MapScene?
    private var tracking: NSTrackingArea?
    private var panning = false

    override var isFlipped: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let t = tracking { removeTrackingArea(t) }
        let t = NSTrackingArea(rect: .zero, options: [.mouseMoved, .mouseEnteredAndExited, .activeAlways, .inVisibleRect],
                               owner: self, userInfo: nil)
        addTrackingArea(t)
        tracking = t
    }

    private func point(_ e: NSEvent) -> CGPoint { convert(e.locationInWindow, from: nil) }

    private func updateCursor(_ p: CGPoint) {
        guard let s = scene else { return }
        if panning { NSCursor.closedHand.set() } else if s.overMascot(p) || s.hovered != nil { NSCursor.pointingHand.set() } else { NSCursor.arrow.set() }
    }

    override func mouseMoved(with e: NSEvent) { let p = point(e); scene?.mouseMoved(p); updateCursor(p) }
    override func mouseExited(with e: NSEvent) { scene?.mouseExited(); NSCursor.arrow.set() }
    override func mouseDown(with e: NSEvent) {
        let p = point(e)
        scene?.mouseDown(p, clicks: e.clickCount)
        panning = scene.map { !$0.overMascot(p) && $0.hit(p) == nil } ?? false
    }
    override func mouseDragged(with e: NSEvent) { let p = point(e); scene?.mouseDragged(p); updateCursor(p) }
    override func mouseUp(with e: NSEvent) { let p = point(e); scene?.mouseUp(p); panning = false; updateCursor(p) }
    override func scrollWheel(with e: NSEvent) {
        scene?.scroll(dx: e.scrollingDeltaX, dy: e.scrollingDeltaY, precise: e.hasPreciseScrollingDeltas,
                      command: e.modifierFlags.contains(.command), at: point(e))
    }
    override func magnify(with e: NSEvent) { scene?.magnify(e.magnification, at: point(e)) }
}
