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

## Amendment · 2026-10-03 · every fact names its subject
Owner feedback: "some fun facts are confusing" (e.g. a bare "Rendering time dropped from 32.2s to 5.7s").
- Each candidate gets a deterministic `context` (also a JSON field for a UI subtitle): for notes the
  project (a word prefixing >=3 filenames, or a mocs-backed tag that mostly appears in titles; derived,
  not listed) plus the title; for digest bullets a subject-bearing `Label:` (project/identifier/acronym),
  else the closest wiki note by `dedupe.py` tf-idf (>= 0.45; below ~0.40 matches were mostly wrong),
  else a same-day sibling bullet sharing >=3 words. No subject -> the bullet is not a candidate.
  A bare `identifier` in the text does not count ("docker:release confirmed success" stayed confusing).
- The prompt gets the fact plus a `Context:` block (title + the note's opening ~400 chars, understanding
  only) and must name the subject first. The 0006 guard checks fact + context. Output that opens with a
  bare verb / unresolved "it/this/the team", or never names the subject, is rejected: up to 3 candidates
  are tried, then the verbatim quote prefixed with its subject ("Orbit · ...") is shown.
- `--quote` prefixes the subject only when the quote lacks it. Cache keys carry VERSION (2) so older
  context-less phrasings are never reused.
