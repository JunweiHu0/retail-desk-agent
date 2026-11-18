#!/usr/bin/env bash
# Run inside the synced snapshot on huoshan. No GPU allocations.
set -euo pipefail
HERE=$(cd -- "$(dirname -- "$0")" && pwd)
source "$HERE/env.sh"
ROOT=$(cd "$HERE/../.." && pwd)
MODE=${1:-app}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)-$$
LOGDIR="$RETAIL_REMOTE_ROOT/runs/setup-$MODE-$STAMP"
mkdir -p "$LOGDIR"
exec > >(tee "$LOGDIR/setup.log") 2>&1
if [[ "$MODE" = app ]]; then
  [[ -d "$RETAIL_REMOTE_ROOT/envs/app" ]] || uv venv --python /usr/bin/python3.12 "$RETAIL_REMOTE_ROOT/envs/app"
  cd "$ROOT"
  UV_PROJECT_ENVIRONMENT="$RETAIL_REMOTE_ROOT/envs/app" uv sync --frozen
  cd frontend
  npm ci
  npm run build
  cd "$ROOT"
  "$RETAIL_REMOTE_ROOT/envs/app/bin/python" -c 'import fastapi, deepagents, tau2, backend'
  uv pip freeze --python "$RETAIL_REMOTE_ROOT/envs/app/bin/python" > "$LOGDIR/packages.txt"
elif [[ "$MODE" = inference ]]; then
  [[ -d "$RETAIL_REMOTE_ROOT/envs/inference" ]] || uv venv --python /usr/bin/python3.12 "$RETAIL_REMOTE_ROOT/envs/inference"
  uv pip install --python "$RETAIL_REMOTE_ROOT/envs/inference/bin/python" --torch-backend=cu128 vllm==0.17.1
  # Import only. This does not establish working CUDA kernels or model inference.
  CUDA_VISIBLE_DEVICES='' "$RETAIL_REMOTE_ROOT/envs/inference/bin/python" -c \
    'import torch, vllm; print("torch", torch.__version__, "CUDA", torch.version.cuda, "vllm", vllm.__version__)'
  uv pip freeze --python "$RETAIL_REMOTE_ROOT/envs/inference/bin/python" > "$LOGDIR/packages.txt"
else
  echo 'Usage: setup.sh app|inference' >&2
  exit 2
fi
printf 'setup_complete\n' > "$LOGDIR/status"
printf 'Setup artifacts: %s\n' "$LOGDIR"
