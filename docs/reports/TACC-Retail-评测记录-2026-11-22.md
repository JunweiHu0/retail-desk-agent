# TACC Retail 评测记录 — Qwen3.8-27B / deep_retail（2026-11-22）

> 独立记录，取代之前 Notion 页面上基于 2026-11-19 快照写的草稿。
> 详细分析：[TACC-Retail-Qwen-Baseline-Report-2026-11-22.md](TACC-Retail-Qwen-Baseline-Report-2026-11-22.md)
> 与 proposal 对齐（指标定义、3 组 baseline、3-trial 运行矩阵）：[TACC-Retail-Proposal-Alignment-2026-11-22.md](TACC-Retail-Proposal-Alignment-2026-11-22.md)
> 原始数据归档：[final-qwen3.8-27b-deep_retail-dev-e09bba6-nothink-seed42-20261122/](tacc-20261116/final-qwen3.8-27b-deep_retail-dev-e09bba6-nothink-seed42-20261122/README.md)

## 1. 本周摘要（跑了什么 / 结果如何 / 优先修什么）

- **跑了什么**：官方 tau2-bench retail（commit `0c69df4`）114 道英文任务。agent 为 `deep_retail`，代码 `dev@e09bba6` 加 TACC nothink 补丁；agent、user simulator、judge 都用 Qwen3.8-27B AWQ INT4（vLLM，temperature 0，nothink）。seed 42，1 trial，max_steps 100，timeout 600 s，并发 3。
- **结果**：**113/114 有效，未完成**。

  | 分桶 | 数量 |
  |---|---|
  | 通过 | 90 |
  | 普通 0 分 | 22 |
  | max_steps | 1（task 99） |
  | infra | 1（task 89） |

  - pass^1 区间 **[0.7895, 0.7982]**，**不是最终官方成绩**。
  - 113 个已评分任务的平均 reward 为 0.7965。
- **最常见的失败类型**：agent 多订单/多实体状态追踪和观察误读（7 个），user simulator 偏移（9 个）。
- **建议优先修**：
  1. 用户提到多个订单时逐一查询核对（R6）
  2. 写操作前按工具结果核算差价方向（R2）
  3. 整单取消前确认（R5）
  4. 退款完成后报出总额（R1）
  5. 重复调用保护（R4）
- **修复后变化**：代码已改完，并通过确定性测试（第 7 节）。还没有用真实模型复测；正在跑的 TACC 3-trial 作业仍然是修复前的官方配置。

## 2. 与旧 Notion 草稿相比的更正

| 旧草稿的说法 | 现在的结论（证据） |
|---|---|
| 续跑后 113 道的 checkpoint 被截断为 0 字节，只能复核 40 道 | 已安全重新下载完整的 114 行 results.json（先写临时文件，校验后替换），sha256 `39c0ae02…3585`；23 个失败全部逐条看过轨迹 |
| task 89 待补跑后更新 | 作业 29969 和 30449 两次都在 **NL judge 阶段** `evaluator_nl_assertions.py:123 json.loads` 报 `JSONDecodeError`，位置完全相同（char 312）。temperature 0 下可以确定性复现，单纯重跑无效，需要团队决定 judge 方案 |
| **task 35：用户拒绝加价后 agent 仍调用了 `modify_pending_order_items`** | **不成立。** agent 从未调用 modify（gold 的 modify 是 MISS，所以 DB 失败）。真正的根因：agent 在 [22] 错说"13 寸更便宜，你会收到差价退款"，用户 [27] 是按"会退款"答应的；直到 [28] 调用 `calculate` 才发现要多付 $113.71，用户在 [31]/[33] 拒绝并保留原单。**agent 尊重用户拒绝是正确的**，错在写操作前没有先核算差价方向，误导了用户。[26] 里还自相矛盾地说"没有 silver 的 i5"，紧接着又列出了 silver i5 |
| task 35 "NL 通过" | 该任务没有 NL assertion（reward_basis 里的 NL 部分为空），失败只因 DB 不匹配 |
| "DB 正确但 NL 错误：28、46、68" | 共 **4 个**：28、46、68、**105** |
| task 28 | 结论不变：三笔退货写入正确（$200.80 + $289.73 + $427.90 = $918.43），但从未报出总额 |
| 其余 21 个失败"无轨迹，不能推断根因" | 已逐条给出根因和证据，见第 3 节 |

## 3. Badcase 一览

| Task | 根因类别 | 一句话证据 | 改进方向 |
|---|---|---|---|
| 28 | 最终答复遗漏 | 退款写入正确，没报总额 $918.43 | 写操作后用清单核对答复（R1） |
| 35 | 价格核算 / 沟通 | 先错说"会退款"，算出 +$113.71 后用户拒绝；从未调用 modify | 写操作前先算差价（R2） |
| 41, 42 | 状态追踪 | 两个地址只改了一个 | 逐个订单核对（R6） |
| 52 | 观察误读 | 读错库存，gold 是 9228757377 | 按 `available` 字段如实列出选项 |
| 76 | 业务政策 | 编造"pending 订单可删单件"，并漏了取消 | 政策检查（R3） |
| 82 | 观察误读 | 认错了平板所在的订单 | 按 item 反查订单 |
| 93 | 状态追踪 | 没查 #W4073673 | R6 |
| 97 | 观察误读 / 状态追踪 | 把 NY 订单当成 LA 订单，漏改地址 | R6 |
| 98 | 政策 + 写操作授权 | 误取消整单后转人工 | 整单取消前确认（R5） |
| 99 | 步数 | 反复调用 `calculate` 到 100 步 | 重复调用保护（R4） |
| 104 | 状态追踪 | 漏了 #W6239298 的书架和拼图 | R6 |
| 95 | user-sim 偏移（由 agent 追问引发） | agent 多问颜色，user sim 选了非 gold 的 variant | 只在必要时追问 |
| 46, 59, 66, 68, 100, 109, 110, 112 | user-sim 偏移或错误 | user sim 漏问、弄反订单、改主意、给错地址等 | 记录为噪声，多 trial 验证 |
| 105 | **确认的 benchmark 问题** | gift card 余额 $17 不够补差价 $21.10，gold 动作本身会报错 | 计入 benchmark 问题清单 |
| 64 | 合理但未覆盖的替代方案 | 用户没指定颜色，agent 选 silver，gold 是 black | 同上 |
| 89 | 评测基础设施 | judge 返回非法 JSON，可确定性复现 | 需要团队决策 |

**其他发现**

- **36/37 异常转人工**：tau2 `modify_pending_order_items` 有 stale-variant bug，多 variant 修改时价格和 options 写错，agent 看到"数据损坏"后转了人工。没有发现 session 污染的证据。
- **34**：adapter 的 guard 文本泄露给了用户。

## 4. 验收标准（给开发同学）

| ID | 标准 | 来源 |
|---|---|---|
| R1 | 退款/退货/换货成功后，最终答复包含金额、支付方式和处理状态 | 28 |
| R2 | modify/exchange 前先根据工具结果算出差价并说明方向；用户拒绝后订单不应改变 | 35 |
| R3 | 拒绝从 pending 订单中删单件商品，不编造政策 | 76 |
| R4 | 同一工具以相同参数连续调用 ≥3 次时停止循环 | 99 |
| R5 | 整单取消前列出订单内全部商品，并取得明确确认 | 98 |
| R6 | 用户提到多个订单或地址时逐一查询核对 | 41/42/93/97/104 |
| R7 | adapter guard 文本不出现在用户可见的回复里 | 34 |
| R8 | 多 variant modify 后，在用户没有请求时不转人工 | 36/37 |

复测要求：使用相同的配置和任务，同时检查原本通过的 90 个任务有没有退化。

## 5. LangGraph 对照实验

- **现状**：没有结果。`backend` 分支没有官方 tau2 adapter（README 引用的 `tau2_agent.py` 不存在），`run_http.py` 是 DB-only 的自定义协议，分数不可比。
- **方案**：
  - 新写 `tau2_graph_agent.py`（HalfDuplexAgent → `run_graph(profile)`）。
  - 除 variant 以外，其他配置与本基线完全一致。
  - 跑 `lg_b1` 和 `lg_review`，各 3 trials；deep_retail 也补到 3 trials。
  - 报告总分、DB/NL 分项、回退任务和成本。
- **不得**把 Qwen 与 DeepSeek 之间的差异归因到框架。

## 6. 待团队决策

1. **task 89 的 judge 方案**：
   - 给 judge 开 JSON mode / `response_format`，统一重评 114 个任务（推荐）
   - 换更强的 judge
   - 只给 89 开 judge 重试（需要注明）
2. 是否另报"排除确认的 benchmark 问题后的诊断分"（非官方）。
3. 是否向 tau2 上游报告 105、64_6 和 stale-variant bug。
4. 人工审核 shadow reviewer 用哪个模型，以及从 shadow 切到 enforce 的阈值。

## 7. 修复进展（11-22，待真实模型复测）

团队决定：把 benchmark 改成本组自建的 **`retail_ours`**（非官方），不和官方排行榜比较。

| 问题 / 标准 | 处理 | 位置 |
|---|---|---|
| query 有歧义但真值只有一个 | 52/64/68/105/109/110 打补丁；上游文件不动 | `benchmarks/retail_ours/` |
| R8 / 36、37 异常转人工 | 修复 stale-variant bug；reviewer 在用户没要求时质询转人工 | `backend/retail_tools.py`、`backend/reviewer.py` |
| 怀疑上下文串扰 | 并发与交错测试没有发现串扰；根因是上一行的 bug | `tests/test_session_isolation.py` |
| R4 重复调用 | 同一轮内相同调用超过 2 次就升级 | reviewer `repeated_call` |
| R5 整单取消 | tau2 侧要求先列出全部商品；Web 侧审批卡片本身就列出了商品 | reviewer |
| R7 内部文本泄露 | 拦截后让模型重写，修正次数用尽时删掉泄露的行 | reviewer |
| 105 礼品卡余额不足 | 写之前拦截 | reviewer |
| 模型出错时人工兜底 | Web：生成 handoff 工单，停止自动处理，返回安全提示；高额或写后不一致的操作需要用户批准加人工复核（`STAFF_TOKEN`、`REVIEW_AMOUNT_THRESHOLD`） | `backend/agent.py`、`backend/retail.py`、`/api/staff/reviews` |

R1、R2、R3、R6 还没有对应的硬规则，仍然依赖 prompt。全套测试 86 passed，全部使用确定性模型。

复测命令：

```bash
python -m benchmarks.run_retail --domain retail_ours --all --num-trials 3 --agent deep_retail --reviewer enforce
```

对照组用 `--reviewer off`。

## 8. 限制

- 单 seed、单 trial；user sim 和 judge 与 agent 是同一个模型，因此 user-sim 类结论的稳定性待多 trial 验证。
- 单次跑分不足以作为微调的训练依据。下一步应先修 prompt、工具接口、状态管理和确认流程，并对照固定基线复测。
