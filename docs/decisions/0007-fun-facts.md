# 0007 · Fun facts: nostalgic or useful, chosen deterministically, phrased by Plasmie

- **Status:** Accepted · 2026-10-03
- **Area:** Product, architecture

## Decision
- Candidates come from the vault's own words: notes filed or digest lines written
  *N months ago today* (nostalgia), gotcha/decision/pattern/convention/concept/reference
  notes older than 14 days that were never retrieved by Ask (resurfacing), and the first
  note (milestone).
- Selection is deterministic per day (seeded), with no model; "Another" alternates
  nostalgic and useful and never repeats the last 60.
- Phrasing is on-device under 0006, cached per fact id. Patterns Plasmie found itself
  get the kicker "A pattern Plasmie noticed".

## Alternatives rejected
LLM-chosen facts (unpredictable, can't guarantee grounding) and verbatim-only quotes
(the owner preferred Plasmie's voice).
