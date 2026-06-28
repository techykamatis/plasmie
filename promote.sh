#!/bin/bash
# Daily: local Gemma (via Claude Code) drafts promotions from recent journal
# entries into a review note. Text-in / text-out — the script does the file I/O,
# so it doesn't depend on the small local model driving CC's tool-use (which it
# doesn't do reliably). Output is a draft for you to review, never direct edits.
set -euo pipefail
umask 077   # audit/transcript logs are owner-only (contain your data)
SELF="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$SELF/logs"
# one audit line per run -> logs/audit-YYYY-MM-DD.log (one file per day; pruned after 90d)
audit(){ printf '%s | promote | %s\n' "$(date '+%F %T')" "$1" >> "$SELF/logs/audit-$(date +%F).log"
         find "$SELF/logs" -name 'audit-*.log' -mtime +90 -delete 2>/dev/null || true; }
# live one-line heartbeat the menu-bar app reads: "<epoch>|<message>"
status(){ printf '%s|%s' "$(date +%s)" "$1" > "$SELF/.status"; }
[ -f "$SELF/config.env" ] && . "$SELF/config.env"
VAULT="${VAULT_DIR:-$HOME/knowledge}"
JDIR="$VAULT/02 Areas/journal"
TODAY="$(date +%F)"
YEST="$(date -v-1d +%F 2>/dev/null || date -d 'yesterday' +%F)"
DRAFT="$VAULT/99 Meta/promotion-drafts/$TODAY.md"
mkdir -p "$VAULT/99 Meta/promotion-drafts"

# gather recent journal text (cap to keep generation bounded at local speed)
input=""
for d in "$YEST" "$TODAY"; do
  [ -f "$JDIR/$d.md" ] && input="$input

===== journal $d =====
$(cat "$JDIR/$d.md")"
done
input="$(printf '%s' "$input" | tail -c 24000)"

# also surface manually-dropped 00 Inbox items so each gets a proposed PARA target
inbox_list="$(ls -1 "$VAULT/00 Inbox" 2>/dev/null || true)"
[ -n "$inbox_list" ] && input="$input

===== 00 Inbox (untriaged manual drops — propose a PARA target for each filename) =====
$inbox_list"

[ -n "$input" ] || { echo "no recent journal to promote"; exit 0; }

prompt="You maintain a PARA Obsidian vault (folders: 01 Projects, 02 Areas, 03 Resources). From the journal entries below, identify durable, reusable knowledge worth promoting out of the raw journal: decisions, how-tos, project status changes, people/meeting facts. Also propose a PARA target for each file in the '00 Inbox' list, if present. Ignore noise and one-off chatter. Output ONLY markdown (no preamble): for each item a '## <title>', then 'Target:' folder, a 2-3 line summary, and 'Source:' the journal date or '00 Inbox/<filename>'. If nothing is worth promoting, output 'Nothing to promote.'

$input"

# uses the 4-bit E4B (5GB); gen.sh handles guard + on-demand load + timeout + free.
# Generous timeout since promote runs nightly while idle and reads more context.
status "Generating draft — local Gemma (~1–2 min)…"
out="$("$SELF/gen.sh" 480 "$prompt")" || { audit "skipped (busy or timed out)"; status "Skipped — machine busy"; echo "promote skipped — retries tomorrow"; exit 0; }

{
  printf -- '---\ntype: note\ntitle: promotion-draft %s\ntags: [promotion-draft]\ntimestamp: %sT00:00:00Z\n---\n\n# Promotion draft %s\n_Local-Gemma suggestions from journal %s–%s. Review before promoting._\n\n' "$TODAY" "$TODAY" "$TODAY" "$YEST" "$TODAY"
  printf '%s\n' "$out"
} > "$DRAFT"
n=$(printf '%s' "$out" | wc -l | tr -d ' ')
audit "ok: wrote ${n}-line draft -> $DRAFT"
echo "wrote promotion draft -> $DRAFT ($n lines)"

# enrich + AUTO-APPLY: dedupe assigns each item an Action; promote-apply --auto then
# applies the confident items (new notes normalized into concepts/, confident-merge only)
# and holds the uncertain ones in <date>.hold.md for a quick review. No human gate.
if command -v python3 >/dev/null 2>&1; then
  status "Finding duplicates…"
  python3 "$SELF/dedupe.py" "$DRAFT" "$VAULT" --write && audit "ok: dedupe-enriched draft" || audit "dedupe skipped (error)"
  status "Auto-applying…"
  result="$(python3 "$SELF/promote-apply.py" --auto "$DRAFT" "$VAULT" 2>&1)"
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
fi
