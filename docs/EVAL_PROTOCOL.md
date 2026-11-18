# Retail reference HTTP evaluation v1

This protocol is an adapted Retail benchmark, pinned to tau2
`0c69df456a96aa76a1162591574dad9c427a34d7`. All variants start with the same
preauthenticated synthetic customer, all of that customer's initial orders, the
full policy, 16 official business tools, and the same execution/approval layer.
Original identity discovery is not scored. There is no LLM judge in v1.

## Frozen inputs and targets

`python -m benchmarks.run_http build-targets` checks the tau2 checkout revision,
tracked source/data cleanliness and the imported module location. An immutable
release without `.git` must have a parent `source-manifest.json` with the exact
pinned `tau2_sha` and a clean-checkout `tau2_file_sha256` inventory covering every
`src/**/*.py`, the four Retail assets and `pyproject.toml`; every byte hash and
the complete source inventory is checked. Application revision/dirty status
comes from that release manifest. It reads the
pinned database, tasks, policy and official split bytes and records their hashes.
Every task is replayed from a fresh `RetailDB` through official `RetailTools`.
Expected read failures are retained in `reference_trace`. Unknown reference
WRITE failures abort fixture generation. At this fixed pin, exactly two audited
no-op WRITE exceptions are allowed: task64/action64_6 (exchange attempted on a
pending order), and task105/action106_0 (insufficient gift-card balance). The
exception match requires exact task/action ID, tool, arguments, exception type
and message, plus an unchanged **full** DB hash. Task64 then executes action64_7;
task105 keeps the native unchanged DB target and is labelled `reference_issue`.
These private labels never enter agent/simulator inputs, and both tasks remain
in their original denominators. This preserves the native DB evaluator's
catch-and-continue reference semantics without ignoring unknown fixture errors. The seven writes are cancellation, exchange,
pending-order address/items/payment, user address and return. Unsupported initial
state overrides abort instead of silently changing the seed.

Selected customer identity is resolved offline from reference identity lookups,
explicit reference user IDs, initial order ownership, or public known identity
text. An unresolved or ambiguous identity is a fixture error. Targets contain the
initial/final DB, public user scenario, frozen scope, reference trace and hashes.
They are private evaluator artifacts. Neither target DB, reference actions,
scope nor scores cross the agent or simulator boundary.

The comparison scope is the complete selected `users[customer_id]` object and
complete `orders[order_id]` objects for **every initial order owned by that
customer**. It is frozen before candidate execution, including unchanged orders.
The initial user order index must agree with ownership. Unrelated customers,
orders and product catalog are outside this declared scope. No changed-fields
mask is derived from either reference or candidate changes.

Comparator version: `complete-customer-initial-orders-v1`. Dictionary key order
is ignored. Lists preserve order and duplicate multiplicity. Missing keys differ
from explicit null. Numeric values compare exactly without tolerance (`1` equals
`1.0`; booleans are not numbers). Financial fields, payment histories, optional
order fields, and complete addresses remain in scope. Self-target comparison
must pass. A one-field scoped change must fail.

## Splits and cohort rules

Official train74 is split into development54 and validation20. Validation IDs:
`4,6,8,21,22,25,28,35,46,52,54,59,72,80,81,84,96,99,104,112`.
Smoke8 is `0,3,10,16,24,34,41,47`; smoke uses one trial (`--seeds 0`). Official
test40 remains frozen. Final B1 and selected candidate each use seeds `0,1,2`:
40 tasks × 3 trials = 120 episodes per variant.

Use the same serving endpoint and model for agent and user simulator within a
cohort. Configure the simulator through `--model-base-url`, `--model`, and the
environment variable selected by `--api-key-env` (default `MODEL_API_KEY`). The
CLI checks backend health for live mode, readiness, matching model name and the
16-tool protocol. Run 9B and 27B as separate cohorts. Do not pool their results.
A matching model name is configuration evidence; retain server/model deployment
manifests as evidence of actual loaded weights.

## Simulator and HTTP boundary

The simulator is a separate OpenAI-compatible model call through `httpx`. Its
request has exactly `user_scenario`, visible user/assistant conversation,
current visible proposal, and application-visible approval receipts. Receipts
are restricted to status/tool/result/message/action ID fields; persisted raw
tool history remains excluded. Session model history, business tool outputs, customer
context outside that card, manifests, targets and current scores are excluded.
Its only actions are a customer message, a decision on the current proposal ID,
or finish. Decision approval must be a JSON boolean; a missing or different
proposal ID is rejected. There is no automatic approval. While a proposal is pending, the simulator
has the same UI affordance as the browser: decision or finish only. To request a
correction, it must reject first and send a message on the following turn.

The HTTP evaluator creates an isolated episode with:

```text
POST /internal/eval/episodes
Authorization: Bearer $EVAL_API_TOKEN
{initial_db, customer_id, variant, task_id, trial_id, seed, metadata}
```

Only public protocol/source identifiers are placed in metadata. The create
response provides `{session:{id,token,...}, manifest}`. The capability token is
kept in memory, excluded from saved artifacts, and used for browser-compatible
session operations:

```text
POST /api/sessions/{id}/messages   {message}
POST /api/sessions/{id}/decisions  {action_id, approve}
GET  /api/sessions/{id}
```

The model transport uses one leading system message containing policy, public
customer context and enabled enhancements. Trusted application receipts are
included in that system block with their chronological conversation positions;
they are never relabelled as customer messages. Persisted history keeps the
original application receipt events. This layout supports Qwen templates that
reject multiple or mid-conversation system messages.

Message and decision streams contain `status`, `tool_start`, `tool_end`,
`proposal`, `receipt`, `done`, or `error` events. A turn requires `done.session`, or a terminal `error.session`
which preserves committed receipts/session state and terminates as `agent_error`.
Such an application error is not an infrastructure retry. HTTP 4xx responses
are protocol/simulator errors, not infrastructure retries; a valid frozen DB
snapshot still receives its pure DB score.
`done` indicates a completed turn, not task success. The simulator sees only the
returned session's UI messages, `context.pending` card and persisted approval receipts. Actual receipts remain
in the audit trace; an execution claim alone does not alter the score.

Finish/export uses the separate evaluator credential:

```text
POST /internal/eval/episodes/{id}/finish  {reason}
GET  /internal/eval/episodes/{id}/snapshot
```

The snapshot is `{db,session,manifest}`. Only a frozen session with
`session.status == "finished"` is a valid final snapshot; an active/busy snapshot
cannot be silently scored as completed. The episode always attempts finish and
snapshot, including after simulator stop, budget exhaustion or HTTP failure.

## Budgets, failures and reporting

Frozen defaults are 30 simulator actions, 600 wall seconds, concurrency one,
4096 simulator output tokens, and simulator temperature 0. The backend enforces
80 agent model calls (including extra enhancement/review/retry calls), 80
business tool calls, 4096 output tokens per call and its active-time budget.
Persist actual `snapshot.manifest.agent_runtime` alongside the evaluator config.
A development budget change must apply to every variant and be frozen before
testing. Infrastructure retries apply only when no valid frozen final snapshot exists,
and are limited to one fresh episode with identical public input, task, trial
and seed. A valid snapshot is scored without rerunning it even after an HTTP
error. Both attempts remain on disk; the last
attempt is primary. Model generation does not promise bitwise determinism.

A valid exported DB is scored even after budget/error termination. Termination
reason is diagnostic, not an extra success gate. No-write tasks are included.
An episode with no valid snapshot makes the fixed-denominator suite incomplete;
`db_success_rate` is null until every expected task/seed has a valid snapshot.
It is never removed from the denominator. A live/model/policy/pin protocol
mismatch also marks the suite invalid while retaining its diagnostic DB score. `pass_3` is the fraction of tasks whose
three seeds all succeed and is only reported for complete three-seed suites.

Each fresh run directory stores source/version hashes, effective public input,
fixture hash, initial response, simulator requests/responses and usage, SSE
trace, final DB, session/runtime manifest, mismatch paths, score, termination,
and primary attempt selection. Credentials are not persisted. A fixture/run
manifest is never overwritten; separate completion files record completion.
Interrupted runs lack a completion marker and must not be called complete.

`compare` is a separate reporting operation. It requires both immutable
`complete.json` markers to declare `suite_complete=true`, identical evaluator
source hashes (including simulator code), and complete paired suites,
matching task/seed grid, model cohort, targets, source hashes and declared
budgets, then bootstraps task clusters (all trials stay together) with a fixed
reporting seed. Its delta is right minus left. This statistical report does not
replace live execution evidence or establish an uplift from an implementation
name. Inspect actual agent runtime and serving manifests before comparing.

## Commands and evidence

Full target replay and live runs belong on **huoshan**, under a fresh directory
inside `/vePFS/han/retail-desk`. Verify remote checkout/environment first; use the
existing SSH configuration. Example commands after that verification:

```bash
python -m benchmarks.run_http build-targets \
  --tau-root /verified/tau2-bench --split smoke \
  --output /vePFS/han/retail-desk/targets/smoke-v1
python -m benchmarks.run_http run \
  --fixtures /vePFS/han/retail-desk/targets/smoke-v1 \
  --output /vePFS/han/retail-desk/evaluations \
  --model Qwen3.5-9B --seeds 0 --variant b1
python -m benchmarks.run_http compare \
  --left /path/to/b1-run --right /path/to/candidate-run \
  --output /fresh/path/paired-comparison.json
```

Local small verification only:

```bash
python3 -m pytest --noconftest -q tests/test_reference_eval.py
python3 -m compileall -q benchmarks/reference benchmarks/run_http.py
```

The isolated test command avoids loading the application-wide conftest when the
local tau2/application environment is absent. The local tests cover exact
comparison, full frozen scope, boundary exclusions, simulator decisions, SSE
parsing, exclusive artifact writes, a mocked HTTP budget snapshot and incomplete
suite handling, immutable source inventory/hash validation, terminal agent-error
streams after a commit, receipt visibility, and final-snapshot freezing. They are deterministic protocol fixtures, not real model results.
Full reference replay and live HTTP smoke are separate acceptance evidence.

The separate `python -m benchmarks.software_smoke --base-url URL --tau-root PATH
--output FRESH_DIRECTORY` command requires demo mode and an eval token. It checks
scripted cancellation approval and whole-order return rejection against public
seed inputs, actual SSE receipts and the complete scoped DB comparator. Its
artifacts explicitly use `validation_kind=deterministic_http_contract`. A terminal
agent error after a decision fails this software contract even if the committed
DB matches; pure DB scoring in live evaluation remains unchanged. The utility makes
no user-simulator LLM calls and produces no live benchmark grades.

Auxiliary summaries include model/tool calls, input/output tokens, simulator
prompt/completion tokens, active agent seconds, and p50/p95 episode/HTTP turn
latencies. Costs include failed trials and retained infrastructure retry
attempts. Unknown usage remains null with missing-call/attempt counts and a
separate observed subtotal. Any nonzero agent `unknown_usage_calls` makes total
agent tokens and all per-success token costs null; `known_total` retains the
recorded token sum and `missing_calls` records the unknown call count. Token cost per successful episode divides all tokens
by DB-successful episodes; token cost per successful task uses tasks whose every
requested seed succeeded. Both are null for unknown total usage or no successes.
HTTP turn timing is not TTFT or inter-token latency: model invocation is not token
streaming. The final seal/drain request allows 315 seconds for the backend's
310-second bounded pending-call drain (300-second model request timeout); conversation and finish/drain durations are retained
separately from total elapsed time.


Private failure diagnostics are available through:

```bash
python -m benchmarks.run_http analyze --run /path/to/run --output /fresh/path/analysis.json
```

`analyze` reads only each primary attempt's trace and score. It retains private
task IDs and reports trial success/termination, mismatch categories (order
status, items/variants, address, payment/balance, other), failed tool/error counts,
identical repeated failed name/argument calls within an episode, and user
rejection counts. Nested session histories are not counted again. Its output sets
`guide_feedback_eligible` only for development runs and explicitly prohibits
validation/test diagnostics from becoming learning data or guide feedback. This
is deterministic reporting, with no LLM call or automatic guide update.


The initial exception freeze is backed by the read-only huoshan all114 audit at
`/vePFS/han/retail-desk/runs/reference-audit-20261118T024107Z-a317337-579751/audit.json`,
SHA-256 `46024e9396dd7076e021e6b0cae2705fcbcad898080e2728958c5e91cc15b751`.
It recorded 16 failed READ actions and the two WRITE actions above; every failed
action left full DB hash
`3ca5bd70e621602e23d909c87f26224a1a486e75955d8a6da53721ec224b23dc`
unchanged. The audited allowlist lives in `benchmarks/reference/known_failures.py`
and is included in evaluator source hashes. No original task, seed DB, NL
assertion, or task membership was changed. The adapted primary metric continues
to score DB only and does not claim native NL-assertion success for task105.

To audit a fresh pinned checkout without creating target completion markers:

```bash
python -m benchmarks.run_http audit-reference --tau-root /verified/tau2-bench --output /fresh/path/audit.json
```

Thinking control is a cohort parameter: backend `MODEL_THINKING=auto|on|off`
and evaluator `--thinking auto|on|off` must match. `auto` omits the request
switch; `on`/`off` send `chat_template_kwargs.enable_thinking` explicitly.
Health, episode provenance and evaluator manifest retain the setting, and paired
comparison rejects different settings or model request timeouts. Current 9B
functional checks use a separate `off` cohort following a reproduced thinking/tool
parser failure. No tools are extracted from reasoning text. Other services must
verify support for the explicit template parameter before selecting it.

The state enhancement also projects an actual application execution/rejection
receipt onto the matching preview ToolMessage by action ID, keeping its original
tool-call correlation. It omits the resolved synthetic confirmation pause in the
model request only. Persisted raw history and business audit events remain
unchanged. This projection never executes a tool, invents a receipt, changes tool
arguments or bypasses approval; B1 retains its minimal raw observation + system
receipt representation. Its version is recorded as `state_receipt_projection` in
the agent runtime manifest.

## Simulator revision visible-action-schema-v2

This revision constrains output with a dynamic JSON Schema based only on the
visible pending card. Without a card, allowed actions are a nonblank message or
finish. With a card, allowed actions are a boolean decision for that exact card
ID or finish. Both approve and reject remain available: the schema never decides
which one the user should choose. No target or reference action enters the schema.
Runtime validation remains at the response boundary; unsupported structured-output
servers fail explicitly rather than silently falling back to unconstrained JSON.

Received invalid responses retain request messages, response schema, raw parsed
response, validation error and any reported token usage in the attempt trace.
They terminate the episode under the existing DB-only rule without an automatic
retry. Invalid responses count as model calls, not executed user actions.

The evaluator records `simulator_version=visible-action-schema-v2` and its source
hashes. Revised and earlier simulator cohorts cannot be paired. DB comparator,
fixtures and HTTP protocol remain unchanged; a new comparison reruns the entire
chosen task grid for both agents, not only earlier failed cases.

## C1 task-planning candidate

`variant=c1` adds a tool-free structured planner using the same configured model,
policy and public customer information. All planner/executor/repair calls share
the existing episode budgets; `usage.phases` and telemetry identify their cost.
The planner may propose tasks and dependencies, but cannot set executed states.
The application allocates task IDs, expands observed order scopes and binds each
write proposal to a matching active task. Known user constraints cannot be silently
rewritten by the executor. Only a matching actual receipt settles a write task;
rejection does not reactivate it without a new customer message.

Public sessions retain their existing UI contract. Authenticated internal snapshot
exports additionally include top-level `agent_state` for private diagnosis, including
planner attempts and task/receipt associations. It is not part of ordinary session
responses or simulator input. Informational tasks are recorded, but C1 does not yet
mark free-form replies as answering them. C2 can record an advisory answer judgment;
neither variant certifies free-text factual correctness.

B1 is frozen locally at tag `baseline/b1-http-v1` (commit
`03ac358c9f49435a8f3fd48548572b643307c9e9`). The candidate shares the same 16 business
tools and approval layer; planner output is not an additional business tool.
C1 requires a model with structured JSON-schema output and native business-tool
calling. Demo mode is not a C1 model-capability validation.

## C2 completion-check candidate

`variant=c2` uses C1's planner and ledger, then checks unsent free-form replies.
When a ready write has every required argument and satisfied dependencies, a
deterministic check selects the next ready task and uses standard named
`tool_choice` once to obtain its native tool proposal instead of asking for
another chat yes. The original 16-tool catalog and argument schemas remain;
proposed arguments still have to match the task and pass the business layer. This is not execution authorization: the normal
card and exact approval still gate every write. If the correction still fails,
the response explicitly lists unexecuted work rather than claiming completion.

Otherwise, unfinished tasks or a post-decision final response may trigger one
structured review by the same model. Review v4 returns only accept/revise/handoff,
a fixed issue category and eligible informational task IDs. It does not rewrite
replies, copy quotes, or generate factual correction advice. Application-owned
feedback maps the issue to one executor correction. Accept preserves the draft.
Review calls count toward the same global budget, with at most one review and one
correction per external turn. Invalid or truncated review output is logged and uses
that same correction allowance; it cannot settle a task. Informational answer IDs
are restricted to active information tasks and stored with the actual outgoing
reply and observed context as an explicitly model-judged record. A reviewer cannot
mark writes executed; factual answer quality still needs human review.
Raw unsent drafts/checks stay in private agent_state and do not become user messages.
Planner updates do not reopen already answered or executed tasks.

Business-tool errors mark matching candidate tasks blocked with the actual error
and failed arguments. An identical failed write is not resubmitted automatically;
a different proposal still has to satisfy known user constraints and backend
validation. Malformed native tool arguments receive a correlated error observation
and can be repaired without corrupting the task ledger.

Planner v5 exposes its dynamic schema in the model prompt and separates updates from
explicit supersession. Object IDs are bound by the application, not regenerated as
business arguments. Validation failures and truncation share one repair attempt; if
still invalid, keep the old ledger and ask the customer to clarify without staging
new writes. All attempts, failures, and reported tokens remain in the private audit.
