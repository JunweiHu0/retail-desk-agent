# 后端与 Agent 说明：接口、执行流程、评测及 TACC 部署

适用代码：`feat/retail-agent-eval`，包含工具接口增强 `cf632c4` 及 main@f3d9765 的账号/订单 API 合并。本文说明当前实现，不表示 TACC 已部署或已通过真实模型验收。实际测试证据见 [VERIFICATION.md](VERIFICATION.md)；详细评测契约见 [EVAL_PROTOCOL.md](EVAL_PROTOCOL.md)。

## 1. 职责与部署模块

我们负责后端 API、agent harness、官方工具接入、会话/DB 持久化以及 evaluator 接口。前端负责展示和发送用户操作，不参与模型推理。当前确认仍是独立 `decisions` 请求；纯聊天确认尚未实现。

最小运行链路只有两类常驻进程：

```text
前端 / evaluator 客户端
        │ HTTP 消息、确认/拒绝；接收 SSE 或 JSON
        ▼
FastAPI + AgentRunner + RetailService + SQLite   ← CPU 应用进程
        │ OpenAI-compatible /v1/chat/completions
        ▼
vLLM + 模型权重                                 ← GPU 推理进程
```

| 模块 | 是否必须 | 作用 |
| --- | --- | --- |
| `backend/` 整个目录，包括 `guides/` | 必须 | API、agent、业务适配、状态存储、日志及工具配置；不要只复制agent.py |
| Python 应用环境 | 必须 | 安装项目依赖及固定版本tau2，Python要求 `>=3.12,<3.14` |
| tau2 Python代码包 | 必须 | 提供RetailDB、RetailTools、工具schema和业务实现 |
| Retail `db.json`、`policy.md` | 必须 | 初始化沙盒数据、提供政策及运行摘要 |
| OpenAI-compatible模型服务 | live模式必须 | 支持原生tool calling；C1/C2/advisory还需要JSON Schema结构化输出 |
| 可写SQLite路径、日志/输出目录 | 必须 | 活动会话、episode DB、消息、审批及审计 |
| `benchmarks/` | 在本部署运行eval时必须 | HTTP驱动、模拟用户、冻结target、DB比较、报告 |
| `tasks.json`、`split_tasks.json`及固定tau2源码 | 构建target/审计时必须 | 生成并验证官方参考最终状态；不进入agent输入 |
| 完整冻结fixtures | 跑eval时必须 | 每题initial/target及范围、manifest和complete.json；仅评测器读取 |
| `frontend/dist/` | 可选 | 后端托管网页时才需要；前端独立部署则不用 |
| `web/infra/` | 可选 | 可视化诊断页面；不影响核心消息/工具API |
| `deploy/tacc/`、`deploy/run.sh` | 使用现有部署助手时需要 | 作业打包、提交、状态检查和隧道入口 |
| `tests/`、开发依赖 | 验证时需要 | 不属于线上模型推理必需模块 |

不需要额外的agent GPU、向量数据库、训练服务或独立的planner服务器。当前planner/reviewer只是同一个模型的内部调用。模型权重不应放进tcloud提交的应用代码包，使用平台提供或单独准备的模型目录。

## 2. `tau2-bench/` 文件夹到底需不需要？

需要区分“安装的Python包”和“源码/数据目录”。它们有不同用途，`TAU2_ROOT` **不是** Python导入路径设置。

### 2.1 同级源码开发/完整复现：保留整个仓库

```text
workspace/
├── retail-desk-agent/
│   ├── backend/
│   ├── benchmarks/
│   ├── pyproject.toml
│   └── uv.lock
└── tau2-bench/
    ├── src/tau2/
    ├── pyproject.toml
    └── data/tau2/domains/retail/
        ├── db.json
        ├── policy.md
        ├── tasks.json
        └── split_tasks.json
```

本项目 `pyproject.toml` 使用 `tau2 = {path = "../tau2-bench", editable = true}`。因此按现有 `uv sync --frozen` 路线安装时，同级完整目录必须存在。仅把JSON文件放在那里不能安装Python包。

固定tau2版本：`0c69df456a96aa76a1162591574dad9c427a34d7`。不要改动原始DB/任务或随意升级到上游main；也不要直接 `pip install tau2`，可能安装到PyPI同名的其他项目。

### 2.2 TACC已安装包的运行部署：可以只留数据目录

现有 `deploy/tacc/setup/job.sh` 分开做两件事：

1. 从固定commit的GitHub源码压缩包安装tau2到应用venv；没有使用本地editable路径。
2. 下载四个Retail资产到 `$TACC_USERDIR/retail-agent/tau2-bench/data/tau2/domains/retail/`。

此时业务运行不需要另带整个tau2 Git仓库，但**不能删除已经安装的tau2包或上述数据资产**。应用至少会读db.json/policy.md；保留四个资产便于来源核对。`TAU2_ROOT` 指向这个含 `data/tau2/...` 的根目录。

注意：不要在这种“已装包＋只有数据目录”的部署里再运行当前项目的 `uv sync`，它仍会寻找完整同级源码。使用已准备环境的Python直接启动应用。

### 2.3 需要在TACC重新生成target：仍需完整固定源码

`build-targets` / `audit-reference` 会校验源码版本、数据哈希及导入代码。只有wheel和四个资产不足以通过完整源码审计。两种交付方法：

- 携带干净的固定commit Git检出；或
- 携带完整源码归档及生成时记录的摘要清单。归档父目录的 `source-manifest.json` 需包含完整tau2源码/资产摘要，见 [fixtures.py](../benchmarks/reference/fixtures.py)。

更简单的TACC运行方式是复用已经生成的完整冻结fixtures。需要带上该fixture集合的manifest.json、所有task文件和complete.json，而不只是一个target文件。私有targets只能由eval读取，不放入agent提示词或新增查询工具。

## 3. 当前代码结构

| 文件 | 职责 |
| --- | --- |
| `backend/main.py` | main 的 cookie/订单 HTTP 入口、SSE/JSON、同会话运行互斥、私有 eval 接口 |
| `backend/auth.py` | main 的密码哈希、登录 cookie 会话及撤销、账号注册与登录限流 |
| `backend/agent.py` | 消息历史、模型调用、工具选择与顺序执行、审批后的续跑、调用/时间预算 |
| `backend/retail.py` | 官方工具catalog、身份/订单归属校验、写预览、批准后调用官方写函数 |
| `backend/tool_profiles.py` | 工具描述、只读结果包装、两个纯查询助手；不读取评测答案 |
| `backend/store.py` | SQLite持久化、每个episode的数据副本、消息/状态/事件和冻结 |
| `backend/agent_planner.py` | 可选结构化需求提取；来源为用户消息和真实观察 |
| `backend/agent_state.py` | 任务笔记、依赖、proposal/action/receipt关联 |
| `backend/agent_review.py` | 可选的有界完成检查；接收真实回执，输出问题类别 |
| `backend/config.py` | 路径、模型、运行模式、可用variant |
| `backend/provenance.py` | 源码、政策、数据和运行配置摘要 |
| `backend/telemetry.py`、`infra.py` | 调用/工具/耗时日志和诊断API |
| `benchmarks/run_http.py`、`benchmarks/reference/` | 独立评测驱动和最终DB比较 |

当前主执行器是显式原生工具循环，不是Deep Agents的自动规划图。依赖文件仍声明deepagents；部署时按现有依赖清单安装，不把“运行器已替换”理解成已经验证可以随意删依赖。

## 4. 消息、多轮与工具执行

一次用户消息会追加到持久历史，随后进入模型循环：

1. 注入完整政策、当前客户上下文、历史以及该variant启用的提示/状态。
2. 模型输出最终文本，或一个工具调用。
3. 查询工具读取当前episode DB，把观察放回同一轮历史，再调用模型。
4. 缺少用户偏好时，模型回答一个问题，本轮结束；下一条用户消息继续同一会话。
5. 写工具在RetailDB副本上调用官方函数以验证并生成before/after预览，不保存这份业务变更。
6. 返回awaiting_confirmation后暂停。前端/evaluator批准或拒绝准确的action_id。
7. 批准：重新读取当前数据，校验预览对应状态，执行官方函数，在事务中保存业务DB及receipt；拒绝：DB不变，保存拒绝receipt。
8. 把实际receipt放回历史。公共浏览器接口按 main 返回 JSON，下一条用户消息继续；内部评测接口自动续跑并返回 SSE。

重要区分：模型说“完成”、tool预览成功、SSE的done，都不等于DB已经修改。以实际executed receipt和DB为准。当前聊天中的yes不会代替decisions接口；若改为聊天确认，需另外实现并冻结交互协议。

读取工具/修改工具的名字和参数来自官方catalog，模型不生成任意SQL。业务数据在内存中表现为tau2的RetailDB对象；SQLite负责持久化这些JSON数据和运行状态。

## 5. 会话、状态和数据隔离

一个应用SQLite文件包含浏览器会话和评测 episode。`owner_user_id` 非空的浏览器会话读取共享业务 `dataset`，所有入口按账号校验归属，确保聊天修改可在订单页立即看到。无 owner 的评测会话通过 `session_datasets` 保存独立完整 RetailDB JSON，不改变浏览器数据或其他 episode。旧匿名会话不自动归属账号；main 的既有账号会话继续使用共享数据。

- `dataset`：持久业务 DB，同时作为未指定 initial_db 的内部 episode 初始来源。
- `accounts` / `auth_sessions` / `login_attempts`：main 的密码哈希、可撤销 cookie 会话及登录限流。
- `sessions`：用户身份、消息、模型历史、pending、agent_state、usage、manifest、结束原因。
- `session_datasets`：每个episode当前业务数据库。
- `events` / `actions`：工具观察、决定、实际写入和回执等审计记录。

pending/历史/账本随SQLite保存，应用重启且保留同一DB文件时可以恢复；节点 `/tmp` 被回收则不能承诺恢复。`finish` 冻结业务写入，并导出最终状态；已有写入不会因超时或错误自动回滚。快照保留不代表已实现从快照自动恢复长任务。

当前按照单个Uvicorn进程运行。会话busy状态含进程内控制，不把它描述为已验证的多worker/多实例服务。

## 6. Agent与工具实验配置

浏览器按 main 创建默认 B1，并隐藏两个身份查询工具（14 工具）；下表工具数量指内部评测配置。variant 在内部创建评测 episode 时固定，前端无须理解其内部实现。

| 配置 | 执行结构 | 工具数 |
| --- | --- | --- |
| b1 | 最小政策＋历史＋原生工具循环，默认对照 | 16 |
| state / errors / guide / enhanced | 历史实验：状态、错误上下文、指南或组合 | 16 |
| c1 | 强制规划、任务账本、任务匹配约束 | 16 |
| c2 | C1＋有界检查；ready任务可触发指定工具纠正 | 16 |
| advisory | 账本降为参考；真实回执约束重复操作 | 16 |
| lean | 无planner/reviewer，回执投影＋同轮重复读取限制 | 16 |
| tools_described | B1循环，改进工具描述 | 16 |
| tools_structured | 上项＋只读observation envelope，保留完整data | 16 |
| tools_extended | 上项＋订单商品筛选、产品款式筛选 | 18 |

新增只读工具：

- `find_customer_order_items`：当前客户订单内，按状态、产品及属性AND筛选，保留重复商品的item_index。
- `find_product_variants`：按产品ID、属性、availability筛选，返回匹配项和真实款式计数。

不做模糊匹配、静默放宽或自动选择支付方式。所有写入仍为官方七个写工具。工具配置差异记录在 `tool_interface` 中，并与harness差异分开比较。默认预算为每episode 80次模型调用、80次工具请求、600秒；planner/reviewer/repair均计入，单次模型输出上限4096token。HTTP evaluator另计从开始到结束的时间。

## 7. 前端与eval接口

| 调用者 | 接口 | 输入/返回 |
| --- | --- | --- |
| 前端 | POST `/api/auth/register`、`/api/auth/login`、`/api/auth/logout` | main 的账号流程；login 设置 HttpOnly cookie |
| 前端 | GET `/api/me`、`/api/orders`、`/api/orders/{oid}` | 仅当前客户资料和订单 |
| 前端 | POST `/api/me/address`、`/api/orders/{oid}/actions` | 返回待审批 session，写前 DB 不变 |
| 前端 | GET/POST `/api/sessions` | 列出账号会话 / 无请求体创建账号 B1 会话，不返回 token |
| 前端 | POST `/api/sessions/{id}/messages` | `{message}` → SSE |
| 前端 | POST `/api/sessions/{id}/decisions` | `{action_id, approve}` → JSON `{receipt, session}` |
| 前端 | GET `/api/sessions/{id}` | 消息、客户/订单上下文、pending、状态、usage等 |
| 运维 | GET `/api/health` | 模式、模型配置、variants、基础tools=16及各配置tool_interfaces |
| eval | POST `/internal/eval/episodes` | 初始DB、customer_id、variant、task/trial/seed；不接收target |
| eval | GET `/internal/eval/episodes/{id}`；POST `.../messages`、`.../decisions` | episode Bearer token；消息/审批返回 SSE，审批后自动续跑 |
| eval | POST `/internal/eval/episodes/{id}/finish` | `{reason}`，冻结并导出 |
| eval | GET `/internal/eval/episodes/{id}/snapshot` | 私有完整实际DB、manifest、agent_state等 |

前端使用 main 的 `retail_auth` cookie；公共 API 不接受 episode Bearer token。注册/登录/退出、SameSite=Lax、HTTPS Secure、Origin 校验与 APP_BASE_PATH cookie 路径保持 main 约定。内部评测创建/冻结/快照使用 EVAL_API_TOKEN，交互使用 episode token；登录 cookie 不能访问评测会话。评测 token 不交给前端或 agent。messages 返回 SSE；公共 decisions 返回 JSON 且不调用模型；内部 decisions 返回 SSE 并自动续跑。SSE 的 done 仅表示本轮结束。协议已升级为 retail-http-v2，旧 evaluator 必须同步升级路由。

`/api/health` 的model_ready只是当前代码的配置级检查，不证明模型已成功生成tool_calls。TACC验收必须另测工具调用和工具结果续跑。

## 8. 最终DB评测如何工作

```text
固定初始DB ──官方参考动作重放──> target DB（私有、离线冻结）
     └────候选agent＋模拟用户──> actual DB（结束后冻结）
                               │
                     完整客户＋其全部初始订单逐字段比较
```

模拟用户是独立模型调用，使用任务用户场景与可见对话/卡片/回执，不使用target。evaluator调用与前端相同的消息和决定接口，不需要网页。主分不检查工具顺序/工具匹配，不使用LLM判断DB是否正确；日志用于诊断和成本统计。

比较包含支付、退款、商品、地址、状态和未修改订单，不只比较参考动作改过的字段。列表保留顺序和重复数量。错误/预算截止后只要有有效冻结DB，仍按同一规则评分。因此DB正确可能伴随对话失败；欠明确偏好也可能产生合法但不同于唯一target的状态，见 [EVAL_ALIGNMENT.md](EVAL_ALIGNMENT.md)。

数据总数114：development54＋validation20＋test40，smoke8是development的子集。开发结果不当正式测试成绩。完整比较要求相同模型、模拟用户、任务、目标、预算及evaluator代码；工具增强实验额外记录和核验工具接口差异。

## 9. TACC部署布局与作业分工

现有脚本结构是setup → GPU serve → CPU agent。setup只准备一次环境，不是常驻服务。若平台只允许两个运行中作业，可把evaluator放在CPU agent作业内作为另一个进程，避免再占一个作业名额；平台当前配额需现场核实。

建议交付形状：

```text
作业代码包/                         按新的release/作业目录保存
├── source-manifest.json            打包时生成的真实版本/摘要
├── app/
│   ├── backend/                    含tool_profiles.py、guides等全部文件
│   ├── benchmarks/                 运行eval时携带
│   ├── pyproject.toml、uv.lock      依赖来源记录；预装venv路线不在此uv sync
│   └── frontend/dist、web/          按需
└── job.sh、tuxiv.conf               平台入口

$TACC_USERDIR/retail-agent/
├── venv.tgz                        与平台Python/ABI匹配的应用环境
├── tau2-bench/data/tau2/domains/retail/   固定资产
├── server-url.txt                  GPU作业发布的/v1地址
├── fixtures/<冻结集合>/            私有评测输入与target
├── runs/<新批次>/                  eval输出
├── episodes/<job-id>/              快照输出
└── infra/                          运行日志

节点本地 /tmp/retail-agent-<job-id>.sqlite3  活动SQLite；不能当长期持久盘
```

应用包不需要包含模型权重或本机/huoshan的venv。TACC原setup将环境在节点本地构建、打成单个tar包存回共享目录，避免大量小文件写入。不要把不同机器的huoshan推理环境直接当TACC运行环境。

### 9.1 GPU模型服务

`deploy/tacc/serve/job.sh` 当前配置目标是课程目录中的 `Qwen3.8-27B-AWQ-INT4`，别名 `qwen3.8-27b`，TP=2、32K上下文、max-num-seqs=4、qwen3 reasoning parser、qwen3_xml tool parser。它不是当前huoshan的9B配置。

这些是脚本配置，不代表已验证实际权重和模型能力。部署时核验模型目录/摘要、课程vLLM版本、原生tool_calls及工具结果续跑。旧脚本将CUDA可见设备写为0,1，这是课程容器的历史假设；按实际Slurm分配及容器映射核验，不复制huoshan的GPU编号。只使用分配给当前作业的资源。

### 9.2 CPU应用作业配置

以下是**作业内配置示例**，应在环境解压、模型地址探活完成后，写入应用job.sh或该作业实际生效的环境；只改本机 `.env` 不保证tcloud传递到远端。不要在本机或登录节点直接执行模型请求来代替平台作业。

```bash
source /mnt/home/public/course-envs/CSIT6000V/project/activate.sh
# APP_PYTHON 指向本作业已解压、装好依赖的应用venv/bin/python
: "${APP_PYTHON:?Set the prepared application Python path}"
: "${TACC_WORKDIR:?Run inside a platform job}"
: "${TACC_USERDIR:?Run inside a platform job}"
: "${SLURM_JOB_ID:?Run inside a platform job}"
RUN=(bash "$QWEN_PROJECT_ROOT/runtime.sh" "$APP_PYTHON")

export AGENT_MODE=live
export MODEL_BASE_URL="$(head -n 1 "$TACC_USERDIR/retail-agent/server-url.txt")"
export MODEL_NAME=qwen3.8-27b  # 必须与服务实际/v1/models一致
export MODEL_API_KEY=EMPTY   # 仅适用于未启用API鉴权的内部服务
export MODEL_THINKING=off    # 首轮待验收配置；与eval一致，不混用其他thinking组
export TAU2_ROOT="$TACC_USERDIR/retail-agent/tau2-bench"
export RETAIL_DB_PATH="/tmp/retail-agent-$SLURM_JOB_ID.sqlite3"
export RETAIL_ARTIFACT_DIR="$TACC_USERDIR/retail-agent/episodes/$SLURM_JOB_ID"
export INFRA_DIR="$TACC_USERDIR/retail-agent/infra"
# eval-token由运维预先生成、限制读取权限；不要提交或打印它
export EVAL_API_TOKEN="$(cat "$TACC_USERDIR/retail-agent/eval-token")"
cd "$TACC_WORKDIR/app"
"${RUN[@]}" -m uvicorn backend.main:app --host 0.0.0.0 --port 8787
```

只做交互服务时可不配置EVAL_API_TOKEN，私有eval接口会关闭。前端不在本包时，核心API仍可启动；前端如何代理到API由其部署方处理，当前没有宣称跨域直连配置已完成。

### 9.3 evaluator作为单独进程

在同一个已分配CPU作业内、API就绪后，使用同一应用环境启动；以下需要第二个进程，不能放在前述前台uvicorn退出之后才执行。冻结fixtures必须已完整交付。

```bash
"${RUN[@]}" -m benchmarks.run_http run \
  --fixtures "$TACC_USERDIR/retail-agent/fixtures/smoke8" \
  --output "$TACC_USERDIR/retail-agent/runs/$SLURM_JOB_ID/b1" \
  --base-url http://127.0.0.1:8787 \
  --model-base-url "$MODEL_BASE_URL" \
  --model "$MODEL_NAME" --thinking "$MODEL_THINKING" \
  --variant b1 --seeds 0
```

先做少量功能检查；正式54/20/40题遵循 [EVAL_PROTOCOL.md](EVAL_PROTOCOL.md)。当前runner逐题串行、每次新建输出目录，没有跨作业自动续跑/合并的完整调度器。

现有tuxiv.conf给serve/agent请求1小时；课程本地笔记（2026-11-06快照）也记录1小时上限，实际以现场Slurm为准。长批次不能假定一个作业跑完。infra/eval需提前落实固定分片、每题结束及时落盘及完整集合汇总，或在已验证的huoshan完成长评测；不能把部分成功任务拼成完整分数。

## 10. 现有TACC部署助手还缺什么

[旧部署入口](../deploy/tacc/README.md)保留，但当前不是新HTTP DB评测的一键验收脚本。静态检查发现：

| 接缝 | 当前脚本情况 | 部署交接要求 |
| --- | --- | --- |
| 后端独立打包 | up.sh强制ensure_frontend_dist，stage_app只复制backend/dist/web | 后端模式可省dist/web；eval需增加benchmarks，当前助手尚未实现此模式 |
| 版本记录 | staging不生成新评测需要的source-manifest.json | 从真实检出生成，放app父目录；不能凭空填写SHA |
| live模式 | agent/job.sh模型不可达时会自动降级demo | 正式eval显式live，模型探活失败应报告失败，不能把demo当模型结果 |
| 私有eval配置 | 默认没有eval token/持久artifact目录配置 | 在远端作业注入同一token，设置RETAIL_ARTIFACT_DIR和持久输出 |
| 环境透传 | env.example不是远端环境注入器；agent端口重试只更新本机变量 | 核对模型名、端口、thinking和token确实进入最终作业；不能只改本机变量 |
| 作业归属 | lib.sh的me()取本机id -un | 使用已有tcloud配置确认远端作业账号，不把本机登录名当用户身份或TACC账号 |
| 依赖版本 | TACC requirements另有固定版本，与huoshan环境不等价 | 本版在课程环境重新做导入/完整软件/工具协议检查 |
| setup缓存 | 缓存标记只覆盖requirements文件 | tau2 pin或setup逻辑变动需明确重建，不能把旧venv误当新环境；现有force-setup不会无条件重建 |
| 数据与参考目标 | setup只准备四资产，不提供完整tau2源码审计清单 | 应用运行够用；重建target需完整固定源码，或直接交付冻结fixtures |
| 生命周期 | 活动SQLite默认/tmp，serve/agent有时限 | 结束前导出实际DB和轨迹；快照持久化、长批次调度另行落实 |

本次文档工作没有连接TACC、提交作业、安装共享依赖或修改这些部署脚本。当前代码在huoshan通过171项软件测试，不等于TACC 27B验收通过。

## 11. 交付验收顺序

1. 核对应用源码、固定tau2版本/四资产、已安装tau2实际导入位置和依赖版本。
2. 在TACC作业中验证模型名称、tool calling、工具结果续跑；需要规划/检查时再测JSON Schema。health成功不能替代这些检查。
3. 验证独立session、只读不改DB、写预览不改DB、批准只执行对应方案、拒绝不改DB、审批后续跑，以及finish后不能继续写入。
4. 验证新工具配置：基础目录16，tools_extended为18；health/episode manifest/实际绑定一致，额外工具只读且受客户隔离约束。
5. 私有eval通过同一HTTP链路运行少量完整episode并保存最终快照，再扩大固定任务集。检查输出可在作业结束后读取，缺快照不得算完整suite。
6. 核对浏览器使用 HttpOnly cookie、messages SSE 和 decisions JSON；eval token/target/参考动作不进入前端或 agent。内部 evaluator 使用 v2 路由，不能把 done 当整题成功。

实验效果与部署验收分开记录。模型、量化、thinking、交互确认模式、工具集合或模拟用户配置变化后，建立新的对照组，不拼接旧分数。

### Main 登录界面的数据准备

首次部署需要登录账户。注册只创建空客户，不继承 tau2 数据。若使用 main
登录页的六个演示账号，应在应用启动前，对单独的应用 DB 运行
`python -m scripts.seed_demo --apply`（先确认 RETAIL_DB_PATH 指向应用 DB；脚本会备份并更新演示清单）；AuthService 启动时
按 `DEMO_ACCOUNTS=1` 创建这些合成账号。不要对冻结 benchmark fixtures
执行 seed。生产式环境可设 `DEMO_ACCOUNTS=0` 并走注册或管理员开户流程。
