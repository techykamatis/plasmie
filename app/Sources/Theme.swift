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
