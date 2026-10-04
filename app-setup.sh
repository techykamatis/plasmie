#!/bin/bash
# First-run setup, driven by Plasmie.app (no terminal, no Homebrew). Two modes:
#
#   app-setup.sh --check <RESOURCES_DIR>          prerequisite report, changes nothing
#   app-setup.sh <RESOURCES_DIR> [VAULT_DIR]      install (idempotent, resumable)
#
# --check prints one line per prerequisite for the app's checklist:
#   CHECK:<id>:<ok|missing|warn>:<required|recommended>:<label>:<detail>
# Install prints "PROGRESS:<pct>:<message>" lines, then "DONE" or "ERROR:<message>".
#
# Layout: the engine runs IN PLACE from <RESOURCES_DIR>/backend (read-only, replaced on
# app update; never copied out). Everything written goes to $PLASMIE_HOME (data: config,
# state, venv) and $PLASMIE_LOGS. See plasmie-env.sh.
#
# Generation is Apple's on-device model via the bundled plasmie-fm helper (ADR 0025):
# nothing to download or pip-install for it, but Apple Intelligence must be on.
set -uo pipefail

MODE=install
[ "${1:-}" = --check ] && { MODE=check; shift; }
RES="${1:?usage: app-setup.sh [--check] <RESOURCES_DIR> [VAULT]}"
VAULT="${2:-$HOME/knowledge}"
ENGINE="$RES/backend"
. "$ENGINE/plasmie-env.sh"
VENV="$PLASMIE_HOME/venv"
PY="$VENV/bin/python3"
NEED_GB=6           # search models 3.7 + Python runtime ~0.1 + index, with headroom
# plasmie-fm ships in Plasmie.app/Contents/MacOS; <RESOURCES_DIR> is Contents/Resources.
FM_BIN="${PLASMIE_FM_BIN:-$RES/../MacOS/$PLASMIE_APP_ID-fm}"
READY="$PLASMIE_HOME/.setup-complete"   # the app's "installed" marker (Setup.swift)

# make node/npm/qmd reachable even under the app's bare GUI PATH. Each dir is
# PREPENDED, so the last one wins: nvm goes last. qmd's better-sqlite3 is a native
# module built for one Node ABI; homebrew node (v26) loading an nvm-built (v22)
# install dies with ERR_DLOPEN_FAILED.
for d in /usr/local/bin /opt/homebrew/bin "$HOME"/.nvm/versions/node/*/bin; do
  [ -d "$d" ] && PATH="$d:$PATH"
done
export PATH

p()   { printf 'PROGRESS:%s:%s\n' "$1" "$2"; }
fail(){ printf 'ERROR:%s\n' "$1"; exit 1; }
chk() { printf 'CHECK:%s:%s:%s:%s:%s\n' "$1" "$2" "$3" "$4" "$5"; }

# --- prerequisites (shared by --check and the install's own preflight) --------
node_major() { node -v 2>/dev/null | sed -E 's/^v([0-9]+).*/\1/'; }
# Apple Intelligence, asked of the model itself (plasmie-fm --check). It writes every
# summary, filing and answer, so it is required; a model still downloading only warns.
check_ai() {
  local st
  if [ ! -x "$FM_BIN" ]; then
    chk ai missing required "Apple Intelligence" "$PLASMIE_APP_NAME's model bridge is missing. Reinstall $PLASMIE_APP_NAME from the DMG."; return
  fi
  st="$("$FM_BIN" --check 2>/dev/null | head -1)"
  case "$st" in
    available) chk ai ok required "Apple Intelligence" "On, and the on-device model is ready." ;;
    appleIntelligenceNotEnabled)
      chk ai missing required "Apple Intelligence" "Turn it on in System Settings › Apple Intelligence & Siri, then check again." ;;
    modelNotReady)
      chk ai warn recommended "Apple Intelligence" "On, but the model is still downloading. $PLASMIE_APP_NAME starts using it once it's ready." ;;
    deviceNotEligible)
      chk ai missing required "Apple Intelligence" "This Mac can't run Apple Intelligence, which $PLASMIE_APP_NAME uses to summarize and answer." ;;
    unsupportedOS)
      chk macos missing required "macOS 26 or later" "Apple's on-device model needs macOS 26. Update in System Settings › General › Software Update." ;;
    *) chk ai missing required "Apple Intelligence" "Couldn't ask the on-device model (${st:-no answer}). Check System Settings › Apple Intelligence & Siri." ;;
  esac
}
check_all() {
  if [ "$(uname -m)" = arm64 ]; then chk chip ok required "Apple silicon" "Runs Apple's on-device model."
  else chk chip missing required "Apple silicon" "Apple's on-device model needs an M-series Mac."; fi

  check_ai

  local free; free="$(df -g "$HOME" 2>/dev/null | awk 'NR==2{print $4}')"
  if [ "${free:-0}" -ge "$NEED_GB" ]; then chk disk ok required "Disk space" "${free} GB free (needs about ${NEED_GB} GB)."
  else chk disk missing required "Disk space" "${free:-?} GB free; free up about ${NEED_GB} GB for the search models."; fi

  if curl -fsI --max-time 6 https://huggingface.co >/dev/null 2>&1; then chk net ok required "Internet" "Needed once to download the search models."
  else chk net missing required "Internet" "Can't reach huggingface.co to download the search models."; fi

  local nm; nm="$(node_major)"
  if [ -x "$RES/node/bin/node" ]; then chk node ok required "Search engine" "Included with $PLASMIE_APP_NAME."
  elif [ -n "$nm" ] && [ "$nm" -ge 22 ]; then chk node ok required "Node.js 22+" "v$(node -v | tr -d v) powers vault search (qmd)."
  elif [ -n "$nm" ]; then chk node missing required "Node.js 22+" "Found v$nm; vault search (qmd) needs 22 or newer."
  else chk node missing required "Node.js 22+" "Vault search (qmd) runs on Node.js."; fi

  if [ -d /Applications/Obsidian.app ] || [ -d "$HOME/Applications/Obsidian.app" ]; then chk obsidian ok recommended "Obsidian" "Opens and browses your vault."
  else chk obsidian missing recommended "Obsidian" "The app you read your vault in."; fi

  if xcode-select -p >/dev/null 2>&1; then chk clt ok recommended "Command Line Tools" "git keeps a history of your vault."
  else chk clt missing recommended "Command Line Tools" "Without them there's no vault history (git)."; fi
}

if [ "$MODE" = check ]; then check_all; exit 0; fi

# required prerequisites must pass before anything is installed
if blockers="$(check_all | awk -F: '$3!="ok" && $4=="required"{print $5}' | paste -sd, -)" && [ -n "$blockers" ]; then
  fail "Missing: ${blockers//,/, }. Fix these, then try again."
fi

# 1) migrate data from the old ~/.plasmie layout (older installs) -------
p 5 "Preparing $PLASMIE_APP_NAME's data folder…"
"$ENGINE/migrate-home.sh" >/dev/null 2>&1 || fail "couldn't move older $PLASMIE_APP_NAME data into place"

# 2) python runtime (the engine is stdlib-only; nothing to pip-install) ---------
if [ ! -x "$PY" ]; then
  p 8 "Setting up the Python runtime…"
  mkdir -p "$VENV"
  cp -R "$RES/python/." "$VENV/" || fail "python copy failed"
fi
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || fail "the bundled Python runtime is broken — reinstall $PLASMIE_APP_NAME"
p 20 "Python runtime ready"

# 3) vault: adopt, never overwrite (ADR 0022) -------------------------------------
# The vault is the one thing that must never be lost: the folder the user chose in setup
# is recorded (other config lines, e.g. connector switches, are kept), an existing vault
# gets a restore point before anything else, a Plasmie vault is adopted untouched, and any
# other folder only gains the pieces it lacks (never an overwrite).
p 25 "Preparing your notes vault…"
ok="$("$PY" "$ENGINE/plasmie-vault.py" check-folder "$VAULT")"
case "$ok" in *'"ok": true'*) ;; *) fail "$(printf '%s' "$ok" | sed -E 's/.*"reason": "([^"]*)".*/\1/')";; esac
esc="$(printf '%s' "$VAULT" | sed "s/'/'\\\\''/g")"
{ grep -v '^VAULT_DIR=' "$PLASMIE_CONFIG" 2>/dev/null; printf "VAULT_DIR='%s'\n" "$esc"; } > "$PLASMIE_CONFIG.tmp" \
  && mv "$PLASMIE_CONFIG.tmp" "$PLASMIE_CONFIG"
"$PY" "$ENGINE/plasmie-vault.py" snapshot "$VAULT" "$PLASMIE_APP_NAME setup" >/dev/null 2>&1 || true
info="$("$PY" "$ENGINE/plasmie-vault.py" inspect "$VAULT")"
case "$info" in
  *'"plasmie_vault": true'*) p 28 "Found your $PLASMIE_APP_NAME vault; using it as is" ;;
  *) mkdir -p "$VAULT" && cp -Rn "$ENGINE/vault-template/." "$VAULT/" 2>/dev/null
     find "$VAULT" -name .gitkeep -delete 2>/dev/null ;;
esac
# versioned data migrations, incl. seeding ingest's watermarks from an existing vault so a
# reinstall never re-captures what's already there (ingest appends, it doesn't de-duplicate)
"$PY" "$ENGINE/plasmie-migrate.py" >/dev/null 2>&1 || fail "couldn't prepare $PLASMIE_APP_NAME's data (migration); try again"
[ "${PLASMIE_SETUP_UNTIL:-}" = vault ] && { echo "DONE"; exit 0; }   # tests stop here (no jobs, no downloads)

# 4) retrieval engine — qmd (hybrid search + MCP), Plasmie's own copy ---------------
# Installed with the Node that ships in Plasmie.app into $PLASMIE_HOME/qmd (prebuilt native
# modules, no compiler); pinned to the version Plasmie is tested with. A dev build without
# a bundled Node falls back to an installed qmd.
QMD_VERSION="2.5.3"
NODE_BIN="$RES/node/bin"
if [ -x "$NODE_BIN/node" ]; then
  if [ ! -x "$PLASMIE_HOME/qmd/bin/qmd" ]; then
    p 30 "Installing the search engine…"
    PATH="$NODE_BIN:$PATH" npm_config_build_from_source=false npm_config_update_notifier=false \
      "$NODE_BIN/npm" install -g --prefix "$PLASMIE_HOME/qmd" "@tobilu/qmd@$QMD_VERSION" >/dev/null 2>&1 \
      || fail "couldn't install the search engine; check the internet connection and try again"
  fi
  QMD="$PLASMIE_HOME/qmd/bin/qmd"
  export PATH="$NODE_BIN:$PLASMIE_HOME/qmd/bin:$PATH"
else
  QMD="$(command -v qmd || true)"
  [ -n "$QMD" ] || fail "Search needs Node.js 22+ (this build has none bundled). Install Node, then try again."
fi

p 35 "Indexing your vault…"
"$QMD" collection add "$VAULT/raw"  --name raw  >/dev/null 2>&1 || true
"$QMD" collection add "$VAULT/wiki" --name wiki >/dev/null 2>&1 || true
"$QMD" context add qmd://raw  "Immutable raw source material captured hourly. Prefer wiki/ for durable answers." >/dev/null 2>&1 || true
"$QMD" context add qmd://raw/slack  "Slack messages sent and received." >/dev/null 2>&1 || true
"$QMD" context add qmd://raw/claude "Claude Code coding-session activity and decisions." >/dev/null 2>&1 || true
"$QMD" context add qmd://raw/confluence "Mirror of Confluence wiki pages." >/dev/null 2>&1 || true
"$QMD" context add qmd://wiki "Curated, synthesized knowledge — the durable answer layer." >/dev/null 2>&1 || true
p 45 "Downloading the search models (~3.7 GB, one-time)…"
"$QMD" embed >/dev/null 2>&1 || true   # downloads embed/rerank models + indexes; safe to retry later

# 5) answer model: Apple's, on-device, managed by macOS — nothing to download --
p 82 "Answer model: Apple Intelligence (on-device)"

# 5b) first-time crawl — seed the vault so day one is useful -----------------
# Only on a genuine first run (no prior state). Best-effort: whatever defers here
# the hourly/nightly loops backfill. Confluence + GitHub = full contributor
# history; Slack + Claude sessions = the bootstrap window (PLASMIE_BOOTSTRAP_DAYS).
if [ ! -f "$PLASMIE_HOME/.loop-state.json" ]; then
  p 85 "Gathering your recent history (first-time crawl)…"
  plasmie_secrets   # connector credentials from the Keychain (plasmie-env.sh)
  export PLASMIE_VAULT="$VAULT" PLASMIE_BOOTSTRAP_DAYS="${PLASMIE_BOOTSTRAP_DAYS:-30}"
  "$PY" "$ENGINE/confluence-backfill.py" "$VAULT" >/dev/null 2>&1 || true
  "$PY" "$ENGINE/github-backfill.py"     "$VAULT" >/dev/null 2>&1 || true
  "$PY" "$ENGINE/loop-ingest.py"                   >/dev/null 2>&1 || true
  "$PY" "$ENGINE/reindex.py" "$VAULT"              >/dev/null 2>&1 || true
  "$QMD" embed                                   >/dev/null 2>&1 || true
fi

# 6) background jobs: the app registers them (SMAppService) as soon as this finishes,
# so they're Plasmie's own Login Items and go away with the app. launchd/install.sh is the
# dev-checkout path only.
p 95 "Getting the background helpers ready…"

date '+%F %T' > "$READY"
p 100 "Done"
echo "DONE"
