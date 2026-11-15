#!/usr/bin/env bash
# vLLM service for the retail agent.
#
# Same knobs as the course serve.sh, plus the two flags the Deep Agents client
# needs: every turn sends `tools`, and without --enable-auto-tool-choice /
# --tool-call-parser vLLM answers 400.
set -euo pipefail
umask 077
: "${TACC_WORKDIR:?Submit with tcloud submit}"
: "${TACC_USERDIR:?Submit with tcloud submit}"
: "${SLURM_JOB_ID:?Submit with tcloud submit}"

QWEN_ACTIVATE=${QWEN_ACTIVATE:-/mnt/home/public/course-envs/CSIT6000V/project/activate.sh}
# shellcheck disable=SC1090
source "$QWEN_ACTIVATE"
: "${QWEN_PROJECT_ROOT:?course environment did not set QWEN_PROJECT_ROOT}"

# serve.sh exports this too; without it vLLM trips on NVML
# (NVMLError_InvalidArgument) before the model loads.
export CUDA_VISIBLE_DEVICES=0,1

TOOL_PARSER="${TOOL_PARSER:-qwen3_xml}"
PORT="${PORT:-8000}"
ROOT="$TACC_USERDIR/retail-agent"
URL_FILE="$ROOT/server-url.txt"

mkdir -p "$ROOT"
# Slurm node names look like 10-0-1-11; peers reach the node as 10.0.1.11.
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
HOST="${IP:-$(hostname)}"
printf '%s\n' "http://${HOST}:${PORT}/v1" > "$URL_FILE.tmp"
mv -f "$URL_FILE.tmp" "$URL_FILE"
cleanup() {
    rm -f "$URL_FILE"
    rm -rf -- "${QWEN_RUN_DIR:-}"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

export QWEN_CACHE_HOME="$TACC_USERDIR/CSIT6000V-project-cache"
mkdir -p -m 700 "$QWEN_CACHE_HOME"

printf 'NODE=%s\n' "$(hostname)"
printf 'SERVICE_BASE_URL=http://%s:%s/v1\n' "$HOST" "$PORT"
printf 'SERVED_MODEL=qwen3.8-27b TOOL_PARSER=%s\n' "$TOOL_PARSER"

printf 'PORT_CHECK_BEGIN\n'
(ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) | grep -E ":${PORT}[[:space:]]" \
    || printf 'PORT_%s_FREE\n' "$PORT"
ps -eo user,pid,ppid,etime,args 2>/dev/null | grep -E '[v]llm|api_server' | head -10 || true
printf 'PORT_CHECK_END\n'

# Who else is on these GPUs before we claim 0.9 of each device.
printf 'GPU_CHECK_BEGIN\n'
nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader 2>&1 | head -4 || true
printf 'GPU_CHECK_END\n'

bash "$QWEN_PROJECT_ROOT/runtime.sh" "$QWEN_PROJECT_ROOT/vllm-env/bin/python" \
    -m vllm.entrypoints.openai.api_server \
    --model "$QWEN_PROJECT_ROOT/models/Qwen3.8-27B-AWQ-INT4" \
    --served-model-name qwen3.8-27b \
    --safetensors-load-strategy prefetch \
    --host 0.0.0.0 --port "$PORT" \
    --tensor-parallel-size 2 --language-model-only --dtype bfloat16 \
    --gpu-memory-utilization 0.90 --max-model-len 32768 \
    --max-num-seqs 4 --max-num-batched-tokens 4096 \
    --reasoning-parser qwen3 --enable-prefix-caching \
    --enable-auto-tool-choice --tool-call-parser "$TOOL_PARSER"
