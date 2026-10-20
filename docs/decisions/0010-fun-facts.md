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

## Amendment · 2026-10-04 · conversational voice, no bare quotes
Owner feedback: facts still read as citations ("In <full title>, ...", or the raw quote), rigid and not fun.
- Measured on 19 real candidates (after: 0 bare, 0 openers, 5 framed on the per-candidate path; 1 framed in 20 real picks): 18 opened "In/For <subject>," and 1 fell back to the bare quote.
- The prompt now talks *to* the reader ("you"/"your"), one opener per fact picked by id from a kind-specific
  list (throwback: "Remember this one?", "Funny how..."; nudge: "Little reminder:", "Turns out...", "Heads up:").
  "In/For <subject>," openers are banned; the subject is worked in as a short noun phrase.
- Guard additions (the numbers/identifiers check stays): no capitalised name absent from fact+context, at most
  one long word with no stem in the source, no copy of the quote with a lead glued on, no "your last attempt"
  style leakage. A rejected first try gets one corrective retry (sampling is greedy, so only a changed prompt
  changes the answer), then the next of up to 4 candidates is tried.
- The fallback is no longer a bare quote: the verbatim quote in a deterministic frame by kind/type
  ("Throwback from your notes on Orbit: ...", "Little reminder from your notes on Helm: ..."); a title over
  36 chars is dropped from the frame ("Throwback from your notes: ...").
- Cache VERSION is 3 (cache keys `v3:<id>`); `--quote` still shows the verbatim quote, subject-prefixed.
- Known limit: a 3B on-device model still occasionally pads a sentence ("so that's the rule"); the guard
  blocks invented specifics, not every flourish.
