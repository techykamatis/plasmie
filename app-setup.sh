#!/bin/bash
# First-run backend setup, driven by the menu-bar app (no terminal, no Homebrew).
# Idempotent: every step detects what's already done, so it's safe to re-run and
# resumes a partial setup. Emits "PROGRESS:<pct>:<message>" lines for the app to
# show, and "DONE" / "ERROR:<message>" at the end.
#
#   app-setup.sh <RESOURCES_DIR> [VAULT_DIR]
#     RESOURCES_DIR contains backend/ (the scripts) and python/ (standalone 3.12)
#
# ponytail: bundles a BARE standalone python and pip-installs mlx-vlm (generation)
# on first run. Retrieval is qmd (Node) — installed via npm here; Node 22+ is the
# one host prerequisite we don't bundle. Models (~8.6 GB total) download once.
set -uo pipefail

RES="${1:?usage: app-setup.sh <RESOURCES_DIR> [VAULT]}"
VAULT="${2:-$HOME/knowledge}"
LOOP="$HOME/.plasmie"
VENV="$LOOP/.venv"
PY="$VENV/bin/python3"
MODEL_DIR="$LOOP/models/gemma-4-e4b"

# make node/npm/qmd reachable even under the app's bare GUI PATH
for d in "$HOME"/.nvm/versions/node/*/bin /opt/homebrew/bin /usr/local/bin; do
  [ -d "$d" ] && PATH="$d:$PATH"
done
export PATH

p()   { printf 'PROGRESS:%s:%s\n' "$1" "$2"; }
fail(){ printf 'ERROR:%s\n' "$1"; exit 1; }

# 1) backend scripts ---------------------------------------------------------
p 5 "Installing the engine…"
mkdir -p "$LOOP" || fail "can't create $LOOP"
# copy everything but the heavy/per-machine bits; never clobber an existing venv/model
/usr/bin/rsync -a --delete \
  --exclude '.venv' --exclude 'models' --exclude 'logs' --exclude 'config.env' \
  "$RES/backend/" "$LOOP/" 2>/dev/null || cp -R "$RES/backend/." "$LOOP/" || fail "copy failed"
chmod +x "$LOOP"/*.sh "$LOOP"/launchd/*.sh 2>/dev/null || true

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
printf 'VAULT_DIR=%s\n' "$VAULT" > "$LOOP/config.env"
"$LOOP/scaffold-vault.sh" "$VAULT" >/dev/null 2>&1 || true   # refuses if non-empty (fine)

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
if [ ! -f "$LOOP/.loop-state.json" ]; then
  p 85 "Gathering your recent history (first-time crawl)…"
  set -a; [ -f "$HOME/.claude/.env" ] && . "$HOME/.claude/.env"; set +a
  export PLASMIE_VAULT="$VAULT" PLASMIE_BOOTSTRAP_DAYS="${PLASMIE_BOOTSTRAP_DAYS:-30}"
  "$PY" "$LOOP/confluence-backfill.py" "$VAULT" >/dev/null 2>&1 || true
  "$PY" "$LOOP/github-backfill.py"     "$VAULT" >/dev/null 2>&1 || true
  "$PY" "$LOOP/loop-ingest.py"                   >/dev/null 2>&1 || true
  "$PY" "$LOOP/reindex.py" "$VAULT"              >/dev/null 2>&1 || true
  "$QMD" embed                                   >/dev/null 2>&1 || true
fi

# 6) background loops --------------------------------------------------------
p 95 "Turning on the background helpers…"
"$LOOP/launchd/install.sh" >/dev/null 2>&1 || fail "couldn't start the background helpers"

p 100 "Done"
echo "DONE"
