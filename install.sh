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

# 1) preflight ----------------------------------------------------------------
say "1/8 · Preflight"
[ "$(uname)" = Darwin ] || { warn "macOS only."; exit 1; }
[ "$(uname -m)" = arm64 ] && ok "Apple Silicon" || warn "Intel Mac — the local MLX model won't run; the loops still work."
command -v brew >/dev/null && ok "Homebrew" || { warn "Homebrew required → https://brew.sh"; exit 1; }
if [ -x "$PY312" ]; then ok "python3.12"; else warn "installing python@3.12…"; brew install python@3.12; PY312="$(command -v python3.12)"; fi
command -v git  >/dev/null && ok "git" || brew install git
[ -d /Applications/Obsidian.app ] && ok "Obsidian" || warn "Obsidian not found (required to view the vault) → https://obsidian.md"
command -v claude >/dev/null && ok "claude CLI" || warn "claude CLI not found — needed for local-model summaries; install Claude Code first."
avail="$(df -g "$HOME" 2>/dev/null | awk 'NR==2{print $4}')"; [ "${avail:-0}" -ge 8 ] && ok "${avail} GB free" || warn "low disk (${avail:-?} GB) — the model needs ~5 GB."

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

# 6) model download -----------------------------------------------------------
say "6/8 · Local model (Gemma-4 E4B · ~4.9 GB, gated)"
MODEL="$SELF/models/gemma-4-e4b"
if [ -f "$MODEL/config.json" ]; then
  ok "model already present"
elif yes "Download it now? (~4.9 GB; needs a Hugging Face login)"; then
  "$SELF/.venv/bin/pip" -q install -U "huggingface_hub[cli]"
  "$SELF/.venv/bin/huggingface-cli" whoami >/dev/null 2>&1 || "$SELF/.venv/bin/huggingface-cli" login
  "$SELF/.venv/bin/huggingface-cli" download mlx-community/gemma-4-e4b-it-4bit --local-dir "$MODEL" \
    && ok "model downloaded" || warn "download interrupted — re-run install.sh to resume (HF resumes partials)"
else
  warn "skipped — promote/summarize skip until the model is present (see models/README.md)"
fi

# 7) background loops ---------------------------------------------------------
say "7/8 · Background loops (launchd)"
if yes "Install the hourly ingest + summarize and nightly promote agents?"; then
  "$SELF/launchd/install.sh" && ok "agents installed"
else warn "skipped — run launchd/install.sh later"; fi

# 8) menu-bar app -------------------------------------------------------------
say "8/8 · Menu-bar app"
if yes "Build & install the Plasmie menu-bar app?"; then
  if "$SELF/app/make-app.sh" >/dev/null 2>&1; then
    rm -rf "/Applications/Plasmie.app"; cp -R "$SELF/app/build/Plasmie.app" /Applications/ && ok "installed to /Applications"
    yes "Launch at login?" && osascript -e 'tell application "System Events" to make login item at end with properties {path:"/Applications/Plasmie.app", hidden:true}' >/dev/null 2>&1 && ok "added login item"
    open "/Applications/Plasmie.app"
  else warn "app build failed (needs Xcode Command Line Tools: xcode-select --install)"; fi
else warn "skipped — build later with app/make-app.sh"; fi

say "Done"
echo "  Vault:    $VAULT   →  open in Obsidian (File ▸ Open folder as vault)"
echo "  Menu bar: look for 🧠"
echo "  Re-run this wizard any time — every step is idempotent."
