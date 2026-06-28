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
rm -f "$DMG"
hdiutil create -volname "Plasmie" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
echo "built: $DMG ($(du -h "$DMG" | cut -f1))"
