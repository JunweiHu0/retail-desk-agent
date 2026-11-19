#!/usr/bin/env bash
# Serve docs/ on a loopback port so the generated pages open from a URL.
#
#   ./deploy/run.sh docs             http://127.0.0.1:8090/agent-infra.html
#   PORT=9000 ./deploy/run.sh docs   another port
#   HOST=0.0.0.0 ./deploy/run.sh docs   expose on the local network (default: loopback only)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PORT="${PORT:-8090}"
HOST="${HOST:-127.0.0.1}"
command -v python3 >/dev/null 2>&1 || { echo "python3 not found" >&2; exit 1; }

printf '%s\n' "serving $ROOT/docs on http://${HOST}:${PORT}/"
printf '%s\n' "  index      : http://${HOST}:${PORT}/EXPERIMENTS.md"
printf '%s\n' "  baseline   : http://${HOST}:${PORT}/experiments/2026-11-17-agent-29402/view.html"
printf '%s\n' "  charts     : http://${HOST}:${PORT}/figures/serving-baseline.html"
exec python3 "$ROOT/deploy/serve_docs.py" --bind "$HOST" --port "$PORT" --directory "$ROOT/docs"
