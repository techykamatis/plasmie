# 0003 · Connectors are opt-in, with one On/Off switch each ("off means off")

- **Status:** Accepted
- **Area:** Architecture, product, privacy

## Context
Plasmie runs on other people's Macs. Defaults that belong to one person (a GitHub org, a git
folder, every connector on) are wrong for anyone else: an org you aren't in fails every
run, and an app reaching services you never chose is a bad surprise. People also want to
turn single sources on and off by hand. The pipeline is several processes (Python ingest,
shell summarize and promote, the doctor, the Swift app), and they all have to agree on
which sources are on.

## Decision
- **A fresh install starts with every network connector Off** (Slack, GitHub, Confluence,
  Outlook). Local sources start On only when there is something to read: Claude Code
  sessions if `~/.claude/projects` exists; local git if developer tools are installed and a
  common folder (`~/code`, `~/Developer`, `~/src`, `~/Projects`, …) holds a repo, in which
  case those folders are written as `PLASMIE_GIT_ROOTS`. Setup writes this once
  (`migrate-home.sh`); running it again changes nothing. An install that already has ingest
  state keeps its switches.
- **One key, one reader.** `PLASMIE_DISABLED_SOURCES="github,confluence"` in
  `$PLASMIE_HOME/config.env`; the app writes it the moment a card's switch flips (no Save).
  `paths.disabled_sources()` / `paths.activity_dirs()` read it, and shell jobs ask
  `paths.py activity-dirs` instead of parsing config themselves. The environment variable
  overrides config.env for one-off runs.
- **Off means off:** no fetch and no network call for that source. Its watermark still
  advances, so turning it back On does **not** backfill the Off period. Backfill scripts
  refuse to run for an Off source, and the doctor reports `enabled:false` without probing.
  The Outlook switch is Outlook's only gate.
- **No owner values in code.** GitHub orgs default to none (= everything you authored or
  commented on, in any org); git folders default to none (= not set up); session labels
  derive from `$HOME` and your git folders. `test_no_personal.py` fails on the owner's org,
  domains, username or home path in any tracked code, doc, template or config file. Its
  terms live in an untracked local `.personal-deny.txt`, so the list itself isn't published.

## Alternatives rejected
- **A missing switch key means all On:** a new user's first hour would call services they
  never chose.
- **Holding the watermark while Off:** it would quietly import the period the user excluded.
- **Each script parsing config itself:** separate parsers drift on quoting.
- **Detecting git folders at every run:** what is scanned should be visible and editable in
  Settings, so detection happens once and is written down.

## Consequences
- Captured data stays searchable; a switch stops new capture only.
- With no connector set up, the app still works from local sessions and git.
