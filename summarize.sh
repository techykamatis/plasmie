#!/bin/bash
# Hourly: condense today's raw activity (every connector switched On) into a
# few bullets via Apple's on-device model (digest.py). Text in / text out — no file
# tools, no Slack creds. Writes a rolling daily digest to meta/digests/YYYY-MM-DD.md,
# regenerated each run so it's always current and idempotent (no marker needed).
set -euo pipefail
umask 077   # audit/transcript logs are owner-only (contain your data)
SELF="$(cd "$(dirname "$0")" && pwd)"
. "$SELF/plasmie-env.sh"
# one audit line per run -> logs/audit-YYYY-MM-DD.log (one file per day; pruned after 90d)
audit(){ printf '%s | summarize | %s\n' "$(date '+%F %T')" "$1" >> "$PLASMIE_LOGS/audit-$(date +%F).log"
         find "$PLASMIE_LOGS" -name 'audit-*.log' -mtime +90 -delete 2>/dev/null || true; }
VAULT="${VAULT_DIR:-$HOME/knowledge}"
DAY="$(date +%F)"

# raw dirs to read: every connector not switched Off in the app (paths.py owns the rule)
DIRS="$("$PY" "$SELF/paths.py" activity-dirs)" \
  || { audit "FAILED: paths.py activity-dirs"; exit 1; }
# gather today's raw source files. Each present source gets an equal share of the
# 20k budget (tail = newest), so one chatty source can't crowd the rest out.
# retry: a read can race the hourly ingest rewriting the same file.
present=(); for s in $DIRS; do [ -f "$VAULT/raw/$s/$DAY.md" ] && present+=("$s"); done
per=$(( 20000 / (${#present[@]} > 0 ? ${#present[@]} : 1) ))
input=""
for s in ${present[@]+"${present[@]}"}; do
  f="$VAULT/raw/$s/$DAY.md"
  for _ in 1 2 3 4; do
    c="$(tail -c "$per" "$f" 2>/dev/null)" && { input="$input

===== $s =====
$c"; break; }
    sleep 0.5
  done
done
[[ "$input" == *[![:space:]]* ]] || { echo "no raw activity today"; exit 0; }

# The digest is a rolling whole-day rollup, so it is regenerated rather than
# appended. But regenerating identical input just burns model cycles and
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

# Generation lives in digest.py: Apple's on-device model, the measured
# faithfulness prompt (see digest.py), one call when the day fits the live
# context window and map-reduce when it doesn't. It defers (rc 3) while the
# machine is busy or hot, like every background job.
model="Apple on-device"
rc=0
out="$(printf '%s' "$input" | "$PY" "$SELF/digest.py" 2>"$PLASMIE_LOGS/digest.err")" || rc=$?
case "$rc" in
  0) ;;
  3) audit "skipped (machine busy)"; echo "summarize skipped (machine busy) — retries next hour"; exit 0 ;;
  4) why="$(tail -c 300 "$PLASMIE_LOGS/digest.err" 2>/dev/null | tr '\n' ' ')"
     audit "skipped: Apple Intelligence unavailable — $why"
     echo "summarize skipped: Apple Intelligence is unavailable. $why"; exit 0 ;;
  *) audit "FAILED (digest.py rc=$rc): $(tail -c 200 "$PLASMIE_LOGS/digest.err" 2>/dev/null | tr '\n' ' ')"
     echo "summarize failed — retries next hour"; exit 0 ;;
esac
[[ "$out" == *[![:space:]]* ]] || { audit "FAILED: empty digest"; exit 0; }

mkdir -p "$DIGEST_DIR"
{ printf -- '---\ntype: note\ntitle: digest %s\ntags: [digest]\ntimestamp: %sT00:00:00Z\n---\n\n# Digest · %s\n_%s rollup of the day'"'"'s raw activity. Regenerated when raw activity changes._\n\n%s\n' \
    "$DAY" "$DAY" "$DAY" "$model" "$out"; } > "$DIGEST"
printf '%s' "$hash" > "$STAMP"
n=$(printf '%s\n' "$out" | grep -c . || true)
audit "ok: wrote ${n}-line digest ($model) -> meta/digests/$DAY.md"
echo "wrote digest ($n lines) -> $DIGEST"
