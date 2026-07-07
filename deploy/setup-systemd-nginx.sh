#!/usr/bin/env bash
# Install systemd + nginx for NLQ on Ubuntu ECS.
# Run from repo root on the server: sudo bash deploy/setup-systemd-nginx.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Installing nginx + Node.js (for frontend build)..."
apt-get update -qq
apt-get install -y nginx curl

# Node 20 LTS via NodeSource (Ubuntu 22.04)
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

echo "==> Building frontend..."
cd frontend
npm ci
npm run build
cd "$REPO_ROOT"

echo "==> Installing systemd unit..."
cp deploy/nlq-backend.service /etc/systemd/system/nlq-backend.service
systemctl daemon-reload
systemctl enable nlq-backend
systemctl restart nlq-backend

echo "==> Installing nginx site..."
mkdir -p /var/www/certbot
cp deploy/nginx-nlq.conf /etc/nginx/sites-available/nlq
ln -sf /etc/nginx/sites-available/nlq /etc/nginx/sites-enabled/nlq
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl reload nginx

echo ""
echo "Done. Check status:"
echo "  systemctl status nlq-backend --no-pager"
echo "  systemctl status nginx --no-pager"
echo "  curl -s http://127.0.0.1/api/health | python3 -m json.tool"
echo ""
echo "Open in browser: http://nlquery.yydigi.top/ (after DNS A record is set)"
echo "Then HTTPS:      sudo bash deploy/setup-ssl.sh you@email.com"
