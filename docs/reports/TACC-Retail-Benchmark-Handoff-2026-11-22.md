# Retail tau2-bench 评测交接

更新时间：2026-11-22（Asia/Shanghai）  
用途：交给后续模型继续核对学校 TACC 上的 Retail benchmark，恢复 task 89 的最终状态，并整理完整 badcase。

## ★ 最新进展（2026-11-22 09:20，接手者先读这一节）

本节之后的内容是 11-22 凌晨写的原始交接，其中关于 task 89、29969 作业和三个小组问题的状态已经过时，以本节为准。

### 0. 代码在哪

- 规范仓库：WSL `/home/mnyh/projects/retail-agent`，分支 **`feature/retail-ours-reviewer-fallback`**，基于 `dev@e09bba6`。这一节描述的全部改动都在这个分支的一个提交里。
- Windows 镜像 `C:\Users\hjw\Documents\ChatGPT\6000V大作业\retail-agent` 只放报告副本，不是 git 规范仓库。
- 测试：
  ```bash
  cd /home/mnyh/projects/retail-agent && .venv/bin/python -m pytest -q
  ```
  当前 **86 passed**，全部使用确定性模型或 MockTransport。
- 前端类型检查：
  ```bash
  cd frontend && npx vue-tsc --noEmit
  ```
  当前通过。

### 1. 已完成

| 项 | 结论 / 产物 |
|---|---|
| Qwen 1-trial 基线收尾 | 113/114 有效，pass^1 区间 [0.7895, 0.7982]，**不是最终官方成绩**。task 89 是 judge 侧 JSONDecodeError，可确定性复现（29969、30449 两次）。归档在 `docs/reports/tacc-20261116/final-…-20261122/`（有 SHA256SUMS） |
| 逐题 badcase | `TACC-Retail-评测记录-2026-11-22.md` 第 3 节，`TACC-Retail-Qwen-Baseline-Report-2026-11-22.md` |
| 与 proposal 对齐 | `TACC-Retail-Proposal-Alignment-2026-11-22.md`：指标冻结，三组 baseline（ours / bare / generic），3-trial 矩阵，rubric，streaming probe。工具在 `docs/reports/tools/` |
| General baseline | `benchmarks/tau2_generic_agent.py`（`--agent deep_generic`），测试在 `tests/test_generic_benchmark.py` |
| 小组问题 1：真值歧义 | 团队决定**改成本组自建的非官方 benchmark `retail_ours`**，不和官方榜单比较。补丁覆盖 52/64/68/105/109/110，并修复 stale-variant 工具 bug。见 `benchmarks/retail_ours/README.md`，测试在 `tests/test_retail_ours.py` |
| 小组问题 2：异常转人工 | 根因是 stale-variant bug 导致订单数据错乱（36/37），**不是会话串扰**，见 `tests/test_session_isolation.py`。新增确定性 reviewer `backend/reviewer.py`，测试在 `tests/test_reviewer.py`。tau2 侧用 `--reviewer off\|shadow\|enforce`，默认 off；Web 侧默认 enforce |
| 小组问题 3：人工兜底 | Web 侧：模型异常、reviewer 修正耗尽或 agent 转人工时生成 handoff 工单（`reviews` 表）。设置 `STAFF_TOKEN` 后，高额操作（`REVIEW_AMOUNT_THRESHOLD`，默认 1000）和写后不一致的操作需要用户批准加人工复核，接口是 `/api/staff/reviews`，前端已适配 `awaiting_review`。测试在 `tests/test_human_fallback.py`。tau2 侧模型异常仍作为 infra error 抛出 |

详细说明见对齐报告第 8 节和评测记录第 7 节。

### 2. 正在进行：TACC 3-trial 运行（官方 `retail`，reviewer off，修复前的代码）

| 组 | 作业（junwei） | 09:17 状态 | TACC 工作目录 |
|---|---|---|---|
| bare (`llm_agent`) | 30500 | 运行中，trial 0 已评 34/114，平均 reward 0.79 | `runtime/tacc-eval-20261122-proposal/retail-p3-bare` |
| generic (`deep_generic`) | 30501 | 排队（Dependency） | `…/retail-p3-generic` |
| probe（E1） | 30503 | 排队 | `…/retail-p3-probe` |
| ours (`deep_retail`) | 30504 | 排队 | `…/retail-p3-deep` |
| rubric（Q1） | 未提交；bare 和 generic 的 trial 0 都完成后由 driver 自动提交 | | `…/retail-p3-rubric` |

- 作业是 1 小时一片，由 **`driver2.sh`** 自动续跑，副本在 `docs/reports/tools/tacc/driver2.sh`。
  - 启动参数是 `"bare:ID generic:ID probe:ID deep:ID"`，日志在 `/home/mnyh/eval-dl/p3/driver.log`。
  - 每片结束后，过滤掉敏感行的日志存到 `/home/mnyh/eval-dl/p3/<组>-<作业>.log`。
- **注意**：driver 是在上一个 Claude 会话的后台 shell 里启动的，那个会话关闭后 driver 会停。接手者先检查它还在不在：
  ```bash
  pgrep -af driver2.sh
  tail driver.log
  /home/mnyh/.local/bin/tcloud ps
  ```
  如果 driver 不在了，从 `driver.log` 的最后几行和 `tcloud ps` 找出每组**当前**的作业号，然后用同样的格式重新启动 driver。重启后它会从 checkpoint 续跑，不会重复计分。
  - 某组的 `variant.env` 如果已经被改成 `TRIALS=3`，说明它的 trial 0 阶段已经完成。
  - 如果 `/home/mnyh/eval-dl/p3/bare.phase1.done` 和 `generic.phase1.done` 都存在而 rubric 还没提交，就手动 `cd …/retail-p3-rubric && tcloud submit`。
- 查看某个运行中作业的进度：
  ```bash
  bash docs/reports/tools/tacc/live.sh bare 30500
  ```
- 预计耗时：每组 114 × 3 个对话，并发 6，加上排队，总共需要十几个小时以上。

### 3. 接手者待办（按顺序）

1. **盯住 TACC 跑完。** 每组结束后，先把 `results.json` 下载到临时文件，校验 JSON 和 114×3 的覆盖情况，再放到正式位置（方法见下文“安全下载”一节）。
2. 计算指标：
   ```bash
   python3 -I docs/reports/tools/proposal_metrics.py RESULTS.json out.json --label ours|bare|generic
   ```
   结果填入对齐报告第 5 节的表格，包括 pass^1、pass^3、DB、F1–F4、token 和工具调用数。还要汇总 rubric 和 probe 的输出。infra 行（例如 task 89）按区间报告，不算普通失败。
3. **用 `retail_ours` 复测修复效果**（需要模型端点，TACC 或租的 vLLM 都行）。同模型、同配置，只改 reviewer：
   ```bash
   python -m benchmarks.run_retail --domain retail_ours --all --num-trials 3 --agent deep_retail --reviewer off --save-to ours-v010-rev-off
   python -m benchmarks.run_retail --domain retail_ours --all --num-trials 3 --agent deep_retail --reviewer enforce --save-to ours-v010-rev-enforce
   ```
   要在 TACC 上跑，就复制一份 `retail-p3-deep` 的作业目录，在 `variant.env` 里加 `--domain retail_ours` 和 `--reviewer`。先把这个分支的代码同步到 TACC 工作区。
4. 比较时要报告：总分，36/37/52/64/68/105/109/110 这些任务的变化，原来通过的 90 题有没有退化，reviewer 的触发次数（`raw_data.reviewer.log`），以及误报。
5. 还没做的硬规则：R1（退款后报总额）、R2（写前核算差价方向）、R3、R6（多订单逐一核对）。现在只靠 prompt，要做的话加到 `backend/reviewer.py` 并补测试。
6. 待团队决策：task 89 的 judge 方案（推荐给 judge 开 JSON mode 后统一重评）；是否向 tau2 上游报告 105、64_6 和 stale-variant bug；生产环境是否开启 `STAFF_TOKEN` 以及阈值定多少。

### 4. 规则（不变）

- 不要把密码、API key、SSH token、tcloud 凭据或 `.env` 写进交接文件、Windows 镜像或 GitHub。
- 只操作 `junwei` 自己的作业。
- `retail_ours` 的分数只能标注为 `retail_ours v0.1.0`（非官方），不能写成 tau2 官方分数。
- 未完成的 run 不能报成最终成绩。
- 普通测试只用确定性模型；live 检查要用户授权，并使用隔离的数据库。

## GitHub 项目

- 仓库：[JunweiHu0/retail-desk-agent](https://github.com/JunweiHu0/retail-desk-agent)
- 与本交接有关的分支：
  - `main`：目前主线使用 Deep Agents。
  - `dev`：同样使用 Deep Agents。
  - `backend`：LangGraph 实验分支，包含 `backend/graph_agent.py`、`backend/graph_profiles.py`，`AgentRunner` 依据 session variant 分派 native loop 或 LangGraph `StateGraph`。
  - `backend-backup-20261120`：agent planner/review/state 试验代码备份。
  - `deploy/tacc`：TACC 部署相关版本。
- 后续团队准备使用 LangGraph 方案；检查或修改代码前先确认所用分支，不要默认 `main` 就是 LangGraph。
- tau2 上游仓库：[sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench)。本轮 TACC 运行使用本地固定 checkout，先在 WSL 查看 commit：

```bash
git -C /home/mnyh/projects/tau2-bench rev-parse HEAD
```

## 课程作业 PDF

当前工作区找到的课程作业说明 PDF：

- Windows 路径：`C:\Users\hjw\Documents\ChatGPT\6000V大作业\assignment2-tacc\Assignment_2.pdf`
- 相对当前工作区：`assignment2-tacc/Assignment_2.pdf`

这是当前已确认找到的课程作业 PDF。WSL 的 tau2-bench 项目目录中也有一些 benchmark 插图和 telecom workflow PDF，它们不是这份课程作业说明。

## 连接学校 TACC

当前可用环境是 Windows 上的 WSL Ubuntu-24.04；TACC CLI 已安装并配置在该 WSL 账号下。不要把密码、API key、SSH token 或 tcloud 凭据复制到交接文件或 GitHub。

从 Windows PowerShell 进入 WSL：

```powershell
wsl -d Ubuntu-24.04
```

在 WSL 中测试集群连接并列出作业：

```bash
/home/mnyh/.local/bin/tcloud ps
```

常用目录：

```text
项目源码：       /home/mnyh/projects/retail-agent
tau2 上游源码：  /home/mnyh/projects/tau2-bench
本轮评测工作区： /home/mnyh/projects/retail-agent/runtime/tacc-eval-20261116
结果在 TACC：    $TACC_USERDIR/retail-agent/eval-20261116-nothink/full/results.json
评测 Slurm 配置：本地 runtime/tacc-eval-20261116/retail-eval-resume/tuxiv.conf
评测作业脚本：   本地 runtime/tacc-eval-20261116/retail-eval-resume/job.sh
模型服务脚本：   本地 runtime/tacc-eval-20261116/retail-eval-resume/model.sh
```

评测使用 `tcloud` 工作区和预先配置好的 `proxy` 环境。提交/查看命令：

```bash
cd /home/mnyh/projects/retail-agent/runtime/tacc-eval-20261116/retail-eval-resume
/home/mnyh/.local/bin/tcloud submit
/home/mnyh/.local/bin/tcloud ps
```

查看作业日志（先用 `tcloud ps` 查到自己的 job id）：

```bash
/home/mnyh/.local/bin/tcloud cat slurm_log/retail-eval-resume-JOBID.log
```

`JOBID` 替换成数字，例如 `29969`。本轮 TACC partition 的单作业时间上限为 1 小时；模型加载和 warmup 会占用一部分时间，runner 使用 checkpoint 自动跳过已完成任务。集群繁忙时作业可能排队。只操作本人 `junwei` 账号提交的作业，不取消或更改其他用户作业。

## 当前评测情况

- 任务集：本轮配置使用 Retail 全部 114 个注册任务，每个任务一次（seed 42）。
- 模型：Qwen3.8-27B AWQ INT4，经 vLLM OpenAI 兼容接口；agent、user simulator、judge 使用相同模型。
- 参数：`max_steps=100`、每任务 timeout 600 秒、并发 3；续跑时保留这些设置并启用 official tau2 checkpoint auto-resume。
- 旧的完整下载 `full-29191-download.json` 是初始阶段结果（40 道有效、38 道通过、74 道基础设施错误），不是完整最终结果。
- 后来续跑快照曾显示 113/114 道有记录、90 道 reward=1；task 89 是唯一 `infrastructure_error`。task 99 达到 `max_steps` 并记 0 分。该续跑结果的本地快照之后被截成 0 字节，不能把它当作当前完整证据。
- task 89 补跑作业曾提交为 Slurm job `29969`。截至交接编写时，最近一次成功 `tcloud ps` 没显示 `junwei` 的运行中任务；因此 29969 已结束或已离开当前活动队列，但完成原因和 task 89 最终结果仍待从结果文件/历史日志确认。
- 最近一次从 TACC `tcloud cat` 得到的 `results.json` 为 8,272,179 字节且 JSON 语法校验通过；但当时汇总脚本遇到本机路径问题，尚未确认该文件包含 task 89 的结果，也未复算最终分数。

旧的 113-task 失败摘要中列出的 23 个零分 task 为：28、35、41、42、46、52、59、64、66、68、76、82、93、95、97、98、99、100、104、105、109、110、112。可完整复核的最早 40-task checkpoint 只支持 task 28 和 task 35 的轨迹级根因：

- **Task 28**：退款 DB 状态通过，但最终答复漏报 $918.43 总额，NL assertion 失败。
- **Task 35**：用户拒绝支付 $113.71 差价并选择保留原单后，agent 仍提交 `modify_pending_order_items`，DB 状态失败。

其他续跑失败任务必须从完整最新结果中的 messages、`action_checks`、NL assertions 和工具 observations 重新检查，不要只凭 DB/NL 分数猜根因。

## 安全下载并核验最新结果

避免直接把远端输出重定向到唯一的本地 checkpoint；曾发生下载失败后将本地目标文件截为 0 字节。应先下载到新临时文件，检查大小并解析 JSON，成功后再替换正式快照：

```bash
cd /home/mnyh/projects/retail-agent/runtime/tacc-eval-20261116
tmp=$(mktemp /tmp/retail-results.XXXXXX.json)
/home/mnyh/.local/bin/tcloud cat retail-agent/eval-20261116-nothink/full/results.json > "$tmp"
test -s "$tmp"
python3 -m json.tool "$tmp" >/dev/null
python3 - "$tmp" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
rows = data["simulations"]
print("rows", len(rows))
print("task89", [(r["termination_reason"], (r.get("reward_info") or {}).get("reward"))
                 for r in rows if r["task_id"] == "89"])
print("termination", {k: sum(r["termination_reason"] == k for r in rows)
                       for k in sorted({r["termination_reason"] for r in rows})})
print("scored", sum((r.get("reward_info") or {}).get("reward") is not None for r in rows),
      "passed", sum((r.get("reward_info") or {}).get("reward") == 1 for r in rows))
PY
```

确认 JSON 行数、task 89 与统计结果合理后，再 `cp "$tmp" latest-resume-snapshot.json`。如果 `tcloud cat` 报错、超时、文件是空的或 JSON 无法解析，保留旧文件并重试；不要覆盖历史证据。最后使用 tau2 官方汇总/评分规则复算，不要把 infra error 当成有效普通失败，也不要把未完成 run 报为最终官方成绩。

## 接手者的建议步骤

1. 进入 WSL 执行 `tcloud ps`，确认集群目前可连接、本人没有仍在运行的续跑作业。
2. 先把 TACC 最新 `results.json` 安全下载到临时文件并校验；确认 task 89 是否已有分数及 114 个任务是否都有终止记录。
3. 如果 task 89 仍为 `infrastructure_error` 或缺失，检查原始 job 29969 日志与配置，再用相同模型和评测参数提交续跑；先确认该 `save-to` 的 checkpoint 路径、`auto_resume=True` 和 `TAU2_DATA_DIR` 设置。
4. 生成可复算的全量汇总：114 任务数、termination 分布、有效 scored 数、通过数/通过率、DB、NL/communication 分项、max_steps 和 infra errors。
5. 对所有失败任务做轨迹级根因分类，保存 task id、用户目标、相关对话/工具调用、工具返回、失败分项、根因证据和修复假设。
6. 更新 Notion 报告：[Tau2 Retail Benchmark 续跑表现分析](https://app.notion.com/p/41faa0ca6306819a864bf466cdbfb926)。同时明确标注模型、用户模拟器、judge、seed、trial 数和 tau2/agent commit，避免与 README 中 DeepSeek 评测（96/114、98/114）混为同一实验。

## 交给接手模型的具体任务

接手者的目标是完成一轮**可核验的 evaluation 闭环**，并把结论写回上述 Notion 报告；不是只查看一个总分。

### A. 收尾当前 Qwen 评测

- 连接 TACC，确认 `junwei` 自己的 job `29969` 是否结束，并取回 Slurm 日志。
- 安全下载最新官方 checkpoint，确认 task 89 是否得到正常终止及 reward；必要时用同一 checkpoint、同一模型和同一参数续跑 task 89。
- 等所有 114 个 task 都有可解释的终止记录后，用官方 tau2 scorer/summary 规则复算。清楚区分正常得 0、max_steps、agent/model error、infra error、缺失结果；说明哪些计入官方分母，哪些仍使 run incomplete。
- 保存原始 JSON、Slurm 日志、评分汇总与运行配置到有日期和模型/variant 标识的目录。保留已有原始文件；下载先写临时文件，非空且 JSON 校验通过后再命名为正式结果。

### B. 做逐题 badcase 归因

对每个 reward=0、max_steps、工具异常的 task，从 trajectory 逐条检查：

1. 该任务的用户目标、偏好、限制和可能改变主意的 turn。
2. agent 的消息、tool call 名称和完整参数。
3. 每个工具的 observation/错误，以及目标 DB 与实际 DB 的差异。
4. Tau2 的 reward basis、DB/action/communicate/NL assertion 分项和 judge 说明。
5. 把根因归到可执行类别：意图/状态追踪、业务政策、工具选择、参数抽取、写操作授权、数据库状态、最终答复遗漏、步数/超时、评测基础设施。
6. 每个结论引用具体 task、turn、tool 和评分证据；材料不足时写“待证”，不要根据分项标签猜根因。

特别回看已知案例：task 28（DB 成功但漏报 $918.43 退款总额）和 task 35（用户拒绝 $113.71 差价并保留原单后仍调用商品修改工具）。检查 LangGraph 分支的当前代码或既有修复是否覆盖这些行为，再建议是否需要回归用例。

### C. 建立团队可复用的可信基线

报告至少记录：Retail task 集/split 与 tau2 commit；agent 仓库 commit、分支和 variant；agent、user simulator、judge 模型及配置；seed、trial 数、max steps、timeout、并发、重试；数据/政策/工具 schema 版本；run 是否完整；原始结果和日志位置；汇总脚本/命令。

基线分数需报告总 reward 与有效 scored 数，并给出 DB、沟通/NL、终止原因分布。单 seed 明确标为单次观测，不声称模型稳定性。Infra failures 单独列出；不能混作 agent 的普通错误，也不能静默剔除。

### D. 后续对 LangGraph agent 做公平对照

- 先确认团队选用的 LangGraph 分支（目前代码可见 `backend`；仓库 `main` 仍是 Deep Agents）。记录精确 commit 和 `lg_*` variant。
- 以现有稳定 agent/配置作 baseline；比较时固定任务集、模型、user simulator、judge、seed、max steps、timeout、并发和数据版本，每组只改 agent variant 或一个明确因素。
- 先完整性校验，再比较总分、DB/communicate/NL 分项、失败 task 集合、工具调用数/错误、步数上限/基础设施错误及成本/时延（若结果可用）。
- 不把不同模型（例如本轮 TACC Qwen 与 README 中 DeepSeek）间的分差直接归因到 LangGraph。若要比较框架，模型与其他配置必须一致。
- 对每个针对 badcase 的代码/提示词修改，先说明可证伪的改进假设，再用相同基线配置复跑相关回归任务及完整评测；检查修复和回退。

### E. 交付物

接手完成后请留下：

- 一份完整、可复算的 run summary（114 task 的覆盖状态与评分口径明确）。
- 一份逐 task badcase 表：task id、reward/终止原因、失败维度、根因证据、建议动作、是否复测。
- 一份 LangGraph 对照结果（如尚未有资源完成，写出方案与阻塞点，不伪造结果）。
- 更新后的 Notion 页面与原始结果文件路径。
- 结论分开写“观察到的事实”“基于证据的根因判断”“尚未验证的假设”“下一轮实验”。

## 小组讨论发现与待验证方向

以下是小组讨论提出的三个问题/计划。它们是后续接手模型需要调查和设计的事项；除已有 badcase 外，目前不应当作已经证明的根因或已完成的功能。

### 1. Benchmark 参考真值可能过度限定答案

小组观察：部分 Retail 情景可能存在多个符合用户目标、政策与数据库约束的合理解法，但任务 evaluator/gold outcome 似乎只认可单一目标状态或参考结果。若另一个操作序列也合理且满足政策，却没有被 gold 接受，可能形成 false negative，把合理解法判成失败。

接手者需要：

- 找出疑似任务并列出 task id；对照 user scenario、domain policy、task evaluation criteria、gold DB 和评分代码。
- 判断差异属于 evaluator/gold 数据错误、任务本身歧义，还是 agent 实际违反政策/未达成用户目标；不要只因“另一条轨迹看起来合理”就认定 benchmark 错。
- 对每个疑似 false negative 保存证据：agent 轨迹、实际 DB 与 gold DB 差异、政策依据、用户最终确认/偏好，以及若有第二个解法时对应的目标状态。
- 将结果分类为“确认的 benchmark 问题”“合理但 benchmark 未覆盖的替代方案”“agent 错误”“证据不足”。建议团队向 benchmark 上游报告数据问题，或在内部分析中单独标记；未经批准不要擅自改官方 scorer/gold 之后仍称结果为官方分数。
- 主报告仍保留官方 tau2 分数；如需补充“人工复核的可接受替代解”分数，单独定义规则、由人工复核并标为团队内部二次评测，不与官方分数混写。

### 2. 普通请求偶发触发无关的人工转接

小组观察：有时用户提出普通问题，agent 却回复将转接人工；用户当轮并未要求转人工。当前原因未知，怀疑可能与上下文输入、历史消息或会话之间的状态隔离有关，但也可能是模型误判、policy prompt、工具返回/转接状态或 LangGraph 状态处理问题。

接手者需要：

- 从完整 trajectory 找出此类 task/turn，记录发生转接前的 user message、完整 agent history、system/policy/context、最近工具 observations、session status/transferred 状态及模型回复。
- 检查是否发生跨 session/episode 的消息串线、历史截断/拼接错误、状态字段未重置，特别检查不同 tau2 task 是否错误共用同一 LangGraph state、Store session、thread/checkpoint 或 conversation history。
- 对照 `AgentRunner.run()`、`_loop()`、LangGraph `run_graph()` 的新建/续接行为，验证每个 task 的消息历史、graph state、转人工标志和 checkpoint 生命周期；检查“转人工”由用户意图触发、模型自发判断触发，还是代码状态直接触发。
- 用隔离的新 session 和受控复现对照：普通问句、明确要求人工、前一 session 曾转人工后再开新 session。保存最小复现，不把“可能混入上一个 session”写成已确认原因，除非日志或测试证明。
- 修复后验证不同 episode 互不污染，并用相同的评测配置重跑相关回归任务。

### 3. 设计错误输出的人工兜底与复核链路

小组计划：系统需要识别模型的高风险或错误输出，将其送入兜底链路，由人工审核/接管，而不是让错误直接到达用户或执行副作用操作。该能力目前属于后续设计项，不能假设已经实现。

接手者与团队需要共同提出并验证：

- **触发信号**：工具/参数校验失败、policy 冲突、缺少关键数据、模型重复或超预算、低置信或 judge 检出答复遗漏、非预期转人工等；分别判断哪些信号可程序化，哪些只能作为风险提示。
- **执行边界**：写操作仍必须遵守现有 preview → 用户确认 → 服务端校验/提交边界。人工兜底不能绕过客户/订单归属校验、确认要求或审计记录。
- **人工处理方式**：暂停自动执行，记录完整上下文、模型拟答复、工具轨迹、数据库快照与触发原因；由人工批准/修改答复、拒绝操作或接管会话，并留下审核人、时间、决定和理由。
- **失败安全**：无人工可用时明确告知用户正在等待/稍后处理，不伪造“已转接成功”；超时、重复回调和人工拒绝都要有明确状态转换。
- **评测方式**：为触发准确性、漏报率、误报率、人工介入率、接管后的任务解决率、响应时延建立单独指标；用标注过的 badcase 做离线回放，再做隔离环境端到端验证。不要让同一个生成模型既自判正确又作为唯一验收依据。
- **渐进实现**：先做只告警/挂起的 shadow mode，人工检查触发质量；再在隔离 demo 中启用人工队列；验证审计和权限后再考虑进入团队演示流程。

接手模型的交付要求：把这三项各自写成“证据/复现”“当前判断与置信度”“建议的代码或 benchmark 变更”“验收用例”“尚待团队决策”。任何修改官方任务、评分规则或人工操作权限的提案都要和原始 tau2 官方结果分开报告。

## 报告口径

本次 TACC/Qwen 单 seed 实验与 GitHub README 中 DeepSeek 的开发评测采用不同模型/配置。它们是不同实验，不能直接把分数差异解释为 agent 框架变更的效果。基础设施中断、模型调用错误、max-step 终止与正常完成的 task 失败要分别列出。只有完整、配置可追溯并可从原始 JSON 复算的运行，才作为完整基线报告。
