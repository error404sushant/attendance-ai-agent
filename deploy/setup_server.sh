#!/bin/bash
# Run this on the server as root: bash setup_server.sh

set -e

REPO_URL="REPLACE_WITH_YOUR_GITHUB_REPO_URL"
DOMAIN="agent.facenova.uk"
APP_DIR="/opt/attendance-agent"

echo "=== Installing system dependencies ==="
apt-get update -y
apt-get install -y python3 python3-pip python3-venv git nginx certbot python3-certbot-nginx curl nodejs npm

echo "=== Cloning repository ==="
if [ -d "$APP_DIR" ]; then
  cd "$APP_DIR" && git pull
else
  git clone "$REPO_URL" "$APP_DIR"
fi

echo "=== Setting up Python environment ==="
cd "$APP_DIR/backend"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

echo "=== Creating .env file ==="
if [ ! -f "$APP_DIR/backend/.env" ]; then
  cp "$APP_DIR/backend/.env.example" "$APP_DIR/backend/.env"
  # Update for server — use OmniRoute running on same server
  sed -i 's|AI_BASE_URL=.*|AI_BASE_URL=http://localhost:20128/v1|' "$APP_DIR/backend/.env"
  echo "IMPORTANT: Edit $APP_DIR/backend/.env if needed"
fi

echo "=== Installing systemd service ==="
cp "$APP_DIR/backend/deploy/attendance-agent.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable attendance-agent
systemctl restart attendance-agent

echo "=== Configuring Nginx ==="
cp "$APP_DIR/backend/deploy/nginx.conf" "/etc/nginx/sites-available/$DOMAIN"
ln -sf "/etc/nginx/sites-available/$DOMAIN" "/etc/nginx/sites-enabled/$DOMAIN"
nginx -t && systemctl reload nginx

echo "=== Setting up SSL ==="
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email admin@facenova.uk

echo ""
echo "=== DONE ==="
echo "Backend running at: https://$DOMAIN"
echo "Health check: curl https://$DOMAIN/health"
