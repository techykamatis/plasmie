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
# Generation is Apple's on-device model via the bundled plasmie-fm helper (ADR 0002):
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
# /usr/local is Intel Homebrew on Apple silicon: never put it ahead of native tools.
for d in /usr/local/bin /opt/homebrew/bin "$HOME"/.nvm/versions/node/*/bin; do
  [ "$d" = /usr/local/bin ] && [ "$(uname -m)" = arm64 ] && continue
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
  else chk obsidian missing recommended "Obsidian" "Optional: $PLASMIE_APP_NAME reads your vault itself; Obsidian is another way to browse and edit it."; fi

  local git; git="$(native_tool git)"
  if [ -n "$git" ]; then chk clt ok recommended "Command Line Tools" "git keeps a history of your vault ($git, built for this Mac)."
  else chk clt missing recommended "Command Line Tools" "Without them there's no vault history (git). Setup will offer to install them."; fi
}
# The native (Apple-silicon) copy of a tool, "" if none: Intel copies are skipped
# (paths.native_tool). Runs on the venv (never quarantined, see step 2); the bundled
# runtime only if the venv isn't there yet.
native_tool() {
  local py="$PY"; [ -x "$py" ] || py="$RES/python/bin/python3"
  xattr -p com.apple.quarantine "$py" >/dev/null 2>&1 && return 0   # would prompt: skip, not block
  "$py" -c 'import sys; sys.path.insert(0, sys.argv[1]); import paths; print(paths.native_tool(sys.argv[2]))' \
    "$ENGINE" "$1" 2>/dev/null
}
set_config() {   # set_config KEY VALUE: one line in config.env, every other line kept
  local esc; esc="$(printf '%s' "$2" | sed "s/'/'\\\\''/g")"
  { grep -v "^$1=" "$PLASMIE_CONFIG" 2>/dev/null; printf "%s='%s'\n" "$1" "$esc"; } > "$PLASMIE_CONFIG.tmp" \
    && mv "$PLASMIE_CONFIG.tmp" "$PLASMIE_CONFIG"
}

if [ "$MODE" = check ]; then check_all; exit 0; fi

# required prerequisites must pass before anything is installed
if blockers="$(check_all | awk -F: '$3!="ok" && $4=="required"{print $5}' | paste -sd, -)" && [ -n "$blockers" ]; then
  fail "Missing: ${blockers//,/, }. Fix these, then try again."
fi

# 1) migrate data from the old home dot-folder layout (older installs) ---------
p 5 "Preparing $PLASMIE_APP_NAME's data folder…"
"$ENGINE/migrate-home.sh" >/dev/null 2>&1 || fail "couldn't move older $PLASMIE_APP_NAME data into place"

# 2) python runtime (the engine is stdlib-only; nothing to pip-install) ---------
# The venv is a copy of the bundled runtime. Missing, broken, or a different version than
# this app ships (left by an older install) -> replaced, so the engine always runs on the
# Python it was tested with.
# The bundled copy is never run here: in a downloaded app it can still carry
# com.apple.quarantine, and running it pops Gatekeeper's "python3.12 Not Opened". Its version
# comes from the stamp make-app.sh writes, and the flag is stripped from the copy (cp keeps
# it, even with -X), here and on a venv an older setup copied with the flag still on.
pyver() { "$1" -c 'import sys; print(sys.version.split()[0])' 2>/dev/null; }
WANT_PY="$(cat "$RES/python/.plasmie-pyver" 2>/dev/null || pyver "$RES/python/bin/python3")"
[ -d "$VENV" ] && xattr -dr com.apple.quarantine "$VENV" 2>/dev/null
if [ -n "$WANT_PY" ] && [ "$(pyver "$PY")" != "$WANT_PY" ]; then
  p 8 "Setting up the Python runtime…"
  rm -rf "$VENV" && mkdir -p "$VENV"
  cp -R "$RES/python/." "$VENV/" || fail "python copy failed"
  xattr -dr com.apple.quarantine "$VENV" 2>/dev/null
fi
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || fail "the bundled Python runtime is broken — reinstall $PLASMIE_APP_NAME"
p 20 "Python runtime ready"

# 2b) native tools: record the Apple-silicon git and gh the background jobs must use, so an
# Intel copy earlier on PATH is never picked; no native git -> offer Apple's installer.
p 22 "Checking tools are built for this Mac…"
GIT_NATIVE="$(native_tool git)"
set_config PLASMIE_GIT_BIN "$GIT_NATIVE"
set_config PLASMIE_GH_BIN "$(native_tool gh)"
[ -n "$GIT_NATIVE" ] || xcode-select --install >/dev/null 2>&1 || true

# 3) vault: adopt, never overwrite (ADR 0023) -------------------------------------
# The vault is the one thing that must never be lost: the folder the user chose in setup
# is recorded (other config lines, e.g. connector switches, are kept), an existing vault
# gets a restore point before anything else, a Plasmie vault is adopted untouched, and any
# other folder only gains the pieces it lacks (never an overwrite).
p 25 "Preparing your notes vault…"
ok="$("$PY" "$ENGINE/plasmie-vault.py" check-folder "$VAULT")"
case "$ok" in *'"ok": true'*) ;; *) fail "$(printf '%s' "$ok" | sed -E 's/.*"reason": "([^"]*)".*/\1/')";; esac
set_config VAULT_DIR "$VAULT"
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
  QMD="$PLASMIE_HOME/qmd/bin/qmd"
  # missing, not the pinned version, or not loading under the bundled Node (a native module
  # built for another Node ABI) -> reinstall fresh
  qmd_ver() { PATH="$NODE_BIN:$PATH" "$QMD" --version 2>/dev/null | awk '{print $NF; exit}'; }
  if [ "$(qmd_ver)" != "$QMD_VERSION" ] \
     || ! PATH="$NODE_BIN:$PATH" "$QMD" collection list >/dev/null 2>&1; then
    p 30 "Installing the search engine…"
    rm -rf "$PLASMIE_HOME/qmd"
    PATH="$NODE_BIN:$PATH" npm_config_build_from_source=false npm_config_update_notifier=false \
      "$NODE_BIN/npm" install -g --prefix "$PLASMIE_HOME/qmd" "@tobilu/qmd@$QMD_VERSION" >/dev/null 2>&1 \
      || fail "couldn't install the search engine; check the internet connection and try again"
    [ "$(qmd_ver)" = "$QMD_VERSION" ] || fail "the search engine didn't install correctly; try again"
  fi
  export PATH="$NODE_BIN:$PLASMIE_HOME/qmd/bin:$PATH"
else
  QMD="$(command -v qmd || true)"
  [ -n "$QMD" ] || fail "Search needs Node.js 22+ (this build has none bundled). Install Node, then try again."
fi

p 35 "Indexing your vault…"
# Search covers ONE location, the vault chosen above: raw/ and wiki/ are Plasmie's
# collections, "vault" is the user's own notes in whatever folders they already use.
# A collection left pointing elsewhere (a previous vault, an iCloud copy) is repointed in
# place through qmd's own config API, so hand-written contexts and ignores survive; plain
# `collection add` refuses an existing name and would silently keep the stale path.
QMD_COLLECTIONS="$PLASMIE_HOME/qmd/lib/node_modules/@tobilu/qmd/dist/collections.js"
if [ -x "$NODE_BIN/node" ] && [ -f "$QMD_COLLECTIONS" ]; then
  PLASMIE_VAULT_ROOT="$VAULT" QMD_COLLECTIONS="$QMD_COLLECTIONS" "$NODE_BIN/node" --input-type=module -e '
    const { pathToFileURL } = await import("node:url");
    const q = await import(pathToFileURL(process.env.QMD_COLLECTIONS).href);
    const v = process.env.PLASMIE_VAULT_ROOT.replace(/\/+$/, "");
    const cfg = q.loadConfig();
    const want = { raw: v + "/raw", wiki: v + "/wiki", vault: v };
    for (const [name, path] of Object.entries(want)) {
      const c = cfg.collections[name] || {};
      c.path = path;
      c.pattern = c.pattern || "**/*.md";
      if (name === "vault")                     // the rest is indexed by raw/wiki, or private
        c.ignore = [...new Set([...(c.ignore || []), ".obsidian/**", "raw/**", "wiki/**", "meta/**"])];
      cfg.collections[name] = c;
    }
    q.saveConfig(cfg);' || fail "couldn't set up search for your vault"
else                                            # dev build: an installed qmd, CLI only
  "$QMD" collection add "$VAULT/raw"  --name raw  >/dev/null 2>&1 || true
  "$QMD" collection add "$VAULT/wiki" --name wiki >/dev/null 2>&1 || true
fi
"$QMD" context add qmd://raw  "Immutable raw source material captured hourly. Prefer wiki/ for durable answers." >/dev/null 2>&1 || true
"$QMD" context add qmd://raw/slack  "Slack messages sent and received." >/dev/null 2>&1 || true
"$QMD" context add qmd://raw/claude "Claude Code coding-session activity and decisions." >/dev/null 2>&1 || true
"$QMD" context add qmd://raw/confluence "Mirror of Confluence wiki pages." >/dev/null 2>&1 || true
"$QMD" context add qmd://wiki "Curated, synthesized knowledge — the durable answer layer." >/dev/null 2>&1 || true
p 45 "Downloading the search models (~3.7 GB, one-time)…"
"$QMD" embed >/dev/null 2>&1 || true   # downloads embed/rerank models + indexes; safe to retry later

# 4b) suggested links: most notes a person brings have none, so the map would be loose dots
# and a note in the reader would lead nowhere. related.py finds each note's text neighbours
# (a few seconds for ~1000 notes) for the map and the reader; nothing is written to a note.
p 80 "Finding links between your notes…"
"$PY" "$ENGINE/related.py" build >/dev/null 2>&1 || true

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
  CRAWLED=1
fi

# 5c) first ingest + promote, on EVERY setup (an existing vault, a re-run, an upgrade), so
# Plasmie starts from today's activity and files it instead of waiting for the hourly and
# nightly jobs. Ingest is incremental (watermarks), so a re-run captures only what's new;
# it runs here with the job's own time limit and log. Promote drafts with the on-device
# model and can take a while: it starts in the background (same limit and log as the
# nightly job, see make-app.sh) and setup finishes without waiting for it.
if [ -z "${CRAWLED:-}" ]; then
  p 88 "Catching up on your latest activity…"
  PLASMIE_JOB_LOG=ingest.log "$ENGINE/plasmie-job.sh" 50 run-ingest.sh >/dev/null 2>&1 || true
fi
p 92 "Filing what I found into your notes (continues in the background)…"
( PLASMIE_JOB_LOG=promote.log nohup "$ENGINE/plasmie-job.sh" 120 promote.sh >/dev/null 2>&1 & ) || true

# 6) background jobs: the app registers them (SMAppService) as soon as this finishes,
# so they're Plasmie's own Login Items and go away with the app. launchd/install.sh is the
# dev-checkout path only.
p 95 "Getting the background helpers ready…"

date '+%F %T' > "$READY"
p 100 "Done"
echo "DONE"
