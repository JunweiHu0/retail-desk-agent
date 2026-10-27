# Retail Desk VPS 部署

线上入口：**https://junweihu.site/retail/**。域名由现有 Caddy 证书维护，无需额外开放公网应用端口。

- 内部端口：`127.0.0.1:8102`，单 worker。
- 服务：`retail-agent.service`，独立账号 `retaildesk`，开机启动、异常重启。
- 当前代码：`/opt/retail-agent/current/retail-agent`。
- 上游工具及 Retail 合成种子：`/opt/retail-agent/current/tau2-bench`。
- 独立数据库：`/var/lib/retail-agent/retail.sqlite3`；没有复制本地会话或个人工作台数据。
- 模型环境：`/etc/retail-agent.env`，root / 600，不能输出到日志或提交到仓库。
- 团队门禁凭据：`/etc/retail-agent/team-access.txt`，root / 600；本地交付文件在被 Git 忽略的 `.deployment/团队访问凭据.txt`。
- 新增代理片段：`/etc/caddy/routes-enabled/retail-agent.caddy`。主 Caddyfile、原有 VPN 片段和工作台服务均保持原样。
- 部署前备份：`/var/backups/retail-agent/<UTC时间>/`，包括 Caddy 配置和原工作台 SQLite 一致性快照。

团队先通过浏览器弹出的 HTTP 身份验证，再在应用内选择合成客户登录。客户演示密码仅能操作本项目的合成数据库；模型使用真实 DeepSeek API，因此门禁凭据只分享给参与演示的团队成员。

## 构建与安装

在开发机使用锁定的 Node / Python 运行离线测试，在 `frontend/` 执行：

```bash
VITE_BASE_PATH=/retail/ npm run build
```

打包 `backend/`、`scripts/`、`deploy/`、`pyproject.toml`、`uv.lock`、`.python-version`、`frontend/dist/`，以及同级 `tau2-bench` 的源码、包元数据和 Retail 数据。不得打包 `.env`、本地运行数据库或会话。运行工具 `uv` 放在 release 的 `bin/uv`；Python 3.12 按锁文件安装到 VPS 的专用目录，不依赖系统 Python 版本。

在新 release 目录调用：

```bash
sudo bash /opt/retail-agent/releases/<release>/retail-agent/deploy/install.sh \
  /opt/retail-agent/releases/<release> /path/to/approved-model.env
```

模型环境只允许使用该应用获授权的模型配置。首轮可用不含任何秘密的 `AGENT_MODE=demo` 验证，用户批准凭据迁移后再接入 live。`install.sh` 不修改现有业务库，先备份，再验证 Caddy，最后 reload。

前端 `VITE_BASE_PATH=/retail/`、后端 `APP_BASE_PATH=/retail` 和 Uvicorn `--root-path /retail` 三者需一致。Caddy 的 `handle_path` 剥离前缀，Uvicorn 重建 ASGI 根路径，静态资源与 API 才能同时正确工作。登录 cookie 仅对 `/retail/` 有效，HTTPS 下为 Secure、HttpOnly、SameSite=Lax。

## 运维与回退

```bash
sudo systemctl status retail-agent --no-pager
sudo journalctl -u retail-agent -n 50 --no-pager
curl -fsS http://127.0.0.1:8102/api/health
sudo systemctl restart retail-agent
```

服务内存软限 550MB、硬限 700MB，CPU 上限一核，避免占满小型 VPS。浏览器门禁拒绝未授权请求，API 不缓存客户资料。团队成员共享选定演示客户的订单状态，确认取消或退货后会影响后续演示；需要重新演示时优先换另一个合成客户，不自动重置数据库。

下线时停止 `retail-agent`，把新增片段移到备份目录（不要删除），执行 `caddy validate --config /etc/caddy/Caddyfile` 后 `systemctl reload caddy`。不要重启 Caddy，也不要覆盖主 Caddyfile 或 VPN 片段。代码回退切换 `current` 至保留的 release 后重启 Retail；数据库必须先做快照，不能直接覆盖。
