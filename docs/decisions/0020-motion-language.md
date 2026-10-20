# 0020 · Motion language: glide and pop, with a little fun physics

- **Status:** Accepted
- **Area:** Design, motion

## Context
The owner's brief: "morphing from one form to another… either a fast-to-slow acceleration
or a fast and bounce-on-halt one depending on where it fits… a bit of physics but in a fun
way".

## Decision
- **glide:** fast-to-slow exponential ease-out, for things moving into place (panels, size
  changes, text swaps, collapsing).
- **pop:** fast with a bounce on halt, for playful arrivals (the mascot landing in a new
  shape, celebrations, the "hi!" bubble, the notch opening).
- **jelly:** a low-damping secondary wobble.
- **Morphs:** anticipation squash → overshooting morph → decaying jelly wobble. Faces morph
  (eye openness and curve, mouth curve) rather than crossfading; idle blinks.
- **Props have weight:** dots fall with gravity and plop, the card lands with a bounce and
  the box squashes, hearts rise with buoyancy and sway, sparkles arc under gravity.
- **Reduce Motion:** every token becomes a short crossfade; loops stop.

## As built (`app/Sources/Motion.swift`)
- `glide` = `timingCurve(0.16, 1, 0.3, 1, 0.42 s)`; `pop` = `spring(response: 0.36,
  dampingFraction: 0.58)`; `jelly` = `interpolatingSpring(stiffness: 180, damping: 9)`.
- Body morphs interpolate in polar form around the centroid, so very different shapes
  (star ↔ hourglass) never fold through themselves and need no intermediate keyframe.
- The notch island ([0021](0021-notch.md)) is one shape on one spring, hung from the top
  edge: it pops down and out of the black notch (spring 0.36/0.72) and glides back (0.3 s).
  Corner radii are a function of the shape's current height, so they fit mid-animation.
