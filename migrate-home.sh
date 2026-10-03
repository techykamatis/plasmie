#!/bin/bash
# One-time move of Plasmie's DATA from the old ~/.plasmie layout to the macOS
# folders (see plasmie-env.sh). Moves data only, never code; never overwrites anything
# already at the destination; safe to re-run (each item is skipped once moved).
#
# In a dev checkout (~/.plasmie is a git repo) it leaves symlinks for .venv and
# models/ so `.venv/bin/python3 -m pytest` and the venv's own scripts keep working.
set -uo pipefail
. "$(cd "$(dirname "$0")" && pwd)/plasmie-env.sh"
OLD="${PLASMIE_OLD_HOME:-$HOME/.plasmie}"
[ -d "$OLD" ] || exit 0

moved=0
move() {   # move <src> <dest>: only when the source is real and the dest is free
  local src="$1" dest="$2"
  [ -e "$src" ] && [ ! -L "$src" ] && [ ! -e "$dest" ] || return 0
  mkdir -p "$(dirname "$dest")"
  mv "$src" "$dest" && moved=$((moved + 1)) && echo "moved $(basename "$src") -> $dest"
}

for f in config.env .loop-state.json .status feed.log .achievements.json .funfacts.json \
         .patterns.json .embed-cache.json; do
  move "$OLD/$f" "$PLASMIE_HOME/$f"
done
move "$OLD/.venv" "$PLASMIE_HOME/venv"
move "$OLD/models" "$PLASMIE_HOME/models"
move "$OLD/launchd.log" "$PLASMIE_LOGS/launchd.log"
if [ -d "$OLD/logs" ] && [ ! -L "$OLD/logs" ]; then
  for f in "$OLD/logs"/* "$OLD/logs"/.[!.]*; do
    [ -e "$f" ] && move "$f" "$PLASMIE_LOGS/$(basename "$f")"
  done
  rmdir "$OLD/logs" 2>/dev/null || true
fi

if [ -d "$OLD/.git" ]; then          # dev checkout: keep the old names working
  [ -e "$OLD/.venv" ] || ln -s "$PLASMIE_HOME/venv" "$OLD/.venv"
  [ -e "$OLD/models" ] || ln -s "$PLASMIE_HOME/models" "$OLD/models"
fi
echo "migrated $moved item(s) to $PLASMIE_HOME"
