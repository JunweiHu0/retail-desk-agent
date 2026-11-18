# 在 TACC 上跑 Retail Desk Agent

> 本目录脚本配置目标：CSIT6000V 平台、`tacc` 分区、课程 vLLM 环境及 `Qwen3.8-27B-AWQ-INT4`。原分支的部署记录不代表当前后端/agent/eval 已在 TACC 重新验收。
> **先读 [后端与 Agent 说明](../../docs/BACKEND_AGENT.md)**：其中列出最小部署模块、tau2 包与数据的区别、无前端运行方式，以及本部署助手尚未接入的新评测交接项。当前 `up.sh` 仍强制准备前端 dist，且未打包 benchmarks/源码清单，不能直接视为新 DB-only 评测的一键部署。
> 项目入口见 [`../../README.md`](../../README.md)。

## 1. 一条命令

```bash
cp deploy/tacc/env.example deploy/tacc/env   # 填 SSH_USER / SSH_KEY
./deploy/run.sh tacc up --tunnel
```

`up.sh` 依次做四件事，任何一步失败都会打印对应的 `slurm_log/...` 和你该看的行：

| 步骤 | 作业             | 成功标志                                  | 失败标志                          |
| ---- | ---------------- | ----------------------------------------- | --------------------------------- |
| 依赖 | `retail-setup` | `SETUP_DONE`（已装过则 `SETUP_SKIP`） | `IMPORT_FAILURES n`             |
| 模型 | `retail-serve` | `Application startup complete.`         | `out of memory`                 |
| 应用 | `retail-agent` | `RETAIL_READY`                          | `PORT_BUSY` / `SERVER_EXITED` |
| 隧道 | 本地 `ssh`     | `/api/health` 返回 `"ok"`             | ssh 立即退出                      |

停止：

```bash
./deploy/run.sh tacc down     # 只取消自己这套作业 + 关隧道
```

## 2. 架构

```
浏览器 http://localhost:8080
  └─ SSH 转发 <你>@gw.turing.ust.hk:30041
       └─ retail-agent 作业 :8787   FastAPI + 原生 agent 循环 + 前端 dist
            └─ POST /v1/chat/completions（native tool call）
                 └─ retail-serve 作业 :8000   vLLM
                      └─ Qwen3.8-27B-AWQ-INT4
```

三个作业各自独立提交，靠 `$TACC_USERDIR/retail-agent/` 里的两个产物串起来：

```
server-url.txt    serve 启动时写自己的 http://<ip>:8000/v1，退出时删掉
venv.tgz          依赖包（一个文件，不是目录树）
tau2-bench/       tau2 retail 的 db.json / policy.md / tasks.json
```

agent 启动时读 `server-url.txt` 并 `GET /v1/models` 探活：通就 `AGENT_MODE=live`，
不通就退回 `demo` 并打 `WARN`（UI 能开，但回答不是真模型）。

## 3. 依赖作业为什么这么装

直接 `pip install` 到 `$TACC_USERDIR`（NFS）会写几千个小文件，实测 30 分钟的作业
上限内装不完。所以：

1. 在节点本地 `/tmp` 建 venv 安装；
2. 整个 venv `tar.gz` 成一个文件写回 NFS；
3. agent 作业启动时解压到 `/tmp/retail-venv-<jobid>`。

`setup/job.sh` 用 `requirements.txt` 的 sha 做标记（`venv.stamp`），pin 的版本没变
就直接 `SETUP_SKIP`，几秒钟结束；改了 `requirements.txt` 才会重建。

**tau2 必须从 GitHub 装**（`requirements.txt` 注释里写了原因）：PyPI 上的 `tau2`
是同名的材料科学包，装错了 `from tau2.domains...` 会直接 ImportError。另外 tau2
的导入链会 `import litellm`，所以即使代码里不直接用它，也必须装在 venv 里——
`up.sh` 的 `IMPORT_FAILURES` 检查会挡住这类问题。

## 4. vLLM 为什么要自己起，而不是用课程 `serve.sh`

课程 `serve.sh` 的原记录未开 tool calling。应用原生工具循环每轮请求都带 `tools`，vLLM 会回
400（`auto tool choice requires --enable-auto-tool-choice and --tool-call-parser`）。`serve/job.sh` 复制了 `serve.sh` 的全部参数，只加：

```bash
--enable-auto-tool-choice --tool-call-parser qwen3_xml
```

选 `qwen3_xml`：该模型 chat template 是 XML 风格
（`<tool_call><function=name><parameter=x>value</parameter></function></tool_call>`），
vLLM 0.26 里 `qwen3_xml` 与 `qwen3_coder` 指向同一个 `Qwen3EngineToolParser`。
换模型时可以改 `TOOL_PARSER`（env 文件里有）。

旧课程容器脚本还使用了以下设备映射：

```bash
export CUDA_VISIBLE_DEVICES=0,1
```

原分支记录过缺少该映射时的 `NVMLError_InvalidArgument`。当前部署须先核对 Slurm 分配与课程容器的 CUDA 枚举，不能将 `0,1` 当成任何节点都适用的物理 GPU 编号。

## 5. 提交前先看目标节点

Slurm 只看 GPU 有没有被**自己**占，不看显存是不是已经被别人的常驻进程吃掉。
直接提 `--gpu-memory-utilization 0.90` 的作业，落到脏节点就会 CUDA OOM。

`up.sh` 的处理是自动的、且不越界：

1. serve 日志打 `NODE=10-0-1-11`；
2. 失败且日志含 `out of memory` / `Engine core initialization failed`；
3. 把这个节点写进 `.run/exclude`，重新渲染 `tuxiv.conf` 的 `exclude=` 再提，
   最多 3 次。

**它不会 cancel 别人的作业，也不会 kill 别人的进程**——只换节点。
已知要长期避开的节点可以直接写进 `deploy/tacc/env` 的 `EXCLUDE`。

serve 日志里还有两段诊断，出问题时先看：

```
PORT_CHECK_BEGIN ... PORT_8000_FREE / 谁在监听 ... PORT_CHECK_END
GPU_CHECK_BEGIN
0, xxx MiB, 24576 MiB        ← 提交那一刻显存被占了多少
GPU_CHECK_END
```

## 6. 端口与地址

- serve 默认 `8000`；当前 job.sh 在端口占用时会继续尝试后续端口，以 `server-url.txt` 和服务日志发布的地址为准。
- agent 默认 `8787`：8080 在共享节点上经常被别人占。`job.sh` 启动前用 `ss` 检查，
  占用就打印 `PORT_BUSY` 退出。`up.sh` 会重提并增加本地端口变量，但当前尚未将该值注入远端作业的 `PORT`；部署交接需补齐，不能假定重提后端口已经改变。
- 节点名是 `10-0-1-11`，互相访问要用 `10.0.1.11`；`job.sh` 用 `hostname -I` 取 IP，
  `up.sh` 读日志拿地址，不用手抄。

## 7. 验证

```bash
curl -s http://localhost:8080/api/health
# {"status":"ok","mode":"live","model":"qwen3.8-27b","model_ready":true,"tools":16,"domain":"retail"}
```

`mode` 必须是 `live`。

真实一轮对话（SSE）：

```bash
S=$(curl -s -X POST http://localhost:8080/api/sessions)
SID=$(printf '%s' "$S" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
TOK=$(printf '%s' "$S" | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')
curl -sN -X POST "http://localhost:8080/api/sessions/$SID/messages" \
  -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d '{"message":"你好，帮我查订单 #W5918442 的状态"}'
```

期望事件序列：`status` → `tool_start` → `tool_end` → … → `done`。

只验证模型侧的 tool calling（不经应用）可以 `cd deploy/tacc/serve` 起作业后，
用同一个 venv 发一个带 dummy tool 的请求，看 `finish_reason=tool_calls`。

## 8. 时限与并发

| 项          | 值                             |
| ----------- | ------------------------------ |
| 分区 / 时限 | `tacc`，`MaxTime=01:00:00` |
| 每用户并发  | 2 个运行中作业（QOS）          |
| 本方案      | setup（一次性）+ serve + agent |

`up` 会先数你自己的运行中作业，已有 2 个就拒绝提交。serve 先起、agent 后起，
到点后 Slurm 直接收；要继续演示就再跑一次 `up`（`venv.tgz` 会 `SETUP_SKIP`）。

## 9. 排错

| 现象                            | 原因                                         | 处理                                                 |
| ------------------------------- | -------------------------------------------- | ---------------------------------------------------- |
| `NVMLError_InvalidArgument`   | 缺 `CUDA_VISIBLE_DEVICES=0,1`              | 别删 `serve/job.sh` 里那行                         |
| `CUDA error: out of memory`   | 节点有别人的常驻进程                         | `up` 会自动 exclude 重试；**别动别人的进程** |
| `PORT_BUSY 8787`              | 节点上端口被占                               | `up` 自动换端口；或改 env 的 `AGENT_PORT`        |
| `MODE=demo`                   | 启动时 vLLM 未就绪 / `server-url.txt` 过期 | serve 就绪后 `down` + `up`                       |
| `Missing venv.tgz`            | setup 没跑或失败                             | `./deploy/run.sh tacc up`（会先跑 setup）          |
| 前端能开、回答报错              | agent 到 vLLM 不通                           | 看 agent 日志 500 前的堆栈                           |
| 日志有 `Traceback` 但服务正常 | vLLM 导入期 WARNING（flashinfer/flash-attn） | 以 `Application startup complete.` 为准            |
| 作业 `PD (Resources)`         | GPU 被占 / QOS 满                            | 等，不要抢                                           |
| `tcloud not found`            | SDK 不在 PATH                                | env 里设 `TCLOUD=/path/to/tcloud`                  |

## 10. 合规

课程 README 要求 **client calls must run inside a platform job**。这里 agent 本身
就是平台作业，模型调用发生在作业内部；SSH 端口转发只用于把浏览器指到作业上，
而它不在课程文档里——正式演示前先跟 TA 确认这一条。

## 11. 清理

```bash
./deploy/run.sh tacc down        # 停自己的作业和隧道
```

`$TACC_USERDIR/retail-agent/`（venv.tgz、tau2 数据）会保留，下次 `up` 直接复用。
`.run/`、`.stage/` 和 `deploy/tacc/env` 都在 `.gitignore` 里，不会被提交。
