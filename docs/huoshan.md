# huoshan 部署与验证

本机仅编辑、小 case 和静态检查；完整测试、服务和评估在现有 `ssh huoshan` 上执行。当前先验收 Qwen3.5-9B；后续 27B 是独立模型组，计划名称 Qwen3.8-27B 的准确仓库、权重与服务尚待核实。依赖安装、CPU demo、真实模型 HTTP 协议和 smoke8 必须分别记录，不能互相替代。

## 目录与资源

远程根目录默认 `/vePFS/han/retail-desk`：

| 路径 | 内容 |
| --- | --- |
| `releases/<时间-SHA>/retail-desk-agent` | 每次同步的应用源码快照 |
| `releases/<时间-SHA>/tau2-bench` | 固定 tau2 上游源码和原始数据 |
| `current`、`app`、`tau2-bench` | 当前 release 及两个源码目录的符号链接 |
| `envs/app`、`envs/inference` | 独立 Python 3.12 应用、推理环境 |
| `cache`、`tmp` | uv、HF、torch、Triton、CUDA、npm 缓存及安装临时文件 |
| `runs` | 不覆盖历史的服务/安装日志、有效配置、完成状态和 episode 导出 |
| `state` | 本任务进程记录、权限 0600 的评估 token |

活动 SQLite 使用 `/dev/shm/retail-desk-<uid>/<run>/retail.sqlite3`，避免在共享文件系统上运行活动数据库。已实查该 node-local tmpfs 总量 325GB、空闲 304GB；`/tmp` 与仅余 4.4GB 的根盘共用文件系统。后端通过 `RETAIL_ARTIFACT_DIR=<run>/episodes` 持久导出已完成 episode；节点内存盘不承担跨节点重启的持久保存责任。停止进程不会删除源码、数据库或结果。

2026-11-17 初次实际检查：2 × A100-SXM4-80GB，kernel driver `535.129.03`，Python `3.12.3`，uv `0.11.6`，glibc `2.39`。GPU0 当时占 61,236 MiB，GPU1 占 12,076 MiB；两卡都有既有计算进程，**没有独占空闲 GPU**。根盘仅余约 4.4GB，`/vePFS` 余约 1.5TB（会变化）；新增依赖和缓存均放 `/vePFS/han/retail-desk`。现成权重 `/vePFS/models/Flora/qwen3.5-9b` 保持只读。

## 同步与安装

从本机仓库执行，`TAU2_ROOT` 默认指向相邻 `../tau2-bench`；同步前核对其 HEAD 为 `0c69df456a96aa76a1162591574dad9c427a34d7`：

```bash
bash deploy/huoshan/sync.sh
ssh -o ClearAllForwardings=yes huoshan \
  'bash /vePFS/han/retail-desk/app/deploy/huoshan/setup.sh app'
ssh -o ClearAllForwardings=yes huoshan \
  'bash /vePFS/han/retail-desk/app/deploy/huoshan/setup.sh inference'
```

同步创建新 release，排除 `.git`、`.env`、运行数据库、虚拟环境和 node_modules；保留本地改动后的实际源码。`source-manifest.json` 同时记录上游 SHA、dirty 状态、diff hash 和实际复制文件的完整快照 hash。应用使用仓库 `uv.lock` 的 `uv sync --frozen` 和 `npm ci`，安装阶段构建前端。推理固定 `vllm==0.17.1`、CUDA 12.8 PyTorch wheels，最终安装清单保存在各 setup run 的 `packages.txt`。

应用和推理环境互相独立，不继承默认 Python3.10 的 torch/transformers。安装与 CPU import 成功只能证明依赖可导入，不能证明 CUDA kernels 或 Qwen 推理成功。

`env.sh` 默认设置 `LITELLM_LOCAL_MODEL_COST_MAP=True`，使用锁定安装包自带的成本映射，避免每次 import 为获取价格表发起网络请求。其余真实模型 HTTP 请求仍按明确配置执行。

## 运行与停止

所有命令在远端调用同一 `run.sh`。两个端口固定绑定 localhost，冲突就退出，不抢占或自动杀现有服务：

```bash
# CPU 软件验收必须显式选择 demo；不是实模或 benchmark 结果。
ssh -o ClearAllForwardings=yes huoshan \
  'bash /vePFS/han/retail-desk/app/deploy/huoshan/run.sh start-app --mode demo'

# 默认 GPU1；检查有进程/显存占用就拒绝启动，不清场。
ssh -o ClearAllForwardings=yes huoshan \
  'bash /vePFS/han/retail-desk/app/deploy/huoshan/run.sh start-model --gpu 1'

# 已明确授权的有限共卡 smoke profile，最多分配整卡 35% 显存。
ssh -o ClearAllForwardings=yes huoshan \
  'bash /vePFS/han/retail-desk/app/deploy/huoshan/run.sh start-model --gpu 1 --shared-budget 0.35'

# 实模通过 /v1/models 后才启动 live 应用。
ssh -o ClearAllForwardings=yes huoshan \
  'bash /vePFS/han/retail-desk/app/deploy/huoshan/run.sh start-app --mode live'

ssh -o ClearAllForwardings=yes huoshan \
  'bash /vePFS/han/retail-desk/app/deploy/huoshan/run.sh status'
ssh -o ClearAllForwardings=yes huoshan \
  'bash /vePFS/han/retail-desk/app/deploy/huoshan/run.sh stop app'
ssh -o ClearAllForwardings=yes huoshan \
  'bash /vePFS/han/retail-desk/app/deploy/huoshan/run.sh stop model'
```

应用是 `127.0.0.1:18881`，模型是 `127.0.0.1:18880/v1`。`start-app` 默认为 live；不会把模型不可用自动降级成 demo。demo 与 live 状态写入 run manifest。若 demo 正运行，先 `stop app` 再启动 live。`status`、`stop app|model|all` 只处理本任务记录的 PID；使用 boot ID 和进程启动时间验证所属进程，停止该进程组，不使用全局 pkill、进程名匹配或 kill-all。

推理参数：单卡 BF16、纯文本、32,768 context、最多 1 条并发、4096 batched tokens、eager 模式、`qwen3` reasoning parser 和 `qwen3_coder` tool parser。默认 GPU memory utilization 0.60，要求 GPU 无计算进程且其他显存占用不超过 100MiB。有限共卡 smoke 必须显式传 `--shared-budget 0.35`；预检要求空闲显存至少为整卡 35% 加 8GiB，记录全部既有计算进程，不停止其他任务，不尝试更高预算。此检查不提供调度器级资源预留，资源变化时应停止本任务自己的进程。

535 驱动配合 `/usr/local/cuda-12.8/compat/libcuda.so.570.86.10`，仅在模型进程的 `LD_LIBRARY_PATH` 前置已有兼容库，不改系统库、共享环境或 kernel driver。Qwen3.5 官方 recipe 要求 vLLM ≥0.17.0，推荐上述两个 parser；CUDA compatibility 的可行性必须通过实际 GPU kernel 和模型请求验收，不从文件存在或 import 成功推断。

浏览器访问使用单独隧道，只监听本机地址。`ClearAllForwardings` 同时会清除命令行 `-L`，所以仅用于上述读写命令；建立隧道时，从现有 `ssh huoshan` 的有效配置生成临时配置，仅去掉已有转发，保留真实地址、用户、端口和密钥设置：

```bash
python3 - <<'PY'
import subprocess, tempfile
config = subprocess.check_output(['ssh', '-G', 'huoshan'], text=True)
config = '\n'.join(line for line in config.splitlines()
                   if line.split()[0] not in {'localforward', 'remoteforward', 'dynamicforward'})
with tempfile.NamedTemporaryFile(mode='w+') as file:
    file.write(config + '\n')
    file.flush()
    subprocess.run(['ssh', '-F', file.name, '-o', 'ExitOnForwardFailure=yes', '-N',
                    '-L', '127.0.0.1:18881:127.0.0.1:18881', 'huoshan'], check=True)
PY
```

评估 token 由应用启动器生成后保存在远端 `state/eval-token`，也可通过远端私有环境变量 `EVAL_API_TOKEN` 指定；不要复制进文档、终端输出、模型输入或提交。manifest 只记录 token 已配置与否。

## 验收证据边界

部署成功需要分别保存以下实际证据：CPU 依赖/前端构建和测试；应用 demo HTTP 流程；空闲 GPU 上 CUDA kernel 与模型启动；真实工具调用和 reasoning 协议；live HTTP smoke8。`/v1/models` 健康本身不等于工具调用协议通过，更不等于 episode 成功。

首次准备阶段已验证本机脚本语法、Python 编译和空 PID 状态查询；远端两个 Python3.12 venv 已创建。应用前置 116 个锁定依赖已安装，`fastapi/deepagents/langchain_openai` import 通过，包清单保存在 `runs/preparation-20261117/app-prerequisites-packages.txt`；此检查尚未包含 tau2 和应用源码安装。实际执行模型启动预检返回 `GPU 1 is occupied (12076 MiB, 2 compute processes); no model was started`。推理依赖安装及后续测试的最终结果以远端 setup 日志、service 状态和项目验证记录为准。此时没有运行 9B 推理，也没有 9B smoke8 成绩。test40×3 和最终 27B 对比均尚未执行。

随后同步快照 `20261118T021402Z-a317337-503934`，在 huoshan 用锁定应用环境安装固定 tau2 editable 并完成源码 import。原始 `a317337` 的干净 git archive 基线完整测试为 **18 passed**（17.82s）；该开发快照为 **53 passed、2 failed**（36.32s），失败分别是旧决策接口测试仍按 JSON 读取 SSE、episode context 订单排序断言。ruff 检出 `backend/infra.py` 的 unused `Path` import。此轮完整日志和退出码在 `runs/software-20261118T021402Z-a317337-503934`；这些问题由各模块在新源码快照修复后重新验证，不能把首次结果写成全绿。

修复后的 `20261118T022622Z-a317337-530701` 快照在 huoshan 完整测试 **66 passed**（40.62s），ruff 通过；`build-targets --split smoke` 生成全部 8 个冻结参考 fixture，`complete.json` 为完成状态。日志和 fixture 保存在 `runs/software-20261118T022622Z-a317337-530701`。这些是软件和参考目标生成验收，尚不是模型 smoke8 成绩。

后续最终业务快照 `20261118T023129Z-a317337-543062` 在 huoshan 完整测试 **72 passed**（43.35s），ruff 与 36 个 Python 文件格式检查通过。参考目标 validation20 完整；development 在 task105、test 在 task64 遇参考写操作失败而中止，对应目录没有 `complete.json`，不能声称 114 个目标已冻结完成。失败原文和退出码位于该快照的 `runs/software-20261118T023129Z-a317337-543062/targets-*.log`，交由评估模块核对官方初始化流程。

同一业务快照启动显式 **demo** 应用，`software_smoke` 的取消确认与退货拒绝两项 HTTP 合约检查通过；预执行无副作用和完成 DB 比较均通过。Playwright 的桌面 SSE 确认/刷新/episode 隔离、移动端 SSE 拒绝/刷新两项测试 **2 passed**（10.6s）。日志和浏览器产物保存在上述 software run 的 `software-smoke`、`playwright.log`、`playwright-artifacts`。应用 run 为 `app-20261118T023726Z-049d5e`，SQLite 实际位于 `/dev/shm`。这些都是确定性软件验收，不计入真实模型 DB success。

114 任务完整参考审计位于 `runs/reference-audit-20261118T024107Z-a317337-579751/audit.json`（SHA256 `46024e9396dd7076e021e6b0cae2705fcbcad898080e2728958c5e91cc15b751`）。全部 18 个失败动作（16 READ、2 WRITE）前后完整 DB 哈希相同。评估模块仅为两个已审计的 WRITE 加入工具、参数、错误和无状态变化的精确例外；未知 WRITE 仍中止。此后 `20261118T024844Z-a317337-599076` 在 huoshan **107 passed**（44.26s），ruff、39 文件格式检查通过，development54/validation20/test40 均在新目录重新生成并带完整 `complete.json`。证据位于 `runs/software-20261118T024844Z-a317337-599076`，早期不完整目录保持原状。

最后 handoff 文案修复后的快照 `20261118T025435Z-a317337-610915` 定向验证 **2 passed**（2.83s），ruff/格式检查通过，显式 demo 的两项软件 HTTP 检查再次通过，smoke8 参考目标完整重建。证据在 `runs/final-focus-20261118T025435Z-a317337-610915`；其中 `code-manifest.json` 覆盖 56 个源码、构建产物和 lock 文件，canonical map SHA256 为 `1f7fba2c1da79394c5f9b711f3dd6a8e7e41fcc3f3c7de49ff5c263b4aa3646e`。新 demo 应用 run 为 `app-20261118T030226Z-9324ac`。

9B 全量权重摘要位于 `runs/model-manifest-20261118T025749Z/model-manifest.json`（文件 SHA256 `e89065e31994497a26df01e31f7a9b338cb920347e5ad1bf8820b89ac79ed403`）。四个分片的实际 SHA256 全部匹配现有 HF download metadata 的 LFS digest，metadata commit 为 `c202236235762e1c871ad0ccb60c8ee5ba337b9a`；另记录 config、index、tokenizer、tokenizer_config、chat_template、vocab 和 README 摘要。此摘要只证明实际输入版本，不能替代 CUDA 或模型功能验收。

参考：[vLLM Qwen3.5-9B recipe](https://recipes.vllm.ai/Qwen/Qwen3.5-9B)、[vLLM 0.17.1 安装](https://docs.vllm.ai/en/v0.17.1/getting_started/installation/gpu/)、[NVIDIA CUDA forward compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/forward-compatibility.html)。
