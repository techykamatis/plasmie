#!/bin/bash
# Plasmie — installation wizard.
# Gets a fresh machine to a working install: prerequisites, vault, secrets, local
# model, background loops, and the menu-bar app. Interactive (prompts with defaults).
# Idempotent and re-runnable — every step detects what's already done and each is skippable.
set -uo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
PY312="$(command -v python3.12 || echo /opt/homebrew/opt/python@3.12/bin/python3.12)"
VENV_PY="$SELF/.venv/bin/python"

say()  { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
ask()  { local a; read -r -p "  $1 [$2]: " a; printf '%s' "${a:-$2}"; }
yes()  { local a; read -r -p "  $1 [y/N]: " a; [[ "$a" =~ ^[Yy] ]]; }
have() { command -v "$1" >/dev/null 2>&1; }

# Make sure the Ollama server is answering (semantic search + the pull need it).
ensure_ollama() {
  curl -s -o /dev/null --max-time 2 http://127.0.0.1:11434/api/tags 2>/dev/null && return 0
  open -a Ollama 2>/dev/null || true
  for _ in $(seq 1 15); do
    curl -s -o /dev/null --max-time 2 http://127.0.0.1:11434/api/tags 2>/dev/null && return 0
    sleep 1
  done
  return 1
}

install_app() {
  "$SELF/app/make-app.sh" >/dev/null 2>&1 || { warn "app build failed (need Xcode CLT: xcode-select --install)"; return 1; }
  rm -rf "/Applications/Plasmie.app"
  cp -R "$SELF/app/build/Plasmie.app" /Applications/ && ok "installed to /Applications"
  # Unsigned build → strip the quarantine flag so Gatekeeper doesn't block first launch.
  xattr -dr com.apple.quarantine "/Applications/Plasmie.app" 2>/dev/null || true
  yes "Launch at login?" && osascript -e 'tell application "System Events" to make login item at end with properties {path:"/Applications/Plasmie.app", hidden:true}' >/dev/null 2>&1 && ok "added login item"
  open "/Applications/Plasmie.app"
}

# 1) preflight — detect what's already here; only offer to install what's missing
say "1/8 · Preflight — checking prerequisites"
[ "$(uname)" = Darwin ] || { warn "macOS only."; exit 1; }
[ "$(uname -m)" = arm64 ] && ok "Apple Silicon" || warn "Intel Mac — the local MLX model won't run; the loops still work."

if have brew; then ok "Homebrew ($(brew --version 2>/dev/null | awk 'NR==1{print $2}'))"
else warn "Homebrew missing (required) — install from https://brew.sh, then re-run."; exit 1; fi

if xcode-select -p >/dev/null 2>&1; then ok "Xcode Command Line Tools"
else warn "Xcode Command Line Tools missing (needed to build the menu-bar app) — run: xcode-select --install, then re-run."; fi

missing=()   # brew-installable prereqs that aren't here yet
if [ -x "$PY312" ] || have python3.12; then ok "python3.12 ($("$PY312" -V 2>&1 | awk '{print $2}'))"; else warn "python3.12 — missing"; missing+=("python@3.12"); fi
if have git; then ok "git"; else warn "git — missing"; missing+=("git"); fi
if [ -d /Applications/Obsidian.app ]; then ok "Obsidian"; else warn "Obsidian — missing (required to view the vault)"; missing+=("--cask obsidian"); fi
if have ollama || [ -d /Applications/Ollama.app ]; then ok "Ollama"; else warn "Ollama — missing (runs the local semantic-search model)"; missing+=("--cask ollama"); fi
if have claude; then ok "claude CLI"; else warn "claude CLI — missing (needed for local-model summaries; install Claude Code separately, not via brew)"; fi
avail="$(df -g "$HOME" 2>/dev/null | awk 'NR==2{print $4}')"; [ "${avail:-0}" -ge 8 ] && ok "${avail} GB free" || warn "low disk (${avail:-?} GB) — the model needs ~5 GB."

if [ ${#missing[@]} -gt 0 ]; then
  warn "missing & brew-installable: ${missing[*]}"
  if yes "Install these now with Homebrew?"; then
    for pkg in "${missing[@]}"; do brew install $pkg && ok "installed $pkg" || warn "failed: $pkg"; done
    PY312="$(command -v python3.12 || echo "$PY312")"
  else warn "skipped — install them before the vault/model steps will fully work."; fi
else ok "all prerequisites present"; fi

# 2) vault location -----------------------------------------------------------
say "2/8 · Vault location"
VAULT="$(ask "Where should the knowledge vault live?" "$HOME/knowledge")"
VAULT="${VAULT/#\~/$HOME}"
printf 'VAULT_DIR=%s\n' "$VAULT" > "$SELF/config.env"
ok "vault → $VAULT  (saved to config.env)"

# 3) scaffold vault -----------------------------------------------------------
say "3/8 · Scaffold vault"
"$SELF/scaffold-vault.sh" "$VAULT"

# 4) secrets ------------------------------------------------------------------
say "4/8 · Secrets (Slack ingest)"
ENV="$HOME/.claude/.env"; mkdir -p "$(dirname "$ENV")"; touch "$ENV"; chmod 600 "$ENV"
if grep -q SLACK_USER_TOKEN "$ENV" 2>/dev/null; then
  ok "SLACK_USER_TOKEN already set"
elif yes "Add a Slack user token now? (enables Slack ingest)"; then
  tok="$(ask "Paste SLACK_USER_TOKEN (xoxp-…)" "")"
  [ -n "$tok" ] && { printf 'export SLACK_USER_TOKEN=%q\n' "$tok" >> "$ENV"; ok "saved to ~/.claude/.env"; }
else
  warn "skipped — ingest logs 'SLACK_USER_TOKEN not set' until you add it to ~/.claude/.env"
fi

# 5) python env + MLX ---------------------------------------------------------
say "5/8 · Python environment (MLX)"
[ -d "$SELF/.venv" ] && ok ".venv exists" || { "$PY312" -m venv "$SELF/.venv"; ok "created .venv"; }
if "$VENV_PY" -c "import mlx_vlm" 2>/dev/null; then ok "mlx-vlm installed"
else warn "installing mlx-vlm (pulls mlx + mlx-lm)…"; "$SELF/.venv/bin/pip" -q install mlx-vlm && ok "mlx-vlm installed" || warn "mlx-vlm install failed — local model won't serve"; fi

# 6) local models -------------------------------------------------------------
say "6/8 · Local models (generation + search)"
# 6a · generation model — mlx Gemma (used by summarize/promote and the ask answer)
MODEL="$SELF/models/gemma-4-e4b"
if [ -f "$MODEL/config.json" ]; then
  ok "generation model already present"
elif yes "Download the generation model now? (~4.9 GB; needs a Hugging Face login)"; then
  "$SELF/.venv/bin/pip" -q install -U "huggingface_hub[cli]"
  "$SELF/.venv/bin/huggingface-cli" whoami >/dev/null 2>&1 || "$SELF/.venv/bin/huggingface-cli" login
  "$SELF/.venv/bin/huggingface-cli" download mlx-community/gemma-4-e4b-it-4bit --local-dir "$MODEL" \
    && ok "model downloaded" || warn "download interrupted — re-run install.sh to resume (HF resumes partials)"
else
  warn "skipped — promote/summarize skip until the model is present (see models/README.md)"
fi

# 6b · search model — EmbeddingGemma on Ollama (ungated, auto-pull). The ask
# feature's semantic search needs this; without it ask.py falls back to weaker
# keyword matching and can't tell when the vault doesn't cover a question.
if have ollama || [ -d /Applications/Ollama.app ]; then
  if ensure_ollama; then
    if ollama list 2>/dev/null | grep -q '^embeddinggemma'; then ok "search model (embeddinggemma) present"
    else warn "pulling embeddinggemma (~620 MB)…"; ollama pull embeddinggemma >/dev/null 2>&1 \
      && ok "search model ready" || warn "pull failed — ask falls back to keyword search until you run: ollama pull embeddinggemma"; fi
  else warn "Ollama installed but not responding — open it once, then re-run to pull embeddinggemma"; fi
else
  warn "Ollama not installed — semantic search is off until you install it (re-run) and it pulls embeddinggemma"
fi

# 7) background loops — detect already-installed agents -----------------------
say "7/8 · Background loops (launchd)"
DOMAIN="gui/$(id -u)"; loaded=0
for l in com.plasmie.dev-ingest com.plasmie.dev-summarize com.plasmie.dev-promote com.plasmie.mlx-server; do
  launchctl print "$DOMAIN/$l" >/dev/null 2>&1 && loaded=$((loaded + 1))
done
if [ "$loaded" -ge 4 ]; then
  ok "agents already installed ($loaded/4 loaded)"
  yes "Refresh them (re-point to this install)?" && { "$SELF/launchd/install.sh" && ok "refreshed"; }
elif yes "Install the ingest + summarize + promote agents${loaded:+ ($loaded/4 currently loaded)}?"; then
  "$SELF/launchd/install.sh" && ok "agents installed"
else warn "skipped — run launchd/install.sh later"; fi

# 8) menu-bar app — detect existing install -----------------------------------
say "8/8 · Menu-bar app"
if [ -d "/Applications/Plasmie.app" ]; then
  pgrep -x Plasmie >/dev/null && ok "app already installed (running)" || ok "app already installed"
  yes "Rebuild & reinstall (pick up the latest)?" && install_app
elif yes "Build & install the Plasmie menu-bar app?"; then
  install_app
else warn "skipped — build later with app/make-app.sh"; fi

say "Done"
echo "  Vault:    $VAULT   →  open in Obsidian (File ▸ Open folder as vault)"
echo "  Menu bar: look for 🧠"
echo "  Re-run this wizard any time — every step is idempotent."
