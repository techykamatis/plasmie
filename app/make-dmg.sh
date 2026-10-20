#!/bin/bash
# Package Plasmie.app into a drag-to-Applications DMG (hdiutil + Finder, both built in).
# The window shows the app, an arrow, the Applications folder, and the first-time steps in
# plain English, drawn into the background by make-dmg-background.swift.
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Plasmie"                   # matches app/make-app.sh (test_brand.py checks)
APP="$SELF/build/$APP_NAME.app"
DMG="$SELF/build/$APP_NAME.dmg"
[ -d "$APP" ] || { echo "build the app first: ./make-app.sh"; exit 1; }

# Window layout. Must match the constants in make-dmg-background.swift.
WIN_W=840; WIN_H=470; TITLEBAR=28
ICON_SIZE=96

WORK="$(mktemp -d)"
STAGE="$WORK/stage"; MNT="$WORK/mnt"; RW="$WORK/rw.dmg"
cleanup() { hdiutil detach "$MNT" -quiet -force 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT
mkdir -p "$STAGE/.background" "$MNT"

# Background: 1x and 2x joined into one TIFF so Retina screens get the sharp one.
swiftc -o "$WORK/make-dmg-background" "$SELF/make-dmg-background.swift"
"$WORK/make-dmg-background" "$WORK" "$APP_NAME"
tiffutil -cathidpicheck "$WORK/bg.png" "$WORK/bg@2x.png" -out "$STAGE/.background/background.tiff" 2>/dev/null

cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
# Step 3 shortcut. A link straight to the Privacy & Security page is refused by macOS when
# opened from a file, so this opens System Settings and the steps say where to click.
ln -s "/System/Applications/System Settings.app" "$STAGE/System Settings"

# Plain .txt, not .md: double-clicking a .md on a Mac opens a code editor or nothing
# useful, while .txt opens in TextEdit and previews with the space bar. The docs are
# light Markdown, so they read fine as text. The install steps live in the background.
REPO="$(cd "$SELF/.." && pwd)"
cp "$REPO/docs/QUICKSTART.md" "$STAGE/Quickstart.txt"
cp "$REPO/docs/PRIVACY.md"    "$STAGE/Privacy.txt"
SetFile -a E "$STAGE/Quickstart.txt" "$STAGE/Privacy.txt"   # hide extensions

# Build read-write, lay out the window in Finder, then compress.
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -fs HFS+ -format UDRW -ov "$RW" >/dev/null
hdiutil detach "/Volumes/$APP_NAME" -quiet -force 2>/dev/null || true   # an older copy would clash by name
hdiutil attach "$RW" -mountpoint "/Volumes/$APP_NAME" -noautoopen -quiet
MNT="/Volumes/$APP_NAME"
# Finder learns about a new disk a moment after it mounts; wait rather than race it.
for _ in $(seq 20); do
  osascript -e "tell application \"Finder\" to exists disk \"$APP_NAME\"" 2>/dev/null | grep -q true && break
  sleep 0.5
done

# Finder writes the layout into the volume's .DS_Store. Needs Automation access to
# Finder for whatever runs this (Terminal, etc.); macOS asks the first time.
layout() {
  osascript <<OSA
tell application "Finder"
  tell disk "$APP_NAME"
    open
    set w to container window
    set current view of w to icon view
    set toolbar visible of w to false
    set statusbar visible of w to false
    set the bounds of w to {200, 120, 200 + $WIN_W, 120 + $WIN_H + $TITLEBAR}
    set opts to the icon view options of w
    set arrangement of opts to not arranged
    set icon size of opts to $ICON_SIZE
    set text size of opts to 13
    set background picture of opts to file ".background:background.tiff"
    set position of item "$APP_NAME.app" of w to {270, 160}
    set position of item "Applications" of w to {570, 160}
    set position of item "System Settings" of w to {560, 380}
    set position of item "Quickstart.txt" of w to {680, 380}
    set position of item "Privacy.txt" of w to {785, 380}
    close
    open
    update without registering applications
    delay 1
    close
  end tell
end tell
OSA
}

# Finder saves the layout to the volume's .DS_Store lazily, and sometimes keeps the icon
# positions but drops the background and icon size. Check what it actually wrote, and retry.
layout_saved() {
  python3 -I - "$MNT/.DS_Store" "$ICON_SIZE" <<'PY'
import plistlib, re, sys
try:
    d = open(sys.argv[1], "rb").read()
except OSError:
    sys.exit(1)
i = d.find(b"icvp")
m = re.search(rb"bplist00", d[i:]) if i >= 0 else None
if not m:
    sys.exit(1)
s = d[i + m.start():]
for n in range(40, len(s) + 1):
    try:
        p = plistlib.loads(s[:n])
        break
    except Exception:
        continue
else:
    sys.exit(1)
sys.exit(0 if p.get("backgroundType") == 2 and p.get("iconSize") == float(sys.argv[2]) else 1)
PY
}

ok=0
for attempt in 1 2 3 4; do
  layout || { echo "could not lay out the DMG window in Finder (if macOS asked, allow Automation > Finder for your terminal)"; exit 1; }
  for _ in $(seq 20); do layout_saved && { ok=1; break; }; sleep 0.5; done
  [ "$ok" = 1 ] && break
  echo "Finder didn't save the window layout (try $attempt), trying again"
done
[ "$ok" = 1 ] || { echo "Finder never saved the window layout; not building a DMG without it"; exit 1; }

chmod -Rf go-w "$MNT" 2>/dev/null || true
sync
hdiutil detach "$MNT" -quiet || { sleep 2; hdiutil detach "$MNT" -quiet -force; }

rm -f "$DMG"
hdiutil convert "$RW" -format UDZO -imagekey zlib-level=9 -o "$DMG" >/dev/null
echo "built: $DMG ($(du -h "$DMG" | cut -f1))"
