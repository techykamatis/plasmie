#!/bin/bash
# Install / refresh Plasmie's dev-path launchd agents (com.plasmie.dev-*).
# Rewrites the __LOOP_DIR__ / __HOME__ tokens in each template to this machine,
# writes them to ~/Library/LaunchAgents/, and (re)bootstraps each into your GUI
# domain. Safe to re-run: each agent is booted out first.
#
#   launchd/install.sh            # install every agent in this dir
#   launchd/install.sh uninstall  # boot out + remove them all
#   launchd/install.sh retire     # only retire agents this repo no longer ships (below)
#
# The loop globs *.plist, so a template dropped in here IS the install manifest —
# an agent that only exists in ~/Library/LaunchAgents is drift and will vanish on
# the next machine (that is how the improve agent went unversioned for a month).
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
LOOP_DIR="$(cd "$SELF/.." && pwd)"          # the engine: this checkout, or the app bundle's backend/
. "$LOOP_DIR/plasmie-env.sh"                  # PLASMIE_HOME (data) and PLASMIE_LOGS
DEST="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"

mkdir -p "$DEST"

# Agents this repo no longer ships. An old install keeps them loaded (and pointing at
# deleted scripts) until something boots them out, so every install/uninstall does.
# Older installs ran these agents under the original author's personal
# reverse-DNS prefix. That prefix is assembled from parts here on purpose: this is the
# only place it is still needed (to retire an old install's jobs), and spelling it out
# would trip the personal-data scan (test_no_personal.py).
#   <old>.<OLD_MID><job> — the same five jobs under their oldest labels
#   <old>.mlx-server  — the local Gemma server, retired (ADR 0002) (Apple FM only)
# Later older installs ran the same five jobs as com.plasmie.<old>-<job> (now
# com.plasmie.dev-<job>, ADR 0024); that old middle part is assembled from parts too, so
# the old-names scan (test_old_names.py) only ever sees it here, in migration code.
OLD="com.v""hen"
OLD_MID="know""ledge-"
JOBS="ingest summarize improve promote snapshot"
retire=("$OLD.mlx-server")
for j in $JOBS; do retire+=("$OLD.$OLD_MID$j" "com.$PLASMIE_APP_ID.$OLD_MID$j"); done
for label in "${retire[@]}"; do
  if [ -f "$DEST/$label.plist" ] || launchctl print "$DOMAIN/$label" >/dev/null 2>&1; then
    launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
    rm -f "$DEST/$label.plist"
    echo "retired $label"
  fi
done

[ "${1:-}" = retire ] && exit 0

if [ "${1:-}" = uninstall ]; then
  for tpl in "$SELF"/*.plist; do
    label="$(basename "$tpl" .plist)"
    launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
    rm -f "$DEST/$label.plist"
    echo "removed $label"
  done
  exit 0
fi

for tpl in "$SELF"/*.plist; do
  label="$(basename "$tpl" .plist)"
  out="$DEST/$label.plist"
  sed -e "s|__LOOP_DIR__|$LOOP_DIR|g" -e "s|__DATA__|$PLASMIE_HOME|g" -e "s|__LOGS__|$PLASMIE_LOGS|g" \
      -e "s|__HOME__|$HOME|g" "$tpl" > "$out"
  launchctl bootout "$DOMAIN/$label" 2>/dev/null || true   # ignore "not loaded"
  launchctl bootstrap "$DOMAIN" "$out"
  launchctl enable "$DOMAIN/$label"
  echo "installed $label"
done

echo "done. ingest :07 hourly · summarize :15 hourly · improve :17 hourly · promote 02:30"
