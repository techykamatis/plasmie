# Plasmie

Plasmie is a private work memory for macOS. It captures what you work on (Slack, GitHub,
local git commits, Confluence, Outlook, coding sessions) into a local Markdown vault,
files the durable knowledge into tagged notes every night, and answers questions about
it. Every model call runs on-device through Apple Intelligence; your notes never leave
the Mac unless you turn on the optional iCloud mirror.

The product is a menu-bar and notch app (SwiftUI) over a stdlib-only Python engine. The
app ships everything it runs, including Python, Node and the search engine, so a user
installs one DMG and nothing else.

- **Product scope and non-goals:** [`PRODUCT.md`](PRODUCT.md)
- **Visual system:** [`DESIGN.md`](DESIGN.md)
- **Why things are the way they are:** [`docs/decisions/`](docs/decisions/README.md)
- **End-user guide:** [`docs/QUICKSTART.md`](docs/QUICKSTART.md) and [`docs/PRIVACY.md`](docs/PRIVACY.md), shipped inside the app

---

## Requirements

| | |
|---|---|
| Hardware | Apple silicon (arm64). Plasmie never runs an Intel tool, see [Apple silicon](#apple-silicon-native-tools-only) |
| OS | macOS 26+ with **Apple Intelligence on**. Without it capture, search and the vault still work; summaries, filing and answers do not |
| Disk / network | About 6 GB free, and internet once at setup for the search models (about 3.7 GB) |
| Optional | Command Line Tools (vault history via git; setup offers Apple's installer). Obsidian is **not** required: Plasmie reads and edits the vault itself |
| Building from source | macOS 26+ SDK (Xcode or Command Line Tools) for `plasmie-fm`; Homebrew `python@3.12` for the dev venv |

---

## Install

**Users:** open `Plasmie.dmg`, drag Plasmie to Applications, open it, then follow
[Quickstart](docs/QUICKSTART.md). The build is ad-hoc signed, so the first launch needs
**System Settings › Privacy & Security › Open Anyway** once.

**Developers:**

```bash
git clone https://github.com/techykamatis/plasmie.git && cd plasmie
./install.sh                 # dev wizard: prerequisites, vault, Keychain, .venv, jobs, app
app/make-app.sh              # build app/build/Plasmie.app (downloads pinned Python + Node once)
app/make-release.sh          # quality gates, then app/build/Plasmie-<VERSION>.dmg + .sha256
```

`install.sh` is the dev path. It runs the engine from the checkout and installs `com.plasmie.*`
launchd agents. The shipped app instead registers its own `com.plasmie.*` jobs, which run the
engine bundled inside the app. **Never run both sets**: ingest appends, so two sets would
capture everything twice. The app refuses to register its jobs while any `com.plasmie.*` agent
is loaded (`launchd/install.sh uninstall` removes them).

### What first-run setup does

The app drives [`app-setup.sh`](app-setup.sh). It is idempotent and resumable, and
`Run setup again…` re-runs it safely.

1. **Prerequisite check.** Apple silicon, Apple Intelligence, disk, network, the bundled
   search engine. Recommended items: Command Line Tools and Obsidian (optional).
2. **Python runtime.** Copies the bundled Python 3.12 to `~/Library/Application Support/Plasmie/venv`.
   It is replaced if it is missing, broken, or a different version from the one the app ships.
3. **Native tools.** Resolves the arm64 `git` and `gh` (see [Apple silicon](#apple-silicon-native-tools-only))
   and records them in `config.env` as `PLASMIE_GIT_BIN` and `PLASMIE_GH_BIN`. With no native git it opens
   Apple's Command Line Tools installer.
4. **Vault.**
   - Cloud-synced folders are refused.
   - A restore point is taken.
   - An existing Plasmie vault is adopted untouched.
   - Any other folder only gains the missing pieces from `vault-template/`; nothing there is overwritten.
5. **Search engine.** Installs qmd, pinned to `@tobilu/qmd@2.5.3`, using the bundled Node.
   It is reinstalled if it is missing, the wrong version, or fails to load under that Node.
6. **Search collections.** Points `raw`, `wiki` and `vault` at the chosen vault, repointing
   any that were left elsewhere *in place*, so hand-written contexts and ignores survive.
   Then it downloads the models and embeds.
7. **Suggested links.** [`related.py`](related.py) finds each note's text neighbours across the
   vault. That takes a few seconds, and nothing is written to a note. Most vaults people bring
   are mostly unlinked (one measured 75%), and this gives the map structure from the first open.
8. **First crawl** (no prior state only). GitHub and Confluence history, plus 30 days of
   sessions and Slack (`PLASMIE_BOOTSTRAP_DAYS`).
9. **Catch-up ingest on every run, then promote in the background.** An existing vault or a
   re-run gets today's activity filed immediately instead of waiting for the nightly job.

---

## How it works

```
 Slack ─────┐
 GitHub ────┤  hourly :07   ┌─────────────┐   raw/<source>/YYYY-MM-DD.md  (scrubbed, appended)
 local git ─┼─────────────▶ │ loop-ingest │ ─▶ log.md, feed.log
 Confluence ┤               └──────┬──────┘
 Outlook ───┤                      └─▶ qmd update + embed
 sessions ──┘
 raw/inbox ◀── plasmie-capture.sh "a thought"

 hourly :15    summarize.sh ─▶ digest.py ─▶ meta/digests/YYYY-MM-DD.md
 hourly :17    plasmie-improve.py: retag, maps, archive, prune raw, coverage gaps, related links
 nightly 02:30 promote.sh ─▶ promote_plan.py (on-device drafts) ─▶ dedupe.py (TF-IDF)
               ─▶ promote-apply.py --auto: confident items filed into wiki/,
                  borderline ones held (*.hold.md) for review in the app
               ─▶ reindex.py: index.md, wiki/mocs/, dead-link check
 daily 00:47   plasmie-snapshot.sh: git-commit the vault (push if a remote exists)
```

**The model.** Every model call goes through [`fm.py`](fm.py) to `plasmie-fm`, a small Swift
helper over the system FoundationModels framework ([ADR 0025](docs/decisions/0025-apple-fm-only.md)).
Nothing is downloaded and there is no network call. The on-device context window is small
and is always read live, so promote and long digests **map-reduce**
([`mapreduce.py`](mapreduce.py)): chunk to the budget, extract, merge. Background calls
defer when the Mac is hot, loaded or short on memory (`fm.machine_busy`). Interactive Ask
doesn't defer.

**Time limits.** Each job runs under [`plasmie-job.sh`](plasmie-job.sh). It gets a hard limit (ingest 50 min,
promote 120 min) and runs in its own process group, so a job stuck on the network or the
model is stopped instead of hanging.

**Search and Ask.** Retrieval is [qmd](https://www.npmjs.com/package/@tobilu/qmd), vector
search with a BM25 fallback, over three collections:

| Collection | Path | Used by |
|---|---|---|
| `wiki` | `<vault>/wiki` | Ask; `plasmie-improve.py` (closing coverage gaps) |
| `vault` | `<vault>` minus `raw/`, `wiki/`, `meta/` | Ask: your own notes, in whatever folders you keep |
| `raw` | `<vault>/raw` | Recaps of a time window; never an answer source for open questions |

[`ask.py`](ask.py) answers only from the retrieved notes, under rules that forbid upgrading a
status or inventing specifics ([ADR 0006](docs/decisions/0006-faithfulness-guard.md)). The
Sources list comes from retrieval, never from model output. Weak matches are logged to
`meta/coverage-gaps.md` so coverage can grow.

---

## The app

| Surface | What it does |
|---|---|
| Notch / menu bar | Status as Plasmie's shape, a daily fun fact, quick actions |
| Ask (⌃⌥⌘K, anywhere) | Streamed on-device answer with clickable sources |
| Map | The vault as a graph (all notes except `raw/` and `meta/`), in your folders as they are, with `[[wikilinks]]` and Markdown links as edges ([`plasmie-graph.py`](plasmie-graph.py)). Suggested links are drawn faint and dashed |
| Reader | Opens any note beside the map, see below |
| Settings | Connectors with Test, vault, iCloud mirror, diagnostics, re-run setup |
| Trophies | Evolution stage and first-year trophies earned from vault history |

**Reader and editor** ([`NoteReader.swift`](app/Sources/NoteReader.swift)). Notes opened
anywhere in the app render natively in the map window.
- **Rendering:** frontmatter as chips, headings, lists and task lists, quotes and callouts,
  code, tables, local images, and inline formatting.
- **Links:** `[[wikilinks]]` resolve by file name the way Obsidian does; relative Markdown links
  resolve from the note's folder. Back and forward are ⌘[ and ⌘].
- **Editing:** **Edit** (⌘E) switches to Markdown, and **Save** (⌘S) writes atomically.
  Save refuses if the file changed on disk since it was opened, so a background job's write
  is never silently lost.
- **Read-only:** `raw/`, the bundled docs, and any note too large to show in full.
- **Related notes** under each note list its suggested neighbours.

**Suggested links** ([`related.py`](related.py)). Each note's nearest neighbours by TF-IDF
over its title and description (or opening text), across the whole vault, minus `raw/` and
`meta/`. The floor is 0.25 and there are at most 4 per note. They are cached in `related.json`,
keyed by every note's mtime and size, and computed, never written. **Settings › Vault ›
Add Related Links to My Notes** is the opt-in that writes them into the user's own notes, as
the same regenerable `<!-- related:start -->` block plasmie-improve keeps in `wiki/`. It takes a
restore point first, refreshes hourly, and can be removed in one click. `wiki/` and
`archive/` are left to plasmie-improve, so the two never write the same file.

Render checks without the full app: `Plasmie.app/Contents/MacOS/Plasmie --map [--read <file>]`.

---

## Connectors

All connectors are **off on a fresh install** except local sources whose folder exists
([ADR 0024](docs/decisions/0024-opt-in-connectors.md)).

| Connector | Captures | Needs | Raw dir |
|---|---|---|---|
| Slack | messages you sent and received | `SLACK_USER_TOKEN` (`xoxp-`, `search:read`, `users:read`) | `raw/slack` |
| GitHub | PRs and issues you opened or commented on | `GITHUB_TOKEN`, a fine-grained token, read-only Issues, Pull requests, Metadata. Falls back to a signed-in native `gh`. `PLASMIE_GITHUB_ORGS` narrows it (blank = all your activity) | `raw/github` |
| Local git | your own commits from local clones, one-liners and chores filtered out | `PLASMIE_GIT_ROOTS` (setup detects `~/code`, `~/Developer`, …); no network | `raw/git` |
| Confluence | pages you created or edited | `JIRA_BASE_URL`, plus `JIRA_EMAIL` and `JIRA_API_TOKEN` (or `CONFLUENCE_*`) | `raw/confluence` |
| Outlook | mail and calendar via Microsoft Graph | `MS_REFRESH_TOKEN` (often needs tenant-admin approval) | `raw/outlook` |
| Claude Code / AgentCLI | local session logs | nothing | `raw/claude` |

**Settings and secrets.** Secrets are generic passwords in the login Keychain: service
`Plasmie`, account = the variable name. They are only ever accessed through `/usr/bin/security`,
so no build or background job raises an access prompt
([ADR 0021](docs/decisions/0021-secrets-in-keychain.md)). Everything else (URLs, orgs,
folders, switches) lives in `config.env`. Python loads both with `paths.load_env()`; shell
jobs call `plasmie_secrets` from `plasmie-env.sh`.

**Off means off** ([ADR 0002](docs/decisions/0002-connector-switches.md)). A connector switched
off (`PLASMIE_DISABLED_SOURCES`) makes no network call, and summarize and promote ignore its raw
files. Its watermark still advances, so switching it back on does not backfill the off
period. Each source keeps its own watermark in `.loop-state.json`. A failing source holds
its watermark, so the next run re-covers the gap.

[`plasmie-doctor.py [source]`](plasmie-doctor.py) prints per-connector reachability and freshness as
JSON. It is what **Test** in Settings runs.

---

## Where things live

| Path | Contents |
|---|---|
| `<vault>/raw/<source>/` | Dated captures, pruned after `PLASMIE_RAW_RETENTION_DAYS` (14). Backfill mirrors are exempt |
| `<vault>/wiki/` | Plasmie's filed notes (flat, tagged); `wiki/mocs/` generated maps of content |
| `<vault>/meta/` | Digests, promotion drafts, held items, coverage gaps, usage |
| `<vault>/index.md`, `log.md` | Generated catalog; append-only audit |
| `<vault>/…` anything else | Your own notes, in your folders. Plasmie reads them (search, map, reader) and never reorganizes them |
| `~/Library/Application Support/Plasmie/` | `config.env`, venv, qmd, state files, `feed.log` |
| `~/Library/Logs/Plasmie/` | Per-run ingest logs, audit and model transcripts |
| `~/.config/qmd/index.yml` | qmd's collection config, shared with any other qmd use |

The vault defaults to `~/knowledge` and must be on local disk. macOS blocks background
helpers from reading iCloud and OneDrive folders, and offloaded files read as empty. The
optional iCloud mirror ([`plasmie-icloud.py`](plasmie-icloud.py), [ADR 0023](docs/decisions/0023-icloud-mirror.md))
copies notes and digests one way, Mac to iCloud, for reading on iPhone. It never copies
raw captures.

| Log | Kept |
|---|---|
| `feed.log`: one line per ingest; `*-ERR` marks a failing source | last 2000 lines |
| `ingest-*.log`: full ingest detail | 14 days |
| `audit-*.log`: summarize, promote and improve outcomes | 90 days |
| `transcript-*.log`: exact instructions, prompt and response of every model call | 30 days |

---

## Apple silicon: native tools only

Plasmie runs as arm64 and never executes an Intel (x86_64) binary. An old Intel Homebrew
in `/usr/local` often shadows native tools on `PATH`. Without Rosetta those copies die with
`Bad CPU type in executable`; with Rosetta they run emulated.

- **Python and Node** are pinned, arm64 builds bundled in the app. Before setup creates the
  venv, the app and `plasmie-env.sh` fall back to the bundled runtime, never `/usr/bin/python3`
  (a 3.9 stub that also triggers a developer-tools prompt).
- **External tools** (`git`, `gh`) are resolved by what the binary *is*, not by where `PATH`
  finds it first. [`paths.native_tool`](paths.py) reads the Mach-O header (thin or universal)
  and checks, in order: the recorded path, then `PATH`, then `/opt/homebrew/bin`,
  `~/.local/bin` and `/usr/bin`. The shell equivalent is `plasmie_native` in `plasmie-env.sh`.
- **Setup** keeps `/usr/local/bin` off its own `PATH` on arm64.

---

## Privacy and security

Full user-facing statement: [`docs/PRIVACY.md`](docs/PRIVACY.md).

- **Network:** ingest only. That means the APIs of the connectors you switch on, qmd's models
  once at setup, and the iCloud mirror if enabled. Local git and session sources touch no
  network.
- **Model:** on-device only. Every call is recorded in a transcript log, so what reached the
  model can be checked.
- **Scrubbing:** [`scrub.py`](scrub.py) is the single redactor. It removes tokens, keys,
  connection-string passwords, PEM blocks and high-entropy secrets after credential words
  before anything is written. Promote also strips emails.
- **Model output is untrusted:** `promote-apply.py` confines every path to the vault, scrubs
  bodies, never overwrites and never deletes. The reader's editor writes only the open note.
- **Owner-only files:** `umask 077`, logs `0600`. Runtime data and `config.env` are gitignored.

---

## Development

```bash
.venv/bin/python -m pytest -q        # full suite (~25 s); fake_fm stands in for plasmie-fm
ruff check .                          # must not exceed RUFF_BASELINE in app/make-release.sh
bash -n *.sh launchd/*.sh app/*.sh    # every shell script parses
app/make-app.sh                       # Swift build (swiftc, no Xcode project)
```

- **Layout:** the engine lives at the repo root, one script per job. `paths.py` is the single
  source of layout, config and tool resolution, and `fm.py` is the single model chokepoint.
  The app is in `app/Sources` (one file per surface); `app/fm/main.swift` is `plasmie-fm`.
- **Tests:** they run without Apple Intelligence or network. `conftest.py` provides
  `fake_fm`, an executable fake, so the subprocess path is tested for real. The setup tests
  (`test_setup_vault.py`) need a built app and are skipped otherwise.
- **Stdlib only:** the engine has no Python dependencies. Keep it that way; the app ships a
  bare interpreter.
- **Releases:** bump `VERSION` in a `chore: release X.Y.Z (…)` commit, then run
  `app/make-release.sh`. It runs the tests, ruff and `bash -n` as gates before building the
  DMG. Commits follow Conventional Commits.
- **Data migrations:** versioned and idempotent, in [`plasmie-migrate.py`](plasmie-migrate.py), and run
  at every launch and setup.
- **Upgrading from Plasmie or Plasmie** (earlier names): the migrations carry the install over
  (data, preferences, Keychain sign-ins, jobs; ADR 0027, 0028).
- **Reset:** `plasmie-reset.sh [--dry-run]` removes jobs, data and logs, **never the vault**.

### Troubleshooting

| Symptom | Look at |
|---|---|
| A connector says "Failed last run" | `tail ~/Library/Application\ Support/Plasmie/feed.log`; the last line's `*-ERR` names it. `plasmie-doctor.py <source>` shows why. The status clears on the next successful ingest |
| Nothing filed overnight | `~/Library/Logs/Plasmie/audit-*.log`, and whether Apple Intelligence is on |
| Search misses your notes | `qmd collection list`: all three collections should point inside the vault. Re-run setup to repoint |
| Sending a bug report | The Plasmie window › **Copy diagnostics**: a scrubbed report with no notes or secrets ([`plasmie-diagnostics.py`](plasmie-diagnostics.py)) |
