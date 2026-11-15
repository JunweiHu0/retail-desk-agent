#!/usr/bin/env bash
# The app job: FastAPI + Deep Agents + the built frontend, talking to the vLLM
# job over the internal network. Runs as its own platform job (the course
# requires client calls to happen inside a job, not from your laptop).
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
# 8080 is often taken on shared compute nodes; stay clear by default.
PORT="${PORT:-8787}"

test -f "$ROOT/venv.tgz" || {
    printf 'Missing %s/venv.tgz. Run the setup job first (deploy/run.sh tacc up).\n' "$ROOT" >&2
    exit 1
}
test -f "$ROOT/tau2-bench/data/tau2/domains/retail/db.json" || {
    printf 'Missing retail data under %s. Run the setup job first.\n' "$ROOT" >&2
    exit 1
}

# The venv ships as one NFS tarball; unpack it on node-local disk.
if [ ! -x "$VENV/bin/python" ]; then
    export VENV_TGZ="$ROOT/venv.tgz"
    VENV="/tmp/retail-venv-$SLURM_JOB_ID"
    rm -rf "$VENV"
    printf 'EXTRACT_BEGIN %s\n' "$VENV"
    tar -C /tmp -xzf "$VENV_TGZ"
    mv /tmp/retail-venv "$VENV"
    printf 'EXTRACT_DONE\n'
fi

RUN=(bash "$QWEN_PROJECT_ROOT/runtime.sh" "$VENV/bin/python")

# ---- LLM endpoint: the serve job advertises its URL, we just read it ----
SERVER_URL="${MODEL_BASE_URL:-}"
if [ -z "$SERVER_URL" ] && [ -f "$ROOT/server-url.txt" ]; then
    SERVER_URL=$(head -1 "$ROOT/server-url.txt")
fi
MODEL_NAME="${MODEL_NAME:-qwen3.8-27b}"
MODEL_API_KEY="${MODEL_API_KEY:-EMPTY}"
AGENT_MODE="${AGENT_MODE:-}"
if [ -z "$AGENT_MODE" ]; then
    AGENT_MODE=live
    if [ -z "$SERVER_URL" ] || ! "${RUN[@]}" -c "
import sys, urllib.request
req = urllib.request.Request(sys.argv[1].rstrip('/') + '/models',
                             headers={'Authorization': 'Bearer ' + sys.argv[2]})
urllib.request.urlopen(req, timeout=5)" "$SERVER_URL" "$MODEL_API_KEY" 2>/dev/null; then
        printf 'WARN: vLLM endpoint not reachable (%s); falling back to demo mode\n' \
            "${SERVER_URL:-unset}" >&2
        AGENT_MODE=demo
    fi
fi

# SQLite on NFS is slow and WAL-unfriendly; the session DB is disposable.
export TAU2_ROOT="$ROOT/tau2-bench"
export RETAIL_DB_PATH="${RETAIL_DB_PATH:-/tmp/retail-agent-$SLURM_JOB_ID.sqlite3}"
# Per-run telemetry survives the job (small JSONL), so the /infra page can show
# this run after the fact. The model endpoint is read server-side, no key leaks.
export INFRA_DIR="${INFRA_DIR:-$ROOT/infra}"
export INFRA_TAGS="${INFRA_TAGS:-tacc}"
export AGENT_MODE MODEL_NAME MODEL_API_KEY
export MODEL_BASE_URL="$SERVER_URL"
export HOST=0.0.0.0 PORT

cd "$TACC_WORKDIR/app"

if (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -qE ":${PORT}[[:space:]]"; then
    printf 'PORT_BUSY %s on %s\n' "$PORT" "$(hostname)" >&2
    (ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) | grep -E ":${PORT}[[:space:]]" >&2 || true
    exit 1
fi

printf 'NODE=%s\n' "$(hostname)"
printf 'MODE=%s PORT=%s MODEL=%s URL=%s DB=%s\n' \
    "$AGENT_MODE" "$PORT" "$MODEL_NAME" "${SERVER_URL:-none}" "$RETAIL_DB_PATH"
"${RUN[@]}" -m uvicorn backend.main:app --host 0.0.0.0 --port "$PORT" &
SERVER_PID=$!
cleanup() {
    kill "$SERVER_PID" 2>/dev/null || true
    # proot can leave the python child behind; match the exact command line so
    # only this job's server is affected.
    pkill -f "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

ready=0
for _ in $(seq 1 120); do
    if "${RUN[@]}" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT}/api/health', timeout=2)" 2>/dev/null; then
        ready=1
        break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        printf 'SERVER_EXITED\n' >&2
        exit 1
    fi
    sleep 1
done
if [ "$ready" != 1 ]; then
    printf 'STARTUP_TIMEOUT\n' >&2
    exit 1
fi

# The job runs inside the course's proot container; `hostname -I` may list the
# 172.17.0.2 bridge first, which nobody outside can reach. Falls back to the
# node name (10-0-1-11 -> 10.0.1.11), which is what serve does too.
node_ip() {
    local ip
    ip=$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^10\.' | head -1)
    [ -n "$ip" ] || ip=$(hostname 2>/dev/null | sed -nE 's/^([0-9]+)-([0-9]+)-([0-9]+)-([0-9]+)$/\1.\2.\3.\4/p')
    printf '%s' "$ip"
}
IP=$(node_ip)
[ -n "$IP" ] || {
    printf 'could not determine the node IP (hostname -I: %s)\n' "$(hostname -I 2>/dev/null)" >&2
    exit 1
}
printf 'RETAIL_IP=%s\n' "$IP"
printf 'RETAIL_PORT=%s\n' "$PORT"
printf 'RETAIL_URL=http://%s:%s\n' "$IP" "$PORT"
printf 'RETAIL_READY\n'

wait "$SERVER_PID"
