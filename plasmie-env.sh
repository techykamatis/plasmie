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
# Background jobs registered by the app (SMAppService) can't name a log file in their
# plist (no home folder there), so they pass PLASMIE_JOB_LOG and the script logs itself,
# once (nested scripts that source this again don't re-redirect).
if [ -n "${PLASMIE_JOB_LOG:-}" ] && [ -z "${PLASMIE_LOGGING:-}" ]; then
  export PLASMIE_LOGGING=1
  exec >>"$PLASMIE_LOGS/$PLASMIE_JOB_LOG" 2>&1
fi
PLASMIE_ENGINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Plasmie's own venv (made from the bundled Python); never a Homebrew or system python,
# which a fresh Mac may not have (/usr/bin/python3 is a stub that prompts for Xcode tools).
PY="$PLASMIE_HOME/venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3)"
PLASMIE_CONFIG="$PLASMIE_HOME/config.env"
[ -f "$PLASMIE_CONFIG" ] && . "$PLASMIE_CONFIG"
export PLASMIE_ENGINE PY
# Search (qmd, a Node CLI): Plasmie's own copy in $PLASMIE_HOME/qmd, run by the Node that ships
# inside Plasmie.app (Resources/node), so a friend needs no Node install. qmd's
# `#!/usr/bin/env node` shebang means node must be on PATH, not just qmd. A dev checkout
# without either falls back to whatever qmd is installed.
PLASMIE_NODE_BIN="$PLASMIE_ENGINE/../node/bin"
# Only when a Node is actually reachable: a dev checkout run by launchd has neither the
# bundled Node beside it nor node on PATH, and then keeps using the installed qmd.
if [ -x "$PLASMIE_HOME/qmd/bin/qmd" ] && [ -x "$PLASMIE_NODE_BIN/node" ]; then
  PATH="$PLASMIE_NODE_BIN:$PLASMIE_HOME/qmd/bin:$PATH"
  export PLASMIE_QMD="$PLASMIE_HOME/qmd/bin/qmd" PATH
fi

# Connector credentials live in the login Keychain (service "Plasmie", account = the
# variable name), never in a file. Mirrors keychain.SECRETS / Keychain.secrets.
PLASMIE_SECRETS="SLACK_USER_TOKEN JIRA_API_TOKEN CONFLUENCE_API_TOKEN MS_REFRESH_TOKEN JIRA_EMAIL CONFLUENCE_EMAIL GITHUB_TOKEN"
# plasmie_secrets: export the stored ones, for the jobs that call a connector (not every
# script gets them). Missing ones are skipped quietly; an already-set variable wins.
# PLASMIE_KEYCHAIN=<file> reads another keychain instead of the login one (tests).
plasmie_secrets() {
  local k v
  # a PLASMIE_KEYCHAIN that doesn't exist would silently mean the login keychain
  [ -n "${PLASMIE_KEYCHAIN:-}" ] && [ ! -f "$PLASMIE_KEYCHAIN" ] && return 0
  for k in $PLASMIE_SECRETS; do
    [ -n "${!k:-}" ] && continue
    # perl's alarm = a 10 s cap (macOS has no `timeout`): a keychain prompt nobody can
    # answer must never hang a background job
    v="$(/usr/bin/perl -e 'alarm 10; exec @ARGV' /usr/bin/security find-generic-password -s Plasmie -a "$k" -w ${PLASMIE_KEYCHAIN:+"$PLASMIE_KEYCHAIN"} 2>/dev/null)" || continue
    [ -n "$v" ] && export "$k=$v"
  done
  return 0
}
