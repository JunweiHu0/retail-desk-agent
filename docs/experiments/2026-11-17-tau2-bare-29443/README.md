# 2026-11-17 · 补跑 4 个任务（全部失败）

为把有效任务补到 10 个而提交的第二次运行。**0 个任务完成**，但暴露了一个真实问题。

| 任务 | 时长 | 终止 | 原因 |
| --- | --- | --- | --- |
| 38 / 39 / 40 | 0 s | infrastructure_error | tau2 的 NL 断言评测器硬编码 `gpt-5.4-mini-2026-03-17`，我们的端点没有这个模型 |
| 42 | 0 s | infrastructure_error | 用户模拟器返回空消息（`UserMessage must have either content or tool_calls`） |

## 已修

`benchmarks/run_retail.py` 现在把断言评测器指向我们自己的模型：

```python
nl_eval.DEFAULT_LLM_NL_ASSERTIONS = f"openai/{config.MODEL}"
nl_eval.DEFAULT_LLM_NL_ASSERTIONS_ARGS = {}
```

注意：用自己的模型当裁判会影响 NL 断言的分数，报告中需要说明这一点。

文件：`results.json`、`metrics.jsonl`（采样到但全程没有请求）。
