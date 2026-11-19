# 2026-11-17 · 无工具 tau2 基线（10 任务，逐轮引擎指标）

在 2 任务版本上扩到 10 个 test 任务，并在评测作业内部每秒采样 `/metrics`，把每一轮对话的
TPOT、KV 占用、缓存命中都切出来。

| 项 | 值 |
| --- | --- |
| serve / eval 作业 | 29434 / 29439 |
| Agent | `bare_llm`（零工具） |
| 任务 | test split `5,9,12,17,18,26,27,32,33,36` |
| 用户模拟器 | `openai/qwen3.8-27b`（LiteLLM → 同一个 vLLM） |
| 采样 | 作业内每秒一次 `/metrics`，写 `metrics.jsonl` |

## 结果

10 个任务里 **8 个有效**，2 个基础设施错误：

| 任务 | 时长 | 终止 | 说明 |
| --- | --- | --- | --- |
| 5 | 65 s | user_stop | |
| 9 | 81 s | user_stop | |
| 12 | 227 s | user_stop | 最长的一次对话 |
| 17 | 0 s | infrastructure_error | 用户模拟器返回空消息（`UserMessage must have either content or tool_calls`） |
| 18 | 108 s | user_stop | |
| 26 | 45 s | user_stop | |
| 27 | 52 s | user_stop | |
| 32 | 53 s | user_stop | |
| 33 | 54 s | user_stop | |
| 36 | 0 s | infrastructure_error | 该任务请求 `gpt-5.4-mini-2026-03-17`，我们的端点没有这个模型 |

有效任务合计 685 s，72 条消息 = 36 轮。质量仍是 0：没有工具，DB 无法被修改。

## 逐轮引擎指标（来自 `/metrics` 增量）

| 指标 | 值 |
| --- | --- |
| TTFT | p50 **429 ms**，范围 120–1,198 |
| TPOT | p50 **15.39 ms**，范围 15.23–15.62 |
| KV 占用峰值 | **2.78%**（均值 1.47%，池 11.23 GiB） |
| 前缀缓存命中 | 均值 **60%**，最高 97% |
| 单轮引擎生成 token | p50 507，最大 3,803 |

三个观察：

1. **TPOT 非常稳定**（15.2–15.6 ms），说明解码本身没有抖动；每轮耗时差异几乎全部来自生成 token 数。
2. **KV 峰值不到 3%**：对话最长 227 s 也没把 KV 推高，这个场景的瓶颈不在缓存容量。
3. **缓存命中从 0% 到 97%**：第一轮必然全 miss，之后随历史复用上升；不同任务之间差异大。

## 文件

| 文件 | 内容 |
| --- | --- |
| `view.html` | 对话视图，每条消息下面标注该轮的 TPOT / KV / 缓存命中 |
| `turns.jsonl` | 逐轮指标（36 条），由 `join_turn_metrics.py` 对齐得到 |
| `metrics.jsonl` | 原始采样（每秒一行，1,162 条） |
| `results.json` | tau2 原始结果 |
| `atif.jsonl` | 10 条 ATIF-v1.8 轨迹 |
