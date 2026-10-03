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

## The notch becomes the front door (owner request, 2026-10-03)
- **The menu-bar icon is hidden while the notch is on**; turning the notch off brings it
  back. Reopening Plasmie (Finder, Spotlight, `open -a Plasmie`) shows the Plasmie window, so
  nothing becomes unreachable. The icon's visibility mirrors a `Model.notchOn` value set
  only on real changes: binding `MenuBarExtra(isInserted:)` straight to `@AppStorage`
  spun the main thread at 100% (the status item writes defaults, which re-render the app).
- **Island actions, few on purpose:** Ask · Ingest (or *Review N* when items are held) ·
  Vault · More. The stage name opens Trophies; right-click gives Ask / Open Plasmie / Quit.
- **The Plasmie window** holds everything else: the old menu panel on the left (status,
  Run / Open / Maintain, held items) beside Settings and connectors on the right.
- **Ask lives in the island**, not a spotlight: it grows to 560 × (notch + 84) for the
  question and to 560 × 470 once an answer streams in, with the same view and state
  throughout. The panel takes the keyboard only while Ask is open; Esc or ⌃⌥⌘K closes
  it and hands focus back. The floating spotlight remains only as a fallback when the
  island can't host it (notch off, or a full-screen Space hides the island).
