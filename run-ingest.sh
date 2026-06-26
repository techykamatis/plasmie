#!/bin/bash
# launchd-driven hourly knowledge-vault ingest — runs with NO Claude session.
# Logging split:
#   logs/ingest-<ts>.log  = FULL DETAIL of one run (window, per-channel + per-project
#                            counts, journal path) — pruned after 14 days.
#   feed.log              = ONE SUMMARY line per run, rolling — `tail -f` this.
set -a
[ -f "$HOME/.claude/.env" ] && . "$HOME/.claude/.env"
set +a

LOGDIR="$HOME/.plasmie/logs"
FEED="$HOME/.plasmie/feed.log"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/ingest-$(date '+%Y%m%d-%H%M%S').log"
TS="$(date '+%Y-%m-%d %H:%M:%S')"

out="$(/opt/homebrew/opt/python@3.12/bin/python3.12 "$HOME/.plasmie/loop-ingest.py" 2>&1)"
rc=$?

# full detail → per-run file
{
  echo "=== $TS ingest start (pid $$) ==="
  echo "$out"
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') ingest done (exit $rc) ==="
} > "$LOG"

# one summary line → rolling feed
summary="$(printf '%s\n' "$out" | sed -n 's/^SUMMARY: //p' | head -1)"
echo "$TS | exit $rc | ${summary:-(no summary)}" >> "$FEED"

# retention: per-run logs 14d; feed capped at 2000 lines
find "$LOGDIR" -name 'ingest-*.log' -type f -mtime +14 -delete
tail -n 2000 "$FEED" > "$FEED.tmp" 2>/dev/null && mv "$FEED.tmp" "$FEED"
exit "$rc"
