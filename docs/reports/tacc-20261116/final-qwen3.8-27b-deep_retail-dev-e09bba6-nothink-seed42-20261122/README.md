# Qwen3.8-27B / deep_retail / dev@e09bba6+tacc-nothink / seed 42 — 运行归档（2026-11-22）

**状态：113/114 有效，未完成。** task 89 两次都在 NL-assertion judge 阶段报 `JSONDecodeError`（作业 29969 和 30449，同一位置 `line 8 column 26 (char 312)`），属于确定性的评测基础设施错误。**本 run 不能作为最终官方成绩。**

| 分桶 | 数量 | 任务 |
|---|---|---|
| pass | 90 | — |
| 普通 0 分（user_stop） | 22 | 28 35 41 42 46 52 59 64 66 68 76 82 93 95 97 98 100 104 105 109 110 112 |
| max_steps | 1 | 99 |
| agent error | 0 | — |
| infra | 1 | 89 |
| missing | 0 | — |

- 暂定 pass^1：90/114 = **0.7895**（task 89 按"未通过"计，这是下界）；如果 89 通过则为 91/114 = 0.7982。**区间 [0.7895, 0.7982]**
- 113 个已评分任务的平均 reward：0.7965（与 tau2 自带汇总一致，tau2 自带汇总排除了 infra）
- 判分代码：未修改的官方 tau2 `0c69df4`，judge 为 `openai/qwen3.8-27b`

## 文件

| 路径 | 内容 |
|---|---|
| `raw/results.json` | 最终 results（作业 30449 结束后下载），sha256 `39c0ae02…3585`，114 行，task id 无重复 |
| `raw/results-pre30449-snapshot.json` | 30449 之前的快照（`10d754f3…2c87`），与最终版只差 task 89 的时间戳和 trace |
| `summary.json` | 由 `final_summary.py` 按官方口径分桶得到的逐任务结果 |
| `logs/retail-eval-resume-{29969,30449}.log` | 作业日志，敏感赋值已脱敏 |
| `config/job.sh`, `model.sh`, `tuxiv.conf` | 作业、vLLM、调度配置（密钥行已替换为 `<REDACTED>`） |
| `config/tacc-nothink.patch` | TACC 副本相对 git `e09bba6` 的 diff（`backend/agent.py`、`benchmarks/run_retail.py`） |
| `config/agent-commit.txt`, `code-data-sha256.txt` | commit 和代码/数据文件的 sha256 |
| `SHA256SUMS` | 本目录全部文件的校验和 |

分析见 `../../TACC-Retail-Qwen-Baseline-Report-2026-11-22.md`。
