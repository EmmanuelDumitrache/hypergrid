#!/bin/bash

# HyperGrid Dashboard Deployment (Docker Version)
# Usage: ./deploy_docker.sh
# Run as root

set -e

echo ">>> Starting HyperGrid Dashboard Deployment..."

# 1. Install Docker & Compose
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
fi

if ! command -v docker-compose &> /dev/null; then
    echo "Installing Docker Compose..."
    apt-get install -y docker-compose-plugin || true
    # Fallback/verify
fi

# 2. Setup Environment
if [ ! -f config.json ]; then
    echo "Creating config.json from example..."
    cp config_example.json config.json
fi

# 3. Build & Run
echo "Building and Starting Containers..."
docker compose up -d --build

echo ">>> DEPLOYMENT COMPLETE!"
echo "Dashboard available at http://YOUR_VPS_IP"
echo "API configured on Port 8000"
echo "Edit config.json and restart container if needed: docker compose restart api"
