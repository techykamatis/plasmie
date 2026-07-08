# Goal: first-run bootstrap & initial multi-source crawl

A prompt/spec to hand a fresh Claude Code session (or run by hand) so a **new
install ends up with a seeded vault**, not an empty one. Self-contained — assumes
no prior context beyond the repo at `~/.plasmie` and vault at `~/knowledge`.

## Why this exists

`app-setup.sh` installs the runtime, models, qmd, vault scaffold, and launchd
loops — but it captures **no history**. The hourly ingest (`loop-ingest.py`) only
looks back **1 hour** on its first run (`last_run` defaults to `NOW - 3600`), so a
fresh vault sits nearly empty until enough hours pass. A first-time user opening
"Ask anything" gets "nothing in the wiki covers this yet." This goal fixes that
with a one-time historical crawl across every configured source, then hands off
to the normal incremental loop.

## End state (definition of done)

1. Every source the user has credentials for has been back-crawled into `raw/`
   over a bootstrap window (default **30 days**; Confluence = full contributor
   history). Sources without creds are **skipped cleanly, never fatal**.
2. An initial `summarize` + `promote` pass has run, so `wiki/` holds a starter set
   of promoted notes (not just raw dumps).
3. `reindex.py` has regenerated `index.md`, and `qmd embed` has indexed both
   collections — `qmd status` shows raw + wiki populated.
4. `ask.py "<something from this month>"` returns a real, cited answer.
5. The hourly/nightly launchd loops are running and will continue incrementally.
6. `log.md` records the bootstrap as an auditable event.

## Sources & how to crawl each (first time)

| Source | Credential (in `~/.claude/.env`) | First-time crawl |
|--------|----------------------------------|------------------|
| Slack | `SLACK_USER_TOKEN` (`xoxp-…`) | ingest with the bootstrap window — `search.messages` already queries by date from `last_run - 86400`, so a wide `last_run` pulls the window |
| Claude sessions | none (local `~/.claude/projects`) | ingest picks up every `*.jsonl` modified inside the window |
| Confluence | `JIRA_BASE_URL` / `JIRA_EMAIL` / `JIRA_API_TOKEN` (or `CONFLUENCE_*`) | run `confluence-backfill.py` — full mirror of `contributor = currentUser()` into `raw/confluence/<space>/` |
| Outlook | `MS_REFRESH_TOKEN` (shelved; usually absent) | if present, ingest pulls mail+calendar in the window; if absent, skip silently |

## Steps

0. **Preflight.** Source `~/.claude/.env` and `~/.plasmie/config.env`.
   Print which sources are configured (token present) vs skipped. Confirm qmd is
   on PATH, the vault exists, and the mlx model is present. Do NOT fail on a
   missing source — only fail if *zero* sources are available.

1. **Choose the bootstrap window.** `PLASMIE_BOOTSTRAP_DAYS` — **30** (default; quick,
   finishes in one setup session) or **90** (thorough; slower, and only as far
   back as Slack retention actually keeps). One-time seed; the incremental loop
   takes over afterward.

2. **Look-back is built in.** `loop-ingest.py` handles this itself: on a genuine
   first run (no `.loop-state.json`) it seeds `last_run = NOW - PLASMIE_BOOTSTRAP_DAYS`
   days, so the first ingest treats the whole window as "new" for Slack + Claude
   sessions + Outlook. No manual state-file poke needed. (Claude sessions use the
   same window rather than "all local" — a full-history dump would exceed what one
   promote pass can distill; the loop compounds older context forward.)

3. **Confluence full backfill** (independent of the state file):
   `python3 confluence-backfill.py ~/knowledge` — rebuilds `raw/confluence/`.

4. **Run the seeded ingest:** `./run-ingest.sh` (sources `.env`, sets `PLASMIE_VAULT`,
   writes per-source `raw/<source>/YYYY-MM-DD.md` + a `log.md` line).

5. **Condense + promote the seed:**
   - `./summarize.sh` → rolling `meta/digests/<today>.md`
   - `./promote.sh` → drafts durable notes, auto-files confident ones into `wiki/`
     (holds the uncertain for review). This is what fills `wiki/` on day one.

6. **Index for retrieval:**
   - `python3 reindex.py` → regenerate `index.md` catalog
   - `qmd collection add`/`context add` if not already registered, then
     `qmd embed` → vector-index raw + wiki.

7. **Audit the bootstrap:** append one `log.md` event —
   `## [ts] bootstrap · <n> sources crawled, <window> days, <k> notes promoted`.

8. **Verify** (see below), then confirm the loops are loaded
   (`launchctl print` the `com.plasmie.dev-*` agents).

## Constraints

- **Idempotent & resumable.** Re-running must not double-ingest (the state file
  advances) nor re-promote (promote-apply uses content-hash `<!-- promoted -->`
  markers). Confluence backfill safely rebuilds its tree each run.
- **Privacy.** All content is secret-scrubbed on ingest; everything stays local;
  logs are `0600`. Never send raw content to a cloud model.
- **Don't hammer the machine.** The bootstrap crawl is heavier than an hourly run
  (30 days of Slack, a full Confluence pull, one-time model downloads). Respect
  the thermal/load/RAM guard (`gen.sh`); if a summarize/promote step is deferred,
  that's fine — the loop retries. Bound Slack to the API's page limits.
- **Graceful degradation.** A source with no creds, or a transient API error,
  logs a note and is skipped — the bootstrap still completes for the rest.
- **raw is transient.** Remember `raw/` is pruned after `PLASMIE_RAW_RETENTION_DAYS`
  (14) — so the *value* of the bootstrap is what gets **promoted into `wiki/`**,
  not the raw dumps themselves. Make step 5 count.

## Success criteria (verify)

```bash
# raw seeded across sources
for s in slack claude outlook; do echo "$s: $(ls ~/knowledge/raw/$s/*.md 2>/dev/null | wc -l)"; done
ls ~/knowledge/raw/confluence | wc -l                 # confluence spaces mirrored
# wiki got starter notes
python3 ~/.plasmie/reindex.py --check ~/knowledge   # "<n> wiki notes"
# retrieval indexed
qmd status
# end-to-end answer works
python3 ~/.plasmie/ask.py "what did I work on this month?" ~/knowledge
# bootstrap audited
grep bootstrap ~/knowledge/log.md
```

Done when: ≥1 source crawled into `raw/`, `wiki/` note count grew, `qmd status`
shows both collections indexed, `ask.py` returns a cited answer, and the launchd
loops are running.

## Notes for the implementer

- **Implemented:** the first-run look-back lives in `loop-ingest.py`
  (`PLASMIE_BOOTSTRAP_DAYS`, default 30), and `app-setup.sh` runs the first-time crawl
  (confluence-backfill → seeded ingest → reindex → qmd embed) during setup, so a
  fresh install finishes with a seeded, indexed vault. `summarize`/`promote` are
  left to the loop (or the app's "Run promote now" button) so setup isn't gated on
  the guarded local model. Everything else composes existing scripts.
- Slack's `search.messages` is date-bounded and paginated (`count=100`); a 30-day
  window across many channels may need the loop to page rather than truncate at 25
  per channel — check coverage and widen if the seed looks thin.
- Consider surfacing bootstrap progress through the app's `PROGRESS:` channel (like
  `app-setup.sh`) so first-run crawl shows in the menu-bar UI, not just logs.
