#!/bin/bash
# Plasmie (Plasmie) — installation wizard.
# Gets a fresh machine to a working install: prerequisites, vault, secrets, Python
# env, background loops, and the menu-bar app. (Dev path; friends use the DMG.) Interactive (prompts with defaults).
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
[ "$(uname -m)" = arm64 ] && ok "Apple Silicon" || warn "Intel Mac — Apple's on-device model won't run; summaries, filing and answers stay off."

if have brew; then ok "Homebrew ($(brew --version 2>/dev/null | awk 'NR==1{print $2}'))"
else warn "Homebrew missing (required) — install from https://brew.sh, then re-run."; exit 1; fi

if xcode-select -p >/dev/null 2>&1; then ok "Xcode Command Line Tools"
else warn "Xcode Command Line Tools missing (needed to build the menu-bar app) — run: xcode-select --install, then re-run."; fi

missing=()   # brew-installable prereqs that aren't here yet
if [ -x "$PY312" ] || have python3.12; then ok "python3.12 ($("$PY312" -V 2>&1 | awk '{print $2}'))"; else warn "python3.12 — missing"; missing+=("python@3.12"); fi
if have git; then ok "git"; else warn "git — missing"; missing+=("git"); fi
if [ -d /Applications/Obsidian.app ]; then ok "Obsidian"; else warn "Obsidian — missing (required to view the vault)"; missing+=("--cask obsidian"); fi
avail="$(df -g "$HOME" 2>/dev/null | awk 'NR==2{print $4}')"; [ "${avail:-0}" -ge 6 ] && ok "${avail} GB free" || warn "low disk (${avail:-?} GB) — qmd's search models need ~4 GB."

if [ ${#missing[@]} -gt 0 ]; then
  warn "missing & brew-installable: ${missing[*]}"
  if yes "Install these now with Homebrew?"; then
    for pkg in "${missing[@]}"; do brew install $pkg && ok "installed $pkg" || warn "failed: $pkg"; done
    PY312="$(command -v python3.12 || echo "$PY312")"
  else warn "skipped — install them before the vault/model steps will fully work."; fi
else ok "all prerequisites present"; fi

# 2) vault location -----------------------------------------------------------
say "2/8 · Vault location"
# Keep the vault on the local disk. A cloud folder (OneDrive/iCloud) lives under
# ~/Library/CloudStorage, which macOS blocks background helpers from reading —
# it would silently break the loop. Guard against picking one here.
while :; do
  VAULT="$(ask "Where should your notes live? (a normal folder on this Mac — not a cloud folder)" "$HOME/knowledge")"
  VAULT="${VAULT/#\~/$HOME}"
  case "$VAULT" in
    */Library/CloudStorage/*|*/OneDrive*|*/iCloud*)
      warn "That's a cloud-synced folder. The background helpers can't read there, so the loop would break." ;;
    *) break ;;
  esac
  warn "Please pick a regular folder on your Mac."
done
# upsert, never overwrite: config.env also holds the app's connector On/Off switches
{ grep -v '^VAULT_DIR=' "$SELF/config.env" 2>/dev/null || true; printf 'VAULT_DIR="%s"\n' "$VAULT"; } > "$SELF/config.env.tmp" \
  && mv "$SELF/config.env.tmp" "$SELF/config.env"   # quoted: safe for paths with spaces
ok "vault → $VAULT  (saved to config.env)"

# 3) scaffold vault -----------------------------------------------------------
say "3/8 · Scaffold vault"
"$SELF/scaffold-vault.sh" "$VAULT"

# 4) secrets ------------------------------------------------------------------
say "4/8 · Secrets (Slack ingest)"
# credentials live in the login Keychain (keychain.py), never in a file
if /usr/bin/security find-generic-password -s Plasmie -a SLACK_USER_TOKEN >/dev/null 2>&1; then
  ok "SLACK_USER_TOKEN already in the Keychain"
elif yes "Add a Slack user token now? (enables Slack ingest)"; then
  tok="$(ask "Paste SLACK_USER_TOKEN (xoxp-…)" "")"
  [ -n "$tok" ] && printf '%s\n' "$tok" | "$PY312" "$SELF/keychain.py" set SLACK_USER_TOKEN \
    && ok "saved to the Keychain"
else
  warn "skipped — add it later in Plasmie's Settings (Slack card)"
fi

# 5) python env (the engine is stdlib-only; pytest for the test suite) -----------
say "5/8 · Python environment"
[ -d "$SELF/.venv" ] && ok ".venv exists" || { "$PY312" -m venv "$SELF/.venv"; ok "created .venv"; }
"$VENV_PY" -c "import pytest" 2>/dev/null || "$SELF/.venv/bin/pip" -q install pytest || warn "pytest install failed (tests only)"

# 6) models -------------------------------------------------------------------
say "6/8 · Apple Intelligence + retrieval"
# 6a · generation is Apple's on-device model through plasmie-fm (built with the app in
# step 8). Nothing to download; Apple Intelligence must be on.
"$SELF/app/build-fm.sh" >/dev/null 2>&1 && st="$("$SELF/app/build/plasmie-fm" --check 2>/dev/null)"
case "${st:-}" in
  available) ok "Apple Intelligence on; on-device model ready" ;;
  "") warn "couldn't build plasmie-fm (needs the macOS 26+ SDK) — summaries, filing and answers stay off" ;;
  *) warn "Apple Intelligence: $st — turn it on in System Settings › Apple Intelligence & Siri" ;;
esac

# 6b · retrieval — qmd (Node) indexes the vault and serves search to ask.py + the
# MCP. It fetches its own embedding model; nothing to download here.
command -v qmd >/dev/null && ok "qmd present" \
  || warn "qmd not found — retrieval needs it: npm install -g @tobilu/qmd (Node 22+)"

# 7) background loops — detect already-installed agents -----------------------
say "7/8 · Background loops (launchd)"
DOMAIN="gui/$(id -u)"; loaded=0
total=0   # launchd/*.plist IS the manifest — never a hand-kept list
for t in "$SELF"/launchd/*.plist; do
  total=$((total + 1))
  launchctl print "$DOMAIN/$(basename "$t" .plist)" >/dev/null 2>&1 && loaded=$((loaded + 1))
done
if [ "$loaded" -ge "$total" ]; then
  ok "agents already installed ($loaded/$total loaded)"
  yes "Refresh them (re-point to this install)?" && { "$SELF/launchd/install.sh" && ok "refreshed"; }
elif yes "Install the background agents ($loaded/$total currently loaded)?"; then
  "$SELF/launchd/install.sh" && ok "agents installed"
else warn "skipped — run launchd/install.sh later"; fi

# 8) menu-bar app — detect existing install -----------------------------------
say "8/8 · Menu-bar app"
# Plasmie was renamed Plasmie (ADR 0027); Plasmie carries its data over at first launch.
[ -d "/Applications/Plasmie.app" ] && warn "the older Plasmie.app is still in Applications: quit it and move it to the Bin"
if [ -d "/Applications/Plasmie.app" ]; then
  pgrep -x Plasmie >/dev/null && ok "app already installed (running)" || ok "app already installed"
  yes "Rebuild & reinstall (pick up the latest)?" && install_app
elif yes "Build & install the Plasmie menu-bar app?"; then
  install_app
else warn "skipped — build later with app/make-app.sh"; fi

say "You're all set"
echo "  Ask anything:  press ⌃⌥⌘K, type a question about your notes."
echo "  Menu bar:      look for the brain icon at the top of your screen."
echo "  Your notes:    $VAULT  (open it in Obsidian: File ▸ Open folder as vault)"
echo
echo "  Slack ingest is optional — add a token in Plasmie's Settings any time to turn it on."
echo "  Run this wizard again whenever you like; it only does what's still needed."
