# 0021 · The mascot lives in the notch

- **Status:** Experimental (a Settings toggle, on by default)
- **Area:** Design, architecture

## Context
A Mac with a notch has a natural home for a small companion: the 185 × 32 pt black notch
at the top of the built-in display. The menu-bar icon must stay available for anyone who
turns the notch off, and nothing may become unreachable.

## Decision
- **Window:** a borderless, non-activating panel at `.mainMenu + 1` (over the menu bar,
  under system alerts), behaviour `[.canJoinAllSpaces, .stationary, .ignoresCycle]` with no
  full-screen auxiliary, so it hides over full-screen apps. It never becomes key except
  while Ask is open. On screens without a notch it is a small pill at the top centre
  (96 × 24).
- **States:** resting (the mascot's eyes peek out **beside** the notch, on the left only, one
  46 pt ear, so the right side of the menu bar stays free), working (widens; the mascot
  shape-shifts on one side, one word on the other), hover (a compact island: the
  interactive mascot, stage and status, fun fact, actions), celebration (new-trophy banner).
  Sizes: resting 241 × 42, working 381 × 42, expanded 460 × 210, celebration 360 × 70.
- **No status dot.** A green dot by the notch reads as macOS's camera indicator, and the
  mascot's shape and pose already are the status (raised hand = review, puddle = failing,
  hourglass = busy, napping = quiet).
- **One fixed-size panel, one spring.** The panel is the union of all mode rects, so the
  window never resizes mid-animation. Hover is geometric: the pointer is polled at 30 Hz
  against the target rect, and clicks outside it pass through to whatever is underneath.
  The shape grows on one spring from its resting size, which already includes the notch, so
  it grows out of the black notch; radii derive from the drawn rect. Hover collapses 0.4 s
  after the pointer leaves, and re-entering cancels it. Motion uses the
  [0020](0020-motion-language.md) tokens.
- **The notch is the front door.** The menu-bar icon is hidden while the notch is on and
  comes back when it is off. Reopening the app (Finder, Spotlight, `open -a Plasmie`) shows
  the Plasmie window. The icon's visibility mirrors a `Model.notchOn` value set only on real
  changes: binding `MenuBarExtra(isInserted:)` straight to `@AppStorage` spins the main
  thread at 100%, because the status item writes defaults, which re-render the app.
- **Island actions, few on purpose:** Ask · Ingest (or *Review N* when items are held) ·
  Vault · More. The stage name opens Trophies; right-click gives Ask / Open (the Plasmie
  window) / Open map / Quit.
- **The Plasmie window** holds everything else: status, Run / Open / Maintain and held items
  on the left, Settings and connectors on the right.
- **Ask lives in the island:** it grows to 560 × (notch + 84) for the question and to
  560 × 470 once an answer streams in, with the same view and state throughout. The panel
  takes the keyboard only while Ask is open; Esc or ⌃⌥⌘K closes it and hands focus back.
  The floating Ask overlay is the fallback when the island can't host it (notch off, or a
  full-screen Space hides the island).
- **Toggle:** `plasmie.notch`, in Settings and the panel's Maintain group.

## Consequences
Turning the notch off brings back the menu-bar icon and the floating Ask overlay, so both
paths have to keep working.
