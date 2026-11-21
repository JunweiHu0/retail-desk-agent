# 前端查看评测数据

这份目录包含 2026-11-21 formal `test` 40 × seed 0/1/2 的完整 replay 数据，以及 14 个 wall-time episode 的 1800 秒重跑 session。共 **134 个 session**、966 条事件。

## 数据文件

| 文件 | 内容 |
| --- | --- |
| `index.html` | 总览报告：汇总、termination、40×3 Per-task matrix、失败原因 |
| `replay-map.json` | `task:seed` → session id，报告矩阵里的链接用的就是它 |
| `replay/sessions.jsonl.gz` | 134 个 session 的 messages / manifest / tool_turns / usage |
| `replay/events.jsonl.gz` | 966 条 tool / decision / receipt 事件 |
| `replay/manifest.json` | 导出元信息 |
| `results-seed-{0,1,2}.json` | 正式 600 秒结果 |
| `reruns/` | 14 个 wall-time episode 的 1800 秒重跑结果和 `summary.json` |

`replay/` 里**没有**账号、密码、session bearer token 或 auth session；导入脚本会单独创建 `replay_viewer` 账号。

## 1. 导入 replay 数据

在仓库根目录执行：

```bash
cd /path/to/retail-desk-merge-preview

export RETAIL_DB_PATH="$PWD/runtime/replay.sqlite3"
python scripts/import_replay.py \
  --data docs/experiments/2026-11-21-formal-test40/replay \
  --db "$RETAIL_DB_PATH"
```

脚本只依赖 Python 标准库，会：

- 创建/复用 SQLite 表；
- 写入 134 个 session 和 966 条事件；
- 创建回放账号 `replay@retail-demo.example.com` / `Replay@2026!`；
- 打印导入数量。

> 如果导入到已有的 app 数据库，请确保 `--db` 与 app 的 `RETAIL_DB_PATH` 是同一个文件。

## 2. 启动前端

### 方式 A：生产模式（推荐，单端口 8000）

```bash
RETAIL_DB_PATH="$PWD/runtime/replay.sqlite3" ./deploy/run.sh local --prod
```

打开 http://127.0.0.1:8000 。

如果 8000 已被占用，先停掉旧进程，或者修改 `backend/server.py` 的端口后再启动。报告里的链接固定指向 `127.0.0.1:8000`。

### 方式 B：开发模式

```bash
RETAIL_DB_PATH="$PWD/runtime/replay.sqlite3" ./deploy/run.sh local
```

API 在 `:8000`，前端 dev server 在 `:5173`。报告链接仍然指向 `:8000`，因此从 `?session=` 深链进入时建议用方式 A，或者手动把链接的端口改成 `:5173`。

## 3. 登录

登录页点 **“回放”** 按钮，或手动输入：

- 邮箱：`replay@retail-demo.example.com`
- 密码：`Replay@2026!`

登录后左侧会列出 134 个 replay session，标题格式：

```text
task 42 · seed 0 · ✓ · Hi, I’m Mei Patel...
task 53 · seed 1 · ✗ · Hi, ...
```

`✓/✗` 是该 episode 的 DB 是否匹配 target；✗ 不等于 agent 一定做错了，原因见 `EVAL-VALIDITY.md`。

## 4. 看报告总览

另开一个终端：

```bash
./deploy/run.sh docs
```

打开：

```text
http://127.0.0.1:8090/experiments/2026-11-21-formal-test40/index.html
```

报告里有：

- **Summary (formal 600 s)**：seed 0/1/2 原始结果；
- **Wall-time rerun**：14 个超时 episode 用 1800 秒重跑后的结果和汇总；
- **Per-task matrix (merged)**：40 个 task × 3 seeds，已把 14 个 wall-time 格子替换成重跑结果；
- 每个格子都可以点击，跳到 `http://127.0.0.1:8000/?session=<session_id>` 打开对应的 replay。

如果只想打开某个 session，直接访问：

```text
http://127.0.0.1:8000/?session=<session_id>
```

session id 可以从 `replay-map.json` 或报告格子的链接里拿。

## 5. 前端 replay 里能看到什么

- **每个 assistant 气泡上方的工具抽屉**：显示 `Thought for Xs, ran N tools`；
- 点开后是完整的 tool chain：序号、工具名、ok/fail、耗时、args、result；
- Markdown 表格正常渲染（GFM table）；
- 14 个重跑 session 的标题/内容来自 1800 秒重跑；报告里对应格子标注 `1800 s rerun`；
- 原始 120 个 session 来自 600 秒正式评测。

## 6. 常见问题

| 现象 | 原因/处理 |
| --- | --- |
| 登录 401 | 导入用的 DB 和 app 的 `RETAIL_DB_PATH` 不是同一个文件 |
| 点格子后 session 404 | app 没跑在 `:8000`，或该 session 没导入 |
| 工具抽屉不显示 | 老 session 的 `manifest` 没有 `tool_turns`；本目录的 134 个都已补齐 |
| 页面还是旧数据 | 强制刷新浏览器缓存，或确认 `./deploy/run.sh docs` 服务的是当前仓库 |

## 7. 与 TACC 前端的关系

TACC 上 `localhost:8080` 的 app 使用自己的 `/tmp` 数据库，只有 demo 客户和实时会话，**不包含**这份 replay 数据。要查看 replay，请在本地按上面的步骤导入并使用 `:8000`；TACC 前端适合做实时对话演示。
