# plasmie

A privacy-first, fully-local pipeline that turns your day's activity into a
curated knowledge vault — **without sending any of it to the cloud.**

Every hour it ingests your recent Slack and Claude Code sessions into an
Obsidian journal, condenses each batch into a few bullets, and once a night
drafts durable notes worth promoting into your permanent vault. All
summarization runs on a **local Gemma model** served on `127.0.0.1` — the only
network call is reading your own Slack messages.

---

## The loop

```
            ┌──────────── hourly :07 ────────────┐
   Slack ──▶│  ingest   │  raw activity ──────────┼──▶ journal/YYYY-MM-DD.md
 sessions ─▶│ (Python)  │  (secret-scrubbed)      │      (Obsidian vault)
            └───────────┘                         │
            ┌──────────── hourly :15 ────────────┐│
            │ summarize │  newest block ──▶ local ││
            │  (Gemma)  │  Gemma ──▶ 4-8 bullets ─┼┘  appended to same note
            └───────────┘
            ┌──────────── nightly 02:30 ─────────┐
            │  promote  │  draft ──▶ dedupe ──▶   │  confident items auto-filed
            │  (Gemma)  │  auto-apply ──▶ reindex │  into PARA; unsure ones held
            └───────────┘
```

The local model is **loaded on demand** (~5 GB) only while a job runs, then
freed — and every job is gated behind a thermal/load/RAM **guard** so it never
fights you for the machine.

---

## Install

```bash
git clone git@github.com:example-user/plasmie.git ~/.plasmie
cd ~/.plasmie
./install.sh        # interactive wizard
```

The wizard walks 8 steps, each idempotent and skippable, so it's safe to re-run:

1. **Preflight** — Homebrew, `python@3.12`, git, Obsidian, claude CLI, free disk.
2. **Vault location** — where the vault lives (default `~/knowledge`); saved to `config.env`.
3. **Scaffold** — creates a fresh PARA vault from `vault-template/` (never overwrites an existing one).
4. **Secrets** — your `SLACK_USER_TOKEN` → `~/.claude/.env` (chmod 600).
5. **Python env** — a `.venv` with `mlx-vlm` (generation) and `mlx-embeddings` (search).
6. **Models** — downloads Gemma-4 E4B for generation (~4.9 GB, no account needed; resumable) and `embeddinggemma` for semantic search (~600 MB), both run in-process via MLX.
7. **Loops** — installs the launchd agents (ingest/summarize/promote).
8. **App** — builds the menu-bar app, installs to `/Applications`, optional launch-at-login.

Nothing is hard-coded to one path: the vault location lives in `config.env`
(scripts fall back to `~/knowledge` if it's absent), and the tooling runs from
wherever you cloned it. Just want a starter vault? `./scaffold-vault.sh [dir]`.

---

## Why local

The journal contains your Slack DMs, channel chatter, and the full text of your
Claude Code sessions. Sending that to a hosted LLM to summarize would defeat the
point. Instead:

- **Summarize / promote** run against a local Gemma-4 (MLX) via an
  Anthropic-compatible endpoint — Claude Code is pointed at `127.0.0.1:8080`
  for these jobs only; your interactive sessions keep using the real Claude.
- **Ingest** touches the network only to read *your own* Slack via your user
  token. A [secret scrubber](#privacy--security) strips credentials before
  anything is written to disk.
- Nothing leaves the Mac. Logs are owner-only (`0600`) and gitignored.

---

## Components

| File | Role |
|------|------|
| `loop-ingest.py` | Pulls recent Slack + updated Claude sessions, scrubs secrets, appends a timestamped digest to today's journal note. Tracks a high-water mark in `.loop-state.json`. |
| `run-ingest.sh` | launchd wrapper for the ingest: loads `.env`, splits full detail → per-run log, one summary line → `feed.log`. |
| `summarize.sh` | Condenses the newest raw ingest block into bullets via the local model. Idempotent per hour. |
| `promote.sh` | Nightly: drafts durable, promotable knowledge from recent journal entries into a review note. Never edits the vault directly. |
| `gen.sh` | The "don't disturb the user" wrapper around a local-model call: guard → load → run-with-hard-timeout → free. Logs the exact prompt+response. |
| `cc-local.sh` | Thin shim that points Claude Code at the local Gemma endpoint, isolated to that process. |
| `mlx_serve.py` | Serves Gemma-4 via mlx-vlm's Anthropic-compatible server, with byte-exact wire logging for audit. |
| `mlx-ctl.sh` | On-demand server control: `up` / `down` / `guard`. |
| `models/` | Local model weights (gitignored; see `models/README.md`). |

---

## Requirements

- macOS on Apple Silicon (the guard uses `pmset`/`memory_pressure`; MLX needs an
  M-series GPU).
- Python 3.12, with `mlx-vlm` installed in `.venv/`.
- [Claude Code](https://claude.com/claude-code) on `PATH`.
- A Slack **user** token (`xoxp-…`) with `search:read` and `users:read`.
- `mlx-embeddings` for semantic search (`embeddinggemma`, ~600 MB) — runs in-process, no extra server.

---

## Setup

**1. Secrets** — put your Slack token in `~/.claude/.env` (never committed):

```bash
SLACK_USER_TOKEN=xoxp-…
```

**2. Models** — download the 4-bit Gemma-4 (ungated, no login); the search model
auto-downloads on first ask (or pre-warm it as below):

```bash
hf download mlx-community/gemma-4-e4b-it-4bit --local-dir models/gemma-4-e4b
.venv/bin/python3 -c "from mlx_embeddings.utils import load; load('mlx-community/embeddinggemma-300m-bf16')"
```

**3. Python env**:

```bash
python3.12 -m venv .venv && .venv/bin/pip install mlx-vlm mlx-embeddings
```

**4. launchd agents** — four agents drive the loop. The templates live in
`launchd/` with `__LOOP_DIR__`/`__HOME__` placeholders; the installer rewrites
them for this machine and bootstraps each:

```bash
launchd/install.sh             # install / refresh all four
launchd/install.sh uninstall   # boot out + remove
```

| Agent | Runs | Cadence |
|-------|------|---------|
| `com.plasmie.dev-ingest` | `run-ingest.sh` | hourly at **:07** |
| `com.plasmie.dev-summarize` | `summarize.sh` | hourly at **:15** |
| `com.plasmie.dev-promote` | `promote.sh` | nightly at **02:30** |
| `com.plasmie.mlx-server` | `mlx_serve.py` | on-demand (started by `mlx-ctl.sh`) |

---

## Monitoring

```bash
tail -f feed.log         # one summary line per ingest
tail -f logs/audit-$(date +%F).log   # summarize/promote outcomes
```

`mlx-ctl.sh guard` prints `ok` (safe to run) or `busy` (machine hot/loaded —
jobs skip and retry next cycle).

---

## Privacy & security

- **Secret scrubber** (`loop-ingest.py`): regex passes redact GitHub/Slack/AWS/API
  tokens, bearer headers, connection-string passwords, and PEM private keys before
  anything is written. A label-gated entropy pass catches bare passwords trailing
  a credential word (e.g. `WiFi: … abc123XY`).
- **Owner-only files**: scripts `umask 077`; wire/transcript logs are `0600`.
- **On-demand RAM**: the ~5 GB model is loaded only while a job runs, then freed.
- **The guard**: defers on thermal warnings, 1-min load ≥ core count, or <30% free RAM.
- **gitignored**: all runtime data (`logs/`, `feed.log`, `.loop-state.json`), the
  `.venv`, and model weights. Only code + docs are tracked.
- **Audit trail**: `gen.sh` and `mlx_serve.py` log the exact context sent to the
  local model and what came back, so you can verify precisely what crossed in.

---

## Logs & retention

| Path | Contents | Kept |
|------|----------|------|
| `feed.log` | One summary line per ingest | last 2000 lines |
| `logs/ingest-*.log` | Full per-run ingest detail | 14 days |
| `logs/transcript-*.log` | Exact prompt+response to local model | 30 days |
| `logs/wire-*.log` | Byte-exact `/v1/messages` request+response | 30 days |
| `logs/audit-*.log` | summarize/promote outcomes | 90 days |

---

## Repo layout

```
loop-ingest.py     ingest (Slack + Claude sessions → journal)
run-ingest.sh      launchd wrapper for ingest
summarize.sh       hourly condense (local Gemma)
promote.sh         nightly promotion drafts (local Gemma)
gen.sh             guard + load + timeout + free wrapper
cc-local.sh        point Claude Code at the local endpoint
mlx_serve.py       MLX Gemma server + wire logging
mlx-ctl.sh         on-demand server control + guard
launchd/           agent templates + install.sh (path-rewriting installer)
models/            weights (gitignored) + setup notes
```
