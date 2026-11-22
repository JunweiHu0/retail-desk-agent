#!/usr/bin/env bash
# tau2 evaluation job: start a private app instance, then drive it over HTTP.
#
# The HTTP evaluator (benchmarks/run_http.py) creates isolated episodes through
# the app's /internal/eval endpoints, so this job does not need the long-lived
# retail-agent job. It needs the model endpoint from retail-serve.
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

for _ in $(seq 1 180); do
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
# replay_reference requires the imported package to be the pinned source tree,
# not just the same version installed in site-packages.
export PYTHONPATH="$TAU2_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export RETAIL_DB_PATH="/tmp/retail-eval-$SLURM_JOB_ID.sqlite3"

# tcloud copies the submit directory; config travels as a shell-quoted file.
set -a
# shellcheck disable=SC1091
. "$TACC_WORKDIR/eval.env"
set +a

: "${SPLIT:=smoke}"
: "${TASK_IDS:=}"
: "${VARIANT:=lg_b1}"
: "${SEEDS:=0}"
: "${THINKING:=auto}"
: "${NAME:=$SLURM_JOB_ID}"
: "${REBUILD:=0}"
: "${EVAL_PORT:=8790}"
: "${CONCURRENCY:=10}"
: "${MAX_SECONDS:=600}"

export MODEL_THINKING="$THINKING"
export AGENT_MAX_ACTIVE_SECONDS="$MAX_SECONDS"
APP_PORT="$EVAL_PORT"
SAVE="$ROOT/tau2-results/$NAME"
mkdir -p "$SAVE"
export RETAIL_ARTIFACT_DIR="$SAVE/app-artifacts"
export INFRA_DIR="${INFRA_DIR:-$SAVE/infra}"

# run_http's build-targets verifies the pinned tau2 source inventory, which the
# setup job now ships next to the data.
if [ ! -d "$TAU2_ROOT/src" ] || [ ! -f "$ROOT/source-manifest.json" ]; then
    printf 'EVAL_SETUP_MISSING: %s is not a pinned tau2 source tree\n' "$TAU2_ROOT" >&2
    printf 'run ./deploy/run.sh tacc up --force-setup first\n' >&2
    exit 1
fi

RUN=(bash "$QWEN_PROJECT_ROOT/runtime.sh" "$VENV/bin/python")
EVAL_API_TOKEN=$("${RUN[@]}" -c 'import secrets; print(secrets.token_urlsafe(24))')
export EVAL_API_TOKEN

SAMPLE_PID=""
if [ -f "$TACC_WORKDIR/sampler.py" ]; then
    bash "$QWEN_PROJECT_ROOT/runtime.sh" "$VENV/bin/python" "$TACC_WORKDIR/sampler.py" \
        --url "${MODEL_BASE_URL%/v1}/metrics" --out "$SAVE/metrics.jsonl" --interval 1 &
    SAMPLE_PID=$!
fi

APP_PID=""
cleanup() {
    kill "$APP_PID" 2>/dev/null || true
    # proot can leave the python child behind; match this job's exact command.
    pkill -f "uvicorn backend.main:app --host 127.0.0.1 --port ${APP_PORT}" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
    if [ -n "$SAMPLE_PID" ]; then
        kill "$SAMPLE_PID" 2>/dev/null || true
    fi
    return 0
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

cd "$TACC_WORKDIR/app"
if (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -qE ":${APP_PORT}[[:space:]]"; then
    printf 'PORT_BUSY %s\n' "$APP_PORT" >&2
    exit 1
fi

printf 'EVAL_NODE=%s\n' "$(hostname)"
printf 'EVAL_MODEL_URL=%s\n' "$MODEL_BASE_URL"
printf 'EVAL_MODE=%s MODEL=%s THINKING=%s VARIANT=%s CONCURRENCY=%s MAX_SECONDS=%s\n' \
    "$AGENT_MODE" "$MODEL_NAME" "$THINKING" "$VARIANT" "$CONCURRENCY" "$MAX_SECONDS"
printf 'EVAL_RESULTS=%s\n' "$SAVE"
printf 'SAMPLER=%s\n' "$SAVE/metrics.jsonl"

"${RUN[@]}" -m uvicorn backend.main:app --host 127.0.0.1 --port "$APP_PORT" &
APP_PID=$!
ready=0
for _ in $(seq 1 120); do
    if "${RUN[@]}" -c \
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${APP_PORT}/api/health', timeout=2)" \
        2>/dev/null; then
        ready=1
        break
    fi
    if ! kill -0 "$APP_PID" 2>/dev/null; then
        printf 'APP_EXITED\n' >&2
        exit 1
    fi
    sleep 1
done
if [ "$ready" != 1 ]; then
    printf 'APP_STARTUP_TIMEOUT\n' >&2
    exit 1
fi

FIXTURES="$SAVE/fixtures/$SPLIT"
if [ "$REBUILD" = 1 ] || [ ! -f "$FIXTURES/complete.json" ]; then
    rm -rf "$FIXTURES"
    mkdir -p "$(dirname "$FIXTURES")"
    printf 'FIXTURES_BEGIN %s\n' "$SPLIT"
    "${RUN[@]}" -m benchmarks.run_http build-targets \
        --tau-root "$TAU2_ROOT" --split "$SPLIT" --output "$FIXTURES"
    printf 'FIXTURES_DONE\n'
fi

printf 'WAITING_MODEL_READY %s\n' "$MODEL_BASE_URL"
model_ready=0
for _ in $(seq 1 180); do
    if "${RUN[@]}" -c "
import sys, urllib.request
req = urllib.request.Request(
    sys.argv[1].rstrip('/') + '/models',
    headers={'Authorization': 'Bearer ' + sys.argv[2]},
)
urllib.request.urlopen(req, timeout=5)" "$MODEL_BASE_URL" "$MODEL_API_KEY" 2>/dev/null; then
        model_ready=1
        break
    fi
    sleep 5
done
if [ "$model_ready" != 1 ]; then
    printf 'MODEL_NOT_READY %s\n' "$MODEL_BASE_URL" >&2
    exit 1
fi
printf 'MODEL_READY %s\n' "$MODEL_BASE_URL"

ARGS=(--fixtures "$FIXTURES" --output "$SAVE/runs"
      --base-url "http://127.0.0.1:$APP_PORT"
      --model-base-url "$MODEL_BASE_URL" --model "$MODEL_NAME"
      --api-key-env MODEL_API_KEY --eval-token-env EVAL_API_TOKEN
      --variant "$VARIANT" --seeds "$SEEDS" --thinking "$THINKING"
      --concurrency "$CONCURRENCY" --max-seconds "$MAX_SECONDS" --progress)
if [ -n "$TASK_IDS" ]; then
    ARGS+=(--task-ids "$TASK_IDS")
fi

set +e
"${RUN[@]}" -m benchmarks.run_http run "${ARGS[@]}"
RC=$?
set -e

"${RUN[@]}" - "$SAVE" <<'PY'
import json
import sys
from pathlib import Path

runs = sorted(
    Path(sys.argv[1], "runs").glob("*/summary.json"), key=lambda p: p.stat().st_mtime
)
if runs:
    summary = json.loads(runs[-1].read_text())
    keep = (
        "complete",
        "expected_episodes",
        "recorded_episodes",
        "successes",
        "db_success_rate",
        "pass_3",
        "terminations",
        "protocol_invalid_episodes",
    )
    print("SUMMARY " + json.dumps({key: summary.get(key) for key in keep}, ensure_ascii=False))
    print("SUMMARY_RUN " + str(runs[-1].parent))
PY
printf 'EVAL_DONE\n'
exit "$RC"
