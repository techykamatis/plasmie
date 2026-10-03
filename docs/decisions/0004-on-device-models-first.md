# 0004 · Apple Foundation Models first; local Gemma as fallback

- **Status:** Accepted · summarize 2026-09-30, Ask 2026-10-03
- **Area:** Architecture

## Context
Local Gemma (MLX, ~5 GB) takes a multi-second warm-up per session; the owner recorded
Ask sitting on "Asking Gemma…". Apple's on-device model is instant but has a small
context window (8,192 tokens live) and, in a September A/B, invented 2 citations to
Gemma's 0 on Ask.

## Decision
- `fm.generate()` first for summarize and Ask; Gemma only when it returns nothing
  (unavailable, over budget, timeout). `PLASMIE_ASK_BACKEND=gemma` forces the old path.
- **Design out invented citations:** Ask no longer asks the model to cite; the Sources
  list comes from retrieval. Faithfulness rules in the prompt.
- Prompts are trimmed to the live `context_size`, question last. Multi-day recaps read
  the daily digests instead of raw logs and are capped at 320 tokens.
- Interactive Ask skips the busy-machine guard (`guard=False`); background jobs keep it.
- Promote stays on Gemma (inputs too large for the on-device window).

## Evidence
6-question A/B on a vault copy: 0 invented citations, 2–4 s answers; Gemma never loaded.

## Consequences
Multi-day recaps are slower and weaker than Gemma's; acceptable because faithfulness held.
