# 0005 · Promote keeps the drafter's kind; created notes stay inside wiki/

- **Status:** Accepted · 2026-10-03
- **Area:** Architecture, security

## Context
After the flat-wiki change, auto-apply rewrote every create's `Target:` hint to `wiki`
*before* deriving the note's type and tag, so every auto-promoted note became a
tagless `note`, and the drafter couldn't say gotcha / decision / pattern at all, though
the vault contract calls those load-bearing.

## Decision
- `Target:` is a **kind** hint (gotcha, decision, pattern, how-to, concept, person,
  project, tech, security, clipping); it sets type + tag, and the file lands flat in `wiki/`.
- Path-like targets keep containment and no-overwrite checks.
- **Security (found by the background commit review):** the first version let an
  untrusted draft name any in-vault path, e.g. plant a fake draft in `meta/` or files
  in `raw/`. Created notes must now resolve inside `wiki/`, or the item is refused.

## Consequences
~100 notes promoted before the fix remain mislabelled `note`; they can be re-typed
from their archived drafts on request.
