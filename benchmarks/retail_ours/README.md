# retail_ours — 小组作业自建的 Retail benchmark（非官方）

> **这不是官方 tau2 Retail。** 在 `retail_ours` 上的分数只能标注为 `retail_ours vX`，
> 不能与官方 tau2 排行榜或论文数字比较，也不能写成“tau2 retail 得分”。

## 基础

- 上游：tau2-bench `0c69df4` 的 `data/tau2/domains/retail/`（`db.json`、`policy.md`、`tasks.json`、`split_tasks.json`）。
- 上游文件在磁盘上**不做任何修改**。改动全部在运行时加载：
  `benchmarks/retail_ours/__init__.py` 读取上游任务，按 `task_patches.json` 打补丁，然后注册为新的 domain `retail_ours`。
- 评估器、user simulator、NL judge 和 reward 计算都沿用上游。

## 运行

```bash
.venv/bin/python -m benchmarks.run_retail --domain retail_ours --all --num-trials 3 --agent deep_retail
```

结果 JSON 带 `"domain": "retail_ours", "official": false`，以及 reviewer 模式。

`--reviewer off|shadow|enforce` 控制确定性 reviewer（`backend/reviewer.py`），默认 `off`。reviewer 属于 agent 一侧的改动，不属于 benchmark：比较 reviewer 的效果时，两组要用同一个 `retail_ours` 版本，分别设成 `--reviewer off` 和 `--reviewer enforce`。

## 改动清单（v0.1.0）

### 环境

| 改动 | 原因 |
|---|---|
| `modify_pending_order_items` 改为逐个 item 查询 variant（`backend/retail_tools.py::FixedRetailTools`） | 上游最后的写循环复用了校验循环剩下的 `variant`。一次修改多个商品时，每个商品都被写成最后一个 variant 的价格和 options（差价本身是对的）。agent 看到订单“数据错乱”后常常转人工（官方跑分 task 36/37）。单商品修改的行为和上游完全一致（有测试）。 |

web 后端 `backend/retail.py` 使用同一个修复后的工具类。

### 任务

| Task | 问题 | 改法 |
|---|---|---|
| 52 | “其他规格都不变，只把变焦拉到最大”无解：没有可用的 24MP + SD 卡 + 更大变焦的相机；gold 9228757377 把分辨率改成了 30MP | 改为有序偏好：保持 SD 卡、分辨率不低于当前、变焦最大。唯一解就是 gold |
| 64 | 订单还是 pending，场景却说 exchange；gold 里有一个对 pending 订单调用 `exchange_delivered_order_items` 的动作（必然报错）；黑色和银色 4K 防水机价格都符合，gold 默选黑色 | 场景说明订单未发货，平局时偏好黑色；删除 64_6 |
| 68 | 订单没有日期，两个 pending 订单无法判断哪个“最近” | 用户记得那单里有蓝牙音箱（只有 gold 订单有） |
| 105 | gold 不可执行：差价 +$21.10，唯一支付方式礼品卡余额只有 $17.00，上游工具直接报错 | gold 改为“数据库不变”，NL assertion 改为检查 agent 解释余额不足、不能谎称已完成 |
| 109 | 哪个地址是“新家”取决于对句子的理解，user sim 多次弄反 | 场景明确写出哪个订单是新地址、哪个是旧地址，以及用信用卡支付 |
| 110 | 同 109，角色对调；账户默认地址已经是新地址，原 NL 要求“修改用户地址”在 no-op 时判定不稳定 | 场景写清楚；NL 改为“确保默认地址是新家（可能已经是）” |

每条补丁的证据写在 `task_patches.json` 的 `evidence` 字段，测试 `tests/test_retail_ours.py` 会检查：

- 只有这 6 个任务被修改，其余 108 个与上游逐字段相同；
- 补丁后的 gold 动作在环境里都能执行；
- 52、64 的唯一解成立；
- 上游 105 的 gold 确实会报 `Insufficient gift card balance`。

## 版本规则

改动任何补丁或环境都要升 `task_patches.json` 的 `version`，并在这里加一行 changelog。不同版本的分数不能直接比较。
