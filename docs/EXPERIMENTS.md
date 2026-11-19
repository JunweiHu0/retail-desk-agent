# 实验索引

一次提交 = 一组实验。每组一个目录，包含该次的配置、原始数据、视图和结论，互不混用。

| 日期 | 组 | 作业 | 内容 | 状态 |
| --- | --- | --- | --- | --- |
| 2026-11-17 | [serving-29378](experiments/2026-11-17-serving-29378/README.md) | 29378 | 合成 5k 前缀的并发扫描 | 作废（前缀不真实） |
| 2026-11-17 | [agent-29402](experiments/2026-11-17-agent-29402/README.md) | 29402 | 真实 prompt + 16 工具 schema，思考开/关 × 并发 1/2/4 | **当前基线** |
| 2026-11-17 | [tau2-bare-29388](experiments/2026-11-17-tau2-bare-29388/README.md) | 29388 | 2 个 tau2 任务、裸模型、pass^1 = 0 | 早期冒烟 |
| 2026-11-17 | [tau2-bare-29439](experiments/2026-11-17-tau2-bare-29439/README.md) | 29439 | 10 个 test 任务（8 有效）+ 逐轮引擎指标 | **质量下限** |
| 2026-11-17 | [tau2-bare-29443](experiments/2026-11-17-tau2-bare-29443/README.md) | 29443 | 补跑 4 个，全部失败（judge 模型） | 失败记录 |
| 2026-11-17 | [tau2-bare-29450](experiments/2026-11-17-tau2-bare-29450/README.md) | 29450 | 补跑 6 个（5 有效），合计 13 有效任务 | 中间批次 |
| 2026-11-17 | [tau2-test40](experiments/2026-11-17-tau2-test40/README.md) | test40 / test40-b | test split 全部 40 任务（34 有效），244 轮引擎指标 | **当前基线** |
| 2026-11-18 | [interference-29487](experiments/2026-11-17-interference-29487/README.md) | 29487 | 长 prefill 对在途解码的干扰 | PD 分离决策依据 |

## 每组目录里有什么

```
<date>-<name>-<job>/
├── README.md          结论、配置、关键数字
├── view.html          单页视图（可独立打开）
├── run.json           运行配置与汇总
├── atif.jsonl         逐次模型调用的 ATIF 轨迹
└── system_prompt.txt  实际发送的 system prompt（有则记录）
```

## 口径

- **TTFT**：第一个生成 token（含思考）
- **TPOT**：相邻输出 token 的平均间隔
- **e2e**：单次请求从发出到结束
- **工具调用率**：发出了工具调用的请求占比（工具由 tau2 执行，这里只统计模型意图）

## 复现

```bash
./deploy/run.sh tacc up --serve-only     # 只起 vLLM
./deploy/run.sh tacc bench               # 负载 + ATIF
python3 deploy/tacc/bench/build_view.py <run-dir>   # 重新生成视图
```
