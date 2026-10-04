import SwiftUI

// Plasmie's map: colour. Pink is Plasmie's alone (the owner's rule), so the mascot reads as
// the one living, pink heart of a calm, neutral network. Notes are graphite blobs; the
// accents come from tokens that already mean something: sparkle gold for decisions, sweat
// blue for gotchas, leaf green for patterns, deep ink for how-tos. Maps (mocs) are graphite
// with a ring. Veins are translucent ink; the lit vein glow and the nutrient pulses are a
// faint sparkle gold. Every value adapts to light and dark.

/// The filter groups; every vault type folds into one.
enum MapKind: Int, CaseIterable, Identifiable {
    case note, decision, gotcha, pattern, howto, map
    var id: Int { rawValue }

    init(type: String, hub: Bool) {
        if hub { self = .map; return }
        switch type {
        case "decision": self = .decision
        case "gotcha": self = .gotcha
        case "pattern", "convention": self = .pattern
        case "howto", "how-to": self = .howto
        default: self = .note
        }
    }

    var plural: String { ["Notes", "Decisions", "Gotchas", "Patterns", "How-tos", "Maps"][rawValue] }

    private var hue: PlasmieHue {
        switch self {
        case .note, .map: return PlasmieHues.mapNote
        case .decision: return PlasmieHues.sparkle
        case .gotcha: return PlasmieHues.sweat
        case .pattern: return PlasmieHues.leaf
        case .howto: return PlasmieHues.mapInk
        }
    }

    /// Fill. Recency: fresh notes are full strength, older ones ease part of the way toward
    /// the ground (never further: the palest graphite stays >= 3:1 on the ground). Maps are
    /// a light graphite: their ring (MapPalette.ring) carries the edge.
    func fill(_ s: ColorScheme, fresh: Double) -> Color {
        if self == .map { return hue.mixed(PlasmieHues.mapGround, 0.4, s) }
        return hue.mixed(PlasmieHues.mapGround, (s == .dark ? 0.35 : 0.15) * (1 - fresh), s)
    }

    /// Fresh accents glow softly; neutral notes don't (a grey glow reads as a smudge).
    var glowsWhenFresh: Bool { self == .decision || self == .gotcha || self == .pattern }

    /// The darker (light mode) / lighter (dark mode) rim that gives pale accents an edge.
    func rim(_ s: ColorScheme) -> Color {
        hue.mixed(PlasmieHues.mapInk, s == .dark ? 0.15 : 0.45, s)
    }
}

enum MapPalette {
    static func ground(_ s: ColorScheme) -> Color { PlasmieHues.mapGround.color(s) }
    /// Labels, veins, the dot grid.
    static func ink(_ s: ColorScheme) -> Color { PlasmieHues.mapInk.color(s) }
    /// A map's ring: full graphite around its lighter fill.
    static func ring(_ s: ColorScheme) -> Color { PlasmieHues.mapNote.color(s) }
    /// The one lit effect: vein glow and pulse halo.
    static func glow(_ s: ColorScheme) -> Color { PlasmieHues.sparkle.color(s) }
    /// A pulse's core: gold, deepened on the light ground so it shows.
    static func pulse(_ s: ColorScheme) -> Color {
        s == .dark ? PlasmieHues.sparkle.color(s) : PlasmieHues.gold.mixed(PlasmieHues.mapInk, 0.15, s)
    }
    static func matchRing(_ s: ColorScheme) -> Color {
        s == .dark ? PlasmieHues.sparkle.color(s) : PlasmieHues.gold.mixed(PlasmieHues.mapInk, 0.3, s)
    }
}
