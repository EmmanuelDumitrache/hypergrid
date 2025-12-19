#!/bin/bash

# HyperGrid Bot + UI Deployment Script (Ubuntu/Debian)
# Usage: ./deploy_pro.sh [DOMAIN_NAME] [EMAIL]
# Example: ./deploy_pro.sh mybot.com admin@mybot.com

set -e

DOMAIN=$1
EMAIL=$2
APP_DIR="/root/HyperGridBot"
USER="root"

if [ -z "$DOMAIN" ]; then
    echo "Usage: ./deploy_pro.sh [DOMAIN_NAME] [EMAIL]"
    echo "Please provide a domain name for SSL."
    exit 1
fi

echo ">>> Starting HyperGrid Deployment for $DOMAIN..."

# 1. Update & Install Dependencies
echo ">>> [1/8] Installing System Dependencies..."
apt-get update
apt-get install -y python3 python3-pip python3-venv nodejs npm nginx certbot python3-certbot-nginx ufw git

# 2. Setup App Directory (Git Clone if needed, else assumes current dir)
echo ">>> [2/8] Setting up Application..."
# If script is running outside repo, clone it. If inside, skip.
if [ ! -f "main.py" ]; then
    echo "Cloning repository..."
    # Replace with actual repo if relevant, or assume we are uploading the folder.
    # For this script context, we assume the user uploaded the folder to $APP_DIR
    mkdir -p $APP_DIR
else
    echo "Using current directory as source..."
    cp -r . $APP_DIR
fi

cd $APP_DIR

# 3. Python Setup
echo ">>> [3/8] Installing Python Dependencies..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. UI Setup
echo ">>> [4/8] Installing UI Dependencies..."
cd ui
npm install
cd ..

# 5. Systemd Services
echo ">>> [5/8] Configuring Systemd Services..."

# Bot Service
cat <<EOF > /etc/systemd/system/hypergrid-bot.service
[Unit]
Description=HyperGrid Trading Bot
After=network.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/main.py
Restart=always
RestartSec=10
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF

# UI Service
cat <<EOF > /etc/systemd/system/hypergrid-ui.service
[Unit]
Description=HyperGrid Dashboard UI
After=network.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR/ui
ExecStart=/usr/bin/node server.js
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable hypergrid-bot
systemctl enable hypergrid-ui

# 6. Nginx & SSL
echo ">>> [6/8] Configuring Nginx & SSL..."

# Remove default
rm -f /etc/nginx/sites-enabled/default

# Nginx Config
cat <<EOF > /etc/nginx/sites-available/hypergrid
server {
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
    }
}
EOF

ln -sf /etc/nginx/sites-available/hypergrid /etc/nginx/sites-enabled/

# SSL Certbot
if [ ! -z "$EMAIL" ]; then
    certbot --nginx -d $DOMAIN --non-interactive --agree-tos -m $EMAIL
else
    echo "Warning: No email provided. Skipping SSL Certbot automatic setup. Run manually."
fi

# 7. Log Rotation
echo ">>> [7/8] Configuring Log Rotation..."
cat <<EOF > /etc/logrotate.d/hypergrid
$APP_DIR/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 $USER $USER
}
EOF

# 8. Firewall
echo ">>> [8/8] Configuring Firewall (UFW)..."
ufw allow OpenSSH
ufw allow 'Nginx Full'
# ufw enable # prompt user usually, or force if automated
echo "y" | ufw enable

# Finalize
systemctl restart nginx
systemctl restart hypergrid-bot
systemctl restart hypergrid-ui

echo ">>> DEPLOYMENT COMPLETE!"
echo "Dashboard: https://$DOMAIN"
echo "Bot Status: systemctl status hypergrid-bot"
echo "Remember to edit config.json with your keys!"
