#!/bin/bash
# Local Dev Start Script

# Kill existing
pkill -f "uvicorn api.main:app" || true
pkill -f "vite" || true

echo "Starting HyperGrid Dashboard Locally..."

# 1. Install UI Deps if needed
if [ ! -d "ui/node_modules" ]; then
    echo "Installing UI dependencies (this may take a minute)..."
    (cd ui && npm install)
fi

# 2. Start API in background
echo "Starting Backend (Port 8000)..."
mkdir -p logs
python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload > logs/api.log 2>&1 &
API_PID=$!

# 3. Start Frontend in background
echo "Starting Frontend..."
(cd ui && npm run dev -- --host > ../logs/ui.log 2>&1 & echo $! > ../ui_pid)
UI_PID=$(cat ui_pid)
rm ui_pid

echo "Services started!"
echo "API PID: $API_PID"
echo "UI PID: $UI_PID"
echo "Opening Browser in 5 seconds..."

sleep 5
open http://localhost:5173

# Wait for user to exit
read -p "Press [Enter] to stop servers..."
kill $API_PID
kill $UI_PID
echo "Stopped."
