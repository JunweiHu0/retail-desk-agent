# TACC Retail Benchmark — Qwen3.8-27B / deep_retail 基线报告（2026-11-22）

> 依据：`TACC-Retail-Benchmark-Handoff-2026-11-22.md`。归档目录：`tacc-20261116/final-qwen3.8-27b-deep_retail-dev-e09bba6-nothink-seed42-20261122/`。
> 所有分数均来自**未修改的官方 tau2 scorer / gold**。本文不包含任何 LangGraph 实测结果（尚未运行，见 §6）。

## 0. 运行状态摘要

<!-- RUN_STATUS_START -->
| 项 | 值 |
|---|---|
| 状态 | **113/114 有效，未完成**。task 89 在作业 29969 和 30449 中两次都在 NL judge 阶段报 `JSONDecodeError`（同一位置 `line 8 column 26 (char 312)`），属于确定性的 infra 错误，**本 run 不能作为最终官方成绩** |
| 最终结果文件 | `raw/results.json`（sha256 `39c0ae02…3585`，作业 30449 后下载：先写临时文件、校验 114 行无重复，再替换），114 行，task id 无重复 |
| 终止原因 | user_stop 112 / max_steps 1（task 99）/ infrastructure_error 1（task 89） |
| 分桶 | pass 90 / 普通 0 分 22 / max_steps 1 / agent error 0 / infra 1 / missing 0 |
| pass^1（分母 114） | 下界 90/114 = **0.7895**（89 记为未通过）；上界 91/114 = 0.7982。**区间 [0.7895, 0.7982]** |
| 平均 reward（仅 113 个已评分任务） | 0.7965（tau2 自带汇总：Pass^1 0.789，排除 1 个 infra） |

**task 89 根因（已确认）**：traceback 为 `simulation.run_simulation → evaluator.evaluate_simulation → NLEvaluator.calculate_reward → evaluator_nl_assertions.py:123 json.loads(assistant_message.content)`。对话本身已经结束，失败点是 judge（qwen3.8-27b, temperature 0）为 4 条 NL assertion 生成的 JSON 不合法；该行没有异常保护，run_with_retry 只尝试了 1 次。因为是 temperature 0 加固定 seed，直接重跑会得到同样的结果，所以没有再提交第三次。要拿到 89 的有效分数，需要团队决定以下方案之一（都不改 gold）：(a) 换一个更强的 judge，或给 judge 开启 JSON mode / `response_format`，并对全部 114 个任务统一重评；(b) 只对 89 重跑并允许 judge 重试（需在报告中说明）。在没有获批之前，本 run 不报最终官方成绩。
<!-- RUN_STATUS_END -->

计分口径：task 89 在拿到有效终止之前一律记为 infra，不当作普通失败，也不会被静默删除；max_steps 按 tau2 官方规则记 reward 0，但单独列出。

## 1. 可复现基线配置

| 维度 | 值 |
|---|---|
| tau2-bench | commit `0c69df456a96aa76a1162591574dad9c427a34d7`（2026-10-24, "Merge PR #679", sierra-research/tau2-bench, tau2 2.0.0）。TACC 上 `$TACC_USERDIR/retail-agent/eval-20261116-nothink/tau2-bench` 是上传的副本，不含 .git；对照本地 `.deployment/package` 后，`domains/retail/tools.py` 完全一致 |
| Agent 代码 | 仓库 `JunweiHu0/retail-desk-agent`，分支 `dev` @ `e09bba63cde046457d436e49566a09027a568606`（2026-10-27）+ TACC 本地补丁（2 个文件，见下） |
| Variant 名 | `deep_retail`（`benchmarks/tau2_agent.py::DeepRetailAgent`，deepagents `create_deep_agent` + `wrap_model_call` middleware），本文记为 **`dev@e09bba6+tacc-nothink`** |
| TACC 补丁 | `backend/agent.py`：LLM timeout 60→180 s；`extra_body={"chat_template_kwargs":{"enable_thinking":False}}`。`benchmarks/run_retail.py`：新增 `--auto-resume`（重跑 infrastructure_error 行）；user sim 的 provider_args 也加了 enable_thinking False |
| Agent 模型 | Qwen3.8-27B AWQ INT4，vLLM 部署（TP=2，max-model-len 32768，reasoning-parser qwen3，auto tool choice），temperature 0 |
| User simulator | `openai/qwen3.8-27b`，与 agent 同一 vLLM 服务，temperature 0，enable_thinking False |
| NL judge | `openai/qwen3.8-27b`，同上。**注意：与 tau2 默认的 GPT 系 judge 不同，分数不能直接和论文榜单比较** |
| seed / trials | 42 / 1 |
| max_steps / max_errors / timeout | 100 / 10 / 600 s |
| 并发 | 3 |
| communicate 打分 | semantic（`communicate-semantic-v1`） |
| 数据 | domain_tools_version `speech-identity-v1`；runtime_rules `regional-tools-v1`（sha `03443b64…`）；pack_revision `voice-v2-entity-order-v5-schema3-textneutral-voiceclauses`；domain_revision `voice-v2-frozen50-v1`；pack_sha256 `6453ef2c…`，tasks_sha256 `2ba1277c…`，metadata_sha256 `2c28ba93…`，scenario_sha256 `0f173e03…`；task split `base`，114 任务 |
| results `info.git_commit` | `"unknown"`（上传副本无 .git，因此需在本报告里补记 commit） |
| 资源 | TACC partition `tacc`，2×GPU，节点 10-0-4-11，1 小时时间片，singleton 作业链 |
| 作业 | 29191（首次全量）→ … → 29969（续跑，113/114）→ 30449（task 89 重跑，仍为 infra，已结束，没有后续作业） |
| 结果位置 | 远端 `$TACC_USERDIR/retail-agent/eval-20261116-nothink/full/results.json`；本地归档见归档目录 |

复现命令（凭据由作业环境注入，此处不写）：

```
python -m benchmarks.run_retail --all --auto-resume --save-to "$results/full" \
  --user-model openai/qwen3.8-27b --judge-model openai/qwen3.8-27b \
  --seed 42 --max-steps 100 --timeout 600 --concurrency 3
```

## 2. Badcase 表

维度：意图/状态追踪 · 业务政策 · 工具选择 · 参数抽取 · 写操作授权 · 数据库状态 · 最终答复遗漏 · 步数/超时 · 评测基础设施，另加 **user-sim 偏移** 和 **benchmark 问题**（不属于 agent 的错误）。证据里的 `[n]` 指 results.json 中该 simulation 的消息下标。

| Task | reward / 终止 | DB / NL | 失败维度 | 证据 | 建议动作 | 复测状态 |
|---|---|---|---|---|---|---|
| 28 | 0 / user_stop | DB ✓ / NL ✗ | 最终答复遗漏 | 退款写操作和 gold 一致，但对话里从未说出合计 $918.43；之后的转人工由用户接受 | 回归用例：完成退货后必须报出退款总额 | 未复测 |
| 35 | 0 / user_stop | DB ✗（缺 modify） | 状态追踪 + 价格方向错误 | 从未调用 `modify_pending_order_items`；agent 称 13 寸更便宜、没有银色 i5，但实际 5052031638 需补差价 +$113.71，用户因此拒绝。**纠正交接文档里的原判断** | 写操作前先根据工具结果计算差价并如实告知 | 未复测 |
| 41 | 0 / user_stop | DB ✗（缺 2 个写） | 状态追踪 | 两个地址只改了一个 | 回归用例：多订单/多地址要逐一枚举 | 未复测 |
| 42 | 0 / user_stop | DB ✗ | 状态追踪 | 同上，漏改第二个地址 | 同 41 | 未复测 |
| 46 | 0 / user_stop | DB ✓ / NL ✗ | user-sim 偏移 | user sim 只问了吸尘器；gold 要求告知 $1,497.65 | 不改 agent，记录为 user-sim 噪声 | 未复测 |
| 52 | 0 / user_stop | DB ✗ | 观察误读（另有 benchmark 歧义） | 误读库存，gold 用的是 9228757377 | agent 侧：列选项时如实读 `available` 字段 | 未复测 |
| 59 | 0 / user_stop | DB ✗ | user-sim 错误 | user sim 把两个订单弄反了 | 记录为 user-sim 噪声 | 未复测 |
| 64 | 0 / user_stop | DB ✗ | 候选假阴性：合理但未覆盖的替代方案 | 用户没指定颜色，agent 选了 silver，gold 是 black；gold 里另有一条对 pending 订单做 exchange 的 no-op（`known_failures.py` 有记录） | 见 §4.1 | 未复测 |
| 66 | 0 / user_stop | DB ✗ | user-sim 偏移 | user sim 中途改成保留订单，gold 是取消 | 记录为 user-sim 噪声 | 未复测 |
| 68 | 0 / user_stop | DB ✓ / NL ✗ | user-sim 错误 / benchmark 歧义 | user sim 选错订单；benchmark 默认列表顺序就是时间先后 | 见 §4.1 | 未复测 |
| 76 | 0 / user_stop | DB ✗ | 业务政策 + 状态追踪 | 编造"pending 订单可以单独删除某件商品"的政策，并漏掉取消操作 | 回归用例：pending 订单不能删单件 | 未复测 |
| 82 | 0 / user_stop | DB ✗ | 观察误读（user-sim 偏移是次要原因） | 认错了平板在哪个订单 | 按 item 反查订单 | 未复测 |
| **89** | **None / infrastructure_error** | — | **评测基础设施** | NL judge 输出的 JSON 不合法，在 `evaluator_nl_assertions.py:123` 抛出 `JSONDecodeError`；29969 和 30449 两次报错位置完全相同（char 312），没有保存 trajectory | 由团队决定 judge 方案（JSON mode / 更强的 judge / judge 重试），之后统一重评 | **已重跑 1 次，确定性复现，仍为 infra** |
| 93 | 0 / user_stop | DB ✗ | 状态追踪 | 从未查询 #W4073673，也没有确认是哪台笔记本 | 同 41 | 未复测 |
| 95 | 0 / user_stop | DB ✗ / NL ✗ | user-sim 偏移（由 agent 引发） | agent 多问了一句颜色，user sim 于是选了 6017636844（15" i7/32GB/1TB 深空灰，$2292.37，确认有货），而 gold 是 9844888101（黑色 8GB，$2459.74） | 只在必要时追问 | 未复测 |
| 97 | 0 / user_stop | DB ✗ | 观察误读 / 状态追踪 | 把 NY 订单当成了 LA 订单，漏改地址；modify 在一次选错工具后恢复，结果与 gold 一致 | 同 41 | 未复测 |
| 98 | 0 / user_stop | DB ✗ | 业务政策 + 写操作授权 → agent 导致的转人工 | 没提相机换货；"另一张卡"有歧义；agent 误取消了整单，然后转人工 | 回归用例：整单取消前要警告并确认 | 未复测 |
| 99 | 0 / max_steps | — | 步数 | 反复调用 `calculate`，直到达到 100 步 | 回归用例：重复调用保护 | 未复测 |
| 100 | 0 / user_stop | DB ✗ | user-sim 偏移 | 用户主动要求转人工；按政策转人工是正确的 | 记录为 user-sim 噪声 | 未复测 |
| 104 | 0 / user_stop | DB ✗ | 状态追踪 | 漏掉 #W6239298 里的书架和拼图 | 同 41 | 未复测 |
| **105** | 0 / user_stop | DB ✓ / NL ✗ | **确认的 benchmark 问题** | 见 §4.1 | 记入 benchmark 问题清单 | 无需复测 |
| 109 | 0 / user_stop | DB ✗ | user-sim 错误 / benchmark 歧义 | user sim 给的"新"地址是错的 | 记录 | 未复测 |
| 110 | 0 / user_stop | DB ✗ | user-sim 错误 / benchmark 歧义 | 同 109 | 记录 | 未复测 |
| 112 | 0 / user_stop | DB ✗ | user-sim 偏移 | user sim 多提了要求，导致多出一次地址写操作 | 记录 | 未复测 |

**汇总（23 个 reward 0 + task 89）**

| 类别 | 任务 |
|---|---|
| agent 侧错误 | 状态追踪/观察误读 41, 42, 52, 82, 93, 97, 104；政策 76, 98；价格沟通 35；最终答复遗漏 28；步数 99 —— 共 12 个 |
| user-sim 偏移或错误 | 46, 59, 66, 68, 95, 100, 109, 110, 112 —— 共 9 个（95 由 agent 引发） |
| benchmark 问题或候选 | 105（确认）、64（合理但未覆盖）—— 共 2 个 |
| 基础设施 | 89 |

所有判断的证据都来自本次 results.json 的单次 trial（seed 42）。user-sim 类判断在多 trial 下的稳定性**待证**。

## 3. 转人工分析与 state contamination 检查

在全部 114 行中扫描 `transfer_to_human_agents`，共 10 次：

| Task | reward | 性质 |
|---|---|---|
| 10, 12, 25, 50 | 1 | 政策拒绝之后用户主动要求转人工，属正常 |
| 34 | 1 | agent 提议转人工，用户同意；gold 只要求改地址。另发现 adapter 的 guard 文本（`variant_change_error`）在 [22] 原样发给了用户 |
| **36, 37** | 1 | **异常转人工**。`modify_pending_order_items` 返回的结果里，Action Camera 和 Desk Lamp 带上了 T-Shirt 的 options 和 $46.66 的价格。36 中 agent 没解释就转人工；37 中 agent 说明了"记录损坏"后转人工 |
| 28 | 0 | 用户接受转人工 |
| 98 | 0 | agent 自己误取消整单后转人工 |
| 100 | 0 | 用户要求转人工 |

**36/37 的根因：tau2 上游工具 bug，不是 session 污染。** `tau2/domains/retail/tools.py::modify_pending_order_items` 的最后一个循环复用了校验循环遗留下来的 `variant`：

```python
for item_id, new_item_id in zip(item_ids, new_item_ids):
    item = next(...)
    item.item_id = new_item_id
    item.price = variant.price      # 复用的是上一个循环最后的 variant
    item.options = variant.options
```

一次修改多个 variant 时，除最后一个以外的商品都会写入错误的价格和 options。gold 回放用的是同一个工具，DB hash 依然一致，所以这类任务的分数不受影响，但 agent 看到的观察结果被污染了，因而触发转人工。受影响的任务：agent 做过多 variant modify 的有 20, 21, 36, 37（都是 reward 1）；gold 含多 variant modify 的有 20, 21, 36, 37, 100。

**Session/state 污染检查（handoff 要求的 `AgentRunner.run()` / `_loop()` / `run_graph()`）：**

1. 本次 TACC run 走的是 `dev` 分支的 `benchmarks/tau2_agent.py`。tau2 的 `factory` 每个 simulation 新建一个 `create_deep_agent`，**根本没有经过** `AgentRunner` 或 `run_graph`；模块里也没有跨 simulation 共享的可变状态。
2. 我对 `origin/backend`（0485c4c）做了代码审查：
   - `AgentRunner.run()` 按 sid 从 Store 读取 history，处于 pending/transferred/finished 状态时拒绝继续。
   - `_loop()` 在 variant 属于 `GRAPH_PROFILES` 时分派给 `run_graph`。
   - `run_graph` 的状态是按 sid 存的 `agent_state.graph_v1`；notes 在每条新用户消息时清空；工具闭包都是局部变量。
   - 没有发现跨会话共享的可变对象。
3. 结论：**目前没有证据表明转人工是 session 污染造成的**（置信度：中高）。已观察到的异常转人工来自上游 stale-variant bug。backend 并发写 Store 的竞态没有压测过，**待证**。

## 4. 三个小组议题

### 4.1 Gold 过度约束导致的假阴性

- **证据/复现**
  - **task 105**：agent 选的 variant 正是 gold 的 3761330360（ceramic 2L gas, $101.12）和 9647374798（glass 1.5L gas, $109.58），差价 +$21.10，但用户唯一的支付方式 gift_card_7245904 只剩 $17.00。gold 的 `exchange_delivered_order_items` 在 tools.py:304 抛出 "Insufficient gift card balance"，所以 gold DB 等于初始 seed，agent 的 DB 也匹配。但 NL assertion 要求"两件都换掉"，这在物理上做不到，所以 reward 只能是 0。backend 分支的 `benchmarks/reference/known_failures.py` 独立审计出了同一条（`("105","106_0")`）。
  - **task 64**：用户没指定颜色，agent 选 silver，gold 是 black。另外 gold 的 action 64_6 对 pending 订单做 exchange，是 no-op（known_failures 有记录）。
  - **task 68 / 109 / 110**：user sim 的错误部分来源于任务描述的歧义（订单的先后顺序、"新"地址指哪个）。
- **当前判断与置信度**

  | 分类 | 任务 | 置信度 |
  |---|---|---|
  | 确认的 benchmark 问题 | 105 | 高 |
  | 合理但未覆盖的替代方案 | 64 | 中 |
  | benchmark 歧义 + user-sim 错误 | 68, 109, 110 | 中低 |
  | agent 错误 | 35（交接文档原本怀疑是 gold 问题，复查后确认是 agent 报错价格方向）, 28 | 高 |
  | 证据不足 | 52（库存可读性是否构成歧义） | — |
- **建议的变更**：不改官方 scorer/gold。另建一份 `benchmark-issues.json` 清单（task id、类型、证据、tau2 commit），报告里同时给出"官方分"和"排除已确认 benchmark 问题后的诊断分"。后者必须明确标注为非官方。
- **验收用例**：脚本读入 results.json 和清单，输出两种分数；对 task 105 断言 `db_match=True`、NL 失败、并被标记为 benchmark_issue。
- **待团队决策**：诊断分是否只排除"确认"一类？是否向 tau2 上游提 issue（105、64_6，以及 §3 的 stale-variant bug）？

### 4.2 异常转人工

- **证据/复现**：见 §3。36/37 可以确定性复现：对任意 pending 订单在一次调用里修改 ≥2 个 variant，观察返回结果中前面几件商品的 price/options。
- **当前判断与置信度**：异常转人工的主要原因是 tau2 stale-variant 工具 bug（高）；不是 session 污染（中高）。98 是 agent 自己的政策错误导致的（高）。34 的 guard 文本泄露属于 adapter 的 UX 问题（高）。
- **建议的变更**
  1. 官方计分 run **不修改** tau2 工具。可以另做诊断 run，打上一个修好的 `variant` 补丁（在 zip 循环里按 new_item_id 重新查 variant），这类 run 必须标注为非官方。
  2. agent 侧：工具返回的价格/options 与刚查询的 variant 对不上时，先重新 `get_order_details` 核对，并如实告诉用户，不要默认转人工。
  3. adapter：`variant_change_error` 改成发给模型的 ToolMessage/系统提示，不要以 AIMessage 发给用户。
- **验收用例**：36、37、20、21 中没有用户请求的转人工数为 0；34 的对话里不出现 guard 文本；新增单元测试，确认 stale-variant 修补后多 variant modify 的价格逐项正确（只在诊断 run 中启用）。
- **待团队决策**：是否接受"诊断 run 打工具补丁"的做法，还是只向上游报告？

### 4.3 人工 fallback / 审核流水线

- **证据**：10 次转人工里，6 次是用户合理请求，4 次属于异常或由 agent 导致（34、36、37、98）。backend 分支的写操作已经走 preview → action card confirm → 服务端校验（WEB_CONTRACT：聊天里说"yes"不算授权）。
- **当前判断**：转人工本身不扣分（例如 36/37 都是 reward 1），所以离线分数衡量不出 fallback 的质量，需要单独的指标。
- **建议的变更**
  1. **Shadow mode 先行**：在 `transfer_to_human_agents` 和高风险写操作（整单取消、多 variant modify、差价超过余额）前，异步调用一个 reviewer（规则 + LLM），只记录"会拦截/会放行"及原因，**不改变**线上行为。
  2. 保持现有边界：reviewer 只能建议，不能直接执行写操作；写操作仍然必须 preview → 用户在 action card 上 confirm → 服务端按政策校验。reviewer 不能替用户确认。
  3. Shadow 指标：转人工 precision（用户确实请求或政策要求）、整单误取消拦截率、误拦截率。
- **验收用例**：在 tau2 回放中 shadow reviewer 应标出 98 的整单取消和 36 的无请求转人工；对 10/12/25/50 应放行；全程 DB 结果与不开 shadow 时逐字节一致。
- **待团队决策**：reviewer 用哪个模型、可以接受多少额外延迟；shadow 运行多久、指标达到什么阈值才切到 enforce。

## 5. 回归用例（建议）

| ID | 来源 task | 断言 |
|---|---|---|
| R1 | 28 | 退货/退款完成后，最终答复包含退款总额 |
| R2 | 35 | modify/exchange 前计算并说出差价的方向和金额 |
| R3 | 76 | 拒绝从 pending 订单中删单件商品，不编造政策 |
| R4 | 99 | 同一工具以相同参数连续调用 ≥3 次时触发保护，停止循环 |
| R5 | 98 | 整单取消前列出订单内全部商品，并要求明确确认 |
| R6 | 41/42/93/104/97 | 用户提到多个订单或地址时，逐个 `get_order_details` 并核对 |
| R7 | 34 | adapter guard 文本不出现在发给用户的消息里 |
| R8 | 36/37 | 多 variant modify 后，即使观察结果异常，也不在用户没请求时转人工 |

R1–R6 在 LangGraph 的哪个 profile 上覆盖：backend 的 `lg_sop` / `lg_notes` / `lg_review` 有 SOP、按轮 notes 和 review 节点，理论上对应 R2、R5、R6，但**没有任何 tau2 实测，覆盖情况待证**。backend 的 `tests/test_graph_agent.py` 目前只测图结构和状态持久化，不包含上述行为断言。

## 6. 公平的 LangGraph 对比：方案与阻塞项

**阻塞项（截至 2026-11-22）**

1. `origin/backend`（0485c4c）**没有** `benchmarks/run_retail.py` 和 `benchmarks/tau2_agent.py`，README 第 147 行引用的是旧文件。现有的只有 `benchmarks/run_http.py` 加 `reference/`，是一套自定义的 HTTP DB-only 协议，有自己的 user simulator（visible-action-schema-v2）和 action card 确认语义，**不是官方 tau2 scorer**，分数不能和本报告比较。
2. TACC 上没有任何 LangGraph run 的结果。
3. 两个分支的确认语义不同：dev 直接写，backend 是 preview + card。要放进 tau2，需要定义"card 确认"在 half-duplex 对话中的映射，否则不公平。

**方案**

1. 在 backend 分支新增 `benchmarks/tau2_graph_agent.py`：一个 `HalfDuplexAgent`，每个 simulation 新建一个 sid，调用 `run_graph(profile)`；tau2 的工具调用直接映射到 retail 工具。preview/confirm 映射为"用户在对话中明确同意后再执行"，与 tau2 政策一致。
2. 固定以下条件与本基线一致：tau2 commit 0c69df4、相同的 data pack sha256、同一个 vLLM Qwen3.8-27B（nothink）、user sim 和 judge 同模型、seed 42、max_steps 100、timeout 600、concurrency 3。
3. 至少跑 `lg_b1` 和 `lg_review` 两个 profile，每个 ≥3 trials（报 pass^k）；同时 deep_retail 也补跑到 3 trials，以消化 user-sim 噪声（本报告有 9 个 user-sim 类失败）。
4. 对比时按本报告 §2 的维度分桶，并单独报告 benchmark 问题任务（105、64）。
5. **不得**把 Qwen 和 DeepSeek 之间的差异归因到框架：模型不同的结果只能作为参考，不参与框架结论。

## 7. 结论

### 观察到的事实
- 114 个任务、114 行、没有重复；112 个 user_stop、1 个 max_steps（99）、1 个 infra（89）。
- task 89 两次在 `evaluator_nl_assertions.py:123` 报同样的 `JSONDecodeError`，可以确定性复现。
- 90 个通过；pass^1 区间 [0.7895, 0.7982]，**不是最终官方成绩**；已评分的 113 个任务平均 reward 为 0.7965。
- 23 个 0 分中，DB 匹配但 NL 失败的有 4 个（28、46、68、105）；其余是 DB 不匹配或 max_steps。
- 共 10 次转人工；36/37 的工具返回结果显示出 stale-variant 写错价格。
- backend 分支没有官方 tau2 adapter。

### 基于证据的根因判断
- agent 侧主要问题是多实体状态追踪和观察误读（7 个），其次是政策幻觉（76、98）、价格沟通（35）、最终答复遗漏（28）、循环（99）。
- 105 是确认的 benchmark 问题；36/37 的异常转人工来自 tau2 上游工具 bug，与 session 污染无关。
- 9 个失败主要由 user sim（与 agent 同一个 Qwen 模型）的偏移或错误造成。

### 尚未验证的假设
- user-sim 类失败在多 trial 下是否稳定（需要 ≥3 trials）。
- LangGraph 的 `lg_sop` / `lg_review` 能否修复 R2/R5/R6。
- 换成更强的 user sim / judge 后，9 个 user-sim 类失败是否会消失。
- backend Store 在并发下是否有竞态。

### 下一轮实验
1. 团队选定 judge 方案（见 §0）之后，补齐 task 89，得出最终官方分。建议开 JSON mode 统一重评 114 个任务，以免只有 89 用不同的 judge 设置。
2. deep_retail 补跑到 3 trials。
3. 实现 `tau2_graph_agent.py`，跑 `lg_b1` 和 `lg_review` × 3 trials。
4. 做一次带 stale-variant 补丁的诊断 run（非官方），验证 36/37 的转人工消失。
5. 把 R1–R8 实现为回归测试。
