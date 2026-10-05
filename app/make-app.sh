#!/bin/bash
# Build Plasmie.app from the Swift sources — no Xcode project needed.
# Compiles with swiftc (CLT), assembles the bundle, ad-hoc signs (personal use).
# Also builds plasmie-fm (app/build-fm.sh), the bridge to Apple's on-device model,
# into Contents/MacOS: building needs the macOS 26+ SDK, running needs nothing.
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
# The name, in one place for the build (ADR 0028); must match Brand.swift, paths.APP_NAME and
# PLASMIE_APP_NAME in plasmie-env.sh (test_brand.py checks).
APP_NAME="Plasmie"
APP_ID="plasmie"
BUNDLE_ID="com.$APP_ID.app"
FM_NAME="$APP_ID-fm"
VERSION="${PLASMIE_VERSION:-$(tr -d '[:space:]' < "$SELF/../VERSION" 2>/dev/null || echo 0.0.0)}"
BUILD_NO="$(git -C "$SELF/.." rev-list --count HEAD 2>/dev/null || echo 1)"   # monotonic build number
APP="$SELF/build/$APP_NAME.app"
ARCH="$(uname -m)"

# ponytail: rename first (atomic): Finder can drop a .DS_Store in mid-delete and fail "rm -rf"
if [ -e "$SELF/build" ]; then mv "$SELF/build" "$SELF/build.old.$$" && rm -rf "$SELF/build.old.$$" || true; fi
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

swiftc -O -parse-as-library -target "${ARCH}-apple-macos13.0" \
  -framework SwiftUI -framework AppKit \
  -o "$APP/Contents/MacOS/$APP_NAME" "$SELF"/Sources/*.swift

# the on-device model bridge (fm.py finds it at ../../MacOS/plasmie-fm from backend/)
"$SELF/build-fm.sh" "$APP/Contents/MacOS/$FM_NAME"

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
rm -f "$BACKEND"/test_*.py "$BACKEND/conftest.py" "$BACKEND/install.sh"   # dev-only / brew-based
say "bundled backend ($(ls "$BACKEND" | wc -l | tr -d ' ') items)"
# the friend docs ship inside the app too (Plasmie window > Help), read in Plasmie's own reader
mkdir -p "$RES/docs"
cp "$LOOP/docs/QUICKSTART.md" "$RES/docs/Quickstart.md"
cp "$LOOP/docs/PRIVACY.md" "$RES/docs/Privacy.md"

# background jobs, owned by the app: registered with SMAppService.agent at launch (Login
# Items lists them; they go away with the app). They run the bundled engine in place and
# log themselves (PLASMIE_JOB_LOG; a bundled plist can't name a path in the user's home).
LA="$APP/Contents/Library/LaunchAgents"; mkdir -p "$LA"
job() {   # job <name> <script> <max minutes> <StartCalendarInterval dict body>
  cat > "$LA/com.$APP_ID.$1.plist" <<JOB
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.$APP_ID.$1</string>
  <key>BundleProgram</key><string>Contents/Resources/backend/plasmie-job.sh</string>
  <key>ProgramArguments</key><array><string>plasmie-job.sh</string><string>$3</string><string>$2</string></array>
  <key>StartCalendarInterval</key><dict>$4</dict>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>PLASMIE_JOB_LOG</key><string>$1.log</string>
  </dict>
  <key>ProcessType</key><string>Background</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
JOB
}
# hard time limits (plasmie-job.sh): a wedged job is stopped, never left hanging
job ingest    run-ingest.sh  50  "<key>Minute</key><integer>7</integer>"
job summarize summarize.sh   30  "<key>Minute</key><integer>15</integer>"
job improve   plasmie-improve.sh  30  "<key>Minute</key><integer>17</integer>"
job promote   promote.sh     120 "<key>Hour</key><integer>2</integer><key>Minute</key><integer>30</integer>"
job snapshot  plasmie-snapshot.sh 20  "<key>Hour</key><integer>0</integer><key>Minute</key><integer>47</integer>"
for f in "$LA"/*.plist; do plutil -lint -s "$f" || { echo "bad plist $f"; exit 1; }; done
chmod +x "$BACKEND"/*.sh
say "bundled $(ls "$LA" | wc -l | tr -d ' ') background jobs"

# standalone Python 3.12 (bare: the engine is stdlib-only, nothing is pip-installed). Cached
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

# standalone Node 22 LTS for vault search (qmd is a Node CLI): pinned, checksum-verified
# against nodejs.org's SHASUMS256, cached. Setup installs qmd with it into
# $PLASMIE_HOME/qmd, so a friend needs no Node install (prebuilt binaries, no compiler).
NODEVER="v22.23.3"; NODEARCH="$([ "$ARCH" = arm64 ] && echo arm64 || echo x64)"
NODENAME="node-${NODEVER}-darwin-${NODEARCH}"
NODETGZ="$CACHE/${NODENAME}.tar.gz"
if [ ! -f "$NODETGZ" ]; then
  say "downloading Node ${NODEVER}…"
  curl -fsSL "https://nodejs.org/dist/${NODEVER}/${NODENAME}.tar.gz" -o "$NODETGZ.part"
  want="$(curl -fsSL "https://nodejs.org/dist/${NODEVER}/SHASUMS256.txt" | awk -v f="${NODENAME}.tar.gz" '$2==f{print $1}')"
  got="$(shasum -a 256 "$NODETGZ.part" | awk '{print $1}')"
  [ -n "$want" ] && [ "$want" = "$got" ] || { rm -f "$NODETGZ.part"; echo "Node checksum mismatch"; exit 1; }
  mv "$NODETGZ.part" "$NODETGZ"
fi
mkdir -p "$RES/nodetmp" && tar xzf "$NODETGZ" -C "$RES/nodetmp"
mv "$RES/nodetmp/$NODENAME" "$RES/node" && rm -rf "$RES/nodetmp"
rm -rf "$RES/node/include" "$RES/node/share" "$RES/node"/*.md "$RES/node/LICENSE"   # headers + docs: not needed to run
say "bundled Node $("$RES/node/bin/node" -v)"
say "bundled Python $("$RES/python/bin/python3" -V 2>&1 | awk '{print $2}')"

# Plasmie (idle pose, coloured) -> AppIcon.icns; uses the app's own PlasmieShapes anchors
ICONSET="$SELF/build/AppIcon.iconset"
LOGOBIN="$SELF/build/make-logo"
if swiftc -parse-as-library -o "$LOGOBIN" "$SELF/make-logo.swift" "$SELF/Sources/PlasmieShapes.swift" \
   && "$LOGOBIN" "$ICONSET" && iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"; then
  echo "icon: generated AppIcon.icns"
else
  echo "icon: generation failed — using default"
fi
rm -rf "$ICONSET" "$LOGOBIN"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>${APP_NAME}</string>
  <key>CFBundleDisplayName</key><string>${APP_NAME}</string>
  <key>CFBundleIdentifier</key><string>${BUNDLE_ID}</string>
  <key>CFBundleVersion</key><string>${BUILD_NO}</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>${APP_NAME}</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

codesign --force --deep -s - "$APP"
echo "built: $APP"
codesign -dv "$APP" 2>&1 | grep -E "Identifier|Signature" || true
