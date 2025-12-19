#!/bin/bash

# HyperGridBot Deployment Script
# Usage: ./deploy.sh
# Run as root or with sudo

set -e

APP_DIR="/root/HyperGridBot" # Adjust if cloning elsewhere
USER="root" # User to run service as

echo "Starting deployment..."

# 1. Install System Dependencies
echo "Installing system dependencies..."
apt-get update
apt-get install -y python3 python3-pip python3-venv nginx

# 2. Setup Python Environment
echo "Setting up Python environment..."
cd $APP_DIR
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Create Systemd Service
echo "Creating systemd service..."
cat <<EOF > /etc/systemd/system/hypergrid.service
[Unit]
Description=Hyperliquid Grid Bot
After=network.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/main.py
Restart=always
RestartSec=10
Environment="HYPERLIQUID_PRIVATE_KEY=YOUR_KEY_HERE_IF_NOT_IN_CONFIG"

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
# Don't enable yet, user needs to configure key

# 4. Configure Nginx for Log Viewing
echo "Configuring Nginx..."
rm -f /etc/nginx/sites-enabled/default

cat <<EOF > /etc/nginx/sites-available/hypergrid
server {
    listen 80;
    server_name _;

    location / {
        root $APP_DIR/logs;
        autoindex on;
        default_type text/plain;
    }
}
EOF

ln -sf /etc/nginx/sites-available/hypergrid /etc/nginx/sites-enabled/
systemctl restart nginx

echo "Deployment complete!"
echo "1. Edit config.json with your settings."
echo "2. Add your Private Key to config.json or environment."
echo "3. Start bot: systemctl start hypergrid"
echo "4. View logs at http://YOUR_VPS_IP/"

