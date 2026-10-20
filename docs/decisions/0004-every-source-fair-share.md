# 0003 · Summarize and promote read every source, with a fair share each

- **Status:** Accepted · 2026-10-03
- **Area:** Architecture

## Context
The audit found `summarize.sh` and `promote.sh` hard-coded `slack claude outlook`:
GitHub and local-git activity was captured, never promoted, and pruned after 14 days.
Both scripts also cut their input with one global `tail -c`, which dropped whole sources.

## Decision
- Source list comes from `paths.activity_dirs()` (respects 0002; includes github + git).
- Each present source file gets an equal share of the byte budget (newest tail), so one
  chatty source can't crowd the others out.
- The Ask recap reads the same dirs.

## Consequences
Promotion now sees commits and PRs; budgets are still bytes, not tokens (see 0004 for
the token-aware budget in Ask).
