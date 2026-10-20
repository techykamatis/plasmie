# 0006 · Generated text may reword, never re-specify

- **Status:** Accepted
- **Area:** Architecture (promote, Ask, fun facts, pattern naming)

## Context
Small on-device models paraphrase well but now and then invent numbers, versions or jokes.
The owner wants the mascot to phrase things in its own words, without getting the facts
wrong.

## Decision
- Every number and identifier-like token (`256`, `v1.0.0-pilot-28`, `user_type`,
  `goose-only`) in generated text must appear in the source text. Otherwise the output is
  rejected: fun facts fall back to the verbatim quote, pattern groups are skipped, promote
  candidates are dropped.
- Prompts carry few-shot examples and explicit "add nothing / no jokes" rules.
- The original wording is always kept (the fun-fact tooltip; pattern drafts list their
  evidence; Ask shows its Sources).

## Known limit
The guard catches changed specifics, not small added flavour ("…to work right").
`plasmie-funfact.py --quote` gives the verbatim quote.
