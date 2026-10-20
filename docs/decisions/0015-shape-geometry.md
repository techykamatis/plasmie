# 0013 · Plasmie's geometry: SDF primitives sampled to 48 anchors, one generator

- **Status:** Accepted · 2026-10-03
- **Area:** Design, architecture

## Context
The first shapes were 12 hand-placed points through a Catmull-Rom curve; the owner
found them "wobbly". The brand page and the app also had to stay identical.

## Decision
- Each state is built from signed-distance primitives (circle, ellipse, rounded box,
  capsule, polygon) joined with smooth union / smooth cut, then **ray-sampled to 48
  anchors** clockwise from 12 o'clock on a 100×100 canvas. Dense, evenly placed samples
  keep outlines crisp, and equal anchor counts make any two states morphable.
- `app/brand/gen_shapes.py` is the single source: it writes `plasmie-shapes.json` (brand
  page) and `app/Sources/PlasmieShapes.swift` (app). Outputs are never hand-edited.
- Shapes revised on feedback: a true hourglass with caps and two triangular bulbs
  ("waiting should show more of an hourglass"), a deeper ingest mouth, a lightbulb with a neck.
- Reaction shapes (hi / annoyed / petted) live in the same generator.
