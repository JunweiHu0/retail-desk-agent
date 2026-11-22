# Course Project Repository Submission — Retail Desk

**Course:** Advanced AI Computing and Systems
**Group:** Junwei Hu, Shuhan Xu, Yun Zhu, Zechuan Huang
**Submission date:** 2026-11-22
**Submitted revision:** branch `v1`, commit `4699eb0c23670d2532abcf4ecc4862e504b04716`

This document contains the three items required for the course project's GitHub
repository submission:

1. the GitHub repository link,
2. the group contributions,
3. the complete contents of the repository's `README.md`.

The README follows the README instructions in the NSDI '27 Call for Artifacts
and is organized around **Getting Started Instructions** and **Detailed
Instructions**.

---

## 1. GitHub repository

**Repository:** <https://github.com/JunweiHu0/retail-desk-agent>

**Exact submitted revision:**
<https://github.com/JunweiHu0/retail-desk-agent/tree/4699eb0c23670d2532abcf4ecc4862e504b04716>

The repository is public and requires no credentials, so the teaching team can
access it throughout grading. The artifact itself is the source code,
deployment/evaluation scripts, archived measurements, and a portable replay
export. The upstream `tau2-bench` benchmark is intentionally not vendored; the
README pins the exact upstream commit and gives the clone command. No VM image
or paid API key is needed for the offline Getting Started check.

---

## 2. Group contributions

The same table appears in the README in Section 3.

| Member | Contribution |
| --- | --- |
| Yun Zhu | Frontend design: Vue 3 chat and order workspace, streaming message rendering, Markdown/tool-call presentation, replay viewer. |
| Shuhan Xu | Agent and backend design: LangGraph StateGraph runtime, Retail tool bridge, preview/approval/commit flow, SSE transport, SQLite session store. |
| Junwei Hu | Experiment design and benchmark setup/modification: tau2 HTTP evaluator, frozen fixtures, DB comparator, simulator protocol, TACC evaluation protocol, failure analysis. |
| Zechuan Huang | Deployment and experiments: TACC setup/serve/eval jobs, concurrency and wall-time measurements, result collection and reporting. |

---

## 3. Repository README

The text below is the complete contents of `README.md` at the submitted
revision, reproduced verbatim.

<!-- BEGIN README.md -->

# Retail Desk — Artifact README

**Repository:** <https://github.com/JunweiHu0/retail-desk-agent>  
**Submitted revision:** branch `v1` (tip; verify the exact commit with `git rev-parse --short HEAD`)  
**Upstream benchmark:** [sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench), commit `0c69df456a96aa76a1162591574dad9c427a34d7`, MIT.  
**Artifact type:** source code, deployment/evaluation scripts, and recorded measurements. No VM image is required for the offline checks.

## Group contributions

| Member | Contribution |
| --- | --- |
| Yun Zhu | Frontend design: Vue 3 chat and order workspace, streaming message rendering, Markdown/tool-call presentation, replay viewer. |
| Shuhan Xu | Agent and backend design: LangGraph StateGraph runtime, Retail tool bridge, preview/approval/commit flow, SSE transport, SQLite session store. |
| Junwei Hu | Experiment design and benchmark setup/modification: tau2 HTTP evaluator, frozen fixtures, DB comparator, simulator protocol, TACC evaluation protocol, failure analysis. |
| Zechuan Huang | Deployment and experiments: TACC setup/serve/eval jobs, concurrency and wall-time measurements, result collection and reporting. |

Retail Desk is a runnable after-sales customer-service artifact for a single retail store. A customer asks in free text to cancel an order, return or exchange an item, or change an order's items, address, or payment method. The agent authenticates the customer through the store's tools, reads the real order state, and stages every write as a field-level before/after proposal. Nothing changes until the customer approves that proposal; approval executes the operation transactionally and returns a receipt.

The system is Vue 3 + FastAPI + LangGraph. It reuses the official `tau2-bench` Retail database, tools, and policy, and runs the LangGraph `StateGraph` runtime (`lg_b1`) against a TACC-served `Qwen3.8-27B` model for the measurements below.

## Artifact claims

| # | Claim | Evidence | Review cost |
| --- | --- | --- | --- |
| C1 | The complete offline flow runs through the real LangGraph graph and all 16 official Retail tools, with preview → explicit approval → transactional commit. | Offline demo below; 190 backend tests | ~10 min, no API key |
| C2 | The evaluation compares business state, not tool calls: the final database is compared with a target database produced by replaying the official reference actions. | `benchmarks/reference/`; 114-task result below | ~30 min, model access |
| C3 | Ten concurrent episodes are the reported configuration: across the full 114-task pool, strict `pass_3` is 86/114 (0.754) and standard `pass@3` is 105/114 (0.921); the 40-task test split alone is 31/40 strict and 101/120 episode successes. This is a mixed-budget diagnostic: test uses 600 s plus 14 wall-time reruns at 1800 s, development uses 1800 s, and validation uses 600 s plus 33 wall-time reruns at 1800 s. Test seed-0 peak KV was 37.4% with zero preemptions. A separate 20-concurrency diagnostic run was faster (~22 min vs ~33 min) but succeeded on only 24/40 seed-0 test episodes under the 600 s budget, because 4 episodes hit the 300 s model-request timeout and 8 hit the episode budget. | `docs/experiments/2026-11-22-full114/`; `docs/experiments/2026-11-21-formal-test40/`; `test40-c20` TACC run | inspect: 2 min; rerun: TACC access |
| C4 | Every tool call, decision and turn is persisted and exposed; per-turn ATIF-v1.8 trajectories are written for the running app. | `/infra`; `infra/<run_id>/atif.jsonl`; `docs/experiments/2026-11-21-formal-test40/replay/` | ~5 min |
| C5 | A secondary, branch-aware re-score accepts only the user-authorized alternative paths listed in `branch-adjustments.json`; it gives 89/114 strict (0.781) and 106/114 standard `pass@3` (0.930), and never replaces the strict metric. | `docs/experiments/2026-11-22-full114/branch-adjustments.json` | inspect: 2 min |

The project report contains the full claims and measurements. The archived JSON under `docs/experiments/2026-11-22-full114/` (114-task aggregate) and `docs/experiments/2026-11-21-formal-test40/` (test-split reruns and replay) is the artifact-side source of truth for the numbers below.

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

The benchmark is one **114-task Retail pool**; the split labels are bookkeeping,
not different datasets. The `test` portion contains 40 tasks and the remaining
74 `train` tasks are the 54 development plus 20 validation tasks. The 8-task
`smoke` set is a quick-check subset. The reported result below covers all 114
tasks with seeds 0, 1 and 2. The budget is heterogeneous: test uses 600 s plus
14 wall-time reruns at 1800 s, development uses 1800 s, and validation uses
600 s plus 33 wall-time reruns at 1800 s. The 114-task aggregate is therefore a
**mixed-budget diagnostic**, not a single 600 s protocol.

`pass_3` in this artifact is the strict definition: a task passes only if **all
three seeds** match the target database (this is stricter than the usual “any of
three” pass@3). Standard `pass@3` (at least one of three) is also reported.

### Baseline reference

The repository also contains a no-tool lower bound recorded with the official tau2 runner on the same model and test split: `bare_llm`, 40 test tasks, **pass^1 = 0.050 (2/40)**; the full record is `docs/experiments/2026-11-17-tau2-test40/`. It uses tau2's own runner/simulator rather than the HTTP evaluator here, so it is a reference floor, not a per-episode paired baseline. A corrected, explicitly non-official benchmark variant (`retail_ours`: fixed multi-item tool + six patched tasks) and general-agent baselines (`deep_generic`, `llm_agent`) are provided in the `feature/retail-ours-reviewer-fallback` branch; their scores must never be mixed with official tau2 scores.

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

To reproduce the 114-task table, run the same evaluator for each split with the archived budgets: `--split test` at 600 s (then rerun wall-time episodes with `--max-seconds 1800`), `--split development --max-seconds 1800`, and `--split validation` at 600 s (then rerun wall-time episodes at 1800 s). The archived per-chunk results and TACC run ids are in `docs/experiments/2026-11-22-full114/`. The 114-task totals are merged from the three split runs; standard `pass@3` is derived from the per-task seed matrix.

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

## View the recorded replay sessions

The portable replay export contains the recorded evaluation sessions and events, with no account passwords or bearer tokens. The `--data` argument is the path to the replay export directory; run the import from the repository root:

```bash
export RETAIL_DB_PATH="$PWD/runtime/replay.sqlite3"
uv run python scripts/import_replay.py \
  --data docs/experiments/2026-11-21-formal-test40/replay \
  --db "$RETAIL_DB_PATH"
RETAIL_DB_PATH="$RETAIL_DB_PATH" ./deploy/run.sh local --prod
```

Open <http://127.0.0.1:8000>, log in as `replay@retail-demo.example.com` / `Replay@2026!`, and open a session. The per-task matrix links use `http://127.0.0.1:8000/?session=<id>`; `replay-map.json` maps `task:seed` to the session id. Full instructions are in `docs/experiments/2026-11-21-formal-test40/REPLAY.md`.

## Metrics and how they map to the report

`summary.json` reports:

- `db_success_rate`: successful episodes / expected episodes; its aggregate is the episode-success (`pass^1`) estimate;
- `pass_3`: the strict definition, tasks that pass on all three seeds (only when all three seeds are in one summary);
- standard `pass@3`: tasks that pass on at least one of three seeds; derived from the per-task seed matrix;
- branch-aware/adjudicated: a secondary post-hoc re-score that accepts only the alternative paths listed in `branch-adjustments.json`; it is not official tau2 and does not replace strict `pass_3`;
- `complete`: all expected episodes have a valid snapshot and no protocol errors;
- `terminations`: `simulator_finish`, `agent_transferred`, `wall_time_budget`, `agent_error`, etc.;
- `protocol_invalid_episodes`: missing/rejected tau2 pin, policy hash, model or protocol.

The 114-task totals are computed by merging the per-split summaries in `docs/experiments/2026-11-22-full114/`; standard `pass@3` is derived from the per-task seed matrix. Each episode's `score.json` contains the scope and exact mismatches; `trace.json` contains the conversation and events for diagnostics. The app also records per-turn model calls, tool calls, tokens and latencies in `infra/`, and an ATIF-v1.8 trajectory per completed turn.

Where each claim is evidenced:

- C1 / correctness → `tests/`, the offline demo in Getting Started, and the per-task matrix in `docs/experiments/2026-11-21-formal-test40/index.html`;
- C2 / DB evaluation and 114-task result → `benchmarks/reference/`, `docs/experiments/2026-11-22-full114/`, `docs/experiments/2026-11-21-formal-test40/reruns/`;
- C3 / concurrency, KV and latency → `docs/experiments/2026-11-22-full114/`, `docs/experiments/2026-11-21-formal-test40/`, and the TACC concurrency run;
- C4 / persistence and ATIF → `infra/<run_id>/atif.jsonl`, `turns.jsonl`, `requests.jsonl`, and the replay export;
- C5 / adjudicated result → `docs/experiments/2026-11-22-full114/branch-adjustments.json`.

## Recorded results to reproduce

The recorded configuration is `lg_b1`, thinking `auto`, concurrency 10, Qwen3.8-27B on vLLM 0.26; seeds 0, 1 and 2 are separate TACC jobs. The 114-task aggregate is a mixed-budget diagnostic: test uses 600 s plus 14 wall-time reruns at 1800 s, development uses 1800 s, and validation uses 600 s plus 33 wall-time reruns at 1800 s.

| Split | Tasks | Strict `pass_3` | Episode success (`pass^1`) |
| --- | ---: | ---: | ---: |
| `test` | 40 | 31/40 (0.775) | 101/120 (0.842) |
| `development` | 54 | 39/54 (0.722) | 134/162 (0.827)† |
| `validation` | 20 | 16/20 (0.800) | 53/60 (0.883) |
| **all 114** | **114** | **86/114 (0.754)** | **288/342 (0.842)**† |

**Standard `pass@3` (at least one of three seeds): 105/114 (0.921).** Strict `pass_3` requires all three seeds to match the target DB. Episode success is the `pass^1` estimate over the 342 episodes (one attempt per task and seed). † Development episode success and the total are provisional: task 41 seed 0 was still queued at aggregation time. Task 41 seed 2 already succeeded, so neither strict `pass_3` nor standard `pass@3` can change; the only possible update is development episode success 134/162 → 135/162.

Task 20 seed 1 and task 37 seed 0 are confirmed tau2 multi-item-bug cases. They are counted conservatively as failures (wall-time failures at 1800 s) and remain in the 134/162 and 114-task denominators; they are not excluded.

The `complete` flag is true for each run; all terminations and protocol fields are in the per-split `summary.json` files. Test seed-0 peak KV was 37.4%, max running 10, preemptions 0.

**Development failure classification (15 tasks).**

| Class | Tasks |
| --- | --- |
| Real agent behaviour | 31, 87, 88, 110 |
| Wall-time budget | 76, 41 |
| Confirmed tau2 multi-item bug | 20, 37 |
| Path ambiguity / gold-target defect | 0, 19, 63, 91, 98, 107, 109 |

**Secondary/adjudicated result (branch-aware-v1).** This is a post-hoc re-score of clear user-authorized alternative paths in already-recorded episodes; no rerun. It is not an official tau2 score and does not replace the strict numbers above. Only the mismatches listed in `docs/experiments/2026-11-22-full114/branch-adjustments.json` are accepted; all other mismatches remain failures.

| Split | Strict `pass_3` | Standard `pass@3` | Episode success |
| --- | ---: | ---: | ---: |
| `test` | 31/40 (0.775) | 36/40 (0.900) | 101/120 (0.842) |
| `development` | 42/54 (0.778) | 51/54 (0.944) | 140/162 (0.864) |
| `validation` | 16/20 (0.800) | 19/20 (0.950) | 53/60 (0.883) |
| **all 114** | **89/114 (0.781)** | **106/114 (0.930)** | **294/342 (0.860)** |

The JSON lists six candidate episode entries across tasks 63, 91, 98 and 107; all six become net new successes under the conservative rule. The accepted alternatives are 63:2 (gift-card refund explicitly requested), 91:1/2 (same 8GB e-reader variant), 98:2 (other Visa card explicitly requested), and 107:0/2 (same-spec boots variant). The entries not adjusted after inspecting the actual DB are 0:1, 19:1, 98:0/1 and 109:1.

**Concurrency trade-off.** A separate 20-concurrency diagnostic run of test seed 0 completed in ~22 min instead of ~33 min, but only 24/40 episodes succeeded (0.600) under the 600 s budget: 8 `wall_time_budget`, 4 `agent_error` (all `OpenAITimeoutError` at the 300 s model-request timeout), 1 simulator/protocol error, 2 `agent_transferred`, 25 `simulator_finish`. Ten concurrent episodes remain the reported configuration; 20 concurrency is reported only as a throughput/quality trade-off. An 8-task smoke subset at concurrency 10 gives 7/8; the failed task is a complex exchange that left the order in `delivered`.

**Test-split rerun detail.** 17 test episodes hit the 600 s `wall_time_budget`; 3 of them still matched the target DB, and the remaining 14 were rerun with `max_seconds=1800`, all other settings unchanged. 10 of those 14 then matched the target DB. The four remaining failures are not timeouts: task 36 seed 0 (cheapest-variant selection plus an approval loop), task 100 seed 0/2 (the action-card `after` preview makes the simulated user reject, then transfer), and task 100 seed 1 (the simulator exhausts its 4096-token reasoning budget). These reruns are archived under `docs/experiments/2026-11-22-full114/test/`.

**No-tool reference.** The official tau2 runner on the same model and test split gives `bare_llm` pass^1 = 0.050 (2/40), archived under `docs/experiments/2026-11-17-tau2-test40/`. It uses tau2's own harness and simulator, so it is a lower-bound reference, not a paired run.

Raw results for the 114-task run are archived under `docs/experiments/2026-11-22-full114/` (per-split results and summaries, including test and validation reruns). The 40-task test formal run and its portable replay export remain under `docs/experiments/2026-11-21-formal-test40/`. Full per-episode `trace.json`/`snapshot.json` files remain under the TACC run directories described above. The older `docs/experiments/2026-11-17-*` serving recordings belong to the earlier deployment line and are not the `v1` reported result.

## Known limitations and expected variation

- **TACC/Qwen is required for the exact numbers.** The local demo and tests verify the implementation, but the recorded quality and serving numbers use the course `Qwen3.8-27B` endpoint. Without TACC access, reviewers can inspect the archived JSON and rerun the local demo/tests.
- **The tau2 pin is strict.** The evaluator rejects any checkout other than `0c69df4...`; the TACC setup downloads that exact archive and builds a source inventory. This is intentional for reproducibility.
- **Per-episode budget and concurrency.** The 114-task aggregate is mixed-budget: test uses 600 s plus 14 wall-time reruns at 1800 s, development uses 1800 s, and validation uses 600 s plus 33 wall-time reruns at 1800 s. The 20-concurrency diagnostic uses 600 s. At 10 concurrency, 6 of 40 test episodes hit the 600 s budget; at 20 concurrency, 8 hit it and 4 more hit the 300 s model-request timeout. The 10-concurrency configuration is the reported one. Do not read the 114-task total as a single 600 s protocol.
- **Known-bug and provisional tasks.** Task 20 seed 1 and task 37 seed 0 are confirmed tau2 multi-item-bug cases and are counted conservatively as failures, not excluded. Task 41 seed 0 was still queued at aggregation time, so development episode success (134/162) and the 288/342 total are provisional; strict `pass_3` and standard `pass@3` are unaffected.
- **Target is a single reference path.** Success is exact equality with one target DB produced by replaying the official reference actions. Conditional scenarios can have valid alternative paths (for example task 5), and the simulated user can choose a different branch or reason text; the report and `EVAL-VALIDITY.md` classify these separately from agent errors. A secondary branch-aware re-score (`branch-adjustments.json`) accepts only the explicitly listed user-authorized alternatives; it is reported separately and does not replace the strict metric.
- **Upstream tau2 multi-item bug.** The pinned tau2 `modify_pending_order_items` reuses the last variant when applying multi-item modifications. This affects test tasks 36 and 100 (and 20/21/37 in train); the strict target contains the same corrupted values. The `retail_ours` branch fixes this and six ambiguous tasks, but is explicitly a non-official benchmark variant.
- **Simulator budget.** The simulated customer has a 4096-token output limit. Verbose personas can exhaust it while reasoning and return `content=null`, recorded as `simulator_or_protocol_error`; this is an evaluation-side failure, not an agent-tool failure.
- **Thinking mode.** The recorded app uses `MODEL_THINKING=auto`. Qwen may spend the entire 4096-token output budget on reasoning and return an empty answer; this is visible in the per-turn telemetry and contributes to some failures. The evaluation does not hide these failures.
- **The offline demo is deliberately small.** It supports identity verification, order lookup, cancellation and whole-order returns. It does not implement every live-mode modification, and its answers are deterministic rather than model-generated.
- **Evaluation scope.** Only the task customer's user object and that customer's orders are compared. Products, other customers and unrelated database fields are outside the scope.
- **Concurrency results vary with node occupancy.** TACC shared nodes can have other users' GPU memory resident; `up.sh` detects this and retries on another node. The recorded runs were on nodes with free GPUs.
- **Frontend Markdown.** The UI renders a safe Markdown subset (bold/italic, lists, inline/fenced code, headings, links, blockquotes, and GFM tables). User messages are always plain text. Recorded replay sessions can be imported with `scripts/import_replay.py` and viewed through the same UI; see `docs/experiments/2026-11-21-formal-test40/REPLAY.md`.

<!-- END README.md -->

---

<!--
Internal notes (not rendered):
- The report table/figure mapping is pending; the final project report will be
  supplied after the remaining experiments finish.
- Before exporting to PDF, resolve the artifact gaps tracked in the handoff
  notes: uncommitted streaming edits, c20/smoke evidence, LICENSE, and the
  submitted-revision tag.
- Suggested export command (pandoc 3.9 + XeLaTeX):
  pandoc docs/submission.md -o retail-desk-submission.pdf --pdf-engine=xelatex \
    -V geometry:margin=2cm -V CJKmainfont="Noto Sans CJK SC"
-->
