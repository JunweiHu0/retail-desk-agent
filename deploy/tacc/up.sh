#!/usr/bin/env bash
# One-command TACC deployment: deps -> vLLM -> agent, then optionally a tunnel.
#
#   ./deploy/tacc/up.sh [--tunnel] [--skip-setup] [--force-setup]
#
# Never touches anyone else's jobs: it only cancels ids it submitted itself.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

TUNNEL=0
SKIP_SETUP=0
FORCE_SETUP=0
for arg in "$@"; do
    case "$arg" in
        --tunnel)      TUNNEL=1 ;;
        --skip-setup)  SKIP_SETUP=1 ;;
        --force-setup) FORCE_SETUP=1 ;;
        -h|--help)
            sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) die "unknown argument: $arg" ;;
    esac
done

AGENT_BASE_PORT="$AGENT_PORT"
SETUP_TIMEOUT=${SETUP_TIMEOUT:-1900}
SERVE_START_TIMEOUT=${SERVE_START_TIMEOUT:-900}
AGENT_START_TIMEOUT=${AGENT_START_TIMEOUT:-300}
MAX_SERVE_TRIES=3
MAX_AGENT_TRIES=3

# ---------------------------------------------------------------- preflight
running=$(my_running_count)
if [ "$running" -ge 2 ]; then
    ps_table | awk -v u="$(me)" 'NR==1 || $4==u'
    die "you already have $running running jobs (QOS max 2). Stop one with ./deploy/run.sh tacc down"
fi

# ------------------------------------------------------------------ staging
# tcloud submits the directory it runs in; every job gets its own copy there.
stage_job() {  # stage_job <name> <source-dir>
    local name=$1 src=$2
    mkdir -p "$STAGE/$name"
    cp "$src/job.sh" "$src/tuxiv.conf" "$STAGE/$name/"
    if [ -f "$src/requirements.txt" ]; then
        cp "$src/requirements.txt" "$STAGE/$name/"
    fi
    printf '%s' "$STAGE/$name"
}

render_serve_conf() {
    local conf="$STAGE/serve/tuxiv.conf" excludes
    excludes="$EXCLUDE"
    if [ -f "$STATE/exclude" ]; then
        excludes=$(printf '%s,%s' "$EXCLUDE" "$(cat "$STATE/exclude")" | sed 's/^,//')
    fi
    if [ -n "$excludes" ]; then
        sed "s/__EXCLUDE__/${excludes}/" "$TACC_DIR/serve/tuxiv.conf" > "$conf"
    else
        grep -v '^    - exclude=' "$TACC_DIR/serve/tuxiv.conf" > "$conf"
    fi
    printf '%s\n' "$excludes" > "$STATE/exclude.current"
}

stage_app() {
    local dest="$STAGE/agent/app"
    rm -rf "$dest"
    mkdir -p "$dest/frontend"
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --exclude __pycache__ --exclude '*.pyc' \
            "$REPO_ROOT/backend/" "$dest/backend/"
        rsync -a "$REPO_ROOT/frontend/dist/" "$dest/frontend/dist/"
    else
        cp -a "$REPO_ROOT/backend" "$dest/backend"
        cp -a "$REPO_ROOT/frontend/dist" "$dest/frontend/dist"
        find "$dest" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
    fi
}

ensure_frontend_dist() {
    if [ -f "$REPO_ROOT/frontend/dist/index.html" ]; then
        return 0
    fi
    log "frontend/dist missing; building it"
    export PATH="$HOME/.local/opt/node-v22.23.4-linux-x64/bin:$HOME/.local/bin:$PATH"
    command -v npm >/dev/null 2>&1 \
        || die "npm not found; build the frontend first (cd frontend && npm ci && npm run build)"
    (cd "$REPO_ROOT/frontend" && npm ci --no-fund --no-audit && npm run build)
}

rm -rf "$STAGE"
mkdir -p "$STAGE"
stage_job setup "$TACC_DIR/setup" >/dev/null
stage_job serve "$TACC_DIR/serve" >/dev/null
stage_job agent "$TACC_DIR/agent" >/dev/null
render_serve_conf
ensure_frontend_dist
stage_app
log "staged under $STAGE"

# ---------------------------------------------------------------- 1/3 deps
if [ "$SKIP_SETUP" = "1" ]; then
    log "== 1/3 setup: skipped (--skip-setup) =="
else
    log "== 1/3 setup =="
    setup_id=$(submit_job "$STAGE/setup") || die "setup submit failed"
    printf '%s\n' "$setup_id" > "$STATE/setup.job"
    setup_log="slurm_log/retail-setup-${setup_id}.log"
    log "setup job $setup_id"
    wait_log "$STAGE/setup" "$setup_log" "$SETUP_TIMEOUT" \
        'SETUP_DONE|Traceback|Exited with exit code' "setup" \
        || { tail_log "$STAGE/setup" "$setup_log"; die "setup failed; see $setup_log"; }
    if ! cat_log "$STAGE/setup" "$setup_log" | grep -q 'SETUP_DONE'; then
        tail_log "$STAGE/setup" "$setup_log"
        die "setup did not finish; see $setup_log"
    fi
    if cat_log "$STAGE/setup" "$setup_log" | grep -q 'IMPORT_FAILURES [1-9]'; then
        cat_log "$STAGE/setup" "$setup_log" | grep 'IMPORT .* FAIL' >&2
        die "dependency import check failed"
    fi
    if [ "$FORCE_SETUP" = "1" ]; then
        log "  (note: --force-setup only matters if the pinned requirements changed)"
    fi
    cat_log "$STAGE/setup" "$setup_log" | grep -E '^(SETUP_SKIP|SETUP_BUILD|TAR_DONE)' || true
fi

# --------------------------------------------------------------- 2/3 vLLM
log "== 2/3 vLLM =="
serve_try=0
serve_id=""
serve_url=""
while :; do
    serve_try=$((serve_try + 1))
    [ "$serve_try" -le "$MAX_SERVE_TRIES" ] || die "vLLM did not start after $MAX_SERVE_TRIES tries"

    render_serve_conf
    serve_id=$(submit_job "$STAGE/serve") || die "serve submit failed"
    printf '%s\n' "$serve_id" > "$STATE/serve.job"
    serve_log="slurm_log/retail-serve-${serve_id}.log"
    log "serve job $serve_id (try $serve_try); waiting for SERVICE_BASE_URL"
    wait_log "$STAGE/serve" "$serve_log" 360 'SERVICE_BASE_URL=|Traceback|Exited with exit code' \
        "serve address" || { tail_log "$STAGE/serve" "$serve_log"; die "see $serve_log"; }

    raw_url=$(cat_log "$STAGE/serve" "$serve_log" | sed -n 's/^SERVICE_BASE_URL=//p' | head -1)
    [ -n "$raw_url" ] || { tail_log "$STAGE/serve" "$serve_log"; die "could not read SERVICE_BASE_URL"; }
    serve_url=$(printf '%s' "$raw_url" | normalise_url)
    printf '%s\n' "$serve_url" > "$STATE/serve.url"

    log "waiting for model startup (up to ${SERVE_START_TIMEOUT}s)"
    wait_log "$STAGE/serve" "$serve_log" "$SERVE_START_TIMEOUT" \
        'Application startup complete|Engine core initialization failed|CUDA error|out of memory|Address already in use|Exited with exit code' \
        "model startup" || { tail_log "$STAGE/serve" "$serve_log"; die "see $serve_log"; }

    if cat_log "$STAGE/serve" "$serve_log" | grep -q 'Application startup complete'; then
        log "serve ready: $serve_url"
        break
    fi

    tail_log "$STAGE/serve" "$serve_log"
    if cat_log "$STAGE/serve" "$serve_log" | grep -qE 'out of memory|Engine core initialization failed'; then
        node=$(cat_log "$STAGE/serve" "$serve_log" | sed -n 's/^NODE=//p' | head -1)
        if [ -n "$node" ]; then
            job_running "$serve_id" && "$TCLOUD" cancel -j "$serve_id" >/dev/null 2>&1 || true
            printf '%s\n' "$node" >> "$STATE/exclude"
            log "node $node has someone else's GPU memory resident; adding it to exclude and retrying"
            log "  (this only skips the node; it does not touch that job or process)"
            continue
        fi
    fi
    die "vLLM failed; see $serve_log"
done

# --------------------------------------------------------------- 3/3 agent
log "== 3/3 agent =="
agent_try=0
agent_id=""
while :; do
    agent_try=$((agent_try + 1))
    [ "$agent_try" -le "$MAX_AGENT_TRIES" ] || die "agent did not start after $MAX_AGENT_TRIES tries"

    agent_id=$(submit_job "$STAGE/agent") || die "agent submit failed"
    printf '%s\n' "$agent_id" > "$STATE/agent.job"
    agent_log="slurm_log/retail-agent-${agent_id}.log"
    log "agent job $agent_id (port $AGENT_PORT, try $agent_try)"
    wait_log "$STAGE/agent" "$agent_log" "$AGENT_START_TIMEOUT" \
        'RETAIL_READY|PORT_BUSY|SERVER_EXITED|STARTUP_TIMEOUT|Traceback|Exited with exit code' \
        "agent ready" || { tail_log "$STAGE/agent" "$agent_log"; die "see $agent_log"; }

    if cat_log "$STAGE/agent" "$agent_log" | grep -q 'RETAIL_READY'; then
        break
    fi

    tail_log "$STAGE/agent" "$agent_log"
    if cat_log "$STAGE/agent" "$agent_log" | grep -q 'PORT_BUSY'; then
        job_running "$agent_id" && "$TCLOUD" cancel -j "$agent_id" >/dev/null 2>&1 || true
        AGENT_PORT=$((AGENT_PORT + 1))
        log "port ${AGENT_PORT-1} is taken on that node; retrying on $AGENT_PORT"
        continue
    fi
    die "agent failed; see $agent_log"
done

agent_ip=$(cat_log "$STAGE/agent" "$agent_log" | sed -n 's/^RETAIL_IP=//p' | tail -1)
agent_port=$(cat_log "$STAGE/agent" "$agent_log" | sed -n 's/^RETAIL_PORT=//p' | tail -1)
agent_node=$(cat_log "$STAGE/agent" "$agent_log" | sed -n 's/^NODE=//p' | head -1)
mode_line=$(cat_log "$STAGE/agent" "$agent_log" | grep '^MODE=' | tail -1 || true)
[ -n "$agent_ip" ] || die "could not read RETAIL_IP from $agent_log"
agent_port=${agent_port:-$AGENT_PORT}
printf '%s\n' "$agent_ip" > "$STATE/agent.ip"
printf '%s\n' "$agent_port" > "$STATE/agent.port"

if ! printf '%s' "$mode_line" | grep -q 'MODE=live'; then
    log "WARNING: $mode_line"
    log "  the agent fell back to demo mode; vLLM was not reachable at startup."
    log "  run './deploy/run.sh tacc down' and 'up' again once serve is stable."
fi

if [ "$TUNNEL" = "1" ]; then
    log "== tunnel =="
    bash "$TACC_DIR/tunnel.sh" "$agent_ip" "$agent_port"
fi

log ""
log "done."
log "  serve : $serve_url (job $serve_id)"
log "  agent : http://$agent_ip:$agent_port (job ${agent_id}, node ${agent_node:-?})"
log "  $mode_line"
if [ "$TUNNEL" = "1" ]; then
    log "  browse: http://localhost:${LOCAL_PORT}"
else
    log "  browse: ./deploy/run.sh tacc tunnel"
fi
log "  stop  : ./deploy/run.sh tacc down"
