# ECS bare-metal deploy (systemd + nginx + HTTPS)

Single Ubuntu ECS instance: Postgres on localhost, FastAPI via systemd, React via nginx.

**Production URL:** https://nlquery.yydigi.top

## Prerequisites

- Repo at `/opt/nlq`
- Python venv + `.env` with working `DB_URL` (port `:5533`)
- Olist loaded + `nlq_readonly` role
- DNS **A record:** `nlquery.yydigi.top` → ECS public IP

## Security group (Alibaba)

| Port | Source | Purpose |
|------|--------|---------|
| 443 | 0.0.0.0/0 | HTTPS demo (judges / public) |
| 80 | 0.0.0.0/0 | HTTP redirect + Let's Encrypt validation |
| 22 | your IP | SSH |
| 8000 | **closed** | Backend localhost-only |
| 5533 | **closed** | Postgres localhost-only |

## Step 1 — systemd + nginx (HTTP)

```bash
cd /opt/nlq
git pull
sudo bash deploy/setup-systemd-nginx.sh
```

Or manually copy `deploy/nginx-nlq.conf` and build frontend (see below).

## Step 2 — HTTPS (Let's Encrypt)

```bash
sudo bash deploy/setup-ssl.sh you@email.com
```

Certbot installs the cert and configures nginx to redirect HTTP → HTTPS.

## Step 3 — production `.env`

```bash
openssl rand -hex 32   # paste into SESSION_SECRET
nano /opt/nlq/.env
```

Use `deploy/env.production.example` as a template:

```env
ALLOWED_ORIGINS=https://nlquery.yydigi.top
ENVIRONMENT=production
COOKIE_SECURE=true
SESSION_SECRET=<output of openssl rand -hex 32>
```

```bash
sudo systemctl restart nlq-backend
```

## Verify

```bash
curl -s https://nlquery.yydigi.top/api/health | python3 -m json.tool
```

Browser: https://nlquery.yydigi.top/

## Logs

```bash
journalctl -u nlq-backend -f
sudo tail -f /var/log/nginx/error.log
sudo certbot certificates
```

## After code changes

```bash
cd /opt/nlq && git pull
source venv/bin/activate && pip install -r backend/requirements.txt
cd frontend && npm ci && npm run build
sudo systemctl restart nlq-backend
sudo systemctl reload nginx
```

## Troubleshooting SSL

| Problem | Fix |
|---------|-----|
| certbot connection refused | Open port 80 to 0.0.0.0/0 in security group |
| DNS problem | Wait for A record propagation; `dig nlquery.yydigi.top` |
| 502 Bad Gateway | `systemctl status nlq-backend` — backend down |
| CORS / cookie errors | `ALLOWED_ORIGINS` must match `https://nlquery.yydigi.top` exactly |
| Production boot fails | Set `SESSION_SECRET` and `COOKIE_SECURE=true` |

## Certificate renewal

Certbot auto-renewal via systemd timer. Test with:

```bash
sudo certbot renew --dry-run
```
