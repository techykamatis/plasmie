#!/bin/bash
# Hourly: condense today's raw activity (Slack + Claude sessions + Outlook) into a
# few bullets via the LOCAL Gemma model. Text in / text out — no file tools, no
# Slack creds. Writes a rolling daily digest to meta/digests/YYYY-MM-DD.md,
# regenerated each run so it's always current and idempotent (no marker needed).
set -euo pipefail
umask 077   # audit/transcript logs are owner-only (contain your data)
SELF="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$SELF/logs"
# one audit line per run -> logs/audit-YYYY-MM-DD.log (one file per day; pruned after 90d)
audit(){ printf '%s | summarize | %s\n' "$(date '+%F %T')" "$1" >> "$SELF/logs/audit-$(date +%F).log"
         find "$SELF/logs" -name 'audit-*.log' -mtime +90 -delete 2>/dev/null || true; }
[ -f "$SELF/config.env" ] && . "$SELF/config.env"
VAULT="${VAULT_DIR:-$HOME/knowledge}"
DAY="$(date +%F)"

# gather today's raw source files. retry: a read can race the hourly ingest
# rewriting the same file; a few attempts ride it out.
input=""
for s in slack claude outlook; do
  f="$VAULT/raw/$s/$DAY.md"
  [ -f "$f" ] || continue
  for _ in 1 2 3 4; do
    c="$(cat "$f" 2>/dev/null)" && { input="$input

===== $s =====
$c"; break; }
    sleep 0.5
  done
done
input="$(printf '%s' "$input" | tail -c 20000)"
[ -n "${input// /}" ] || { echo "no raw activity today"; exit 0; }

# The digest is a rolling whole-day rollup, so it is regenerated rather than
# appended. But regenerating identical input just burns local-LLM cycles and
# lets a worse sample overwrite a better one — so skip when nothing changed.
DIGEST_DIR="$VAULT/meta/digests"
DIGEST="$DIGEST_DIR/$DAY.md"
STAMP="$DIGEST_DIR/.$DAY.inputhash"
hash="$(printf '%s' "$input" | shasum -a 256 | cut -d' ' -f1)"
if [ -f "$DIGEST" ] && [ -f "$STAMP" ] && [ "$hash" = "$(cat "$STAMP" 2>/dev/null)" ]; then
  audit "skipped (raw activity unchanged)"
  echo "digest current — raw activity unchanged since last run"
  exit 0
fi

prompt="Condense this raw activity log into 4-8 terse markdown bullets: real decisions, blockers, and who/what changed. No preamble, no headings, bullets only.

$input"

# gen.sh handles guard + on-demand load + hard timeout + free. Skips quietly if busy.
out="$("$SELF/gen.sh" 200 "$prompt")" || { audit "skipped (busy or timed out)"; echo "summarize skipped — retries next hour"; exit 0; }

mkdir -p "$DIGEST_DIR"
{ printf -- '---\ntype: note\ntitle: digest %s\ntags: [digest]\ntimestamp: %sT00:00:00Z\n---\n\n# Digest · %s\n_Local-Gemma rollup of the day'"'"'s raw activity. Regenerated when raw activity changes._\n\n%s\n' \
    "$DAY" "$DAY" "$DAY" "$out"; } > "$DIGEST"
printf '%s' "$hash" > "$STAMP"
n=$(printf '%s\n' "$out" | grep -c . || true)
audit "ok: wrote ${n}-line digest -> meta/digests/$DAY.md"
echo "wrote digest ($n lines) -> $DIGEST"
