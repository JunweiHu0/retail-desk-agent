# Retail Desk implementation plan

## Objective and fixed protocol

Build an isolated-session Retail backend, a minimal B1 tool-loop agent, independently switchable enhancements, frontend integration, and a reference HTTP evaluator. Validate with Qwen3.5-9B on huoshan; compare B1 and the selected candidate with the same 27B deployment later. The official Qwen/Qwen3.8-27B model repository exists; the TACC AWQ-INT4 artifact, exact weight revision and live endpoint still require verification. Do not substitute a base model or infer a model identity from its size. Model cohorts must be reported separately.

Upstream application: `a3173371079b53779a933e50ed79d528b7843a96`.
Upstream tau2: `0c69df456a96aa76a1162591574dad9c427a34d7`.

All variants receive a preauthenticated synthetic customer and all their orders, full Retail policy, the same 16 business tools, conversation history, and the same approval/execution layer. This is an adapted benchmark: original identity discovery is not scored. No target, reference action or score mask is visible to the agent.

The primary score is exact end-state matching of the selected complete customer object and all that customer's initial orders. Dictionary key order is irrelevant; list order/duplicates and numeric values are preserved. All test40 tasks count, including no-write tasks. Termination reason is diagnostic rather than an extra pass gate. Infrastructure failures with no valid snapshot make a suite incomplete instead of disappearing from its denominator.

## Modules and acceptance tests

| Module | Implementation | Acceptance evidence |
| --- | --- | --- |
| Versions/scenarios | Frozen data, policy, task/split hashes; public input separated from private targets | Stable hashes, disjoint splits, no private evaluation data in model requests |
| Episode store | One session is one episode, each with an independent RetailDB; persist history/pending/events/actions | Same order modified in two sessions is isolated; restart recovery; immutable seed |
| Business execution | Reuse official schemas and RetailTools, preview, approval and receipts | All seven write types; preview has no side effects; reject and duplicate approval; associated financial fields |
| B1 | Explicit model/tool/observation loop; stop at text, pending, handoff or budget | Sequential tools, correct tool message correlation, errors fed back, no hidden graph tools |
| State enhancement | Pending intents and observed facts; only actual commit receipts settle operations | Multiple requests, changed intent, preview is not execution, no cross-session state |
| Error enhancement | Attach relevant already-observed context to real errors, without silent business argument edits | Wrong order/item/payment, bounded recovery, same backend validation |
| Guide enhancement | Separate frozen short operational guidance, learned only from development failures | Toggle works, provenance/hash saved, no test IDs or solutions, fixed during tests |
| HTTP/frontend | Scenario/variant initialization, SSE messages and decisions, episode lifecycle, private export | Browser and evaluator use same routes; refresh recovery; pending/reject/update; true receipts |
| Reference evaluator | Frozen targets, simulator, HTTP driver, comparator and reports | Self-target pass, scored-field mismatch fail, simulator cannot see gold, no auto-approval |
| Telemetry/deployment | Correlated run/episode/turn/call events, token/latency/errors, isolated serving | Extra calls counted, credentials absent, artifacts survive completed episodes |

## Public API changes

- `POST /api/sessions`: optional registered scenario/customer and variant; return existing capability plus episode metadata.
- `GET /api/sessions/{id}`: existing content plus variant/status/manifest/usage.
- `POST /api/sessions/{id}/messages`: SSE with existing events plus proposal/receipt.
- `POST /api/sessions/{id}/decisions`: SSE; apply the exact pending action then continue the agent with the actual application receipt.
- Internal eval endpoints: create episode from public input, finish, export full RetailDB and manifest. An independent eval token protects these endpoints.
- `done` means a turn finished, not task success. Only explicit finish/budget termination freezes an episode.
- Keep progress streaming and complete assistant text in v1; do not present tool progress as token streaming.

## Data and experiments

Validation20: `4,6,8,21,22,25,28,35,46,52,54,59,72,80,81,84,96,99,104,112`.
Development54 is the remainder of official train74.
Smoke8: `0,3,10,16,24,34,41,47`, one trial each.
Official test40 stays frozen. Final B1 and selected candidate each run 40 x 3 = 120 episodes.

Gold targets are generated in clean official environments, with expected read failures recorded and unknown write failures treated as fixture issues. The fixed pin has two audited no-op write failures; their exact exception allowlist, unchanged-DB requirement and evidence are documented in EVAL_PROTOCOL.md. All 114 tasks remain included. Freeze target, selected customer/order scope and comparator version before candidate runs. Never choose the mask from candidate changes.

The simulator can send a message, approve/reject a visible action, or finish. It sees its user scenario and visible conversation/card, never target/mask/reference actions/current score. Deterministic simulator tests do not represent live benchmark results.

Defaults: 30 simulator actions, 80 agent model calls including extra state/review/retry calls, 80 agent business tool calls, 600 seconds per episode, 4096 output tokens per model call, concurrency 1. Any development-time budget change applies to every variant and is frozen before test.

Compare B1, B1+state, B1+errors, B1+guide, then selected combinations. Main metrics: DB success, pass^3 (all three trials succeed), paired task-clustered confidence interval. Auxiliary metrics: error categories/recovery, tokens, calls, p50/p95 latency, unsupported success claims. Never claim an uplift from a framework name or another paper's result.

## Deployment

Local source lives under `Line/6000v/retail-desk-agent`. Remote application, environments, caches and persistent results live under `/vePFS/han/retail-desk`. Active SQLite uses node-local storage; completed episode snapshots and manifests are exported to persistent storage.

Use existing `ssh huoshan`. Defaults: application 127.0.0.1:18881, model 127.0.0.1:18880, separate processes/environments. Existing Qwen3.5-9B weights at `/vePFS/models/Flora/qwen3.5-9b` stay read-only. GPU processes and shared drivers/environments are untouched. The 535-series driver requires an actual isolated runtime compatibility check. An occupied GPU is not an authorization to preempt its workloads.

TACC retains GPU service + CPU application jobs. Require live mode for evaluations; persist completed episodes across jobs. Deployment scripts own platform differences; business code does not depend on Slurm or fixed nodes.

## Stages and progress

- [x] P0: Save protocol/manifest/splits and establish existing test/build baseline.
- [x] P1: Implement episode isolation, lifecycle, shared business execution and frontend contracts.
- [x] P2: Implement B1 and deterministic model integration tests.
- [x] P3: Implement reference evaluator and end-to-end HTTP smoke without a real model.
- [x] P4: Deploy application on huoshan; validate model protocol and run real 9B smoke8 when GPU resources permit.
- [ ] P5: Implement independent state/error/guide switches; deterministic tests and 9B functional checks.
- [ ] P6: Establish 27B development baseline and select enhancements on development54/validation20.
- [ ] P7: Freeze all versions; run final B1/candidate test40 x 3 comparison and publish local artifacts/report.

Each stage records actual commands, execution location, scale, results and unresolved resource conditions. Ordinary implementation and verification are authorized; no repeated permission prompts. Software acceptance and measured agent improvement are separate outcomes.

### Current acceptance evidence (2026-11-17 America/Chicago / 2026-11-18 UTC)

- P0–P3: huoshan upstream baseline **18 passed**; latest implemented full suite **114 passed** after the real Qwen integration fixes. Ruff and frontend production build pass. Browser desktop/mobile flows **2 passed**; separate demo HTTP cancellation/approval and return/rejection checks both pass.
- Frozen targets: development54, validation20, test40 and smoke8 all have completion markers. Original tasks, DB and split membership remain unchanged.
- P4: the huoshan application and isolated inference dependencies are installed. Qwen3.5-9B's four weight shards match their recorded SHA256 digests. CUDA, initial native-tool and JSON protocol checks passed. Live multi-turn checks exposed and fixed a single-system layout error, then reproduced a thinking/tool-parser issue and 60-second HTTP timeouts. The explicit thinking=off cohort with 300-second request timeout completed B1 smoke8 at **6/8**, with all snapshots valid; demo tests are not a model score.
- P5: state/error/guide switches and deterministic tests are implemented. The current guide is policy-derived seed guidance, not learned from development traces. The state variant now projects action-matched actual receipts into tool observations while preserving raw history; its new enhanced smoke8 is running. Development feedback, learned guidance and final measured uplift remain pending.
- P6–P7: not run. Exact deployed 27B weights/service have not been verified; no final test40 model results or claimed improvement exist.

See [verification evidence](VERIFICATION.md) and [remote run locations](huoshan.md). Historical failed and incomplete runs remain preserved alongside subsequent passing runs.
