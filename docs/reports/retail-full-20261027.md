# 完整 Retail 评测与优化回归

日期：2026-10-27。

## 范围与配置

- 官方 runner 默认英文 Retail base 全集：114 条、ID 0–113，每条 1 次。
- 仓库另有 50 条发布筛选集；本轮使用完整 114 条注册任务，不混淆为 50 条成绩。
- Agent：Deep Agents + deepseek-flash；用户模拟器和 NL 评分器同为 DeepSeek Flash。
- 前后两轮均 seed=42、并发 3、最多 100 步、每任务 600 秒、不按失败分数重试。
- 未修改官方业务工具、任务、预期答案和 reward。网页沙盒与评测数据隔离。
- 两个中间候选分别在 35 条和 76 条停止：前者补同规格政策防护，后者修正混合计划整单拒绝过严。检查点分别保存在 retail-full-after-20261027、retail-full-optimized-20261027。最终版从头跑完 114 条，不拼接中间成绩。
- 不是官方 frozen leaderboard 提交；这是根据完整集失败分析后的同集回归，不是独立未见集成绩。

## 前后对比

| 指标 | 基线 | 优化后 |
| --- | ---: | ---: |
| 完成任务 | 114/114 | 114/114 |
| 通过任务 | 96/114 | 98/114 |
| 成功率 | 84.2% | 86.0% |
| 最终数据库状态匹配 | 101/114 | 101/114 |
| 平均对话执行耗时（不含后置评分） | 26.2s | 23.0s |

净增加 2 条通过；提升 1.75 个百分点。修复与回退同时存在，属于小幅净改善，不能视为稳定的大幅提升。保持 dev 实验分支，不合入 main。

修复任务：3, 4, 22, 27, 52, 63, 64, 68, 72, 93, 99, 101, 104。

回退任务：0, 39, 43, 44, 49, 66, 74, 76, 98, 100, 110。

两轮都未通过：38, 41, 59, 67, 105。

## 优化内容

1. 仅从实际工具返回计算可用/缺货/总规格数、可用最低价和订单商品金额，未使用任务答案或固定数字。
2. 明确同一已送达订单的退货与换货存在状态冲突，先确定优先级再执行。
3. 保留多订单请求的完整范围；回滚仅限用户明确要求的对象，不主动扩展变更。
4. 地址/支付变更在一次性商品修改前完成；收集支付方式与最终确认分开，变更细节后重新确认。
5. 先按库存、规格和预算过滤可行商品，再比较最佳选项；保留客户未要求改变的规格。
6. 优先使用真实原支付方式的清晰描述，尊重用户明确选择，不为匹配预设答案改写用户选择。

## 全部任务

| Task | 基线 | 优化后 | 优化后失败类别 |
| --- | ---: | ---: | --- |
| 0 | 1 | 0 | database_mismatch |
| 1 | 1 | 1 | — |
| 2 | 1 | 1 | — |
| 3 | 0 | 1 | — |
| 4 | 0 | 1 | — |
| 5 | 1 | 1 | — |
| 6 | 1 | 1 | — |
| 7 | 1 | 1 | — |
| 8 | 1 | 1 | — |
| 9 | 1 | 1 | — |
| 10 | 1 | 1 | — |
| 11 | 1 | 1 | — |
| 12 | 1 | 1 | — |
| 13 | 1 | 1 | — |
| 14 | 1 | 1 | — |
| 15 | 1 | 1 | — |
| 16 | 1 | 1 | — |
| 17 | 1 | 1 | — |
| 18 | 1 | 1 | — |
| 19 | 1 | 1 | — |
| 20 | 1 | 1 | — |
| 21 | 1 | 1 | — |
| 22 | 0 | 1 | — |
| 23 | 1 | 1 | — |
| 24 | 1 | 1 | — |
| 25 | 1 | 1 | — |
| 26 | 1 | 1 | — |
| 27 | 0 | 1 | — |
| 28 | 1 | 1 | — |
| 29 | 1 | 1 | — |
| 30 | 1 | 1 | — |
| 31 | 1 | 1 | — |
| 32 | 1 | 1 | — |
| 33 | 1 | 1 | — |
| 34 | 1 | 1 | — |
| 35 | 1 | 1 | — |
| 36 | 1 | 1 | — |
| 37 | 1 | 1 | — |
| 38 | 0 | 0 | database_mismatch |
| 39 | 1 | 0 | database_mismatch, answer_assertion |
| 40 | 1 | 1 | — |
| 41 | 0 | 0 | database_mismatch |
| 42 | 1 | 1 | — |
| 43 | 1 | 0 | database_mismatch |
| 44 | 1 | 0 | answer_assertion |
| 45 | 1 | 1 | — |
| 46 | 1 | 1 | — |
| 47 | 1 | 1 | — |
| 48 | 1 | 1 | — |
| 49 | 1 | 0 | database_mismatch |
| 50 | 1 | 1 | — |
| 51 | 1 | 1 | — |
| 52 | 0 | 1 | — |
| 53 | 1 | 1 | — |
| 54 | 1 | 1 | — |
| 55 | 1 | 1 | — |
| 56 | 1 | 1 | — |
| 57 | 1 | 1 | — |
| 58 | 1 | 1 | — |
| 59 | 0 | 0 | database_mismatch, answer_assertion |
| 60 | 1 | 1 | — |
| 61 | 1 | 1 | — |
| 62 | 1 | 1 | — |
| 63 | 0 | 1 | — |
| 64 | 0 | 1 | — |
| 65 | 1 | 1 | — |
| 66 | 1 | 0 | database_mismatch |
| 67 | 0 | 0 | answer_assertion |
| 68 | 0 | 1 | — |
| 69 | 1 | 1 | — |
| 70 | 1 | 1 | — |
| 71 | 1 | 1 | — |
| 72 | 0 | 1 | — |
| 73 | 1 | 1 | — |
| 74 | 1 | 0 | database_mismatch |
| 75 | 1 | 1 | — |
| 76 | 1 | 0 | database_mismatch |
| 77 | 1 | 1 | — |
| 78 | 1 | 1 | — |
| 79 | 1 | 1 | — |
| 80 | 1 | 1 | — |
| 81 | 1 | 1 | — |
| 82 | 1 | 1 | — |
| 83 | 1 | 1 | — |
| 84 | 1 | 1 | — |
| 85 | 1 | 1 | — |
| 86 | 1 | 1 | — |
| 87 | 1 | 1 | — |
| 88 | 1 | 1 | — |
| 89 | 1 | 1 | — |
| 90 | 1 | 1 | — |
| 91 | 1 | 1 | — |
| 92 | 1 | 1 | — |
| 93 | 0 | 1 | — |
| 94 | 1 | 1 | — |
| 95 | 1 | 1 | — |
| 96 | 1 | 1 | — |
| 97 | 1 | 1 | — |
| 98 | 1 | 0 | database_mismatch |
| 99 | 0 | 1 | — |
| 100 | 1 | 0 | database_mismatch |
| 101 | 0 | 1 | — |
| 102 | 1 | 1 | — |
| 103 | 1 | 1 | — |
| 104 | 0 | 1 | — |
| 105 | 0 | 0 | answer_assertion |
| 106 | 1 | 1 | — |
| 107 | 1 | 1 | — |
| 108 | 1 | 1 | — |
| 109 | 1 | 1 | — |
| 110 | 1 | 0 | database_mismatch, answer_assertion |
| 111 | 1 | 1 | — |
| 112 | 1 | 1 | — |
| 113 | 1 | 1 | — |

## 剩余失败的原始评分理由

### Task 0

You received your order #W2378156 and wish to exchange the mechanical keyboard for the same one but with clicky switches and the smart thermostat for one compatible with Google Home instead of Apple HomeKit. If there is no keyboard that is clicky, RGB backlight, full size, you'd go for no backlight.

终止：user_stop；DB 匹配：False。

- 未命中预期写操作：`exchange_delivered_order_items`，参数 `{"order_id": "#W2378156", "item_ids": ["1151293680", "4983901480"], "new_item_ids": ["7706410293", "7747408585"], "payment_method_id": "credit_card_9513926"}`。

### Task 38

You just placed an order but you realize that your card has only $950 credit left, but the order total is more than $1100. You wonder if the agent can help split the payment with another card. If not, you wonder what the most expensive item and its price, and if you can just cancel that item. If not, you wonder if you can switch all items to their cheapest options and bring the cost down to $950. If not, you wonder if the agent can just cancel the order so that you can order again.

终止：user_stop；DB 匹配：False。

- 工具错误：Error: User not found
- 未命中预期写操作：`cancel_pending_order`，参数 `{"order_id": "#W9348897", "reason": "no longer needed"}`。

### Task 39

You just moved from Florida to Phoenix. Unfortunately your address is still the old one, and you want to update it. Your current address should be in your recent order (you can mention this to the agent), and you do not want to reveal it. Also, you want to know what is the price of the cheapest available t-shirt right now, and if you can order it through the agent.

终止：user_stop；DB 匹配：False。

- Agent should tell the user the cheapest t-shirt costs $46.66.
  - The conversation is about updating a customer's address, not about t-shirt prices. The agent never mentions any t-shirt or price, so the expected outcome is not met.
- 工具错误：Error: User not found
- 未命中预期写操作：`modify_user_address`，参数 `{"user_id": "fatima_taylor_3452", "address1": "157 Oak Street", "address2": "Suite 258", "city": "Phoenix", "state": "AZ", "country": "USA", "zip": "85033"}`。

### Task 41

You just created your user id mei_patel_7272 and ordered some things, but you have two problems: first, the 1000-piece intermediate jigsaw might be too hard for your little kid, you wonder if you can change it to the easiest one with fewest pieces; second, you might have typed your address wrong. You want to check it, and potentially correct all order addresses and your user address. Make sure you mention these two problems at the same time in the same order.

终止：user_stop；DB 匹配：False。

- 未命中预期写操作：`modify_pending_order_address`，参数 `{"order_id": "#W9583042", "address1": "445 Maple Drive", "address2": "Suite 394", "city": "Fort Worth", "state": "TX", "country": "USA", "zip": "76165"}`。

### Task 43

You ordered some things for your daughter but she has not received them, so you want to know which address the order was sent to, the tracking number, and if the order is still in transit. You also want to check if the storage of the tablet you ordered. Lastly, you want to change your default address to your daughter's address so that you don't have to change it every time you order something for her.

终止：user_stop；DB 匹配：False。


### Task 44

You want to change the Desk Lamp in order #W9300146 that you've placed for the cheapest Desk Lamp that's available. Any price difference should go to a gift card. You also want to know how much you get back in total.

终止：user_stop；DB 匹配：True。

- Agent should tell the user they will get back $17.99.
  - The agent told the user they would get back $18.00, not $17.99. Although the actual refund processed was $17.99, the agent did not communicate that exact amount to the user.

### Task 49

You mistakenly ordered a Wireless Earbud with an IPX7 water resistance level, but you don't require this feature. You wish to exchange it for one with the same water resistance level as the other Wireless Earbuds that you've purchased. In fact, you want to exchange it to the cheapest earbud item from the rest of that order.

终止：user_stop；DB 匹配：False。

- 未命中预期写操作：`exchange_delivered_order_items`，参数 `{"order_id": "#W3470184", "item_ids": ["2757705742"], "new_item_ids": ["1646531091"], "payment_method_id": "gift_card_7245904"}`。

### Task 59

You recently placed two orders, and now you would like to make several changes and checks. You'll first inquire about the status difference between your two orders, #W2702727 and #W8268610, since both are "pending," but one was placed much earlier in the year. You are considering cancelling the older order as you find the wait time unreasonable. If the agent cannot guarantee the older order will be processed within 5 days, you want to cancel it. You also want to confirm the total price of the refund. 

    For order #W2702727, you intend to switch the shipping address to your new home in a different city because you plan to move prior to its delivery next month. Your new address is 1234 Elm St, Springfield, IL, 62701. You want the agent to confirm the change and ensure the order will be delivered to the new address. You also want to confirm the total price of the order after the address change.

终止：user_stop；DB 匹配：False。

- Agent should tell the user the refund for the cancelled desk lamp order is $164.28.
  - The desk lamp order (#W8268610) was not cancelled; only the shipping address was updated. The agent never mentioned a refund for this order, so the expectation is not met.
- 未命中预期写操作：`cancel_pending_order`，参数 `{"order_id": "#W8268610", "reason": "no longer needed"}`。
- 未命中预期写操作：`modify_pending_order_address`，参数 `{"order_id": "#W2702727", "address1": "1234 Elm St", "address2": "", "city": "Springfield", "state": "IL", "country": "USA", "zip": "62701"}`。

### Task 66

You want to change the luggage set in your order for a coat.  Your goal is to change the order. If there is no way to do that, return the item specifically. If there are any issues, cancel the entire order.

终止：user_stop；DB 匹配：False。

- 未命中预期写操作：`cancel_pending_order`，参数 `{"order_id": "#W3361211", "reason": "no longer needed"}`。

### Task 67

You want to check how much you paid for the order that you most recently placed. You are not sure how long ago the order was placed.

终止：user_stop；DB 匹配：True。

- Agent should tell the user the order total is $829.43.
  - The agent told the user the total for order #W4219264 was $3,916.77, not $829.43. The $829.43 total corresponds to order #W6729841, which the agent did not state as the answer.
- 工具错误：Error: User not found
- 工具错误：Error: User not found

### Task 74

You recently bought a laptop, but you want to exchange it to i9 CPU. If multiple storage options are available, you prefer 256GB SSD. If multiple colors are available, you prefer silver. You also have a pending order with five items (you don't remember order ID), and you want to cancel it because you no longer need them.

终止：user_stop；DB 匹配：False。

- 未命中预期写操作：`modify_pending_order_items`，参数 `{"order_id": "#W5166363", "item_ids": ["3334537816"], "new_item_ids": ["3265035808"], "payment_method_id": "credit_card_4466831"}`。

### Task 76

You ordered a fleece jacket by mistake and want to remove it from your pending order. If removing one item is not possible, cancel the whole order since you ordered it by mistake. You also want to modify the skateboard to maple material, 34 inch, graphic. If that is not possible, cancel the order since you no longer need this one. 
Finally, you also want to know the total price for all the grills you have bought in previous orders.

终止：user_stop；DB 匹配：False。

- 未命中预期写操作：`cancel_pending_order`，参数 `{"order_id": "#W1242543", "reason": "no longer needed"}`。

### Task 98

You want to exchange your Bicycle for one with a larger frame size for your kid (you are okay with having a mountain bike instead of a road bike). Jigsaw Puzzle in the same order also needs to be exchanged, you want the same difficulty, but 1000 more pieces, and you prefer animal than art theme if both are available. Make sure you mention these at the same time.  You also want to exchange your camera to a slightly lower resolution, without changing the other options. If the agent asks for confirmation, mention that you'd prefer the other card as payment or refund method. Lastly, you want to cancel the skateboard in your other order.

终止：user_stop；DB 匹配：False。

- 未命中预期写操作：`exchange_delivered_order_items`，参数 `{"order_id": "#W4689314", "item_ids": ["5996159312"], "new_item_ids": ["8363011723"], "payment_method_id": "credit_card_8105988"}`。
- 未命中预期写操作：`exchange_delivered_order_items`，参数 `{"order_id": "#W3916020", "item_ids": ["7758198585", "4068787148"], "new_item_ids": ["5606522780", "6245746168"], "payment_method_id": "credit_card_8105988"}`。

### Task 100

You want to return your luggage set and get the exact same item but with red color, and return you skateboard in the same order to get a new one with features {'length': '34 inch', 'design': 'custom'}. For the pending order modification, you want to use your credit card. You also want to return the hiking boots.

终止：user_stop；DB 匹配：False。

- 未命中预期写操作：`modify_pending_order_items`，参数 `{"order_id": "#W3295833", "item_ids": ["8926329222", "5312063289"], "new_item_ids": ["7160999700", "6956751343"], "payment_method_id": "credit_card_3261838"}`。

### Task 105

For order #W4316152, you want to  exchange one Tea Kettle {'material': 'glass', 'capacity': '2 liters', 'stovetop compatibility': 'induction'} to {'material': 'ceramic', 'stovetop compatibility': 'gas'}; and another Tea Kettle {'material': 'glass', 'capacity': '2 liters', 'stovetop compatibility': 'induction'} to {'capacity': '1.5 liters', 'stovetop compatibility': 'gas'};

终止：user_stop；DB 匹配：True。

- Agent should exchange both tea kettles (same style) to the items requested
  - The agent did not complete the exchange because the customer could not provide a valid payment method for the $20.10 price difference. The exchange was planned but not executed, so the expected outcome was not met.
- 未命中预期写操作：`exchange_delivered_order_items`，参数 `{"order_id": "#W4316152", "item_ids": ["7292993796", "7292993796"], "new_item_ids": ["3761330360", "9647374798"], "payment_method_id": "gift_card_7245904"}`。

### Task 110

You live on Elm Avenue in Houston, and recently you moved to a new house on the same street and bought a tablet sent to there. But you realize you have another order sent to the old address, and you want to change your wrong order address to the new home, and also your user default address to the new home. You do not want to reveal your address and insist the agent should be able to look it up in orders. You also want to exchange your tablet to the cheapest one due to moving costs.

终止：user_stop；DB 匹配：False。

- Agent should modify address for the order
  - The agent did not modify the shipping address for any order. The agent repeatedly asked the user to provide the new address explicitly, but the user refused. No address change was made.
- Agent should modify user address
  - The agent did not update the user's default address. The agent requested the new address from the user, but the user did not provide it, and no update was performed.
- Agent should modify the items in the pending order.
  - The agent did not modify any items in the pending order. The conversation focused on address changes, and no item modifications were requested or made.
- 未命中预期写操作：`modify_pending_order_address`，参数 `{"order_id": "#W1092119", "address1": "760 Elm Avenue", "address2": "Suite 564", "city": "Houston", "state": "TX", "country": "USA", "zip": "77034"}`。
- 未命中预期写操作：`modify_user_address`，参数 `{"user_id": "sophia_martin_8570", "address1": "760 Elm Avenue", "address2": "Suite 564", "city": "Houston", "state": "TX", "country": "USA", "zip": "77034"}`。
- 未命中预期写操作：`modify_pending_order_items`，参数 `{"order_id": "#W1603792", "item_ids": ["6501071631"], "new_item_ids": ["2106335193"], "payment_method_id": "credit_card_5694100"}`。

## 解释限制

仍有真实 Agent 错误，例如未严格执行备选偏好、漏掉可查询地址、把 17.99 口头说成 18.00，不能将所有失败都归因于数据或评分器。
用户模拟器、模型与评分器仍有随机性。部分任务会出现用户明确选择/规格要求与预设写操作不一致，或订单数据缺乏日期却要求判定最近订单。
这些失败保留官方原分，不通过猜测未暴露信息、硬编码任务答案、强制改写用户选择来提升分数。
额外人工/安全 LLM 复审未运行，不能将空复审统计当作零问题。DeepSeek 的费用映射缺失，成本为不可用，不视作免费。

## 原始产物

- 基线：`runtime/benchmarks/retail-full-before-20261027/results.json`
- 优化后：`runtime/benchmarks/retail-full-final-20261027/results.json`
- 完整逐任务汇总：[JSON](retail-full-20261027.json)。
- [失败审查与候选回归](retail-full-audit-20261027.md)。
- [原始轨迹与检查点 ZIP](retail-full-20261027.zip)。
- 两轮完整对话和官方 reward_info 保留在上述 runtime/benchmarks 目录。
