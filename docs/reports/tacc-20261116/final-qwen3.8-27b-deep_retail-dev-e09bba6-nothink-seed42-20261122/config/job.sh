#!/usr/bin/env bash
# Reuse the original official checkpoint and evaluation conditions on TACC.
set -euo pipefail
umask 077
SECONDS=0
root="$TACC_USERDIR/retail-agent"
results="$root/eval-20261116-nothink"
checkpoint="$results/full/results.json"
cd "$TACC_WORKDIR"
test -s "$checkpoint"

summary() {
    python3 - "$checkpoint" <<'PY'
import collections
import json
import sys

with open(sys.argv[1]) as file:
    data = json.load(file)
rows = data["simulations"]
target = len(data["tasks"])
assert target == 114
assert len({(r["trial"], r["task_id"], r["seed"]) for r in rows}) == len(rows)
valid = [
    r for r in rows
    if r["termination_reason"] != "infrastructure_error"
    and isinstance((r.get("reward_info") or {}).get("reward"), (int, float))
]
counts = collections.Counter(r["termination_reason"] for r in rows)
print(f"RESUME_CHECKPOINT scored={len(valid)}/{target} passed="
      f"{sum(r['reward_info']['reward'] == 1 for r in valid)} stops={dict(counts)}")
sys.exit(0 if len(valid) == target else 10)
PY
}

before=0
summary || before=$?
if [[ "$before" -eq 0 ]]; then
    echo RETAIL_EVAL_COMPLETE
    exit 0
elif [[ "$before" -ne 10 ]]; then
    exit "$before"
fi

mkdir -p "$results/resume-jobs"
archive="$results/resume-jobs/$SLURM_JOB_ID"
mkdir -p "$archive"
cp "$checkpoint" "$archive/before.json"
export URL_FILE="$archive/endpoint.txt"
setsid bash model.sh >"$archive/model.log" 2>&1 &
model_pid=$!
cleanup() {
    trap - EXIT INT TERM
    kill -TERM -- "-$model_pid" 2>/dev/null || true
    sleep 2
    kill -KILL -- "-$model_pid" 2>/dev/null || true
    if [[ -n "${scratch:-}" && "$scratch" = /tmp/retail-eval-"$SLURM_JOB_ID".* ]]; then
        rm -rf -- "$scratch"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

source /mnt/home/public/course-envs/CSIT6000V/project/activate.sh
scratch=$(mktemp -d "/tmp/retail-eval-$SLURM_JOB_ID.XXXXXX")
tar -xzf "$root/venv.tgz" -C "$scratch"
run=(bash "$QWEN_PROJECT_ROOT/runtime.sh" "$scratch/retail-venv/bin/python")
export TAU2_ROOT="$root/tau2-bench"
export TAU2_DATA_DIR="$TACC_WORKDIR/benchmark-data/tau2-data"
export AGENT_MODE=live MODEL_PROVIDER=openai MODEL_NAME=qwen3.8-27b
export MODEL_API_KEY=<REDACTED>
export PYTHONUNBUFFERED=1 LITELLM_LOCAL_MODEL_COST_MAP=True
expected=http://10.0.4.11:8000/v1

for attempt in $(seq 1 220); do
    if ! kill -0 "$model_pid" 2>/dev/null; then
        tail -50 "$archive/model.log" >&2
        exit 1
    fi
    if [[ -s "$URL_FILE" ]]; then
        endpoint=$(head -1 "$URL_FILE")
        if [[ "$endpoint" != "$expected" ]]; then
            printf 'RESUME_UNEXPECTED_ENDPOINT %s (wanted %s)\n' "$endpoint" "$expected" >&2
            exit 1
        fi
        if curl -fs --max-time 3 "$endpoint/models" | grep -qF "$MODEL_NAME"; then
            export MODEL_BASE_URL="$endpoint"
            break
        fi
    fi
    sleep 3
done
if [[ -z "${MODEL_BASE_URL:-}" ]]; then
    printf 'RESUME_MODEL_NOT_READY\n' >&2
    tail -50 "$archive/model.log" >&2
    exit 1
fi

# Make time for shutdown before Slurm ends the model allocation. The runner
# checkpoints every completed simulation; the next slice picks up the rest.
remaining=$((53 * 60 - SECONDS))
if (( remaining < 60 )); then
    echo RESUME_NO_TIME_LEFT >&2
    exit 1
fi
echo "RESUME_MODEL_READY seconds_available=$remaining"
status=0
timeout --signal=INT --kill-after=30s "${remaining}s" "${run[@]}" \
    -m benchmarks.run_retail --all --auto-resume --save-to "$results/full" \
    --user-model "openai/$MODEL_NAME" --judge-model "openai/$MODEL_NAME" \
    --seed 42 --max-steps 100 --timeout 600 --concurrency 3 || status=$?
cp "$checkpoint" "$archive/after.json"
after=0
summary || after=$?
echo "RESUME_RUNNER_EXIT code=$status"
if [[ "$after" -eq 0 ]]; then
    echo RETAIL_EVAL_COMPLETE
elif [[ "$after" -eq 10 && "$status" =~ ^(0|124|130|137)$ ]]; then
    echo RETAIL_EVAL_NEXT_SLICE
else
    exit 1
fi
