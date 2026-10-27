#!/usr/bin/env bash
# Run as root on the target VPS, after uploading a reviewed release and model environment.
set -euo pipefail
umask 022
release=${1:?release directory required}
model_env=${2:?model environment file required}
[[ "$release" == /opt/retail-agent/releases/* && -f "$release/retail-agent/uv.lock" ]]
[[ -f "$model_env" ]]
base=/opt/retail-agent
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup=/var/backups/retail-agent/$stamp
install -d -m 700 "$backup"
cp -a /etc/caddy "$backup/caddy"
if [[ -f /var/lib/hjw-workbench/workbench.sqlite3 ]]; then
    python3 -c 'import sqlite3,sys; src=sqlite3.connect("file:/var/lib/hjw-workbench/workbench.sqlite3?mode=ro",uri=True); dst=sqlite3.connect(sys.argv[1]); src.backup(dst); dst.close(); src.close()' "$backup/workbench.sqlite3"
fi
if [[ -f /var/lib/retail-agent/retail.sqlite3 ]]; then
    python3 -c 'import sqlite3,sys; src=sqlite3.connect("file:/var/lib/retail-agent/retail.sqlite3?mode=ro",uri=True); dst=sqlite3.connect(sys.argv[1]); src.backup(dst); dst.close(); src.close()' "$backup/retail.sqlite3"
fi
id retaildesk >/dev/null 2>&1 || useradd --system --home-dir /var/lib/retail-agent --shell /usr/sbin/nologin retaildesk
install -d -o retaildesk -g retaildesk -m 750 /var/lib/retail-agent
install -d -m 755 "$base/python" "$base/cache"
export UV_PYTHON_INSTALL_DIR=$base/python UV_CACHE_DIR=$base/cache
cd "$release/retail-agent"
"$release/bin/uv" sync --frozen --no-dev --python 3.12
chmod -R a+rX "$release/retail-agent/.venv" "$base/python"
install -m 600 "$model_env" /etc/retail-agent.env
cat >> /etc/retail-agent.env <<'ENV'

TAU2_ROOT=../tau2-bench
RETAIL_DB_PATH=/var/lib/retail-agent/retail.sqlite3
APP_BASE_PATH=/retail
HOST=127.0.0.1
PORT=8102
ENV
# Only a fresh, separate synthetic dataset is seeded; existing demo state is retained.
if [[ ! -f /var/lib/retail-agent/retail.sqlite3 ]]; then
    RETAIL_DB_PATH=/var/lib/retail-agent/retail.sqlite3 TAU2_ROOT=../tau2-bench OPENBLAS_NUM_THREADS=1 \
        .venv/bin/python -c 'from backend.store import Store; from scripts.seed_demo import seed; seed(Store())'
    chown retaildesk:retaildesk /var/lib/retail-agent/retail.sqlite3*
fi
ln -sfn "$release" "$base/current"
install -m 644 deploy/retail-agent.service /etc/systemd/system/retail-agent.service
systemctl daemon-reload
systemctl enable --now retail-agent.service
systemctl restart retail-agent.service
for attempt in {1..30}; do
    if curl -fsS http://127.0.0.1:8102/api/health > /dev/null; then break; fi
    sleep 1
done
curl -fsS http://127.0.0.1:8102/api/health

# A separate team gate prevents the public demo login from exposing unrestricted model usage.
install -d -m 700 /etc/retail-agent
if [[ ! -f /etc/retail-agent/team-access.txt ]]; then
    team_password=$(openssl rand -base64 24 | tr -d '\n')
    printf 'URL: https://junweihu.site/retail/\nUsername: team\nPassword: %s\n\nAfter the browser gate, use the synthetic demo login on the page.\n' "$team_password" > /etc/retail-agent/team-access.txt
    chmod 600 /etc/retail-agent/team-access.txt
else
    team_password=$(sed -n 's/^Password: //p' /etc/retail-agent/team-access.txt)
fi
team_hash=$(caddy hash-password --plaintext "$team_password")
route=/etc/caddy/routes-enabled/retail-agent.caddy
if [[ -e "$route" ]]; then cp -a "$route" "$backup/retail-agent.caddy"; fi
cat > "$route" <<ROUTE
handle /retail {
    redir /retail/ 308
}
handle_path /retail/* {
    basic_auth {
        team $team_hash
    }
    header X-Robots-Tag "noindex, nofollow"
    reverse_proxy 127.0.0.1:8102 {
        header_up -Authorization
        header_up X-Real-IP {remote_host}
        flush_interval -1
    }
}
ROUTE
if ! caddy validate --config /etc/caddy/Caddyfile; then
    if [[ -f "$backup/retail-agent.caddy" ]]; then
        cp -a "$backup/retail-agent.caddy" "$route"
    else
        mv "$route" "$backup/rejected-retail-agent.caddy"
    fi
    exit 1
fi
systemctl reload caddy
systemctl is-active retail-agent caddy hjw-workbench hjw-xray
echo "Retail deployed on 127.0.0.1:8102; HTTPS path /retail/; backup $backup"
