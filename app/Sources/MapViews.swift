import SwiftUI

// Plasmie's map: the small native pieces around the canvas: toolbar, preview card, and
// the notes list (the accessible way through the map: every note by type, each one a
// button that opens it, with a "Show on map" action).

struct MapToolbar: View {
    @ObservedObject var scene: MapScene
    var findFocused: FocusState<Bool>.Binding

    var body: some View {
        HStack(spacing: 10) {
            Button { scene.listShown.toggle() } label: { Image(systemName: "sidebar.left") }
                .buttonStyle(.borderless)
                .help(scene.listShown ? "Hide the notes list" : "Show the notes list")
                .accessibilityLabel(scene.listShown ? "Hide notes list" : "Show notes list")
            find
            ViewThatFits(in: .horizontal) {
                chips(compact: false)
                chips(compact: true)
            }
            Spacer(minLength: 4)
            zoomButtons
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
    }

    private var find: some View {
        HStack(spacing: 5) {
            Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
            TextField("Find a note", text: $scene.search)
                .textFieldStyle(.plain)
                .focused(findFocused)
                .onSubmit { if let m = scene.match { scene.open(m) } }
                .accessibilityHint("Glides the map to the first matching note. Return opens it.")
            if !scene.search.isEmpty {
                Button { scene.search = "" } label: { Image(systemName: "xmark.circle.fill") }
                    .buttonStyle(.plain).foregroundStyle(.secondary).accessibilityLabel("Clear search")
            }
        }
        .font(.klLabel)
        .padding(.horizontal, 8).padding(.vertical, 5)
        .background(RoundedRectangle(cornerRadius: 6).fill(Color.primary.opacity(0.06)))
        .frame(width: 190)
    }

    private func chips(compact: Bool) -> some View {
        HStack(spacing: 5) {
            ForEach(scene.kindsPresent) { k in
                let on = !scene.hidden.contains(k)
                Button {
                    if on { scene.hidden.insert(k) } else { scene.hidden.remove(k) }
                } label: {
                    HStack(spacing: 5) {
                        MapSwatch(kind: k)
                        if !compact { Text(k.plural) }
                    }
                    .font(.klLabel)
                    .padding(.horizontal, compact ? 6 : 9).padding(.vertical, 4)
                    .background(Capsule().fill(Color.primary.opacity(on ? 0.07 : 0)))
                    .overlay(Capsule().strokeBorder(Color.primary.opacity(on ? 0.14 : 0.1)))
                    .opacity(on ? 1 : 0.5)
                    .contentShape(Capsule())
                }
                .buttonStyle(.plain)
                .help(on ? "Hide \(k.plural.lowercased())" : "Show \(k.plural.lowercased())")
                .accessibilityLabel(k.plural)
                .accessibilityValue(on ? "shown" : "hidden")
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
    }

    private var zoomButtons: some View {
        HStack(spacing: 2) {
            Button { scene.zoomStep(1 / 1.4) } label: { Image(systemName: "minus.magnifyingglass") }
                .help("Zoom out (⌘−)").accessibilityLabel("Zoom out")
            Button { scene.zoomStep(1.4) } label: { Image(systemName: "plus.magnifyingglass") }
                .help("Zoom in (⌘+)").accessibilityLabel("Zoom in")
            Button { scene.fit() } label: { Image(systemName: "scope") }
                .help("Fit the whole map (⌘0)").accessibilityLabel("Fit the whole map")
        }
        .buttonStyle(.borderless)
        .font(.klBody)
    }
}

/// The kind's colour as a small blob (filters, card chip, list rows).
struct MapSwatch: View {
    let kind: MapKind
    @Environment(\.colorScheme) private var scheme
    var body: some View {
        Circle().fill(kind.fill(scheme, fresh: 1))
            .overlay(Circle().strokeBorder(kind.rim(scheme).opacity(0.7), lineWidth: 1))
            .overlay(kind == .map ? Circle().strokeBorder(MapPalette.ring(scheme), lineWidth: 1.2).padding(-2.5) : nil)
            .frame(width: 9, height: 9)
            .accessibilityHidden(true)
    }
}

struct MapCard: View {
    let node: MapNode

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(node.title).font(.klHeading).lineLimit(2).fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                HStack(spacing: 4) { MapSwatch(kind: node.kind); Text(node.type) }
                    .padding(.horizontal, 7).padding(.vertical, 2)
                    .background(Capsule().fill(Color.primary.opacity(0.07)))
                if let d = AchDate.short(node.dateText) { Text(d) }
                Spacer(minLength: 0)
                Text(node.links == 1 ? "1 link" : "\(node.links) links")
            }
            .font(.klMeta).foregroundStyle(.secondary)
            if !node.excerpt.isEmpty {
                Text(node.excerpt.replacingOccurrences(of: "\n", with: " "))
                    .font(.klMeta).foregroundStyle(.secondary).lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .windowBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Color.primary.opacity(0.12)))
        .accessibilityHidden(true)          // the canvas is one element; the list carries the notes
    }
}

struct MapNotesList: View {
    @ObservedObject var scene: MapScene
    let graph: MapGraph

    private func items(_ k: MapKind) -> [MapNode] {
        let q = scene.search.trimmingCharacters(in: .whitespaces).lowercased()
        return graph.nodes
            .filter { $0.kind == k && (q.isEmpty || $0.title.lowercased().contains(q)) }
            .sorted { $0.title.localizedCaseInsensitiveCompare($1.title) == .orderedAscending }
    }

    var body: some View {
        List {
            ForEach(MapKind.allCases.filter { !scene.hidden.contains($0) }) { k in
                let rows = items(k)
                if !rows.isEmpty {
                    Section("\(k.plural) · \(rows.count)") {
                        ForEach(rows) { n in row(n) }
                    }
                }
            }
        }
        .listStyle(.sidebar)
        .accessibilityLabel("Notes on the map")
    }

    private func row(_ n: MapNode) -> some View {
        Button { scene.open(n.id) } label: {
            HStack(spacing: 7) {
                MapSwatch(kind: n.kind)
                Text(n.title).font(.klLabel).lineLimit(1)
                Spacer(minLength: 0)
                Text("\(n.links)").font(.klMeta).foregroundStyle(.tertiary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { inside in
            if inside { scene.listFocus = n.id } else if scene.listFocus == n.id { scene.listFocus = nil }
        }
        .accessibilityLabel("\(n.title), \(n.type), \(n.links == 1 ? "1 link" : "\(n.links) links")")
        .accessibilityHint("Opens the note in the reader")
        .accessibilityAction(named: "Show on map") { scene.listFocus = n.id; scene.show(n.id) }
    }
}
