# 0006 · Generated text may reword, never re-specify

- **Status:** Accepted · 2026-10-03
- **Area:** Architecture (applies to fun facts and pattern naming)

## Context
Small on-device models paraphrase well but occasionally invent numbers, versions or
jokes. The owner asked Plasmie to phrase things in its own words.

## Decision
- Every number and identifier-like token (`256`, `v1.0.0-pilot-28`, `user_type`,
  `goose-only`) in generated text must appear in the source text; otherwise the output
  is rejected: fun facts fall back to the verbatim quote, pattern groups are skipped.
- Prompts carry few-shot examples and explicit "add nothing / no jokes" rules.
- The original wording is always kept (fun-fact tooltip; pattern drafts list their evidence).

## Known limit
The guard catches changed specifics, not small added flavour ("…to work right").
`plasmie-funfact.py --quote` restores verbatim mode.
