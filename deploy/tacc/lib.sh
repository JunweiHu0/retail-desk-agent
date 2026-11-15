#!/usr/bin/env bash
# Shared helpers for the TACC scripts. Source this file; do not execute it.
set -euo pipefail

TACC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TACC_DIR/../.." && pwd)"
STATE="$TACC_DIR/.run"
STAGE="$TACC_DIR/.stage"
mkdir -p "$STATE"

# Optional local config, never committed.
# shellcheck disable=SC1091
if [ -f "$TACC_DIR/env" ]; then
    . "$TACC_DIR/env"
fi

: "${SSH_HOST:=gw.turing.ust.hk}"
: "${SSH_PORT:=30041}"
: "${LOCAL_PORT:=8080}"
: "${AGENT_PORT:=8787}"
: "${SERVE_PORT:=8000}"
: "${TOOL_PARSER:=qwen3_xml}"
: "${EXCLUDE:=}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
SSH_KEY="${SSH_KEY/#\~/$HOME}"

log() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
me()  { id -un; }

find_tcloud() {
    local candidate
    if [ -n "${TCLOUD:-}" ]; then
        [ -x "$TCLOUD" ] || die "TCLOUD=$TCLOUD is not executable"
        return 0
    fi
    candidate="$(command -v tcloud 2>/dev/null || true)"
    if [ -n "$candidate" ]; then
        TCLOUD="$candidate"
        return 0
    fi
    # Unpacked SDK layouts differ per person; try a few bounded globs instead of
    # a filesystem-wide find (fast, and it can only pick already-executable files).
    for candidate in \
        "$HOME/.local/bin/tcloud" \
        "$HOME/bin/tcloud" \
        "$HOME/tcloud" \
        "$HOME"/Downloads/tcloud \
        "$HOME"/Downloads/quickstart-*/linux-amd64-*/tcloud \
        "$HOME"/Downloads/*/linux-amd64-*/tcloud \
        "$HOME"/*/quickstart-*/linux-amd64-*/tcloud \
        "$HOME"/*/*/quickstart-*/linux-amd64-*/tcloud \
        "$PWD"/quickstart-*/linux-amd64-*/tcloud; do
        if [ -x "$candidate" ]; then
            TCLOUD="$candidate"
            return 0
        fi
    done
    die "tcloud not found. Set TCLOUD=/path/to/tcloud in deploy/tacc/env (see deploy/README.md)"
}
find_tcloud

ps_table() { "$TCLOUD" ps 2>/dev/null; }

job_owner() {
    ps_table | awk -v id="$1" '$1==id{print $4; exit}'
}

job_running() {
    ps_table | awk -v id="$1" '$1==id && $5=="R"{found=1} END{exit !found}'
}

my_running_count() {
    ps_table | awk -v u="$(me)" '$4==u && $5=="R"{c++} END{print c+0}'
}

# submit_job <job-dir>: prints the job id; tcloud output goes to stderr.
submit_job() {
    local dir=$1 out id
    out=$(cd "$dir" && "$TCLOUD" submit 2>&1) || {
        printf '%s\n' "$out" >&2
        return 1
    }
    printf '%s\n' "$out" >&2
    id=$(printf '%s\n' "$out" | sed -n 's/.*[Ss]ubmitted[^0-9]*\([0-9][0-9]*\).*/\1/p' | tail -1)
    [ -n "$id" ] || return 1
    printf '%s\n' "$id"
}

cat_log() {
    local dir=$1 file=$2
    (cd "$dir" && "$TCLOUD" cat "$file" 2>/dev/null) || true
}

# wait_log <job-dir> <logfile> <timeout-s> <extended-regex> [<label>]
wait_log() {
    local dir=$1 file=$2 timeout=$3 pattern=$4 label=${5:-$4} elapsed=0
    while [ "$elapsed" -lt "$timeout" ]; do
        if cat_log "$dir" "$file" | grep -qE "$pattern"; then
            return 0
        fi
        sleep 3
        elapsed=$((elapsed + 3))
        if [ $((elapsed % 30)) -eq 0 ]; then
            printf '  ... waiting for %s (%ss)\n' "$label" "$elapsed"
        fi
    done
    printf 'Timed out after %ss waiting for %s in %s\n' "$timeout" "$label" "$file" >&2
    return 1
}

# 10-0-1-11 -> 10.0.1.11 inside a URL
normalise_url() {
    sed -E 's#(https?://)([0-9]+)-([0-9]+)-([0-9]+)-([0-9]+)#\1\2.\3.\4.\5#'
}

tail_log() {
    cat_log "$1" "$2" | tail -20 >&2
}
