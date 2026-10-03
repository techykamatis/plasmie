#!/bin/bash
# Sourced by every Plasmie script: where data and logs live, which Python to use, and
# the user's config. The engine (these scripts) is wherever this file sits: the dev
# checkout, or Plasmie.app/Contents/Resources/backend for an installed copy.
#   PLASMIE_HOME  data: config.env, state, venv, models   (~/Library/Application Support/Plasmie)
#   PLASMIE_LOGS  logs: audit, transcripts, launchd.log   (~/Library/Logs/Plasmie)
# Paths contain a space ("Application Support"): always quote them.
: "${PLASMIE_HOME:=$HOME/Library/Application Support/Plasmie}"
: "${PLASMIE_LOGS:=$HOME/Library/Logs/Plasmie}"
export PLASMIE_HOME PLASMIE_LOGS
mkdir -p "$PLASMIE_HOME" "$PLASMIE_LOGS"
PLASMIE_ENGINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Plasmie's own venv (made from the bundled Python); never a Homebrew or system python,
# which a fresh Mac may not have (/usr/bin/python3 is a stub that prompts for Xcode tools).
PY="$PLASMIE_HOME/venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3)"
PLASMIE_CONFIG="$PLASMIE_HOME/config.env"
[ -f "$PLASMIE_CONFIG" ] && . "$PLASMIE_CONFIG"
export PLASMIE_ENGINE PY
