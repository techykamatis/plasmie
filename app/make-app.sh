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
