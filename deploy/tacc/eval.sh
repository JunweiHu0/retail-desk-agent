#!/usr/bin/env bash
# Submit a tau2 evaluation against the running serve job.
#
#   ./deploy/tacc/eval.sh --agent bare --task-ids 0,1 --user-model openai/qwen3.8-27b
#
# Everything after the script name goes to benchmarks/run_retail.py.
#
# EVAL_NAME selects the checkpoint directory. tau2 refuses to resume when the
# task set changed, so one name must always mean one fixed task list; use a new
# name for a different batch and merge the results afterwards.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[ -f "$STATE/serve.url" ] || die "no serve address recorded; run './deploy/run.sh tacc up --serve-only' first"
running=$(my_running_count)
if [ "$running" -ge 2 ]; then
    die "you already have $running running jobs (QOS max 2); stop one first"
fi

EVAL_STAGE="$STAGE/eval"
mkdir -p "$EVAL_STAGE"
cp "$TACC_DIR/eval/job.sh" "$TACC_DIR/eval/tuxiv.conf" "$EVAL_STAGE/"
cp "$TACC_DIR/bench/sampler.py" "$EVAL_STAGE/"
printf '%s\n' "$*" > "$EVAL_STAGE/args.txt"
NAME="${EVAL_NAME:-$(date +%Y%m%d-%H%M%S)}"
printf '%s\n' "$NAME" > "$EVAL_STAGE/name.txt"

# The evaluator needs our code, not the frontend: stage it here so the job does
# not depend on an earlier `up` having left its stage directory behind.
APP="$EVAL_STAGE/app"
rm -rf "$APP"
mkdir -p "$APP"
cp -a "$REPO_ROOT/backend" "$APP/backend"
cp -a "$REPO_ROOT/benchmarks" "$APP/benchmarks"
find "$APP" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true

id=$(submit_job "$EVAL_STAGE") || die "eval submit failed"
printf '%s\n' "$id" > "$STATE/eval.job"
log "eval job $id: python -m benchmarks.run_retail $* (results: $NAME, resumable)"
logfile="slurm_log/retail-eval-${id}.log"
wait_log "$EVAL_STAGE" "$logfile" "${EVAL_TIMEOUT:-3300}" \
    'EVAL_DONE|Traceback|Exited with exit code' "eval" \
    || { tail_log "$EVAL_STAGE" "$logfile"; die "see $logfile"; }
if ! cat_log "$EVAL_STAGE" "$logfile" | grep -q 'EVAL_DONE'; then
    tail_log "$EVAL_STAGE" "$logfile"
    die "eval did not finish; see $logfile"
fi
cat_log "$EVAL_STAGE" "$logfile" | grep -E '^(agent=|EVAL_|Running|Average|Pass|Task|✓|✗)' | tail -40
