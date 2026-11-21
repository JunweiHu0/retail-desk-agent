# 评测有效性记录：path-dependent target（2026-11-21）

状态：**待讨论**。这是给团队讨论的材料，不是最终结论。

## 术语：scenario、reference actions、target

三者不是同一份 formal spec：

- **`user_scenario`**：给 LLM 模拟用户看的自然语言说明（目标、条件、偏好）。它驱动对话，但不直接参与判分。
- **`reference_trace` / reference actions**：官方参考动作序列，例如 `modify_pending_order_address(...)`、`modify_pending_order_items(...)`。
- **`target_db`**：把 reference actions 在初始 DB 上重放出来的固定数据库；comparator 只拿它和实际最终 DB 比。
- **simulator**：把 scenario 转成可见用户消息/决定的 LLM；它可以对模糊措辞做自己的解释，选择不同分支。

因此 scenario 和 target **可以不同尺度**：scenario 是行为描述，target 是某一条具体参考轨迹的结果。task 71 就是 scenario 说“只改 backpack”，而 reference target 仍包含 address change；simulator 又额外说了“不要改 address”，agent 按可见用户执行，target 却要求 address 已改。

## 问题

评测把 `success` 定义为“最终 DB 必须精确等于单一路径的 target DB”。对带条件分支的 user scenario，这会**把合法的另一条交互路径判成失败**。

## 已确认的例子：task 5

官方 `user_scenario` 的关键条件：

> You want to exchange the water bottle and the desk lamp. ... If the agent asks for confirmation, only exchange the desk lamp. If the agent asks for confirmation again, do not exchange anything, and return the water bottle instead.

参考 target 走的是第二条分支：

```
return_items = ['8538875209']            # water bottle
return_payment_method_id = paypal_7644869
status = return requested
```

本次 episode 实际走的是第一条分支：

```
exchange_items = ['8384507844']
exchange_new_items = ['7453605304']
exchange_payment_method_id = paypal_7644869
exchange_price_difference = 12.07
status = exchange requested
```

`score.json` 共 **7 处 mismatch**，`success=false`，`termination=simulator_finish`。

## 为什么说 agent 没有明显做错

可见对话中用户明确说：

> Please only exchange the desk lamp for the battery-powered low-brightness one. I don't want to exchange the water bottle.

agent 只换了台灯，随后用户确认，application receipt 完成。这与可见用户请求一致。

问题在于：

- 这次 episode 只发生了一次确认，“再次确认 → 退水瓶”分支没有触发；
- 参考 target 固定在另一条分支；
- agent 看不到 scenario 里的隐藏条件，也没有理由主动再问一次；
- 所以最终 DB 是 exchange，target 是 return。

这是 **path-dependent target / false negative**，不是运行时错误，也不应简单归为 agent 能力失败。

## 当前 strict 指标

| 指标      | 值            |
| --------- | ------------- |
| seed 0    | 31/40, 0.775  |
| seed 1    | 30/40, 0.750  |
| seed 2    | 30/40, 0.750  |
| all seeds | 91/120, 0.758 |
| pass_3    | 25/40, 0.625  |

以上全部是 **single-target exact DB match**。已有至少一个确认的 path-divergence 例子（task 5），因此这些数字不能直接当作纯 agent-quality 分数。

把 14 个 `wall_time_budget` episode 用 1800 秒重跑后（其它设置不变），诊断性的 mixed-budget 指标为：seed 0 34/40、seed 1 33/40、seed 2 34/40、all 101/120 (0.842)、pass_3 31/40 (0.775)。详见下面的“wall-time 重跑”一节和 `reruns/summary.json`。

`simulator_finish` 只是终止方式，不是错误；红色来自 DB mismatch。报告页已把列名改为 “termination (failed rows)” 并加了说明。

## 对照：task 18 是真实失败，不是 path divergence

task 18 的 scenario 也有条件分支，但失败原因不同：

> 想退 office chair（有破损）。如果 agent 要求确认，先说“再想想”，然后改口要换同款。**如果 agent 说明同款/同商品不可换，就改要 gray office chair with fixed armrest made of leather。**

- seed 1：agent 正确说明“exchange 必须是同商品的不同选项，不能是完全相同的 item”，用户随后选择 gray leather；成功。
- seed 0：agent 没有说明这个限制，直接按“换同款”做了一个 exchange。实际 DB 的 `exchange_new_items[0] = 8069050545`、`exchange_price_difference = 0.0`；target 是 `1071497737`、`-15.33`；2 处 mismatch，`success=false`。
- 这不是“合法路径被判错”：同款 exchange 本身不合法，agent 应该指出限制并让用户选择另一个 variant。seed 0/2 是 **真实 agent 行为/政策失败**；seed 1 展示了正确行为。

### task 32：过早转人工（真实 agent 行为问题）

scenario 是两段：先问丢失 tablet 的 tracking、能否退款/重买（明确说是 long shot）；如果不行，再取消 charger/boot/kettle 并退 sneaker。reference actions 只包含后面的取消/退货，不包含丢失 tablet 的退款。

三个 seed 都在第一段就 `agent_transferred`，session 直接 `status=finished`，后续取消/退货没有发生，最终 DB 与 target 有 17 处 mismatch。seed 1 的可见对话里，agent 先提出“退货退款”，用户说“东西丢了没法寄回”，agent 随即转人工，没有说“这个做不到，还有其他需要吗”。seed 2 是用户明确说 “Please transfer me to a human agent”，转人工本身合规；seed 0/1 是 agent 主动/过早转人工。

policy 允许在“请求超出工具范围”时转人工，但同一 policy 也要求处理同一用户的多个请求；转人工会让 session 结束，所以应该作为最后手段：先说明丢失商品无法无退货退款，再询问/继续其它请求，用户坚持或整个会话都无法处理时才转。UI 里的“已记录人工转接请求，咨询和订单记录已保留。”不是另一条工具消息，而是前端对 `YOU ARE BEING TRANSFERRED...` 的替换文案（`frontend/src/retail.ts:133-140`）。

### task 101 seed 0：simulator 4096-token 耗尽（协议错误）

可见对话里 agent 已完成地址修改（`#W4219264` → 144 Lakeview Drive, New York），但 task 101 还要求把硅胶表带换成 metal/white dial，并把空气净化器改成 large/night mode/HEPA。下一轮模拟用户（persona：logical but impatient，说话分片）在 reasoning 里纠结订单内容，写满了 4096 completion tokens，返回 `finish_reason=length`、`content=null`；evaluator 的 `json.loads(None)` 抛错，termination 记为 `simulator_or_protocol_error`。此时最终 DB 只完成了地址修改，还有 12 处 mismatch（表带/dial/价格/payment_history、净化器 features 等）。这是 **simulator 预算/格式失败**，不是 agent 行为错误；task 100 seed 1 也是同一失败模式。

因此当前失败至少分三类，讨论时不要混在一起：

1. `wall_time_budget` / `agent_error` / protocol error：预算或运行时问题；
2. task 5 这类：合法 alternative path，被 single-target 判错；
3. task 18 这类：agent 没有执行正确的政策约束 / 选错 variant。

## 补充：task 38 seed 1 是 cancellation-reason 歧义

- 唯一 mismatch：`/orders/#W9348897/cancel_reason`，target = `no longer needed`，actual = `ordered by mistake`。
- `user_scenario` 里**既没有** `no longer needed`，也**没有** `ordered by mistake`；scenario 只说“cancel the order so that you can order again”。
- target 的 reason 来自 reference action：`cancel_pending_order(order_id="#W9348897", reason="no longer needed")`；target DB 因此固定成 `no longer needed`。
- 可见对话里模拟用户说“Ordered by mistake. Please cancel it.”；tau2 的 `cancel_pending_order` 两种 reason 都合法，agent 按用户说的执行。
- 订单已正确取消、退款和状态都匹配；只有 reason 文本不同。
- seed 0 / seed 2 成功，说明同一任务在另一条对话里选了与 target 一致的 reason。
- 这是 **target/simulator 的 reason-enum 歧义**，不是 agent 行为错误；除非 comparator 把两种合法 reason 视为等价，否则 strict 指标会误判。

## 补充：task 64 seed 2 是 variant-choice 歧义

- scenario 只要求“highest resolution, waterproof camera at the previous price”，**没有指定颜色**。
- reference action 选了 black 4K（item `6700049080`，$466.75，refund `35.53`）。
- 可见对话里模拟用户明确说“4K waterproof **silver** camera”；agent 按用户要求改成 silver 4K（item `6117189161`，$481.50，refund `20.78`）。
- 4 个 mismatch 全部来自这个 variant 选择：`items/0/item_id`、`options/color`、`price`、`payment_history/1/amount`。
- silver 和 black 都是 4K waterproof，且都低于原价；这是 **variant-choice 的 target/simulator 歧义**，不是 agent 错误。seed 0/1 成功（模拟用户选择了与 target 一致的 variant）。

## 补充：task 71 seed 1 是地址变更的 scenario/simulator 歧义

- scenario：把订单地址改到 Charlotte 默认地址，desk lamp 改黑色，backpack 改 medium/polyester；如果 agent 要求确认，改成 PayPal，并且“only modify the backpack”。
- reference actions：`modify_pending_order_address`（Charlotte）+ `modify_pending_order_items`（backpack，PayPal）；**没有** lamp 修改。
- seed 1 可见对话里，模拟用户说：“only modify the backpack ... **Please don't change the shipping address or the desk lamp**.” agent 按可见用户执行，地址保持 Washington DC。
- target 期望地址已改到 Charlotte；actual 仍是原地址；5 个 mismatch 全是 address 字段。
- seed 0/2 成功；seed 1 的模拟用户额外加了“不要改地址”，与 reference action 冲突。这是 **scenario/simulator 对“only modify the backpack”的解释歧义**，agent 按可见用户做，不是 agent 错误。
- 另有一个独立的 UX/状态问题：application receipt 已经说“已按你的确认完成办理”，但最后一条 assistant 仍在说“Please review the action card and click Confirm”。这不是 DB 判分原因，但消息状态和实际执行不一致，值得单独修。

## `wall_time_budget` 是什么

- `run_attempt` 给每个 episode 的 `max_seconds` 默认是 **600 秒**；app 侧 `AGENT_MAX_ACTIVE_SECONDS` 默认也是 600 秒（按 turn 计）。
- 达到上限时，evaluator 停止对话、调用 `finish` 并取 snapshot，然后仍然按当时的 DB 判分；`termination` 记为 `wall_time_budget`。
- 所以它 **不是 DB mismatch 本身，也不是 agent 的政策错误**，而是“时间用完了，业务没走完”。通常最终 DB 还没到 target，于是 `success=false`；少数情况下截止时 DB 已经匹配（例如 task 27 seed 0 出现过 `wall_time_budget` + success=true）。
- 在 10 并发正式配置下，各 seed 有 4~7 个 wall-time；20 并发时 seed 0 有 12 个，说明并发升高会放大单轮延迟。
- 这是 **operational budget / timeout**，和 task 5/38/64/71 的语义歧义、task 18 的 agent 错误应分开统计。

可选的缓解方式：

1. `--thinking off`：最直接，降低单轮生成 tokens 和延迟；
2. 降低并发（10 → 8/6）以减少单请求延迟；
3. 提高 per-episode 预算（evaluator `max_seconds` + app `AGENT_MAX_ACTIVE_SECONDS`），同时注意 TACC 1 小时作业限制和分批；
4. 更快的 serving 配置/模型。

## wall-time 重跑（1800s，诊断）

对 14 个 `wall_time_budget` episode 保持其它设置不变（Qwen3.8-27B、thinking auto、concurrency 10、variant `lg_b1`），只把 `max_seconds` 从 600 提到 1800：

- seed 0：36, 42, 79, 97, 100
- seed 1：27, 49, 97, 100
- seed 2：27, 79, 97, 100, 111

结果：**10/14 变成 DB match**。

| 配置   | 原 600s        | 重跑调整后      |
| ------ | -------------- | --------------- |
| seed 0 | 31/40 (0.775)  | 34/40 (0.850)   |
| seed 1 | 30/40 (0.750)  | 33/40 (0.825)   |
| seed 2 | 30/40 (0.750)  | 34/40 (0.850)   |
| all    | 91/120 (0.758) | 101/120 (0.842) |
| pass_3 | 25/40 (0.625)  | 31/40 (0.775)   |

新增 pass_3：27、42、49、79、97、111。重跑使用更大预算，因此这是 **诊断性 mixed-budget 指标**，不和 600s 正式配置直接混为一个结论。

仍然失败的 4 个都不是超时：

- **task 36 seed 0**：多 item 修改的 action card preview 被 tau2 的 variant 泄漏 bug 污染（见下），模拟用户连续拒绝，最后落到“取消整单”分支。
- **task 100 seed 0/2**：同一个 bug：Luggage Set 的 `after` preview 被写成 skateboard 的 options/价格，模拟用户拒绝，agent 重新 stage，最后 `agent_transferred`。不是 agent 单纯循环。
- **task 100 seed 1**：simulator 在 reasoning 中用满 4096 completion tokens（`finish_reason=length`、`content=null`），解析失败，`simulator_or_protocol_error`。属于 simulator 预算问题。

## 根因：tau2 `modify_pending_order_items` 的 variant 泄漏

pinned tau2 的 `src/tau2/domains/retail/tools.py` 里，校验循环（约 541-550 行）计算了每个新 item 的 `variant`，但真正应用修改的循环（约 578-583 行）没有重新取：

```python
for item_id, new_item_id in zip(item_ids, new_item_ids):
    ...
    item.item_id = new_item_id
    item.price = variant.price        # 上一个循环遗留的最后一个 variant
    item.options = variant.options
```

因此多 item 修改时，所有新 item 都会继承**最后一个 new item** 的 options 和 price。test split 中受影响的是 task 36（最后一个是 T-Shirt，$46.66）和 task 100（最后一个是 skateboard，$217.06）；其它 split 还有 20/21/37。单 item 修改不受影响。

关键点是 target DB 同样由 replay 这段 buggy reference action 生成，所以 target 里也带着错误的 options/price。模拟用户看到 preview 与 agent 描述不符就拒绝；agent 无法通过重试改变工具输出，最后只能走“取消整单”分支，于是 strict target 判失败。这不是 agent 能力问题，也不是简单的 scenario 歧义，而是 **上游 tau2 工具实现 bug + 单一路径 target** 共同造成的。

## 待团队讨论的选项

1. **Branch-aware targets**：对条件 scenario 生成多个合法 target DB，最终 DB 匹配任意一个分支即成功。task 5 的合法分支至少包括“只换台灯”和“退水瓶”。
2. **失败分类**：逐个失败 episode 对照官方 scenario + `mismatches.json`，分类为 agent error / simulator-path / budget error；报告 strict 与 adjusted 两个指标。
3. **官方 tau2 evaluator**：使用 tau2 的 evaluation criteria / user simulator，而不是单一路径 DB target。
4. **保留 strict 指标但披露**：在报告/README 明确 target 是路径相关的，并列出已知的 path-dependent task；不把它当作唯一质量结论。

## 需要确认

- 报告和 artifact 最终用哪个指标（strict / adjusted / 两个都给）？
- 是否要改 evaluator 支持 branch-aware targets？工作量：fixture 需要记录目标动作的分支条件，comparator 接受多个 target。
- 其他 `simulator_finish` 失败是否也是类似路径问题？目前只逐字段确认了 task 5；可以用同样方法检查 task 18/36/38/64/71 等。
- 是否要用官方 tau2 evaluator 做对照？这会改变当前 HTTP evaluator 的协议。

## 相关材料

- 总览/矩阵：`docs/experiments/2026-11-21-formal-test40/index.html`
- 本次 task 5 replay：总览表 task 5 seed 0 格子
- TACC 原始结果：`$TACC_USERDIR/retail-agent/tau2-results/formal-test40-20261120/runs/`
- 早期 backend README 诊断说明：`backend/README.md` 的 “最终 DB 评测” 一节
