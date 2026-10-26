#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/opt/node-v22.23.4-linux-x64/bin:$HOME/.local/bin:$PATH"
export UV_FROZEN=1
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload &
api_pid=$!
(cd frontend && npm run dev -- --port 5173 --strictPort) &
ui_pid=$!
trap 'kill "$api_pid" "$ui_pid" 2>/dev/null || true' EXIT INT TERM
wait -n "$api_pid" "$ui_pid"
