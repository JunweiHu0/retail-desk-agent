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

Compare B1, B1+state, B1+errors, B1+guide, then selected combinations. Main metrics: DB success, pass^3 (all three trials succeed), paired task-clustered confidence interval. Auxiliary metrics: error categories/recovery, tokens, calls, p50/p95 latency, unsupported success claims (manual trace audit; no automatic judge rate). Never claim an uplift from a framework name or another paper's result.

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
- [x] P5: Implement independent state/error/guide switches; deterministic tests and 9B functional checks.
- [ ] P6: Establish 27B development baseline and select enhancements on development54/validation20.
- [ ] P7: Freeze all versions; run final B1/candidate test40 x 3 comparison and publish local artifacts/report.

Each stage records actual commands, execution location, scale, results and unresolved resource conditions. Ordinary implementation and verification are authorized; no repeated permission prompts. Software acceptance and measured agent improvement are separate outcomes.

### Current acceptance evidence (2026-11-17 America/Chicago / 2026-11-18 UTC)

- P0–P3: huoshan upstream baseline **18 passed**; latest implemented full suite **114 passed** (51.27s) after the real Qwen integration fixes. Ruff and frontend production build pass. Browser desktop/mobile flows **2 passed**; separate demo HTTP cancellation/approval and return/rejection checks both pass.
- Frozen targets: development54, validation20, test40 and smoke8 all have completion markers. Original tasks, DB and split membership remain unchanged.
- P4: the huoshan application and isolated inference dependencies are installed. Qwen3.5-9B's four weight shards match their recorded SHA256 digests. CUDA, initial native-tool and JSON protocol checks passed. Live multi-turn checks exposed and fixed a single-system layout error, then reproduced a thinking/tool-parser issue and 60-second HTTP timeouts. The explicit thinking=off cohort with 300-second request timeout completed B1 smoke8 at **6/8**, with all snapshots valid; demo tests are not a model score.
- P5: state/error/guide switches and deterministic tests are implemented. The current guide is policy-derived seed guidance, not learned from development traces. The state variant now projects action-matched actual receipts into tool observations while preserving raw history; the frozen policy/application guide v2 and enhanced smoke8 are complete at **6/8**, equal to B1. Agent model calls fell 61→46 and agent tokens fell about 22.1%, but no success-rate uplift is established. Development54/validation20 ablations, learned guidance and final measured uplift remain pending.
- P6–P7: not run. Exact deployed 27B weights/service have not been verified; no final test40 model results or claimed improvement exist.

Before formal model comparisons, resolve the concrete target/simulator issues in [eval alignment](EVAL_ALIGNMENT.md), freezing any revised protocol before rerunning both variants. Current v1 scores and targets stay unchanged.

See [verification evidence](VERIFICATION.md) and [remote run locations](huoshan.md). Historical failed and incomplete runs remain preserved alongside subsequent passing runs.

### 后续进展：模拟器 schema v2

已实现动态可见动作约束与错误响应/usage保留；完整软件119项通过，真实消息/正确批准/错误拒绝三项通过。双方完整smoke8重测均6/8，16题无协议错误、用量无缺失；总token为B1 732,296、enhanced 561,299。仍有用户场景未指定支付方式导致的严格target差异，以及模拟器把pending当完成的问题；正式27B开发/验证比较前需固定语义。证据见VERIFICATION.md最新章节。

## 下一轮 agent 改进计划（2026-11-18，C1/C2已实现，效果验证中）

### 目标与 baseline

保留当前简单 B1：完整政策、预认证客户及订单、16 个业务工具、原生顺序调用循环、多轮历史、公共预览/审批层。B1 不使用任务规划器、状态增强、额外检查或操作指南。不为拉开分数故意弱化提示词、工具或模型，也不把已修复的模型模板/传输故障当作 baseline 能力。冻结当前可运行版本的源码摘要、system prompt、模型参数及输入协议，后续新增独立候选 variant，不在 B1 分支注入增强逻辑。

基线证据使用最新 schema-v2 批次：`schema-v2-paired-smoke-20261118T065355Z/b1/20261118T065358Z-98a2b327`，9B、thinking=off、smoke8×seed0，6/8；16题配对中的两组用量均完整。当前 enhanced 同为6/8，作为历史实验保留，不命名为“已改进成功”的最终方案。固定源码版本与实际运行路径对应关系见该批次 `source-attestation.json`。

本轮先解决需求遗漏、执行状态混淆和重复确认。目标是提高完整任务的最终 DB 匹配率，同时减少未执行就声称完成、遗漏与重复动作；不预先承诺提升幅度。后端使用同一 RetailService/Store/审批机制。若发现公共后端错误，双方共同修复并重跑，不能让候选独享修复。

### 为什么重做状态维护

当前 `STATE_CONTRACT` 允许模型在普通答复或工具调用旁“可选”输出任务 JSON；真实模型不保证输出，账本可能一直为空。只增加一段状态提示不能保证提取了全部需求。system 中的 executed 回执与历史 awaiting_confirmation 观察也可能互相干扰。回执投影已经缓解后一问题，下一轮需要把需求提取和运行时状态更新变成明确的阶段。

采用同一个模型的几个顺序阶段，不新增多 agent 或业务工具：

```text
用户消息
  → 结构化需求提取/更新（JSON，无业务工具）
  → 持久任务账本 + 当前观察
  → 执行器（同一套16工具）
  → 读结果：补充事实/解析对象；写结果：awaiting_confirmation，停止本轮
  → 页面或模拟用户批准/拒绝
  → 公共后端实际执行 + receipt
  → 应用依据回执更新账本，继续剩余任务
  → 回复前核对未完成需求与事实依据
```

规划器只是同一个 agent 的内部模型阶段，不获得 target、参考动作、模拟用户隐藏场景或评分结果。所有阶段使用相同模型与解码参数，并计入现有80次模型调用、80次工具请求、4096单次输出和600秒episode预算。不得在后台绕过预算调用额外模型。

### 模块 A：强制结构化需求提取与任务账本

实现独立 `agent_planner.py`：在每条真实用户消息后调用一次结构化输出，从用户已说的话、已观察的客户信息及旧账本产生任务增量。只在读结果揭示未解析范围或用户纠正需求时再解析一次，不在每个工具调用后反复重规划。结构化响应在入口用类型/schema校验；最多一次有错误信息的修复请求，计入预算。仍失败则明确记录 planning_error，不假称账本完整。

`agent_state.py` 增加有版本的任务结构：稳定任务ID、用户来源消息ID/原文片段、操作类别、对象范围/对象ID、用户约束、缺少的信息、依赖、候选工具及参数、当前状态、proposal/action/receipt关联。用户约束保留来源；模型可以提出待查询选项，不能把自选的付款方式当成用户已选择。应用分配并维护任务ID；不允许一次重规划清空旧的未完成需求或改写已执行历史。

“改账户地址和所有订单地址”首先表示一个账户任务与一个有待展开的订单范围。订单集合仅从当前公开客户上下文/真实读取结果解析，展开为每个对象的子任务；不能看到一个订单就把“全部”标完成。跨对象写入分开跟踪；同一订单的商品修改/换货按政策合并全部选中商品，避免重复调用只能执行一次的修改。查询型任务单独标为 answered，需要关联实际查询观察和已发出的回答，不伪造执行回执。

模型提出依赖和缺项，运行时决定状态。写任务状态：`needs_info → ready → awaiting_confirmation → executed`；拒绝进入`rejected`，需要用户修改/重新授权；用户替换需求进入`superseded`，保留原始记录；政策不支持或真实错误暂不能继续则`blocked`。只有后端 executed 回执且动作/对象/参数匹配，才能进入executed。用户的“已经完成了”和模型自报done均不能推进写任务状态。用户主动结束仍须允许，不强迫完成所有任务。

测试：用独立合成案例覆盖单意图、四项混合需求、“全部订单”、同订单多商品合并、用户改口、补充信息、重复提问、查询+写入混合、无关信息和抽取失败。断言没有遗漏/新增用户未提出的目标、约束有来源、已执行任务不重开、读取未知范围后能正确展开。模拟器/target不进入规划请求，任务日志可复核。

### 模块 B：审批与执行状态由应用驱动

复用现有真实 receipt 和 action-matched 投影，加入显式的“当前待批准操作”“最近实际执行结果”“剩余任务”上下文。业务工具产生proposal时绑定一个任务或同订单的一组任务；批准后的 exact receipt 只结算匹配项。拒绝只结束这张方案，不把其他需求删除，也不自动换一个支付方式重提。重启后从持久状态与回执恢复。

候选执行器在参数齐全时生成无副作用预览，不额外要求一轮聊天yes。每次最多一张待审批卡。批准后继续下一个ready任务；缺少用户明确选择时提出一个简短问题；执行完或用户结束时停止。任务列表是执行选择的上下文，不是绕过模型和审批批量提交的脚本。执行器仍逐次调用原16工具，后端维持原有身份、状态、参数及事务验证。

生成工具请求前核对：是否对应某个尚未完成的用户需求、对象及显式支付/商品/地址约束是否一致。发现冲突反馈给模型或询问用户，不能静默改参数。当前DB事实以已有上下文/允许的读工具为准，agent不使用eval snapshot接口。动作完成后必要时通过读工具复核，额外读调用计入相同预算。

测试：preview不结算；批准只结算对应任务；拒绝不变DB；两个订单同类修改互不串单；旧action不能结算新需求；审批后连续生成下一项正确预览；刷新/重启恢复；已执行的退货或退款不重复提交。用真实HTTP测试整个多操作链路，保留原B1回归测试。

### 模块 C：回复前完成核对与有界纠错

先做基于账本/回执的确定性检查：有pending就等待卡片；有ready项就继续选择下一动作；needs_info就询问；blocked说明原因或转人工。无未完成写任务才允许声称这些写入全部完成。工具失败不会自动将任务标完成。

仅在执行器准备结束回答、但账本仍有未完成项或回答缺少执行证据时，增加一次同模型结构化检查，结果限定为继续、询问、说明未完成、转人工、结束。每个外部turn最多一次检查和一次纠正，不做无限反思循环；检查/纠正调用计入公共预算。判据只使用用户需求、观察、proposal和receipt，不读取target。对不支持的要求解释一次并提供可执行选项，反复坚持时按政策转人工，不能靠重复模板对话消耗预算。

测试：执行器过早说“全部完成”、执行后又要求相同确认、遗漏一个订单、未回答用户要求的退款总额、相同工具参数重复失败、用户合法取消剩余需求；确认检查不能制造新操作或强迫用户批准。人工复核文本事实性，主评分仍只看冻结DB。

### 模块 D：执行上下文与指南

模型请求固定为唯一首条system，包含完整政策、统一应用契约、当前任务表、真实观察摘要和最近回执；保留当前多轮历史。原始历史与审计事件完整落盘。只从真实上下文/工具结果/回执建立事实，不使用模型猜测替代DB。首轮不做跨episode长期记忆、向量检索、历史摘要模型或大规模上下文裁剪。

规划/状态/审批/完成检查先验收；错误上下文和操作指南随后独立消融。指南只从development的可复现失败及政策归纳，保留版本、来源和SHA，冻结后再验证；不得把特定task ID、参考工具序列或目标字段答案写入通用指南。当前静态guide v2保持历史可复现。

当前失败是执行控制与需求遗漏，并非缺少长文知识。RAG、BM25、BGE-M3、多agent、训练暂不进入本轮；若开发集后续证实政策检索/长上下文是主要瓶颈，再单列实验。

### 代码与接口改动范围

| 模块 | 计划改动 |
| --- | --- |
| `backend/agent.py` | 保留B1行为；增加新候选variant的规划、执行、回复检查入口；统一各阶段调用计数和耗时 |
| `backend/agent_planner.py`（新增） | 无工具JSON需求提取/更新；限定结构、来源与一次修复 |
| `backend/agent_state.py` | 任务/范围/依赖状态及proposal、receipt精确关联，保存schema版本 |
| `backend/agent_review.py`（按复杂度决定是否独立文件） | 确定性完成核对及触发式一次模型检查；简单逻辑优先放现有runner |
| `backend/store.py` | 继续使用现有agent_state JSON持久化，按实际需要添加版本兼容；不新建任务数据库 |
| `backend/main.py` / `config.py` | 注册候选variant，输出必要任务进度与manifest版本；内部规划文本不直接暴露给用户 |
| `frontend/src` | 后端稳定后，可选展示各操作的等待确认/已执行/未完成；现有消息和审批端点继续复用 |
| `tests/` | 任务更新、审批结算、检查预算、B1回归、合成HTTP多操作案例 |
| `docs/` | 源码/提示/预算冻结记录、实验矩阵、实际结果和限制 |

复用现有公共执行与快照接口，不建立agent直写DB路径。每次模型调用标记phase（planner/executor/reviewer/repair），每项任务关联turn/tool/action/receipt；指标区分观察事实与模型提议。

### 对比协议与实验顺序

**主baseline固定为当前正常运行的简单B1。** 同一组实验中双方必须使用相同模型权重/量化/thinking/解码参数、用户模拟器版本、初始信息、政策、16工具、审批层、任务集合、target、比较器和预算。所有规划/检查额外调用都计费计预算，不能给候选更多隐含额度。当前target歧义不作为agent专用修复：不强制agent使用参考PayPal、不泄漏gold、不删除失败题。

本阶段先保留现行严格DB规则，将欠明确支付选择和模拟器提前finish作为逐题诊断；审批/账本的合成测试使用明确用户偏好与正确审批，以独立验证agent行为。正式最终比较前，eval负责人冻结选择的口径；若修改用户场景或模拟器语义，双方在新协议下完整重跑，旧分数不混用。agent开发可继续，不依赖先修改所有target。

| 配置 | 新增内容 | 要回答的问题 |
| --- | --- | --- |
| B1 | 最小工具循环 | 简单基线的能力与成本 |
| C1 | B1＋强制需求提取＋账本＋回执驱动续跑 | 是否减少多项需求遗漏和审批状态混淆 |
| C2 | C1＋回复前完成核对/一次纠错 | 是否减少过早结束和重复确认，成本是否可接受 |
| C3 | C2＋按开发失败冻结的错误上下文/短指南 | 是否还有稳定收益；不默认组合越多越好 |

C1本身的最小内部消融：固定规划与账本，关闭回执投影；用于区分“记录任务”与“执行状态表达”的作用。资源允许时再做错误上下文/指南单独开关；不同时启动大量组合。

执行顺序：

1. **G0 冻结baseline**：保存B1受测源码、输入与评测版本，新增候选variant名，不更改历史结果。
2. **G1 合成案例**：实现A/B，先本机小测试，再huoshan完整软件/HTTP验证；优先用新客户与新对象的四任务、拒绝/改口、恢复案例。
3. **G2 C1功能smoke**：huoshan同9B配置跑完整smoke8，核对规划覆盖、真实审批与回执、额外成本。8题仅做功能检查，不用于正式提升结论。
4. **G3 开发集迭代**：在development54上跑B1/C1/C2，保存失败分类后才决定C3；先小片确认再批量。仅development轨迹可用于改指南。9B属于开发模型组，不能和27B成绩混合。
5. **G4 验证与选择**：预先约定一次候选检查点，在validation20比较主要候选。若成功率不提高或成本明显不值得，保留B1，不按单个有利子集挑结果。27B就绪后在同一27B组重新建立baseline并确认候选。
6. **G5 最终评测**：模型/模拟器/数据/agent/指南全部冻结后，B1和选定候选各test40×3。test期间不修改配置，不基于test失败继续调当前候选。

主指标：固定范围最终DB success、三次全成功pass^3、按任务聚类的配对差值区间。辅助：各阶段模型调用/token、工具请求、延迟、完整每成功成本、重复失败工具、人工审阅的遗漏需求/错误完成声明/重复确认。模拟器协议错误、语义提前退出和目标欠明确分别列诊断，仍保留规定分母；不自动将它们移除以制造提升。

验收要求：软件状态/审批/预算测试全部通过，原B1回归不退化；新候选的每个executed任务都有真实匹配回执；审批后能继续下一项独立需求；任何性能结论必须来自完整同协议比较。若仅节约token而成功率持平，则报告效率观察，不宣称成功率提升。以上为原始设计与验收要求；C1/C2当前实施进度见下文，C3尚未启动。

### C1 实施进度（2026-11-18）

已保留baseline标签 `baseline/b1-http-v1@03ac358`。新增实验variant `c1`，实现强制结构化规划、账户/单订单/订单集合类型、按公开订单展开、稳定任务ID、依赖与已知参数检查、真实proposal/receipt关联、拒绝后不自动重提、原始规划记录及阶段计费。普通session不暴露内部规划；私有eval快照增加agent_state。B1不使用规划器，前端默认仍为B1。

本机12项C1小测试和原26项agent/传输测试通过，前端构建通过。早期huoshan完整套件128项通过。真实9B合成四操作验证先后发现长原文quote格式丢失与账户任务scope混淆，均在写入前拦截；已经收紧短quote和typed schema，完整套件与同案例重测进行中。这些是开发集成诊断，未取得C1 benchmark成功率。C2尚未实现；C1记录查询需求但暂不认证自由文本已回答，不能把记录账本等同于完成校验。

C1真实模型集成补充：逐字复述source_quote在9B上反复失败，改为结构化引用现有用户消息ID（schema枚举），应用从该消息保存原文作为证据；避免模型复制/改写原始文本。任务scope也通过账户/单订单/订单集合联合schema约束。尚未明确对象ID的两个任务保持独立，不能因object_id均为空而合并。旧失败案例与token成本保留。

C1消息ID版本的真实合成验证已一次提取四个任务（无需修复），执行了账户地址和两个订单地址，但取消操作仍因多余聊天yes停留在ready，严格四操作验收失败。基于这一复现按计划加入独立C2：参数齐全时回复前确定性续跑一次，其他未完成/执行后答复进行同模型一次有界检查；C1/B1不启用该检查。C1/C2本机19项测试通过，C2完整远程与真实同案例正在验证。

C2在消息ID规划器版本下通过真实四操作合成验收（`c2-four-operations-20261118T085948Z`），4项真实写入及回执齐全，DB严格匹配；138项完整软件测试通过。随后完整C1 smoke前两题暴露未知参数名和商品/订单ID混淆，开发批次已标记superseded，未当完整成绩。规划器v3改为直接字符串/字符串数组参数、可用参数名与按对象类型限制的ID枚举；两道原失败题真实规划一次通过，20项C1/C2定向测试通过。即将对v3做完整集成与冻结smoke重测。

C2纠正机制补充：真实四操作v3复测中，纯文字纠正后仍出现额外聊天yes。改为仅对参数齐全且依赖完成的ready任务，在唯一纠正调用上使用标准named tool_choice选择下一业务工具生成预览；工具目录与参数schema不变，参数约束和真实卡片批准仍生效。业务错误记录blocked并拦截相同参数重复写入；新增原生HTTP传输测试确认tool_choice不执行DB变更。

最新验收：冻结代码 `5a928fe` 在huoshan完整142项测试通过；C2真实四操作案例DB与四条executed回执全部匹配，真实named tool_choice协议单独通过。冻结smoke8批次 `c1-c2-v3-smoke-20261118T092829Z` 已启动，未完成前不报告C1/C2成功率；B1默认不变。

开发发现并修复同对象替换bug：原实现先合并新任务再supersede旧ID，可能误废弃细化后的请求。现先处理显式替换，禁止复用被替换ID，给新任务独立ID并将原依赖接到替代任务；supersede只能引用最新用户消息。新增同对象改地址/依赖保持与来源时效测试，本机24项C1/C2测试通过。此前v3 smoke标记为不完整开发记录，不输出完整成功率。

最新软件回归：`dfe9b23` 在 huoshan `c1-c2-replacement-regression-20261118T094550Z/` 完整145项通过（67.05s）；`c1-v4-replacement-20261118T100234Z/` 真实两轮公开输入复测通过，任务细化后换货请求及明确参数保留。下一步冻结源码跑C1/C2完整smoke8，尚无新候选成功率结论。

### 完整 smoke 后的修订：减少结构化控制负担（2026-11-18）

`c1-c2-v4-smoke-20261118T100356Z` 已完整完成：同协议B1=6/8，C1=3/8，C2=2/8。C1有3个agent_error（任务更新/废弃冲突、参数对象冲突、规划空白循环截断）；C2有7个检查阶段错误及1个规划截断，8题均异常结束。C2两题最终DB仍匹配，按纯DB规则计成功。不能把异常早停造成的低token当效率提升。

参考依据及采用范围：

- [tau2官方原生工具循环](https://github.com/sierra-research/tau2-bench/blob/main/src/tau2/agent/llm_agent.py)：保留政策、历史、原生工具调用这一最小执行层，不替换为多agent框架；本项目业务环境仍使用固定tau2 SHA，未升级依赖。
- [Anthropic evaluator-optimizer 示例](https://github.com/anthropics/claude-cookbooks/blob/main/patterns/agents/evaluator_optimizer.ipynb)：检查与执行分离，检查输出评价和反馈。这里只保留一次有界检查/纠正，不采用示例的开放式循环。
- [JSONSchemaBench (2025)](https://arxiv.org/abs/2501.10868)：语法合规、覆盖与输出质量需要分别衡量。我们将协议失败、语义任务状态及实际DB分数分开；schema合法不等于任务正确。
- [When Can LLMs Actually Correct Their Own Mistakes? (TACL 2024)](https://aclanthology.org/2024.tacl-1.78/) 与 [Large Language Models Cannot Self-Correct Reasoning Yet (ICLR 2024)](https://arxiv.org/abs/2310.01798)：外部可靠反馈与无依据自评不同。当前采用实际业务回执/参数校验作确定性反馈，不假设增加自评必然提高成功率。这是用于本任务的设计推论，论文并未验证本项目。
- [vLLM v0.17.1 structured outputs](https://github.com/vllm-project/vllm/blob/v0.17.1/docs/features/structured_outputs.md)：在提示中明确schema及字段含义。远程安装代码确认xgrammar的任意空白开关取自引擎配置；本轮不改模型服务及模拟器配置，以保持与B1同协议。

具体修改：

1. C1规划v5在可见输入中带完整动态输出schema；要求紧凑JSON、必须输出tasks与supersede；补充信息属于原任务更新，不得同时更新/废弃同一ID。object_id由应用绑定，生成schema不再允许重复生成user_id/order_id参数。审批不属于missing。拒绝冲突的校验仍保留。
2. 规划格式/截断错误共享最多一次修复额度，所有实际用量保留；仍失败则保持旧账本、停止本轮新写入并请求用户澄清，不使用不完整计划执行，也不改为无校验直写。预算耗尽仍真实终止。
3. C2检查v3仅返回accept/revise/handoff、简短feedback及可选信息任务ID。删除自由改写reply和逐字复制quote要求；动态schema只允许当前未回答的信息任务ID，写任务不能被检查器结算。accept保持原答复；信息任务记录原答复和实际观察供审阅，明确是模型判断而非事实认证。
4. 检查格式错误记录原文与错误，执行器在既有一次纠正额度内根据账本/回执回复，检查器错误不再直接抛出agent_error；不额外给检查器重试预算。ready任务仍经原生工具生成预览，再经过真实审批。B1路径、16工具、target及模拟器均不变。

验证顺序：本机定向回归 → huoshan完整软件套件 → 上一批公开输入的规划/检查复现（不输入target/隐藏用户场景）→ 冻结新版本C1/C2各smoke8。保留v4失败及新协议日志，完整成绩出现前不报告提升，不提前扩大development54。

真实阶段重放补充：`c1-v5-stages-20261118T122309Z` 的2个planner与7个reviewer均格式通过，但人工复核发现自由feedback会误判商品并重新要求聊天yes。故在正式smoke前进一步收紧检查v4：action + 固定issue枚举（none/omitted_request/premature_completion/redundant_confirmation/needs_handoff）+ 信息任务ID；由应用将issue映射为固定纠正提示。模型不再生成纠正事实、商品选择或确认规则。检查只看任务覆盖/实际执行状态；正常询问未知偏好默认accept，不评商品、价格或文风。此前9项仅作为格式复现证据，不称语义验收。

### Advisory 实验：移除错误账本对执行器的强制控制（2026-11-18）

v5 C2完整结果为3/8（比旧C2的2/8多一题，仍低于B1的6/8），186次模型调用、82次工具请求，1个agent_error、1个wall_time_budget；最后一题有一次usage未知，总token不可报完整数。task24/47显示具体控制缺陷：错误的ready任务触发强制工具选择/替换回复，形成循环。task24把撤销取消误作重新取消；task47把用户明确指定的吸尘器类型映射错，正确执行器参数受错误known_args阻挡。

新增独立variant `advisory`，保留原B1/C1/C2供对比：

- 复用相同规划器、账本、回执投影及有界检查，但账本明确是可错的模型笔记。以用户实际最新请求、政策和真实观察为准，不用账本known_args/依赖直接拒绝业务预览。
- 不根据ready笔记强制named tool_choice，也不在纠正后用固定未完成模板覆盖执行器回复；修复“错误计划比正确执行更有权威”的问题。
- 实际回执仍约束动作：没有新用户消息时，不能重新提交已拒绝的同类同对象操作，不能重复提交完全相同的已执行动作。新用户明确请求后可提出新预览。所有业务权限、参数验证和用户审批仍在公共后端。
- 加入通用对象筛选与撤回语义提示：只考虑符合用户明确属性的对象；拒绝是用户决定，不表述为系统失败或永久禁止；未执行请求撤回后保持DB，不强迫执行；继续独立查询需求。
- 规划器两次失败时，advisory允许基础执行器继续读取/沟通，原始失败与调用计费保留，写操作仍经公共预览/审批。其他variant的失败策略不变。

先用注入错误计划的小测试检查：撤回请求不被ready笔记强制执行；旧参数不阻挡当前用户的正确预览且批准前DB不变；拒绝后禁止同轮换参数重提，新用户请求后可重提；规划失败不阻断信息查询。之后huoshan完整套件及两类真实HTTP合成对比（撤销取消后查询、拒绝地址方案后修改），合成验证通过才跑advisory smoke8。小案例使用独立合成对象和明确参数；不修改target/模拟用户，不把合成通过视为benchmark提高。原v5 C1批次继续，新的模型实验排在它之后，避免共享推理队列影响旧组600秒预算。
