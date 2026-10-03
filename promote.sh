#!/bin/bash
# Daily: Apple's on-device model drafts promotions from recent raw activity into a
# review note, then dedupe + auto-apply. Text-in / text-out: promote_plan.py reads
# yesterday+today's raw activity (every connector switched On) and raw/inbox drops
# (scrubbed), map-reduces it to fit the model's live context window (ADR 0021), and
# prints the draft body; this script owns the draft file, the audit and the apply.
#
#   promote.sh                  nightly run (writes meta/promotion-drafts/<today>.md)
#   promote.sh --dry-run DIR    draft into DIR only: no vault writes, no dedupe/apply
set -euo pipefail
umask 077   # audit/transcript logs are owner-only (contain your data)
SELF="$(cd "$(dirname "$0")" && pwd)"
. "$SELF/plasmie-env.sh"
DRY=""
[ "${1:-}" = --dry-run ] && { DRY="${2:?usage: promote.sh --dry-run DIR}"; mkdir -p "$DRY"; }
# one audit line per run -> logs/audit-YYYY-MM-DD.log (one file per day; pruned after 90d)
audit(){ printf '%s | promote | %s\n' "$(date '+%F %T')" "$1" >> "$PLASMIE_LOGS/audit-$(date +%F).log"
         find "$PLASMIE_LOGS" -name 'audit-*.log' -mtime +90 -delete 2>/dev/null || true; }
# live one-line heartbeat the menu-bar app reads: "<epoch>|<message>"
STATUS_FILE="$PLASMIE_HOME/.status"
status(){ [ -n "$DRY" ] || printf '%s|%s' "$(date +%s)" "$1" > "$STATUS_FILE"; }
VAULT="${VAULT_DIR:-$HOME/knowledge}"
TODAY="$(date +%F)"
YEST="$(date -v-1d +%F 2>/dev/null || date -d 'yesterday' +%F)"
if [ -n "$DRY" ]; then DRAFT="$DRY/$TODAY.md"
else DRAFT="$VAULT/meta/promotion-drafts/$TODAY.md"; mkdir -p "$VAULT/meta/promotion-drafts"; fi

status "Drafting on-device…"
rc=0
args=(--vault "$VAULT" --dates "$YEST,$TODAY")
if [ -n "$DRY" ]; then args+=(--no-guard); else args+=(--status-file "$STATUS_FILE"); fi
out="$("$PY" "$SELF/promote_plan.py" "${args[@]}" 2>"$PLASMIE_LOGS/promote-plan.err")" || rc=$?
plan="$(grep '^PLAN:' "$PLASMIE_LOGS/promote-plan.err" 2>/dev/null | tail -1 | sed 's/^PLAN: //')"
case "$rc" in
  0) ;;
  3) audit "skipped (machine busy) ${plan}"; status "Skipped — machine busy"
     echo "promote skipped (machine busy) — retries tomorrow"; exit 0 ;;
  4) audit "skipped: Apple Intelligence unavailable ${plan}"; status "Skipped — Apple Intelligence is off"
     echo "promote skipped: Apple Intelligence is unavailable (${plan})"; exit 0 ;;
  6) echo "no recent raw activity to promote"; exit 0 ;;
  *) audit "FAILED (promote_plan rc=$rc) ${plan}: $(grep -v '^PLAN:' "$PLASMIE_LOGS/promote-plan.err" | tail -c 200 | tr '\n' ' ')"
     status "Promote failed — retries tomorrow"; echo "promote failed (rc=$rc) — retries tomorrow"; exit 0 ;;
esac

{
  printf -- '---\ntype: note\ntitle: promotion-draft %s\ntags: [promotion-draft]\ntimestamp: %sT00:00:00Z\n---\n\n# Promotion draft %s\n_On-device suggestions from raw activity %s–%s. Review before promoting._\n\n' "$TODAY" "$TODAY" "$TODAY" "$YEST" "$TODAY"
  printf '%s\n' "$out"
} > "$DRAFT"
n=$(printf '%s' "$out" | grep -c '^## ' || true)
audit "ok: ${n}-item draft (${plan}) -> $DRAFT"
echo "wrote promotion draft -> $DRAFT ($n items; $plan)"
[ -z "$DRY" ] || exit 0

# enrich + AUTO-APPLY: dedupe assigns each item an Action; promote-apply --auto then
# applies the confident items (new notes normalized into concepts/, confident-merge only)
# and holds the uncertain ones in <date>.hold.md for a quick review. No human gate.
{
  status "Finding duplicates…"
  "$PY" "$SELF/dedupe.py" "$DRAFT" "$VAULT" --write && audit "ok: dedupe-enriched draft" || audit "dedupe skipped (error)"
  status "Auto-applying…"
  result="$("$PY" "$SELF/promote-apply.py" --auto "$DRAFT" "$VAULT" 2>&1)"
  echo "$result"
  summary="$(printf '%s' "$result" | sed -n 's/^AUTO: //p' | head -1)"
  audit "auto: ${summary:-none}"
  applied="$(printf '%s' "$summary" | sed -n 's/^\([0-9]*\) applied.*/\1/p')"
  held="$(printf '%s' "$summary" | sed -n 's/.* \([0-9]*\) held.*/\1/p')"
  status "Promoted ${applied:-0} · ${held:-0} held"
  if [ -n "$summary" ]; then
    msg="auto-promoted ${applied:-0}"
    if [ "${held:-0}" -gt 0 ] 2>/dev/null; then msg="$msg · ${held} held for review"; fi
    osascript -e "display notification \"$msg\" with title \"Plasmie 🧠\"" 2>/dev/null || true
  fi
}
