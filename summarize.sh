#!/bin/bash
# Hourly: condense today's raw activity (every connector switched On) into a
# few bullets via the on-device Apple model (local Gemma fallback). Text in / text out — no file tools, no
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

# raw dirs to read: every connector not switched Off in the app (paths.py owns the rule)
DIRS="$("$SELF/.venv/bin/python3" "$SELF/paths.py" activity-dirs 2>/dev/null || python3 "$SELF/paths.py" activity-dirs)" \
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

# Faithfulness rules: the bare prompt put an unsupported claim (a plan reported
# as done, "merged"/"live" nobody said, an invented team) in 14/15 real digests;
# these cut it to 3/15 and won blind 11-3 (docs/fm-baseline.md, 2026-09-30).
prompt="Condense this raw activity log into 4-8 terse markdown bullets: real decisions, blockers, and who/what changed.
Rules:
- State only what the log explicitly says. Never upgrade a status: write merged, deployed, live, fixed or confirmed only if the log says exactly that. A request, plan or attempt stays a request, plan or attempt.
- Copy names, PR numbers and identifiers exactly as written. Never invent people, teams, milestones or follow-up work.
- If unsure, leave it out: fewer accurate bullets beat more guessed ones.
No preamble, no headings, bullets only.

$input"

# gen.sh handles guard + on-demand load + hard timeout + free. Skips quietly if busy.
# On-device Apple FM first: beat Gemma blind 9-6 on 15 real digests with equal
# unsupported-claim counts (2026-09-30), and needs no 5GB model load. fm.generate
# returns "" (-> Gemma) when unavailable, busy, over the context window, or slow.
model="Apple on-device"
out="$(printf '%s' "$prompt" | "$SELF/.venv/bin/python3" -c 'import sys; sys.path.insert(0, sys.argv[1]); import fm; print(fm.generate(sys.stdin.read(), timeout=90, max_tokens=800) or "", end="")' "$SELF" 2>>"$SELF/logs/gen.err")" || out=""
if [ -z "$out" ]; then
  model="Local-Gemma"
  out="$("$SELF/gen.sh" 200 "$prompt")" || { audit "skipped (busy or timed out)"; echo "summarize skipped — retries next hour"; exit 0; }
fi

mkdir -p "$DIGEST_DIR"
{ printf -- '---\ntype: note\ntitle: digest %s\ntags: [digest]\ntimestamp: %sT00:00:00Z\n---\n\n# Digest · %s\n_%s rollup of the day'"'"'s raw activity. Regenerated when raw activity changes._\n\n%s\n' \
    "$DAY" "$DAY" "$DAY" "$model" "$out"; } > "$DIGEST"
printf '%s' "$hash" > "$STAMP"
n=$(printf '%s\n' "$out" | grep -c . || true)
audit "ok: wrote ${n}-line digest ($model) -> meta/digests/$DAY.md"
echo "wrote digest ($n lines) -> $DIGEST"
