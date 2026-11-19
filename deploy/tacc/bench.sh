#!/usr/bin/env bash
# Submit the fixed-workload benchmark against a running serve job.
#
#   ./deploy/tacc/bench.sh            concurrency 1/2/4, fixed prompt shape
#   ./deploy/tacc/bench.sh --report   just print the last result on the cluster
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

REPORT_ONLY=0
[ "${1:-}" = "--report" ] && REPORT_ONLY=1

BENCH_STAGE="$STAGE/bench"
mkdir -p "$BENCH_STAGE"
cp "$TACC_DIR/bench/job.sh" "$TACC_DIR/bench/main.py" "$TACC_DIR/bench/tuxiv.conf" "$BENCH_STAGE/"
cp "$TACC_DIR/bench/interference.py" "$BENCH_STAGE/" 2>/dev/null || true
printf '%s\n' "${BENCH_SCRIPT:-main.py}" > "$BENCH_STAGE/script.txt"
# Load shape travels as a file: the local environment does not reach the job.
{
    printf 'BENCH_LEVELS=%q\n' "${BENCH_LEVELS:-}"
    printf 'BENCH_REQS=%q\n' "${BENCH_REQS:-}"
} > "$BENCH_STAGE/bench.env"
# main.py imports backend.agent / backend.retail to use the app's real prompt.
rm -rf "$BENCH_STAGE/backend"
cp -a "$REPO_ROOT/backend" "$BENCH_STAGE/backend"
find "$BENCH_STAGE/backend" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true

if [ "$REPORT_ONLY" = "0" ]; then
    [ -f "$STATE/serve.url" ] || die "no serve address recorded; run './deploy/run.sh tacc up --serve-only' first"
    running=$(my_running_count)
    if [ "$running" -ge 2 ]; then
        die "you already have $running running jobs (QOS max 2); stop one first"
    fi
    id=$(submit_job "$BENCH_STAGE") || die "bench submit failed"
    printf '%s\n' "$id" > "$STATE/bench.job"
    log "bench job $id; serve is $([ -f "$STATE/serve.url" ] && cat "$STATE/serve.url")"
    logfile="slurm_log/retail-bench-${id}.log"
    wait_log "$BENCH_STAGE" "$logfile" "${BENCH_TIMEOUT:-1800}" \
        'BENCH_DONE|Traceback|Exited with exit code' "bench" \
        || { tail_log "$BENCH_STAGE" "$logfile"; die "see $logfile"; }
    if ! cat_log "$BENCH_STAGE" "$logfile" | grep -q 'BENCH_DONE'; then
        tail_log "$BENCH_STAGE" "$logfile"
        die "bench did not finish; see $logfile"
    fi
else
    id=$(cat "$STATE/bench.job" 2>/dev/null || true)
    [ -n "$id" ] || die "no bench job recorded"
    logfile="slurm_log/retail-bench-${id}.log"
fi

cat_log "$BENCH_STAGE" "$logfile" | sed -nE '/^(think|conc) /,$p'
