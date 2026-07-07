#!/usr/bin/env bash
# Obtain Let's Encrypt cert and enable HTTPS for nlquery.yydigi.top
#
# Before running:
#   1. DNS A record: nlquery.yydigi.top → your ECS public IP
#   2. Security group: inbound TCP 80 AND 443 from 0.0.0.0/0 (required for
#      Let's Encrypt validation and public demo access)
#   3. nginx HTTP config installed (deploy/nginx-nlq.conf)
#
# Usage:
#   sudo bash deploy/setup-ssl.sh you@email.com
set -euo pipefail

DOMAIN="${NLQ_DOMAIN:-nlquery.yydigi.top}"
EMAIL="${1:-}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/setup-ssl.sh you@email.com"
  exit 1
fi

if [[ -z "$EMAIL" ]]; then
  echo "Usage: sudo bash deploy/setup-ssl.sh you@email.com"
  exit 1
fi

echo "==> Checking DNS for ${DOMAIN}..."
RESOLVED="$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1 || true)"
PUBLIC_IP="$(curl -s --max-time 5 ifconfig.me 2>/dev/null || curl -s --max-time 5 icanhazip.com 2>/dev/null || true)"
echo "    DNS resolves to: ${RESOLVED:-<not found>}"
echo "    ECS public IP:   ${PUBLIC_IP:-<unknown>}"
if [[ -n "$RESOLVED" && -n "$PUBLIC_IP" && "$RESOLVED" != "$PUBLIC_IP" ]]; then
  echo "WARNING: DNS does not match this server's public IP yet."
  echo "         Fix the A record before continuing."
  read -r -p "Continue anyway? [y/N] " ans
  [[ "${ans,,}" == "y" ]] || exit 1
fi

echo "==> Installing certbot..."
apt-get update -qq
apt-get install -y certbot python3-certbot-nginx

mkdir -p /var/www/certbot

echo "==> Requesting certificate..."
certbot --nginx \
  -d "$DOMAIN" \
  --email "$EMAIL" \
  --agree-tos \
  --no-eff-email \
  --redirect \
  --non-interactive

echo "==> Testing renewal timer..."
systemctl enable certbot.timer 2>/dev/null || true
systemctl start certbot.timer 2>/dev/null || true

echo ""
echo "HTTPS enabled for https://${DOMAIN}/"
echo ""
echo "Update /opt/nlq/.env:"
echo "  ALLOWED_ORIGINS=https://${DOMAIN}"
echo "  ENVIRONMENT=production"
echo "  COOKIE_SECURE=true"
echo "  SESSION_SECRET=<strong-random-64-chars>"
echo ""
echo "Then: sudo systemctl restart nlq-backend"
echo "Verify: curl -s https://${DOMAIN}/api/health | python3 -m json.tool"
