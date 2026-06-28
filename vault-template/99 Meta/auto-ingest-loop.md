---
type: reference
title: Auto-ingest loop
description: The hourly background loop that logs Slack + Claude sessions to the journal and auto-promotes durable knowledge into the vault.
tags: [meta, automation]
timestamp: 2026-06-22T00:00:00Z
---

# Auto-ingest loop

A background loop keeps this vault current without manual capture. Set up 2026-06-22. It has **two independent halves** that run on separate schedules:

## 1. Ingest — always-on (launchd, no Claude needed)
A macOS **LaunchAgent** (`com.plasmie.dev-ingest`) fires hourly at :07 whether or not a Claude session — or even Terminal — is open. It survives logout/reboot (loaded at login) and coalesces a missed run on wake. It runs `~/.plasmie/loop-ingest.py`, which pulls, since the last high-water mark:
- recent **Slack** (personal user token, `search.messages`: your sent + to-you messages — `users.conversations` is scope-blocked, `search:read` works),
- newly created / recently updated **Claude Code sessions** (`~/.claude/projects/**/*.jsonl` by mtime),

then appends a timestamped section to `02 Areas/journal/<date>.md` and advances the mark. Fully deterministic — no model, so it can run headless.

## 2. Promote — fully local, automated (propose → dedupe → auto-apply → reindex)
The model only *proposes*; deterministic Python dedupes, applies, and indexes — so a small local model is enough and tool-use reliability is a non-issue. Runs nightly, no clicks.

**2a — propose + dedupe (launchd, local Gemma):** `com.plasmie.dev-promote` runs `promote.sh` daily at 02:30 — feeds recent journal + the `00 Inbox` listing to Gemma → `99 Meta/promotion-drafts/<date>.md`, then `dedupe.py` tags each item with a suggested `Action:` via **TF-IDF cosine** (stdlib, no deps) against all concept/people/project notes, plus a `Near:` line of top matches + scores.

**2b — auto-apply (launchd, no human):** `promote-apply.py --auto` applies the confident items and **holds the uncertain**:
- confident merge (cosine ≥ 0.45) → merged into the nearest note
- new note → created, target **normalized to `03 Resources/concepts/`** (the model's folder guesses are unreliable)
- inbox file → moved (default `03 Resources/clippings/`)
- borderline merge (0.30–0.45) → **held** in `<date>.hold.md`

Then `reindex.py` recounts concepts, fixes `index.md`, parks unlinked notes under `## Unfiled`, reports dead links. A notification says `auto-promoted N · M held`.

**2c — held review (you, only if something's held):** the menu-bar app shows held items — **Approve all** (apply as suggested + clear), **Review** (open in Obsidian to edit/skip), or **Dismiss**. Most nights nothing is held.

Safe by construction: paths confined to the vault, bodies scrubbed (incl. emails), `create` never overwrites, `merge` is idempotent (content-hash marker), nothing is ever deleted.

> ⚠️ History: 2b was once a *session-only* cron (`e78c8d15`) that expired silently, leaving drafts un-actioned and `00 Inbox` undrained. Auto-apply replaced it — if notes stop appearing in PARA, check the menu-bar app's activity line / `feed.log`.

> **Upgrade path (dedupe):** TF-IDF catches lexical dups (shared identifiers/proper nouns) — proven on the real vault (Xet-CDN 0.41, ElastiCache 0.49). If it starts missing *semantic* dups (same idea, different words), swap `dedupe.py::nearest()` for a local embedding model; nothing else changes.

## Safety
- **Secret scrubber** in the script redacts gh/AWS/Slack tokens, `sk-`/Bearer keys, connection-string passwords, and private keys → `«redacted»` before anything is written. Promotion step also never writes secrets/PII.
- **Promote path is hardened against the untrusted local model** (battle-tested): `promote-apply.py` confines every draft path to the vault root (rejects `../`, absolute paths, symlink escapes), scrubs secrets **and emails** from written bodies via [[scrub.py]], refuses to overwrite/delete, and merges idempotently (content-hash marker). Adversarial suite: `python3 ~/.plasmie/test_pipeline.py` (runs on a `cp -r` vault copy; 6/6). Known weak link is the **proposer**: the 4B mis-targets the PARA folder/granularity (~40%) and restates already-captured facts — which is why auto-apply normalizes new notes into `concepts/` and **holds** borderline merges for review rather than trusting the model blindly.
- **Work-only** (laptop): personal finance/family/health is skipped.
- Promotes only durable, reusable items — one-off debugging and chatter stay in the journal.
- **TODO (security):** the worker sources `~/.claude/.env` — a plaintext pile of real secrets (AWS MFA, DB passwords, GH PAT, Jira, Datadog, Sonar…). A keychain migration scoped to just `SLACK_USER_TOKEN` was attempted and reverted (zsh `${!k}` mismatch wrote 0 bytes); parked. The scrubber protects the *vault*, but the source `.env` stays plaintext for now.

## Moving parts
Tooling lives **outside the vault** (`~/.plasmie/`) — the vault holds only markdown knowledge, never scripts or state.
- Worker: `~/.plasmie/loop-ingest.py` (stdlib only; needs `SLACK_USER_TOKEN`, `SLACK_MY_USER_ID` from `~/.claude/.env`).
- Wrapper: `~/.plasmie/run-ingest.sh` (sources env, runs the worker via homebrew python3.12).
- State / high-water mark: `~/.plasmie/.loop-state.json` (`{last_run}` epoch).
- Logs (two views of each hourly run):
  - `~/.plasmie/logs/ingest-<YYYYMMDD-HHMMSS>.log` — **full detail** per run: window, per-channel Slack counts, per-project session counts, journal path. Pruned after 14 days. Use to audit a specific hour.
  - `~/.plasmie/feed.log` — **one summary line per run** (`<ts> | exit <rc> | slack N convos / M msgs · sessions K files`), rolling, capped 2000 lines. `tail -f ~/.plasmie/feed.log` to follow live (don't `tail -f` a per-run file — each run is a new filename, so it'd freeze).
  - `~/.plasmie/launchd.log` — launchd-level errors only (before the wrapper runs).
- LaunchAgents: `com.plasmie.dev-ingest` (hourly ingest), `com.plasmie.dev-summarize` (hourly Gemma bullets), `com.plasmie.dev-promote` (daily 02:30 → draft). Plists + `launchd/install.sh` under `~/.plasmie/launchd/`.
- Promote pipeline (step 2, all in `~/.plasmie/`, stdlib-only):
  - `promote.sh` — proposer (local Gemma) → draft; then calls `dedupe.py`.
  - `dedupe.py` — TF-IDF dedupe; enriches the draft with `Action:`/`Merge-into:`/`Near:`. (`--selfcheck`)
  - `promote-apply.py` — `--auto` (nightly: apply confident, hold uncertain, normalize targets) or `<draft> --apply` (apply a reviewed/held draft); vault-path containment + secret/email scrub + idempotent merge; auto-runs reindex. (`--selfcheck`)
  - `reindex.py` — recounts concepts, fixes index counts, flags orphans/dead links. (`--check`, `--selfcheck`)
  - `scrub.py` — the single secret/PII redactor, shared by ingest + promote (`redact(s, emails=)`; promote passes `emails=True`). (`--selfcheck` via `python3 scrub.py`)
  - `test_pipeline.py` — adversarial battle-test (path escape, no-data-loss, malformed input, idempotency, scrub, reindex) on a `cp -r` vault copy.
- Menu-bar app: `~/.plasmie/app/` — native SwiftUI `MenuBarExtra` cockpit (live activity heartbeat via `plasmie-status.py` + `.status`, held-review, in-process actions). Build: `app/make-app.sh` → `app/make-dmg.sh`.
- Output: digests land at `02 Areas/journal/<date>.md`; promoted notes land in People / Projects / Concepts.

## Operate it
- **Ingest fire-now:** `launchctl kickstart -p gui/$(id -u)/com.plasmie.dev-ingest`
- **Look back N hours:** `python3 -c "import json,time;json.dump({'last_run':time.time()-3600*N},open('$HOME/.plasmie/.loop-state.json','w'))"` then kickstart.
- **Stop ingest:** `launchctl bootout gui/$(id -u)/com.plasmie.dev-ingest`  ·  **(re)start:** `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.plasmie.dev-ingest.plist`
- **Stop promote:** `CronDelete e78c8d15` (or just close Claude — it's session-only).
- **Promote after being away:** open a Claude session; the cron's next :12 fire (or re-run `/loop`) catches up on the journal backlog. Promotion only happens with a session open — the ingest never stops.

## Related
- [[README]] — vault conventions
