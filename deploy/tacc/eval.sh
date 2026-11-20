#!/usr/bin/env bash
# Submit a tau2 evaluation through the real HTTP app (LangGraph runtime).
#
#   ./deploy/tacc/eval.sh --split smoke --seeds 0 --variant lg_b1
#   ./deploy/tacc/eval.sh --split test --task-ids 41,47 --seeds 0
#
# The eval job starts its own private app instance on the node and drives it
# over HTTP, so it needs the serve job (model endpoint) but not the long-lived
# agent job. The course QOS allows two running jobs; start the model with
#   ./deploy/run.sh tacc up --serve-only
# and leave the second slot for this evaluator.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SPLIT=${EVAL_SPLIT:-smoke}
TASK_IDS=${EVAL_TASK_IDS:-}
VARIANT=${EVAL_VARIANT:-lg_b1}
SEEDS=${EVAL_SEEDS:-0}
THINKING=${EVAL_THINKING:-auto}
NAME=${EVAL_NAME:-$(date +%Y%m%d-%H%M%S)}
REBUILD=${EVAL_REBUILD:-0}
EVAL_PORT=${EVAL_PORT:-8790}
CONCURRENCY=${EVAL_CONCURRENCY:-10}

usage() {
    sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --split)    SPLIT=$2; shift 2 ;;
        --task-ids) TASK_IDS=$2; shift 2 ;;
        --variant)  VARIANT=$2; shift 2 ;;
        --seeds)    SEEDS=$2; shift 2 ;;
        --thinking) THINKING=$2; shift 2 ;;
        --name)     NAME=$2; shift 2 ;;
        --port)     EVAL_PORT=$2; shift 2 ;;
        --concurrency) CONCURRENCY=$2; shift 2 ;;
        --rebuild)  REBUILD=1; shift ;;
        -h|--help)  usage; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done

case "$SPLIT" in development|validation|test|smoke) ;; *) die "bad --split: $SPLIT" ;; esac
case "$THINKING" in auto|on|off) ;; *) die "bad --thinking: $THINKING" ;; esac
[[ "$SEEDS" =~ ^[0-2](,[0-2])*$ ]] || die "bad --seeds: $SEEDS (use 0,1,2 subsets)"
[[ -z "$TASK_IDS" || "$TASK_IDS" =~ ^[0-9]+(,[0-9]+)*$ ]] \
    || die "bad --task-ids: $TASK_IDS (comma-separated task ids)"
[[ "$EVAL_PORT" =~ ^[0-9]+$ ]] || die "bad --port: $EVAL_PORT"
[[ "$CONCURRENCY" =~ ^[0-9]+$ ]] || die "bad --concurrency: $CONCURRENCY"
[ "$CONCURRENCY" -ge 1 ] || die "--concurrency must be at least 1"

[ -f "$STATE/serve.url" ] || die "no serve address recorded; run './deploy/run.sh tacc up --serve-only' first"
running=$(my_running_count)
if [ "$running" -ge 2 ]; then
    die "you already have $running running jobs (QOS max 2). Use 'up --serve-only' and stop the agent job first."
fi

EVAL_STAGE="$STAGE/eval"
mkdir -p "$EVAL_STAGE"
cp "$TACC_DIR/eval/job.sh" "$TACC_DIR/eval/tuxiv.conf" "$EVAL_STAGE/"
cp "$TACC_DIR/bench/sampler.py" "$EVAL_STAGE/"
{
    printf 'SPLIT=%q\n' "$SPLIT"
    printf 'TASK_IDS=%q\n' "$TASK_IDS"
    printf 'VARIANT=%q\n' "$VARIANT"
    printf 'SEEDS=%q\n' "$SEEDS"
    printf 'THINKING=%q\n' "$THINKING"
    printf 'NAME=%q\n' "$NAME"
    printf 'REBUILD=%q\n' "$REBUILD"
    printf 'EVAL_PORT=%q\n' "$EVAL_PORT"
    printf 'CONCURRENCY=%q\n' "$CONCURRENCY"
} > "$EVAL_STAGE/eval.env"

# The job starts the app itself; stage the code it imports.
APP="$EVAL_STAGE/app"
rm -rf "$APP"
mkdir -p "$APP"
cp -a "$REPO_ROOT/backend" "$APP/backend"
cp -a "$REPO_ROOT/benchmarks" "$APP/benchmarks"
find "$APP" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true

# The staged app has no .git; run_http.version_manifest() then reads this file
# from the stage root (the parent of app/) for its provenance fields.
app_sha=$(git -C "$REPO_ROOT" rev-parse HEAD)
if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
    app_dirty=true
else
    app_dirty=false
fi
printf '{"application_sha": "%s", "application_dirty": %s}\n' "$app_sha" "$app_dirty" \
    > "$EVAL_STAGE/source-manifest.json"

id=$(submit_job "$EVAL_STAGE") || die "eval submit failed"
printf '%s\n' "$id" > "$STATE/eval.job"
log "eval job $id: split=$SPLIT variant=$VARIANT seeds=$SEEDS thinking=$THINKING concurrency=$CONCURRENCY (results: $NAME)"
logfile="slurm_log/retail-eval-${id}.log"
wait_log "$EVAL_STAGE" "$logfile" "${EVAL_TIMEOUT:-3300}" \
    'EVAL_DONE|Traceback|Exited with exit code' "eval" \
    || { tail_log "$EVAL_STAGE" "$logfile"; die "see $logfile"; }
if ! cat_log "$EVAL_STAGE" "$logfile" | grep -q 'EVAL_DONE'; then
    tail_log "$EVAL_STAGE" "$logfile"
    die "eval did not finish; see $logfile"
fi
cat_log "$EVAL_STAGE" "$logfile" \
    | grep -E '^(EVAL_|FIXTURES_|SUMMARY)|\{"task_id"' | tail -60
