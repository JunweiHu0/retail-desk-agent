# 部署

两种模式，同一个应用，同一套代码：

| 模式                   | 用途                          | 命令                                 | 模型来源                                      |
| ---------------------- | ----------------------------- | ------------------------------------ | --------------------------------------------- |
| **local**        | 本地开发 / 免 Key 演示        | `./deploy/run.sh local`            | `.env` 里的 `AGENT_MODE`（默认 `demo`） |
| **local --prod** | 构建后单进程运行，最接近 TACC | `./deploy/run.sh local --prod`     | 同上                                          |
| **tacc**         | 平台测试 / 演示               | `./deploy/run.sh tacc up --tunnel` | TACC 上 vLLM 的 `qwen3.8-27b`               |

## 前置：每个人自己要做一次的事

代码和配置可以复用，但下面两样是**按账号**的，别人 clone 之后必须自己做一遍
（这些不写进脚本，也不能写进仓库）：

```bash
# 1) tcloud SDK：配置自己的 TACC 账号 + 私钥（私钥对应注册过的公钥）
tcloud config -u YOUR_USERNAME -f /path/to/your/private_key
tcloud init
tcloud ps                     # 能列出作业 = 配好了

# 2) SSH 私钥路径写进本地配置（隧道用）
cp deploy/tacc/env.example deploy/tacc/env
#   编辑 deploy/tacc/env：SSH_USER=你的账号  SSH_KEY=你的私钥
```

关于两个常见的 `export`：

| 导出                                  | 谁需要                                                          | 本仓库怎么处理                                                                                                                                      |
| ------------------------------------- | --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `export PATH=/path/to/tcloud:$PATH` | 课程 README 里的做法，**按终端**                          | 不需要：`deploy/tacc/lib.sh` 依次找 `TCLOUD` 变量 → `PATH` 里的 `tcloud` → `~/.local/bin`、`~/bin`、`~/tcloud`、`~/Downloads/*/quickstart-*/linux-amd64-*/tcloud` 等固定位置；全都不中就在 `env` 里写 `TCLOUD=/path/to/tcloud` |
| `source .../activate.sh`            | 只在**集群作业内部**需要（vLLM、runtime.sh、qwen-python） | 不需要你在 shell 里 source：三个 `job.sh` 启动时自己 source（路径可用 `QWEN_ACTIVATE` 覆盖）                                                    |

`deploy/tacc/env` 已被 gitignore，里面放的是个人账号和私钥路径，不会被提交。

## 本地（local）

```bash
cp .env.example .env          # AGENT_MODE=demo 即可，无需任何 key
./deploy/run.sh local         # API :8000（热重载）+ 前端 :5173
```

打开 http://localhost:5173 。

构建产物模式（单进程、同源、最接近 TACC 的样子）：

```bash
./deploy/run.sh local --prod  # = bash scripts/start.sh，打开 http://localhost:8000
```

接真实模型时，在 `.env` 里改成：

```dotenv
AGENT_MODE=live
MODEL_NAME=qwen3.8-27b
MODEL_API_KEY=EMPTY
MODEL_BASE_URL=http://<TACC 节点>:8000/v1   # 需先开隧道，见 deploy/tacc/README.md
```

## TACC（测试 / 演示）

前置见上一节「每个人自己要做一次的事」（`tcloud config` + `deploy/tacc/env`）。

```bash
cp deploy/tacc/env.example deploy/tacc/env    # 填 SSH 账号/私钥
./deploy/run.sh tacc up --tunnel              # 一键：依赖→vLLM→agent→隧道
./deploy/run.sh tacc status                   # 看作业、地址、健康检查
./deploy/run.sh tacc down                     # 只停自己的作业和隧道
```

`up` 会依次完成：

1. 检查 QOS 槽位（每用户最多 2 个运行中作业）；
2. 打包前端产物 + 后端代码到 `deploy/tacc/.stage/agent/app`；
3. 提交依赖作业 `retail-setup`（已就绪则几十秒内 `SETUP_SKIP`）；
4. 提交 vLLM 作业 `retail-serve`，等到 `Application startup complete`；
5. 提交 agent 作业 `retail-agent`，等到 `RETAIL_READY` 并读出节点地址；
6. `--tunnel` 时在本地开 `127.0.0.1:8080` 转发。

失败处理（节点显存被别人占用导致 CUDA OOM）已经内置：`up` 会从日志里读出节点名，
把它加进 `exclude` 后重提一次，**不会去动别人的作业或进程**。

细节、排错表、时限与合规说明见 [`tacc/README.md`](tacc/README.md)。

## 跑评测

```bash
./deploy/run.sh tacc up --serve-only
EVAL_NAME=test40 ./deploy/run.sh tacc eval --agent bare --task-ids 5,9,12 --user-model openai/qwen3.8-27b
```

`EVAL_NAME` 是 checkpoint 目录名。任务跑完一个就落盘，作业被砍后同名重提会跳过已完成的；
但 **tau2 不允许换任务集后复用同名**（会报 `cannot resume changed language/task/persona content`），
所以换一批任务就换一个名字，最后合并结果。

## 看 infra：/infra 面板

应用自带一个 infra 页面，和 agent 同一个端口，不需要额外开作业或端口：

- 本地：`http://127.0.0.1:8000/infra/`
- TACC：走已有的隧道，`http://localhost:8080/infra/`

页面分两块：上半屏是 vLLM 引擎的实时序列（服务端每 2 s 采样 `/metrics` 并算窗口增量，
所以能看到 **TPOT**、解码吞吐、TTFT、排队、KV 占用和前缀命中率）；下半屏是每次进程运行的
落盘记录（`turn → model call → tool call`），用来对比两次配置。

运行记录默认写到 `runtime/infra/<run_id>/`；TACC 上写在
`$TACC_USERDIR/retail-agent/infra/<run_id>/`，作业结束后仍可回看。要换位置就设 `INFRA_DIR`。

## 目录

```
deploy/
├── run.sh            # 模式分发：local | tacc
└── tacc/
    ├── README.md     # TACC 部署 SOP（完整版）
    ├── env.example   # 本地配置模板（复制成 env，不提交）
    ├── up.sh         # 一键启动
    ├── status.sh     # 状态 / 健康检查
    ├── down.sh       # 停止（只动自己的）
    ├── tunnel.sh     # SSH 转发
    ├── setup/        # 依赖作业（venv.tgz + retail 数据）
    ├── serve/        # vLLM 作业（开启 tool calling）
    └── agent/        # 应用作业（FastAPI + 前端 dist）
```

`.run/`（作业号、地址、隧道 pid）和 `.stage/`（提交用的打包目录）都是生成物，已 gitignore。

## 账号与业务接口

当前 cookie/auth/order API 与 main 对齐，见 [项目说明](../README.md)。
浏览器审批返回 JSON，内部 evaluator 审批返回 SSE。使用子路径时 APP_BASE_PATH
和前端 Vite base 应保持一致。
