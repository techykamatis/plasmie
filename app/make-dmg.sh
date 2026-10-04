#!/bin/bash
# Package Plasmie.app into a drag-to-Applications DMG (hdiutil, built-in).
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Plasmie"                   # matches app/make-app.sh (test_brand.py checks)
APP="$SELF/build/$APP_NAME.app"
DMG="$SELF/build/$APP_NAME.dmg"
[ -d "$APP" ] || { echo "build the app first: ./make-app.sh"; exit 1; }

STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

# Plain .txt, not .md: double-clicking a .md on a Mac opens a code editor or nothing
# useful, while .txt opens in TextEdit and previews with the space bar. The docs are
# light Markdown, so they read fine as text.
REPO="$(cd "$SELF/.." && pwd)"
cp "$REPO/docs/QUICKSTART.md" "$STAGE/Quickstart.txt"
cp "$REPO/docs/PRIVACY.md"    "$STAGE/Privacy.txt"

# This build is unsigned (no Apple Developer account), so the first launch hits
# Gatekeeper. Spell out the one-time right-click → Open workaround in the DMG.
cat > "$STAGE/HOW TO OPEN (first time).txt" <<TXT
Opening $APP_NAME the first time
===============================

1. Drag "$APP_NAME" onto the Applications folder (in this window).

2. Open Applications and double-click $APP_NAME. macOS will say it can't
   check it for malicious software (it isn't from the App Store yet).
   Click "Done".

3. Open System Settings > Privacy & Security, scroll down, and click
   "Open Anyway" next to $APP_NAME. Confirm with your password.

You only do this once. $APP_NAME then checks your Mac, shows anything it
needs (with a button for each), and sets itself up. It lives beside the
notch at the top of your screen; press Control-Option-Command-K to ask.

Your notes never leave your Mac.

More in this window: Quickstart.txt (setup, daily use, uninstall) and
Privacy.txt (what $APP_NAME reads and where it goes).
TXT

rm -f "$DMG"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
echo "built: $DMG ($(du -h "$DMG" | cut -f1))"
