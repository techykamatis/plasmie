#!/bin/bash
# Build plasmie-fm, the native bridge to Apple's on-device model (see app/fm/main.swift).
#   app/build-fm.sh [OUT]     default OUT: app/build/plasmie-fm
# Needs the macOS 26+ SDK at BUILD time only (this Mac's Xcode or CommandLineTools);
# the binary itself runs on any Mac and reports "unsupportedOS" below macOS 26.
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$SELF/build/plasmie-fm}"
ARCH="$(uname -m)"
SDK="$(xcrun --sdk macosx --show-sdk-path)"
[ -d "$SDK/System/Library/Frameworks/FoundationModels.framework" ] \
  || { echo "build-fm: this SDK has no FoundationModels (needs the macOS 26+ SDK): $SDK" >&2; exit 1; }
mkdir -p "$(dirname "$OUT")"
# Deployment target 13.0 (same as the app) + weak-linked framework: the helper loads
# everywhere and answers unsupportedOS instead of failing in dyld on older macOS.
swiftc -O -parse-as-library -swift-version 5 -target "${ARCH}-apple-macos13.0" -sdk "$SDK" \
  -Xlinker -weak_framework -Xlinker FoundationModels \
  -o "$OUT" "$SELF/fm/main.swift"
echo "built: $OUT"
