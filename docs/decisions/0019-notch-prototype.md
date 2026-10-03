# 0019 · Plasmie in the notch (experimental prototype)

- **Status:** Experimental · 2026-10-03 · built and running
- **Area:** Design, architecture

## Context
The owner asked whether Plasmie could be a notch app. This Mac's built-in display has a
185 × 32 pt notch. The owner chose a toggleable prototype first, keeping the menu-bar icon.

## Decision
- A borderless, non-activating panel just above the menu bar, hidden over full-screen
  apps; on screens without a notch, a small pill at the top centre.
- States: resting (Plasmie's eyes peek below the notch, status dot), working (widens;
  Plasmie shape-shifts on one side, one word on the other), hover (compact island:
  interactive Plasmie, stage and status, fun fact, Ask / Ingest / Trophies), celebration
  (new-trophy banner).
- Toggle in Settings and the panel (`plasmie.notch`, on for the prototype). Motion uses
  the 0018 tokens.

## As built
- Window level `.mainMenu + 1` (over the menu bar, under system alerts); behaviour
  `[.canJoinAllSpaces, .stationary, .ignoresCycle]` with no full-screen auxiliary, so it
  hides over full-screen apps. The panel is sized to the visible shape, so clicks outside
  it reach whatever is underneath; it never becomes key.
- Sizes: resting 241×42 (notch 185 + 28 each side; 32 + 10 tall), working 381×42,
  expanded 460×210, celebration 360×70; no-notch fallback pill 96×24.
- Hover collapses 0.4 s after the pointer leaves; re-entering cancels it.

## Revisions (owner feedback, same day)
- Resting sits **beside** the notch on the left only (one 46 pt ear; the shape and panel
  shift left), so the right side of the menu bar stays free.
- **No status dot**: a green dot next to the notch reads as macOS's camera indicator, and
  Plasmie's own shape/pose already is the status (raised hand = review, puddle = failing,
  hourglass = busy, napping = quiet).
- ~~Opening tucks into the exact hardware notch, then pours down (height leads) and
  spreads out (width follows).~~ Superseded after screen recordings showed it glitching:
  the tuck was a separate `.notch` mode whose content vanished and whose radii snapped
  small while the shape was still large (a square-cornered black slab on every close), and
  the timer-chained phases flickered under fast hover. Now: **one fixed-size panel** (the
  union of all mode rects, so the window never resizes mid-animation), **geometric hover**
  (pointer polled at 30 Hz against the target rect; click-through outside it), and **one
  spring** on the shape from its resting size, which already includes the notch, so it
  still grows out of the black notch. Radii derive from the drawn rect.

## Open question
Whether the notch replaces the menu-bar icon is decided after the owner tries it.
