# Retail Desk — Artifact README

**Repository:** <https://github.com/JunweiHu0/retail-desk-agent>  
**Submitted revision:** branch `v1` (tip; verify the exact commit with `git rev-parse --short HEAD`)  
**Upstream benchmark:** [sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench), commit `0c69df456a96aa76a1162591574dad9c427a34d7`, MIT.  
**Artifact type:** source code, deployment/evaluation scripts, and recorded measurements. No VM image is required for the offline checks.

## Group contributions

| Member | Contribution |
| --- | --- |
| Yun Zhu | Frontend design: Vue 3 chat and order workspace. |
| Shuhan Xu | Agent and backend design: LangGraph StateGraph runtime, Retail tool bridge, preview/approval/commit flow, SSE transport, SQLite session store. |
| Junwei Hu | Experiment design and benchmark setup/modification: tau2 HTTP evaluator, frozen fixtures, DB comparator, simulator protocol, TACC evaluation protocol, failure analysis. |
| Zechuan Huang | Deployment and experiments: TACC setup/serve/eval jobs, concurrency and wall-time measurements, result collection and reporting; Markdown/tool-call presentation, replay viewer. |

Retail Desk is a runnable after-sales customer-service artifact for a single retail store. A customer asks in free text to cancel an order, return or exchange an item, or change an order's items, address, or payment method. The agent authenticates the customer through the store's tools, reads the real order state, and stages every write as a field-level before/after proposal. Nothing changes until the customer approves that proposal; approval executes the operation transactionally and returns a receipt.

The system is Vue 3 + FastAPI + LangGraph. It reuses the official `tau2-bench` Retail database, tools, and policy, and runs the LangGraph `StateGraph` runtime against a TACC-served `Qwen3.8-27B` model for the measurements below.

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
- TACC access

## 1. Clone the artifact and pin the benchmark

```bash
git clone https://github.com/JunweiHu0/retail-desk-agent.git
cd retail-desk-agent
git checkout v1

git clone https://github.com/sierra-research/tau2-bench.git ../tau2-bench
git -C ../tau2-bench checkout 0c69df456a96aa76a1162591574dad9c427a34d7
```

The evaluator verifies both the commit and the clean `src/`, `data/tau2/domains/retail`, and `pyproject.toml` paths before building fixtures.

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
209 passed
```

## 4. Run the offline demo

Seed the synthetic demo customers once:

```bash
uv run python scripts/seed_demo.py --apply
```

Start the app on `http://127.0.0.1:8000` with the LangGraph runtime:

```bash
BROWSER_AGENT_VARIANT=lg_b1 ./scripts/start.sh
```

`scripts/start.sh` runs `uv sync --frozen`, builds `frontend/dist` if it is missing, and starts the API.

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

The evaluator is in `benchmarks/reference/`. It does **not** score the agent's tool-call sequence.

An **episode** is one task instance run end to end: one task, one seed, one simulated customer conversation against the app, starting from the task's initial database and ending with a final database snapshot. The 114 tasks × 3 seeds produce 342 episodes.

For each task:

1. `build-targets` loads the pinned tau2 Retail tasks and replay the official reference actions on a copy of the initial database (`fixtures.py`).
2. The fixture freezes the comparison scope: the task customer's user object and all of that customer's orders.
3. The evaluator creates an isolated episode through the app's `/internal/eval` endpoints and lets the simulated customer and the agent converse.
4. It finishes and snapshots the episode, then calls `compare_db(target_db, snapshot.db, scope)` (`comparator.py`).
5. Success is exact equality over the scoped objects, including status, items, addresses, payment history, refunds, cancellations and returns.

### Evaluation HTTP protocol, scope and budgets

The evaluator drives the app through the same internal endpoints used by the recorded runs:

- `POST /internal/eval/episodes` with `EVAL_API_TOKEN` creates an isolated episode from `initial_db`, `customer_id`, `variant`, `task_id` and `seed`.
- `GET /internal/eval/episodes/{id}`, `POST .../messages` and `POST .../decisions` use that episode's Bearer token.
- `POST .../finish` and `GET .../snapshot` use `EVAL_API_TOKEN`; the episode is frozen before the final database is scored.

The comparison scope is the complete task-customer object plus the orders that customer owned in the initial database. List order and duplicate entries are preserved; dictionary key order is ignored. 

Per-episode budgets are 80 model calls, 80 tool calls and 1800 seconds.

## Test cases and data

The benchmark is one **114-task Retail pool**. The reported result below covers all 114 tasks
with seeds 0, 1 and 2, for 342 episodes.

`pass_3` in this artifact is the strict definition: a task passes only if **all
three seeds** match the target database. Standard `pass@3` is also reported.

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

To reproduce the 114-task table, use the archived per-chunk results and TACC run ids in `docs/experiments/2026-11-22-full114/`; the 114-task totals are merged from those runs, and standard `pass@3` is derived from the per-task seed matrix. 

## View the recorded replay sessions

The portable replay export contains the recorded evaluation sessions and events, with no account passwords or bearer tokens. The `--data` argument is the path to the replay export directory; replace `<path-to-data>` with that directory. Run the import from the repository root:

```bash
export RETAIL_DB_PATH="$PWD/runtime/replay.sqlite3"
uv run python scripts/import_replay.py \
  --data <path-to-data> \
  --db "$RETAIL_DB_PATH"
RETAIL_DB_PATH="$RETAIL_DB_PATH" ./deploy/run.sh local --prod
```

Open <http://127.0.0.1:8000>, log in as `replay@retail-demo.example.com` / `Replay@2026!`, and open a session. The per-task matrix links use `http://127.0.0.1:8000/?session=<id>`; `replay-map.json` maps `task:seed` to the session id. Full instructions are in `docs/experiments/2026-11-21-formal-test40/REPLAY.md`.

## Metrics and how they map to the report

The archived results are episode-level comparisons against the scoped target DB. The headline metrics are:

- **Episode success (`pass^1`)**: an episode succeeds when its final DB matches the target DB; success rate = successful episodes / expected episodes;
- **Strict `pass_3`**: tasks that match the target DB on all three seeds;
- **Standard `pass@3`**: tasks that match on at least one of three seeds;

The 114-task totals are merged from the archived runs; standard `pass@3` is derived from the per-task seed matrix. Each episode's `score.json` contains the scope and exact mismatches; `trace.json` contains the conversation and events for diagnostics. The app also records per-turn model calls, tool calls, tokens and latencies in `infra/`, and an ATIF-v1.8 trajectory per completed turn.

## Recorded results to reproduce

The recorded 114-task configuration is thinking `auto`, concurrency 10, Qwen3.8-27B on vLLM 0.26; seeds 0, 1 and 2 are separate TACC jobs. The 114-task aggregate is a mixed-budget diagnostic.

| Tasks | Strict `pass_3` | Standard `pass@3` | Episode success |
| ---: | ---: | ---: | ---: |
| **114** | **89/114 (0.781)** | **106/114 (0.930)** | **294/342 (0.860)** |

These are the final results from `docs/experiments/2026-11-22-full114/merged/results-114-adjusted.json`.

`pass_3` requires all three seeds to match the target DB; standard `pass@3` counts a task if at least one of three seeds matches. Episode success is the `pass^1` estimate over the 342 episodes (one attempt per task and seed).

Raw results for the 114-task run are archived under `docs/experiments/2026-11-22-full114/`.

**KV cache (diagnostic).** During the diagnostic run, the vLLM engine reported a KV-cache peak of 72.4%, an active-period mean of 34.2%, and an active-period p95 of 61.0%; max running was 20, max waiting 9, and there were 0 preemptions. These are engine-global metrics and cannot be attributed to a single episode. Evidence: `docs/experiments/2026-11-22-full114/c20-kv/summary.json`.

## Service quality (LLM judge, 1–5)

The service-quality pass is an evaluation-side DeepSeek `deepseek-flash` judge (thinking, reasoning effort high, max_tokens 32768) over the 342 recorded episodes. It sees the user scenario, the conversation and tool calls, the final scoped DB and the DB comparison; it does not see the target DB or reference actions, and it does not participate in the agent loop. Each aspect is scored 1–5 (1 = poor, 3 = adequate, 5 = excellent), and the overall score is a 1–5 judgment of the conversation as a whole:

- **Intent recognition**: did the agent understand what the customer wanted?
- **Empathy**: did it acknowledge the customer's situation and tone?
- **Policy compliance**: did it follow identity, confirmation and transfer policy?
- **Missing information**: did it ask for details it needed before acting?

| Dimension | Mean (1–5) |
| --- | ---: |
| Intent recognition | 4.66 |
| Empathy | 2.89 |
| Policy compliance | 3.43 |
| Missing information | 4.04 |
| **Overall** | **3.42** |

Read against the 1–5 anchors, intent recognition (4.66) and missing information (4.04) are the strong dimensions; policy compliance (3.43) is adequate; empathy (2.89) is the weakest, just below the "adequate" anchor. The overall mean (3.42) is just above "adequate".

These are judge-derived service-quality scores, not a pass rate and not the DB pass/fail verdict. 0 episodes failed to parse. Evidence: `docs/experiments/2026-11-22-full114/judge-secondary/` (`summary.json`, `verdicts.json`, `payloads.jsonl.gz`, `manifest.json`).

## Known limitations and expected variation

- **We provide a corrected tau2 variant.** The pinned `modify_pending_order_items` reuses the last new item's variant when applying multi-item modifications, which corrupts multi-item target DBs. The `retail_ours` branch fixes that tool and six ambiguous tasks, but its results are explicitly non-official and are never mixed with official tau2 scores.
- **The baseline set is limited.** The artifact includes a no-tool `bare_llm` reference. It does not yet include a tool-visible bare-model or general-purpose-agent baseline on the official 114-task set.
