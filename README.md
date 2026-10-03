# plasmie

A local pipeline that turns your work activity into a curated, searchable knowledge vault (an LLM-maintained wiki in the llm-wiki pattern, edited in Obsidian). Raw activity is captured hourly, digested on-device, and promoted nightly into flat, tagged wiki notes. Summarization and generation run on-device (Apple Foundation Model, or a local Gemma served on `127.0.0.1`); see [Privacy](#privacy--security) for the few network calls ingest makes.

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
 raw/inbox ◀─ plasmie-capture.sh        (Apple on-device model, Gemma fallback)

 nightly 02:30   promote.sh (local Gemma drafts) ─▶ dedupe.py (TF-IDF)
                 ─▶ promote-apply.py --auto ─▶ confident items filed FLAT into wiki/
                                               borderline ones held (*.hold.md) for review
                 ─▶ reindex.py (index.md, wiki/mocs/, dead-link check)

 hourly :17      plasmie-improve.py: retag, maps, archive resolved drafts, prune raw past
                 retention, close coverage gaps, related links, merge proposals
 daily 00:47     plasmie-snapshot.sh: git-commit the vault
```

The Gemma model is loaded on demand (~5 GB) only while a job runs, then freed; every model job is gated behind a thermal/load/RAM guard (`mlx-ctl.sh guard`) so it defers instead of fighting you for the machine.

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

1. **Preflight** — Homebrew, `python@3.12`, git, Obsidian, claude CLI, free disk.
2. **Vault location** — default `~/knowledge`, saved to `config.env` (refuses cloud-synced folders).
3. **Scaffold** — `scaffold-vault.sh` copies `vault-template/` (never into a non-empty dir).
4. **Secrets** — `SLACK_USER_TOKEN` into the login Keychain (`keychain.py set`).
5. **Python env** — `.venv` with `mlx-vlm` and `mlx-embeddings`.
6. **Models** — Gemma-4 E4B 4-bit (~4.9 GB) and `embeddinggemma` (see `models/README.md`; the latter is vestigial).
7. **Loops** — `launchd/install.sh` installs every agent in `launchd/`.
8. **App** — builds the menu-bar app into `/Applications`, optional launch-at-login.

The wizard does not install **qmd** or Node; `app-setup.sh` (run by the app on first launch) does, via `npm install -g @tobilu/qmd`, registers the `raw`/`wiki` collections, runs `qmd embed`, and performs the first-time crawl (see `docs/first-run-crawl.goal.md`). With the wizard, install qmd yourself. Starter vault only: `./scaffold-vault.sh [dir]`.

Agents, all templates in `launchd/` (the installer rewrites `__LOOP_DIR__`/`__HOME__`; `launchd/install.sh uninstall` removes them):

| Agent | Runs | When |
|-------|------|------|
| `com.plasmie.dev-ingest` | `run-ingest.sh` | hourly :07 |
| `com.plasmie.dev-summarize` | `summarize.sh` | hourly :15 |
| `com.plasmie.dev-improve` | `plasmie-improve.py` | hourly :17 |
| `com.plasmie.dev-promote` | `promote.sh` | nightly 02:30 |
| `com.plasmie.dev-snapshot` | `plasmie-snapshot.sh` | daily 00:47 |
| `com.plasmie.mlx-server` | `mlx_serve.py` | on demand, `127.0.0.1:8091` |

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
| `summarize.sh` | Condenses today's `raw/{slack,claude,outlook}` into a rolling `meta/digests/` note; skipped if input unchanged. |
| `promote.sh` | Nightly: drafts promotable knowledge (incl. `raw/inbox` content) with local Gemma, then dedupe + auto-apply. |
| `dedupe.py` | TF-IDF cosine against existing notes; sets `Action:` and `Near:` on each draft item. |
| `promote-apply.py` | Applies drafts; `--auto` files confident items flat into `wiki/`, holds borderline ones. Path-confined, scrubbed, idempotent, never deletes. |
| `reindex.py` | Regenerates `index.md` and `wiki/mocs/`, flags dead links (`--check` is read-only). |
| `plasmie-improve.py` | Hourly deterministic upkeep: tags, maps, archive, raw pruning, coverage gaps, related links, merge proposals, retirement of stale event notes. |
| `ask.py` | Q&A over `wiki/` with qmd retrieval + local Gemma; logs coverage gaps and usage. |
| `eval.py`, `backtest.py` | Retrieval eval (hit-rate/MRR across qmd modes); backtest of the auto-merge threshold. |
| `fm.py` | Apple Foundation Models wrapper (generate, tag, probe) with guard, timeout and audit. |
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
| `gen.sh`, `cc-local.sh`, `mlx_serve.py`, `mlx-ctl.sh` | Local Gemma: guarded one-shot generation, Claude Code pointed at it, Anthropic-compatible server with wire logging, up/down/guard control. |
| `install.sh`, `app-setup.sh`, `scaffold-vault.sh`, `launchd/install.sh` | Terminal wizard; app first-run backend setup; vault scaffold; agent installer. |
| `app/` | SwiftUI menu-bar app (`make-app.sh`, `make-dmg.sh`): status, Ask (⌃⌥⌘K), held-draft review, Settings → Connectors. |
| `test_*.py` | pytest suites (`fm`, `improve`, `ingest`, `pipeline`, `scrub`, `status`). |
| `docs/`, `models/`, `vault-template/` | Notes and baselines; weights (gitignored); new-vault scaffold. |

---

## Requirements

- macOS on Apple Silicon (the guard uses `pmset`/`memory_pressure`; MLX needs an M-series GPU). The Apple on-device model additionally needs macOS 26+ with Apple Intelligence; otherwise Gemma is used.
- Python 3.12 with `mlx-vlm` in `.venv/`; Node 22+ and `qmd` (`@tobilu/qmd`) for retrieval.
- Obsidian (to read the vault); [Claude Code](https://claude.com/claude-code) on `PATH` (drives local-Gemma jobs through `cc-local.sh`).
- Per connector, the credentials in the table above.

---

## Privacy & security

- **Network calls** (ingest only): Slack API (user token), GitHub via `gh`, Confluence via the Atlassian API, Microsoft Graph if Outlook is connected. Local git and session sources touch no network. A source switched Off makes no call. Model downloads (Hugging Face, qmd models) happen once at setup.
- **On-device models**: summarize, promote and ask run on the Apple Foundation Model or the local Gemma server (`127.0.0.1:8091`, only while a job runs). Interactive Claude sessions are unaffected. `gen.sh`, `fm.py` and `mlx_serve.py` log the exact prompt and response, so what crossed into the model is checkable.
- **Secret scrubber** (`scrub.py`): redacts GitHub/Slack/AWS/API tokens, bearer headers, connection-string passwords and PEM keys before anything is written; a label-gated entropy pass catches bare passwords after a credential word. The promote path also strips emails.
- **Untrusted model output**: `promote-apply.py` confines every draft path to the vault, scrubs bodies, refuses to overwrite and never deletes.
- **Owner-only files**: scripts set `umask 077`; logs are `0600`; runtime data, `.venv`, models and `config.env` are gitignored.
- **Vault stays on local disk.** launchd agents cannot read `~/Library/CloudStorage` (TCC). The OneDrive mirror was removed in commit `e070d75` after 528 failures; do not put `VAULT_DIR` in OneDrive/iCloud.
- **Credentials in the Keychain**, never in a file: written and read only through `/usr/bin/security`, so no ad-hoc app build or background job ever raises an access prompt (ADR 0021).

---

## Logs & retention

| Path | Contents | Kept |
|------|----------|------|
| `feed.log` | One line per ingest (`*-ERR` marks failures) | last 2000 lines |
| `logs/ingest-*.log` | Full per-run ingest detail | 14 days |
| `logs/audit-*.log` | summarize/promote/improve outcomes | 90 days |
| `logs/transcript-*.log` | Exact prompt+response for local-model calls | 30 days |
| `logs/wire-*.log` | Byte-exact server request+response | 30 days |
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
summarize.sh promote.sh dedupe.py promote-apply.py reindex.py plasmie-improve.py   vault pipeline
ask.py eval.py backtest.py fm.py scrub.py paths.py   retrieval, models, shared
plasmie-doctor.py plasmie-status.py plasmie-capture.sh plasmie-snapshot.sh   ops
github-backfill.py confluence-backfill.py msgraph.py   connectors
gen.sh cc-local.sh mlx_serve.py mlx-ctl.sh   local model
install.sh app-setup.sh scaffold-vault.sh launchd/   install
app/  vault-template/  models/  docs/  test_*.py
```
