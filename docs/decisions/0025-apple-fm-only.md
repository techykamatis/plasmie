# 0025 · Apple Foundation Models only, through a native helper; map-reduce for long input

- **Status:** Accepted · 2026-10-04 · supersedes [0004](0004-on-device-models-first.md)
- **Area:** Architecture

## Context
The owner's direction: stop relying on the local Gemma; move everything to Apple's
on-device model. Plasmie is about to go to friends as an unsigned DMG, so every install
must work on a stock Apple-silicon Mac **without Xcode, Homebrew, Claude Code or a
5 GB model download**. Two things stood in the way:

- `apple-fm-sdk`, Apple's Python binding, only `pip install`s with a full Xcode (it
  compiles Swift bindings). Friends won't have Xcode.
- Promote fed a day to Gemma (via `gen.sh` → `cc-local.sh` → Claude Code → an mlx
  server); a day of raw activity is 30–100k tokens and the on-device window is 4096
  (documented) or 8192 (macOS 27, read live). It does not fit one call.

## Decision
- **One backend.** Every generation goes through `fm.py` to **`plasmie-fm`**, a ~200-line
  Swift CLI (`app/fm/main.swift`) that links the system FoundationModels framework.
  `app/make-app.sh` builds it (`app/build-fm.sh`, swiftc, macOS 26+ SDK at build time
  only) into `Plasmie.app/Contents/MacOS/plasmie-fm`. Weak-linked with a 13.0 deployment
  target, so on older macOS it answers `unsupportedOS` instead of dying in dyld.
  Interface: JSON on stdin (`prompt`, `instructions`, `max_tokens`, `greedy`,
  `temperature`, `use_case`, `guardrails`, `stream`, `op: count`) → JSON on stdout
  (`{text}` or `{error, reason}`; NDJSON `{delta}` lines when streaming), plus
  `--check`, `--context-size`, `--probe`. It counts tokens first (macOS 26.4+) and
  reports `over_budget` with numbers instead of an opaque failure. fm.py finds it via
  `$PLASMIE_FM_BIN`, the bundle, `app/build/`, then `/Applications/Plasmie.app`. The Python
  SDK survives only as an optional dev fallback (`fm_sdk.py`) when no helper exists.
- **Map-reduce, never truncation** (`mapreduce.py`). Input is split at line boundaries
  into chunks sized to the **live** window, each piece keeping its `===== source date
  =====` header; an over-budget chunk is halved and retried; `busy`/`unavailable` abort
  the run. Promote (`promote_plan.py`, `promote_items.py`): each chunk yields ≤3
  candidates in the draft shape; the reduce asks the model only to **pick numbers**,
  near-duplicates fold in code with their Sources joined; one short call per kept item
  rewrites its title + description. The digest (`digest.py`) is one call when it fits,
  else chunk bullets → merged bullets.
- **Rails kept.** Faithfulness (ADR 0006) on every stage: a candidate whose numbers or
  identifiers aren't in its own chunk is dropped; a rewrite that re-specifies is
  discarded. `Target:` is coerced to a kind word (ADR 0005); a `Source:` must name the
  chunk it came from. Inbox drops are scrubbed before the model; the draft format
  dedupe.py and promote-apply.py parse is unchanged; promote-apply's confinement is
  untouched. Background jobs keep the busy/thermal guard (now `fm.machine_busy`, pure
  Python; the RAM arm drops to 15% since nothing loads); interactive Ask and fun facts
  skip it. Apple's `permissiveContentTransformations` guardrails for summarize/promote,
  which transform the user's own text.
- **Removed:** `gen.sh`, `cc-local.sh`, `mlx-ctl.sh`, `mlx_serve.py`, the
  `com.plasmie.mlx-server` agent (and `launchd/install.sh` now boots it out of old
  installs), `models/`, the Gemma download and `mlx-vlm`/`huggingface_hub` installs,
  Ask's Gemma fallback and `PLASMIE_ASK_BACKEND`. The engine is stdlib-only: setup
  pip-installs nothing.
- **Setup.** `app-setup.sh --check` drops "Claude Code" and adds a **required** "Apple
  Intelligence" row from `plasmie-fm --check` (fix button opens Apple Intelligence & Siri
  settings; `unsupportedOS` gets a "macOS 26 or later" row with Software Update; a model
  still downloading only warns). Disk need 12 → 6 GB (qmd's 3.7 GB search models).
  Setup writes `.setup-complete` at 100%; `backendReady()` checks it (or, for installs
  that predate it, `.loop-state.json`), not a model folder.

## Evidence (2026-10-04, macOS 27.0.1, context 8192)
- `plasmie-fm` from the bundled backend with the bundled stdlib Python (no SDK): probe
  `available`, 8192 tokens; one-sentence answer in 0.9 s; streaming; `over_budget`.
- Promote dry runs on real days (vault read-only, drafts to a temp dir): 10-02+10-03,
  136 k chars → 13 chunks, 34 candidates, 5 dropped by the faithfulness gate, 6 items,
  103 s; 10-01, 85 k chars → 8 chunks, 23 candidates, 4 items, 62 s; 09-30, 132 k chars →
  12 chunks, 29 candidates, 7 dropped, 4 items, 101 s. No chunk failed on any day.
- A full day's digest that cannot fit one call (57 k chars): 3 map calls + 1 merge, 43 s.
  Gemma had seen at most 24 k chars of the same days (a fair-share tail); FM now reads
  every source in full.
- Same days vs Gemma's drafts (transcripts): both surfaced the audit/erasure-cap
  security finding and the eval-scorer fix area; Gemma's items read more synthesized
  ("Audit trail integrity gap…") but carried embellishments the log never said
  ("securing the deletion process", "the team successfully utilized"). FM's are more
  literal and occasionally pick a status update over an insight.

## Consequences
- No Apple Intelligence, no summaries, filing or answers (ingest, search and the vault
  still work). Setup blocks on it; Ask, summarize and promote say so in words.
- Drafts are more extractive than Gemma's. Measured failure modes the code repairs:
  kind-word headings ("## gotcha"), copies of the few-shot example, bold/inline item
  shapes. If quality needs to rise, the cheap lever is the pick prompt, not the model.
- A promote run is ~15–25 short calls instead of one long one (1–2 min a night).
- The owner's machine still holds `~/Library/Application Support/Plasmie/models/`
  (~4.9 GB of Gemma weights); nothing uses it, delete it by hand.
