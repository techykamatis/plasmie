// Plasmie's fun fact: one line quoted from the vault (plasmie-funfact.py), useful or nostalgic.
import SwiftUI

struct FunFact: Codable, Equatable {
    var id: String?
    var kind: String?
    var kicker: String?
    var text: String?          // Plasmie's phrasing (or the quote when phrasing wasn't faithful)
    var quote: String?         // the vault's own words
    var title: String?
    var path: String?
    var date: String?

    var isUsable: Bool { !(text ?? "").isEmpty }
    var symbol: String {
        switch kind {
        case "on-this-day": return "clock.arrow.circlepath"
        case "milestone": return "star.fill"
        default: return "lightbulb.fill"
        }
    }
}

/// Runs the engine off the main thread. nil = nothing to show (empty vault, script missing, bad JSON).
func loadFunFact(next: Bool) -> FunFact? {
    let loop = "\(NSHomeDirectory())/.plasmie"
    let venv = "\(loop)/.venv/bin/python3"
    let py = FileManager.default.isExecutableFile(atPath: venv) ? venv : "/usr/bin/python3"
    let out = runCapture(py, ["\(loop)/plasmie-funfact.py"] + (next ? ["--next"] : []))
    guard let data = out.data(using: .utf8),
          let f = try? JSONDecoder().decode(FunFact.self, from: data), f.isUsable else { return nil }
    return f
}

struct FunFactCard: View {
    @ObservedObject var m: Model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        if let f = m.funFact {
            FunFactCardBody(fact: f, reduceMotion: reduceMotion,
                            open: { if let p = f.path, !p.isEmpty { openInObsidian("\(m.s.vault)/\(p)") } },
                            another: { m.nextFunFact() })
        }
    }
}

struct FunFactCardBody: View {
    let fact: FunFact
    var reduceMotion = false
    var open: () -> Void = {}
    var another: () -> Void = {}

    // Two explicit controls on the kicker row (another fact / open its note), same as the
    // notch island; the text is for reading, so it isn't a click target. Hover still shows
    // the vault's own words when Plasmie paraphrased them.
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 2) {
                Label {
                    Text(fact.kicker ?? "Did you know?").font(.klMeta.weight(.semibold)).foregroundStyle(.secondary)
                } icon: {
                    Image(systemName: fact.symbol).foregroundStyle(Color.plasmieBlush)
                }
                Spacer(minLength: 8)
                iconButton("arrow.clockwise", "Another fact", another)
                if !(fact.path ?? "").isEmpty {
                    iconButton("arrow.up.forward.square", "Open this note in Obsidian", open)
                }
            }
            Text(fact.text ?? "").font(.klLabel).foregroundStyle(.primary)
                .lineLimit(4).multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .help(fact.quote.map { $0 == fact.text ? "" : "In your notes: \($0)" } ?? "")
                .id(fact.id ?? fact.text)
                .transition(.asymmetric(insertion: .opacity.combined(with: .offset(y: 5)),
                                        removal: .opacity.combined(with: .offset(y: -5))))
        }
        .padding(.horizontal, 10).padding(.vertical, 8)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.plasmieBody.opacity(0.08)))
        .padding(.horizontal, 12).padding(.bottom, 9)
        .animation(Motion.resolved(Motion.glide, reduce: reduceMotion), value: fact)
    }

    private func iconButton(_ symbol: String, _ label: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.klMeta).foregroundStyle(.secondary)
                .frame(width: 24, height: 24).contentShape(Rectangle())
        }
        .buttonStyle(.borderless)
        .help(label)
        .accessibilityLabel(label)
    }
}
