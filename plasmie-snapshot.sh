#!/bin/bash
# Daily: commit the vault to git (and push if a remote exists).
# The loop writes ~100 wiki pages a month and prunes raw/ at 14 days; without
# this, all of it lives only in one uncommitted working tree on one laptop.
set -euo pipefail
_env_vault="${VAULT_DIR:-}"   # an explicit VAULT_DIR wins over config.env (makes this testable)
[ -f "$HOME/.plasmie/config.env" ] && . "$HOME/.plasmie/config.env"
VAULT="${_env_vault:-${VAULT_DIR:-$HOME/knowledge}}"
cd "$VAULT" || exit 0

git add -A
if git diff --cached --quiet; then
  echo "$(date '+%F %T') | nothing to snapshot"
  exit 0
fi

stat="$(git diff --cached --shortstat | sed 's/^ *//')"
git commit -q -m "snapshot: $(date +%F) — ${stat}"
echo "$(date '+%F %T') | committed: ${stat}"

# ponytail: push only if a remote is configured; a local-only vault is still
# protected against accidental deletion, just not against disk loss.
if git remote get-url origin >/dev/null 2>&1; then
  if git push -q origin HEAD 2>/dev/null; then
    echo "$(date '+%F %T') | pushed to origin"
  else
    echo "$(date '+%F %T') | WARN push failed (offline or auth) — commit is safe locally"
  fi
fi
