#!/usr/bin/env bash
# Local SSH forward: 127.0.0.1:$LOCAL_PORT -> <agent ip>:<port> on the cluster.
#   ./deploy/tacc/tunnel.sh            uses the address recorded by up.sh
#   ./deploy/tacc/tunnel.sh <ip> <port>
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

IP=${1:-}
PORT=${2:-}
if [ -z "$IP" ] && [ -f "$STATE/agent.ip" ]; then
    IP=$(cat "$STATE/agent.ip")
    PORT=$(cat "$STATE/agent.port" 2>/dev/null || printf '%s' "$AGENT_PORT")
fi
[ -n "$IP" ] || die "no address yet: run ./deploy/run.sh tacc up first, or pass <ip> <port>"
PORT=${PORT:-$AGENT_PORT}

: "${SSH_USER:=}"
[ -n "$SSH_USER" ] || SSH_USER=$(python3 - <<'PY' 2>/dev/null || true
import json, os
path = os.path.expanduser("~/.tcloud/.userconfig")
print(json.load(open(path))["UserName"])
PY
)
SSH_USER=${SSH_USER:-$(me)}
[ -r "$SSH_KEY" ] || die "SSH key not readable: $SSH_KEY (set SSH_KEY in deploy/tacc/env)"

if [ -f "$STATE/tunnel.pid" ]; then
    old=$(cat "$STATE/tunnel.pid")
    if kill -0 "$old" 2>/dev/null; then
        log "tunnel already running (pid $old) -> http://localhost:${LOCAL_PORT}"
        exit 0
    fi
    rm -f "$STATE/tunnel.pid"
fi

log "opening 127.0.0.1:${LOCAL_PORT} -> ${IP}:${PORT} via ${SSH_USER}@${SSH_HOST}:${SSH_PORT}"
nohup ssh -N -p "$SSH_PORT" -i "$SSH_KEY" \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=accept-new \
    -L "127.0.0.1:${LOCAL_PORT}:${IP}:${PORT}" \
    "${SSH_USER}@${SSH_HOST}" >"$STATE/tunnel.log" 2>&1 &
pid=$!
printf '%s\n' "$pid" > "$STATE/tunnel.pid"

sleep 1
if ! kill -0 "$pid" 2>/dev/null; then
    cat "$STATE/tunnel.log" >&2 || true
    rm -f "$STATE/tunnel.pid"
    die "ssh exited immediately (see $STATE/tunnel.log)"
fi

for _ in $(seq 1 15); do
    if curl -sS --max-time 2 "http://127.0.0.1:${LOCAL_PORT}/api/health" 2>/dev/null \
        | grep -q '"ok"'; then
        log "tunnel up: http://localhost:${LOCAL_PORT}  (pid $pid, log $STATE/tunnel.log)"
        exit 0
    fi
    sleep 1
done

cat "$STATE/tunnel.log" >&2 || true
die "tunnel process $pid runs but /api/health did not answer (is the agent job still up?)"
