# ECS bare-metal deploy (systemd + nginx)

Single Ubuntu ECS instance: Postgres on localhost, FastAPI via systemd, React static build via nginx.

## Prerequisites

- Repo at `/opt/nlq`
- Python venv at `/opt/nlq/venv` with deps installed
- `.env` at `/opt/nlq/.env` with working `DB_URL` (include port, e.g. `:5533`)
- Olist database loaded + `nlq_readonly` role

### `.env` for HTTP demo (no TLS yet)

```env
DB_URL=postgresql://nlq_readonly:changeme@localhost:5533/olist
DASHSCOPE_API_KEY=sk-...
DASHSCOPE_MODEL=qwen3.6-flash
META_TOOLS_ENABLED=true
ALLOWED_ORIGINS=http://47.88.23.2
ENVIRONMENT=development
COOKIE_SECURE=false
```

Use `ENVIRONMENT=development` until HTTPS is configured (production boot requires `COOKIE_SECURE=true`).

## One-shot install

```bash
cd /opt/nlq
git pull   # get deploy/ files
sudo bash deploy/setup-systemd-nginx.sh
```

Edit `deploy/nginx-nlq.conf` `server_name` if your IP differs, before running the script.

## Manual steps

### systemd backend

```bash
sudo cp deploy/nlq-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable nlq-backend
sudo systemctl start nlq-backend
sudo systemctl status nlq-backend
```

Backend binds **127.0.0.1:8000** only — nginx proxies public traffic.

### nginx + frontend

```bash
cd /opt/nlq/frontend && npm ci && npm run build

sudo cp deploy/nginx-nlq.conf /etc/nginx/sites-available/nlq
sudo ln -sf /etc/nginx/sites-available/nlq /etc/nginx/sites-enabled/nlq
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

## Verify

```bash
curl http://127.0.0.1/api/health
curl http://127.0.0.1/api/query -H 'Content-Type: application/json' \
  -d '{"question":"How many delivered orders in Sao Paulo last month?"}'
```

Browser: `http://<ECS_PUBLIC_IP>/`

## Logs

```bash
journalctl -u nlq-backend -f
tail -f /var/log/nginx/error.log
```

## After code changes

```bash
cd /opt/nlq && git pull
source venv/bin/activate && pip install -r backend/requirements.txt
cd frontend && npm ci && npm run build
sudo systemctl restart nlq-backend
sudo systemctl reload nginx
```

## Security group

| Port | Source | Purpose |
|------|--------|---------|
| 80 | your IP or 0.0.0.0/0 | Web UI + API via nginx |
| 22 | your IP | SSH |
| 8000 | **close** | Backend is localhost-only |
| 5533 | **close after migration** | Postgres admin |
