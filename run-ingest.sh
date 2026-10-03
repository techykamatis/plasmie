#!/bin/bash
# launchd-driven hourly knowledge-vault ingest — runs with NO Claude session.
# Logging split:
#   logs/ingest-<ts>.log  = FULL DETAIL of one run (window, per-channel + per-project
#                            counts, journal path) — pruned after 14 days.
#   feed.log              = ONE SUMMARY line per run, rolling — `tail -f` this.
set -a
[ -f "$HOME/.claude/.env" ] && . "$HOME/.claude/.env"
set +a

SELF="$(cd "$(dirname "$0")" && pwd)"
[ -f "$SELF/config.env" ] && . "$SELF/config.env"
export PLASMIE_VAULT="${VAULT_DIR:-$HOME/knowledge}"

LOGDIR="$HOME/.plasmie/logs"
FEED="$HOME/.plasmie/feed.log"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/ingest-$(date '+%Y%m%d-%H%M%S').log"
TS="$(date '+%Y-%m-%d %H:%M:%S')"
status(){ printf '%s|%s' "$(date +%s)" "$1" > "$HOME/.plasmie/.status"; }

status "Ingesting Slack + Claude sessions…"
out="$(/opt/homebrew/opt/python@3.12/bin/python3.12 "$HOME/.plasmie/loop-ingest.py" 2>&1)"
rc=$?

# full detail → per-run file
{
  echo "=== $TS ingest start (pid $$) ==="
  echo "$out"
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') ingest done (exit $rc) ==="
} > "$LOG"

summary="$(printf '%s\n' "$out" | sed -n 's/^SUMMARY: //p' | head -1)"

# refresh qmd so the docs just ingested are actually searchable. Without this the
# index freezes at install time — the hourly loop appends raw/ docs that ask.py
# and the MCP never see. `update` re-indexes (fast, sqlite); `embed` is incremental
# (only new/changed docs), so per-run cost tracks the handful of new files.
# qmd is a Node CLI, not on launchd's PATH — resolve it explicitly. Resolving the
# BINARY is not enough: its `#!/usr/bin/env node` shebang needs `node` on PATH too,
# or every run dies with "env: node: No such file or directory" straight into $LOG
# where nobody reads it. Put qmd's own bin dir (which holds node) on PATH, and
# surface failures on the feed line instead of muting them.
status "Indexing new docs…"
QMD="$(command -v qmd || true)"
[ -z "$QMD" ] && QMD="$(ls "$HOME"/.nvm/versions/node/*/bin/qmd 2>/dev/null | tail -1)"
qmd_err=""
if [ -n "$QMD" ]; then
  export PATH="$(dirname "$QMD"):$PATH"
  for step in update embed; do
    echo "--- qmd $step ---" >> "$LOG"
    if ! "$QMD" "$step" >> "$LOG" 2>&1; then
      qmd_err="${qmd_err:+$qmd_err,}$step"
    fi
  done
else
  qmd_err="not-found"
  echo "qmd not found — skipped index refresh" >> "$LOG"
fi
[ -n "$qmd_err" ] && summary="${summary:-(no summary)} · QMD-ERR $qmd_err"
status "Ingested · ${summary:-done}"

# trophies + evolution: cheap, read-only on the vault; notifies only on NEW unlocks
"$SELF/.venv/bin/python3" "$SELF/plasmie-achievements.py" --notify >/dev/null 2>>"$LOG" || true
# weekly (self-gated): draft recurring patterns for review — nothing reaches the wiki unapproved
"$SELF/.venv/bin/python3" "$SELF/plasmie-patterns.py" >>"$LOG" 2>&1 || true

# one summary line → rolling feed. Written AFTER indexing so a qmd failure lands
# on the feed line too — `tail feed.log` is the one place failures get noticed.
# ERR count makes a broken stage greppable instead of buried mid-string.
errs="$(printf '%s\n' "$summary" | grep -o '[A-Z-]*-ERR' | wc -l | tr -d ' ')"
echo "$TS | exit $rc | errors $errs | ${summary:-(no summary)}" >> "$FEED"

# retention: per-run logs 14d; feed capped at 2000 lines
find "$LOGDIR" -name 'ingest-*.log' -type f -mtime +14 -delete
tail -n 2000 "$FEED" > "$FEED.tmp" 2>/dev/null && mv "$FEED.tmp" "$FEED"
exit "$rc"
