---
name: Plasmie
description: A brain-pink blob that keeps your work day and shape-shifts to show what it's doing.
colors:
  plasmie-body: "#F49AB2"
  plasmie-body-dark: "#F7A8BE"
  plasmie-belly: "#FBC9D6"
  plasmie-ink: "#3A1430"
  plasmie-blush: "#E8668A"
  plasmie-off: "#C9B9C0"
  plasmie-off-dark: "#8E7F86"
  plasmie-sweat: "#6EC5F0"
  plasmie-sparkle: "#FFC94A"
  source-slack: "#7A3A82"
  source-github: "#3A3F58"
  source-git: "#F07A3E"
  source-confluence: "#3D7BE0"
  source-claude: "#D97757"
  source-outlook: "#5B8DEF"
  brand-ground: "#FDF1F4"
  brand-ground-dark: "#1E1218"
  icon-ground: "#FDEFF3"
typography:
  app-title:
    fontFamily: "SF Pro (system), .title3 semibold"
  app-heading:
    fontFamily: "SF Pro (system), .headline"
  app-body:
    fontFamily: "SF Pro (system), .body"
  app-label:
    fontFamily: "SF Pro (system), .callout"
  app-meta:
    fontFamily: "SF Pro (system), .subheadline — the 11pt floor"
  brand-display:
    fontFamily: "Baloo 2, Arial Rounded MT Bold, ui-rounded, sans-serif"
    fontWeight: 800
  brand-text:
    fontFamily: "Hanken Grotesk, ui-sans-serif, system-ui, sans-serif"
rounded:
  card: "8px"
  pill: "999px"
---

# Plasmie — design system

## Overview

Plasmie (formerly Plasmie, and before that Plasmie) is a personal, fully local macOS menu-bar app.
Its identity is one character: a soft **brain-pink blob** whose **silhouette is
the pipeline status**. The owner chose a blob "because it can take any shape or
form", so every state is a shape, not a label. The app chrome stays native
SwiftUI (system font, semantic colours); the brand lives in Plasmie, the app icon,
and the menu-bar glyph. Sources of truth:

- `app/brand/gen_shapes.py` → `app/brand/plasmie-shapes.json` + `app/Sources/PlasmieShapes.swift`
  (48 anchors per state, generated; never hand-edit the outputs)
- `app/Sources/Theme.swift` (`PlasmieHues`, type scale `klTitle…klMono`)
- `app/Sources/Plasmie*.swift` (view, geometry/faces, menu-bar glyph; type and file names keep the old name)
- `app/brand/plasmie-brand.template.html` (brand sheet; build injects the JSON)

## Colors

Restrained: one body colour, one ink, everything else semantic and rare.

- **Body `#F49AB2`** (dark `#F7A8BE`) is Plasmie. **Ink `#3A1430`** draws eyes,
  mouth and outline in both schemes (it sits on the pink body, not the window).
- **Belly `#FBC9D6`**: a soft sheen ellipse clipped to the body. **Blush
  `#E8668A`**: cheeks on happy states only.
- **Off `#C9B9C0`** greys the body when everything is switched off.
- **Sparkle `#FFC94A`** only for success, held "!", the Ask spark and hourglass
  sand. **Sweat `#6EC5F0`** only for the failing state.
- **Source dots** are the only multicolour moment (ingest): Slack aubergine,
  GitHub graphite, git orange, Confluence blue, Claude clay,
  Outlook blue.
- App UI keeps macOS semantic colours (`.primary/.secondary`, green/orange/red
  verdicts); no hard-coded hex outside `PlasmieHues`.

## Typography

App: SF Pro via `Theme.swift` text styles (`klTitle` 15 semibold, `klHeading`
13 semibold, `klBody` 13, `klLabel` 12, `klMeta` 11 — the floor, `klMono` 11).
Nothing the user reads goes below 11pt; `.klNote()` is the wrapping secondary
style. Brand sheet only: Baloo 2 ExtraBold display, Hanken Grotesk text.

## Layout

**Notch island** (the front door while the notch is on): resting = the notch plus one
46pt ear on the left holding Plasmie. Open states hug their content (measured, capped:
hover 460×≤260, Ask 560×≤470) so there is never dead black space; every open state uses
one content inset, `NotchMode.inset` = 30pt (12pt concave shoulder + 18pt air). Hover
island: Plasmie 68pt centred on the left; header (name · stage → trophies · status pill),
8pt, the fun fact with explicit ↻ / ↗ buttons on its kicker row (text is never a click
target), 14pt, chips Ask · Ingest|Review N · Vault · More.
**Plasmie window** (More / reopening the app): the status column on the native sidebar
material (320pt) beside Settings. Order: status hero → fun fact → attention (Obsidian
missing, held items) → Ask → Run · Open · Maintain → Log (live activity line, notes count,
last runs, captured output, full activity log) → Quit. Audit-type lines always sit at the
bottom. It focuses no text field on open.
Menu-bar panel (only when the notch is off) is the SHORT form of the same column, so it
fits any screen height: hero (72pt Plasmie) → fun fact → attention → Ask → Ingest now ·
Vault in Obsidian · Open Plasmie… (⌘,) → Quit. Older notes on the full menu follow: status header (Plasmie ~44pt + pill), Run / Open /
Maintain groups of ≤4, Quit footer. Settings is one resizable scrolling page
(min 520×560): Connectors (summary bar, then one card per connector), then
Vault. Ask overlay 560pt wide: Plasmie is the focal point in a leading column beside the
query field (88pt; springs down to 56pt once an answer arrives so the answer gets room),
with one status line under the field. Panel hero Plasmie is 104pt on a soft pink stage;
click says hi, rapid clicks annoy it, click-drag pets it.

## Shapes

Plasmie is a closed Catmull-Rom spline through **48 anchors** on a 100×100
canvas, clockwise from 12 o'clock. Shapes are built from SDF primitives
(circle, ellipse, rounded box, capsule, polygon) with smooth union, then
ray-sampled — never hand-placed points (that wobbles).

| State | Shape | Face / prop | Pipeline meaning |
|---|---|---|---|
| idle | mochi | dot eyes, smile, blush | resting, all flowing |
| ingest | bowl with a scooped mouth | "o" mouth, three source dots falling in | hourly capture |
| summarize | squat dumpling, three pleats | happy eyes, kneading squash | hourly digest |
| promote | rounded box | wink, note card drops in | nightly filing |
| ask | lightbulb with neck | eyes up, pulsing spark | answering ⌃⌥⌘K |
| held | mochi raising a hand | "o", bobbing "!" | drafts need review |
| error | puddle with two drips | worried, sweat drop, wobble | connector failing |
| busy | hourglass with caps | sleepy eyes in the top bulb, sand piling | Mac busy, jobs defer |
| quiet | flat mochi | closed eyes, drifting z's | no new data |
| off | small grey ball | closed eyes | all connectors off |
| success | soft five-point star | grin, sparkles | a job just finished |

Menu bar: a **template** silhouette (single colour, face knocked out) so it
follows light/dark menu bars; cached frames, swapped at 8 fps only while a job
runs. App icon: idle Plasmie on a flat `#FDEFF3` rounded square.

## Elevation & Depth

Flat. Depth comes only from the belly sheen inside Plasmie and native window
chrome. No drop shadows, glass, glows or gradients.

## Components

- **Motion tokens** (`Motion.swift`; no ad-hoc curves): `glide` =
  `timingCurve(0.16, 1, 0.3, 1, 0.42s)`, fast-to-slow, for things moving into
  place (panels, size changes, text swaps, collapsing); `pop` =
  `spring(response: 0.36, dampingFraction: 0.58)`, fast with a bounce on halt,
  for playful arrivals (Plasmie landing in a shape, celebrations, the "hi!"
  bubble, trophy tiles, the notch expanding); `jelly` = low-damping
  interpolating spring for secondary wobble. Reduce Motion maps all three to a
  0.15s ease. Pick by fit: glide when something settles, pop when it arrives.
- **PlasmieView(state:size:)**: a state change is an ~80ms anticipation squash
  (x1.05, y0.94), then a `pop` morph that overshoots the new silhouette, then a
  decaying jelly wobble (~0.6s). Bodies morph in polar form about the centroid
  so star-to-hourglass never folds through itself. The face is parametric (eye
  openness/curve, brow tilt, mouth width/curve/openness), so expressions morph,
  never crossfade; idle blinks every 3-6s. Props are pure functions of time with
  real physics (gravity falls, bounce on landing, buoyant hearts, burst arcs) and
  feed body squash on impact. Idle breathing +-1.8% over ~2.4s as a transform
  (the path is rebuilt only when the shape changes). The menu-bar glyph stays
  cached frames, no physics.
- **Connector card**: verdict pill (symbol + word, never colour alone), On/Off
  switch with an accessibility name, freshness bar labelled with the source's
  usual cadence.
- **Confirmations** share one copy pattern: "Verb object?", one sentence of
  consequence, a button repeating the verb, Cancel. Mechanism per surface:
  inline in the menu-bar panel, `confirmationDialog` in Settings cards,
  `NSAlert` for closing with unsaved changes.

## Plasmie's map

The vault as the network Plasmie grew (ADR 0029). Plasmie (from *plasmodium*) is the living,
pink heart; everything around it is calm and neutral, so the mascot reads at a glance.
`MapPalette.swift` holds every colour; `MapRender.swift` draws.

- **Pink is Plasmie's alone.** No body/belly/blush anywhere else on the map.
- **The ground is space** (`MapSpace.swift`): deep space in dark, a dusk sky in light; a
  nebula wash, then three depths of soft bokeh that follow the camera at 5 / 13 / 28 % of its
  movement (parallax). Among the pinpoint stars are other Plasmies far away: the real body
  silhouettes (PlasmieShapes anchors, the glyph's knocked-out face from 11 pt) at 6–24 pt,
  blurred, in lavender, periwinkle, peach, aqua, lilac, apricot and ice, never Plasmie's pink.
  A future, hinted: stars first, Plasmies on a second look. Every layer is pre-rendered once
  (seeded, the same sky every open) and only composited; a few pinpoints twinkle while the map
  is awake. Reduce Motion: no parallax, no twinkle. `mapGround` (`#E9E6F0` / `#0D0E1A`) is
  the sky's mean, what older notes fade toward.
- Notes are graphite (`mapNote` `#6B7285` / `#A3AABA`, >= 3:1 on the backdrop even at their
  palest, checked at the brightest bokeh in dark and the deepest lavender cloud in light); decisions sparkle gold, gotchas sweat blue, patterns leaf green,
  how-tos ink; maps (mocs) light graphite with a full-graphite ring. Older notes ease toward
  the ground (recency); fresh accents glow softly.
- **Minute blobs, big mascot.** At zoom 1: notes 2–5 pt radius (sqrt of links), maps 5.5–6.5 pt
  plus ring, Plasmie 72 pt (never under 56). Hover pops a note to ~4x (`pop`), lights its
  veins and neighbours, dims the rest (`glide`), and shows a native card by the cursor
  (title, type chip, date, links, two-line excerpt). Hit radius >= 10 pt.
- **Veins**, not hairlines: curved, tapered, translucent ink, 0.5–1 pt, thicker only on
  Plasmie's own veins to the maps. The one lit effect: a faint sparkle-gold glow on lit veins,
  and gold nutrient pulses walking downhill to Plasmie (a few at a time).
- **Labels** only on hover, or once zoomed in (maps from 1.4x, every note from 2x), 11 pt
  floor, greedy collision so they never stack.
- **Motion:** camera moves glide; hover grows pop; physics settles and then everything sleeps
  (~8 s after the last touch). Reduce Motion: no pulses or breathing, the layout arrives
  settled, 0.15 s eases.
- **The opening** (`MapIntro.swift`, after the hologram burst in Iron Man 2): Plasmie swells
  from the loading size to half the view with the web packed out of sight behind it, morphs
  into `tada` (its "hi" arm on both sides, raised from the lower sides: arms off the top of
  the head read as ears), then snaps to size while the web bursts out spinning, one soft
  overshoot, a sparkle-gold shockwave ring. ~2.2 s. Clicking Plasmie replays it; any other
  click or scroll skips it; Reduce Motion: none.
- **Native chrome:** toolbar = notes-list toggle, find (type to glide to a match, Return opens
  it), type chips (only kinds the vault has), zoom −/+/fit. The notes list is also the
  VoiceOver route.

## Do's and Don'ts

- **Do** let the shape carry the status; the face carries the mood; one prop at most.
- **Do** regenerate shapes from `gen_shapes.py`; app and brand page must read the same anchors.
- **Do** honour Reduce Motion: no loops, no physics, every token becomes a 0.15s ease.
- **Do** take curves from `Motion` (glide, pop, jelly); a bounce is welcome when it is `pop` or `jelly` and the thing is arriving.
- **Don't** show the mascot happy when the pipeline isn't (Plasmie's state is derived from real status).
- **Don't** add new hues for states; reuse sparkle/sweat/off.
- **Don't** invent per-view curves, or bounce things that are leaving, collapsing or resizing (those glide); don't animate when nothing is running in the menu bar.
- **Don't** hand-place anchors or edit `PlasmieShapes.swift` / `plasmie-shapes.json` directly.
- **Don't** put pink on the map anywhere but Plasmie, or let notes grow toward Plasmie's size.
