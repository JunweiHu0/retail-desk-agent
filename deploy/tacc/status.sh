#!/usr/bin/env bash
# Read-only view: jobs, recorded addresses, tunnel, /api/health.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

log "== jobs (all users, read-only) =="
ps_table || log "  (tcloud ps failed)"

log ""
log "== recorded state =="
show_job() {  # show_job <state-file> <stage-dir> <log-prefix>
    local file="$STATE/$1" dir=$2 prefix=$3 id owner
    if [ ! -f "$file" ]; then
        log "$prefix: (not recorded)"
        return 0
    fi
    id=$(cat "$file")
    owner=$(job_owner "$id")
    if [ -n "$owner" ]; then
        log "$prefix: job $id (owner $owner)"
    else
        log "$prefix: job $id (not running)"
    fi
    cat_log "$STAGE/$dir" "slurm_log/${prefix}-${id}.log" | tail -5 || true
}

show_job setup.job setup retail-setup
show_job serve.job serve retail-serve
show_job agent.job agent retail-agent

if [ -f "$STATE/serve.url" ]; then
    log "  serve url: $(cat "$STATE/serve.url")"
fi
if [ -f "$STATE/agent.ip" ]; then
    log "  agent url: http://$(cat "$STATE/agent.ip"):$(cat "$STATE/agent.port" 2>/dev/null || printf '%s' "$AGENT_PORT")"
fi
if [ -s "$STATE/exclude" ]; then
    log "  excluded nodes: $(paste -sd, "$STATE/exclude")"
fi

log ""
log "== tunnel =="
if [ -f "$STATE/tunnel.pid" ] && kill -0 "$(cat "$STATE/tunnel.pid")" 2>/dev/null; then
    log "pid $(cat "$STATE/tunnel.pid") -> http://localhost:${LOCAL_PORT}"
    if curl -sS --max-time 3 "http://127.0.0.1:${LOCAL_PORT}/api/health" 2>/dev/null; then
        log ""
    else
        log "  health: no answer (agent job gone, or tunnel broken)"
    fi
else
    log "not running"
fi
