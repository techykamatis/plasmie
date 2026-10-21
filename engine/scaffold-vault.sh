#!/bin/bash
# Scaffold a fresh knowledge vault (raw/wiki/archive/meta) from the bundled template.
# Never overwrites an existing, non-empty vault.
# Usage: scaffold-vault.sh [DEST]   (default: ~/knowledge)
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
TPL="$SELF/vault-template"
DEST="${1:-$HOME/knowledge}"

[ -d "$TPL" ] || { echo "template missing: $TPL"; exit 1; }
if [ -e "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null)" ]; then
  echo "vault already exists and is non-empty: $DEST — refusing to overwrite"
  exit 0
fi

mkdir -p "$DEST"
cp -R "$TPL/." "$DEST/"
find "$DEST" -name .gitkeep -delete   # placeholders only needed to keep empty dirs in git

echo "✓ scaffolded vault → $DEST"
echo "  next: in Obsidian, 'Open folder as vault' → $DEST,"
echo "        then run launchd/install.sh to start the ingest/promote loops."
