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
============================

1. Drag "Plasmie" onto the Applications folder (in this window).

2. Open Applications and double-click Plasmie. macOS will say it can't
   check it for malicious software (it isn't from the App Store yet).
   Click "Done".

3. Open System Settings > Privacy & Security, scroll down, and click
   "Open Anyway" next to Plasmie. Confirm with your password.

You only do this once. Plasmie then checks your Mac, shows anything it
needs (with a button for each), and sets itself up. It lives beside the
notch at the top of your screen; press Control-Option-Command-K to ask.

Your notes never leave your Mac.
TXT

rm -f "$DMG"
hdiutil create -volname "Plasmie" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
echo "built: $DMG ($(du -h "$DMG" | cut -f1))"
