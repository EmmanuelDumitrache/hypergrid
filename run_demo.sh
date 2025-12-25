#!/bin/bash
# HyperGridBot Demo Script
# Runs the bot in testnet mode for demonstration

set -e

echo "🤖 HyperGridBot Demo"
echo "===================="
echo ""

# Check for .env
if [ ! -f .env ]; then
    echo "⚠️  No .env file found!"
    echo "   Copy .env.example to .env and add your testnet API keys:"
    echo ""
    echo "   cp .env.example .env"
    echo "   # Edit .env with your Binance Testnet keys"
    echo "   # Get keys from: https://testnet.binancefuture.com"
    echo ""
    exit 1
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.9+"
    exit 1
fi

# Install dependencies if needed
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "📦 Installing dependencies..."
pip install -q -r requirements.txt

echo ""
echo "🚀 Starting HyperGridBot in TESTNET mode..."
echo "   Press Ctrl+C to stop"
echo ""

python3 binance_bot.py
