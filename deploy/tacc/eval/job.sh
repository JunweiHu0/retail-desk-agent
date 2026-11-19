#!/usr/bin/env bash
# tau2 evaluation job. One CPU slot, no GPU: the model calls go to the serve job.
#
#   ./deploy/run.sh tacc eval --agent bare --task-ids 0,1
set -euo pipefail
: "${TACC_WORKDIR:?Submit with tcloud submit}"
: "${TACC_USERDIR:?Submit with tcloud submit}"
: "${SLURM_JOB_ID:?Submit with tcloud submit}"

QWEN_ACTIVATE=${QWEN_ACTIVATE:-/mnt/home/public/course-envs/CSIT6000V/project/activate.sh}
# shellcheck disable=SC1090
source "$QWEN_ACTIVATE"
: "${QWEN_PROJECT_ROOT:?course environment did not set QWEN_PROJECT_ROOT}"

ROOT="$TACC_USERDIR/retail-agent"
VENV="$ROOT/venv"
URL_FILE="$ROOT/server-url.txt"

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

for _ in $(seq 1 60); do
    [ -s "$URL_FILE" ] && break
    printf 'waiting for %s\n' "$URL_FILE"
    sleep 5
done
test -s "$URL_FILE" || { printf 'no server-url.txt; is the serve job running?\n' >&2; exit 1; }

export MODEL_BASE_URL=$(head -1 "$URL_FILE" | tr -d '\r')
export MODEL_NAME="${MODEL_NAME:-qwen3.8-27b}"
export MODEL_API_KEY="${MODEL_API_KEY:-EMPTY}"
export AGENT_MODE=live
export TAU2_ROOT="$ROOT/tau2-bench"
# tau2 resolves its data (including the en language pack) from this root.
export TAU2_DATA_DIR="$ROOT/tau2-bench/data"
export RETAIL_DB_PATH="/tmp/retail-eval-$SLURM_JOB_ID.sqlite3"

# tcloud copies the submit directory; args travel as a file, not as env.
EVAL_ARGS=$(cat "$TACC_WORKDIR/args.txt" 2>/dev/null || true)
# A stable name means a killed job can be resubmitted and resume from the
# checkpoint tau2 writes after every task.
NAME=$(cat "$TACC_WORKDIR/name.txt" 2>/dev/null | tr -d '\r' | head -1)
SAVE="$ROOT/tau2-results/${NAME:-$SLURM_JOB_ID}"
mkdir -p "$SAVE"

# Engine-side samples for the whole evaluation: counters only, so the analysis
# can cut per-turn TPOT and KV out of the window between two messages.
SAMPLE_PID=""
if [ -f "$TACC_WORKDIR/sampler.py" ]; then
    bash "$QWEN_PROJECT_ROOT/runtime.sh" "$VENV/bin/python" "$TACC_WORKDIR/sampler.py" \
        --url "${MODEL_BASE_URL%/v1}/metrics" --out "$SAVE/metrics.jsonl" --interval 1 &
    SAMPLE_PID=$!
    trap 'kill "$SAMPLE_PID" 2>/dev/null || true' EXIT
    printf 'SAMPLER=%s\n' "$SAVE/metrics.jsonl"
fi

RUN=(bash "$QWEN_PROJECT_ROOT/runtime.sh" "$VENV/bin/python")
printf 'EVAL_NODE=%s\n' "$(hostname)"
printf 'EVAL_URL=%s\n' "$MODEL_BASE_URL"
printf 'EVAL_ARGS=%s\n' "$EVAL_ARGS"
printf 'EVAL_RESULTS=%s\n' "$SAVE"

cd "$TACC_WORKDIR/app"
# shellcheck disable=SC2086
"${RUN[@]}" -m benchmarks.run_retail $EVAL_ARGS --save-to "$SAVE"
printf 'EVAL_DONE\n'
