# Hyperliquid Perp Grid Bot

A production-ready Python grid trading bot for Hyperliquid SOL/USD perpetuals.

## Features
- **Grid Strategy**: 25 grids, dynamic spacing.
- **Capital Management**: 30% cash reserve enforcement.
- **Safety First**:
    - Max Account Drawdown Limit (10%).
    - Daily Loss Limit ($50).
    - Margin Ratio Check (>150%).
    - Trend Break Detection.
- **Deployment**: Systemd service + Nginx log viewer.

## Setup

### 1. Requirements
- Python 3.10+
- Hyperliquid Account (with API Wallet/Key)

### 2. Configuration
Copy `config_example.json` to `config.json` and edit:
```bash
cp config_example.json config.json
nano config.json
```
**CRITICAL**:
- Set `wallet.secret_key` (or use `HYPERLIQUID_PRIVATE_KEY` env var).
- Set `wallet.account_address`.
- Ensure `capital` matches your deposit (Bot uses 70% of this).

### 3. Run Locally
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py --paper
```
Use `--paper` for safety testing (Note: Requires Hyperliquid Testnet setup or Mock).

### 4. VPS Deployment (Docker Dashboard) - **RECOMMENDED**
This deploys the full Web Dashboard (React + FastAPI).

1. **Upload Code** to VPS.
2. **Run Script**:
   ```bash
   chmod +x deploy_docker.sh
   sudo ./deploy_docker.sh
   ```
3. **Access**:
   - Dashboard: `http://YOUR_VPS_IP`
   - Config: Edit `config.json` locally or via the Web UI.

### 5. VPS Deployment (Legacy Systemd)
For a headless simple deployment without Docker:
```bash
./deploy_pro.sh your-domain.com ...
```

### Dashboard Features
- **Live Logs**: Real-time websocket streaming.
- **Controls**: Start/Stop bot process.
- **Config**: Live JSON editor.

## Safety Mechanisms
The bot contains **MANDATORY** hard-coded safety checks in `src/safety.py`:
1. **Stop Loss**: If Account Value drops 10% below start -> **CANCEL ALL + CLOSE POSITIONS**.
2. **Daily Loss**: If Daily PnL < -$50 -> **EXIT**.
3. **Margin**: Checks margin ratio > 1.5x before every cycle.

## Disclaimer
Use at your own risk. This software is for educational purposes. 
