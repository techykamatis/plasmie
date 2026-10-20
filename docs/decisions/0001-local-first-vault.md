# 0001 · Local-only pipeline over an llm-wiki vault

- **Status:** Accepted (pre-dates 2026-10-03; recorded here as the foundation)
- **Area:** Architecture

## Context
The tool turns one person's work activity (Slack, GitHub, local git, Confluence,
Claude Code sessions) into durable, searchable memory on their own Mac.
The record contains DMs, code, and incident details: it must not leave the machine.

## Decision
- Vault at `~/knowledge` (local disk only; cloud-synced folders break launchd reads
  under TCC). Layers: `raw/` (transient, pruned after 14 days) → `wiki/` (flat,
  curated, the only answer layer) → `archive/`; `meta/` for drafts, digests, state.
  `index.md` and `log.md` are generated; `log.md` is the durable audit.
- Hourly ingest, hourly summarize, nightly promote (draft → dedupe → auto-apply or
  hold), plus an improve/prune pass and a nightly git snapshot of the vault.
- Retrieval by qmd (BM25 + vectors) over `raw` and `wiki`; Ask answers from `wiki` only.
- All generation on-device (see 0004). The only network calls read the owner's own accounts.

## Consequences
- Old raw activity disappears; anything worth keeping must be promoted before it ages out.
- Email stays a blind spot (Outlook needs tenant-admin consent this tool won't get).
