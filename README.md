# Retail Desk — 业务操作与最终数据库评测

Vue 3 + FastAPI 零售客服沙盒。Agent 通过官方 tau2 Retail 工具查询数据、生成修改预览，在用户确认后提交真实的沙盒数据库变更。浏览器会话按登录账号归属，订单与资料共享持久化业务数据；评测 episode 使用独立 DB。

当前默认 agent 是 **B1：政策全文 + 原生工具调用循环 + 会话历史**。`state`、`errors`、`guide`、`enhanced` 是可单独比较的增强配置；尚未经过真实模型评测的配置不代表已获得性能提升。`guide` 初始内容来自公开政策，不能称为训练轨迹学习结果。

`state` 增加任务状态记录，并按 action ID 将实际执行/拒绝回执合入对应工具观察，解除已完成确认的暂停提示；原始审计轨迹保留。`errors` 为工具错误附加已观察到的相关信息，`guide` 注入冻结操作指南，`enhanced` 同时启用三项。默认指南为 `backend/guides/retail_seed.md`，来源标记为 `policy_seed`。后端可通过 `AGENT_GUIDE_PATH` 指定开发集产生的指南文件；每个 episode 记录实际内容 SHA256，自定义文件默认标记为未核实来源。指南版本、开发来源及冻结要求见 [指南说明](backend/guides/README.md)。

已有 huoshan 的 Qwen3.5-9B 功能实验和软件验证；不同候选、工具配置及批次的成绩与限制统一记录在[验收记录](docs/VERIFICATION.md)，不能用小样本功能检查替代正式评测。当前分支尚未完成 TACC 27B 部署验收。

## 入口与文档

- [后端与 Agent 说明、最小部署模块与 TACC 交接](docs/BACKEND_AGENT.md)
- [实施计划与阶段状态](docs/PLAN.md)
- [前后端 / evaluator 协议](docs/EVAL_PROTOCOL.md)
- [正式评测前的具体对齐问题](docs/EVAL_ALIGNMENT.md)
- [huoshan 部署与验证](docs/huoshan.md)
- [实际验收记录](docs/VERIFICATION.md)
- [原有 TACC 部署](deploy/tacc/README.md)

源码从 `deploy/tacc` 的 `a3173371079b53779a933e50ed79d528b7843a96` 开始。tau2 固定为 `0c69df456a96aa76a1162591574dad9c427a34d7`，同级 `../tau2-bench` 或通过 `TAU2_ROOT` 指定源码与数据。

`c1` 是新增的实验候选：显式提取需求、展开多订单任务、按真实回执结算、校验写操作与任务约束。规划和修复调用计入同一预算，B1 仍为默认。C1 的真实模型效果以验收记录为准；它需要支持 JSON Schema 的模型服务。

`c2` 在 C1 上增加有界的回复前完成检查，优先消除参数已齐全时的额外聊天确认；缺少用户选择时继续提问，业务写入仍必须经卡片批准。C1/C2 的规划与检查成本分阶段记录，均计入公共预算。

## 业务流程

1. 通过 main 的 cookie 登录创建账号所属会话，或从订单/个人资料页发起操作。
2. 发送消息；后端调用模型，执行一个业务工具，将结果交回模型继续决策。
3. 写工具先在副本上预演；页面显示具体商品、支付/退款及修改前后信息。
4. 通过确认卡批准或拒绝；只有后端执行回执才证明数据库已改变。
5. 浏览器确认返回 JSON 回执和会话状态；下一条消息继续对话。内部评测确认仍以 SSE 自动续跑 agent。

聊天文本中的“yes”不代替确认接口。刷新页面会恢复会话和待确认操作。工具进度通过 SSE 展示，正文在本轮完成后展示；不将进度事件称为 token 流。

## API

公共 API 与 `origin/main@f3d9765` 对齐：使用 `retail_auth` HttpOnly cookie，支持 `APP_BASE_PATH`。浏览器不接收 session token，也不能凭 Bearer 绕过登录。

| 方法 | 路径 | 内容 |
| --- | --- | --- |
| GET | `/api/health` | 模式、模型配置、工具数、可用变体 |
| POST | `/api/auth/register`、`/api/auth/login`、`/api/auth/logout` | 注册、登录、退出 |
| GET | `/api/me`、`/api/orders`、`/api/orders/{oid}` | 当前客户资料与订单 |
| POST | `/api/orders/{oid}/actions`、`/api/me/address` | 创建待审批操作，返回 session |
| GET | `/api/samples` | 当前登录客户订单示例 |
| GET | `/api/sessions` | 当前账号历史会话 |
| POST | `/api/sessions` | 无请求体，创建当前账号的 B1 会话，返回 id 等信息，不含 token |
| GET | `/api/sessions/{id}` | 消息、订单、pending、真实回执、状态和 usage |
| POST | `/api/sessions/{id}/messages` | `{message}`，返回 SSE |
| POST | `/api/sessions/{id}/decisions` | `{action_id, approve}`，返回 JSON `{receipt, session}`，不额外调用模型 |

评测创建/快照/结束使用独立的 `EVAL_API_TOKEN`；未配置时无法创建评测。评测消息/审批使用创建时返回的 episode token，仅访问内部路由。

| 方法 | 路径 | 内容 |
| --- | --- | --- |
| POST | `/internal/eval/episodes` | 公开初始 DB、客户、variant、task/trial/seed |
| POST | `/internal/eval/episodes/{id}/messages`、`/internal/eval/episodes/{id}/decisions` | episode Bearer token；SSE，共用 agent/工具执行器 |
| POST | `/internal/eval/episodes/{id}/finish` | `{reason}`，冻结并导出状态 |
| GET | `/internal/eval/episodes/{id}/snapshot` | 完整实际 RetailDB、会话与运行 manifest |

`done` 只代表本轮结束；任务完成状态和最终 DB 评分由独立 evaluator 处理。接口不能接收 target DB。私有评测 metadata 不进入模型上下文。

## 模式与运行

`AGENT_MODE=demo` 使用确定性模型，仅供软件验证，不产生有效模型 benchmark 成绩。`live` 使用 `MODEL_BASE_URL`、`MODEL_NAME`、`MODEL_API_KEY` 配置的 OpenAI-compatible 工具调用服务，凭据只保留在后端。

本机仅做轻量开发和小测试。完整服务、测试套件、目标重放及真实模型评测在 huoshan 运行，命令见部署文档。应用使用独立 Python 3.12 环境；不要更改共享环境。

```bash
uv sync --frozen --python 3.12
uv run --frozen python -m pytest tests/test_reference_eval.py -q
cd frontend
npm ci
npm run build
```

完整验证：后端 pytest、Ruff、前端类型构建、Playwright 浏览器场景，以及经同一 HTTP 路径的 evaluator 闭环。执行位置、规模和结果记录在实验报告；可控模型测试不表示真实 Qwen 通过率。

## 评测口径

参考 evaluator 入口是 `python -m benchmarks.run_http`，支持 `build-targets`、`run`、`compare`、`analyze` 和只读 `audit-reference`。预设已核验客户与其订单，比较该客户完整对象及其全部初始订单与目标状态。身份发现不计分，结果应称为 **适配后的 Retail HTTP DB 评测**。

开发54、验证20来自官方 train74；test40 全部保留。首轮 smoke8 各运行一次；正式对比 B1 与冻结候选，各执行 test40 × 3。目标和评分范围只存在于 evaluator，不能传给 agent 或用户模拟器。有效 DB 在预算/错误截止后仍按约定比较；缺快照则报告 suite 未完成。

私有开发诊断可运行 `python -m benchmarks.run_http analyze --run RUN_DIR --output FRESH.json`，汇总主尝试的逐任务结果、终止原因、DB 不匹配类别、重复失败工具调用和用户拒绝次数。仅 development 输出标记为 guide feedback 可用；validation/test 输出不得用于学习或更新 guide。该命令不调用 LLM，不自动学习。

固定 pin 的全114题只读审计确认两个无状态变化的参考 WRITE 异常（task64/action64_6、task105/action106_0）。构建器仅精确允许这两个已审计异常，随后继续参考动作；未知 WRITE 异常仍中止。task105 保留初始 DB 目标及私有 `reference_issue` 标签，任务不删除、分母不变；本适配指标只评 DB，不声称该题 NL assertion 通过。审计证据与异常冻结规则见协议。

原有 `benchmarks/run_retail.py` 与 `tau2_agent.py` 保留作原生 tau2 适配兼容入口，其环境独立于网页 DB，不能用其分数代表新的 HTTP 后端链路。

## 数据与使用范围

全部客户、订单、支付数据均为公开合成沙盒数据。业务写入不会连接真实商户、支付或邮件服务。保留原始 tau2 数据，实验输出使用独立目录，并记录源码、数据、policy/guide 摘要及完成状态。

真实 Qwen 服务可通过 `MODEL_THINKING=auto|on|off` 选择思考模式（默认 `auto`，沿用服务模板）。显式设置会发送 `chat_template_kwargs.enable_thinking`；服务需支持该参数。评测必须传相同的 `--thinking`，preflight 会检查 agent 与 simulator 一致，配对报告拒绝混用设置。huoshan 当前 9B 功能验证使用 `off`，原因是已复现当前 thinking/parser 组合在工具续跑时返回空 `tool_calls`；具体原始响应见验收记录。单次模型 HTTP 请求上限为 300 秒，episode 仍以 600 秒为预算。

`lean` 是后续消融候选：保留原生工具循环、真实回执投影和审批，省去强制规划/检查调用；同一轮同一读取及结果重复三次后，限制为一次文本回答或澄清。它目前仅完成软件验证，不代表已获得模型成功率提升；正在运行的 development54 对照仍使用已冻结的 B1/advisory 版本。

后端工具接口实验通过内部评测创建请求的 `variant` 字段选择：`tools_described`（16工具，改进描述）、`tools_structured`（16工具，统一只读结果格式）、`tools_extended`（18工具，增加当前客户订单商品筛选和产品款式筛选）。三个配置共用B1执行循环，写入仍使用官方工具与原审批层。前端无需新增页面；API契约、比较口径见 `docs/EVAL_PROTOCOL.md`。这些是独立工具实验，尚无成功率提升结论。
