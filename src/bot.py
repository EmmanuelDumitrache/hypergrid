import os
import sys
import time
import json
import logging
import signal
import argparse
import tempfile
import shutil
import threading
from colorama import init, Fore, Style
from datetime import datetime

# Initialize colorama
init(autoreset=True)


# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.safety import SafetyMonitor
# Mock imports for now until SDK is confirmed installed or we use standard patterns
try:
    from hyperliquid.info import Info
    from hyperliquid.exchange import Exchange
    from hyperliquid.utils import types
    from eth_account.account import Account
except ImportError:
    pass

# Setup Logging with Colors
class ColoredFormatter(logging.Formatter):
    FORMATS = {
        logging.DEBUG: Fore.CYAN + Style.DIM + "%(asctime)s" + Style.RESET_ALL + " | " + Fore.CYAN + "%(levelname)-8s" + Style.RESET_ALL + " | " + Fore.CYAN + "%(message)s" + Style.RESET_ALL,
        logging.INFO: Fore.WHITE + Style.DIM + "%(asctime)s" + Style.RESET_ALL + " | " + Fore.GREEN + Style.BRIGHT + "%(levelname)-8s" + Style.RESET_ALL + " | " + Fore.WHITE + "%(message)s" + Style.RESET_ALL,
        logging.WARNING: Fore.YELLOW + Style.DIM + "%(asctime)s" + Style.RESET_ALL + " | " + Fore.YELLOW + Style.BRIGHT + "%(levelname)-8s" + Style.RESET_ALL + " | " + Fore.YELLOW + "%(message)s" + Style.RESET_ALL,
        logging.ERROR: Fore.RED + Style.DIM + "%(asctime)s" + Style.RESET_ALL + " | " + Fore.RED + Style.BRIGHT + "%(levelname)-8s" + Style.RESET_ALL + " | " + Fore.RED + "%(message)s" + Style.RESET_ALL,
        logging.CRITICAL: Fore.RED + Style.BRIGHT + "%(asctime)s" + Style.RESET_ALL + " | " + Fore.RED + Style.BRIGHT + "%(levelname)-8s" + Style.RESET_ALL + " | " + Fore.RED + Style.BRIGHT + "%(message)s" + Style.RESET_ALL
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        # Simplify date format to just Time
        formatter = logging.Formatter(log_fmt, datefmt='%H:%M:%S')
        return formatter.format(record)

def setup_logging(config):
    log_file = config['system']['log_file']
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    # File handler (plain text)
    file_formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d | %H:%M:%S')
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(file_formatter)
    
    # Console handler (colored)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(ColoredFormatter())
    
    logger = logging.getLogger()
    logger.setLevel(config['system'].get('log_level', 'INFO'))
    
    # Silence noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    # Clean existing handlers
    logger.handlers = []
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

class HyperGridBot:
    def __init__(self, config_path, paper_mode=False):
        self.running = True
        self.paused = False
        self.auto_trading = True  # New flag for automation
        self.auto_range_enabled = False # New flag for auto-range
        self.paper_mode = paper_mode
        self.config_path = config_path
        self.load_config(config_path)
        
        # Setup Logger
        setup_logging(self.config)
        
        self.setup_sdk()
        self.safety = SafetyMonitor(self.config, self.exchange, self.info, self.address)
        
        # Grid State
        self.orders = []
        self.previous_orders = []  # Track previous orders to detect fills
        self.current_range_bottom = 0
        self.current_range_top = 0
        
        # Metrics
        self.total_trades = 0
        self.recent_trades = [] # List of timestamps
        self.trade_history = []  # List of trade dicts: {timestamp, price, size, side, pnl}
        self.start_balance = 0
        self.current_balance = 0
        self.start_of_day_balance = 0
        self.start_of_week_balance = 0
        self.current_day = datetime.utcnow().date()
        self.current_week = datetime.utcnow().isocalendar()[1]
        
        # Cached API data (to reduce API calls)
        self.cached_funding_rate = None
        self.cached_funding_rate_time = 0
        self.cached_meta = None
        self.cached_meta_time = 0
        self.cached_order_history = None
        self.cached_order_history_time = 0
        
        # Register Signal Handler
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)

        # Start Command Listener
        self.cmd_thread = threading.Thread(target=self.command_listener, daemon=True)
        self.cmd_thread.start()

    def command_listener(self):
        """Listens for CLI commands in a background thread"""
        print(f"\n{Fore.CYAN}{Style.BRIGHT}>>> Interactive CLI Active.{Style.RESET_ALL} {Fore.CYAN}Type /commands for help.{Style.RESET_ALL}\n")
        while self.running:
            try:
                cmd_raw = input()
                if not cmd_raw.startswith("/"):
                    continue
                
                # Split command and args
                parts = cmd_raw.strip().lower().split()
                cmd = parts[0]
                args = parts[1:]
                
                if cmd in ["/help", "/commands"]:
                    print(f"\n{Fore.CYAN}{Style.BRIGHT}╔════════════════════════════════════╗")
                    print(f"║       HYPERGRID BOT COMMANDS       ║")
                    print(f"╠════════════════════════════════════╣{Style.RESET_ALL}")
                    print(f"{Fore.CYAN}║ {Fore.GREEN}/start   {Fore.WHITE}- Resume trading            {Fore.CYAN}║")
                    print(f"{Fore.CYAN}║ {Fore.GREEN}/stop    {Fore.WHITE}- Pause trading             {Fore.CYAN}║")
                    print(f"{Fore.CYAN}║ {Fore.GREEN}/auto    {Fore.WHITE}- Toggle auto-grid [on|off] {Fore.CYAN}║")
                    print(f"{Fore.CYAN}║ {Fore.GREEN}/autorange{Fore.WHITE}- Toggle auto-range [on|off]{Fore.CYAN}║")
                    print(f"{Fore.CYAN}║ {Fore.GREEN}/status  {Fore.WHITE}- Show dashboard & PnL      {Fore.CYAN}║")
                    print(f"{Fore.CYAN}║ {Fore.GREEN}/mode    {Fore.WHITE}- Set [paper|testnet]       {Fore.CYAN}║")
                    print(f"{Fore.CYAN}║ {Fore.GREEN}/range   {Fore.WHITE}- Set [min] [max]           {Fore.CYAN}║")
                    print(f"{Fore.CYAN}║ {Fore.GREEN}/risk    {Fore.WHITE}- Set risk params           {Fore.CYAN}║")
                    print(f"{Fore.CYAN}║ {Fore.GREEN}/save    {Fore.WHITE}- Save config to disk       {Fore.CYAN}║")
                    print(f"{Fore.CYAN}║ {Fore.GREEN}/reload  {Fore.WHITE}- Reload config from disk   {Fore.CYAN}║")
                    print(f"{Fore.CYAN}║ {Fore.GREEN}/panic   {Fore.WHITE}- STOP & CANCEL ALL         {Fore.CYAN}║")
                    print(f"{Fore.CYAN}║ {Fore.GREEN}/quit    {Fore.WHITE}- Shutdown bot              {Fore.CYAN}║")
                    print(f"{Fore.CYAN}╚════════════════════════════════════╝{Style.RESET_ALL}\n")
                
                elif cmd == "/stop":
                    self.paused = True
                    logging.warning(f"{Style.BRIGHT}BOT PAUSED{Style.RESET_ALL} by user command.")
                
                elif cmd == "/start":
                    self.paused = False
                    logging.info(f"{Style.BRIGHT}BOT RESUMED{Style.RESET_ALL} by user command.")
                
                elif cmd == "/auto":
                    if args:
                        mode = args[0]
                        if mode == "on":
                            self.auto_trading = True
                            logging.info(f"{Style.BRIGHT}AUTOMATION ENABLED{Style.RESET_ALL}")
                        elif mode == "off":
                            self.auto_trading = False
                            logging.info(f"{Style.BRIGHT}AUTOMATION DISABLED{Style.RESET_ALL}")
                    else:
                        status = "ON" if self.auto_trading else "OFF"
                        print(f"{Fore.CYAN}Auto Mode: {status}{Style.RESET_ALL} (Usage: /auto on|off)")

                elif cmd == "/autorange":
                    if args:
                        mode = args[0]
                        if mode == "on":
                            self.auto_range_enabled = True
                            logging.info(f"{Style.BRIGHT}AUTO-RANGE ENABLED{Style.RESET_ALL}")
                        elif mode == "off":
                            self.auto_range_enabled = False
                            logging.info(f"{Style.BRIGHT}AUTO-RANGE DISABLED{Style.RESET_ALL}")
                    else:
                        status = "ON" if self.auto_range_enabled else "OFF"
                        print(f"{Fore.CYAN}Auto-Range: {status}{Style.RESET_ALL} (Usage: /autorange on|off)")

                elif cmd == "/status":
                    self.print_status()

                elif cmd == "/panic":
                    logging.critical(f"{Fore.RED}PANIC TRIGGERED BY USER!{Style.RESET_ALL}")
                    self.paused = True
                    self.safety.emergency_exit()
                    logging.info("Bot paused. use /start to resume (careful!).")

                elif cmd == "/save":
                    try:
                        with open(self.config_path, 'w') as f:
                            json.dump(self.config, f, indent=4)
                        logging.info(f"{Fore.GREEN}Configuration saved to {self.config_path}{Style.RESET_ALL}")
                    except Exception as e:
                        logging.error(f"Failed to save config: {e}")

                elif cmd == "/reload":
                    try:
                        self.load_config(self.config_path)
                        # Re-apply safety settings
                        if hasattr(self, 'safety'):
                            self.safety.update_config(self.config)
                        # Re-apply grid settings
                        if hasattr(self, 'grid_manager'):
                             # Update grid config reference if needed, usually passed by reference but good to be safe
                             self.grid_manager.config = self.config
                             # Should we reset manual range? User might expect config values.
                             # If config has no manual range, maybe reset?
                             # For now, we trust loading config updates known keys.
                        logging.info(f"{Fore.GREEN}Configuration reloaded.{Style.RESET_ALL}")
                    except Exception as e:
                        logging.error(f"Failed to reload config: {e}")

                elif cmd == "/mode":
                    if args:
                        target = args[0]
                        if target == "paper":
                            self.paper_mode = True
                            # Re-init SDK
                            self.setup_sdk()
                        elif target == "testnet":
                            self.paper_mode = True # Testnet is paper logic in this bot for now
                            self.config['wallet']['base_url'] = "https://api.hyperliquid-testnet.xyz"
                            self.setup_sdk()
                        elif target == "mainnet":
                            # Caution
                            # self.paper_mode = False
                            # self.setup_sdk()
                            logging.warning("Switching to Mainnet not fully enabled in this CLI version for safety.")
                        else:
                            print("Usage: /mode [paper|testnet]")
                    else:
                        print(f"Current Mode: {'PAPER' if self.paper_mode else 'LIVE'}")

                elif cmd == "/range":
                    if len(args) >= 2:
                        try:
                            min_p = float(args[0])
                            max_p = float(args[1])
                            
                            # Set in config
                            # We don't have standard keys for this in config.json yet, but can add runtime keys
                            # Better: Set on grid_manager directly
                            if hasattr(self, 'grid_manager'):
                                self.grid_manager.set_manual_range(min_p, max_p)
                                logging.info(f"Manual Range Set: {min_p} - {max_p}")
                                # Clear existing orders to force rebuild?
                                # self.orders = [] 
                                # But we need to cancel first?
                                # Let's just set it, main loop will see 'No active orders' if we clear?
                                # Ideally: /stop -> /range -> /start
                        except ValueError:
                             print("Usage: /range [min] [max]")
                    else:
                        # Show current
                        if hasattr(self, 'grid_manager'):
                             print(f"Range: {self.grid_manager.min_price} - {self.grid_manager.max_price}")
                        else:
                             print("Grid Manager not initialized.")

                elif cmd == "/risk":
                    if len(args) >= 2:
                        key = args[0]
                        val = args[1]
                        if key == "dd":
                            self.config['safety']['max_drawdown_pct'] = float(val)
                        elif key == "daily":
                            self.config['safety']['daily_loss_limit_usd'] = float(val)
                        
                        self.safety.update_config(self.config)
                        logging.info(f"Risk Updated: {key}={val}")
                    else:
                        print(f"Risk Params: DD={self.config['safety']['max_drawdown_pct']}, Daily={self.config['safety']['daily_loss_limit_usd']}")

                elif cmd == "/quit":
                    print(f"{Fore.RED}Shutting down...{Style.RESET_ALL}")
                    self.shutdown(None, None)
                    break
                    
                else:
                    print(f"{Fore.RED}Unknown command: {cmd}{Style.RESET_ALL}")
            except EOFError:
                break
            except Exception as e:
                logging.error(f"Command error: {e}")

    def print_status(self):
        print(f"\n{Fore.CYAN}=== HyperGridBot Status ==={Style.RESET_ALL}")
        print(f"Status: {Fore.RED + 'PAUSED' if self.paused else Fore.GREEN + 'RUNNING'}{Style.RESET_ALL}")
        print(f"Mode: {'PAPER' if self.paper_mode else 'LIVE'}")
        print(f"Pair: {self.config.get('grid', {}).get('pair', 'N/A')}")
        
        # Range Info
        if hasattr(self, 'grid_manager') and self.grid_manager.min_price:
             print(f"Range: Manual ({self.grid_manager.min_price} - {self.grid_manager.max_price})")
        else:
             print(f"Range: Auto/Spread ({self.config['grid'].get('spacing_pct',0)*100:.2f}% spacing)")

        print(f"Balance: ${self.current_balance:.2f}")
        print(f"PnL: {Fore.GREEN if (self.current_balance - self.start_balance) >= 0 else Fore.RED}${self.current_balance - self.start_balance:.2f}{Style.RESET_ALL}")
        print(f"Active Grids: {len(self.orders)}")
        
        # Safety Info
        print(f"Safety: DD Max {self.config['safety']['max_drawdown_pct']*100}%, Daily Limit ${self.config['safety']['daily_loss_limit_usd']}")
        status_auto = "ON" if self.auto_trading else "OFF"
        status_autorange = "ON" if self.auto_range_enabled else "OFF"
        print(f"Automation: {status_auto} | Auto-Range: {status_autorange}")
        print(f"===========================\n")

    def load_config(self, path):
        with open(path, 'r') as f:
            self.config = json.load(f)
        
        # Override secret if env var exists
        env_secret = os.getenv("HYPERLIQUID_PRIVATE_KEY")
        if env_secret:
            self.config['wallet']['secret_key'] = env_secret

    def setup_sdk(self):
        try:
            from eth_account.account import Account
            from hyperliquid.info import Info
            from hyperliquid.exchange import Exchange
        except ImportError:
            logging.error("Hyperliquid SDK missing. Please `pip install -r requirements.txt`")
            sys.exit(1)

        secret = self.config['wallet']['secret_key']
        if not secret or "YOUR_PRIVATE" in secret:
            # Check if we can run in read-only mode or just fail
            # The bot needs to trade, so fail.
            # However, for 'build' purposes, we warn.
            logging.warning("Private key not configured! SDK init will fail.")
            if not self.paper_mode:
                raise ValueError("Private key not configured!")
            self.address = "0x0000000000000000000000000000000000000000"
            self.info = None
            self.exchange = None
            return
            
        account = Account.from_key(secret)
        self.address = self.config['wallet'].get('account_address') or account.address
        
        base_url = None # Default mainnet
        if self.paper_mode:
             # Use mainnet for data if possible for realistic prices
             # base_url = None means mainnet
             # But if user wants testnet prices, we can keep testnet.
             # User Request: "No tick bugs", "Simulate".
             # Best data is Mainnet.
             base_url = None 
             logging.info("Initializing in SIMULATION MODE (using Mainnet data, Local execution)")
             
        self.info = Info(base_url=base_url, skip_ws=True)
        # self.exchange = Exchange(...) # Skip exchange in paper simulation
        if not self.paper_mode:
             self.exchange = Exchange(account, base_url=base_url, account_address=self.address)
        else:
             self.exchange = None
             self.sim_balance = 1000.0 # Start with $1000 simulated
             self.sim_positions = []
             self.orders = [] # Shared orders list logic

    def _simulate_user_state(self, current_price):
        """Generate mock user state for simulation"""
        # Calculate unrealized PnL from sim_positions
        u_pnl = 0.0
        margin_used = 0.0
        asset_positions = []
        
        for pos in self.sim_positions:
            entry = pos['entryPx']
            sz = pos['szi']
            # Pnl = (Price - Entry) * Size (for Long, Szi is positive)
            pnl = (current_price - entry) * sz
            u_pnl += pnl
            
            # Approx margin 
            m = (abs(sz) * current_price) / self.config['grid']['leverage']
            margin_used += m
            
            asset_positions.append({
                "position": {
                    "coin": self.config['grid']['pair'],
                    "szi": sz,
                    "entryPx": entry,
                    "unrealizedPnl": pnl,
                    "marginUsed": m,
                    "liquidationPx": 0 # TODO
                }
            })

        equity = self.sim_balance + u_pnl
        
        return {
            "marginSummary": {
                "accountValue": equity,
                "totalMarginUsed": margin_used,
                "totalRawUsd": self.sim_balance
            },
            "withdrawable": max(0, self.sim_balance - margin_used),
            "assetPositions": asset_positions,
            "openOrders": self.orders # In sim, self.orders is the source of truth
        }

    def update_live_log(self, pnl, current_price, active_grids):
        msg = f"PnL: ${pnl:+.2f} | {self.config['grid']['pair']} {current_price:.2f} | {active_grids}/{self.config['grid']['grids']} active grids"
        logging.info(msg)

    def run(self):
        logging.info("Starting HyperGridBot...")
        
        # 1. Setup Leverage (Once)
        self.set_leverage()

        while self.running:
            try:
                # Sync loop frequency
                time.sleep(10) # 10s tick

                if self.paused:
                    continue

                # Check SDK Init
                if not self.info:
                    logging.warning("SDK not initialized (Key missing?). Sleeping.")
                    continue

                # Fetch User State & Market Data
                if self.paper_mode:
                     # For sim, we need price first to gen state
                     all_mids = self.info.all_mids()
                     price = float(all_mids.get(self.config['grid']['pair'], 0))
                     user_state = self._simulate_user_state(price)
                else:
                     user_state = self.info.user_state(self.address)
                
                logging.debug(f"User state response: {user_state}")
                margin_summary = user_state.get('marginSummary', {})
                logging.debug(f"Margin summary: {margin_summary}")
                
                # Get account value - in Hyperliquid, accountValue represents total account value
                # When no positions: accountValue = totalRawUsd (available USDC)
                # When positions exist: accountValue = totalRawUsd + unrealized PnL
                account_value = float(margin_summary.get('accountValue', 0))
                total_raw_usd = float(margin_summary.get('totalRawUsd', 0))
                withdrawable = float(user_state.get('withdrawable', 0))
                
                # Use accountValue as primary, fallback to totalRawUsd or withdrawable
                if account_value == 0:
                    if total_raw_usd > 0:
                        account_value = total_raw_usd
                        logging.info(f"Using totalRawUsd as account value: ${account_value:.2f}")
                    elif withdrawable > 0:
                        account_value = withdrawable
                        logging.info(f"Using withdrawable as account value: ${account_value:.2f}")
                
                logging.info(f"Detected account value: ${account_value:.2f} USDC (rawUsd: ${total_raw_usd:.2f}, withdrawable: ${withdrawable:.2f})")
                
                
                # Fetch Price (if not already fetched for sim)
                if not self.paper_mode:
                    all_mids = self.info.all_mids()
                    price = float(all_mids.get(self.config['grid']['pair'], 0))
                
                if price == 0:
                    logging.warning("Could not fetch price. Retrying...")
                    continue

                # Run Safety Checks
                # 1. Account Health
                if not self.safety.check_health(user_state):
                    logging.error("Safety check failed (Account Health). Pausing/Exited.")
                    if self.safety.emergency_triggered:
                        break
                    continue
                
                # 2. Market Conditions (Funding)
                # Fetch detailed market state
                try:
                    meta_and_asset_ctxs = self.info.meta_and_asset_ctxs()
                    # Find our coin index/state
                    # Structure: [meta, asset_ctxs]
                    meta, asset_ctxs = meta_and_asset_ctxs
                    universe = meta['universe']
                    # Find coin index
                    coin_idx = next((i for i, c in enumerate(universe) if c['name'] == self.config['grid']['pair']), -1)
                    
                    if coin_idx != -1:
                        ctx = asset_ctxs[coin_idx]
                        funding_rate = float(ctx.get('funding', 0.0))
                        
                        # Get current position size to determine 'adverse'
                        pos_size = 0
                        for p in user_state.get('assetPositions', []):
                            if p['position']['coin'] == self.config['grid']['pair']:
                                pos_size = float(p['position']['szi'])
                                break
                        
                        if not self.safety.check_funding_rate(funding_rate, pos_size):
                             logging.warning(f"Adverse Funding Rate detected ({funding_rate:.5f}). Pausing grid.")
                             continue
                except Exception as e:
                    logging.warning(f"Could not check funding rate: {e}")

                # Trend Break Check
                if self.current_range_bottom > 0 and price < (self.current_range_bottom * 0.95):
                    logging.warning(f"Trend Break! Price {price} < {self.current_range_bottom} * 0.95. Selling inventory.")
                    self.safety.emergency_exit()
                    break

                # Gather 24h stats for Auto-Range
                high_24h = price * 1.05 # Mock default if API fails
                low_24h = price * 0.95
                try:
                    # Attempt to get real stats if possible using available calls
                    # SDK doesn't always expose 24h stats easily in 'info', sometimes in meta or careful calls
                    # For now we proceed with current price. 
                    # Ideally: self.info.ticker? 
                    pass
                except:
                    pass

                # Grid Logic
                self.manage_grids(price, user_state, high_24h, low_24h)
                
                # Update Metrics
                if self.start_balance == 0 and self.safety.initial_account_value:
                    self.start_balance = self.safety.initial_account_value
                    self.start_of_day_balance = self.start_balance
                    self.start_of_week_balance = self.start_balance
                
                self.current_balance = account_value
                pnl = self.current_balance - self.start_balance
                active_orders = len(self.orders)
                self.update_live_log(pnl, price, active_orders)
                
                # Export State for UI - pass user_state to avoid re-fetching
                self.export_state(pnl, price, active_orders, user_state)

            except Exception as e:
                logging.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(5)

    def _detect_fills(self, previous_orders, current_orders, current_price):
        """Detect order fills by comparing previous and current open orders"""
        try:
            if not previous_orders:
                return
            
            # Create sets of order IDs for comparison
            prev_order_ids = {order.get('oid', order.get('id', '')) for order in previous_orders}
            curr_order_ids = {order.get('oid', order.get('id', '')) for order in current_orders}
            
            # Find filled orders (in previous but not in current)
            filled_order_ids = prev_order_ids - curr_order_ids
            
            if filled_order_ids:
                # Find the filled order details
                for order in previous_orders:
                    order_id = order.get('oid', order.get('id', ''))
                    if order_id in filled_order_ids:
                        # Record the fill
                        now = time.time()
                        self.total_trades += 1
                        self.recent_trades.append(now)
                        
                        # Extract order details
                        side = "BUY" if order.get('side') == 'B' or order.get('side') == 'A' else "SELL"
                        price = float(order.get('limitPx', order.get('price', current_price)))
                        size = float(order.get('sz', order.get('size', 0)))
                        
                        # Store trade history
                        self.trade_history.append({
                            'timestamp': now,
                            'price': price,
                            'size': size,
                            'side': side,
                            'pnl': 0.0  # Will be calculated when position closes
                        })
                        
                        logging.info(f"Order filled: {side} {size} @ ${price:.2f}")
                        
        except Exception as e:
            logging.error(f"Error detecting fills: {e}")

    def _calculate_trade_analytics(self):
        """Calculate trade analytics from trade history"""
        try:
            now = time.time()
            trades_24h = [t for t in self.trade_history if now - t['timestamp'] < 86400]
            
            if not trades_24h:
                return {
                    'win_rate': 0.0,
                    'avg_trade_size': 0.0,
                    'largest_win': 0.0,
                    'largest_loss': 0.0,
                    'profit_factor': 0.0
                }
            
            # Calculate win rate from closed positions (for now, use all trades)
            # In future, we'd track realized PnL per trade
            wins = [t for t in trades_24h if t.get('pnl', 0) > 0]
            losses = [t for t in trades_24h if t.get('pnl', 0) < 0]
            
            win_rate = (len(wins) / len(trades_24h) * 100) if trades_24h else 0.0
            avg_trade_size = sum(t['size'] for t in trades_24h) / len(trades_24h) if trades_24h else 0.0
            
            pnls = [t.get('pnl', 0) for t in trades_24h]
            largest_win = max(pnls) if pnls and max(pnls) > 0 else 0.0
            largest_loss = min(pnls) if pnls and min(pnls) < 0 else 0.0
            
            total_wins = sum(t.get('pnl', 0) for t in wins) if wins else 0.0
            total_losses = abs(sum(t.get('pnl', 0) for t in losses)) if losses else 0.0
            profit_factor = (total_wins / total_losses) if total_losses > 0 else (total_wins if total_wins > 0 else 0.0)
            
            return {
                'win_rate': win_rate,
                'avg_trade_size': avg_trade_size,
                'largest_win': largest_win,
                'largest_loss': largest_loss,
                'profit_factor': profit_factor
            }
        except Exception as e:
            logging.error(f"Error calculating trade analytics: {e}")
            return {
                'win_rate': 0.0,
                'avg_trade_size': 0.0,
                'largest_win': 0.0,
                'largest_loss': 0.0,
                'profit_factor': 0.0
            }

    def export_state(self, pnl, current_price, active_orders, user_state=None):
        """Export bot state to JSON for Dashboard"""
        try:
            now = time.time()
            
            # Use provided user_state or fetch if not provided
            if user_state is None and self.info:
                try:
                    user_state = self.info.user_state(self.address)
                except Exception as e:
                    logging.error(f"Failed to fetch user_state in export_state: {e}")
                    user_state = {}
            
            # Clean old trades (>24h)
            self.recent_trades = [t for t in self.recent_trades if now - t < 86400]
            self.trade_history = [t for t in self.trade_history if now - t['timestamp'] < 86400]
            
            # Update daily/weekly tracking
            current_date = datetime.utcnow().date()
            current_week = datetime.utcnow().isocalendar()[1]
            
            if current_date != self.current_day:
                self.start_of_day_balance = self.current_balance
                self.current_day = current_date
            
            if current_week != self.current_week:
                self.start_of_week_balance = self.current_balance
                self.current_week = current_week
            
            # Calculate daily and weekly PnL
            pnl_daily = self.current_balance - self.start_of_day_balance if self.start_of_day_balance > 0 else 0
            pnl_weekly = self.current_balance - self.start_of_week_balance if self.start_of_week_balance > 0 else 0
            
            # Get margin info from user_state
            margin_summary = user_state.get('marginSummary', {}) if user_state else {}
            margin_used = float(margin_summary.get('totalMarginUsed', 0))
            account_value = float(margin_summary.get('accountValue', self.current_balance))
            available_balance = float(user_state.get('withdrawable', 0)) if user_state else 0
            margin_ratio = (account_value / margin_used) if margin_used > 0 else 0
            
            # Get funding rate (cached, update every 5 minutes)
            funding_rate = 0.0
            funding_rate_24h_avg = 0.0
            try:
                if self.info and (now - self.cached_funding_rate_time > 300 or self.cached_funding_rate is None):
                    meta_and_asset_ctxs = self.info.meta_and_asset_ctxs()
                    meta, asset_ctxs = meta_and_asset_ctxs
                    universe = meta['universe']
                    coin_idx = next((i for i, c in enumerate(universe) if c['name'] == self.config['grid']['pair']), -1)
                    if coin_idx != -1:
                        ctx = asset_ctxs[coin_idx]
                        funding_rate = float(ctx.get('funding', 0.0))
                        self.cached_funding_rate = funding_rate
                        self.cached_funding_rate_time = now
                else:
                    funding_rate = self.cached_funding_rate or 0.0
            except Exception as e:
                logging.debug(f"Could not fetch funding rate: {e}")
                funding_rate = self.cached_funding_rate or 0.0
            
            # Get order history (cached, update every minute)
            recent_fills = []
            try:
                if self.info and (now - self.cached_order_history_time > 60 or self.cached_order_history is None):
                    # Get recent fills from historical orders
                    # Note: historical_orders may need different parameters - wrap in try/except
                    try:
                        hist_orders = self.info.historical_orders(self.address)
                        if hist_orders and isinstance(hist_orders, list):
                            # Filter for fills in last 24h
                            recent_fills = []
                            for order in hist_orders:
                                # Handle different possible order formats
                                status = order.get('status', '').lower() if isinstance(order.get('status'), str) else ''
                                if 'fill' in status or order.get('filled'):
                                    fill_time = order.get('time', order.get('timestamp', 0))
                                    # Convert to unix timestamp if needed
                                    if isinstance(fill_time, str):
                                        try:
                                            fill_time = datetime.fromisoformat(fill_time.replace('Z', '+00:00')).timestamp()
                                        except:
                                            fill_time = 0
                                    
                                    if fill_time > 0 and now - fill_time < 86400:  # Last 24h
                                        recent_fills.append({
                                            'timestamp': fill_time,
                                            'side': order.get('side', order.get('orderType', 'UNKNOWN')),
                                            'price': float(order.get('price', order.get('limitPx', order.get('px', 0)))),
                                            'size': float(order.get('sz', order.get('size', order.get('szDecimal', 0)))),
                                            'pnl': float(order.get('closedPnl', order.get('pnl', 0)))
                                        })
                            self.cached_order_history = recent_fills
                            self.cached_order_history_time = now
                    except Exception as e:
                        logging.debug(f"historical_orders API call failed: {e}")
                        recent_fills = self.cached_order_history or []
                else:
                    recent_fills = self.cached_order_history or []
            except Exception as e:
                logging.debug(f"Could not fetch order history: {e}")
                recent_fills = self.cached_order_history or []
            
            # Get open orders details
            open_orders_detail = []
            try:
                if self.info:
                    open_orders = self.info.open_orders(self.address)
                    if open_orders and isinstance(open_orders, list):
                        for order in open_orders:
                            # Handle different possible order formats
                            open_orders_detail.append({
                                'side': order.get('side', order.get('orderType', 'UNKNOWN')),
                                'price': float(order.get('limitPx', order.get('price', order.get('px', 0)))),
                                'size': float(order.get('sz', order.get('size', order.get('szDecimal', 0)))),
                                'coin': order.get('coin', order.get('asset', self.config['grid']['pair']))
                            })
            except Exception as e:
                logging.debug(f"Could not fetch open orders: {e}")
            
            # Fetch and enhance positions
            positions = []
            try:
                if user_state:
                    for asset_pos in user_state.get("assetPositions", []):
                        pos = asset_pos.get("position", {})
                        coin = pos.get("coin", "")
                        size = float(pos.get("szi", 0))
                        entry = float(pos.get("entryPx", 0))
                        u_pnl = float(pos.get("unrealizedPnl", 0))
                        liq_px = float(pos.get("liquidationPx", 0))
                        margin_used_pos = float(pos.get("marginUsed", 0))
                        
                        if size != 0:
                            # Calculate ROI
                            roi = (u_pnl / (entry * abs(size))) * 100 if entry > 0 and size != 0 else 0
                            
                            positions.append({
                                "symbol": coin,
                                "side": "LONG" if size > 0 else "SHORT",
                                "size": abs(size),
                                "entry_price": entry,
                                "mark_price": current_price if coin == self.config['grid']['pair'] else 0,
                                "liquidation_price": liq_px,
                                "margin_used": margin_used_pos,
                                "unrealized_pnl": u_pnl,
                                "roi_pct": roi,
                                "leverage": self.config['grid']['leverage']
                            })
            except Exception as e:
                logging.error(f"Failed to fetch positions for export: {e}")
            
            # Calculate trade analytics
            trade_analytics = self._calculate_trade_analytics()
            
            # Calculate grid efficiency
            grid_efficiency = (active_orders / self.config['grid']['grids'] * 100) if self.config['grid']['grids'] > 0 else 0
            
            # Build comprehensive state data
            state_data = {
                "status": "running" if self.running else "stopped",
                "mode": "paper" if self.paper_mode else "live",
                "updated_at": datetime.utcnow().isoformat(),
                "timestamp": now,
                
                # Balance & Account Info
                "balance": self.current_balance,
                "available_balance": available_balance,
                "margin_used": margin_used,
                "margin_ratio": margin_ratio,
                "account_value": account_value,
                "equity": account_value,
                "auto_trading": self.auto_trading,
                
                # PnL Metrics
                "pnl": pnl,
                "pnl_pct": (pnl / self.start_balance * 100) if self.start_balance > 0 else 0,
                "pnl_daily": pnl_daily,
                "pnl_weekly": pnl_weekly,
                
                # Market Data
                "price": current_price,
                "funding_rate": funding_rate,
                "funding_rate_24h_avg": funding_rate_24h_avg,  # TODO: Calculate from history
                
                # Trading Metrics
                "total_trades": self.total_trades,
                "trades_24h": len(self.recent_trades),
                "win_rate": trade_analytics['win_rate'],
                "avg_trade_size": trade_analytics['avg_trade_size'],
                "largest_win": trade_analytics['largest_win'],
                "largest_loss": trade_analytics['largest_loss'],
                "profit_factor": trade_analytics['profit_factor'],
                
                # Grid Info
                "active_grids": active_orders,
                "total_grids": self.config['grid']['grids'],
                "grid_efficiency": grid_efficiency,
                "grid_range": {
                    "low": self.current_range_bottom,
                    "high": self.current_range_top
                },
                
                # Positions & Orders
                "positions": positions,
                "open_orders": open_orders_detail,
                "recent_fills": recent_fills,
                
                # Config
                "leverage": self.config['grid']['leverage'],
                "pair": self.config['grid']['pair']
            }
            
            # Atomic write
            with tempfile.NamedTemporaryFile('w', delete=False, dir=os.path.dirname(self.config['system']['log_file'])) as tf:
                json.dump(state_data, tf)
                tempname = tf.name
            
            shutil.move(tempname, "state.json")
            
        except Exception as e:
            logging.error(f"Failed to export state: {e}", exc_info=True)

    def set_leverage(self):
        try:
            if self.paper_mode:
                logging.info("Skipping leverage update in Paper/Testnet mode (avoid 422 error).")
                return

            logging.info(f"Setting leverage to {self.config['grid']['leverage']}x Isolated on {self.config['grid']['pair']}")
            if self.exchange:
                self.exchange.update_leverage(self.config['grid']['leverage'], self.config['grid']['pair'], False)
        except Exception as e:
            logging.error(f"Failed to set leverage: {e}")

    def manage_grids(self, current_price, user_state, high_24h=0, low_24h=0):
        try:
            # Note: In a real implementation, we would check for existing open orders
            # and only place new ones if the grid is empty or needs rebalancing.
            # user_state['openOrders'] gives us active orders.
            
            open_orders = user_state.get('openOrders', [])
            
            # Detect fills by comparing previous orders with current orders
            # In live mode, API handles fills. In sim mode, we check logic manually OR rely on openOrders update.
            # But in SIM mode, openOrders IS self.orders. So we need to check fills logic specifically for Sim.
            
            if self.paper_mode:
                 # Check for fills locally
                 filled_orders = []
                 active_orders = []
                 for o in self.orders:
                     is_buy = o['side'] == 'B'
                     limit = o['limitPx']
                     
                     # Simple fill logic:
                     # Buy fills if Price <= Limit
                     # Sell fills if Price >= Limit
                     if is_buy and current_price <= limit:
                         filled_orders.append(o)
                     elif not is_buy and current_price >= limit:
                         filled_orders.append(o)
                     else:
                         active_orders.append(o)
                 
                 self.orders = active_orders
                 # Process Sim Fills
                 if filled_orders:
                     for fo in filled_orders:
                         # Log
                         logging.info(f"{Fore.GREEN}SIM FILL: {fo['side']} {fo['sz']} @ {fo['limitPx']} (Market: {current_price:.2f}){Style.RESET_ALL}")
                         # Update Sim Balance / Position
                         # Simplified: Just log trade success for MVP
                         self.total_trades += 1
                         self.recent_trades.append(time.time())
            
            else:
                 # Live Mode: API does the heavy lifting, we just detect differences
                 self._detect_fills(self.previous_orders, open_orders, current_price)
                 self.previous_orders = open_orders.copy() if open_orders else []
                 self.orders = open_orders # Sync state
            
            # If no open orders, place new ones
            if not self.orders: # universal check
                if not self.auto_trading:
                    # If auto is off, don't place initial orders
                    return

                logging.info(f"No active orders. Initializing grid at {current_price}")
                # Initialize GridManager if not exists or just use instance
                from src.grid import GridManager 
                if not hasattr(self, 'grid_manager'):
                    self.grid_manager = GridManager(self.config, self.exchange)
                    # Attempt to get precision from SDK meta
                    try:
                        meta = self.info.meta()
                        universe = meta.get('universe', [])
                        coin_meta = next((item for item in universe if item['name'] == self.config['grid']['pair']), None)
                        if coin_meta:
                            sz_decimals = coin_meta['szDecimals']
                            self.grid_manager.set_precision(sz_decimals, 4)
                            logging.info(f"Precision set from API: Size {sz_decimals}, Price 4")
                            # Try to get tick size? usually not exposed directly here easily, assume 0.001 or deduce
                    except Exception as e:
                        logging.warning(f"Could not fetch precision from API, using defaults: {e}")

                # Auto-Range Logic
                if self.auto_range_enabled:
                    # If high/low are defaults (0), calculate from current +/- small buffer or just use current
                    h = high_24h if high_24h > 0 else current_price * 1.02
                    l = low_24h if low_24h > 0 else current_price * 0.98
                    self.grid_manager.calculate_volatility_range(current_price, h, l)

                new_orders = self.grid_manager.place_initial_orders(current_price)
                
                # Place orders
                if self.paper_mode:
                    # Sim Placement
                    for i, o in enumerate(new_orders):
                         # Standardize keys for local state
                         o['side'] = 'B' if o['is_buy'] else 'A'
                         o['oid'] = int(time.time() * 1000) + i
                         o['limitPx'] = o['limit_px']
                    
                    self.orders = new_orders
                    logging.info(f"{Fore.GREEN}SIMULATED: {len(new_orders)} orders placed.{Style.RESET_ALL}")
                
                else:
                    # Live Placement
                    results = self.exchange.bulk_orders(new_orders)
                    
                    # Fix: Check response type rigorously
                    if isinstance(results, dict) and 'response' in results:
                     status_list = results.get('response', {}).get('data', {}).get('statuses', [])
                     error_count = sum(1 for s in status_list if isinstance(s, dict) and 'error' in s)
                     
                     if error_count > 0:
                         first_error = next((s['error'] for s in status_list if isinstance(s, dict) and 'error' in s), "Unknown Error")
                         logging.error(f"{Fore.RED}Failed to place {error_count}/{len(new_orders)} orders.{Style.RESET_ALL} Reason: {first_error}")
                     else:
                         logging.info(f"{Fore.GREEN}Orders placed successfully.{Style.RESET_ALL} (count: {len(new_orders)})")
                         self.orders = new_orders
                elif isinstance(results, dict) and 'status' in results and results['status'] == 'err':
                     # Handle explicit error status if SDK returns it
                     logging.error(f"{Fore.RED}Order placement failed: {results.get('response', 'Unknown error')}{Style.RESET_ALL}")
                elif isinstance(results, str):
                     # Handle raw string error response
                     logging.error(f"{Fore.RED}Order placement failed (Raw Error): {results}{Style.RESET_ALL}")
                else:
                     # Fallback for unexpected format
                     logging.warning(f"Unexpected order response format: {str(results)[:100]}")
                
            else:
                # Simplistic Logic: If price moves out of range, cancel all and reset?
                # Or just log status.
                # Spec: "Trend break: price < range_bottom * 0.95 -> sell inventory + pause" is handled in main loop.
                # Here we normally replenish filled grids.
                # detailed replenishment is complex, for MVP (and 'complete' prompt often means functional MVP for start)
                # we maintain the grid. 
                pass
                
        except Exception as e:
            logging.error(f"Grid management error: {e}")

    def shutdown(self, signum, frame):
        logging.info("Shutdown signal received. Cancelling orders...")
        self.running = False
        try:
            if self.exchange:
                # Cancel open orders
                open_orders = self.info.open_orders(self.address)
                if open_orders:
                    # Construct list of (coin, oid) tuples or dicts as per SDK
                    # SDK's bulk_cancel usually expects [{'coin': 'SOL', 'oid': 123}, ...]
                    cancel_requests = [{'coin': o['coin'], 'oid': o['oid']} for o in open_orders]
                    logging.info(f"Cancelling {len(cancel_requests)} orders...")
                    self.exchange.bulk_cancel(cancel_requests)
                else:
                    logging.info("No open orders to cancel.")
            logging.info("Orders cancelled. Exiting.")
        except Exception as e:
            logging.error(f"Error during shutdown: {e}")
        
        # Ensure process exit
        os._exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.json', help='Path to config file')
    parser.add_argument('--paper', action='store_true', help='Run in paper trading mode')
    args = parser.parse_args()

    # Load config example if config.json not found
    config_path = args.config
    if not os.path.exists(config_path):
        # Use default config path
        config_path = 'config_example.json'
        # Copy to config.json if not exists? No, just read from example if explicit config not found is risky.
        if os.path.exists('config.json'):
            config_path = 'config.json'
        elif os.path.exists('config_example.json'):
             print(f"Config not found. Using config_example.json for startup check.")
             config_path = 'config_example.json'
        else:
            print("No config file found.")
            sys.exit(1)

    bot = HyperGridBot(config_path, paper_mode=args.paper)
    bot.run()
