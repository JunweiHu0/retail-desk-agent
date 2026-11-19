# 2026-11-18 · ngram 投机解码：负结果

在同一套负载上对比 `--speculative-config '{"method":"ngram","num_speculative_tokens":5,
"prompt_lookup_min":2,"prompt_lookup_max":4}'`。

| 项 | 基线 29488 | ngram 29493 |
| --- | --- | --- |
| serve 节点 | 10-0-4-11 | 10-0-3-11 |
| 其余配置 | TP=2 · 32k · max-seqs 4 · prefix cache | 相同 |

## 结果（p50）

| 思考 | 并发 | TTFT | TPOT | e2e | req/s |
| --- | --- | --- | --- | --- | --- |
| 开 | 1 | 499 → 374 (−25%) | 15.66 → **22.19 (+42%)** | 3867 → 5241 (+36%) | 0.26 → 0.19 (−27%) |
| 开 | 2 | 514 → 397 (−23%) | 19.68 → **41.14 (+109%)** | 4785 → 8667 (+81%) | 0.42 → 0.23 (−45%) |
| 开 | 4 | 1712 → 431 (−75%) | 21.50 → **60.25 (+180%)** | 6010 → 12625 (+110%) | 0.66 → 0.32 (−52%) |
| 关 | 1 | 468 → 343 (−27%) | 15.22 → **25.47 (+67%)** | 818 → 928 (+13%) | 1.20 → 1.07 (−11%) |
| 关 | 2 | 490 → 621 (+27%) | 33.08 → 42.93 (+30%) | 1265 → 1393 (+10%) | 1.54 → 1.42 (−8%) |
| 关 | 4 | 1589 → 1177 (−26%) | 18.69 → **47.00 (+151%)** | 2054 → 2108 (+3%) | 1.89 → 1.91 (+1%) |

## 为什么变慢

1. **输出没有可利用的重复**：这个模型主要产出自然语言和思考，不是结构化模板，ngram 草稿的接受率低，
   每次都要多算几个候选 token 再丢弃。
2. **异步调度被禁用**：vLLM 明确警告 `Async scheduling not supported with ngram-based
   speculative decoding and will be disabled`，这本身就是吞吐损失。
3. **批预算不够**：`max_num_batched_tokens=4096` 要同时容纳草稿槽位，vLLM 警告
   `max_num_scheduled_tokens is set to 4096 ... may lead to suboptimal performance`。

## 结论

投机解码在"输出高度重复"的负载上才划算（代码、JSON、tool-call XML）。这个 agent 的输出是
散文式中文回答 + 思考，属于反例。若要重试，至少需要同时把 `max-num-batched-tokens` 提到 8192，
但那是第二个变量，本次先保持单一变量。

文件：`run.json`（ngram）、`baseline-29488.json`（同负载基线）。
对比：`python3 deploy/tacc/bench/compare_runs.py baseline.json run.json`
