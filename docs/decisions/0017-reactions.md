# 0017 · The mascot reacts: click says hi, rapid clicks annoy it, dragging pets it

- **Status:** Accepted
- **Area:** Design, interaction

## Context
A mascot people want to poke should respond to being poked, without ever hiding the real
pipeline state.

## Decision
- One `DragGesture(minimumDistance: 0)` tells a tap from a drag (a drag never counts as a
  tap). 1 tap → `hi` (waves, "hi!" bubble, ~1.6 s); 4 or more taps in 1.5 s → `annoyed`
  (puffs up, brows, anger mark, shake, ~2.2 s); drag → `petted` (squishes toward the stroke,
  hearts), lingering ~0.9 s.
- Reactions are short overlays on the real pipeline state; error and held always come back.
- Clicks on the mascot belong to the mascot: clicking it doesn't open Ask (Ask is on ⌃⌥⌘K
  and its own row).
- No reactions on the menu-bar glyph or the Ask field. Reduce Motion: pose changes, no
  shakes.
