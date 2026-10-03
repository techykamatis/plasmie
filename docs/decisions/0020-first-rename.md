# 0020 · Rename: Plasmie (app and mascot)

- **Status:** Superseded by 0027 (Plasmie) · 2026-10-03 · supersedes the name in 0011 and 0012
- **Area:** Design, architecture

## Decision
The app and the mascot are both **Plasmie**: "Plasmie", squished into one soft word,
the way the blob squishes into any shape. "Plasmie" was the working name while the
character was designed. Chosen by the owner ("it's basically Plasmie"), who also
chose one name for both rather than an app/mascot split (Duolingo/Duo style).

## Consequences
- Bundle `Plasmie.app`, executable `Plasmie`, login item re-pointed; bundle identifier
  unchanged so macOS permissions carry over. Swift types, files (`Plasmie*.swift`,
  `PlasmieShapes.swift`), brand files and UserDefaults keys (`plasmie.*`) renamed; the notch
  preference and the celebrated-trophy set re-seed once (silently).
- Pattern notes saved as "Plasmie noticed" still count for trophies and fun facts.
- Earlier records keep the name they were written with.
