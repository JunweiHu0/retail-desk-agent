#!/usr/bin/env bash
# Source on huoshan. Nothing is installed into the shared Python or root disk.
set -euo pipefail
umask 077
export RETAIL_REMOTE_ROOT=${RETAIL_REMOTE_ROOT:-/vePFS/han/retail-desk}
export UV_CACHE_DIR="$RETAIL_REMOTE_ROOT/cache/uv"
export HF_HOME="$RETAIL_REMOTE_ROOT/cache/huggingface"
export TORCH_HOME="$RETAIL_REMOTE_ROOT/cache/torch"
export TORCH_EXTENSIONS_DIR="$RETAIL_REMOTE_ROOT/cache/torch_extensions"
export TRITON_CACHE_DIR="$RETAIL_REMOTE_ROOT/cache/triton"
export NUMBA_CACHE_DIR="$RETAIL_REMOTE_ROOT/cache/numba"
export FLASHINFER_WORKSPACE_BASE="$RETAIL_REMOTE_ROOT/cache/flashinfer-workspace"
export FLASHINFER_CUBIN_DIR="$RETAIL_REMOTE_ROOT/cache/flashinfer-cubins"
export VLLM_CACHE_ROOT="$RETAIL_REMOTE_ROOT/cache/vllm"
export XDG_CACHE_HOME="$RETAIL_REMOTE_ROOT/cache/xdg"
export CUDA_CACHE_PATH="$RETAIL_REMOTE_ROOT/cache/cuda"
export TMPDIR="$RETAIL_REMOTE_ROOT/tmp"
export npm_config_cache="$RETAIL_REMOTE_ROOT/cache/npm"
export UV_PYTHON_INSTALL_DIR="$RETAIL_REMOTE_ROOT/python"
export UV_LINK_MODE=copy
# Use the installed, versioned LiteLLM cost map during tests and serving.
export LITELLM_LOCAL_MODEL_COST_MAP=${LITELLM_LOCAL_MODEL_COST_MAP:-True}
mkdir -p "$UV_CACHE_DIR" "$HF_HOME" "$TORCH_HOME" "$TORCH_EXTENSIONS_DIR" \
  "$TRITON_CACHE_DIR" "$NUMBA_CACHE_DIR" "$FLASHINFER_WORKSPACE_BASE" \
  "$FLASHINFER_CUBIN_DIR" "$VLLM_CACHE_ROOT" \
  "$XDG_CACHE_HOME" "$CUDA_CACHE_PATH" "$TMPDIR" "$npm_config_cache" \
  "$RETAIL_REMOTE_ROOT/envs" "$RETAIL_REMOTE_ROOT/runs" "$RETAIL_REMOTE_ROOT/state"
