import SwiftUI

// One type scale for the whole app. Built on macOS text styles (not fixed point
// sizes) so text follows the system's size setting, and floored at 11pt: nothing
// the user must read goes below `.klMeta`.
//
//   klTitle    15 semibold  window / overlay titles
//   klHeading  13 semibold  card + row names
//   klBody     13           primary text, answers
//   klLabel    12           buttons, field labels, summary lines
//   klMeta     11           captions, detail, hints (the floor)
//   klMono     11 mono      paths, logs, captured output
extension Font {
    static let klTitle = Font.title3.weight(.semibold)
    static let klHeading = Font.headline
    static let klBody = Font.body
    static let klLabel = Font.callout
    static let klMeta = Font.subheadline
    static let klMono = Font.system(.subheadline, design: .monospaced)
}

extension View {
    /// Secondary explanatory text that wraps instead of truncating — the chain that
    /// was hand-repeated ~11 times (`.font(10.5).secondary.fixedSize(...)`).
    func klNote() -> some View {
        font(.klMeta).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
    }
}

// MARK: - Plasmie palette

/// A colour with a light and a dark value (hex). `color(_:)` takes the scheme explicitly
/// (Canvas and ImageRenderer don't reliably resolve dynamic colours); `adaptive` follows
/// the system appearance for ordinary views.
struct PlasmieHue {
    let light: UInt32
    let dark: UInt32
    init(_ light: UInt32, dark: UInt32? = nil) { self.light = light; self.dark = dark ?? light }

    func rgb(_ s: ColorScheme) -> (r: Double, g: Double, b: Double) {
        let h = s == .dark ? dark : light
        return (Double((h >> 16) & 0xFF) / 255, Double((h >> 8) & 0xFF) / 255, Double(h & 0xFF) / 255)
    }
    func color(_ s: ColorScheme) -> Color { let c = rgb(s); return Color(red: c.r, green: c.g, blue: c.b) }
    /// Linear blend towards `other` (0 = self, 1 = other).
    func mixed(_ other: PlasmieHue, _ t: Double, _ s: ColorScheme) -> Color {
        let a = rgb(s), b = other.rgb(s)
        return Color(red: a.r + (b.r - a.r) * t, green: a.g + (b.g - a.g) * t, blue: a.b + (b.b - a.b) * t)
    }
    var adaptive: Color {
        func ns(_ h: UInt32) -> NSColor {
            NSColor(srgbRed: CGFloat((h >> 16) & 0xFF) / 255, green: CGFloat((h >> 8) & 0xFF) / 255,
                    blue: CGFloat(h & 0xFF) / 255, alpha: 1)
        }
        let l = ns(light), d = ns(dark)
        return Color(nsColor: NSColor(name: nil) { ap in
            ap.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? d : l
        })
    }
}

enum PlasmieHues {
    static let body = PlasmieHue(0xF49AB2, dark: 0xF7A8BE)
    static let ink = PlasmieHue(0x3A1430)             // same ink on the body in both schemes
    static let blush = PlasmieHue(0xE8668A)
    static let belly = PlasmieHue(0xFBC9D6)
    static let off = PlasmieHue(0xC9B9C0, dark: 0x8E7F86)
    static let sweat = PlasmieHue(0x6EC5F0)
    static let sparkle = PlasmieHue(0xFFC94A)
    /// Drifting z's sit on the window background, not the body: darker in light mode.
    static let dream = PlasmieHue(0xC2527A, dark: 0xF7A8BE)
    static let slack = PlasmieHue(0x7A3A82)
    static let github = PlasmieHue(0x3A3F58)
    static let git = PlasmieHue(0xF07A3E)
    static let confluence = PlasmieHue(0x3D7BE0)
    static let claude = PlasmieHue(0xD97757)
    static let agentcli = PlasmieHue(0x2BB3A0)
    static let outlook = PlasmieHue(0x5B8DEF)
    static let eggshell = PlasmieHue(0xFFF7EC)
    /// Plasmie's map (DESIGN.md › Plasmie's map): pink is Plasmie's alone, so the map around
    /// it is neutral. Ground, the ordinary note (>= 3:1 on the ground at its palest), and ink
    /// for labels, how-tos and veins. Accents reuse sparkle, sweat and leaf.
    static let mapGround = PlasmieHue(0xF4F4F2, dark: 0x17171A)
    static let mapNote = PlasmieHue(0x6B7285, dark: 0xA3AABA)
    static let mapInk = PlasmieHue(0x2A2E3A, dark: 0xDADDE4)
    static let leaf = PlasmieHue(0x6CC18E)
    static let bronze = PlasmieHue(0xC98A5B)
    static let silver = PlasmieHue(0xA7B1C2)
    static let gold = PlasmieHue(0xF2B83B)
}

extension Color {
    static let plasmieBody = PlasmieHues.body.adaptive
    static let plasmieInk = PlasmieHues.ink.adaptive
    static let plasmieBlush = PlasmieHues.blush.adaptive
    static let plasmieBelly = PlasmieHues.belly.adaptive
    static let plasmieOff = PlasmieHues.off.adaptive
    static let plasmieSweat = PlasmieHues.sweat.adaptive
    static let plasmieSparkle = PlasmieHues.sparkle.adaptive
    static let sourceSlack = PlasmieHues.slack.adaptive
    static let sourceGithub = PlasmieHues.github.adaptive
    static let sourceGit = PlasmieHues.git.adaptive
    static let sourceConfluence = PlasmieHues.confluence.adaptive
    static let sourceClaude = PlasmieHues.claude.adaptive
    static let sourceAgentcli = PlasmieHues.agentcli.adaptive
    static let sourceOutlook = PlasmieHues.outlook.adaptive
}
