# 0013 · App structure: files by surface, shared tokens, parallel-safe ownership

- **Status:** Accepted
- **Area:** Architecture (Swift app)

## Context
The app is plain SwiftUI built with `swiftc`: no Xcode project, no packages. It is worked on
by several agents at once, in separate git worktrees, and has to look consistent across
every surface.

## Decision
- **One file per surface or concern** in `app/Sources`: `Core` (model, helpers), `Panel`,
  `AskOverlay`, `AskSources`, `Setup`, `SetupSteps`, `Settings`, `Connectors`, `App`,
  `Theme`, `Motion`, `Notch`, `NotchTour`, `Trophies`, `FunFact`, `Origin`, the mascot's
  files (`Plasmie`, `PlasmieGeometry`, `PlasmieGlyph`, `PlasmieShapes`), the map's `Map*`
  files, and the system plumbing (`Brand`, `BackgroundJobs`, `LegacyJobs`, `LoginItem`,
  `Keychain`, `ICloud`, `RenameMigration`, `Reset`, `Quarantine`, `NoteReader`).
  `make-app.sh` compiles `Sources/*.swift`.
- **One type scale** (`Theme.swift`: system text styles, 11 pt floor) and **one palette**
  (`PlasmieHues`). No hard-coded colours outside it.
- **Disjoint file ownership**, so parallel worktrees merge by cherry-pick without conflicts.

## Consequences
A new surface gets its own file and takes its type and colour from `Theme.swift` and
`PlasmieHues`.
