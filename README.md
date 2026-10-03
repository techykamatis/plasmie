# plasmie

A local pipeline that turns your work activity into a curated, searchable knowledge vault (an LLM-maintained wiki in the llm-wiki pattern, edited in Obsidian). Raw activity is captured hourly, digested on-device, and promoted nightly into flat, tagged wiki notes. Summarization, filing and answers run on-device on Apple's Foundation Model (Apple Intelligence), reached through the bundled `plasmie-fm` helper; see [Privacy](#privacy--security) for the few network calls ingest makes.

---

## The loop

```
 Slack ─────┐
 GitHub ────┤  hourly :07   ┌──────────────┐   raw/<source>/YYYY-MM-DD.md
 local git ─┼─────────────▶ │ loop-ingest  │ ─▶ (scrubbed, appended) + log.md
 Confluence ┤               └──────┬───────┘        │
 Outlook ───┤                      │ qmd update/embed (index raw + wiki)
 Claude/AGENTCLI┘                      ▼
 sessions            hourly :15   summarize ─▶ meta/digests/YYYY-MM-DD.md
 raw/inbox ◀─ plasmie-capture.sh        (digest.py: Apple on-device model, map-reduce if long)

 nightly 02:30   promote.sh ─▶ promote_plan.py (on-device map-reduce drafts) ─▶ dedupe.py (TF-IDF)
                 ─▶ promote-apply.py --auto ─▶ confident items filed FLAT into wiki/
                                               borderline ones held (*.hold.md) for review
                 ─▶ reindex.py (index.md, wiki/mocs/, dead-link check)

 hourly :17      plasmie-improve.py: retag, maps, archive resolved drafts, prune raw past
                 retention, close coverage gaps, related links, merge proposals
 daily 00:47     plasmie-snapshot.sh: git-commit the vault
```

Every model call goes through `fm.py` to `plasmie-fm`, a small Swift helper linked against the system FoundationModels framework (no Xcode, no download; [ADR 0021](docs/decisions/0021-apple-fm-only.md)). The on-device window is small (4096 tokens documented, 8192 on macOS 27; always read live), so promote and long digests **map-reduce**: chunk to the live budget, extract per chunk, then choose and merge. Background jobs are gated by a thermal/load/RAM guard (`fm.machine_busy`) so they defer instead of fighting you for the machine; interactive Ask skips it.

## Vault layout (at `VAULT_DIR`, default `~/knowledge`)

| Path | Contents |
|------|----------|
| `raw/` | Sources, one subdir each: `slack`, `claude` (Claude Code + AgentCLI sessions), `outlook`, `github` (dated dumps + per-repo backfill mirror), `git` (local commits), `confluence` (backfill mirror), `inbox` (manual drops), `journal` (legacy digests). Dated dumps pruned after 14 days. |
| `wiki/` | Durable notes, **flat**; `wiki/mocs/` generated per-tag maps; `wiki/attachments/` |
| `archive/`, `meta/` | Done/dead material; templates, promotion drafts, digests, `coverage-gaps.md`, `improvement-loop.md`, `usage.tsv` |
| `index.md`, `log.md` | Generated catalog; durable append-only audit |

The vault's own `CLAUDE.md` is the maintenance contract. Layout constants live in `paths.py`; the scaffold for new installs is `vault-template/`. Retrieval is **qmd** (hybrid; `ask.py` uses vector search) over collections `raw` and `wiki`, also exposed as an MCP server.

---

## Install

```bash
git clone git@github.com:example-user/plasmie.git ~/.plasmie
cd ~/.plasmie
./install.sh        # interactive wizard (or use the app: app-setup.sh)
```

The wizard has 8 idempotent, skippable steps:

1. **Preflight** — Homebrew, `python@3.12`, git, Obsidian, free disk.
2. **Vault location** — default `~/knowledge`, saved to `config.env` (refuses cloud-synced folders).
3. **Scaffold** — `scaffold-vault.sh` copies `vault-template/` (never into a non-empty dir).
4. **Secrets** — `SLACK_USER_TOKEN` into the login Keychain (`keychain.py set`).
5. **Python env** — `.venv` (the engine is stdlib-only; pytest for the tests).
6. **Apple Intelligence** — builds `plasmie-fm` (`app/build-fm.sh`) and checks the on-device model is on. Nothing to download.
7. **Loops** — `launchd/install.sh` installs every agent in `launchd/`.
8. **App** — builds the menu-bar app into `/Applications`, optional launch-at-login.

The app's first-run setup (`app-setup.sh`) installs Plasmie's own qmd with the Node that ships in the app (into `~/Library/Application Support/Plasmie/qmd`), registers the `raw`/`wiki` collections, runs `qmd embed`, and performs the first-time crawl (skipped for an existing vault, whose ingest watermarks are seeded instead). With the Terminal wizard, install qmd yourself. Starter vault only: `./scaffold-vault.sh [dir]`.

Background jobs belong to the app (ADR 0026): `Plasmie.app/Contents/Library/LaunchAgents`, registered with SMAppService, listed in Login Items, running the bundled engine:

| Agent | Runs | When |
|-------|------|------|
| `com.plasmie.ingest` | `run-ingest.sh` | hourly :07 |
| `com.plasmie.summarize` | `summarize.sh` | hourly :15 |
| `com.plasmie.improve` | `plasmie-improve.sh` → `plasmie-improve.py` | hourly :17 |
| `com.plasmie.promote` | `promote.sh` | nightly 02:30 |
| `com.plasmie.snapshot` | `plasmie-snapshot.sh` | daily 00:47 |

**Dev checkout only:** `launchd/install.sh` installs `com.plasmie.*` agents that run the checkout instead (`uninstall` removes them). Never run both sets: ingest appends, so two would double-capture (the app won't register while any `com.plasmie.*` agent exists).

`launchd/install.sh` also boots out agents the repo no longer ships (the retired `com.plasmie.mlx-server`).

---

## Connectors

| Connector | Source | Needs | Raw dir |
|-----------|--------|-------|---------|
| Slack | your sent/to-you messages | `SLACK_USER_TOKEN` (`xoxp-`, `search:read`, `users:read`) | `raw/slack` |
| GitHub | PRs, issues, comments | `gh` CLI signed in; optional `PLASMIE_GITHUB_ORGS` to narrow (blank = all your activity) | `raw/github` |
| Local git commits | your commits from local clones, low-signal ones dropped | `PLASMIE_GIT_ROOTS` (setup detects `~/code`, `~/Developer`, … when they hold repos); no network | `raw/git` |
| Confluence | pages you touched; page changes logged hourly, content via `confluence-backfill.py` | `JIRA_BASE_URL`; `JIRA_EMAIL` + `JIRA_API_TOKEN` (or `CONFLUENCE_*`) in the Keychain | `raw/confluence` |
| Outlook | mail + calendar via Microsoft Graph (`msgraph.py`) | `MS_REFRESH_TOKEN`; usually needs tenant-admin approval | `raw/outlook` |
| Claude Code sessions | `~/.claude/projects/**/*.jsonl` | nothing | `raw/claude` |
| AgentCLI sessions | AgentCLI SQLite DB (`PLASMIE_AGENTCLI_DB`) | nothing | `raw/claude` |

**Where settings live.** Credentials (`SLACK_USER_TOKEN`, `JIRA_API_TOKEN`, `CONFLUENCE_API_TOKEN`, `MS_REFRESH_TOKEN`, `JIRA_EMAIL`, `CONFLUENCE_EMAIL`) are generic passwords in the login Keychain, service `Plasmie`, account = the variable name; everything else (site URL, orgs, folders, switches) is in `config.env`. Python jobs load both with `paths.load_env()`, shell jobs call `plasmie_secrets` (plasmie-env.sh). An install from before this read `~/.claude/.env`; its Plasmie keys are copied out once (`keychain.py migrate`) and the file is never edited. See ADR 0021.

**Fresh installs start with every connector Off** except local sources whose folder exists (Claude Code sessions, AgentCLI, local git); see ADR 0022.

`plasmie-doctor.py [source]` prints per-connector reachability and data freshness as JSON (what the app's Settings "Test" button runs).

**On/Off switch.** Each connector has a toggle in the app (Settings → Connectors), stored as `PLASMIE_DISABLED_SOURCES="github,confluence"` (comma-separated source names: `slack github git confluence outlook claude agentcli`) in `config.env`; edit it by hand if you like. The env var `PLASMIE_DISABLED_SOURCES` overrides `config.env`. Off means: ingest skips the source with no network call; its watermark still advances, so turning it back On does **not** backfill the Off period; summarize/promote ignore its raw files; `plasmie-doctor.py` reports `enabled:false` without probing. `github-backfill.py` and `confluence-backfill.py` refuse to run for an Off source.

Each source has its own watermark in `.loop-state.json`; a source that errors holds its watermark so the next run re-covers the gap. A first run seeds `PLASMIE_BOOTSTRAP_DAYS` (30) days.

---

## Components

| File | Role |
|------|------|
| `loop-ingest.py` | Pulls every enabled source since its watermark, scrubs, appends to `raw/<source>/`, logs to `log.md`. |
| `ingest_window.py` | Watermark/pagination arithmetic and git-commit filter, shared with tests. |
| `run-ingest.sh` | launchd wrapper: loads `config.env` + Keychain credentials, runs ingest, then `qmd update` + `qmd embed`; full detail to a per-run log, one line to `feed.log`. |
| `summarize.sh`, `digest.py` | Condenses today's raw activity into a rolling `meta/digests/` note (one call if it fits the window, else map-reduce); skipped if input unchanged. |
| `promote.sh`, `promote_plan.py`, `promote_items.py` | Nightly: map-reduce drafts of promotable knowledge (incl. `raw/inbox` content) on-device, then dedupe + auto-apply. `promote.sh --dry-run DIR` drafts without touching the vault. |
| `dedupe.py` | TF-IDF cosine against existing notes; sets `Action:` and `Near:` on each draft item. |
| `promote-apply.py` | Applies drafts; `--auto` files confident items flat into `wiki/`, holds borderline ones. Path-confined, scrubbed, idempotent, never deletes. |
| `reindex.py` | Regenerates `index.md` and `wiki/mocs/`, flags dead links (`--check` is read-only). |
| `plasmie-improve.py` | Hourly deterministic upkeep: tags, maps, archive, raw pruning, coverage gaps, related links, merge proposals, retirement of stale event notes. |
| `ask.py` | Q&A over `wiki/` with qmd retrieval + the on-device model; logs coverage gaps and usage. |
| `eval.py`, `backtest.py` | Retrieval eval (hit-rate/MRR across qmd modes); backtest of the auto-merge threshold. |
| `fm.py`, `fm_sdk.py`, `mapreduce.py` | The one model chokepoint (generate, respond, tag, probe, guard, timeout, audit, transcript) over `plasmie-fm`; the Xcode-only Python SDK as an optional dev fallback; chunk/map/reduce to the live window. |
| `scrub.py` | The single secret/PII redactor, used by ingest, promote and capture. |
| `paths.py` | Vault layout, `config.env` reader, connector switch, retention constant. |
| `plasmie-doctor.py`, `plasmie-status.py` | Connector health JSON; menu-bar heartbeat JSON (reads `feed.log`, `.status`). |
| `plasmie-capture.sh` | `plasmie-capture.sh "thought"` (or stdin) writes a scrubbed note to `raw/inbox/`. |
| `plasmie-achievements.py` | Plasmie's evolution stage and 34 first-year trophies, earned from vault history (`--notify` hourly from `run-ingest.sh`). State: `.achievements.json`. |
| `plasmie-funfact.py` | The daily fun fact: nostalgic ("N months ago today") or resurfaced gotcha/decision/pattern, phrased by Plasmie on-device under a no-invented-specifics guard (`--next`, `--quote`). State: `.funfacts.json`. |
| `plasmie-patterns.py` | Weekly: drafts recurring patterns (3+ days in 4 weeks) as a pending promotion for review (`--dry`, `--force`). State: `.patterns.json`. |
| `plasmie-snapshot.sh` | Daily git commit of the vault; pushes only if a remote exists. |
| `github-backfill.py`, `confluence-backfill.py` | One-shot full-history mirrors into `raw/github/<org>-<repo>/` and `raw/confluence/<space>/`. |
| `msgraph.py` | Minimal Microsoft Graph client (device-code login) for Outlook. |
| `install.sh`, `app-setup.sh`, `scaffold-vault.sh`, `launchd/install.sh` | Terminal wizard; app first-run backend setup; vault scaffold; agent installer. |
| `app/` | SwiftUI menu-bar app (`make-app.sh`, `make-dmg.sh`): status, Ask (⌃⌥⌘K), held-draft review, Settings → Connectors. `app/fm/main.swift` is `plasmie-fm` (`build-fm.sh`): JSON in/out, `--check`, `--context-size`, `--probe`. |
| `test_*.py`, `conftest.py` | pytest suites; `fake_fm` is an executable fake of `plasmie-fm` so the subprocess path is tested for real. |
| `docs/`, `vault-template/` | Notes, baselines and decisions; new-vault scaffold. |

---

## Requirements

- macOS 26+ on Apple Silicon with **Apple Intelligence turned on** (System Settings › Apple Intelligence & Siri). Without it ingest, search and the vault still work; summaries, filing and answers don't (the app's setup check says so).
- Python 3.12 (bundled in the app; stdlib only); Node 22+ and `qmd` (`@tobilu/qmd`) for retrieval (~3.7 GB of search models, downloaded once).
- Obsidian (to read the vault). Building from source needs the macOS 26+ SDK (Xcode or Command Line Tools); running the app needs neither.
- Per connector, the credentials in the table above.

---

## Privacy & security

- **Network calls** (ingest only): Slack API (user token), GitHub via `gh`, Confluence via the Atlassian API, Microsoft Graph if Outlook is connected. Local git and session sources touch no network. A source switched Off makes no call. qmd's search models download once at setup; the answer model is Apple's and ships with macOS.
- **On-device model**: summarize, promote, Ask, fun facts and pattern naming run on Apple's on-device Foundation Model through `plasmie-fm` (a local process; no network). `fm.py` logs the exact instructions, prompt and response of every call, so what crossed into the model is checkable.
- **Secret scrubber** (`scrub.py`): redacts GitHub/Slack/AWS/API tokens, bearer headers, connection-string passwords and PEM keys before anything is written; a label-gated entropy pass catches bare passwords after a credential word. The promote path also strips emails.
- **Untrusted model output**: `promote-apply.py` confines every draft path to the vault, scrubs bodies, refuses to overwrite and never deletes.
- **Owner-only files**: scripts set `umask 077`; logs are `0600`; runtime data, `.venv` and `config.env` are gitignored.
- **Vault stays on local disk.** launchd agents cannot read `~/Library/CloudStorage` (TCC). The OneDrive mirror was removed in commit `e070d75` after 528 failures; do not put `VAULT_DIR` in OneDrive/iCloud.
- **Credentials in the Keychain**, never in a file: written and read only through `/usr/bin/security`, so no ad-hoc app build or background job ever raises an access prompt (ADR 0021).

---

## Logs & retention

| Path | Contents | Kept |
|------|----------|------|
| `feed.log` | One line per ingest (`*-ERR` marks failures) | last 2000 lines |
| `logs/ingest-*.log` | Full per-run ingest detail | 14 days |
| `logs/audit-*.log` | summarize/promote/improve outcomes | 90 days |
| `logs/transcript-*.log` | Exact instructions+prompt+response for every on-device model call | 30 days |
| `logs/*.log`, `launchd.log` | Per-agent stdout/stderr | not rotated |
| `raw/<source>/YYYY-MM-DD.md` (vault) | Dated activity dumps | `PLASMIE_RAW_RETENTION_DAYS` (14) |
| `meta/digests/`, `log.md` (vault) | Digests; durable audit | not pruned |

Raw pruning is done by `plasmie-improve.py` and logged to `log.md`. `raw/confluence/`, `raw/github/<repo>/` and `raw/journal/` are exempt.

```bash
tail -f feed.log          # one line per ingest
python3 plasmie-doctor.py      # per-connector health + freshness
```

---

## Design & decisions

- `PRODUCT.md`: who Plasmie is for and what it must never do.
- `DESIGN.md`: the visual system (palette, type, shapes, motion, components).
- `docs/decisions/`: one short record per design or architecture decision, with the
  alternatives that were rejected. Start at `docs/decisions/README.md`.
- Brand sheet: `app/brand/plasmie-brand.html` (built by `app/brand/build.py`).

## Repo layout

```
loop-ingest.py ingest_window.py run-ingest.sh   ingest
summarize.sh digest.py promote.sh promote_plan.py promote_items.py dedupe.py promote-apply.py reindex.py plasmie-improve.py   vault pipeline
ask.py eval.py backtest.py fm.py fm_sdk.py mapreduce.py scrub.py paths.py   retrieval, model, shared
plasmie-doctor.py plasmie-status.py plasmie-capture.sh plasmie-snapshot.sh   ops
github-backfill.py confluence-backfill.py msgraph.py   connectors
install.sh app-setup.sh scaffold-vault.sh launchd/   install
app/ (app/fm: plasmie-fm)  vault-template/  docs/  test_*.py
```
