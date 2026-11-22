#!/usr/bin/env bash
set -euo pipefail
umask 077
source /mnt/home/public/course-envs/CSIT6000V/project/activate.sh

root="$TACC_USERDIR/retail-agent"
results="$root/eval-20261116-nothink"
mkdir -p "$results"
scratch=$(mktemp -d "/tmp/retail-eval-$SLURM_JOB_ID.XXXXXX")
tar -xzf "$root/venv.tgz" -C "$scratch"
run=(bash "$QWEN_PROJECT_ROOT/runtime.sh" "$scratch/retail-venv/bin/python")
export TAU2_ROOT="$root/tau2-bench"
export TAU2_DATA_DIR="$TACC_WORKDIR/benchmark-data/tau2-data"
export AGENT_MODE=live MODEL_PROVIDER=openai MODEL_NAME=qwen3.8-27b
export MODEL_API_KEY=EMPTY OPENAI_API_KEY=EMPTY
export PYTHONUNBUFFERED=1 LITELLM_LOCAL_MODEL_COST_MAP=True
cd "$TACC_WORKDIR"
for attempt in $(seq 1 240); do
    if [[ -s "$root/server-url.txt" ]]; then
        endpoint=$(head -1 "$root/server-url.txt" 2>/dev/null) || continue
        if [[ -n "$endpoint" ]] && curl -fs --max-time 3 "$endpoint/models" | grep -qF "$MODEL_NAME"; then
            export MODEL_BASE_URL="$endpoint"
            break
        fi
    fi
    sleep 3
done
if [[ -z "${MODEL_BASE_URL:-}" ]]; then
    printf 'EVAL_MODEL_NOT_READY: vLLM /v1/models never became reachable\n' >&2
    exit 1
fi
printf 'EVAL_MODEL_READY %s\n' "$MODEL_NAME"

common=(--user-model "openai/$MODEL_NAME" --judge-model "openai/$MODEL_NAME" --seed 42 --max-steps 100 --timeout 600 --concurrency 3)
run_eval() {
    local label=$1
    shift
    "${run[@]}" -m benchmarks.run_retail "${common[@]}" --save-to "$results/$label" "$@" 2>&1 | tee -a "$results/$label.log"
    if [[ -f "runtime/benchmarks/$label.json" ]]; then
        cp "runtime/benchmarks/$label.json" "$results/$label-result.json"
    fi
}

run_eval smoke --task-ids 0 1 2
"${run[@]}" - "$results/smoke-result.json" <<'PY'
import json
import sys
from pathlib import Path

rows = json.loads(Path(sys.argv[1]).read_text())["simulations"]
stop_reasons = {"agent_error", "user_error", "infrastructure_error", "unexpected_error"}
if len(rows) != 3 or any(row["termination_reason"] in stop_reasons for row in rows):
    raise SystemExit("Smoke test has a model or infrastructure error")
if not any(
    message.get("role") == "assistant" and message.get("tool_calls")
    for row in rows for message in row["messages"]
):
    raise SystemExit("Smoke test did not produce an agent tool call")
print("EVAL_SMOKE_OK", [(row["task_id"], row["reward_info"]["reward"]) for row in rows])
PY
eval_slug=full
printf 'EVAL_FULL_BEGIN\n'
run_eval "$eval_slug" --all
printf 'EVAL_FULL_DONE\n'
