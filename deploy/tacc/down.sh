#!/usr/bin/env bash
# Stop what this deployment started. Only cancels jobs whose owner is you.
#
#   ./deploy/tacc/down.sh              agent + serve (keeps the venv cache)
#   ./deploy/tacc/down.sh --all        also setup (rarely useful)
#   ./deploy/tacc/down.sh 12345 67890  cancel exactly these job ids (must be yours)
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ALL=0
ids=()
for arg in "$@"; do
    case "$arg" in
        --all) ALL=1 ;;
        -h|--help) sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        ''|*[!0-9]*) die "unknown argument: $arg" ;;
        *) ids+=("$arg") ;;
    esac
done

cancel_one() {
    local id=$1 owner
    [ -n "$id" ] || return 0
    owner=$(job_owner "$id")
    if [ -z "$owner" ]; then
        log "job $id: not running; skipping"
        return 0
    fi
    if [ "$owner" != "$(me)" ]; then
        printf 'REFUSING: job %s belongs to %s, not %s\n' "$id" "$owner" "$(me)" >&2
        return 1
    fi
    log "cancelling our job $id"
    "$TCLOUD" cancel -j "$id" >/dev/null 2>&1 || log "  cancel failed (already finished?)"
}

if [ "${#ids[@]}" -gt 0 ]; then
    for id in "${ids[@]}"; do
        cancel_one "$id" || true
    done
else
    for name in agent serve bench; do
        [ -f "$STATE/$name.job" ] && cancel_one "$(cat "$STATE/$name.job")" || true
    done
    if [ "$ALL" = "1" ] && [ -f "$STATE/setup.job" ]; then
        cancel_one "$(cat "$STATE/setup.job")" || true
    fi
fi

if [ -f "$STATE/tunnel.pid" ]; then
    pid=$(cat "$STATE/tunnel.pid")
    if kill -0 "$pid" 2>/dev/null && ps -p "$pid" -o args= 2>/dev/null | grep -q 'ssh -N'; then
        kill "$pid" 2>/dev/null || true
        log "tunnel stopped (pid $pid)"
    fi
    rm -f "$STATE/tunnel.pid"
fi

rm -f "$STATE"/*.job "$STATE"/agent.ip "$STATE"/agent.port "$STATE"/serve.url
log "state cleared (the venv cache on \$TACC_USERDIR/retail-agent is kept)"
