#!/bin/bash
# Thin shim: run Claude Code against the LOCAL Gemma-4 model, isolated to this
# process. Nothing leaks to interactive sessions — they keep using Claude.
# Usage:  cc-local.sh -p "prompt" [any other claude flags...]
set -euo pipefail

export ANTHROPIC_BASE_URL="http://127.0.0.1:8091"   # mlx-vlm native Anthropic endpoint
export ANTHROPIC_AUTH_TOKEN="local-dummy"           # mlx server ignores auth
# mlx-vlm selects the served model by the request's model id -> use the model path.
# GEMMA_MODEL lets a caller point at a different local model dir; defaults to the
# 4-bit E4B used by the hourly summarize/promote jobs.
GEMMA="${GEMMA_MODEL:-${PLASMIE_HOME:-$HOME/Library/Application Support/Plasmie}/models/gemma-4-e4b}"
export ANTHROPIC_MODEL="$GEMMA"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="$GEMMA"   # route small/background tasks local too
export ANTHROPIC_DEFAULT_SONNET_MODEL="$GEMMA"
export ANTHROPIC_DEFAULT_OPUS_MODEL="$GEMMA"
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

# Ensure the on-demand local model server is loaded (reclaim the ~5GB with mlx-ctl.sh down).
"$(cd "$(dirname "$0")" && pwd)/mlx-ctl.sh" up

exec claude "$@"
