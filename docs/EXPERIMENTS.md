# 实验记录

每一条都是一次可复现的运行：环境、负载、原始数据文件都写清楚，别人可以照着重跑。

---

## 1. Serving baseline：思考开/关 × 并发 1/2/4

日期：2026-11-17。这是 System Efficiency 方向的 baseline，后续所有改动都跟它比。

### 环境

| 项       | 值                                                                                                                    |
| -------- | --------------------------------------------------------------------------------------------------------------------- |
| 集群作业 | serve `29372`（bench `29378`）                                                                                    |
| 节点     | `10-0-3-11`，2 × 24 GB GPU                                                                                         |
| 模型     | `Qwen3.8-27B-AWQ-INT4`，以 `qwen3.8-27b` 提供服务                                                                 |
| vLLM     | 0.26.0，`--tensor-parallel-size 2 --dtype bfloat16`                                                                 |
| 调度参数 | `--gpu-memory-utilization 0.90 --max-model-len 32768 --max-num-seqs 4 --max-num-batched-tokens 4096`                |
| 特性     | `--enable-prefix-caching`，`--reasoning-parser qwen3`，`--enable-auto-tool-choice --tool-call-parser qwen3_xml` |

### 负载

固定形状，贴近本 agent 的真实流量：

- system prompt ≈ **5,000 token**（tokenizer 截断到 5000 后再 decode，所有请求共享同一前缀）
- user 消息一句订单查询，每个请求订单号不同
- `temperature=0`，`max_tokens=512`，流式 + `include_usage`
- 每格 **24 个请求**；先热身 2 个（丢弃），再依次跑
- **并发 = 同时打到 vLLM 的客户端请求数**，压测作业直连 `MODEL_BASE_URL`，不经过
  FastAPI/agent 后端。它对应真实系统里"同时有几个会话在等模型"，而非后端的并发实现
- 思考模式：`on`（服务端默认）/ `off`（`chat_template_kwargs.enable_thinking=false`）

### 结果

单位 ms。**TTFT** = 第一个生成 token（含思考）；**首正文字** = 第一个 `content` token，即用户/agent 真正看到内容的时间。

| 思考 | 并发 | TTFT p50 | TTFT p95 | 首正文字 | TPOT p50 | e2e p50 | gen | 思考字符 p50 | tok/s | req/s |
| ---- | ---- | -------- | -------- | -------- | -------- | ------- | --- | ------------ | ----- | ----- |
| on   | 1    | 352      | 367      | 2396     | 16.2     | 3160    | 184 | 535          | 55.5  | 0.30  |
| on   | 2    | 396      | 399      | 3353     | 20.8     | 4632    | 199 | 604          | 87.2  | 0.44  |
| on   | 4    | 392      | 1296     | 4223     | 25.7     | 5648    | 208 | 633          | 139.1 | 0.67  |
| off  | 1    | 337      | 342      | 337      | 17.5     | 1648    | 77  | 0            | 46.3  | 0.60  |
| off  | 2    | 627      | 643      | 627      | 23.1     | 2100    | 74  | 0            | 71.6  | 0.97  |
| off  | 4    | 396      | 1184     | 396      | 28.8     | 2824    | 83  | 0            | 108.8 | 1.32  |

思考长度分布（`on`，n=72）：min 380 · p50 604 · p90 724 · p95 773 · max 894 字符；零思考请求 0/72。

prompt token 数：`on` 5069，`off` 5033（关闭思考后 chat template 少 36 个 token）。

### 结论

1. **服务本身不是瓶颈**：两种模式 TTFT 都在 350–400 ms，prefill 与前缀缓存正常。
2. **思考把首正文字推迟 7 倍**（2396 → 337 ms），e2e 减半（3160 → 1648 ms，−48%）。
3. **思考占输出 token 约 58%**（184 → 77），每请求多付约 107 个 token。
4. **`tok/s` 不能当主指标**：关思考后 tok/s 反而下降（55.5 → 46.3），因为分子里都是思考 token；req/s 才是（0.30 → 0.60，×2）。报告用 **req/s + e2e**。
5. **并发 4 开始排队**：TTFT p95 367 → 1296 ms，e2e 5.6 s。这是 `max-num-seqs=4` 的边界。
6. 同一并发下 TPOT 稳定在 16–29 ms，说明 decode 本身没有退化；延迟差异全部来自"生成了多少 token"。

### 无效数据（保留作为教训）

第一次运行（job 29375）把 `max_tokens` 设成 128，**全部 24 个请求都恰好生成 128 token、正文为空**——思考把预算吃光了。因此：

- 大量请求的 TTFT 是 `None`（没有 content）。
- 那版报出的 TPOT 4.35 ms 是假的：只在少数"挤进正文"的请求上算，且计时起点在思考之后。

教训：先用探针确认返回结构，再设 token 上限。

另一个坑：vLLM 0.26 把思考放在 `reasoning` 字段，不是 `reasoning_content`。第一版统计只读后者，得到"0 字符思考"的错误结论。

### 原始数据

- `docs/data/2026-11-17-serving-baseline.json`（本次运行的完整 per-request 记录与汇总）
- 集群路径：`$TACC_USERDIR/retail-agent/bench/29378/results.json`

复现：

```bash
./deploy/run.sh tacc up --serve-only     # 只起 vLLM，留出第二个作业位
./deploy/run.sh tacc bench               # 提交负载作业并打印表格
```

### 下一步

| 实验                 | 改动                                          | 要对比的指标                    | 质量保障                    |
| -------------------- | --------------------------------------------- | ------------------------------- | --------------------------- |
| 思考关闭（agent 侧） | 让 agent 的请求带 `enable_thinking=false`   | 每轮 e2e、首正文字、tokens/turn | 同一批 10 个 task 的 pass^1 |
| 投机解码             | `--speculative-config '{"method":"ngram"}'` | TPOT、req/s                     | 输出抽样比对                |
| 并发上限             | `--max-num-seqs` 4 vs 8                     | req/s、TTFT p95                 | 无（模型未变）              |

---

## 2. 无工具基线（tau2 评测流水线验证）

日期：2026-11-17。目的不是拿分，是验证 tau2 runner 能跑通，并给出质量下限。

### 环境与负载

| 项         | 值                                                 |
| ---------- | -------------------------------------------------- |
| 作业       | serve `29372`，eval `29388`                    |
| Agent      | `bare_llm`：同一模型、同一政策，**零工具** |
| 任务       | `task_ids=[0,1]`，split=base，1 trial，并发 1    |
| 用户模拟器 | `openai/qwen3.8-27b`（LiteLLM → 同一个 vLLM）   |
| 结果目录   | `$TACC_USERDIR/retail-agent/tau2-results/29388`  |

### 质量

```
Average Reward 0.0000   Pass^1 0.000
Read Actions 0/8   Write Actions 0/2   DB Match 0/2
Termination: Normal Stop 2（都是用户主动结束）
```

符合预期：没有工具就无法查询或修改，任务全败。

### 时间与 KV（采样窗口 15:51:10–15:53:50）

| 指标            | 值                                      |
| --------------- | --------------------------------------- |
| task 0          | 114.3 s，12 条消息（6 agent / 6 user）  |
| task 1          | 63.5 s，6 条消息（3 / 3）               |
| 两次模拟合计    | 177.8 s                                 |
| 捕获窗口内请求  | 5 个（采样器晚启动，前半段缺失）        |
| TTFT 平均       | 0.518 s                                 |
| e2e 平均        | 12.68 s                                 |
| 生成 token/请求 | 677                                     |
| KV 占用峰值     | **1.7%**（11.23 GiB 池约 190 MB） |
| 排队 / 抢占     | 0 / 0                                   |
| 前缀命中        | 62.2%                                   |

### 结论

1. **KV 不是瓶颈**：并发 1、上下文约 5–6k token，KV 峰值不到 2%。
2. **延迟由生成 token 决定**：677 token/请求 × 约 18 ms = 12 s 量级，与 TPOT 折算一致。i
3. **真实任务的前缀命中率明显低于压测**（62% vs 91%），因为每个任务的对话历史不同；
   压测里"重复同一前缀"会高估缓存收益，报告里要分开写。
4. 无工具时模型会写很长的道歉解释，反而推高 token；这提醒：**提示词里的输出约束也是延迟旋钮**。

采样窗口不完整（采样器在评测开始约 2 分钟后才启动），请求数与 token 统计只覆盖后半段。

---

## 3. 真实 prompt + 工具 schema 的压测（ATIF 记录）

日期：2026-11-17。修正第 1 节的偏差：system prompt 不再用合成填充文本，而是直接调用
`backend.agent.system_prompt()`（policy + 应用契约），并把 16 个 Retail 工具的真实 schema
一起发过去，和线上请求一致。

- serve `29400`，bench `29402`，节点 `10-0-4-11`
- prompt 5,284 token（含工具 schema），24 请求/格
- 每个请求写成一条 ATIF-v1.8 轨迹：`docs/data/atif/atif.jsonl`（144 条）
- 视图：`docs/agent-infra.html`（由 `deploy/tacc/bench/build_view.py` 生成）

| 思考 | 并发 | TTFT p50 | TTFT p95 | TPOT p50 | e2e p50 | gen | 工具调用率 | req/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| on | 1 | 500 | 505 | 15.65 | 3860 | 216 | 0% | 0.26 |
| on | 2 | 517 | 908 | 19.73 | 4797 | 216 | 0% | 0.42 |
| on | 4 | 1741 | 1820 | 21.54 | 6041 | 217 | 0% | 0.66 |
| off | 1 | 471 | 472 | 15.22 | 821 | 25 | 4% | 1.19 |
| off | 2 | 493 | 875 | 33.24 | 1265 | 26 | 8% | 1.53 |
| off | 4 | 1619 | 1670 | 18.73 | 2078 | 25 | 4% | 1.88 |

### 与第 1 节的差异

1. **思考开时模型不调用工具**：6 个格子里工具调用率 0%，它选择用散文要客户提供邮箱；
   关掉思考后出现 4–8% 的工具调用。同一模型、同一提示，行为随思考开关改变——
   这条必须配合 pass^1 才能下结论。
2. **关思考后生成 token 从 216 掉到 25**，e2e 从 3.86 s 降到 0.82 s（−79%），比第 1 节的
   −48% 更大，因为真实提示下答案更短。
3. 并发 4 时 TTFT 从 ~500 ms 涨到 1.6–1.8 s（排队），比第 1 节更明显。

### ATIF 轨迹形状

```json
{"schema_version":"ATIF-v1.8","session_id":"bench-29402-0",
 "agent":{"name":"retail-agent-bench","version":"1","model_name":"qwen3.8-27b"},
 "steps":[
   {"step_id":1,"source":"user","timestamp":"...","message":"请告诉我订单 #W1000000 当前的状态。"},
   {"step_id":2,"source":"agent","timestamp":"...","model_name":"qwen3.8-27b",
    "message":"为了查询订单…请提供您的注册邮箱地址…","tool_calls":[],
    "metrics":{"prompt_tokens":5284,"completion_tokens":217},
    "extra":{"thinking":"on","reasoning_content":"...","ttft_ms":500,"tpot_ms":15.65,"e2e_ms":3860}}],
 "final_metrics":{"total_prompt_tokens":5284,"total_completion_tokens":217,"total_steps":2},
 "extra":{"concurrency":1,"mode":"on"}}
```

### GPU 侧（`nvidia-smi dmon -s pum -d 1`，serve 作业内部采样）

| 窗口 | SM 利用率 | 显存管道 | 功耗 | 显存占用 |
| --- | --- | --- | --- | --- |
| 压测 08:41–08:45 | 均值 **82.7%**，忙碌样本均值 **98.9%** | 均值 **53.9%**，峰值 79% | 均值 274 W，峰值 344 W | 22.3 GB / 24 GB |
| 空闲 08:34–08:36 | 0% | 0% | 27 W | 4 MB |

**这推翻了我先前的 roofline 猜测。** 我根据"每 token 要读一遍权重"推断 decode 是带宽
bound，但实测显存管道只到 54%，而 SM 在 99% 的采样里都处于忙碌状态。也就是说：

- 不是带宽打满，也不是 GPU 空闲（有大量可跑的工作）；
- 时间更可能花在反量化、小 batch 的 kernel 效率、以及 TP=2 的 all-reduce 上；
- 因此"换量化格式"未必有用，而"减少 token 数"（关思考）确实有效——数据也证明了这点。

注意：nvidia-smi 的 `sm` 只是"该采样周期内有 SM 在跑"，不代表计算单元饱和；
它能排除"GPU 空闲"和"显存带宽打满"两种解释，但不能单独证明是哪个 kernel 慢。
要继续定位需要 nsys。
