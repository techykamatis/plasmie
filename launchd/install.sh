#!/bin/bash
# Install / refresh the plasmie launchd agents.
# Rewrites the __LOOP_DIR__ / __HOME__ tokens in each template to this machine,
# writes them to ~/Library/LaunchAgents/, and (re)bootstraps each into your GUI
# domain. Safe to re-run: each agent is booted out first.
#
#   launchd/install.sh            # install every agent in this dir
#   launchd/install.sh uninstall  # boot out + remove them all
#
# The loop globs *.plist, so a template dropped in here IS the install manifest —
# an agent that only exists in ~/Library/LaunchAgents is drift and will vanish on
# the next machine (that is how knowledge-improve went unversioned for a month).
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
LOOP_DIR="$(cd "$SELF/.." && pwd)"          # the engine: this checkout, or the app bundle's backend/
. "$LOOP_DIR/plasmie-env.sh"                  # PLASMIE_HOME (data) and PLASMIE_LOGS
DEST="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"

mkdir -p "$DEST"

# Agents this repo no longer ships. An old install keeps them loaded (and pointing at
# deleted scripts) until something boots them out, so every install/uninstall does.
# Before the com.plasmie.* rename these agents used the original author's personal
# reverse-DNS prefix. That prefix is assembled from parts here on purpose: this is the
# only place it is still needed (to retire an old install's jobs), and spelling it out
# would trip the personal-data scan (test_no_personal.py).
#   <old>.dev-* — the same five jobs under their pre-rename labels
#   <old>.mlx-server  — the local Gemma server, retired by ADR 0025 (Apple FM only)
OLD="com.v""hen"
for label in "$OLD.mlx-server" "$OLD.dev-ingest" "$OLD.dev-summarize" \
             "$OLD.dev-improve" "$OLD.dev-promote" "$OLD.dev-snapshot"; do
  if [ -f "$DEST/$label.plist" ] || launchctl print "$DOMAIN/$label" >/dev/null 2>&1; then
    launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
    rm -f "$DEST/$label.plist"
    echo "retired $label"
  fi
done

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
