import AppKit
import SwiftUI

// Plasmie reads the vault itself: a note opens in the map window's reader pane, rendered
// natively, so nobody needs Obsidian (or has to register a vault with it) to read their notes.
// The renderer covers what Plasmie and a typical vault write: frontmatter (shown as chips),
// headings, paragraphs, bullet / numbered / task lists, quotes and callouts, fenced code,
// tables, rules, images, and inline bold / italic / code / links. Links stay inside the
// reader: [[wikilinks]] resolve the way Obsidian does (file name, then title), relative
// Markdown links from the note's folder; web links open in the browser.

// MARK: - the document

enum MDBlock: Equatable {
    case heading(Int, String)
    case paragraph(String)
    case item(level: Int, marker: String, task: Bool?, text: String)   // marker: "•" or "3."
    case quote(String)
    case code(String)
    case table([[String]])
    case image(String)
    case rule
}

struct MDDocument: Equatable {
    var meta: [(key: String, value: String)] = []
    var blocks: [MDBlock] = []

    static func == (a: MDDocument, b: MDDocument) -> Bool {
        a.blocks == b.blocks && a.meta.map(\.key) == b.meta.map(\.key) && a.meta.map(\.value) == b.meta.map(\.value)
    }

    /// The note opens with its own top heading: that is the title, shown once.
    var leadsWithHeading: Bool { if case .heading(1, _) = blocks.first { return true }; return false }

    var title: String? {
        if let t = meta.first(where: { $0.key == "title" })?.value, !t.isEmpty { return t }
        for b in blocks { if case .heading(1, let t) = b { return t } }
        return nil
    }

    /// Line-based block parse: forgiving, never fails, a line it doesn't know is text.
    static func parse(_ raw: String) -> MDDocument {
        var doc = MDDocument()
        var lines = raw.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n")
        if lines.first?.trimmingCharacters(in: .whitespaces) == "---",
           let end = lines.dropFirst().firstIndex(where: { $0.trimmingCharacters(in: .whitespaces) == "---" }) {
            doc.meta = frontmatter(Array(lines[1..<end]))
            lines.removeSubrange(0...end)
        }
        var para: [String] = []
        func flush() {
            // a single newline is a line break, as Obsidian shows it by default
            if !para.isEmpty { doc.blocks.append(.paragraph(para.joined(separator: "\n"))); para = [] }
        }
        var i = 0
        while i < lines.count {
            let line = lines[i], t = line.trimmingCharacters(in: .whitespaces)
            defer { i += 1 }
            if t.isEmpty { flush(); continue }
            if t.hasPrefix("```") || t.hasPrefix("~~~") {                       // fenced code
                flush()
                let fence = String(t.prefix(3))
                var body: [String] = []
                i += 1
                while i < lines.count, !lines[i].trimmingCharacters(in: .whitespaces).hasPrefix(fence) {
                    body.append(lines[i]); i += 1
                }
                doc.blocks.append(.code(body.joined(separator: "\n")))
                continue
            }
            if t.hasPrefix("<!--") {                                            // HTML comments
                flush()
                while i < lines.count, !lines[i].contains("-->") { i += 1 }
                continue
            }
            if let h = heading(t) { flush(); doc.blocks.append(.heading(h.0, h.1)); continue }
            if t.count >= 3, Set(t.replacingOccurrences(of: " ", with: "")).count == 1,
               ["-", "*", "_"].contains(t.first!) { flush(); doc.blocks.append(.rule); continue }
            if let img = image(t) { flush(); doc.blocks.append(.image(img)); continue }
            if t.hasPrefix(">") {                                               // quote / callout
                flush()
                var q: [String] = []
                while i < lines.count, lines[i].trimmingCharacters(in: .whitespaces).hasPrefix(">") {
                    var s = String(lines[i].trimmingCharacters(in: .whitespaces).dropFirst())
                    if s.hasPrefix(" ") { s.removeFirst() }
                    if let m = s.range(of: #"^\[!(\w+)\][+-]?\s*"#, options: .regularExpression) {
                        let kind = s[m].dropFirst(2).prefix { $0 != "]" }
                        let rest = s[m.upperBound...]
                        s = "**\(kind.capitalized)**" + (rest.isEmpty ? "" : " — \(rest)")
                    }
                    q.append(s); i += 1
                }
                i -= 1
                doc.blocks.append(.quote(q.joined(separator: "\n")))
                continue
            }
            if t.hasPrefix("|"), i + 1 < lines.count,
               lines[i + 1].range(of: #"^\s*\|?\s*:?-{2,}"#, options: .regularExpression) != nil {
                flush()
                var rows = [cells(t)]
                i += 2
                while i < lines.count, lines[i].trimmingCharacters(in: .whitespaces).hasPrefix("|") {
                    rows.append(cells(lines[i])); i += 1
                }
                i -= 1
                doc.blocks.append(.table(rows))
                continue
            }
            if let it = item(line) { flush(); doc.blocks.append(it); continue }
            para.append(t)
        }
        flush()
        return doc
    }

    private static func frontmatter(_ lines: [String]) -> [(key: String, value: String)] {
        var out: [(key: String, value: String)] = []
        for l in lines {
            let t = l.trimmingCharacters(in: .whitespaces)
            if t.hasPrefix("- "), let last = out.indices.last {                // block list under a key
                let v = String(t.dropFirst(2)).trimmingCharacters(in: CharacterSet(charactersIn: "\"' "))
                out[last].value += (out[last].value.isEmpty ? "" : ", ") + v
            } else if let c = t.firstIndex(of: ":"), !l.hasPrefix(" ") {
                var v = t[t.index(after: c)...].trimmingCharacters(in: .whitespaces)
                if v.hasPrefix("["), v.hasSuffix("]") { v = String(v.dropFirst().dropLast()) }
                v = v.split(separator: ",").map { $0.trimmingCharacters(in: CharacterSet(charactersIn: "\"' ")) }
                    .joined(separator: ", ")
                out.append((String(t[..<c]), v))
            }
        }
        return out
    }

    private static func heading(_ t: String) -> (Int, String)? {
        let n = t.prefix { $0 == "#" }.count
        guard (1...6).contains(n), t.dropFirst(n).first == " " else { return nil }
        return (n, t.dropFirst(n + 1).trimmingCharacters(in: CharacterSet(charactersIn: "# ")))
    }

    private static func image(_ t: String) -> String? {
        if t.hasPrefix("![["), t.hasSuffix("]]") {
            return String(t.dropFirst(3).dropLast(2).split(separator: "|").first ?? "")
        }
        if let m = t.range(of: #"^!\[[^\]]*\]\(([^)\s]+)[^)]*\)$"#, options: .regularExpression) {
            let s = t[m]
            if let o = s.firstIndex(of: "("), let e = s.lastIndex(of: ")") {
                return String(s[s.index(after: o)..<e]).components(separatedBy: " ").first
            }
        }
        return nil
    }

    private static func cells(_ l: String) -> [String] {
        var t = l.trimmingCharacters(in: .whitespaces)
        if t.hasPrefix("|") { t.removeFirst() }
        if t.hasSuffix("|") { t.removeLast() }
        return t.components(separatedBy: "|").map { $0.trimmingCharacters(in: .whitespaces) }
    }

    private static func item(_ line: String) -> MDBlock? {
        let indent = line.prefix { $0 == " " || $0 == "\t" }
            .reduce(0) { $0 + ($1 == "\t" ? 4 : 1) }
        let t = line.trimmingCharacters(in: .whitespaces)
        var marker: String, rest: Substring
        if let f = t.first, "-*+".contains(f), t.dropFirst().first == " " {
            marker = "•"; rest = t.dropFirst(2)
        } else if let m = t.range(of: #"^\d{1,3}[.)] "#, options: .regularExpression) {
            marker = String(t[m].dropLast(2)) + "."; rest = t[m.upperBound...]
        } else { return nil }
        var task: Bool?
        if rest.hasPrefix("[ ] ") { task = false; rest = rest.dropFirst(4) }
        else if rest.lowercased().hasPrefix("[x] ") { task = true; rest = rest.dropFirst(4) }
        return .item(level: min(indent / 2, 6), marker: marker, task: task, text: String(rest))
    }
}

// MARK: - inline text and links

enum NoteLink {
    static let scheme = "plasmie-note"

    /// Inline Markdown as AttributedString, with [[wikilinks]] turned into links the reader
    /// follows (`plasmie-note:target`), and Obsidian's ==highlight== / %%comments%% handled.
    static func inline(_ s: String) -> AttributedString {
        var t = s.replacingOccurrences(of: #"%%.*?%%"#, with: "", options: .regularExpression)
        t = t.replacingOccurrences(of: #"==([^=]+)=="#, with: "**$1**", options: .regularExpression)
        let wiki = try! NSRegularExpression(pattern: #"!?\[\[([^\]\n]+?)\]\]"#)
        let ns = t as NSString
        var out = "", last = 0
        for m in wiki.matches(in: t, range: NSRange(location: 0, length: ns.length)) {
            out += ns.substring(with: NSRange(location: last, length: m.range.location - last))
            let inner = ns.substring(with: m.range(at: 1))
            let parts = inner.split(separator: "|", maxSplits: 1).map(String.init)
            let target = parts[0], label = parts.count > 1 ? parts[1] : target.components(separatedBy: "#")[0]
            let enc = target.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? target
            out += "[\(label.replacingOccurrences(of: "]", with: ""))](\(scheme):\(enc))"
            last = m.range.location + m.range.length
        }
        out += ns.substring(from: last)
        let opts = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        return (try? AttributedString(markdown: out, options: opts)) ?? AttributedString(t)
    }
}

/// Every note in the vault by file name and title, for resolving [[wikilinks]].
final class VaultIndex {
    let root: String
    private var byKey: [String: String] = [:]      // lowercased stem or title -> vault-relative path

    init(root: String) {
        self.root = root
        let fm = FileManager.default
        guard let e = fm.enumerator(at: URL(fileURLWithPath: root), includingPropertiesForKeys: nil,
                                    options: [.skipsHiddenFiles, .skipsPackageDescendants]) else { return }
        for case let u as URL in e where u.pathExtension.lowercased() == "md" {
            let rel = String(u.path.dropFirst(root.count + 1))
            let stem = u.deletingPathExtension().lastPathComponent.lowercased()
            if byKey[stem] == nil || rel.count < byKey[stem]!.count { byKey[stem] = rel }   // shortest path wins
        }
    }

    /// `target` as Obsidian reads it: "folder/note#heading" -> note, by file name.
    func resolve(_ target: String) -> String? {
        var t = target.components(separatedBy: "#")[0].components(separatedBy: "^")[0]
        if t.lowercased().hasSuffix(".md") { t = String(t.dropLast(3)) }
        let key = (t as NSString).lastPathComponent.lowercased()
        if let r = byKey[key] { return r }
        let direct = (root as NSString).appendingPathComponent(t + ".md")
        return FileManager.default.fileExists(atPath: direct) ? t + ".md" : nil
    }
}

// MARK: - the reader pane

struct NoteReaderView: View {
    @ObservedObject var scene: MapScene
    let path: String                                 // absolute
    @State private var doc = MDDocument()
    @State private var truncated = false
    @State private var missing = false
    // editing: the file as loaded, its modification date, and the draft
    @State private var raw = ""
    @State private var loadedAt: Date?
    @State private var draft = ""
    @State private var conflict = false
    @State private var saveError: String?
    private static let maxBytes = 400_000            // a raw log can be long; show its start

    /// Your notes and Plasmie's wiki are editable; raw/ captures (the untouched record the
    /// hourly job appends to), files outside the vault (the bundled help) and a note shown
    /// only in part are read-only.
    private var editable: Bool {
        let v = scene.vault()
        return path.hasPrefix(v + "/") && !path.hasPrefix(v + "/raw/") && !truncated && !missing
            && path.lowercased().hasSuffix(".md")
    }
    private var editing: Bool { scene.readerEditing }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if editing {
                TextEditor(text: $draft)
                    .font(.klMono)
                    .padding(10)
                    .accessibilityLabel("Note text")
            } else {
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    if missing {
                        Text("This note isn't in your vault anymore.").klNote()
                    } else {
                        // the title once: the note's own top heading, else frontmatter / file name
                        if case .heading(1, let t)? = doc.blocks.first {
                            Text(NoteLink.inline(t)).font(.klTitle).textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                        } else {
                            Text(doc.title ?? fileTitle).font(.klTitle).textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        if !chips.isEmpty { chipRow }
                        ForEach(Array(doc.blocks.enumerated().dropFirst(doc.leadsWithHeading ? 1 : 0)), id: \.offset) { _, b in block(b) }
                        if truncated {
                            Text("This note is long; showing the start. Open it in another app for the rest.").klNote()
                        }
                    }
                }
                .padding(18)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .environment(\.openURL, OpenURLAction { url in follow(url) })
            }
        }
        .background(Color(nsColor: .textBackgroundColor))
        .onAppear(perform: load)
        .onChange(of: path) { _ in load() }
        .onDisappear { scene.readerEditing = false }
        .alert("This note changed while you were editing", isPresented: $conflict) {
            Button("Keep Editing", role: .cancel) {}
            Button("Discard My Changes", role: .destructive) { scene.readerEditing = false; load() }
            Button("Save Anyway") { write(force: true) }
        } message: {
            Text("Something else saved it since you opened it, perhaps \(Brand.name)'s nightly filing. Saving now replaces that version with yours.")
        }
        .alert("Couldn't save the note", isPresented: Binding(get: { saveError != nil }, set: { if !$0 { saveError = nil } })) {
            Button("OK", role: .cancel) {}
        } message: { Text(saveError ?? "") }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Note: \(doc.title ?? fileTitle)")
    }

    private var fileTitle: String { ((path as NSString).lastPathComponent as NSString).deletingPathExtension }

    private var relPath: String {
        let v = scene.vault()
        return path.hasPrefix(v + "/") ? String(path.dropFirst(v.count + 1)) : (path as NSString).lastPathComponent
    }

    private var header: some View {
        HStack(spacing: 6) {
            Button { scene.readBack() } label: { Image(systemName: "chevron.left") }
                .disabled(!scene.canReadBack || editing).help("Back").accessibilityLabel("Back")
            Button { scene.readForward() } label: { Image(systemName: "chevron.right") }
                .disabled(!scene.canReadForward || editing).help("Forward").accessibilityLabel("Forward")
            Text(relPath).font(.klMeta).foregroundStyle(.secondary).lineLimit(1).truncationMode(.head)
            Spacer(minLength: 4)
            if editing {
                Button("Cancel") { scene.readerEditing = false; draft = raw }
                Button("Save") { write(force: false) }.keyboardShortcut("s", modifiers: .command)
                    .buttonStyle(.borderedProminent).controlSize(.small)
            } else if editable {
                Button { draft = raw; scene.readerEditing = true } label: { Label("Edit", systemImage: "pencil") }
                    .help("Edit this note's Markdown").keyboardShortcut("e", modifiers: .command)
            }
            Menu {
                Button("Open in Default App") { NSWorkspace.shared.open(URL(fileURLWithPath: path)) }
                Button("Edit as Text") { fireAndForget("/usr/bin/open", ["-t", path]) }
                Button("Show in Finder") { fireAndForget("/usr/bin/open", ["-R", path]) }
                if detectObsidian() { Button("Open in Obsidian") { openInObsidian(path) } }
            } label: { Image(systemName: "ellipsis.circle") }
                .menuStyle(.borderlessButton).fixedSize().help("More ways to open this note")
            Button { scene.closeReader() } label: { Image(systemName: "xmark") }
                .disabled(editing).help("Close the note").accessibilityLabel("Close note")
        }
        .buttonStyle(.borderless)
        .padding(.horizontal, 12).padding(.vertical, 8)
    }

    private var chips: [String] {
        doc.meta.filter { ["tags", "type", "date", "status"].contains($0.key) && !$0.value.isEmpty }
            .flatMap { $0.key == "tags" ? $0.value.components(separatedBy: ", ").map { "#" + $0 } : [$0.value] }
    }

    private var chipRow: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 5) { ForEach(chips, id: \.self, content: chip) }
            VStack(alignment: .leading, spacing: 4) { ForEach(chips, id: \.self, content: chip) }
        }
    }

    private func chip(_ s: String) -> some View {
        Text(s).font(.klMeta).foregroundStyle(.secondary)
            .padding(.horizontal, 7).padding(.vertical, 2)
            .background(Capsule().fill(Color.primary.opacity(0.07)))
    }

    @ViewBuilder private func block(_ b: MDBlock) -> some View {
        switch b {
        case .heading(let n, let t):
            Text(NoteLink.inline(t))
                .font(n == 1 ? .title2.weight(.semibold) : n == 2 ? .title3.weight(.semibold) : .headline)
                .padding(.top, n <= 2 ? 8 : 4)
                .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
        case .paragraph(let t):
            Text(NoteLink.inline(t)).font(.klBody).lineSpacing(2)
                .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
        case .item(let level, let marker, let task, let text):
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                if let task {
                    Image(systemName: task ? "checkmark.square.fill" : "square")
                        .foregroundStyle(task ? Color.accentColor : .secondary).accessibilityHidden(true)
                } else {
                    Text(marker).foregroundStyle(.secondary).monospacedDigit().accessibilityHidden(true)
                }
                Text(NoteLink.inline(text)).font(.klBody)
                    .strikethrough(task == true, color: .secondary)
                    .foregroundStyle(task == true ? .secondary : .primary)
                    .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
            }
            .padding(.leading, CGFloat(level) * 16)
            .accessibilityElement(children: .combine)
            .accessibilityValue(task == nil ? "" : task! ? "done" : "not done")
        case .quote(let t):
            HStack(alignment: .top, spacing: 10) {
                RoundedRectangle(cornerRadius: 1.5).fill(Color.secondary.opacity(0.4)).frame(width: 3)
                Text(NoteLink.inline(t)).font(.klBody).foregroundStyle(.secondary)
                    .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
            }
        case .code(let t):
            ScrollView(.horizontal, showsIndicators: false) {
                Text(t).font(.klMono).textSelection(.enabled).padding(10)
            }
            .background(RoundedRectangle(cornerRadius: 6).fill(Color.primary.opacity(0.06)))
        case .table(let rows):
            ScrollView(.horizontal, showsIndicators: false) {
                Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 6) {
                    ForEach(Array(rows.enumerated()), id: \.offset) { r, row in
                        GridRow {
                            ForEach(Array(row.enumerated()), id: \.offset) { _, c in
                                Text(NoteLink.inline(c)).font(r == 0 ? .klLabel.weight(.semibold) : .klLabel)
                                    .textSelection(.enabled)
                            }
                        }
                        if r == 0 { Divider().gridCellUnsizedAxes(.horizontal) }
                    }
                }
                .padding(10)
            }
            .background(RoundedRectangle(cornerRadius: 6).strokeBorder(Color.primary.opacity(0.1)))
        case .image(let src):
            if let img = image(src) {
                Image(nsImage: img).resizable().scaledToFit()
                    .frame(maxWidth: min(img.size.width, 560), alignment: .leading)
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                    .accessibilityLabel((src as NSString).lastPathComponent)
            } else {
                Label((src as NSString).lastPathComponent, systemImage: "photo").font(.klMeta).foregroundStyle(.secondary)
            }
        case .rule:
            Divider().padding(.vertical, 4)
        }
    }

    private func image(_ src: String) -> NSImage? {
        guard !src.contains("://") else { return nil }               // never fetch from the web
        let s = src.removingPercentEncoding ?? src
        let here = ((path as NSString).deletingLastPathComponent as NSString).appendingPathComponent(s)
        if let i = NSImage(contentsOfFile: here) { return i }
        if let rel = scene.index().resolveAny(s) { return NSImage(contentsOfFile: (scene.vault() as NSString).appendingPathComponent(rel)) }
        return nil
    }

    private func load() {
        missing = false; truncated = false
        guard let h = FileHandle(forReadingAtPath: path) else { missing = true; doc = MDDocument(); return }
        defer { try? h.close() }
        let data = h.readData(ofLength: Self.maxBytes + 1)
        truncated = data.count > Self.maxBytes
        raw = String(decoding: data.prefix(Self.maxBytes), as: UTF8.self)
        loadedAt = modified()
        doc = MDDocument.parse(raw)
    }

    private func modified() -> Date? {
        (try? FileManager.default.attributesOfItem(atPath: path))?[.modificationDate] as? Date
    }

    /// Save the draft over the note, atomically; refuses (asks) if the file changed on disk
    /// since it was opened, so a background job's write is never silently lost.
    private func write(force: Bool) {
        if !force, let was = loadedAt, let now = modified(), now != was { conflict = true; return }
        do {
            try draft.write(toFile: path, atomically: true, encoding: .utf8)
            scene.readerEditing = false
            load()
        } catch {
            saveError = error.localizedDescription
        }
    }

    /// Links stay in the reader when they point at a note; the web opens in the browser.
    private func follow(_ url: URL) -> OpenURLAction.Result {
        let s = url.absoluteString
        if s.hasPrefix(NoteLink.scheme + ":") {
            let target = String(s.dropFirst(NoteLink.scheme.count + 1)).removingPercentEncoding ?? ""
            if let rel = scene.index().resolve(target) { scene.read((scene.vault() as NSString).appendingPathComponent(rel)) }
            return .handled
        }
        if url.scheme == nil || url.scheme == "file" {
            let p = (url.scheme == "file" ? url.path : (s.removingPercentEncoding ?? s)).components(separatedBy: "#")[0]
            let base = p.hasPrefix("/") ? scene.vault() : (path as NSString).deletingLastPathComponent
            let abs = ((base as NSString).appendingPathComponent(p) as NSString).standardizingPath
            if FileManager.default.fileExists(atPath: abs) {
                if abs.lowercased().hasSuffix(".md") { scene.read(abs) } else { NSWorkspace.shared.open(URL(fileURLWithPath: abs)) }
            } else if let rel = scene.index().resolve(p) {
                scene.read((scene.vault() as NSString).appendingPathComponent(rel))
            }
            return .handled
        }
        return .systemAction
    }
}

extension VaultIndex {
    /// Any vault file by name (attachments, images), not only notes.
    func resolveAny(_ name: String) -> String? {
        let want = (name as NSString).lastPathComponent.lowercased()
        let e = FileManager.default.enumerator(at: URL(fileURLWithPath: root), includingPropertiesForKeys: nil,
                                               options: [.skipsHiddenFiles, .skipsPackageDescendants])
        while let u = e?.nextObject() as? URL {
            if u.lastPathComponent.lowercased() == want { return String(u.path.dropFirst(root.count + 1)) }
        }
        return nil
    }
}

/// Open a vault note in Plasmie's own reader (the map window), never requiring Obsidian.
func openNote(_ path: String) {
    MapController.shared.read(path)
}
