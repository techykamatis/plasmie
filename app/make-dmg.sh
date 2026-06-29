#!/bin/bash
# Package Plasmie.app into a drag-to-Applications DMG (hdiutil, built-in).
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
APP="$SELF/build/Plasmie.app"
DMG="$SELF/build/Plasmie.dmg"
[ -d "$APP" ] || { echo "build the app first: ./make-app.sh"; exit 1; }

STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

# This build is unsigned (no Apple Developer account), so the first launch hits
# Gatekeeper. Spell out the one-time right-click → Open workaround in the DMG.
cat > "$STAGE/HOW TO OPEN (first time).txt" <<'TXT'
Opening Plasmie the first time
=====================================

1. Drag "Plasmie" onto the Applications folder (in this window).

2. Open the Applications folder, then RIGHT-CLICK "Plasmie"
   and choose "Open". (Double-clicking the first time will be blocked.)

3. A box says it's from an unidentified developer — click "Open".

You only do this once. After that it opens normally, and a small brain
icon appears in your menu bar at the top of the screen.

If you don't see an "Open" option: open System Settings ▸ Privacy &
Security, scroll down, and click "Open Anyway" next to Plasmie.
TXT

rm -f "$DMG"
hdiutil create -volname "Plasmie" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
echo "built: $DMG ($(du -h "$DMG" | cut -f1))"
