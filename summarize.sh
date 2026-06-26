#!/bin/bash
# Hourly: condense the newest raw auto-ingest block in today's journal into a
# few bullets, using the LOCAL Gemma model via Claude Code. Text in / text out —
# no file tools, no Slack creds needed (operates on already-ingested journal).
set -euo pipefail
umask 077   # audit/transcript logs are owner-only (contain your data)
SELF="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$SELF/logs"
# one audit line per run -> logs/audit-YYYY-MM-DD.log (one file per day; pruned after 90d)
audit(){ printf '%s | summarize | %s\n' "$(date '+%F %T')" "$1" >> "$SELF/logs/audit-$(date +%F).log"
         find "$SELF/logs" -name 'audit-*.log' -mtime +90 -delete 2>/dev/null || true; }
VAULT="$HOME/knowledge"
JPATH="$VAULT/02 Areas/journal/$(date +%F).md"
[ -f "$JPATH" ] || { echo "no journal for today: $JPATH"; exit 0; }

# grab the last "## HH:MM · auto-ingest ..." block through EOF
block="$(awk '/^## .*auto-ingest/{buf=""; cap=1} cap{buf=buf $0 ORS} END{printf "%s", buf}' "$JPATH")"
[ -n "$block" ] || { echo "no auto-ingest block to summarize"; exit 0; }

# already summarized this block? (idempotent for re-runs within the hour)
case "$block" in *"summary (local gemma)"*) echo "already summarized"; exit 0;; esac

prompt="Condense this raw activity log into 4-8 terse markdown bullets: real decisions, blockers, and who/what changed. No preamble, no headings, bullets only.

$block"

# gen.sh handles guard + on-demand load + hard timeout + free. Skips quietly if busy.
out="$("$SELF/gen.sh" 150 "$prompt")" || { audit "skipped (busy or timed out)"; echo "summarize skipped — retries next hour"; exit 0; }

{ printf '\n#### 🤖 summary (local gemma)\n%s\n' "$out"; } >> "$JPATH"
n=$(printf '%s' "$out" | wc -l | tr -d ' ')
audit "ok: appended ${n}-line summary"
echo "appended summary ($n lines) to $JPATH"
