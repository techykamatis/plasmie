#!/bin/bash
# Build Plasmie.app from the single Swift source — no Xcode project needed.
# Compiles with swiftc (CLT), assembles the bundle, ad-hoc signs (personal use).
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
APP="$SELF/build/Plasmie.app"
ARCH="$(uname -m)"

rm -rf "$SELF/build"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

swiftc -O -parse-as-library -target "${ARCH}-apple-macos13.0" \
  -framework SwiftUI -framework AppKit \
  -o "$APP/Contents/MacOS/Plasmie" "$SELF/Plasmie.swift"

# --- bundle the backend so the app can self-install on first run -------------
LOOP="$(cd "$SELF/.." && pwd)"
RES="$APP/Contents/Resources"
say() { printf '%s\n' "$1"; }

# backend scripts + templates (everything the loops need; not the dev cruft).
# Globs are anchored to $LOOP — a bare *.sh would expand against app/ (cwd).
BACKEND="$RES/backend"
mkdir -p "$BACKEND"
shopt -s nullglob
for m in "$LOOP"/*.py "$LOOP"/*.sh "$LOOP"/launchd "$LOOP"/vault-template; do
  cp -R "$m" "$BACKEND/"
done
shopt -u nullglob
rm -f "$BACKEND/test_pipeline.py" "$BACKEND/install.sh"   # dev-only / brew-based
say "bundled backend ($(ls "$BACKEND" | wc -l | tr -d ' ') items)"

# standalone Python 3.12 (bare; mlx-vlm is pip-installed on first run). Cached
# in app/build-cache so rebuilds don't re-download the ~15 MB tarball.
PYVER="3.12.11"; PYTAG="20250612"
# python-build-standalone names arm64 as "aarch64"; uname -m says "arm64".
PYARCH="$([ "$ARCH" = arm64 ] && echo aarch64 || echo "$ARCH")"
PYURL="https://github.com/astral-sh/python-build-standalone/releases/download/${PYTAG}/cpython-${PYVER}+${PYTAG}-${PYARCH}-apple-darwin-install_only.tar.gz"
CACHE="$SELF/build-cache"; mkdir -p "$CACHE"
PYTGZ="$CACHE/python-${PYVER}-${ARCH}.tar.gz"
[ -f "$PYTGZ" ] || { say "downloading standalone Python…"; curl -sL "$PYURL" -o "$PYTGZ"; }
mkdir -p "$RES/pytmp" && tar xzf "$PYTGZ" -C "$RES/pytmp"
mv "$RES/pytmp/python" "$RES/python" && rm -rf "$RES/pytmp"
say "bundled Python $("$RES/python/bin/python3" -V 2>&1 | awk '{print $2}')"

# custom logo -> AppIcon.icns (same glyph as the menu bar, colored)
ICONSET="$SELF/build/AppIcon.iconset"
if swift "$SELF/make-logo.swift" "$ICONSET" && iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"; then
  echo "icon: generated AppIcon.icns"
else
  echo "icon: generation failed — using default"
fi
rm -rf "$ICONSET"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Plasmie</string>
  <key>CFBundleDisplayName</key><string>Plasmie</string>
  <key>CFBundleIdentifier</key><string>com.plasmie.legacy</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Plasmie</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

codesign --force --deep -s - "$APP"
echo "built: $APP"
codesign -dv "$APP" 2>&1 | grep -E "Identifier|Signature" || true
