#!/bin/bash
# gen.sh <timeout_secs> <prompt>
# Run Claude Code against the local Gemma with a "don't disturb the user" wrapper:
#   1. guard  — skip entirely if the machine is busy/hot/low-RAM
#   2. up     — load the model on-demand (~5GB)
#   3. run    — with a HARD timeout: if it drags (contended/slow), kill it fast
#   4. down   — always free the model afterward (trap)
# Prints the model's text on success; exits non-zero (no output) on skip/timeout.
# Honors GEMMA_MODEL from the environment (which local model to use).
set -uo pipefail
umask 077   # logs/transcripts contain your data -> create them owner-only (0600)
SELF="$(cd "$(dirname "$0")" && pwd)"
to="${1:?timeout secs}"; prompt="${2:?prompt}"

[ "$("$SELF/mlx-ctl.sh" guard)" = ok ] || { echo "skip: machine busy/hot/low-RAM" >&2; exit 3; }
"$SELF/mlx-ctl.sh" up || { echo "skip: model server unavailable" >&2; exit 4; }
trap '"$SELF/mlx-ctl.sh" down' EXIT

tmp="$(mktemp)"
"$SELF/cc-local.sh" -p "$prompt" --output-format text --bare \
  --no-session-persistence --permission-mode bypassPermissions \
  >"$tmp" 2>>"$SELF/logs/gen.err" &
cpid=$!
# watchdog: detached from our stdout (else its orphaned `sleep` holds the caller's
# $(...) pipe open for the full timeout) and killed with its sleep when the model returns
( sleep "$to" & spid=$!; trap 'kill "$spid" 2>/dev/null; exit 0' TERM; wait "$spid"; kill "$cpid" 2>/dev/null ) \
  </dev/null >/dev/null 2>&1 & wpid=$!
wait "$cpid"; rc=$?
kill "$wpid" 2>/dev/null || true
out="$(cat "$tmp")"; rm -f "$tmp"

# transcript: exactly what context was sent to the LOCAL model + what came back.
# One daily file; contains your journal/Slack/session data -> pruned after 30 days.
{
  printf '\n========== %s | endpoint=%s | model=%s ==========\n' \
    "$(date '+%F %T')" "${ANTHROPIC_BASE_URL:-http://127.0.0.1:8091}" "${GEMMA_MODEL:-gemma-4-e4b(4bit)}"
  printf -- '----- REQUEST (context sent to model) -----\n%s\n' "$prompt"
  printf -- '----- RESPONSE (rc=%s) -----\n%s\n' "$rc" "$out"
} >> "$SELF/logs/transcript-$(date +%F).log"
find "$SELF/logs" -name 'transcript-*.log' -mtime +30 -delete 2>/dev/null || true

if [ "$rc" -ne 0 ] || [ -z "$out" ]; then
  echo "gen aborted (rc=$rc, likely ${to}s timeout under load) — will retry next run" >&2
  exit 5
fi
printf '%s' "$out"
