# Course Project Artifact Submission — Retail Desk

**Course:** Advanced AI Computing and Systems
**Group:** HU Junwei, XU Shuhan, ZHU Yun, HUANG Zechuan
**Submission date:** [TODO: date]
**Document status:** DRAFT — contains placeholders marked `[TODO]`; remove this line and all internal notes before exporting to PDF.

This PDF contains the three required items:

1. GitHub repository link (Section 1)
2. Group contributions (Section 2)
3. Full contents of the repository README (Section 3)

---

## 1. GitHub repository

**Repository:** <https://github.com/JunweiHu0/retail-desk-agent>

**Submitted revision:** tag `[TODO: artifact-v1]`, commit `[TODO: full SHA]`

Access statement: the repository is public and requires no credentials. `[TODO: confirm in a private/incognito browser; if it is private, add the teaching team as read-only collaborators and state that here.]`

The repository does not vendor the upstream benchmark. Reviewers must clone `sierra-research/tau2-bench` next to it and check out the pinned commit; the exact commands are in Section 3, "Getting Started Instructions". `[TODO: before submission, either vendor tau2-bench as a pinned submodule or add scripts/setup.sh so that one command prepares it. A fresh clone outside the group currently cannot run uv sync without the sibling checkout.]`

---

## 2. Group contributions

> `[TODO: confirm ownership and wording with each member. The areas below follow the main code components, but the per-person mapping is a placeholder.]`

| Member | Contributions |
| --- | --- |
| **HU Junwei** | Project lead. Agent runtime and tool layer: Deep Agents graph, all 16 official Retail tools, preview/approval engine, tau2 Retail adapter; overall integration and evaluation design. `[TODO: confirm]` |
| **XU Shuhan** | Frontend: Vue 3 + TypeScript chat workspace, SSE progress rendering, field-level before/after confirmation card, responsive layout and browser tests. `[TODO: confirm]` |
| **ZHU Yun** | Backend API and state layer: FastAPI session API, SSE protocol, SQLite schema and transactions, audit log, per-session capability tokens, backend test suite. `[TODO: confirm]` |
| **HUANG Zechuan** | Deployment and measurement: one-command TACC deployment, vLLM tool-calling configuration, fixed-workload serving benchmark, ATIF trajectory recording, figures and experiment records. `[TODO: confirm]` |

All members contributed to the project report, the experiment runs, and the artifact review.

---

## 3. Repository README

> The text below is the complete contents of `README.md` at the submitted revision. In the final PDF it is reproduced verbatim, starting on the next page. It follows the README instructions of the NSDI '27 Call for Artifacts and is organized around **Getting Started Instructions** and **Detailed Instructions**.

<!-- BEGIN README.md -->

# Retail Desk: tool-use retail customer service with human-approved writes

Retail Desk is a runnable artifact for after-sales customer service in a single retail store. A customer asks in free text to cancel an order, return or exchange an item, or change an order's items, address, or payment method. The agent authenticates the customer through the store's tools, reads the real order state, and stages the write as a field-level before/after proposal. Nothing changes until the customer approves that specific proposal; approval executes the operation transactionally and returns a receipt. The system is built with Vue 3, FastAPI, Deep Agents, and SQLite, reuses the official `tau2-bench` Retail database, tools, and policy, and runs end to end against a TACC-served Qwen3.8-27B model.

- **Repository:** <https://github.com/JunweiHu0/retail-desk-agent>
- **Upstream benchmark:** [sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench), commit `0c69df4` (tau2 2.0.0), MIT.
- **Artifact type:** source code, scripts, and recorded measurements. No VM image is required.

## Artifact claims and how to check them

| # | Claim | Evidence in this repository | Review cost |
| --- | --- | --- | --- |
| C1 | The complete after-sales flow runs offline through the real Deep Agents graph and all 16 official Retail tools, with preview → explicit approval → transactional commit. | Getting Started smoke test; 18 backend tests | ~10 min, no API key |
| C2 | The tau2 Retail adapter drives the official evaluator; the no-tool control scores 0.0 on the recorded task subset, establishing the quality floor. | `benchmarks/`, `docs/EXPERIMENTS.md` §2, [TODO: report Table __] | ~30 min, model access |
| C3 | Reasoning tokens dominate latency: disabling thinking moves the first content token ~7× earlier and roughly halves end-to-end latency, while cutting generated tokens ~58% and doubling request throughput. | `docs/data/2026-11-17-serving-baseline.json`, `docs/figures/`, [TODO: report Table __, Figure __] | inspect: 2 min; rerun: GPU access |
| C4 | Every tool call and decision is persisted and exposed; `/infra` shows live vLLM telemetry and per-turn records; benchmark requests are recorded as ATIF-v1.8 trajectories. | `/infra`, `docs/agent-infra.html`, `docs/data/atif/atif.jsonl` (144 trajectories) | ~5 min |

Claims C1 and C4 need no API key. C2 and C3 need a model endpoint. C3's rerun needs the same two-GPU vLLM shape described below; the committed raw JSON is enough to check the reported numbers without rerunning.

## Repository layout

```text
backend/          FastAPI app, Deep Agents runtime, Retail tool bridge, SQLite store
frontend/         Vue 3 + TypeScript chat and order workspace
benchmarks/       tau2 Retail adapter and evaluation entry point
tests/            backend integration tests (no paid model calls)
deploy/           one-command local and TACC deployment; benchmark and eval jobs
docs/             experiment records, raw measurements, figures, screenshots
scripts/          start / dev helpers
runtime/          generated data and logs (git-ignored)
```

## Getting Started Instructions

### Prerequisites

| Requirement | Version used | Notes |
| --- | --- | --- |
| Linux or macOS | Ubuntu 24.04 (WSL2) tested | Windows users should use WSL2 |
| Python | **3.12.x** | 3.13 is not supported: the tau2 import chain still imports `audioop` |
| [uv](https://docs.astral.sh/uv/) | 0.13.7 tested | resolves and installs the pinned environment from `uv.lock` |
| Node.js + npm | 22.23.4 tested | needed once to build the frontend bundle |
| git, curl | any recent | |
| Disk | ~1.5 GB | Python environment ~440 MB, `node_modules` ~120 MB, plus caches |
| Model endpoint | optional for Getting Started | any OpenAI-compatible chat-completions service with tool calling; needed only for live mode and the tau2 evaluation |

No API key is needed for the Getting Started example: the default `AGENT_MODE=demo` uses a deterministic local model that still drives the real Deep Agents graph and the real Retail tools.

### Setup

The backend declares the upstream benchmark as a sibling path dependency, so clone it next to this repository:

```bash
git clone https://github.com/JunweiHu0/retail-desk-agent.git
cd retail-desk-agent

git clone https://github.com/sierra-research/tau2-bench.git ../tau2-bench
git -C ../tau2-bench checkout 0c69df456a96aa76a1162591574dad9c427a34d7

cp .env.example .env          # defaults to AGENT_MODE=demo
uv sync --frozen              # installs the pinned environment, including editable tau2
```

`uv sync` must be run with the sibling `../tau2-bench` checkout present. The PyPI package named `tau2` is an unrelated materials-science package; do not install it.

### End-to-end example (demo mode, no API key)

This is the smallest check that the system works: one conversation, one real tool sequence, one staged write, one approval, and a verified data change.

#### 1. Start the server

```bash
bash scripts/start.sh
```

`scripts/start.sh` runs `uv sync --frozen`, builds the frontend bundle if `frontend/dist/index.html` is missing, and starts the API and static frontend on port 8000. Expected final line:

```text
Retail Desk ready: http://127.0.0.1:8000 (PID <pid>)
```

#### 2. Check health

```bash
curl -s http://127.0.0.1:8000/api/health
```

Expected output:

```json
{"status":"ok","mode":"demo","model":"offline-demo","model_ready":true,"tools":16,"domain":"retail"}
```

`tools` must be `16` and `mode` must be `demo` for this example.

#### 3. Run one conversation through the API

The demo model understands the three scenarios shown on the home page. The script below reads a synthetic customer and a pending order from the benchmark data, asks to cancel that order, inspects the staged proposal, approves it, and verifies the status change.

```bash
BASE=http://127.0.0.1:8000

S=$(curl -s -X POST "$BASE/api/sessions")
SID=$(printf '%s' "$S" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
TOK=$(printf '%s' "$S" | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')
read -r EMAIL OID <<<"$(curl -s "$BASE/api/samples" | python3 -c 'import json,sys;s=json.load(sys.stdin)["samples"][0];print(s["email"],s["order_id"])')"

echo "customer=$EMAIL order=$OID"

# Ask for a cancellation. The message is in Chinese because the deterministic
# demo model matches the same phrasing as the UI; the live mode accepts free text.
curl -sN -X POST "$BASE/api/sessions/$SID/messages" \
  -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d "{\"message\":\"我的邮箱是 $EMAIL，请取消订单 $OID，原因是不再需要\"}"
```

Expected event sequence (one JSON object per `data:` line; IDs and timings vary):

```text
data: {"type":"status","message":"正在理解请求并查询业务工具"}
data: {"type":"tool_start","name":"find_user_id_by_email","args":{"email":"..."}}
data: {"type":"tool_end","name":"find_user_id_by_email","result":"<user_id>","ok":true,...}
data: {"type":"tool_start","name":"get_user_details","args":{"user_id":"..."}}
data: {"type":"tool_end","name":"get_user_details",...}
data: {"type":"tool_start","name":"get_order_details","args":{"order_id":"..."}}
data: {"type":"tool_end","name":"get_order_details",...}
data: {"type":"tool_end","name":"cancel_pending_order","result":{"status":"awaiting_confirmation","action_id":"<action_id>",...}}
data: {"type":"done",...}
```

The four tool calls, in order, are `find_user_id_by_email`, `get_user_details`, `get_order_details`, and `cancel_pending_order`. The last one returns `awaiting_confirmation`; the order is **not** changed yet.

Inspect the staged proposal:

```bash
curl -s "$BASE/api/sessions/$SID" -H "Authorization: Bearer $TOK" \
  | python3 -c 'import json,sys;print(json.dumps(json.load(sys.stdin)["context"]["pending"],ensure_ascii=False,indent=2))'
```

Expected: a `pending` object with `tool: "cancel_pending_order"`, the order id, and `before`/`after` snapshots. Re-reading the order confirms its status is still `pending`.

Approve the exact proposal:

```bash
AID=$(curl -s "$BASE/api/sessions/$SID" -H "Authorization: Bearer $TOK" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["context"]["pending"]["id"])')

curl -s -X POST "$BASE/api/sessions/$SID/decisions" \
  -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d "{\"action_id\":\"$AID\",\"approve\":true}"
```

Expected output (abridged):

```json
{"receipt":{"status":"executed","tool":"cancel_pending_order","result":{"order_id":"...","status":"cancelled"}}}
```

The same `action_id` is single-use; repeating the decision returns HTTP 409 and does not refund or cancel twice.

Verify the stored state:

```bash
curl -s "$BASE/api/sessions/$SID" -H "Authorization: Bearer $TOK" \
  | python3 -c 'import json,sys;print([(o["order_id"],o["status"]) for o in json.load(sys.stdin)["context"]["orders"]])'
```

The approved order must now appear as `cancelled`.

#### 4. Check the browser UI (optional)

Open <http://127.0.0.1:8000>. The home page offers three sample customers (pending, delivered, processed orders). Run the pending-order scenario to see streaming tool progress and the confirmation card; the order status updates only after clicking approve. API documentation is at <http://127.0.0.1:8000/docs>; live serving telemetry and per-turn records are at <http://127.0.0.1:8000/infra/>.

#### 5. Stop

```bash
uv run --frozen python -m backend.server stop
```

### Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `ModuleNotFoundError: audioop` | Python 3.13 | Use Python 3.12 (`.python-version` pins it) |
| `uv sync` cannot resolve `tau2` | sibling `../tau2-bench` missing | run the clone command above |
| `Port 8000 is already occupied` | another process owns the port | stop it, or set `PORT` in `.env` |
| Health shows `"model_ready": false` | `.env` sets `AGENT_MODE=live` without a key | use `AGENT_MODE=demo` for this example |
| Frontend is blank / 404 | `frontend/dist` missing | `cd frontend && npm ci && npm run build` |
| Browser cannot reach `localhost:8000` from Windows | WSL networking | use the WSL address shown by `hostname -I`, or run the browser inside WSL |

## Detailed Instructions

### 1. Automated tests

Backend integration tests use temporary databases and the deterministic demo model. They make no paid model calls.

```bash
uv run --frozen pytest -q
```

Expected:

```text
18 passed, 1 warning in ~7s
```

Coverage includes: identity and cross-customer access control, session customer locking, all seven write tools, previews having no side effects, approve/reject, duplicate approval, stale snapshots, restart recovery, SSE event ordering, per-session capability tokens, human handoff, amount calculation, and the tau2 adapter boundary. A separate test exercises the real ChatOpenAI transport through `httpx.MockTransport`, including tool schemas and the forced stop after a write preview, without sending a network request.

Lint:

```bash
uv run --frozen ruff check backend benchmarks tests
uv run --frozen ruff format --check backend benchmarks tests
```

Frontend build and browser tests:

```bash
cd frontend
npm ci
npm run build
npx playwright install chromium

# Terminal 1: a disposable database, separate from the demo database
cd .. && RETAIL_DB_PATH=runtime/e2e.sqlite3 uv run --frozen uvicorn backend.main:app \
  --host 127.0.0.1 --port 8001

# Terminal 2
cd frontend && BASE_URL=http://127.0.0.1:8001 npm run test:e2e
```

Expected: 2 passed. The browser tests confirm one cancellation and reject one return; they change only the SQLite file passed in `RETAIL_DB_PATH` (delete it afterwards to reset).

### 2. Quality evaluation on tau2 Retail

This runs the official tau2 Retail environment and scorer. It requires a tool-calling model endpoint, because the agent must call real tools, and a model for tau2's user simulator.

Configure the endpoint in `.env` (credentials stay server-side):

```dotenv
AGENT_MODE=live
MODEL_NAME=<tool-calling model name>
MODEL_API_KEY=<key>
MODEL_BASE_URL=<OpenAI-compatible base URL, ending in /v1>
```

Run the no-tool control (quality floor) and the system:

```bash
# Control: same model and policy, zero tools. Should score near zero on write tasks.
uv run --frozen python -m benchmarks.run_retail \
  --agent bare --task-ids 0,1 --split base --num-trials 1 \
  --user-model openai/gpt-4.1-mini --save-to artifact-bare-0-1

# System under test. [TODO: replace with the exact task list used in the report.]
uv run --frozen python -m benchmarks.run_retail \
  --agent deep_retail --task-ids <comma-separated ids> --split base --num-trials 1 \
  --user-model openai/gpt-4.1-mini --save-to artifact-deep-retail
```

- `--user-model` is the tau2/LiteLLM model name for the simulated customer; it is separate from the agent's `MODEL_NAME`. If the simulator uses a different provider, set that provider's environment variables as documented by LiteLLM.
- Results are written to `<tau2-bench>/data/simulations/<save_to>/results.json`. Inspect them with `uv run --frozen tau2 view`.
- `--save-to` must be unique per run; tau2 refuses to overwrite an existing result.

Recorded control run (2026-11-17, TACC-served `qwen3.8-27b`, tasks 0-1, one trial):

```text
Average Reward 0.0000   Pass^1 0.000
Read Actions 0/8   Write Actions 0/2   DB Match 0/2
Termination: Normal Stop 2
```

This is the expected floor: without tools the model cannot read or modify the database. The system's pass^1/pass^3 numbers on the full task set are in [TODO: report Table __]; the corresponding `results.json` is [TODO: commit it under `docs/data/`].

Known limitation: this entry point evaluates the Retail domain of the checked-out tau2 version. It is **not** the frozen `text-v1` leaderboard submission workflow, and the numbers are not directly comparable to published leaderboard results.

### 3. Serving benchmark (reasoning on/off, concurrency 1/2/4)

This reproduces the latency/token measurements behind Claim C3. It needs two 24 GB GPUs running vLLM with the model used in the report.

Reference environment:

| Item | Value |
| --- | --- |
| Cluster / partition | course CSIT6000V platform, `tacc` partition, 1 h job limit |
| Node | 2 × 24 GB GPU |
| Model | `Qwen3.8-27B-AWQ-INT4`, served as `qwen3.8-27b` |
| vLLM | 0.26.0 |
| Serve flags | `--tensor-parallel-size 2 --dtype bfloat16 --gpu-memory-utilization 0.90 --max-model-len 32768 --max-num-seqs 4 --max-num-batched-tokens 4096 --enable-prefix-caching --reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_xml` |

Workload (fixed in `deploy/tacc/bench/main.py`):

- system prompt is the application's real prompt (policy + application contract) plus the schemas of all 16 Retail tools, ~5,284 prompt tokens;
- one order-status question per request, unique order id;
- `temperature=0`, `max_tokens=512`, streaming with usage;
- 2 warm-up requests discarded, then 24 requests per cell;
- thinking `on` (server default) and `off` (`chat_template_kwargs.enable_thinking=false`);
- concurrency 1, 2, 4 simultaneous client requests, sent directly to vLLM (not through FastAPI);
- each request is also written as one ATIF-v1.8 trajectory.

Run on TACC:

```bash
# One-time personal setup: tcloud account/key and SSH settings.
cp deploy/tacc/env.example deploy/tacc/env   # fill SSH_USER and SSH_KEY
tcloud config -u <username> -f <private_key>
tcloud init && tcloud ps

./deploy/run.sh tacc up --serve-only   # dependency setup + vLLM only
./deploy/run.sh tacc bench             # submit the workload and print the table
./deploy/run.sh tacc down              # stop only this project's jobs
```

The benchmark job prints the per-cell table and leaves the full per-request record at `$TACC_USERDIR/retail-agent/bench/<job>/results.json` on the cluster; copy it into `docs/data/` to reproduce the committed measurements. The benchmark can also run against any other vLLM deployment with the same flags by setting `MODEL_BASE_URL`, `MODEL_NAME`, `MODEL_API_KEY`, and `BENCH_OUT`.

Recorded results (2026-11-17, job `29402`, node `10-0-4-11`; ms):

| Thinking | Concurrency | TTFT p50 | TTFT p95 | TPOT p50 | e2e p50 | generated tokens | tool-call rate | req/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| on  | 1 | 500  | 505  | 15.65 | 3860 | 216 | 0% | 0.26 |
| on  | 2 | 517  | 908  | 19.73 | 4797 | 216 | 0% | 0.42 |
| on  | 4 | 1741 | 1820 | 21.54 | 6041 | 217 | 0% | 0.66 |
| off | 1 | 471  | 472  | 15.22 | 821  | 25  | 4% | 1.19 |
| off | 2 | 493  | 875  | 33.24 | 1265 | 26  | 8% | 1.53 |
| off | 4 | 1619 | 1670 | 18.73 | 2078 | 25  | 4% | 1.88 |

The earlier synthetic-prompt baseline (job `29378`, section 1 of `docs/EXPERIMENTS.md`) isolates the same effect with a shorter prompt; its first-content-token column is the cleanest statement of the claim:

| Thinking | Concurrency | TTFT p50 | first content token | e2e p50 | generated tokens | req/s |
| --- | --- | --- | --- | --- | --- | --- |
| on  | 1 | 352 | 2396 | 3160 | 184 | 0.30 |
| off | 1 | 337 | 337  | 1648 | 77  | 0.60 |

Interpretation used in the report: the serving stack is not the bottleneck (TTFT stays ~350-500 ms in both modes); the latency difference comes from how many tokens the model generates. Disabling thinking moves the first content token earlier by about 7×, roughly halves e2e, cuts generated tokens by about 58%, and doubles request throughput. `tok/s` is not a useful headline metric here because reasoning tokens inflate its numerator.

Evidence files:

| File | Contents |
| --- | --- |
| `docs/data/2026-11-17-serving-baseline.json` | per-request records and per-cell summaries for the synthetic-prompt baseline |
| `docs/data/atif/atif.jsonl` | 144 ATIF-v1.8 trajectories from the real-prompt benchmark |
| `docs/data/atif/run.json` | run-level configuration for those trajectories |
| `docs/figures/e2e.png`, `ttft-content.png`, `throughput.png`, `reasoning-length.png` | figures derived from the measurements |
| `docs/figures/serving-baseline.html` | interactive view of the baseline |
| `docs/agent-infra.html` | per-request model-side view generated from `atif.jsonl` |

Open the static views locally:

```bash
bash deploy/docs.sh    # http://127.0.0.1:8090/agent-infra.html
```

Regenerate the trajectory view from a run directory:

```bash
python3 deploy/tacc/bench/build_view.py docs/data/atif docs/agent-infra.html
```

`[TODO: the PNG figures were produced from the JSON by an ad-hoc plotting step that is not yet committed. Add `deploy/tacc/bench/plot.py` (and a README command) before submission so reviewers can regenerate every figure from the committed data.]`

### 4. Mapping results to the project report

`[TODO: fill the report locations after the report is finalized. The artifact paths are fixed.]`

| Result | Artifact evidence | Report location |
| --- | --- | --- |
| Serving baseline, reasoning on/off × concurrency | `docs/data/2026-11-17-serving-baseline.json`, `docs/figures/serving-baseline.html` | Table __, §__ |
| First-content-token latency | `docs/figures/ttft-content.png` | Figure __, §__ |
| End-to-end latency | `docs/figures/e2e.png` | Figure __, §__ |
| Throughput (req/s) | `docs/figures/throughput.png` | Figure __, §__ |
| Reasoning volume | `docs/figures/reasoning-length.png` | Figure __, §__ |
| Real-prompt behavior and tool-call rate | `docs/data/atif/atif.jsonl`, `docs/agent-infra.html` | Table __, §__ |
| No-tool quality floor | `docs/EXPERIMENTS.md` §2 | Table __, §__ |
| System pass^1 / pass^3 | [TODO: `docs/data/<run>/results.json`] | Table __, §__ |
| GPU utilization interpretation | `docs/EXPERIMENTS.md` §3 (SM/DRAM sampling) | §__ |

### 5. Expected variation

- **Serving numbers** are medians from one run on one shared cluster node. Shared-node contention, GPU clocks, prefix-cache state, and scheduling can shift them. Compare medians across reruns, not individual requests; the qualitative result (thinking on delays the first content token by several times and lowers req/s) is what the claim rests on.
- **Concurrency 4** is at the `--max-num-seqs=4` boundary, so TTFT p95 and e2e include queueing. Do not read concurrency-4 numbers as per-request service time.
- **tau2 scores** depend on the model, the user simulator, and the sampled task subset. A two-task pass^1 is coarse: one task flips the average by 0.5. The report's full-set numbers should be compared only at the same task list, seed, trial count, and user model.
- **Demo mode is deterministic** and is a plumbing check, not a measure of model quality. It cannot produce a benchmark score.
- **Prefix-cache hit rate** in the synthetic benchmark is higher than in real multi-turn tasks (the workload reuses one prefix). The report separates these; do not apply the synthetic hit rate to end-to-end conversations.

### 6. Known limitations

- The system is a local benchmark sandbox. It never contacts a merchant, payment, or email system; human handoff only writes a local record.
- Identity verification follows the benchmark policy (email, or name + zip). It is not production authentication.
- SQLite with WAL and a single API worker is intentional. Multi-instance deployment needs a shared database and cross-instance coordination; the current session mutex is per process.
- The demo model supports the documented scenarios only; arbitrary free-form requests require live mode.
- The exact serving reproduction requires the course TACC environment (`tcloud`, `$TACC_USERDIR`, course model path and activation script). Reviewers outside the course must supply an equivalent Slurm + vLLM deployment; the benchmark itself only needs an OpenAI-compatible endpoint and the documented serve flags.
- Upstream tau2 is pinned. Upgrading it can change task data, tool signatures, or simulator behavior; rerun the full test suite after any bump.
- The repository does not include a production security review: no login, rate limiting, secret manager, or multi-tenant isolation beyond the per-session capability token.
- `[TODO: add the system's full tau2 results and any remaining measured claims before submission.]`

### 7. Cleanup

```bash
# Local
uv run --frozen python -m backend.server stop
rm -f runtime/retail.sqlite3 runtime/e2e.sqlite3

# TACC: cancels only this project's jobs and closes the tunnel
./deploy/run.sh tacc down
```

## Data and license

Customer, order, and payment records are the synthetic data shipped with `tau2-bench`; no real customer data is used. The upstream project is MIT-licensed. `[TODO: add a LICENSE file to this repository; it currently has none.]`

## References

- tau2-bench: <https://github.com/sierra-research/tau2-bench>
- Deep Agents: <https://docs.langchain.com/oss/python/deepagents/overview>
- NSDI '27 Call for Artifacts: <https://www.usenix.org/conference/nsdi27/call-for-artifacts>

<!-- END README.md -->

---

## Internal notes — delete before exporting to PDF

**这份稿子的状态：** 第 3 节是按 NSDI artifact README 要求重写的英文 README，建议直接替换仓库的 `README.md`；当前仓库里的中文 README 没有 "Getting Started Instructions" / "Detailed Instructions" 这两个必需小节，而且写死了 `/home/mnyh/...` 路径，评审 clone 后跑不起来。

**提交前必须处理的缺口（按重要性排序）：**

1. **tau2-bench 没有进仓库。** 现在 `../tau2-bench` 是指向组员本地目录的 symlink，`pyproject.toml` 用 `path = "../tau2-bench"`。教学团队 clone 后 `uv sync` 会失败。建议改成 pinned submodule，或加 `scripts/setup.sh` 自动 clone 到固定 commit。
2. **commit 不一致。** 本地 checkout 是 `122e243`（tau2 2.0.0），README / TACC setup 固定的是 `0c69df4`。先统一，再在最终 pin 上完整跑一遍 18 个测试 + smoke test。
3. **仓库没有 LICENSE。** 加一个 MIT（或与上游一致的许可证）。
4. **未提交改动。** `benchmarks/`、`deploy/tacc/` 有 9 个修改文件，`deploy/tacc/eval.sh` 和 `deploy/tacc/eval/` 还未跟踪。提交前 commit 并打 tag，README 里填 tag/commit。
5. **仓库可见性未验证。** 我没有 GitHub 凭据，无法确认 public；用无痕窗口或另一个账号验证一次。私有时把教学团队加成 read-only。
6. **组员分工是占位。** 我按代码模块猜的，务必和每个人确认后改掉。
7. **系统完整 pass^1/pass^3 还没跑。** 目前只有 bare 控制组（0.0000）。报告的主结果如果包含系统质量，必须先跑完整评测并把 `results.json` 提交到 `docs/data/`，否则 "Results Reproduced" 这一项站不住。
8. **报告表/图编号是 `[TODO]`**，报告定稿后回填。
9. **PNG 图没有生成脚本。** 原始 JSON 在仓库里，但 `docs/figures/*.png` 是临时脚本产物。建议补一个从 JSON 出图的脚本；至少 HTML 视图可以重生成。
10. **TACC 依赖课程环境。** 外部评审没有 `tcloud` / `$TACC_USERDIR` / 课程模型路径，无法原样复现 serving 实验。README 已经写了替代路径（任意 OpenAI 兼容端点 + 相同 vLLM flags），但最好在报告里也说明这一点。

**最后一步：** 找一个干净目录，完全照 README 从 clone 走到 smoke test 和 `pytest`，确认没有依赖组员机器上的隐藏状态。

**加分项（可选）：** 加 `scripts/smoke.sh`，把 Getting Started 的 curl 流程封装成一条命令；artifact 的 "Functional" 会明显更好评。
