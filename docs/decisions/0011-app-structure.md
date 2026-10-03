# 0011 · App structure: files by surface, shared tokens, parallel-safe ownership

- **Status:** Accepted · 2026-10-03
- **Area:** Architecture (Swift app)

## Decision
- The 1,524-line `Plasmie.swift` split by surface: Core (model, helpers), Panel,
  AskOverlay, Setup, Settings, Connectors, App, Theme, plus Plasmie*, Trophies, FunFact,
  Motion and Notch. `make-app.sh` compiles `Sources/*.swift`.
- One type scale (`Theme.swift`: system text styles, 11 pt floor) and one palette
  (`PlasmieHues`); no hard-coded colours outside it.
- Disjoint file ownership lets several agents work in parallel git worktrees and merge
  by cherry-pick without conflicts.
- Renamed to **Plasmie**: bundle `Plasmie.app`, executable `Plasmie`, login item re-pointed;
  bundle identifier kept so macOS permissions carry over.
