# 0024 · Connectors are opt-in; nothing about the owner is a default

- **Status:** Accepted · 2026-10-04
- **Area:** Product, privacy

## Context
Plasmie grew up on one Mac. Its defaults were that person's: GitHub org `fabrikam`, git
folder `~/code`, session labels keyed to his home path, every connector On. For a friend
those defaults are wrong at best (an org they aren't in fails every run) and surprising at
worst (Plasmie reaching out to services they never chose).

## Decision
- A **fresh install starts with every network connector Off** (Slack, GitHub, Confluence,
  Outlook). Local sources start On only when there is something to read: Claude Code
  sessions if `~/.claude/projects` exists, AgentCLI if its database exists, local git if
  developer tools are installed and a common folder (`~/code`, `~/Developer`, `~/src`,
  `~/Projects`, …) holds a repo, in which case those folders are written as
  `PLASMIE_GIT_ROOTS`. Setup writes this once (`migrate-home.sh`); re-running it changes nothing.
- **No owner values in code:** GitHub orgs default to none (= everything you authored or
  commented on, any org); git folders default to none (= not set up); session labels derive
  from `$HOME` and your git folders. `test_no_personal.py` fails on the owner's org,
  domains, username or home path in any tracked code file.
- The Outlook switch is its only gate (the old `PLASMIE_OUTLOOK=1` second gate is gone).
- **Existing installs keep everything:** an install with ingest state keeps its switches;
  its old settings move from `~/.claude/.env` to `config.env` verbatim (ADR 0021).

## Alternatives rejected
- **Absent switch key = all On** for new installs too: a friend's first hour would call
  services they never chose.
- **Auto-detecting git folders at every run:** what is scanned should be visible and
  editable in Settings, so detection happens once and is written down.

## Consequences
With no connector set up, Plasmie still works from local sessions and git. The com.legacy
launchd labels and bundle id remain; they move with the SMAppService work.
