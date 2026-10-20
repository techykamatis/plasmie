# 0015 · Plasmie reacts: click says hi, rapid clicks annoy it, dragging pets it

- **Status:** Accepted · 2026-10-03
- **Area:** Design, interaction

## Decision
- One `DragGesture(minimumDistance: 0)` disambiguates tap vs drag (a drag never counts
  as a tap). 1 tap → `hi` (waves, "hi!" bubble, ~1.6 s); ≥4 taps in 1.5 s → `annoyed`
  (puffs up, brows, anger mark, shake, ~2.2 s); drag → `petted` (squishes toward the
  stroke, hearts), lingers ~0.9 s.
- Reactions are transient overlays on the real pipeline state; error/held always come back.
- Clicks belong to Plasmie: the panel hero no longer opens Ask (Ask stays on ⌃⌥⌘K and its row).
- Not on the menu-bar glyph or the Ask field. Reduce Motion: pose changes, no shakes.
