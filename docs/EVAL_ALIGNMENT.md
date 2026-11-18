# 正式评测前的对齐事项

后端与 agent 的 HTTP 合约已实现，见 [EVAL_PROTOCOL.md](EVAL_PROTOCOL.md)。以下来自 huoshan 的真实开发 smoke，不改变已冻结的 v1 目标、范围、分母或历史分数。正式 27B 对比前，由 eval 负责人与 agent 负责人共同冻结处理方式。

## 1. 单一参考 DB 不一定唯一表达用户意图

具体证据是开发 task41：用户场景要求修改拼图与账户/全部订单地址，但 `user_scenario.instructions` 没有规定价差退款方式。政策 Modify items 允许用户提供支付/收退款方式。冻结参考动作选择 `paypal_4768213`；增强组的用户批准了信用卡方案，最终字段 `/orders/#W4082615/payment_history/1/payment_method_id` 为 `credit_card_9503061`，严格目标要求 PayPal，因此计失败。

同一 episode 还有一个订单地址尚未提交，**不能因此宣称整题实际正确**。这里只证明支付字段的期望存在欠明确之处。原始场景、卡片、回执、目标与字段差异都保存在：

```text
/vePFS/han/retail-desk/runs/final-focus-20261118T025435Z-a317337-610915/targets-smoke8/task-41.json
/vePFS/han/retail-desk/runs/live-smoke8-enhanced-v2-20261118T042543Z/evaluation/*/task-41/seed-0/attempt-0/
```

当前 v1 继续使用单一完整客户/初始订单目标，支付字段不移出范围，不根据候选改动扩缩范围，失败分数保留。正式版本应在跑候选前选择并冻结一种口径：

- 保持单一目标：把确实需要唯一化的用户偏好明确写入改编后的用户场景，标注数据改编及来源；所有 agent 共用同一场景，用户模拟器按该偏好审批。
- 允许等价最终状态：离线定义允许的最终状态集合或业务约束，再比较；这将改变“必须等于单一 target DB”的定义，必须作为新协议完整重跑，不能事后为某个失败放宽。

此处没有实施上述任一变更。

## 2. 用户模拟器也必须通过协议验收

9B smoke 已出现 `simulator_or_protocol_error`。现有解析器严格检查 action/字段/可见卡片 ID；非法动作会终止并尝试导出冻结 DB，照原分母计分，不当基础设施重试。初轮请求使用 `response_format=json_object`，只能约束 JSON 外形。后续 `visible-action-schema-v2` 已实现动态 JSON Schema，按当前卡片限定动作与 action ID；真实 9B 三项检查已通过（完整发消息、批准正确卡片、拒绝错误卡片）；完整业务批次另行重跑，不能由结构有效推断所有审批判断正确。

正式评测前需验证：

- 有卡片时仅允许 approve/reject/finish，决策 ID 必须是当前卡片；需修正需求时先拒绝，再在下一轮发消息。
- 用户有明确支付、商品、地址偏好时，错误卡片应被拒绝；不能因为页面提出了方案就自动批准。
- 可用动态 JSON Schema/语法约束 action 形状与卡片 ID，但 approve/reject 仍由用户模型判断，不能改成自动批准。
- 无效响应也应保存原始响应、usage 和错误原因。旧版无效 step 的 usage 计为缺失；v2 已保留收到的无效响应与已知 usage，缺失用量仍保持未知。

这些约束或模拟器模型发生变化后，冻结新版本，重新运行双方完整题目，不只补跑失败题。当前参考协议要求 agent 与 simulator 用同一模型；若改成固定的更强用户模型，也须更新并冻结协议，双方使用完全相同设置。

## 3. 最终报告的边界

主分仍是 DB 成功率；同时报告模拟器/协议错误、转人工、预算、agent 错误、缺快照与缺 usage。错误截止但有有效快照时仍按 v1 DB 口径计分。8 题单 seed 是功能 smoke，不能替代开发54/验证20消融、test40×3、pass^3 或正式提升结论。成功/等待确认等文本声明目前人工核查，不输出未经实现的自动事实性评分。

## schema v2 完整重测新增证据

`schema-v2-paired-smoke-20261118T065355Z/` 两组共16题没有格式/协议错误，usage完整，B1与enhanced均6/8。增强task16唯一差异为退款至已有礼品卡而非target中的PayPal；公开用户场景也未指定该选择。task41的模拟器则在pending卡片仍存在时声称所有地址已完成并finish，DB证实两个订单地址仍旧。这是用户完成判断错误，不是JSON格式错误；后续应明确预览不代表执行、finish可表示主动放弃但不能把预览当成功证据，并用独立合成场景验证，不把target传给模拟器。

已向项目负责人提出单一target加明确用户偏好、预先定义等价状态、保留原始歧义三种口径供选择。在选择确定前保持现行严格比较及全部历史结果，不从候选输出来修改目标。

## 新候选 task0 的商品选择差异

`c1-c2-v5-smoke-20261118T122924Z/c2/*/task-0/seed-0/attempt-0/`中，用户模型明确选择键盘 `6342039236`（white/full size/clicky），agent按该选择完成换货及真实审批回执。target固定键盘 `7706410293`（none/full size/clicky）。最终仅两项差异：`exchange_new_items/0` 与由价格决定的 `exchange_price_difference`（实际-40.88，目标-16.63）。严格计失败，不能将真实执行正常视作DB通过。此案例应与支付选择一样交由eval负责人核对偏好是否充分明确；本轮没有改变用户场景、目标或比较器。
