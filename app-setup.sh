#!/bin/bash
# First-run backend setup, driven by the menu-bar app (no terminal, no Homebrew).
# Idempotent: every step detects what's already done, so it's safe to re-run and
# resumes a partial setup. Emits "PROGRESS:<pct>:<message>" lines for the app to
# show, and "DONE" / "ERROR:<message>" at the end.
#
#   app-setup.sh <RESOURCES_DIR> [VAULT_DIR]
#     RESOURCES_DIR contains backend/ (the scripts) and python/ (standalone 3.12)
#
# ponytail: bundles a BARE standalone python and pip-installs the model libs on
# first run — keeps the .app small and gets the right arch, at the cost of one
# network install the user already needs network for (the 5 GB model anyway).
set -uo pipefail

RES="${1:?usage: app-setup.sh <RESOURCES_DIR> [VAULT]}"
VAULT="${2:-$HOME/knowledge}"
LOOP="$HOME/.plasmie"
VENV="$LOOP/.venv"
PY="$VENV/bin/python3"
MODEL_DIR="$LOOP/models/gemma-4-e4b"
EMBED_MODEL="mlx-community/embeddinggemma-300m-bf16"

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

# 2) python runtime ----------------------------------------------------------
if [ -x "$PY" ] && "$PY" -c "import mlx_vlm" 2>/dev/null; then
  p 25 "Python runtime ready"
else
  p 10 "Setting up the Python runtime…"
  if [ ! -x "$PY" ]; then
    mkdir -p "$VENV"
    cp -R "$RES/python/." "$VENV/" || fail "python copy failed"
  fi
  p 15 "Installing model libraries (one-time)…"
  "$VENV/bin/python3" -m pip -q install --upgrade pip >/dev/null 2>&1
  "$VENV/bin/python3" -m pip -q install mlx-vlm mlx-embeddings "huggingface_hub[cli]" \
    || fail "could not install model libraries"
  p 25 "Python runtime ready"
fi

# 3) search model — EmbeddingGemma in-process (MLX, no extra server) ----------
# Cached in the HF hub cache; pre-warm it so the first ask is instant & offline.
if "$PY" -c "from mlx_embeddings.utils import load; load('$EMBED_MODEL')" 2>/dev/null; then
  p 45 "Search model ready"
else
  p 40 "Downloading the search model (~600 MB, one-time)…"
  "$PY" -c "from mlx_embeddings.utils import load; load('$EMBED_MODEL')" \
    || fail "couldn't download the search model"
  p 45 "Search model ready"
fi

# 4) generation model (ungated, resumable) -----------------------------------
if [ -f "$MODEL_DIR/config.json" ]; then
  p 75 "Answer model ready"
else
  p 50 "Downloading the answer model (~4.9 GB, one-time)…"
  "$VENV/bin/hf" download mlx-community/gemma-4-e4b-it-4bit --local-dir "$MODEL_DIR" \
    || fail "model download interrupted — reopen the app to resume"
  p 75 "Answer model ready"
fi

# 5) vault -------------------------------------------------------------------
p 85 "Creating your notes vault…"
printf 'VAULT_DIR=%s\n' "$VAULT" > "$LOOP/config.env"
"$LOOP/scaffold-vault.sh" "$VAULT" >/dev/null 2>&1 || true   # refuses if non-empty (fine)

# 6) background loops --------------------------------------------------------
p 92 "Turning on the background helpers…"
"$LOOP/launchd/install.sh" >/dev/null 2>&1 || fail "couldn't start the background helpers"

p 100 "Done"
echo "DONE"
