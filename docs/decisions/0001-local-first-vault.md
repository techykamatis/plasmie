# 0001 · A local-only pipeline over an llm-wiki vault

- **Status:** Accepted
- **Area:** Architecture

## Context
Plasmie turns one person's work activity (Slack, GitHub, local git, Confluence, Outlook,
Claude Code sessions) into durable, searchable memory on their own Mac. That record holds
DMs, code and incident details, so it must not leave the machine.

## Decision
- **The vault is a folder on local disk:** `~/knowledge` unless the user picks another
  (`PLASMIE_VAULT`). Cloud-synced folders are refused as the vault, because launchd jobs
  can't read them under TCC (see [0025](0025-icloud-mirror.md) for the iCloud mirror).
- **Layers:** `raw/` (captures, pruned after 14 days) → `wiki/` (flat, curated) →
  `archive/`; `meta/` holds drafts, digests and state. `index.md` and `log.md` are
  generated; `log.md` is the durable audit.
- **Jobs:** hourly ingest, hourly summarize, an improve/prune pass, a nightly promote
  (draft → dedupe → auto-apply or hold) and a nightly git snapshot of the vault
  ([0024](0024-background-jobs.md) has the schedule).
- **Retrieval** is qmd (BM25 + vectors). Ask answers from `wiki/` and the user's own notes.
  `raw/` is source material: Ask reads it only for recaps and summary questions
  ([0007](0007-plain-summary-answers.md)).
- **Generation is on-device** ([0002](0002-apple-on-device-model.md)). The only network calls
  read the user's own accounts.

## Consequences
- Raw activity ages out after 14 days. Anything worth keeping has to be promoted first.
- The vault is plain Markdown in a git repository, so it opens in Obsidian and survives the
  app being deleted.
