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
# state, venv, models) and $PLASMIE_LOGS. See plasmie-env.sh.
set -uo pipefail

MODE=install
[ "${1:-}" = --check ] && { MODE=check; shift; }
RES="${1:?usage: app-setup.sh [--check] <RESOURCES_DIR> [VAULT]}"
VAULT="${2:-$HOME/knowledge}"
ENGINE="$RES/backend"
. "$ENGINE/plasmie-env.sh"
VENV="$PLASMIE_HOME/venv"
PY="$VENV/bin/python3"
MODEL_DIR="$PLASMIE_HOME/models/gemma-4-e4b"
NEED_GB=12          # answer model 4.9 + search models 3.7 + runtime ~1.5, with headroom

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
check_all() {
  if [ "$(uname -m)" = arm64 ]; then chk chip ok required "Apple silicon" "Runs the on-device models."
  else chk chip missing required "Apple silicon" "Plasmie's on-device models need an M-series Mac."; fi

  local free; free="$(df -g "$HOME" 2>/dev/null | awk 'NR==2{print $4}')"
  if [ "${free:-0}" -ge "$NEED_GB" ]; then chk disk ok required "Disk space" "${free} GB free (needs about ${NEED_GB} GB)."
  else chk disk missing required "Disk space" "${free:-?} GB free; free up about ${NEED_GB} GB for the models."; fi

  if curl -fsI --max-time 6 https://huggingface.co >/dev/null 2>&1; then chk net ok required "Internet" "Needed once to download the models."
  else chk net missing required "Internet" "Can't reach huggingface.co to download the models."; fi

  local nm; nm="$(node_major)"
  if [ -n "$nm" ] && [ "$nm" -ge 22 ]; then chk node ok required "Node.js 22+" "v$(node -v | tr -d v) powers vault search (qmd)."
  elif [ -n "$nm" ]; then chk node missing required "Node.js 22+" "Found v$nm; vault search (qmd) needs 22 or newer."
  else chk node missing required "Node.js 22+" "Vault search (qmd) runs on Node.js."; fi

  if [ -d /Applications/Obsidian.app ] || [ -d "$HOME/Applications/Obsidian.app" ]; then chk obsidian ok recommended "Obsidian" "Opens and browses your vault."
  else chk obsidian missing recommended "Obsidian" "The app you read your vault in."; fi

  if xcode-select -p >/dev/null 2>&1; then chk clt ok recommended "Command Line Tools" "git keeps a history of your vault."
  else chk clt missing recommended "Command Line Tools" "Without them there's no vault history (git)."; fi

  if command -v claude >/dev/null 2>&1 || [ -x "$HOME/.local/bin/claude" ]; then chk claude ok recommended "Claude Code" "Files new knowledge nightly, on the local model."
  else chk claude missing recommended "Claude Code" "Nightly filing (promote) uses it; everything else works without."; fi
}

if [ "$MODE" = check ]; then check_all; exit 0; fi

# required prerequisites must pass before anything is installed
if blockers="$(check_all | awk -F: '$3!="ok" && $4=="required"{print $5}' | paste -sd, -)" && [ -n "$blockers" ]; then
  fail "Missing: ${blockers//,/, }. Fix these, then try again."
fi

# 1) migrate data from the old ~/.plasmie layout (older installs) -------
p 5 "Preparing Plasmie's data folder…"
"$ENGINE/migrate-home.sh" >/dev/null 2>&1 || fail "couldn't move older Plasmie data into place"

# 2) python runtime (generation only — mlx-vlm) ------------------------------
if [ -x "$PY" ] && "$PY" -c "import mlx_vlm" 2>/dev/null; then
  p 20 "Python runtime ready"
else
  p 8 "Setting up the Python runtime…"
  if [ ! -x "$PY" ]; then
    mkdir -p "$VENV"
    cp -R "$RES/python/." "$VENV/" || fail "python copy failed"
  fi
  p 12 "Installing the generation library (one-time)…"
  "$VENV/bin/python3" -m pip -q install --upgrade pip >/dev/null 2>&1
  "$VENV/bin/python3" -m pip -q install mlx-vlm "huggingface_hub[cli]" \
    || fail "could not install the generation library"
  p 20 "Python runtime ready"
fi

# 3) vault (needed before qmd can index it) ----------------------------------
p 25 "Creating your notes vault…"
# never clobber an existing config (it holds the connector switches); only seed the vault
grep -q '^VAULT_DIR=' "$PLASMIE_CONFIG" 2>/dev/null || printf 'VAULT_DIR="%s"\n' "$VAULT" >> "$PLASMIE_CONFIG"
"$ENGINE/scaffold-vault.sh" "$VAULT" >/dev/null 2>&1 || true   # refuses if non-empty (fine)

# 4) retrieval engine — qmd (hybrid search + MCP; Node 22+) ------------------
QMD="$(command -v qmd || true)"
if [ -z "$QMD" ]; then
  NPM="$(command -v npm || true)"
  [ -n "$NPM" ] || fail "Retrieval needs Node.js 22+ (for qmd). Install Node, then reopen the app."
  p 30 "Installing the search engine (qmd)…"
  "$NPM" install -g @tobilu/qmd >/dev/null 2>&1 || fail "could not install qmd via npm"
  QMD="$(command -v qmd || true)"
fi
[ -n "$QMD" ] || fail "qmd not found after install — install Node.js 22+, then reopen the app"

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

# 5) generation model (ungated, resumable) -----------------------------------
if [ -f "$MODEL_DIR/config.json" ]; then
  p 82 "Answer model ready"
else
  p 65 "Downloading the answer model (~4.9 GB, one-time)…"
  "$VENV/bin/hf" download mlx-community/gemma-4-e4b-it-4bit --local-dir "$MODEL_DIR" \
    || fail "model download interrupted — reopen the app to resume"
  p 82 "Answer model ready"
fi

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

# 6) background loops --------------------------------------------------------
p 95 "Turning on the background helpers…"
"$ENGINE/launchd/install.sh" >/dev/null 2>&1 || fail "couldn't start the background helpers"

p 100 "Done"
echo "DONE"
