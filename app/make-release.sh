#!/bin/bash
# One command from source to a shippable DMG:
#   app/make-release.sh            # gates, build, DMG, SHA-256  (version from ./VERSION)
# Gates (any failure stops the release): full test suite, ruff never above the baseline,
# `bash -n` on every script. Output: app/build/Plasmie-<version>.dmg + .sha256.
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SELF/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
RUFF_BASELINE=29
APP_NAME="Plasmie"                   # matches app/make-app.sh (test_brand.py checks)
PY="$ROOT/.venv/bin/python3"
say() { printf '\n== %s ==\n' "$1"; }

say "$APP_NAME $VERSION: quality gates"
T="$(mktemp -d)"
( cd "$ROOT" && PLASMIE_HOME="$T/home" PLASMIE_LOGS="$T/logs" "$PY" -m pytest -q ) | tail -1
n="$(cd "$ROOT" && { ruff check . 2>/dev/null || true; } | sed -nE 's/^Found ([0-9]+) errors?\./\1/p')"
n="${n:-0}"
[ "$n" -le "$RUFF_BASELINE" ] || { echo "ruff: $n errors > baseline $RUFF_BASELINE"; exit 1; }
echo "ruff: $n (baseline $RUFF_BASELINE)"
for f in "$ROOT"/*.sh "$ROOT"/launchd/*.sh "$SELF"/*.sh; do bash -n "$f"; done
echo "bash -n: ok"
rm -rf "$T"

say "build"
PLASMIE_VERSION="$VERSION" "$SELF/make-app.sh" | tail -3
"$SELF/make-dmg.sh"

say "package"
OUT="$SELF/build/$APP_NAME-$VERSION.dmg"
mv -f "$SELF/build/$APP_NAME.dmg" "$OUT"
( cd "$SELF/build" && shasum -a 256 "$(basename "$OUT")" > "$(basename "$OUT").sha256" )
cat "$OUT.sha256"
echo "release ready: $OUT"
