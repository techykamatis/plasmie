#!/bin/bash
# One-way mirror: local vault -> OneDrive replica (cross-device sync).
#
# ~/knowledge (local disk) is the SOURCE OF TRUTH; OneDrive holds a replica.
# The loop agents only ever touch the local vault (CloudStorage is TCC-hostile
# to background reads — see the "knowledge-vault-stays-local" note). This mirror
# only *writes* to CloudStorage, which launchd is allowed to do.
#
# rsync writes to a temp name then renames, so a file the loop is mid-rewrite
# never propagates half-written. One-way + --delete keeps the replica exact;
# a guard refuses to run against an empty/broken source so we never wipe it.
set -uo pipefail

SELF="$(cd "$(dirname "$0")" && pwd)"
[ -f "$SELF/config.env" ] && . "$SELF/config.env"
SRC="${VAULT_DIR:-$HOME/knowledge}"
DEST="${MIRROR_DEST:-}"           # OneDrive replica path; blank = sync not configured
LOG="$SELF/logs/mirror.log"
mkdir -p "$(dirname "$LOG")"
ts() { date '+%F %T'; }

# sync not set up (grandma skipped it in the wizard) — nothing to do, quietly.
[ -n "$DEST" ] || exit 0

# safety: a near-empty source would let --delete nuke the replica. Bail out.
n=$(find "$SRC" -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')
if [ "$n" -lt 5 ]; then
    echo "$(ts) ABORT: source $SRC looks empty/broken (entries=$n)" >>"$LOG"
    exit 1
fi

mkdir -p "$DEST"
rsync -a --delete \
    --exclude '.DS_Store' \
    --exclude '.ruff_cache/' \
    --exclude '.obsidian/workspace*.json' \
    "$SRC/" "$DEST/" >>"$LOG" 2>&1
rc=$?
echo "$(ts) mirror rc=$rc (source entries=$n)" >>"$LOG"
exit $rc
