#!/bin/bash
# One-time data migrations, run by setup (app-setup.sh step 1). Safe to re-run: each
# step is skipped once done, and nothing at a destination is ever overwritten.
#
#  1. Move Plasmie's DATA from the old ~/.plasmie layout to the macOS folders
#     (see plasmie-env.sh). Data only, never code. In a dev checkout (~/.plasmie is
#     a git repo) it leaves a .venv symlink so `.venv/bin/python3 -m pytest` and the
#     venv's own scripts keep working. Old local-model weights (models/) are left where
#     they are: nothing uses them since Apple FM became the only backend (ADR 0025).
#  2. Credentials and connector defaults (below).
set -uo pipefail
. "$(cd "$(dirname "$0")" && pwd)/plasmie-env.sh"
OLD="${PLASMIE_OLD_HOME:-$HOME/.plasmie}"

moved=0
move() {   # move <src> <dest>: only when the source is real and the dest is free
  local src="$1" dest="$2"
  [ -e "$src" ] && [ ! -L "$src" ] && [ ! -e "$dest" ] || return 0
  mkdir -p "$(dirname "$dest")"
  mv "$src" "$dest" && moved=$((moved + 1)) && echo "moved $(basename "$src") -> $dest"
}

if [ -d "$OLD" ]; then
  for f in config.env .loop-state.json .status feed.log .achievements.json .funfacts.json \
           .patterns.json .embed-cache.json; do
    move "$OLD/$f" "$PLASMIE_HOME/$f"
  done
  move "$OLD/.venv" "$PLASMIE_HOME/venv"
  move "$OLD/launchd.log" "$PLASMIE_LOGS/launchd.log"
  if [ -d "$OLD/logs" ] && [ ! -L "$OLD/logs" ]; then
    for f in "$OLD/logs"/* "$OLD/logs"/.[!.]*; do
      [ -e "$f" ] && move "$f" "$PLASMIE_LOGS/$(basename "$f")"
    done
    rmdir "$OLD/logs" 2>/dev/null || true
  fi
  if [ -d "$OLD/.git" ]; then          # dev checkout: keep the old names working
    [ -e "$OLD/.venv" ] || ln -s "$PLASMIE_HOME/venv" "$OLD/.venv"
  fi
  echo "migrated $moved item(s) to $PLASMIE_HOME"
fi

# --- 2. credentials, and connector defaults -----------------------------------
# An install that has run before (it has ingest state) keeps every switch and value:
# its ~/.claude/.env credentials move into the Keychain once (keychain.py; the jobs
# also run it lazily, so an install that never re-runs setup migrates too).
# A fresh install imports nothing from ~/.claude/.env (it may belong to other tools)
# and starts with every network connector Off; local sources start On only when
# their folder exists. The user switches the rest on in Settings.
MARKER="$PLASMIE_HOME/.secrets-migrated"
VENV_PY="$PLASMIE_HOME/venv/bin/python3"
if [ -f "$PLASMIE_HOME/.loop-state.json" ]; then
  if [ ! -f "$MARKER" ] && [ -x "$VENV_PY" ]; then
    "$VENV_PY" "$PLASMIE_ENGINE/keychain.py" migrate || echo "secrets: migration incomplete; the jobs retry it"
  fi
elif ! grep -q '^PLASMIE_DISABLED_SOURCES=' "$PLASMIE_CONFIG" 2>/dev/null; then
  off="slack,github,confluence,outlook"
  [ -d "$HOME/.claude/projects" ] || off="$off,claude"
  roots=""
  if xcode-select -p >/dev/null 2>&1; then     # no developer tools = /usr/bin/git is a stub
    for d in code Developer src Projects dev repos git workspace GitHub Documents/GitHub; do
      for g in "$HOME/$d"/*/.git; do
        [ -e "$g" ] && { roots="${roots:+$roots,}~/$d"; break; }
      done
    done
  fi
  if grep -q '^PLASMIE_GIT_ROOTS=' "$PLASMIE_CONFIG" 2>/dev/null; then :
  elif [ -n "$roots" ]; then printf 'PLASMIE_GIT_ROOTS="%s"\n' "$roots" >> "$PLASMIE_CONFIG"
  else off="$off,git"; fi
  printf 'PLASMIE_DISABLED_SOURCES="%s"\n' "$off" >> "$PLASMIE_CONFIG"
  : > "$MARKER"                     # nothing to migrate on a fresh install, ever
  echo "fresh install: off by default: $off${roots:+ · git folders: $roots}"
fi
exit 0
