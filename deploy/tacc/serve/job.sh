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

# Node port 8000 is shared with everyone else on the machine; someone else's
# leftover can be sitting on it. Walk up to the first free port instead of
# dying with "Address already in use".
port_busy() {
    (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -qE ":$1[[:space:]]"
}
port_try=0
while port_busy "$PORT"; do
    printf 'PORT_BUSY %s on %s\n' "$PORT" "$(hostname)"
    PORT=$((PORT + 1))
    port_try=$((port_try + 1))
    if [ "$port_try" -ge 10 ]; then
        printf 'no free port in %s..+9\n' "${PORT}" >&2
        exit 1
    fi
done

mkdir -p "$ROOT"
# Slurm node names look like 10-0-1-11; peers reach the node as 10.0.1.11.
# The job runs inside the course's proot container, so `hostname -I` also lists
# the container bridge (172.17.0.2) and the order is not stable — take the
# cluster address, and fall back to converting the node name itself.
node_ip() {
    local ip
    ip=$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^10\.' | head -1)
    [ -n "$ip" ] || ip=$(hostname 2>/dev/null | sed -nE 's/^([0-9]+)-([0-9]+)-([0-9]+)-([0-9]+)$/\1.\2.\3.\4/p')
    printf '%s' "$ip"
}
IP=$(node_ip)
HOST="${IP:-$(hostname)}"
printf '%s\n' "http://${HOST}:${PORT}/v1" > "$URL_FILE.tmp"
mv -f "$URL_FILE.tmp" "$URL_FILE"
cleanup() {
    # vLLM spawns engine-core children and proot wraps the whole tree; killing
    # only the launcher can leave them holding GPU memory after the job slot is
    # gone. Take the whole process group down instead.
    if [ -n "${VLLM_PID:-}" ] && kill -0 "$VLLM_PID" 2>/dev/null; then
        kill -TERM -"$VLLM_PID" 2>/dev/null || kill -TERM "$VLLM_PID" 2>/dev/null || true
        for _ in $(seq 1 100); do
            kill -0 "$VLLM_PID" 2>/dev/null || break
            sleep 0.1
        done
        kill -KILL -"$VLLM_PID" 2>/dev/null || true
        printf 'VLLM_GROUP_STOPPED\n'
    fi
    if [ -n "${DMON_PID:-}" ]; then
        kill "$DMON_PID" 2>/dev/null || true
    fi
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

# Read-only sampling for the whole service lifetime. dmon only reads the
# driver: it allocates nothing and cannot disturb the model process. One line
# per second per GPU is ~0.5 MB/hour.
DMON_PID=""
GPU_LOG="$ROOT/gpu-$SLURM_JOB_ID.csv"
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi dmon -s pum -d 1 -o DT > "$GPU_LOG" 2>&1 &
    DMON_PID=$!
    printf 'GPU_LOG=%s\n' "$GPU_LOG"
fi

# Own session => its own process group, so cleanup() can signal every child.
setsid bash "$QWEN_PROJECT_ROOT/runtime.sh" "$QWEN_PROJECT_ROOT/vllm-env/bin/python" \
    -m vllm.entrypoints.openai.api_server \
    --model "$QWEN_PROJECT_ROOT/models/Qwen3.8-27B-AWQ-INT4" \
    --served-model-name qwen3.8-27b \
    --safetensors-load-strategy prefetch \
    --host 0.0.0.0 --port "$PORT" \
    --tensor-parallel-size 2 --language-model-only --dtype bfloat16 \
    --gpu-memory-utilization 0.90 --max-model-len 32768 \
    --max-num-seqs 4 --max-num-batched-tokens 4096 \
    --reasoning-parser qwen3 --enable-prefix-caching \
    --enable-auto-tool-choice --tool-call-parser "$TOOL_PARSER" &
VLLM_PID=$!
wait "$VLLM_PID"
