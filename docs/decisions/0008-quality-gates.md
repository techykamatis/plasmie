# 0008 · Quality gates the pipeline enforces on itself

- **Status:** Accepted
- **Area:** Architecture, security

## Context
The pipeline runs unattended. A quiet failure looks the same as a quiet day, and a secret
that slips into the vault stays there. Each gate below makes one of those failures loud.

## Decision
- **Scrubber:** redacts bare Atlassian, JWT, Slack app, GitLab, Hugging Face and Microsoft
  refresh tokens alongside its other patterns, with a test per shape, negatives included.
- **`reindex.py --check`** exits non-zero on dead wikilinks and on notes stamped on or after
  2026-09-17 (`PROVENANCE_FROM`) that cite no source. `index.md` reports notes and maps
  truthfully.
- **Doctor:** a source that has delivered before and has since lost its credentials is
  stale. Without this, a dead connector can sit dark for months reporting `stale:false`.
- **Coverage gaps** close only strictly above the score floor.

## Consequences
A failing gate shows up in the audit log, the doctor's verdicts and the connector cards,
rather than as a slowly emptier wiki.
