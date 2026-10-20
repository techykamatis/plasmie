# 0010 · Quality gates the pipeline enforces on itself

- **Status:** Accepted · 2026-10-03
- **Area:** Architecture, security

## Decision
- **Scrubber** redacts bare Atlassian, JWT, Slack app, GitLab, Hugging Face and MS
  refresh tokens in addition to the existing patterns (tests per shape, negatives too).
- **`reindex.py --check`** exits non-zero on dead wikilinks and on notes stamped after
  2026-09-17 without provenance; `index.md` reports notes and maps truthfully.
- **Doctor** marks a source stale when it used to deliver and lost credentials
  (Confluence sat dark for 93 days reporting `stale:false`).
- **Coverage gaps** close only strictly above the score floor.
- **`gen.sh` watchdog** is detached from stdout and killed with its `sleep`; before this,
  every caller waited out the full timeout ("Promote now" hung 8 minutes).
- Commits run as their own shell call (a plugin hook rejects any command mixing a commit
  with `-n` flags).
