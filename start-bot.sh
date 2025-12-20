#!/bin/bash
cd /root/hypergrid/hypergrid
source venv/bin/activate
pip install -r requirements.txt
echo "🚀 Starting HyperGridBot TESTNET..."
python3 src/bot.py --config test_config.json
