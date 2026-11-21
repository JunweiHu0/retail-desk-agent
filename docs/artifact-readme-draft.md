# Retail Desk — Artifact README (draft)

**Repository:** <https://github.com/JunweiHu0/retail-desk-agent>  
**Submitted revision:** branch `v1` (tip; verify the exact commit with `git rev-parse --short HEAD`)  
**Upstream benchmark:** [sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench), commit `0c69df456a96aa76a1162591574dad9c427a34d7`, MIT.  
**Artifact type:** source code, deployment/evaluation scripts, and recorded measurements. No VM image is required for the offline checks.

Retail Desk is a runnable after-sales customer-service artifact for a single retail store. A customer asks in free text to cancel an order, return or exchange an item, or change an order's items, address, or payment method. The agent authenticates the customer through the store's tools, reads the real order state, and stages every write as a field-level before/after proposal. Nothing changes until the customer approves that proposal; approval executes the operation transactionally and returns a receipt.

The system is Vue 3 + FastAPI + LangGraph. It reuses the official `tau2-bench` Retail database, tools, and policy, and runs the LangGraph `StateGraph` runtime (`lg_b1`) against a TACC-served `Qwen3.8-27B` model for the measurements below.

## Artifact claims

| # | Claim | Evidence | Review cost |
| --- | --- | --- | --- |
| C1 | The complete offline flow runs through the real LangGraph graph and all 16 official Retail tools, with preview → explicit approval → transactional commit. | Offline demo below; 190 backend tests | ~10 min, no API key |
| C2 | The evaluation compares business state, not tool calls: the final database is compared with a target database produced by replaying the official reference actions. | `benchmarks/reference/`; formal test below | ~30 min, model access |
| C3 | Concurrency is a throughput/latency trade-off rather than a KV constraint: the recorded run at 10 concurrent episodes completes 31/40 test tasks with 37.4% peak KV and zero preemptions. | `summary.json`; serve metrics; [TODO: report Table/Figure] | inspect: 2 min; rerun: TACC access |
| C4 | Every tool call, decision and turn is persisted and exposed; per-turn ATIF-v1.8 trajectories are written for the running app. | `docs/` / `/infra`; `infra/<run_id>/atif.jsonl`; [TODO: report Table/Figure] | ~5 min |

The project report contains the full claims and measurements. Replace the `[TODO: report Table/Figure]` references with the final numbers before exporting the submission.

## Repository layout

```text
backend/          FastAPI app, LangGraph StateGraph runtime, Retail tool bridge, SQLite store
frontend/         Vue 3 + TypeScript chat and order workspace
benchmarks/       tau2 Retail HTTP evaluator, fixtures, DB comparator, simulator
tests/            backend integration tests; no paid model calls
deploy/           local/TACC deployment, setup, serve, eval and benchmark jobs
docs/             experiment records, raw measurements, figures, screenshots
scripts/          start / dev / demo-seeding helpers
runtime/          generated data and logs (git-ignored)
```

---

# Getting Started Instructions

## Prerequisites

- Linux or WSL2, Python 3.12 (the project requires `>=3.12,<3.14`)
- [`uv`](https://docs.astral.sh/uv/) for the Python environment
- Node.js 22 and npm for the frontend build
- `git`
- No model credential is needed for the offline demo or the test suite. A live OpenAI-compatible endpoint is needed only for live evaluation. TACC access (`tcloud` + the course gateway) is needed only to reproduce the recorded cluster numbers.

## 1. Clone the artifact and pin the benchmark

`tau2` is intentionally not vendored. The project expects a sibling checkout at the exact pinned commit:

```bash
git clone https://github.com/JunweiHu0/retail-desk-agent.git
cd retail-desk-agent
git checkout v1

git clone https://github.com/sierra-research/tau2-bench.git ../tau2-bench
git -C ../tau2-bench checkout 0c69df456a96aa76a1162591574dad9c427a34d7
```

The evaluator verifies both the commit and the clean `src/`, `data/tau2/domains/retail`, and `pyproject.toml` paths before building fixtures. A different checkout is rejected with `tau2 HEAD must equal 0c69df4...`.

## 2. Install the Python and frontend dependencies

```bash
uv sync --frozen
(cd frontend && npm ci && npm run build)
```

## 3. Verify the build without a model

```bash
uv run pytest -q
```

Expected result:

```text
190 passed
```

These tests use the deterministic offline model and scripted models; they make no paid model calls.

## 4. Run the offline demo

Seed the synthetic demo customers once (this creates three users with three orders each in the configured SQLite database):

```bash
uv run python scripts/seed_demo.py --apply
```

Start the app on `http://127.0.0.1:8000` with the LangGraph runtime:

```bash
BROWSER_AGENT_VARIANT=lg_b1 ./scripts/start.sh
```

`scripts/start.sh` runs `uv sync --frozen`, builds `frontend/dist` if it is missing, and starts the API. The offline model is deterministic and is not a benchmark-capable LLM, but it executes the real tools through the real LangGraph state graph.

Check the health endpoint:

```bash
curl -s http://127.0.0.1:8000/api/health | jq '{mode, model, model_ready, tools}'
```

Expected:

```json
{"mode": "demo", "model": "offline-demo", "model_ready": true, "tools": 16}
```

Open <http://127.0.0.1:8000> and use one of the one-click demo accounts:

| Name | Email | Password |
| --- | --- | --- |
| 李明 | `li.ming@retail-demo.example.com` | `Demo@Retail2026!` |
| 王芳 | `wang.fang@retail-demo.example.com` | `Demo@Retail2026!` |
| 张伟 | `zhang.wei@retail-demo.example.com` | `Demo@Retail2026!` |

Ask `我的订单到哪了？` (or “Where is my order?”). The expected behavior is:

1. `get_user_details` and one `get_order_details` call per order in the SSE tool trace;
2. an answer listing the three demo orders with status and totals;
3. the right-hand order panel showing the same orders.

The offline model supports identity verification, order lookup, cancellation of pending orders, and whole-order returns with the original payment method. It does not implement every modification; use live mode for the full tool surface.

To stop the API:

```bash
uv run python -m backend.server stop
```

## 5. Optional: live mode

Use any OpenAI-compatible tool-calling endpoint:

```bash
export AGENT_MODE=live
export MODEL_BASE_URL=https://api.deepseek.com
export MODEL_NAME=deepseek-flash
export MODEL_API_KEY=...
export MODEL_THINKING=auto
uv run python -m backend.server start
```

The same UI is available at `http://127.0.0.1:8000`. Live mode is required for benchmark episodes; demo mode is explicitly rejected by the evaluator.

---

# Detailed Instructions

## Evaluation principle

The evaluator is in `benchmarks/reference/`. It does **not** score the agent's tool-call sequence. For each task:

1. `build-targets` loads the pinned tau2 Retail tasks and replay the official reference actions on a copy of the initial database (`fixtures.py`).
2. The fixture freezes the comparison scope: the task customer's user object and all of that customer's orders.
3. The evaluator creates an isolated episode through the app's `/internal/eval` endpoints and lets the simulated customer and the agent converse.
4. It finishes and snapshots the episode, then calls `compare_db(target_db, snapshot.db, scope)` (`comparator.py`).
5. Success is exact equality over the scoped objects, including status, items, addresses, payment history, refunds, cancellations and returns. Different tool paths that reach the same final DB succeed.

Tool calls and events are recorded for diagnostics in `trace.json`; they are not the score.

### Evaluation HTTP protocol, scope and budgets

The evaluator drives the app through the same internal endpoints used by the recorded runs:

- `POST /internal/eval/episodes` with `EVAL_API_TOKEN` creates an isolated episode from `initial_db`, `customer_id`, `variant`, `task_id` and `seed`.
- `GET /internal/eval/episodes/{id}`, `POST .../messages` and `POST .../decisions` use that episode's Bearer token.
- `POST .../finish` and `GET .../snapshot` use `EVAL_API_TOKEN`; the episode is frozen before the final database is scored.

The comparison scope is the complete task-customer object plus the orders that customer owned in the initial database. List order and duplicate entries are preserved; dictionary key order is ignored. The scope is never narrowed to the agent's actual edits, and the model saying "done" is not evidence. The target database and reference actions never enter the agent or simulator input.

Per-episode budgets are 80 model calls, 80 tool calls and 600 seconds; note and review calls count toward them. Running only known failures (for example tasks 41 and 47) is a diagnostic, not an overall success rate.

## Test cases and data

| Split | Tasks | Use |
| --- | --- | --- |
| `smoke` | 8 | quick end-to-end check |
| `test` | 40 | main evaluation |
| `development` | 54 | development tasks |
| `validation` | 20 | held-out validation tasks |

The formal result below uses the official **`test` split, seed 0**. `pass_3` requires seeds 0, 1 and 2, each run as a separate TACC job at the same configuration.

## Rerun the main results on TACC

The recorded numbers use the course TACC environment: vLLM 0.26.0, `Qwen3.8-27B-AWQ-INT4`, tensor parallel 2, thinking `auto`.

1. Copy the TACC configuration template and set the account/key:

   ```bash
   cp deploy/tacc/env.example deploy/tacc/env
   # edit: SSH_USER, SSH_KEY
   # add for the recorded run:
   #   MAX_NUM_SEQS=40
   #   MAX_NUM_BATCHED_TOKENS=8192
   ```

2. Start the model only, leaving the second QOS slot for the evaluator:

   ```bash
   ./deploy/run.sh tacc up --serve-only
   ```

   The setup job downloads the pinned tau2 archive and writes `source-manifest.json`; the serve job starts vLLM and writes `server-url.txt`.

3. Submit the HTTP evaluator. The job starts a private app instance, builds fixtures if needed, runs the episodes, and prints a summary:

   ```bash
   EVAL_NAME=formal-test40-20261120 \
     ./deploy/run.sh tacc eval \
     --split test --seeds 0 --variant lg_b1 --concurrency 10
   ```

   The first run of a name builds `fixtures/test`; later runs with the same `EVAL_NAME` reuse them.

4. Results are written under the TACC user directory:

   ```text
   $TACC_USERDIR/retail-agent/tau2-results/<EVAL_NAME>/
     fixtures/test/
     runs/<run_id>/summary.json
     runs/<run_id>/results.json
     runs/<run_id>/task-<id>/seed-<s>/attempt-0/{score.json,final_db.json,mismatches.json,trace.json}
   ```

5. To stop the jobs:

   ```bash
   ./deploy/run.sh tacc down
   ```

For `pass_3`, rerun seeds 1 and 2 with the same `EVAL_NAME` and configuration, then merge the three `results.json` files. The evaluator's `summarize(records, task_ids, [0,1,2])` computes `pass_3`; a task passes only if all three seeds match the target database. In the recorded environment, seeds 1 and 2 are run as separate jobs because the TACC serve job has a one-hour limit.

## Rerun locally with an OpenAI-compatible endpoint

If a TACC allocation is unavailable, the same evaluator can run against a local live app. The model endpoint must support the app's tool calls; the simulator automatically falls back from chat `json_schema` to the Responses API and then to `json_object` when a provider lacks one of those modes.

```bash
export AGENT_MODE=live
export MODEL_BASE_URL=https://api.deepseek.com
export MODEL_NAME=deepseek-flash
export MODEL_API_KEY=...
export MODEL_THINKING=auto
export EVAL_API_TOKEN=local-eval-token
uv run python -m backend.server start

# Build fixtures from the pinned sibling checkout.
uv run python -m benchmarks.run_http build-targets \
  --tau-root ../tau2-bench --split smoke --output eval/fixtures/smoke

# Run one episode.
uv run python -m benchmarks.run_http run \
  --fixtures eval/fixtures/smoke --output eval/runs \
  --base-url http://127.0.0.1:8000 \
  --model-base-url "$MODEL_BASE_URL" --model "$MODEL_NAME" \
  --api-key-env MODEL_API_KEY --eval-token-env EVAL_API_TOKEN \
  --variant lg_b1 --seeds 0 --thinking auto --concurrency 1 --task-ids 0
```

The local live run requires the same model and thinking value on the app and the simulator; the preflight rejects a mismatch.

## Metrics and how they map to the report

`summary.json` reports:

- `db_success_rate`: successful episodes / expected episodes;
- `pass_3`: tasks that pass on seeds 0, 1 and 2 (only when all three seeds are in one summary);
- `complete`: all expected episodes have a valid snapshot and no protocol errors;
- `terminations`: `simulator_finish`, `agent_transferred`, `wall_time_budget`, `agent_error`, etc.;
- `protocol_invalid_episodes`: missing/rejected tau2 pin, policy hash, model or protocol.

Each episode's `score.json` contains the scope and exact mismatches; `trace.json` contains the conversation and events for diagnostics. The app also records per-turn model calls, tool calls, tokens and latencies in `infra/`, and an ATIF-v1.8 trajectory per completed turn.

Report mapping: [TODO: fill in the final report table/figure numbers]

- C1 / correctness → report Section [ ], Table [ ];
- C2 / DB evaluation and formal test → report Table [ ], Figure [ ];
- C3 / concurrency, KV and latency → report Figure [ ], Table [ ];
- C4 / persistence and ATIF → report Figure [ ].

## Recorded results to reproduce

The recorded formal configuration is `test`, seed 0, `lg_b1`, thinking `auto`, concurrency 10, Qwen3.8-27B on vLLM 0.26:

| Metric | Value |
| --- | --- |
| expected episodes | 40 |
| successes | 31 |
| `db_success_rate` | **0.775** |
| `complete` | true |
| terminations | 30 simulator_finish, 3 agent_transferred, 6 wall_time_budget, 1 simulator/protocol error |
| peak KV | 37.4% |
| max running | 10 |
| preemptions | 0 |

A 20-concurrency run of the same split is included as the concurrency comparison: 23/40 (`db_success_rate` 0.575), 12 `wall_time_budget`, 5 `agent_error`, peak KV 60.4%, no preemptions. It was not chosen as the formal configuration because the per-episode 600 s budget is exceeded under the higher latency. The `smoke` split at concurrency 10 gives 7/8; the failed task is a complex exchange that left the order in `delivered`.

**Wall-time rerun (diagnostic).** The three-seed formal cohort gives seed 0/1/2 = 31/30/30 of 40, all 91/120 (0.758), `pass_3` 25/40 (0.625). The 14 episodes that hit the 600 s `wall_time_budget` were rerun with `max_seconds=1800`, all other settings unchanged; 10 of 14 then matched the target DB. The mixed-budget diagnostic numbers are seed 0/1/2 = 34/33/34 of 40, all 101/120 (0.842), `pass_3` 31/40 (0.775). The four remaining failures are not timeouts: task 36 seed 0 (cheapest-variant selection plus an approval loop), task 100 seed 0/2 (the action-card `after` preview makes the simulated user reject, then transfer), and task 100 seed 1 (the simulator exhausts its 4096-token reasoning budget). These reruns are archived under `docs/experiments/2026-11-21-formal-test40/reruns/` and should not be presented as the formal 600 s protocol.

Raw JSON for these runs is archived under `docs/experiments/2026-11-21-formal-test40/` [TODO: copy the TACC run artifacts into the repository before submission]. The TACC paths are listed above. The older `docs/experiments/2026-11-17-*` recordings belong to the earlier deployment line and should not be presented as the `v1` formal result.

## Known limitations and expected variation

- **TACC/Qwen is required for the exact numbers.** The local demo and tests verify the implementation, but the recorded quality and serving numbers use the course `Qwen3.8-27B` endpoint. Without TACC access, reviewers can inspect the archived JSON and rerun the local demo/tests.
- **The tau2 pin is strict.** The evaluator rejects any checkout other than `0c69df4...`; the TACC setup downloads that exact archive and builds a source inventory. This is intentional for reproducibility.
- **Per-episode budget.** The evaluator allows 600 s per episode. At 10 concurrency, 6 of 40 test episodes hit this budget; at 20 concurrency, 12 did and 5 more hit agent errors. The 10-concurrency configuration is the formal one; the remaining timeouts are a known source of variation. Raising the budget would change the protocol and is not part of the recorded result.
- **Thinking mode.** The recorded app uses `MODEL_THINKING=auto`. Qwen may spend the entire 4096-token output budget on reasoning and return an empty answer; this is visible in the per-turn telemetry and contributes to some failures. The evaluation does not hide these failures.
- **The offline demo is deliberately small.** It supports identity verification, order lookup, cancellation and whole-order returns. It does not implement every live-mode modification, and its answers are deterministic rather than model-generated.
- **Evaluation scope.** Only the task customer's user object and that customer's orders are compared. Products, other customers and unrelated database fields are outside the scope.
- **Concurrency results vary with node occupancy.** TACC shared nodes can have other users' GPU memory resident; `up.sh` detects this and retries on another node. The recorded runs were on nodes with free GPUs.
- **Frontend Markdown.** The UI renders a safe Markdown subset (bold/italic, lists, inline/fenced code, headings, links, blockquotes). Tables are not rendered. User messages are always plain text.
