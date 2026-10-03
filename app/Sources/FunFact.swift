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

    var body: some View {
        HStack(alignment: .top, spacing: 6) {
            Button(action: open) {
                VStack(alignment: .leading, spacing: 3) {
                    Label {
                        Text(fact.kicker ?? "Did you know?").font(.klMeta.weight(.semibold)).foregroundStyle(.secondary)
                    } icon: {
                        Image(systemName: fact.symbol).foregroundStyle(Color.plasmieBlush)
                    }
                    Text(fact.text ?? "").font(.klLabel).foregroundStyle(.primary)
                        .lineLimit(4).multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
                .id(fact.id ?? fact.text)
                .transition(.opacity)
            }
            .buttonStyle(.plain)
            .help(fact.quote.map { $0 == fact.text ? "Open the note in Obsidian" : "In your notes: \($0)" } ?? "Open the note in Obsidian")
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("\(fact.kicker ?? "Fun fact"): \(fact.text ?? ""). Opens the note in Obsidian.")

            Button(action: another) {
                Image(systemName: "arrow.triangle.2.circlepath").font(.klMeta).foregroundStyle(.secondary)
                    .frame(width: 24, height: 24).contentShape(Rectangle())
            }
            .buttonStyle(.borderless)
            .help("Another fact")
            .accessibilityLabel("Another fact")
        }
        .padding(.horizontal, 10).padding(.vertical, 8)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.plasmieBody.opacity(0.08)))
        .padding(.horizontal, 12).padding(.bottom, 9)
        .animation(reduceMotion ? nil : .easeOut(duration: 0.25), value: fact)
    }
}
