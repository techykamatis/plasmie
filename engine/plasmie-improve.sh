#!/bin/bash
# launchd entry for the hourly improve pass (plasmie-improve.py) on Plasmie's own Python.
SELF="$(cd "$(dirname "$0")" && pwd)"
. "$SELF/plasmie-env.sh"
exec "$PY" "$SELF/plasmie-improve.py" "$@"
