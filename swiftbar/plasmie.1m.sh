#!/bin/bash
# <xbar.title>Plasmie</xbar.title>
# <xbar.version>v0</xbar.version>
# <xbar.author>vhen</xbar.author>
# <xbar.desc>Cockpit + review gate for the local plasmie promote pipeline.</xbar.desc>
# <xbar.dependencies>bash,python3</xbar.dependencies>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>false</swiftbar.hideRunInTerminal>
#
# A thin menu-bar front-end over the existing scripts — it runs nothing itself,
# just reads state (drafts, feed.log, audit, index count) and shells out to
# promote.sh / promote-apply.py / reindex.py. Filename interval = 1 min refresh.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
PY="$(command -v python3.12 || command -v python3)"
LOOP="$HOME/.plasmie"
VAULT="$HOME/knowledge"
DRAFTS="$VAULT/99 Meta/promotion-drafts"
UID_="$(id -u)"

# ---- gather state ----
pending=0; pending_file=""
if [ -d "$DRAFTS" ]; then
  while IFS= read -r f; do
    grep -q "✅" "$f" 2>/dev/null || { pending=$((pending + 1)); [ -z "$pending_file" ] && pending_file="$f"; }
  done < <(find "$DRAFTS" -name '*.md' 2>/dev/null | sort -r)
fi
pending_items=0
[ -n "$pending_file" ] && pending_items=$(grep -c '^## ' "$pending_file" 2>/dev/null)

running=""; pgrep -f "promote.sh|run-ingest.sh|gen.sh|loop-ingest.py" >/dev/null 2>&1 && running=1
notes=$(grep -ho '[0-9]\{1,\} atomic notes' "$VAULT/index.md" 2>/dev/null | grep -o '[0-9]\{1,\}'); [ -z "$notes" ] && notes="?"
last_feed=$(grep -v '^$' "$LOOP/feed.log" 2>/dev/null | tail -1)
audit="$LOOP/logs/audit-$(date +%F).log"
last_promote=$(grep ' promote ' "$audit" 2>/dev/null | tail -1)
journal="$VAULT/02 Areas/journal/$(date +%F).md"

# ---- menu-bar title (state-driven) ----
if [ -n "$running" ]; then
  echo "🧠 ◐ | color=#888888"
elif [ "$pending" -gt 0 ]; then
  echo "🧠 $pending | color=orange"
elif echo "$last_promote" | grep -q skipped; then
  echo "🧠 ⚠ | color=red"
else
  echo "🧠"
fi
echo "---"

state="healthy"; [ "$pending" -gt 0 ] && state="$pending draft(s) to review"; [ -n "$running" ] && state="working…"
echo "Plasmie · $state | color=gray"
echo "---"

# ---- the review gate (only when something is pending) ----
if [ "$pending" -gt 0 ] && [ -n "$pending_file" ]; then
  base="$(basename "$pending_file")"
  echo "📥 Review: $base ($pending_items items) | color=orange size=13"
  echo "Open draft in editor | bash=open param1=\"$pending_file\" terminal=false"
  echo "Preview apply (dry-run) | bash=$PY param1=$LOOP/promote-apply.py param2=\"$pending_file\" terminal=true"
  echo "✅ Apply reviewed → vault | bash=$PY param1=$LOOP/promote-apply.py param2=\"$pending_file\" param3=--apply terminal=true refresh=true color=orange"
  echo "---"
fi

# ---- today ----
echo "Today | color=gray"
echo "$notes notes in vault | bash=$PY param1=$LOOP/reindex.py param2=--check param3=$VAULT terminal=true"
[ -n "$last_feed" ] && echo "${last_feed//|/·} | color=gray size=11"
echo "---"

# ---- recent activity ----
echo "Recent | color=gray"
grep -v '^$' "$LOOP/feed.log" 2>/dev/null | tail -3 | tail -r | while IFS= read -r line; do
  echo "${line//|/·} | color=gray size=11 font=Menlo"
done
echo "---"

# ---- actions ----
echo "⚙ Run promote now | bash=/bin/launchctl param1=kickstart param2=-p param3=gui/$UID_/com.plasmie.dev-promote terminal=false refresh=true"
echo "⟳ Run ingest now | bash=/bin/launchctl param1=kickstart param2=-p param3=gui/$UID_/com.plasmie.dev-ingest terminal=false refresh=true"
echo "📂 Open vault | bash=open param1=$VAULT terminal=false"
[ -f "$journal" ] && echo "📓 Open today's journal | bash=open param1=\"$journal\" terminal=false"
echo "---"

# ---- health (submenu) ----
echo "Health | color=gray"
if [ -n "$last_promote" ]; then
  echo "--last promote: ${last_promote##*| } | color=gray"
fi
echo "--.env: ⚠ plaintext secrets (known) | color=red"
echo "--Reindex check… | bash=$PY param1=$LOOP/reindex.py param2=--check param3=$VAULT terminal=true"
echo "Refresh | refresh=true"
