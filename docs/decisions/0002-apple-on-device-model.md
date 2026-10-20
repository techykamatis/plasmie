# 0002 · Apple's on-device model only, through a native helper; map-reduce for long input

- **Status:** Accepted
- **Area:** Architecture

## Context
Generation must stay on the Mac ([0001](0001-local-first-vault.md)), and every install has
to work on a stock Apple-silicon Mac without Xcode, Homebrew, Claude Code or a multi-gigabyte
model download. Apple's on-device Foundation Model starts instantly, but:

- its context window is small: 4096 tokens documented, 8192 read live on macOS 27;
- Apple's Python binding (`apple-fm-sdk`) only installs with a full Xcode, because it
  compiles Swift bindings;
- a day of raw activity is 30–100k tokens, so promote and the digest can't fit one call;
- asked to cite its sources, a small model invents citations.

## Decision
- **One backend.** Every generation goes through `fm.py` to `plasmie-fm`, a ~200-line Swift
  CLI (`app/fm/main.swift`) that links the system FoundationModels framework.
  `app/make-app.sh` builds it (`app/build-fm.sh`, swiftc, macOS 26+ SDK at build time only)
  into the bundle's `Contents/MacOS/`. It is weak-linked with a 13.0 deployment target, so
  on older macOS it answers `unsupportedOS` instead of dying in dyld.
- **Interface:** JSON on stdin (`prompt`, `instructions`, `max_tokens`, `greedy`,
  `temperature`, `use_case`, `guardrails`, `stream`, `op: count`) → JSON on stdout
  (`{text}` or `{error, reason}`; NDJSON `{delta}` lines when streaming), plus `--check`,
  `--context-size` and `--probe`. It counts tokens first (macOS 26.4+) and reports
  `over_budget` with numbers rather than an opaque failure. `fm.py` finds it via
  `$PLASMIE_FM_BIN`, the bundle, `app/build/`, then the app in `/Applications`. The Python
  SDK is an optional dev fallback (`fm_sdk.py`) for when no helper exists.
- **Prompts fit the live window.** Each prompt is budgeted to the `context_size` read at
  run time, question last.
- **Map-reduce, never truncation** (`mapreduce.py`). Input splits at line boundaries into
  chunks sized to the live window, each keeping its `===== source date =====` header. An
  over-budget chunk is halved and retried; `busy` or `unavailable` aborts the run.
  - Promote (`promote_plan.py`, `promote_items.py`): each chunk yields at most 3 candidates
    in the draft shape. The reduce step asks the model only to **pick numbers**;
    near-duplicates fold in code with their Sources joined. One short call per kept item
    rewrites its title and description.
  - The digest (`digest.py`) is one call when it fits, else chunk bullets → merged bullets.
- **Ask never asks the model to cite.** The Sources list comes from retrieval, and the
  prompt carries faithfulness rules. Multi-day recaps read the daily digests, not raw logs,
  and are capped at 320 tokens.
- **Rails on every stage.** Faithfulness ([0006](0006-faithfulness-guard.md)): a candidate
  whose numbers or identifiers aren't in its own chunk is dropped, and a rewrite that
  re-specifies is discarded. `Target:` is coerced to a kind word
  ([0005](0005-promote-kinds-and-confinement.md)), and a `Source:` must name the chunk it
  came from. Inbox drops are scrubbed before the model sees them. The draft format that
  `dedupe.py` and `promote-apply.py` parse, and promote-apply's confinement, are the same
  for every backend path.
- **Busy machine.** Background jobs check `fm.machine_busy` (pure Python: load, thermal,
  and free RAM under 15%) and skip a run when the Mac is busy. Interactive Ask and fun facts
  skip the check (`guard=False`). Summarize and promote use Apple's
  `permissiveContentTransformations` guardrails, since they transform the user's own text.
- **Stdlib-only engine.** Setup pip-installs nothing.
- **Setup.** `app-setup.sh --check` has a **required** "Apple Intelligence" row from the
  helper's `--check`. Its fix button opens Apple Intelligence & Siri settings;
  `unsupportedOS` gets a "macOS 26 or later" row with Software Update; a model still
  downloading only warns. Disk need is 6 GB (qmd's 3.7 GB search models). Setup writes
  `.setup-complete` at 100%, and `backendReady()` checks that marker (or existing ingest
  state), not a model folder.

## Alternatives rejected
- **A bundled open-weights model:** a ~5 GB download, a multi-second warm-up each session
  and a model server to keep running.
- **Apple's Python SDK as the main path:** it needs Xcode to install.
- **Truncating long input to fit:** it drops whole sources.

## Evidence (macOS 27, context 8192)
- The helper from the bundled backend, run by the bundled stdlib Python (no SDK): probe
  `available`, 8192 tokens; a one-sentence answer in 0.9 s; streaming; `over_budget`.
- Ask on a vault copy, 6 questions: 0 invented citations, answers in 2–4 s.
- Promote dry runs on real days (vault read-only, drafts to a temp dir): 136k chars → 13
  chunks, 34 candidates, 5 dropped by the faithfulness gate, 6 items, 103 s; 85k chars → 8
  chunks, 23 candidates, 4 items, 62 s; 132k chars → 12 chunks, 29 candidates, 7 dropped,
  4 items, 101 s. No chunk failed.
- A full day's digest too big for one call (57k chars): 3 map calls + 1 merge, 43 s, with
  every source read in full.

## Consequences
- Without Apple Intelligence there are no summaries, filing or answers; ingest, search and
  the vault still work. Setup blocks on it, and Ask, summarize and promote say so in words.
- Drafts are literal and extractive, and occasionally pick a status update over an insight.
  Failure modes the code repairs: kind-word headings ("## gotcha"), copies of the few-shot
  example, bold or inline item shapes. If quality needs to rise, the cheap lever is the pick
  prompt, not the model.
- A promote run is 15–25 short calls, 1–2 minutes a night.
