#!/bin/bash
# Reset Plasmie: remove its background jobs, data and logs. NEVER the vault.
#   plasmie-reset.sh --dry-run    print what would be removed, change nothing
#   plasmie-reset.sh --yes        do it (the app asks for confirmation first)
# Order: restore point of the vault first, then jobs, then data and logs. Refuses outright
# if the vault sits inside a folder it would delete. Keychain items are removed here; the login item and app
# preferences are removed by the app itself (they belong to the app, not to this script).
set -uo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
. "$SELF/plasmie-env.sh"
MODE="${1:-}"
[ "$MODE" = --dry-run ] || [ "$MODE" = --yes ] || { echo "usage: plasmie-reset.sh --dry-run|--yes" >&2; exit 2; }

VAULT_PATH="$(cd "${VAULT_DIR:-$HOME/knowledge}" 2>/dev/null && pwd -P || echo "${VAULT_DIR:-$HOME/knowledge}")"
for d in "$PLASMIE_HOME" "$PLASMIE_LOGS"; do
  real="$(cd "$d" 2>/dev/null && pwd -P || echo "$d")"
  case "$VAULT_PATH/" in
    "$real"/*) echo "REFUSED: the vault ($VAULT_PATH) is inside $real; nothing was removed." >&2; exit 3 ;;
  esac
done

say() { printf '%s\n' "$1"; }
run() { if [ "$MODE" = --dry-run ]; then say "would: $*"; else "$@"; fi; }

say "vault kept: $VAULT_PATH"
if [ "$MODE" = --yes ]; then
  "$PY" "$SELF/plasmie-vault.py" snapshot "$VAULT_PATH" "Plasmie reset" 2>/dev/null | sed 's/^/vault: /' || true
fi
if [ "${PLASMIE_RESET_SKIP_JOBS:-0}" != 1 ]; then          # tests skip launchd
  run "$SELF/launchd/install.sh" uninstall
fi
# Plasmie's Keychain items (service "Plasmie"). A PLASMIE_KEYCHAIN that doesn't exist would
# silently mean the LOGIN keychain (tests set one), so then: skip, never guess.
if [ -z "${PLASMIE_KEYCHAIN:-}" ] || [ -f "$PLASMIE_KEYCHAIN" ]; then
  for k in $PLASMIE_SECRETS; do
    if [ "$MODE" = --dry-run ]; then say "would: remove Keychain item Plasmie/$k"
    else /usr/bin/perl -e 'alarm 10; exec @ARGV' /usr/bin/security delete-generic-password -s Plasmie -a "$k" \
           ${PLASMIE_KEYCHAIN:+"$PLASMIE_KEYCHAIN"} >/dev/null 2>&1 || true
    fi
  done
fi
run rm -rf "$PLASMIE_HOME"
run rm -rf "$PLASMIE_LOGS"
say "reset done"
