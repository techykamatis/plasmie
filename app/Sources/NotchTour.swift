import SwiftUI

// First-run tour of the notch island: three short steps, shown once when Plasmie is set up,
// replayable from the Plasmie window (Maintain › Show the tour). It runs inside the island
// itself, so the first thing a new user learns is where Plasmie lives.

enum TourPrefs {
    static let key = "plasmie.toured"
    static var done: Bool {
        get { UserDefaults.standard.bool(forKey: key) }
        set { UserDefaults.standard.set(newValue, forKey: key) }
    }
}

struct TourStep {
    let pose: PlasmieState
    let title: String
    let body: String

    static let all: [TourStep] = [
        TourStep(pose: .idle, title: "Hi! I live beside your notch.",
                 body: "Hover here any time to see what I'm up to. My shape shows how things are going: a bowl while I catch your work, a puddle if something broke."),
        TourStep(pose: .ask, title: "Ask me anything about your work.",
                 body: "Press ⌃⌥⌘K anywhere, or hover and click Ask. Answers come from your own notes, worked out right here on this Mac."),
        TourStep(pose: .success, title: "Everything else is under More.",
                 body: "Connectors, settings, trophies and logs live in the \(Brand.name) window. Right-click me for quick options."),
    ]
}

struct NotchTourView: View {
    let step: Int
    let next: () -> Void
    let skip: () -> Void

    private var s: TourStep { TourStep.all[min(step, TourStep.all.count - 1)] }
    private var last: Bool { step >= TourStep.all.count - 1 }

    var body: some View {
        HStack(alignment: .center, spacing: 16) {
            PlasmieView(state: s.pose, size: 64)
                .frame(width: 64, height: 64)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 6) {
                Text(s.title).font(.klHeading).foregroundStyle(.white)
                Text(s.body).font(.klLabel).foregroundStyle(.white.opacity(0.75))
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 10) {
                    HStack(spacing: 5) {
                        ForEach(0..<TourStep.all.count, id: \.self) { i in
                            Circle().fill(Color.white.opacity(i == step ? 0.9 : 0.25)).frame(width: 6, height: 6)
                        }
                    }
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel("Step \(step + 1) of \(TourStep.all.count)")
                    Spacer(minLength: 8)
                    if !last {
                        Button("Skip", action: skip).buttonStyle(.plain)
                            .font(.klMeta).foregroundStyle(.white.opacity(0.6))
                    }
                    Button(action: next) {
                        Text(last ? "Got it" : "Next").font(.klMeta.weight(.semibold)).foregroundStyle(.black)
                            .padding(.horizontal, 12).padding(.vertical, 5)
                            .background(Capsule().fill(Color.plasmieBody))
                    }
                    .buttonStyle(.plain)
                    .keyboardShortcut(.defaultAction)
                }
                .padding(.top, 6)
            }
        }
        .padding(.horizontal, NotchMode.inset)
        .padding(.bottom, 18)
        .id(step)
        .transition(.opacity)
    }
}
