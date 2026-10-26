#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/opt/node-v22.23.4-linux-x64/bin:$HOME/.local/bin:$PATH"
uv sync --frozen
if [ ! -f frontend/dist/index.html ]; then
  (cd frontend && npm ci --no-fund --no-audit && npm run build)
fi
uv run --frozen python -m backend.server start
