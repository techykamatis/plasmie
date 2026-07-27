#!/bin/bash
# Capture a thought into the vault by hand.
#
#   plasmie-capture.sh "postgres connection pool is the dev 504 culprit"
#   pbpaste | plasmie-capture.sh
#   plasmie-capture.sh -t "pool sizing" "long note text here"
#
# Writes raw/inbox/<date>-<slug>.md. The nightly promote pass reads raw/inbox,
# proposes a wiki target, and files it — so this is the manual on-ramp to the
# same pipeline Slack/GitHub/Claude activity already flows through.
#
# Everything else in this repo writes through scrub.py; so does this, because
# raw/ is indexed by qmd and a pasted token would otherwise get embedded.
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
[ -f "$SELF/config.env" ] && . "$SELF/config.env"
VAULT="${PLASMIE_VAULT:-${VAULT_DIR:-$HOME/knowledge}}"

title=""
if [ "${1:-}" = "-t" ]; then
  title="${2:-}"; shift 2
fi

text="$*"
[ -n "$text" ] || text="$(cat)"          # no args -> read stdin
text="${text#"${text%%[![:space:]]*}"}"  # trim leading whitespace
[ -n "${text// /}" ] || { echo "nothing to capture (pass text as args or on stdin)" >&2; exit 1; }

# Redact FIRST. The title, slug and filename are all derived from the text, so
# redacting only the body would still leak a pasted key into the filename — and a
# filename is the one thing that shows up in listings, promote drafts and git.
clean="$(printf '%s' "$text" | PLASMIE_SELF="$SELF" /usr/bin/python3 -c \
  'import sys,os; sys.path.insert(0,os.environ["PLASMIE_SELF"]); from scrub import redact; print(redact(sys.stdin.read()), end="")' )" \
  || clean="$text"
[ -n "$title" ] && title="$(printf '%s' "$title" | PLASMIE_SELF="$SELF" /usr/bin/python3 -c \
  'import sys,os; sys.path.insert(0,os.environ["PLASMIE_SELF"]); from scrub import redact; print(redact(sys.stdin.read()), end="")' )"

[ -n "$title" ] || title="$(printf '%s' "$clean" | head -1 | cut -c1-60)"

DEST="$VAULT/raw/inbox"
mkdir -p "$DEST"
slug="$(printf '%s' "$title" | tr '[:upper:]' '[:lower:]' \
        | sed -e 's/[^a-z0-9]\{1,\}/-/g' -e 's/^-//' -e 's/-$//' | cut -c1-50)"
[ -n "$slug" ] || slug="note"
stamp="$(date +%Y-%m-%d-%H%M%S)"
FILE="$DEST/$stamp-$slug.md"

{
  printf -- '---\ntype: capture\nsource: inbox\ntitle: %s\ntags: [raw, capture]\ntimestamp: %sZ\n---\n\n# %s\n\n%s\n' \
    "$title" "$(date -u +%Y-%m-%dT%H:%M:%S)" "$title" "$clean"
} > "$FILE"

echo "captured -> ${FILE#"$VAULT"/}"
