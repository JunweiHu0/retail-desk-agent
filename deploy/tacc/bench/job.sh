#!/usr/bin/env bash
# Load generator for the vLLM job. Runs as its own CPU job: client calls must
# come from inside the platform, and serve + bench fit the two-job QOS limit.
set -euo pipefail
: "${TACC_WORKDIR:?Submit with tcloud submit}"
: "${TACC_USERDIR:?Submit with tcloud submit}"
: "${SLURM_JOB_ID:?Submit with tcloud submit}"

QWEN_ACTIVATE=${QWEN_ACTIVATE:-/mnt/home/public/course-envs/CSIT6000V/project/activate.sh}
# shellcheck disable=SC1090
source "$QWEN_ACTIVATE"
: "${QWEN_PROJECT_ROOT:?course environment did not set QWEN_PROJECT_ROOT}"

ROOT="$TACC_USERDIR/retail-agent"
URL_FILE="$ROOT/server-url.txt"
OUT="$ROOT/bench/$SLURM_JOB_ID"

# The benchmark imports backend.agent / backend.retail to reuse the app's real
# prompt and tool schemas, so it needs the application venv, not the vLLM one.
VENV="$ROOT/venv"
test -f "$ROOT/venv.tgz" || { printf 'missing venv.tgz; run the setup job first\n' >&2; exit 1; }
if [ ! -x "$VENV/bin/python" ]; then
    UNPACK="/tmp/retail-unpack-$SLURM_JOB_ID"
    VENV="/tmp/retail-venv-$SLURM_JOB_ID"
    rm -rf "$VENV" "$UNPACK"
    mkdir -p "$UNPACK"
    tar -C "$UNPACK" -xzf "$ROOT/venv.tgz"
    mv "$UNPACK/retail-venv" "$VENV"
    rmdir "$UNPACK"
fi

# The serve job publishes its own address; never guess it.
for _ in $(seq 1 60); do
    [ -s "$URL_FILE" ] && break
    printf 'waiting for %s\n' "$URL_FILE"
    sleep 5
done
test -s "$URL_FILE" || { printf 'no server-url.txt; is the serve job running?\n' >&2; exit 1; }

MODEL_BASE_URL=$(head -1 "$URL_FILE" | tr -d '\r')
printf 'BENCH_URL=%s\n' "$MODEL_BASE_URL"
printf 'NODE=%s\n' "$(hostname)"
mkdir -p "$OUT"

export MODEL_BASE_URL
export MODEL_NAME="${MODEL_NAME:-qwen3.8-27b}"
export MODEL_API_KEY="${MODEL_API_KEY:-EMPTY}"
export TAU2_ROOT="$ROOT/tau2-bench"
export TAU2_DATA_DIR="$ROOT/tau2-bench/data"
export RETAIL_DB_PATH="/tmp/retail-bench-$SLURM_JOB_ID.sqlite3"
export AGENT_MODE=demo
export BENCH_OUT="$OUT"

cd "$TACC_WORKDIR"
if [ -f "$TACC_WORKDIR/bench.env" ]; then
    # `set -a` so the values reach the Python process, not just this shell.
    set -a
    # shellcheck disable=SC1091
    . "$TACC_WORKDIR/bench.env"
    set +a
fi
SCRIPT=$(cat "$TACC_WORKDIR/script.txt" 2>/dev/null | tr -d '\r' | head -1)
bash "$QWEN_PROJECT_ROOT/runtime.sh" "$VENV/bin/python" "${SCRIPT:-main.py}"
printf 'BENCH_DONE\n'
