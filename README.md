# Retail Desk

Vue + FastAPI 零售客服。模型通过 tau2 Retail 工具查询订单、生成修改预览；用户批准后，后端调用官方写工具修改数据库。

## 项目结构

```text
backend/               认证、API、agent、工具与 SQLite
  main.py              main 的 cookie/auth/order API；SSE 消息与 JSON 审批
  auth.py              账号、密码哈希、登录 cookie 与退出
  agent.py             B1 原生工具循环及运行器入口
  graph_agent.py       LangGraph 每轮执行图
  graph_profiles.py    候选配置
  graph_context.py     上下文整理、业务指引、需求笔记与检查
  retail.py            官方工具、权限校验、预览、实际提交与回执
  store.py             账号会话及隔离评测 DB
  tool_profiles.py     工具描述、返回格式与两个只读助手
frontend/              main 前端及浏览器测试
benchmarks/             HTTP 评测、冻结目标、最终 DB 比较
scripts/               本地启动及合成演示客户初始化
tests/                 当前实现的回归测试
deploy/tacc/           TACC 环境、作业、打包和隧道
web/infra/             TACC 可用的运行诊断页面
```

历史 agent、研究文档、非 TACC 部署工具和实验产物不属于应用发布包。
默认数据库、快照和运行日志位于仓库外的同级 `retail-desk-data/`；可通过环境变量覆盖。

## Agent 执行流程

```text
用户消息 → 读取身份/历史/回执 → 模型决策
  ├─ 查询工具 → 保存观察 → 继续决策
  ├─ 修改工具 → 生成待审批预览 → 结束本轮
  └─ 回复或追问 → 保存对话 → 结束本轮
用户审批 → 官方写工具执行或拒绝 → 真实回执与当前会话 JSON
```

B1 保持为默认原生循环。LangGraph 使用同一业务工具和数据库层，通过 StateGraph 组织阶段；没有单独的模型服务器、向量库或多 agent 委派。

| 配置 | 累计增加的能力 |
| --- | --- |
| `lg_b1` | 与 B1 同策略的图执行器 |
| `lg_described` | 改进工具描述 |
| `lg_structured` | 只读结果格式 |
| `lg_extended` | 订单商品及款式筛选工具 |
| `lg_context` | 实际回执投影、相同查询结果压缩 |
| `lg_sop` | 取消、地址、商品、退换货及支付指引 |
| `lg_notes` | 每条新用户消息一次辅助需求笔记 |
| `lg_review` | 条件触发的一次检查及一次反馈修正 |

笔记不生成可执行参数，不决定是否批准，不阻止合法写入。执行事实来自真实回执。
SQLite 是唯一持久状态来源；重启后恢复会话和待审批操作，不自动重放未知结果的工具调用。
`BROWSER_AGENT_VARIANT` 只控制新浏览器会话，默认 `b1`；已有会话保留原配置。
内部保留 `tools_described/structured/extended` 三个接口对照别名。

## 前后端 API

登录使用 `retail_auth` HttpOnly cookie，支持 `APP_BASE_PATH`；前端不接收 session token。

| 接口 | 行为 |
| --- | --- |
| POST `/api/auth/register`、`login`、`logout` | 注册、登录、退出 |
| GET `/api/me`、`/api/orders`、`/api/orders/{oid}` | 当前账号资料和订单 |
| POST `/api/me/address`、`/api/orders/{oid}/actions` | 创建待审批操作，返回会话 |
| GET/POST `/api/sessions` | 列出/创建当前账号会话 |
| GET `/api/sessions/{id}` | 消息、上下文、待审批操作和回执 |
| POST `/api/sessions/{id}/messages` | `{message}`，返回 SSE |
| POST `/api/sessions/{id}/decisions` | `{action_id, approve}`，返回 JSON `{receipt, session}` |

浏览器审批后等待下一条用户消息，不自动调用模型。订单页和聊天读取同一账号业务数据。
内部评测的审批接口则会自动续跑并返回 SSE，这两种交互语义不能混同。

## 运行与 TACC

Python 3.12–3.13；模型服务须支持 OpenAI-compatible tool calling。
默认从同级 `../tau2-bench` 加载官方数据与代码，源码固定到上述 pin；`TAU2_ROOT` 可覆盖路径。

```bash
uv sync --frozen --python 3.12
cp .env.example .env
bash scripts/dev.sh
```

`AGENT_MODE=demo` 使用确定性演示模型；`live` 使用 `MODEL_BASE_URL`、`MODEL_NAME`、`MODEL_API_KEY`。
首次使用 main 登录页的演示账号前，明确设置独立应用 `RETAIL_DB_PATH`，运行：

```bash
uv run python -m scripts.seed_demo --apply
```

初始化脚本在应用 DB 同级保存备份及演示清单，不写入源码目录。
注册新账号只创建空客户，不会继承 tau2 用户数据。

TACC 说明见 [deploy/README.md](deploy/README.md) 和 [部署步骤](deploy/tacc/README.md)。
运行后端需要整个 `backend/`、应用依赖、已安装的 tau2 包以及 Retail db.json/policy.md。
若使用 uv 的本地 editable 依赖，需要完整同级 tau2 源码；仅运行已安装包时可以只提供数据目录。
本分支更新了应用依赖声明，但不代表新版本已在 TACC 完成部署验收。

## 最终 DB 评测

保留 `benchmarks/run_http.py` 与 `benchmarks/reference/` 供 evaluator 调用。
主分比较冻结目标与实际最终 DB：完整客户对象及初始所属订单；列表顺序和重复项保留。
字典键顺序忽略，不根据 agent 实际改动来缩小范围。模型回复“完成”不是评分依据。

- 创建：POST `/internal/eval/episodes`，使用 `EVAL_API_TOKEN`，传 initial_db/customer_id/variant/task_id。
- 交互：GET `/internal/eval/episodes/{id}`，POST `.../messages`、`.../decisions`，使用返回的 episode Bearer token。
- 结束/快照：POST `.../finish`、GET `.../snapshot`，使用 EVAL_API_TOKEN；先冻结再做最终评分。
- 每个 episode 的 DB 独立，目标 DB、参考动作和评分范围不能进入 agent 或模拟用户输入。

当前诊断只测试 B1 未通过的 task41、task47：

```bash
python -m benchmarks.run_http run \
  --fixtures /path/to/frozen-fixtures --task-ids 41,47 \
  --output /path/to/new-output --variant lg_sop --seeds 0 \
  --model YOUR_MODEL --thinking off \
  --base-url http://127.0.0.1:8000 --model-base-url http://127.0.0.1:8001/v1
```

只测失败题用于排错，不能当作整体成功率。冻结 fixture 和历史结果放在代码仓库之外。
模型/工具预算默认为每题 80/80 次、600 秒；额外笔记及检查调用同样计入。
