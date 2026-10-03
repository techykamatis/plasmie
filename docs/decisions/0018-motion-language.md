# 0018 · Motion language: glide and pop, with a little fun physics

- **Status:** Accepted · 2026-10-03 · built
- **Area:** Design, motion

## Context
Owner's request: "morphing from one form to another… either a fast-to-slow
acceleration or a fast and bounce-on-halt one depending on where it fits… a bit of
physics but in a fun way". This **replaces** the earlier "no bounce/elastic" rule.

## Decision
- **glide**: fast-to-slow exponential ease-out, for things moving into place (panels,
  size changes, text swaps, collapsing).
- **pop**: fast with a bounce on halt, for playful arrivals (Plasmie landing in a new
  shape, celebrations, the "hi!" bubble, the notch opening).
- **jelly**: low-damping secondary wobble.
- Morphs: anticipation squash → overshooting morph → decaying jelly wobble; very
  different shapes may pass through the round idle silhouette. Faces morph (eye
  openness/curve, mouth curve) instead of crossfading; idle blinks.
- Props have weight: dots fall with gravity and plop, the card lands with a bounce and
  the box squashes, hearts rise with buoyancy and sway, sparkles arc under gravity.
- Reduce Motion: every token becomes a short crossfade; loops stop.

## As built (`app/Sources/Motion.swift`)
- `glide` = `timingCurve(0.16, 1, 0.3, 1, 0.42 s)`; `pop` = `spring(response: 0.36,
  dampingFraction: 0.58)`; `jelly` = `interpolatingSpring(stiffness: 180, damping: 9)`.
- Body morphs interpolate in polar form around the centroid, so very different shapes
  (star ↔ hourglass) never fold through themselves; no intermediate keyframe needed.
- The notch opens by tucking into the exact hardware notch (~90 ms, invisible) and then
  popping out; it closes by gliding back into the notch before the resting ears return.
