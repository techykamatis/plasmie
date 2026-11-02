import AppKit
import SwiftUI

// The Review window: held items one at a time, each with what Plasmie found, the note it
// would join (its opening lines, so a wrong match is plain), why it asked, and three
// plain choices. Backed by engine/review.py, which lists items across every held file and
// applies one decision per item.

struct HeldTarget: Decodable, Equatable { let path: String; let title: String; let excerpt: String }
struct HeldOther: Decodable, Equatable { let path: String; let title: String; let pct: Int }
struct HeldItem: Decodable, Equatable, Identifiable {
    let file: String; let index: Int; let title: String; let body: String
    let from: String; let suggest: String; let why: String
    let target: HeldTarget?; let others: [HeldOther]
    var id: String { "\(file)#\(index)#\(title)" }
}

/// The engine calls the Review window and the notch share (engine/review.py).
enum HeldReview {
    struct Result: Decodable { let ok: Bool; let message: String }

    static func list(vault: String) -> [HeldItem] {
        struct Out: Decodable { let items: [HeldItem] }
        let out = runCapture(PlasmiePaths.python, [PlasmiePaths.script("review.py"), "list", vault])
        return (try? JSONDecoder().decode(Out.self, from: Data(out.utf8)))?.items ?? []
    }

    static func decide(_ it: HeldItem, _ choice: String, into: String? = nil, vault: String) -> Result {
        var args = [PlasmiePaths.script("review.py"), "decide", it.file, String(it.index), it.title, choice]
        if let into { args += ["--into", into] }
        let out = runCapture(PlasmiePaths.python, args + [vault])
        return (try? JSONDecoder().decode(Result.self, from: Data(out.utf8)))
            ?? Result(ok: false, message: "Something went wrong; nothing was filed.")
    }
}

extension HeldItem {
    /// The notch's one-line version of the card's question, naming both notes.
    var shortQuestion: String {
        let a = "\u{201C}\(Self.clip(title))\u{201D}"
        let b = target.map { "\u{201C}\(Self.clip($0.title))\u{201D}" } ?? ""
        switch suggest {
        case "add":  return "Should I merge \(a) into \(b)?"
        case "done": return "I put \(a) into \(b). Keep it there?"
        case "pattern": return "I keep seeing \(a) in your work. Save it as a pattern?"
        default:     return "Should I save \(a) as its own note?"
        }
    }
    /// What Yes and No do, matching the card's first two buttons.
    var yesChoice: String { suggest == "add" ? "add" : suggest == "done" ? "keep" : "new" }
    var noChoice: String { suggest == "add" || suggest == "done" ? "new" : "discard" }

    private static func clip(_ s: String) -> String { s.count > 28 ? String(s.prefix(26)) + "…" : s }
}

final class ReviewModel: ObservableObject {
    @Published var items: [HeldItem] = []
    @Published var at = 0
    @Published var loading = true
    @Published var busy = false
    @Published var message: String?
    let vault: String

    init(vault: String) { self.vault = vault }

    var current: HeldItem? { items.indices.contains(at) ? items[at] : nil }

    func load() {
        loading = true
        DispatchQueue.global().async {
            let items = HeldReview.list(vault: self.vault)
            DispatchQueue.main.async {
                self.items = items
                self.at = min(self.at, max(0, items.count - 1))
                self.loading = false
            }
        }
    }

    /// choice: keep / add / new / discard. `into` adds to another note than the suggested one.
    func decide(_ choice: String, into: String? = nil) {
        guard let it = current, !busy else { return }
        busy = true
        DispatchQueue.global().async {
            let r = HeldReview.decide(it, choice, into: into, vault: self.vault)
            DispatchQueue.main.async {
                self.busy = false
                self.message = r.message
                Model.shared.refresh()
                self.load()
            }
        }
    }
}

struct ReviewView: View {
    @ObservedObject var rm: ReviewModel
    let close: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider()
            if rm.loading && rm.items.isEmpty {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let it = rm.current {
                ScrollView { card(it).padding(20) }
                Divider()
                choices(it).padding(.horizontal, 20).padding(.vertical, 14)
            } else {
                done
            }
        }
        .frame(minWidth: 680, minHeight: 480)
        .background(Color(nsColor: .windowBackgroundColor))
        .background(Group {
            Button("Close", action: close).keyboardShortcut(.cancelAction)
            Button("Close Window", action: close).keyboardShortcut("w", modifiers: .command)
        }.opacity(0).frame(width: 0, height: 0).accessibilityHidden(true))
    }

    private var header: some View {
        HStack(spacing: 8) {
            Text(rm.items.isEmpty ? "Review" : "Review · \(rm.at + 1) of \(rm.items.count)").font(.klHeading)
            if let m = rm.message {
                Text(m).font(.klMeta).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            Button { rm.at -= 1; rm.message = nil } label: { Image(systemName: "chevron.left") }
                .disabled(rm.at == 0).help("Previous item")
            Button { rm.at += 1; rm.message = nil } label: { Image(systemName: "chevron.right") }
                .disabled(rm.at >= rm.items.count - 1).help("Next item")
        }
        .buttonStyle(.borderless)
        .padding(.horizontal, 20).padding(.vertical, 12)
    }

    /// Plasmie's question, in its own voice: what it isn't sure about.
    private func question(_ it: HeldItem) -> String {
        switch it.suggest {
        case "add":  return "I'm not sure if I should merge these two. Should I?"
        case "done": return "I merged these two on my own, but I'm not sure I got it right. Keep them together?"
        case "pattern": return "I keep seeing this in your work. Should I save it as a pattern?"
        case "new" where it.why.contains("isn't in your notes"):
            return "I was going to add this to a note that isn't there any more. Should I save it as its own note?"
        case "new":  return "I'm not sure this is worth its own note. Should I save it?"
        default:     return "I couldn't tell what to do with this. Should I save it as a note?"
        }
    }

    @ViewBuilder private func card(_ it: HeldItem) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .center, spacing: 14) {
                PlasmieView(state: .held, size: 46).accessibilityHidden(true)
                Text(question(it)).font(.klTitle).fixedSize(horizontal: false, vertical: true)
            }
            numbered(1, "What I found",
                     detail: it.from.isEmpty ? nil : "from \(it.from)") {
                Text(it.title).font(.klHeading)
                Text(it.body).font(.klBody).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
            }
            if let t = it.target {
                numbered(2, "Your note", detail: nil) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(t.title).font(.klHeading)
                        Spacer()
                        Button { openNote("\(rm.vault)/\(t.path)") } label: {
                            Label("Open note", systemImage: "arrow.up.forward.square")
                        }
                        .buttonStyle(.borderless).font(.klMeta).help("Read the whole note in the map")
                    }
                    Text(t.excerpt.isEmpty ? "This note is empty so far." : t.excerpt)
                        .font(.klBody).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
            }
            VStack(alignment: .leading, spacing: 4) {
                Text("Why I'm asking").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                Text(it.why).font(.klLabel).fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// One of the two things being compared, numbered so the question can point at them.
    @ViewBuilder private func numbered<C: View>(_ n: Int, _ title: String, detail: String?,
                                                @ViewBuilder _ content: () -> C) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text("\(n)").font(.klHeading).foregroundStyle(.white)
                .frame(width: 24, height: 24).background(Circle().fill(Color.orange))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 6) {
                    Text(title.uppercased()).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    if let detail { Text("· \(detail)").font(.caption).foregroundStyle(.secondary) }
                }
                content()
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.primary.opacity(0.05)))
        .accessibilityElement(children: .combine)
    }

    /// Other close notes as a menu: the "no, but it belongs over there" answer.
    @ViewBuilder private func elsewhere(_ it: HeldItem, _ title: String) -> some View {
        if !it.others.isEmpty {
            Menu(title) {
                ForEach(it.others, id: \.path) { o in
                    Button("\(o.title) (\(o.pct)% alike)") { rm.decide("add", into: o.path) }
                }
            }
            .fixedSize()
        }
    }

    @ViewBuilder private func choices(_ it: HeldItem) -> some View {
        HStack(spacing: 8) {
            switch it.suggest {
            case "add":
                choice("Yes, merge them", primary: true) { rm.decide("add") }
                choice("No, keep them separate", primary: false) { rm.decide("new") }
                elsewhere(it, "Another note…")
            case "done":
                choice("Yes, keep them together", primary: true) { rm.decide("keep") }
                choice("No, separate them", primary: false) { rm.decide("new") }
                elsewhere(it, "Move elsewhere…")
            case "pattern":
                choice("Yes, save it", primary: true) { rm.decide("new") }
                choice("No, skip it", primary: false) { rm.decide("discard") }
            default:
                choice("Yes, save it", primary: true) { rm.decide("new") }
                elsewhere(it, "Add to a note…")
            }
            Spacer()
            if it.suggest != "pattern" {
                Button(it.suggest == "done" ? "Remove it" : "Discard") { rm.decide("discard") }
                    .fixedSize()
                    .help(it.suggest == "done" ? "Take it out of \(it.target?.title ?? "that note") and keep nothing"
                                               : "Don't keep this at all")
            }
        }
        .controlSize(.large)
        .disabled(rm.busy)
    }

    @ViewBuilder private func choice(_ title: String, primary: Bool, _ action: @escaping () -> Void) -> some View {
        if primary {
            Button(title, action: action).buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction).fixedSize()
        } else {
            Button(title, action: action).buttonStyle(.bordered).fixedSize()
        }
    }

    private var done: some View {
        VStack(spacing: 10) {
            Image(systemName: "checkmark.circle").font(.system(size: 34)).foregroundStyle(.secondary)
            Text("Nothing is waiting for your review.").font(.klHeading)
            Button("Close", action: close)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }


    private func short(_ s: String) -> String { s.count > 32 ? String(s.prefix(30)) + "…" : s }
}

final class ReviewController: NSObject, NSWindowDelegate {
    static let shared = ReviewController()
    private var win: NSWindow?
    private var rm: ReviewModel?

    func show(vault: String) {
        if let w = win { rm?.load(); bringForward(w); return }
        let model = ReviewModel(vault: vault)
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 700, height: 620),
                         styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        w.title = "\(Brand.name) · Review"
        w.center(); w.isReleasedWhenClosed = false
        w.delegate = self
        w.contentView = NSHostingView(rootView: ReviewView(rm: model) { [weak self] in self?.win?.performClose(nil) })
        win = w; rm = model
        model.load()
        bringForward(w)
    }

    func windowWillClose(_ notification: Notification) { win = nil; rm = nil }
}
