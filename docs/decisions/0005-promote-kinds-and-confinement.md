# 0005 · Promote keeps the drafter's kind; created notes stay inside wiki/

- **Status:** Accepted
- **Area:** Architecture, security

## Context
The wiki is flat, but the kind of a note (gotcha, decision, pattern…) is load-bearing: the
vault contract relies on it, and so do summary answers and fun facts. Promotion drafts are
model output, so the apply step must treat them as untrusted.

## Decision
- `Target:` is a **kind** hint (gotcha, decision, pattern, how-to, concept, person,
  project, tech, security, clipping). It sets the note's type and tag, and the file lands
  flat in `wiki/`. Type and tag come from the hint itself, so placing the file never erases
  the kind.
- Path-like targets keep the containment and no-overwrite checks.
- **Created notes must resolve inside `wiki/`**, or the item is refused. A draft can't name
  any other path in the vault, so it can't plant a fake draft in `meta/` or files in `raw/`.

## Consequences
Every auto-promoted note carries a type and a tag, which summary answers
([0007](0007-plain-summary-answers.md)) and fun facts ([0010](0010-fun-facts.md)) depend on.
