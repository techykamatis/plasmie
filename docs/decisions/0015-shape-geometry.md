# 0015 · The mascot's geometry: SDF primitives sampled to 48 anchors, one generator

- **Status:** Accepted
- **Area:** Design, architecture

## Context
The mascot morphs between many shapes ([0014](0014-brand-plasmie.md)). A handful of
hand-placed points through a Catmull-Rom curve reads as wobbly, and two shapes with
different point counts can't morph cleanly. The brand page and the app must draw exactly
the same shapes.

## Decision
- Each state is built from signed-distance primitives (circle, ellipse, rounded box,
  capsule, polygon) joined with smooth union and smooth cut, then **ray-sampled to 48
  anchors** clockwise from 12 o'clock on a 100×100 canvas. Dense, evenly placed samples keep
  outlines crisp, and equal anchor counts make any two states morphable.
- `app/brand/gen_shapes.py` is the single source. It writes `plasmie-shapes.json` (brand
  page) and `app/Sources/PlasmieShapes.swift` (app). Outputs are never hand-edited.
- Shapes that carry meaning are drawn to read at a glance: a true hourglass with caps and
  two triangular bulbs for waiting, a deep mouth for ingest, a lightbulb with a neck for Ask.
- Reaction shapes (hi, annoyed, petted; [0017](0017-reactions.md)) live in the same
  generator.
