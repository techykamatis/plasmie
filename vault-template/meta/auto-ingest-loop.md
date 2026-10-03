---
type: reference
title: Auto-ingest loop
description: The launchd pipeline that ingests Slack, GitHub, git, Confluence, Claude/AgentCLI sessions into raw/, digests them hourly, promotes durable notes into the flat wiki nightly, and maintains the vault.
tags: [meta, automation]
timestamp: 2026-10-03T00:00:00Z
---

# Auto-ingest loop

A set of macOS LaunchAgents keeps this vault current with no Claude session open. They survive logout/reboot and coalesce missed runs on wake. Tooling lives **outside the vault** in `~/.plasmie/` (the vault is data only); schedules are in `launchd/*.plist`, installed by `launchd/install.sh`.

| Agent | Runs | Does |
|-------|------|------|
| `com.plasmie.dev-ingest` | hourly :07 | `run-ingest.sh` → `loop-ingest.py` appends scrubbed activity to `raw/<source>/YYYY-MM-DD.md`, one line to `log.md`; then `qmd update` + `qmd embed` so it's searchable |
| `com.plasmie.dev-summarize` | hourly :15 | `summarize.sh` condenses today's `raw/{slack,claude,outlook}` into 4-8 bullets → `meta/digests/YYYY-MM-DD.md` (Apple on-device model first, local Gemma fallback; skipped if the input is unchanged) |
| `com.plasmie.dev-improve` | hourly :17 | `plasmie-improve.py`: retag, regenerate `wiki/mocs/` + `index.md`, archive resolved drafts, prune raw past retention, close coverage gaps, add `## Related` links, propose duplicate merges, retire stale event notes |
| `com.plasmie.dev-promote` | nightly 02:30 | `promote.sh` (local Gemma drafts) → `dedupe.py` → `promote-apply.py --auto` → `reindex.py` |
| `com.plasmie.mlx-server` | on demand | Gemma server on `127.0.0.1:8091`, started/stopped by `gen.sh` via `mlx-ctl.sh` |
| `plasmie-snapshot.sh` | daily 00:47 | commits the vault to its own git repo (pushes only if a remote exists); agent `com.plasmie.dev-snapshot` |

## Sources

| Source | Lands in | Notes |
|--------|----------|-------|
| Slack | `raw/slack/` | user token; your sent + to-you messages via `search.messages` |
| Claude Code + AgentCLI sessions | `raw/claude/` | local `~/.claude/projects/**/*.jsonl` and the AgentCLI SQLite DB; no network |
| GitHub | `raw/github/` | `gh` CLI, orgs from `PLASMIE_GITHUB_ORGS` (default `fabrikam`); per-repo backfill mirror in `raw/github/<repo>/` |
| Local git | `raw/git/` | your own commits from clones under `PLASMIE_GIT_ROOTS` (default `~/code`); low-signal commits are dropped |
| Confluence | `raw/confluence/` | backfill mirror; needs `JIRA_*` credentials (run `confluence-backfill.py`) |
| Outlook | `raw/outlook/` | optional; needs a Microsoft 365 refresh token (tenant-admin approval may be required) |
| Manual | `raw/inbox/` | `plasmie-capture.sh`; the nightly promote reads inbox content |

Per-connector On/Off: `PLASMIE_DISABLED_SOURCES="github,confluence"` in `~/.plasmie/config.env` (or the app's Settings → Connectors). Off means no fetch, watermark still advances (re-enabling does not backfill), summarize/promote ignore its raw files, `plasmie-doctor.py` reports `enabled:false`. The env var overrides `config.env`.

## Promote: propose → dedupe → auto-apply → reindex

The model only *proposes*; deterministic Python does the rest, so a small local model suffices.

1. `promote.sh` feeds yesterday+today's `raw/{slack,claude,outlook}` and the `raw/inbox` contents (scrubbed) to local Gemma → `meta/promotion-drafts/<date>.md`.
2. `dedupe.py` tags each item with `Action:` (merge/create/move) and a `Near:` line via TF-IDF cosine against existing notes.
3. `promote-apply.py --auto`: confident merge (cosine >= 0.45) merges into the nearest note; new notes are created **flat in `wiki/`** (the draft's `Target:` becomes a tag, `Source:` is carried into the note); borderline merges and refusals are **held** in `<date>.hold.md`. Then `reindex.py`.
4. A notification reads `auto-promoted N · M held`.

**Held drafts must be reviewed.** They sit in `meta/promotion-drafts/` until resolved (a ✅ marker moves them to `archive/`). The menu-bar app shows pending drafts: Approve all, Review, or Dismiss; by hand: `promote-apply.py <draft> --apply`.

Safe by construction: paths confined to the vault, bodies scrubbed (emails too), `create` never overwrites, `merge` is idempotent (content-hash marker), nothing is deleted. Weak link is the 4B proposer, which mis-targets and restates known facts, hence the hold path. Adversarial suite: `test_pipeline.py`.

## Retention

- `raw/{slack,claude,outlook,github,git}/YYYY-MM-DD.md` pruned after `PLASMIE_RAW_RETENTION_DAYS` (14) by `plasmie-improve.py`; each prune is logged to `log.md`. Backfill mirrors (`raw/confluence/`, `raw/github/<repo>/`) are exempt.
- `log.md` and `meta/digests/` are never pruned. The vault's git history (daily snapshot) is the safety net for a prune.

## Operate it

- **Fire ingest now:** `launchctl kickstart -p gui/$(id -u)/com.plasmie.dev-ingest` (same for summarize/improve/promote).
- **Stop / start:** `launchctl bootout gui/$(id -u)/com.plasmie.dev-ingest` · `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.plasmie.dev-ingest.plist` (or `launchd/install.sh` to refresh all).
- **Look back N hours:** `.loop-state.json` holds per-source watermarks: `{"last_run": <epoch>, "sources": {"slack": <epoch>, "confluence": ..., "github": ..., "outlook": ..., "claude": ..., "git": ...}}`. A source that errors keeps its old watermark so the next run re-covers the gap. To re-read the last N hours for every source:
  `python3 -c "import json,time,os;t=time.time()-3600*N;p=os.path.expanduser('~/.plasmie/.loop-state.json');json.dump({'last_run':t,'sources':{s:t for s in ['slack','confluence','github','outlook','claude','git']}},open(p,'w'))"` then kickstart ingest. **Ingest appends, so re-reading duplicates already-captured blocks** — only look back over a window you know was missed. A bare legacy `{"last_run": ...}` also works (it seeds every source). Missing file = first run: last `PLASMIE_BOOTSTRAP_DAYS` (30) days.
- **Bounded backfill without touching the watermark:** `PLASMIE_SINCE=2026-10-01T09:00 PLASMIE_UNTIL=2026-10-01T18:00 ~/.plasmie/run-ingest.sh` (raw files are dated by the window end).
- **Health:** `tail ~/.plasmie/feed.log` (one line per ingest, `QMD-ERR`/`*-ERR` mark failures); `python3 ~/.plasmie/plasmie-doctor.py` for per-connector reachability and freshness.

## Logs

`~/.plasmie/feed.log` (last 2000 lines), `logs/ingest-*.log` (14 days), `logs/audit-*.log` (90 days; summarize, promote, improve), `logs/transcript-*.log` and `logs/wire-*.log` (exact prompts to the local model), `launchd.log` (launchd-level errors only).

## Safety

- `scrub.py` redacts tokens, keys, connection-string passwords and PEM keys → `«redacted»` before anything is written; the promote path also strips emails.
- Work-only: personal finance/family/health is skipped.
- Network calls: Slack (user token), GitHub (`gh`), Confluence (Atlassian API, when credentialed), Outlook/Graph (if connected). All summarization/generation is on-device.
- **TODO (security):** the worker sources `~/.claude/.env`, a plaintext file of real secrets. A keychain migration for just `SLACK_USER_TOKEN` was attempted and reverted; parked.
- The vault must stay on local disk: launchd agents cannot read `~/Library/CloudStorage` (TCC). Do not point `VAULT_DIR` at OneDrive/iCloud.

## Related
- [[README]] — vault conventions
- [[tags]] — tag rules
