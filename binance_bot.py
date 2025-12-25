#!/usr/bin/env python3
"""
HyperGridBot - Binance Futures Grid Trading Bot
A simplified grid trading bot using the Binance Futures API.
"""
import os
import sys
import json
import time
import signal
import logging
import argparse
import threading
import select
import sys
import subprocess
from datetime import datetime
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from colorama import init, Fore, Style

# Advanced Modules
from src.telegram_bot import TelegramNotifier
from src.scanner import MarketScanner
from src.websocket_manager import WebSocketManager

# Initialize colorama
init()

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.binance_adapter import BinanceAdapter
from src.exchange_adapter import OrderSide, OrderResult


def setup_logging(config):
    """Setup logging configuration with clean, readable output."""
    log_file = config.get('system', {}).get('log_file', 'logs/bot.log')
    log_level = config.get('system', {}).get('log_level', 'INFO')
    
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    # Custom formatter with colors and emojis
    class ColorFormatter(logging.Formatter):
        FORMATS = {
            logging.DEBUG: f"{Fore.CYAN}%(asctime)s │ DEBUG   │ %(message)s{Style.RESET_ALL}",
            logging.INFO: f"{Fore.WHITE}%(asctime)s │ {Fore.GREEN}INFO{Fore.WHITE}    │ %(message)s{Style.RESET_ALL}",
            logging.WARNING: f"{Fore.YELLOW}%(asctime)s │ ⚠ WARN  │ %(message)s{Style.RESET_ALL}",
            logging.ERROR: f"{Fore.RED}%(asctime)s │ ✗ ERROR │ %(message)s{Style.RESET_ALL}",
            logging.CRITICAL: f"{Fore.RED}{Style.BRIGHT}%(asctime)s │ ✗ CRIT  │ %(message)s{Style.RESET_ALL}",
        }
        
        def format(self, record):
            log_fmt = self.FORMATS.get(record.levelno, self.FORMATS[logging.INFO])
            formatter = logging.Formatter(log_fmt, datefmt='%H:%M:%S')
            return formatter.format(record)

    # Filter out keepalive noise
    class KeepAliveFilter(logging.Filter):
        def filter(self, record):
            return "keepalive_socket" not in record.getMessage()

    keep_alive_filter = KeepAliveFilter()
    
    # File handler with rotation (no colors) - 5MB max, keep 3 backups
    file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3)
    file_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    file_handler.addFilter(keep_alive_filter)
    
    # Console handler (with colors)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(ColorFormatter())
    console_handler.addFilter(keep_alive_filter)
    
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        handlers=[file_handler, console_handler]
    )
    
    # Silence noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("binance").setLevel(logging.ERROR)
    logging.getLogger("binance.websocket").setLevel(logging.CRITICAL)


class BinanceGridBot:
    """
    Grid trading bot for Binance Futures.
    Places buy orders below current price and sell orders above.
    When orders fill, replaces them on the opposite side.
    """
    
    # Trading presets for different risk profiles
    PRESETS = {
        "NEUTRAL": {"grids": 5, "spacing_pct": 0.0010, "leverage": 3},
        "ULTRA_SAFE": {"grids": 3, "spacing_pct": 0.0020, "leverage": 2},
        "AGGRESSIVE": {"grids": 8, "spacing_pct": 0.0005, "leverage": 5},
    }
    
    def __init__(self, config: dict, testnet: bool = True):
        self.config = config
        self.testnet = testnet
        self.running = True
        self.paused = False
        
        # Grid config
        grid_config = config['grid']
        self.symbol = grid_config['pair']  # e.g., "SOLUSDT"
        self.capital = float(grid_config['capital'])
        self.leverage = int(grid_config['leverage'])
        self.num_grids = int(grid_config.get('grids', 10))  # More grids = more trades
        self.spacing_pct = float(grid_config.get('spacing_pct', 0.002))  # 0.2% = ~$0.25 per level for micro trades
        self.buffer_pct = float(grid_config.get('buffer_pct', 0.02))    # 2% buffer for auto-range
        self.current_preset = grid_config.get('preset', 'NEUTRAL')  # Active preset name
        
        # State
        self.orders = []
        self.order_map = {}  # {order_id: {'side': OrderSide, 'price': float, 'quantity': float}}
        self.current_price = 0.0
        self.start_balance = 0.0
        self.current_balance = 0.0
        
        # Profit tracking
        self.realized_pnl = 0.0
        self.trade_count = 0
        self.pending_trades = {}  # {order_id: entry_price} - tracks entry for profit calc
        
        # Volatility tracking
        self.price_history = []  # Recent prices for ATR calculation
        self.base_quantity = 0.0  # Calculated during grid setup
        
        # Auto-range state
        self.grid_center = 0.0
        self.grid_upper = 0.0
        self.grid_lower = 0.0
        
        # Safety features
        safety_config = config.get('safety', {})
        self.max_drawdown_pct = float(safety_config.get('max_drawdown_pct', 0.10))  # 10% max loss
        self.max_position_size = float(safety_config.get('max_position_sol', 20.0))  # Max 20 SOL exposure
        self.crash_threshold = float(safety_config.get('crash_threshold_pct', 0.05))  # 5% crash detection
        self.daily_loss_limit = float(safety_config.get('daily_loss_limit_usd', 50.0))
        
        # Position tracking
        self.net_position = 0.0  # Net SOL position (positive = long, negative = short)
        self.avg_entry_price = 0.0 # Average entry price for unrealized PnL
        self.position_value = 0.0  # USD value of position
        self.peak_balance = 0.0  # For drawdown calculation
        self.crash_price_base = 0.0  # Price when started, for crash detection
        self.session_start_time = None
        self.daily_realized_pnl = 0.0
        
        # Profit compounding
        self.initial_capital = self.capital
        self.compound_threshold = float(config.get('grid', {}).get('compound_threshold', 5.0))  # Reinvest every $5
        self.last_compound_pnl = 0.0
        
        # Persistent state file
        self.state_file = 'state.json'
        
        # Setup logging
        setup_logging(config)
        
        # Initialize exchange adapter
        self._setup_exchange()
        
        # Load saved state (if exists)
        self._load_state()
        
        # Signal handlers
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)
    
    def _setup_exchange(self):
        """Initialize the Binance adapter."""
        binance_config = self.config.get('binance', {})
        
        # Try env vars first, then config
        api_key = os.getenv('BINANCE_API_KEY') or binance_config.get('api_key', '')
        api_secret = os.getenv('BINANCE_API_SECRET') or binance_config.get('api_secret', '')
        
        if not api_key or not api_secret:
            logging.error("Binance API key/secret not found. Set BINANCE_API_KEY and BINANCE_API_SECRET in .env")
            sys.exit(1)
        
        self.exchange = BinanceAdapter(
            api_key=api_key,
            api_secret=api_secret,
            testnet=self.testnet
        )
        
        # Initialize Telegram
        tg_config = self.config.get('telegram', {})
        if tg_config.get('enabled', False):
            token = os.getenv('TELEGRAM_TOKEN') or tg_config.get('token')
            chat_id = os.getenv('TELEGRAM_CHAT_ID') or tg_config.get('chat_id')
            if token and chat_id and "YOUR_" not in token:
                self.telegram = TelegramNotifier(token, chat_id)
                self.telegram.start_polling(
                    self._handle_telegram_command, 
                    self._handle_telegram_callback,
                    self._handle_telegram_text
                )
                self.telegram.send_message(f"🤖 *HyperGridBot Started* \nMode: {'TESTNET' if self.testnet else 'LIVE'}\nPair: {self.symbol}")
                self.telegram.send_main_menu()  # Show control panel with buttons
                logging.info("Telegram integration active")
            else:
                self.telegram = None
                logging.warning("Telegram enabled but token/chat_id missing or default.")
        else:
            self.telegram = None
            
        # Initialize Scanner
        scan_config = self.config.get('scanner', {})
        if scan_config.get('enabled', False):
            self.scanner = MarketScanner(
                exchange_adapter=self.exchange,
                whitelist=scan_config.get('whitelist', []),
                check_interval_minutes=scan_config.get('check_interval_minutes', 240)
            )
            logging.info("Market Scanner active")
        else:
            self.scanner = None
            
        self.ws_manager = None
        self.last_price_update = time.time()
        
        if not self.exchange.connect():
            logging.error("Failed to connect to Binance. Check API credentials.")
            sys.exit(1)
        
        logging.info(f"Connected to Binance {'Testnet' if self.testnet else 'Mainnet'}")
    
    def _save_state(self):
        """Save bot state to disk for persistence across restarts."""
        state = {
            'realized_pnl': self.realized_pnl,
            'trade_count': self.trade_count,
            'net_position': self.net_position,
            'capital': self.capital,
            'daily_realized_pnl': self.daily_realized_pnl,
            'last_compound_pnl': self.last_compound_pnl,
            'peak_balance': self.peak_balance,
            'order_map': {oid: {'side': o['side'].value, 'price': o['price'], 'quantity': o['quantity']} 
                         for oid, o in self.order_map.items()},
            'pending_trades': self.pending_trades,
            'saved_at': datetime.now().isoformat()
        }
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logging.warning(f"Failed to save state: {e}")
    
    def _load_state(self):
        """Load bot state from disk if available."""
        if not os.path.exists(self.state_file):
            logging.info("No saved state found, starting fresh")
            return
        
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
            
            self.realized_pnl = state.get('realized_pnl', 0.0)
            self.trade_count = state.get('trade_count', 0)
            self.net_position = state.get('net_position', 0.0)
            self.capital = state.get('capital', self.capital)
            self.daily_realized_pnl = state.get('daily_realized_pnl', 0.0)
            self.last_compound_pnl = state.get('last_compound_pnl', 0.0)
            self.peak_balance = state.get('peak_balance', 0.0)
            self.pending_trades = state.get('pending_trades', {})
            
            # Restore order map with OrderSide enum
            saved_orders = state.get('order_map', {})
            for oid, o in saved_orders.items():
                self.order_map[oid] = {
                    'side': OrderSide.BUY if o['side'] == 'buy' else OrderSide.SELL,
                    'price': o['price'],
                    'quantity': o['quantity']
                }
            
            saved_at = state.get('saved_at', 'unknown')
            logging.info(f"📂 Loaded state from {saved_at}")
            logging.info(f"   └─ Trades: {self.trade_count} │ PnL: ${self.realized_pnl:+.2f} │ Pos: {self.net_position:+.1f}")
        except Exception as e:
            logging.warning(f"Failed to load state: {e}")
    
    def _set_leverage(self):
        """Set leverage for the trading pair."""
        if self.exchange.set_leverage(self.symbol, self.leverage):
            logging.info(f"Leverage set to {self.leverage}x for {self.symbol}")
        else:
            logging.warning(f"Could not set leverage (might already be set)")
    
    def _get_market_info(self):
        """Get market info and store precision values."""
        info = self.exchange.get_market_info(self.symbol)
        self.tick_size = info.tick_size
        self.lot_size = info.lot_size
        self.min_notional = info.min_notional
        logging.info(f"Market info: tick_size={self.tick_size}, lot_size={self.lot_size}, min_notional={self.min_notional}")
    
    def _round_price(self, price: float) -> float:
        """Round price to tick size."""
        precision = max(0, -int(f"{self.tick_size:e}".split('e')[1]))
        return round(round(price / self.tick_size) * self.tick_size, precision)
    
    def _round_quantity(self, qty: float) -> float:
        """Round quantity to lot size."""
        precision = max(0, -int(f"{self.lot_size:e}".split('e')[1]))
        return round(round(qty / self.lot_size) * self.lot_size, precision)
    
    def _update_price_history(self):
        """Update price history for volatility calculation."""
        self.price_history.append(self.current_price)
        # Keep last 20 prices (about 3-4 minutes at 10s intervals)
        if len(self.price_history) > 20:
            self.price_history = self.price_history[-20:]
    
    def _calculate_volatility(self) -> float:
        """Calculate recent volatility as percentage."""
        if len(self.price_history) < 3:
            return 0.005  # Default 0.5% if not enough data
        
        # Calculate price returns
        returns = []
        for i in range(1, len(self.price_history)):
            ret = abs(self.price_history[i] - self.price_history[i-1]) / self.price_history[i-1]
            returns.append(ret)
        
        # Average absolute return
        avg_volatility = sum(returns) / len(returns)
        return avg_volatility
    
    def _get_volatility_multiplier(self) -> float:
        """Get position size multiplier based on volatility."""
        vol = self._calculate_volatility()
        
        if vol < 0.003:  # Low volatility (< 0.3%)
            return 0.5  # Smaller positions
        elif vol > 0.01:  # High volatility (> 1%)
            return 1.5  # Larger positions
        else:
            return 1.0  # Normal positions
    
    # ═══════════════════════════════════════════════════════════════
    # SAFETY FEATURES
    # ═══════════════════════════════════════════════════════════════
    
    def _check_crash_condition(self) -> bool:
        """Check if market is crashing - pause buying if so."""
        if self.crash_price_base == 0:
            self.crash_price_base = self.current_price
            return False
        
        price_drop = (self.crash_price_base - self.current_price) / self.crash_price_base
        
        if price_drop >= self.crash_threshold:
            logging.warning(f"⚠️ CRASH DETECTED: Price dropped {price_drop*100:.1f}% from ${self.crash_price_base:.2f}")
            return True
        
        # Update base slowly (moving average effect)
        self.crash_price_base = self.crash_price_base * 0.99 + self.current_price * 0.01
        return False
    
    def set_preset(self, preset_name: str) -> bool:
        """Apply a trading preset and recenter grid."""
        if preset_name not in self.PRESETS:
            logging.error(f"Unknown preset: {preset_name}. Available: {list(self.PRESETS.keys())}")
            return False
        
        preset = self.PRESETS[preset_name]
        self.num_grids = preset['grids']
        self.spacing_pct = preset['spacing_pct']
        self.leverage = preset['leverage']
        self.current_preset = preset_name
        
        # Apply leverage to exchange
        try:
            self.exchange.set_leverage(self.symbol, self.leverage)
            logging.info(f"🎚 Preset changed to {preset_name}: Grids={self.num_grids}, Spacing={self.spacing_pct*100:.2f}%, Leverage={self.leverage}x")
            
            # Recenter grid with new settings
            self._recenter_grid()
            return True
        except Exception as e:
            logging.error(f"Failed to apply preset {preset_name}: {e}")
            return False
    
    def _calculate_liquidation_price(self) -> float:
        """Calculate estimated liquidation price based on position and leverage."""
        if self.net_position <= 0 or self.avg_entry_price <= 0:
            return 0.0
        # For long position: liq_price ≈ entry * (1 - 1/leverage + maintenance_margin)
        # Simplified: liq_price ≈ entry * (1 - 0.9/leverage) accounting for ~10% buffer
        return self.avg_entry_price * (1 - 0.9 / self.leverage)
    
    def _check_liquidation_risk(self) -> bool:
        """Check if current price is approaching liquidation. Returns True if at risk."""
        liq_price = self._calculate_liquidation_price()
        if liq_price <= 0:
            return False
        
        distance_pct = (self.current_price - liq_price) / self.current_price
        if distance_pct < 0.10:  # Within 10% of liquidation
            logging.warning(f"🚨 LIQUIDATION RISK! Price ${self.current_price:.2f} is {distance_pct*100:.1f}% from liquidation @ ${liq_price:.2f}")
            return True
        elif distance_pct < 0.20:  # Within 20% - warning
            logging.warning(f"⚠️ Liquidation distance: {distance_pct*100:.1f}% (Liq @ ${liq_price:.2f})")
        return False
    
    def _check_position_limit(self, side: OrderSide, quantity: float) -> bool:
        """Check if placing this order would exceed position limits."""
        if side == OrderSide.BUY:
            new_position = self.net_position + quantity
        else:
            new_position = self.net_position - quantity
        
        if abs(new_position) > self.max_position_size:
            logging.warning(f"⚠️ POSITION LIMIT: Would exceed {self.max_position_size} SOL (current: {self.net_position:.1f})")
            return False
        return True
    
    def _check_drawdown(self) -> bool:
        """Check if we've hit max drawdown - stop trading if so."""
        if self.peak_balance == 0:
            self.peak_balance = self.current_balance
            return True
        
        # Update peak
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
        
        if self.current_balance <= 0:
            logging.warning("⚠️ Zero balance detected (possible API error). Skipping drawdown check.")
            return True

        # Check drawdown
        drawdown = (self.peak_balance - self.current_balance) / self.peak_balance
        if drawdown >= self.max_drawdown_pct:
            logging.error(f"🛑 MAX DRAWDOWN HIT: {drawdown*100:.1f}% loss from peak ${self.peak_balance:.2f} (Current: ${self.current_balance:.2f})")
            return False
        return True
    
    def _check_daily_loss_limit(self) -> bool:
        """Check if daily loss limit is exceeded."""
        if self.daily_realized_pnl < -self.daily_loss_limit:
            logging.error(f"🛑 DAILY LOSS LIMIT: Lost ${abs(self.daily_realized_pnl):.2f} today (limit: ${self.daily_loss_limit:.2f})")
            return False
        return True
    
    def _update_position(self, side: OrderSide, quantity: float):
        """Update net position after a fill."""
        if side == OrderSide.BUY:
            self.net_position += quantity
        else:
            self.net_position -= quantity
        
        self.position_value = abs(self.net_position) * self.current_price
    
    def _check_compound_profits(self):
        """Reinvest profits into capital when threshold is reached."""
        profit_since_compound = self.realized_pnl - self.last_compound_pnl
        
        if profit_since_compound >= self.compound_threshold:
            old_capital = self.capital
            self.capital += profit_since_compound
            self.last_compound_pnl = self.realized_pnl
            
            increase_pct = (self.capital / self.initial_capital - 1) * 100
            msg = f"💎 COMPOUND: +${profit_since_compound:.2f} → Capital now ${self.capital:.2f} (+{increase_pct:.1f}% from start)"
            logging.info(msg)
            if self.telegram:
                self.telegram.send_message(f"🚀 *Compound Event* \n{msg}")
    
    def _all_safety_checks_pass(self) -> bool:
        """Run all safety checks before allowing trades."""
        if not self._check_drawdown():
            self.paused = True
            return False
        
        if not self._check_daily_loss_limit():
            self.paused = True
            return False
        
        # Check funding rate periodically
        self._check_funding_rate()
        
        return True
    
    def _generate_grid_orders(self, center_price: float) -> list:
        """Generate grid orders with tiered sizing - small for micro trades, larger for big moves."""
        orders = []
        
        # Calculate base order size with 15% margin safety factor
        # This prevents "Margin is insufficient" errors by reserving headroom
        total_capital_usd = self.capital * self.leverage * 0.85  # 15% safety margin
        base_qty = (total_capital_usd / self.num_grids) / center_price
        
        # Apply volatility multiplier to base
        vol_mult = self._get_volatility_multiplier()
        
        # Generate orders above and below
        half_grids = self.num_grids // 2
        
        vol = self._calculate_volatility() * 100
        vol_label = "LOW" if vol_mult < 1 else ("HIGH" if vol_mult > 1 else "NORMAL")
        logging.info(f"📊 Grid: ${center_price:.2f} │ Vol: {vol:.2f}% ({vol_label}) │ Tiered sizing")
        
        for i in range(1, half_grids + 1):
            # Tiered sizing: inner grids smaller, outer grids larger
            # Level 1: 0.5x (micro trades, frequent)
            # Level 2: 1.0x (normal)
            # Level 3+: 1.5x (bigger moves, worth more)
            if i == 1:
                size_mult = 0.5  # Micro trades
            elif i == 2:
                size_mult = 1.0  # Normal
            else:
                size_mult = 1.5 + (i - 3) * 0.5  # Increasing for outer grids
            
            quantity = base_qty * vol_mult * size_mult
            quantity = max(quantity, self.lot_size)
            quantity = self._round_quantity(quantity)
            
            # Check minimum notional
            if quantity * center_price < self.min_notional:
                quantity = self._round_quantity(self.min_notional / center_price + self.lot_size)
            
            # Buy orders below
            buy_price = self._round_price(center_price * (1 - self.spacing_pct * i))
            orders.append({
                'symbol': self.symbol,
                'side': OrderSide.BUY,
                'quantity': quantity,
                'price': buy_price
            })
            logging.info(f"   📉 BUY  {quantity:.1f} @ ${buy_price:.2f} (-{self.spacing_pct * i * 100:.1f}%)")
            
            # Sell orders above
            sell_price = self._round_price(center_price * (1 + self.spacing_pct * i))
            orders.append({
                'symbol': self.symbol,
                'side': OrderSide.SELL,
                'quantity': quantity,
                'price': sell_price
            })
            logging.info(f"   📈 SELL {quantity:.1f} @ ${sell_price:.2f} (+{self.spacing_pct * i * 100:.1f}%)")
        
        # Store base for counter orders
        self.base_quantity = self._round_quantity(base_qty * vol_mult)
        
        return orders
    
    def _place_initial_grid(self):
        """Place the initial grid orders."""
        self.current_price = self.exchange.get_mark_price(self.symbol)
        
        if self.current_price == 0:
            logging.error("Failed to get mark price")
            return False
        
        logging.info(f"📍 Current {self.symbol} price: ${self.current_price:.2f}")
        
        # Cancel any existing orders
        self.exchange.cancel_all_orders(self.symbol)
        
        # Set grid center and bounds for auto-range
        self.grid_center = self.current_price
        half_grids = self.num_grids // 2
        self.grid_upper = self.current_price * (1 + self.spacing_pct * half_grids + self.buffer_pct)
        self.grid_lower = self.current_price * (1 - self.spacing_pct * half_grids - self.buffer_pct)
        
        logging.info(f"🎯 Auto-range: ${self.grid_lower:.2f} - ${self.grid_upper:.2f}")
        
        # Generate and place orders
        grid_orders = self._generate_grid_orders(self.current_price)
        
        if not grid_orders:
            logging.error("No grid orders generated")
            return False
        
        logging.info(f"Placing {len(grid_orders)} grid orders...")
        
        results = self.exchange.bulk_place_orders(grid_orders)
        
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        
        if successful > 0:
            logging.info(f"✓ Placed {successful} orders successfully")
        if failed > 0:
            logging.warning(f"✗ Failed to place {failed} orders")
            for r in results:
                if not r.success:
                    logging.error(f"  Order failed: {r.error}")
        
        # Store order details in order_map for tracking
        self.order_map = {}
        for i, r in enumerate(results):
            if r.success and r.order_id:
                order = grid_orders[i]
                self.order_map[r.order_id] = {
                    'side': order['side'],
                    'price': order['price'],
                    'quantity': order['quantity']
                }
        
        self.orders = list(self.order_map.keys())
        
        return successful > 0
    
    def _check_and_replenish(self):
        """Check for filled orders and place counter orders with profit tracking and safety checks."""
        open_orders = self.exchange.get_open_orders(self.symbol)
        open_ids = {str(o['orderId']) for o in open_orders}
        
        # Find filled orders (were in self.order_map but not in open_orders)
        filled_ids = [oid for oid in self.order_map if oid not in open_ids]
        
        if not filled_ids:
            return
        
        # Check crash condition before processing BUY fills
        is_crashing = self._check_crash_condition()
        
        # Process each filled order
        for oid in filled_ids:
            order_info = self.order_map.get(oid)
            if not order_info:
                continue
                
            filled_side = order_info['side']
            filled_price = order_info['price']
            quantity = order_info['quantity']
            
            # Track position change
            self._update_position(filled_side, quantity)
            
            # Get dynamic size based on current volatility
            vol_mult = self._get_volatility_multiplier()
            new_qty = self._round_quantity(self.base_quantity * vol_mult) if self.base_quantity > 0 else quantity
            
            # Calculate profit if this was a counter-order (completing a round trip)
            entry_price = self.pending_trades.pop(oid, None)
            if entry_price:
                # This is a closing trade
                if filled_side == OrderSide.SELL:
                    profit = (filled_price - entry_price) * quantity
                else:
                    profit = (entry_price - filled_price) * quantity
                
                self.realized_pnl += profit
                self.daily_realized_pnl += profit
                self.trade_count += 1
                
                emoji = "✅" if profit > 0 else "❌"
                log_msg = f"{emoji} TRADE #{self.trade_count}: {filled_side.value.upper()} @ ${filled_price:.2f}\n   └─ Profit: ${profit:+.2f} │ Total: ${self.realized_pnl:+.2f}"
                logging.info(f"{emoji} TRADE #{self.trade_count}: {filled_side.value.upper()} @ ${filled_price:.2f}")
                logging.info(f"   └─ Profit: ${profit:+.2f} │ Total: ${self.realized_pnl:+.2f}")
                
                if self.telegram:
                    self.telegram.send_message(f"{emoji} *Order Filled*\nPair: `{self.symbol}`\nSide: `{filled_side.value.upper()}`\nPrice: `${filled_price:.2f}`\nProfit: `${profit:+.2f}`")

                
                # Check for profit compounding
                self._check_compound_profits()
            else:
                # This is an opening trade - log it
                logging.info(f"🔔 {filled_side.value.upper()} FILLED @ ${filled_price:.2f} ({quantity} SOL)")
            
            # Determine counter order
            if filled_side == OrderSide.BUY:
                counter_price = self._round_price(filled_price * (1 + self.spacing_pct))
                counter_side = OrderSide.SELL
            else:
                counter_price = self._round_price(filled_price * (1 - self.spacing_pct))
                counter_side = OrderSide.BUY
            
            # Safety check: Don't buy during crash
            if counter_side == OrderSide.BUY and is_crashing:
                logging.warning(f"   └─ ⚠️ Counter BUY SKIPPED (crash protection)")
                del self.order_map[oid]
                continue
            
            # Safety check: Position limit
            if not self._check_position_limit(counter_side, new_qty):
                logging.warning(f"   └─ ⚠️ Counter {counter_side.value.upper()} SKIPPED (position limit)")
                del self.order_map[oid]
                continue
            
            logging.info(f"   └─ Counter {counter_side.value.upper()} @ ${counter_price:.2f}")
            
            # Place the counter order
            result = self.exchange.place_limit_order(
                symbol=self.symbol,
                side=counter_side,
                quantity=new_qty,
                price=counter_price
            )
            
            if result.success:
                # Track the new order and store entry for profit calc
                self.order_map[result.order_id] = {
                    'side': counter_side,
                    'price': counter_price,
                    'quantity': new_qty
                }
                # Store the filled price as entry for the counter order
                self.pending_trades[result.order_id] = filled_price
            else:
                logging.error(f"   ✗ Counter order failed: {result.error}")
            
            # Remove filled order from tracking
            del self.order_map[oid]
        
        # Update our list
        self.orders = list(self.order_map.keys())
        
        # Save state after processing fills
        if filled_ids:
            self._save_state()
    
    def _update_balance(self):
        """Update account balance."""
        balance = self.exchange.get_account_balance()
        self.current_balance = balance.total_balance
        
        if self.start_balance == 0:
            self.start_balance = self.current_balance
        
        pnl = self.current_balance - self.start_balance
        pnl_pct = (pnl / self.start_balance * 100) if self.start_balance > 0 else 0
        
        return pnl, pnl_pct
    
    def print_status(self):
        """Print current bot status."""
        pnl, pnl_pct = self._update_balance()
        
        status_color = Fore.GREEN if not self.paused else Fore.YELLOW
        pnl_color = Fore.GREEN if pnl >= 0 else Fore.RED
        
        print(f"\n{status_color}═══════════════════════════════════════{Style.RESET_ALL}")
        print(f"{status_color}  HyperGridBot - Binance Futures{Style.RESET_ALL}")
        print(f"{status_color}═══════════════════════════════════════{Style.RESET_ALL}")
        print(f"  Status: {'RUNNING' if not self.paused else 'PAUSED'}")
        print(f"  Mode: {'TESTNET' if self.testnet else 'LIVE'}")
        print(f"  Symbol: {self.symbol}")
        print(f"  Price: ${self.current_price:.2f}")
        print(f"  Lev: {self.leverage}x")
        print(f"  Eq (Real): ${self.current_balance:.2f}")
        print(f"  Buy Power: ${self.current_balance * self.leverage:.2f}")
        print(f"  PnL: {pnl_color}${pnl:+.2f} ({pnl_pct:+.2f}%){Style.RESET_ALL}")
        print(f"  Active Orders: {len(self.orders)}")
        print(f"{status_color}═══════════════════════════════════════{Style.RESET_ALL}\n")
    
    def _try_auto_resume(self):
        """Attempt to resume bot if market conditions are safe."""
        # Only try every 5 minutes
        now = time.time()
        if not hasattr(self, '_last_resume_check'):
            self._last_resume_check = 0
            
        if now - self._last_resume_check < 300:
            return

        self._last_resume_check = now
        
        # 1. Check volatility
        vol = self._get_volatility_multiplier()
        if vol < 1.5: # < 1.5% volatility usually
             # 2. Check if balance is healthy
             if self.current_balance > 0:
                 logging.info(f"✅ Auto-Resume: Volatility safe ({vol:.2f}). Resuming trading.")
                 self.paused = False
                 self.paused = False
                 # Reset panic flags if any
                 self.state_file_valid = True # Hypothetical flag reset

    def _handle_telegram_command(self, text):
        """Handle incoming Telegram commands."""
        cmd = text.lower().strip()
        
        if cmd == '/status':
            pnl, pnl_pct = self._update_balance()
            return (
                f"📊 *Status Report*\n"
                f"Pair: `{self.symbol}`\n"
                f"Price: `${self.current_price:.2f}`\n"
                f"PnL: `${pnl:.2f}` ({pnl_pct:.2f}%)\n"
                f"Pos: `{self.net_position}` | Grids: `{len(self.orders)}`\n"
                f"State: `{'PAUSED' if self.paused else 'RUNNING'}`"
            )
            
        elif cmd == '/balance':
            pnl, _ = self._update_balance()
            return (
                f"💰 *Balance Info*\n"
                f"Equity: `${self.current_balance:.2f}`\n"
                f"Unrealized PnL: `${pnl:.2f}`\n"
                f"Leverage: `{self.leverage}x`"
            )
            
        elif cmd == '/stop':
            self.paused = True
            return "🛑 Bot PAUSED by remote command."
            
        elif cmd == '/start' or cmd == '/menu':
            if self.telegram:
                self.telegram.send_main_menu()
            return None
            
        elif cmd == '/logs':
            # Read last 10 lines of log file
            try:
                log_file = self.config['system'].get('log_file', 'logs/bot.log')
                with open(log_file, 'r') as f:
                    lines = f.readlines()[-10:]
                return "📜 *Recent Logs:*\n" + "".join(lines)
            except Exception as e:
                return f"⚠️ Could not read logs: {e}"
        
        return None

    def _handle_telegram_callback(self, callback_data):
        """Handle inline keyboard button presses from Telegram."""
        
        if callback_data == "status":
            unrealized = (self.current_price - self.avg_entry_price) * self.net_position if self.net_position else 0
            total = self.realized_pnl + unrealized
            return (
                f"📊 *Status Report*\n"
                f"Pair: `{self.symbol}`\n"
                f"Price: `${self.current_price:.2f}`\n"
                f"Total PnL: `${total:+.2f}`\n"
                f"Preset: `{self.current_preset}`\n"
                f"State: `{'PAUSED' if self.paused else 'RUNNING'}`"
            )
        
        elif callback_data == "pnl":
            unrealized = (self.current_price - self.avg_entry_price) * self.net_position if self.net_position else 0
            total = self.realized_pnl + unrealized
            return (
                f"💰 *PnL Breakdown*\n"
                f"Realized: `${self.realized_pnl:+.2f}`\n"
                f"Unrealized: `${unrealized:+.2f}`\n"
                f"*Total: `${total:+.2f}`*\n"
                f"Position: `{self.net_position}` | Trades: `{self.trade_count}`"
            )
        
        elif callback_data == "pause":
            self.paused = True
            return "⏸ *Bot PAUSED*\nTrading halted. Use Resume to continue."
        
        elif callback_data == "resume":
            self.paused = False
            return "▶️ *Bot RESUMED*\nTrading active."
        
        elif callback_data == "preset_menu":
            if self.telegram:
                self.telegram.send_preset_menu()
            return None
        
        elif callback_data.startswith("preset_"):
            preset_name = callback_data.replace("preset_", "")
            if self.set_preset(preset_name):
                return f"✅ Preset changed to *{preset_name}*\nGrid recentered."
            else:
                return f"❌ Failed to set preset: {preset_name}"
        
        elif callback_data == "main_menu":
            if self.telegram:
                self.telegram.send_main_menu()
            return None
        
        elif callback_data == "help":
            return (
                "❓ *HyperGridBot Help*\n\n"
                "📊 *Status* - Current price, PnL, state\n"
                "📈 *PnL* - Detailed profit breakdown\n"
                "⏸ *Pause* - Stop trading (keeps positions)\n"
                "▶️ *Resume* - Resume trading\n"
                "🎚 *Preset* - Change strategy\n"
                "  • NEUTRAL: Balanced\n"
                "  • ULTRA_SAFE: Conservative\n"
                "  • AGGRESSIVE: High risk/reward"
            )
        
        elif callback_data == "custom_menu":
            if self.telegram:
                self.telegram.send_custom_menu()
            return None
        
        elif callback_data == "custom_leverage":
            if self.telegram:
                self.telegram.set_user_state(chat_id, self.telegram.STATE_AWAITING_LEVERAGE)
            return "📊 *Set Custom Leverage*\n\nEnter a value between 1 and 10:"
        
        elif callback_data == "custom_grids":
            if self.telegram:
                self.telegram.set_user_state(chat_id, self.telegram.STATE_AWAITING_GRIDS)
            return "📈 *Set Grid Count*\n\nEnter a value between 3 and 20:"
        
        elif callback_data == "custom_spacing":
            if self.telegram:
                self.telegram.set_user_state(chat_id, self.telegram.STATE_AWAITING_SPACING)
            return "📏 *Set Spacing %*\n\nEnter a value between 0.05 and 1.0 (e.g., 0.15 for 0.15%):"
        
        elif callback_data.startswith("pair_"):
            pair = callback_data.replace("pair_", "")
            if pair in ["BNBUSDT", "SOLUSDT", "ETHUSDT"]:
                self.symbol = pair
                return f"✅ Trading pair changed to *{pair}*"
            return "❌ Invalid pair"
        
        return None

    def _handle_telegram_text(self, chat_id, text, state, data):
        """Handle multi-step text input for custom settings."""
        from src.telegram_bot import TelegramNotifier
        
        if state == TelegramNotifier.STATE_AWAITING_LEVERAGE:
            try:
                leverage = int(text.strip())
                if 1 <= leverage <= 10:
                    self.leverage = leverage
                    self.exchange.set_leverage(self.symbol, leverage)
                    self._recenter_grid()
                    if self.telegram:
                        self.telegram.clear_user_state(chat_id)
                    return f"✅ Leverage set to *{leverage}x*\nGrid recentered."
                else:
                    return "❌ Leverage must be between 1 and 10. Try again:"
            except ValueError:
                return "❌ Please enter a valid number (1-10):"
        
        elif state == TelegramNotifier.STATE_AWAITING_GRIDS:
            try:
                grids = int(text.strip())
                if 3 <= grids <= 20:
                    self.num_grids = grids
                    self._recenter_grid()
                    if self.telegram:
                        self.telegram.clear_user_state(chat_id)
                    return f"✅ Grid count set to *{grids}*\nGrid recentered."
                else:
                    return "❌ Grid count must be between 3 and 20. Try again:"
            except ValueError:
                return "❌ Please enter a valid number (3-20):"
        
        elif state == TelegramNotifier.STATE_AWAITING_SPACING:
            try:
                spacing = float(text.strip())
                if 0.05 <= spacing <= 1.0:
                    self.spacing_pct = spacing / 100  # Convert to decimal
                    self._recenter_grid()
                    if self.telegram:
                        self.telegram.clear_user_state(chat_id)
                    return f"✅ Spacing set to *{spacing}%*\nGrid recentered."
                else:
                    return "❌ Spacing must be between 0.05 and 1.0. Try again:"
            except ValueError:
                return "❌ Please enter a valid number (e.g., 0.15):"
        
        return None

    def console_listener(self):
        """Background thread to listen for console commands."""
        while self.running:
            try:
                if sys.stdin in select.select([sys.stdin], [], [], 1.0)[0]:
                    cmd_line = sys.stdin.readline().strip().lower()
                    if cmd_line:
                        self._handle_command(cmd_line)
            except Exception:
                pass
    


    def _check_funding_rate(self):
        """Monitor funding rate to warn about expensive positions."""
        # Simple timer check (run every 60 mins)
        now = time.time()
        if not hasattr(self, '_last_funding_check'):
            self._last_funding_check = 0
            
        if now - self._last_funding_check < 3600:
            return

        try:
            funding = self.exchange.client.futures_funding_rate(symbol=self.symbol, limit=1)
            if funding:
                rate = float(funding[0]['fundingRate']) * 100
                self._last_funding_check = now
                
                # Warn if expensive
                if rate > 0.05 and self.net_position > 0:
                    logging.warning(f"⚠️ HIGH FUNDING RATE: {rate:.4f}%. Paying high fees to hold LONG.")
                elif rate < -0.05 and self.net_position < 0:
                    logging.warning(f"⚠️ NEGATIVE FUNDING RATE: {rate:.4f}%. Paying high fees to hold SHORT.")
                else:
                    logging.info(f"ℹ️ Funding Rate: {rate:.4f}%")
        except Exception as e:
            logging.error(f"Failed to check funding rate: {e}")

    def _handle_command(self, cmd: str):
        """Handle console commands."""
        if cmd in ['/status', 'status']:
            self.print_status()
        elif cmd in ['/stop', 'stop']:
            self.paused = True
            logging.warning("Bot PAUSED")
        elif cmd in ['/start', 'start']:
            self.paused = False
            logging.info("Bot RESUMED")
        elif cmd.startswith('/pair'):
            parts = cmd.split()
            if len(parts) > 1:
                new_symbol = parts[1].upper()
                self.switch_pair(new_symbol)
            else:
                print("Usage: /pair <SYMBOL> (e.g. /pair BTCUSDT)")
        elif cmd in ['/statistics', '/stats', 'stats']:
            self.print_statistics()
        elif cmd in ['/clear', 'clear']:
            print("\033c", end="")
        elif cmd in ['/help', 'help', '/commands']:
            print("\nAvailable Commands:")
            print("  /status  - Show bot status")
            print("  /stats   - Show detailed statistics")
            print("  /start   - Resume trading")
            print("  /stop    - Pause trading")
            print("  /pair [S]- Switch trading pair (e.g. /pair BTCUSDT)")
            print("  /clear   - Clear screen")
            print("  /help    - Show this menu\n")

        else:
            print(f"Unknown command: {cmd}")

    def print_statistics(self):
        """Print detailed session statistics."""
        elapsed = time.time() - self.session_start_time
        hours = elapsed / 3600
        days = hours / 24
        
        # Calculations
        roi_pct = (self.realized_pnl / self.capital) * 100 if self.capital else 0.0
        trades_per_hour = self.trade_count / hours if hours > 0 else 0
        avg_profit_trade = self.realized_pnl / self.trade_count if self.trade_count > 0 else 0
        daily_proj = (self.realized_pnl / hours) * 24 if hours > 0 else 0
        monthly_proj = daily_proj * 30
        
        # Drawdown from peak
        dd_val = self.peak_balance - self.current_balance
        dd_pct = (dd_val / self.peak_balance * 100) if self.peak_balance > 0 else 0.0
        
        print(f"\n{Fore.CYAN}═══════════════════════════════════════")
        print(f"  📊 DETAILED STATISTICS ({self.symbol})")
        print(f"═══════════════════════════════════════{Style.RESET_ALL}")
        
        print(f"{Fore.YELLOW}⏱️  Runtime:{Style.RESET_ALL}      {int(hours)}h {int((hours%1)*60)}m")
        print(f"{Fore.YELLOW}💰 Total Profit:{Style.RESET_ALL} ${self.realized_pnl:+.2f} ({Fore.GREEN}+{roi_pct:.2f}%{Style.RESET_ALL})")
        print(f"{Fore.YELLOW}📉 Drawdown:{Style.RESET_ALL}     ${dd_val:.2f} ({dd_pct:.2f}%)")
        print(f"{Fore.YELLOW}🧱 Avg Trade:{Style.RESET_ALL}    ${avg_profit_trade:.2f}")
        print(f"{Fore.YELLOW}⚡ Velocity:{Style.RESET_ALL}     {trades_per_hour:.1f} trades/hr")
        
        print(f"\n{Fore.MAGENTA}🔮 PROJECTIONS:{Style.RESET_ALL}")
        print(f"   └─ Daily:    ${daily_proj:+.2f} / day")
        print(f"   └─ Monthly:  ${monthly_proj:+.2f} / month")
        print(f"   └─ Annual:   ${monthly_proj * 12:+.2f} / year")
        
        print(f"\n{Fore.MAGENTA}🛡️  SAFETY HEALTH:{Style.RESET_ALL}")
        buffer_pts = (self.current_price * self.buffer_pct)
        print(f"   └─ Position: {self.net_position} SOL (Max: {self.max_position_size})")
        print(f"   └─ Buffer:   {self.buffer_pct*100}% (${buffer_pts:.2f})")
        print(f"═══════════════════════════════════════\n")
    
    def switch_pair(self, new_symbol):
        """Switch trading pair dynamically."""
        if new_symbol == self.symbol:
            logging.info(f"Already trading {new_symbol}")
            return
            
        logging.info(f"🔄 Switching pair to {new_symbol}...")
        
        # 1. Cancel existing orders
        cancelled = self.exchange.cancel_all_orders(self.symbol)
        logging.info(f"Cancelled {cancelled} orders for {self.symbol}")
        
        # 2. Update symbol
        self.symbol = new_symbol
        self.config['grid']['pair'] = new_symbol
        
        # 3. Reset bot state for new pair
        self.orders = []
        self.order_map = {}
        self.pending_trades = {}
        self.price_history = []
        self.net_position = 0.0
        self.realized_pnl = 0.0
        self.trade_count = 0
        self.start_balance = self.current_balance  # Reset baseline
        
        # 4. Get new market info/leverage
        self._set_leverage()
        self._get_market_info()
        
        # 5. Place new grid
        time.sleep(1) # Safety pause
        self.current_price = self.exchange.get_mark_price(self.symbol)
        logging.info(f"📍 New price for {self.symbol}: ${self.current_price:.2f}")
        
        if self._place_initial_grid():
            logging.info(f"✅ Successfully switched to {self.symbol}")
            # Reset session start time to show stats for this pair
            self.session_start_time = time.time()
        else:
            logging.error(f"❌ Failed to place grid for {self.symbol}")

    def shutdown(self, signum=None, frame=None):
        """Graceful shutdown - close positions and save state."""
        logging.info("Shutting down...")
        self.running = False
        
        # Cancel all pending orders first
        cancelled = self.exchange.cancel_all_orders(self.symbol)
        logging.info(f"Cancelled {cancelled} orders")
        
        # Close any open positions with market order
        if abs(self.net_position) > 0.1:
            logging.info(f"Closing position: {self.net_position:+.1f} SOL")
            try:
                if self.net_position > 0:
                    # Long position - sell to close
                    close_qty = self._round_quantity(abs(self.net_position))
                    result = self.exchange.place_market_order(self.symbol, OrderSide.SELL, close_qty)
                else:
                    # Short position - buy to close
                    close_qty = self._round_quantity(abs(self.net_position))
                    result = self.exchange.place_market_order(self.symbol, OrderSide.BUY, close_qty)
                
                if result.success:
                    logging.info(f"✅ Position closed at market")
                    self.net_position = 0.0
                else:
                    logging.warning(f"⚠️ Failed to close position: {result.error}")
            except Exception as e:
                logging.warning(f"⚠️ Error closing position: {e}")
        
        # Save final state
        self._save_state()
        logging.info("💾 State saved")
        
        logging.info("Shutdown complete")
        sys.exit(0)
    
    def run(self):
        """Main execution method (Event-Driven via WebSockets)."""
        logging.info(f"🚀 Starting BinanceGridBot on {self.symbol}...")
        logging.info(f"   └─ Capital: ${self.capital} (Leverage: {self.leverage}x)")
        logging.info(f"   └─ Grids: {self.num_grids} (Spacing: {self.spacing_pct*100:.2f}%)")
        
        # Initial Balance & Grid
        self._set_leverage()
        self._get_market_info()

        # Place initial grid
        if not self._place_initial_grid():
            logging.error("Failed to place initial grid. Exiting.")
            return
        
        self.last_status_time = time.time()
        self.print_status()
        
        # Start WebSockets
        self.ws_manager = WebSocketManager(
            self.exchange.api_key, 
            self.exchange.api_secret, 
            testnet=self.exchange.testnet
        )
        self.ws_manager.start(
            self.symbol, 
            self._on_price_update, 
            self._on_user_update
        )
        
        try:
            while self.running:
                # Keep main thread alive
                time.sleep(10)
                
                # Check for stale connection (Heartbeat) - 60s
                if time.time() - self.last_price_update > 60:
                    logging.warning("⚠️ No price updates for 60s! Reconnecting WebSockets...")
                    self.ws_manager.stop()
                    time.sleep(1)
                    self.ws_manager.start(self.symbol, self._on_price_update, self._on_user_update)
                    self.last_price_update = time.time()

                # Periodic Status Log (every 5 minutes)
                if time.time() - self.last_status_time > 300:
                    try:
                        # Local PnL Calculation (Est.)
                        unrealized_pnl = 0.0
                        if self.net_position != 0 and self.avg_entry_price:
                            unrealized_pnl = (self.current_price - self.avg_entry_price) * self.net_position
                        
                        lower_bound = min([o['price'] for o in self.order_map.values()], default=0)
                        upper_bound = max([o['price'] for o in self.order_map.values()], default=0)
                        
                        # Total PnL
                        total_pnl = self.realized_pnl + unrealized_pnl
                        
                        status_msg = (
                            f"🕒 STATUS | {self.symbol}: ${self.current_price:.2f} | "
                            f"📊 Total: ${total_pnl:+.2f} | "
                            f"💰 Real: ${self.realized_pnl:+.2f} | "
                            f"📉 Unreal: ${unrealized_pnl:+.2f} | "
                            f"💼 Pos: {self.net_position} | "
                            f"� {self.current_preset}"
                        )
                        logging.info(status_msg)
                        self.last_status_time = time.time()
                        
                        # Check liquidation risk
                        self._check_liquidation_risk()
                        
                        # Auto-Recenter Logic (Infinite Grid)
                        # If price deviates significantly from grid range (e.g. out of bounds > spacing)
                        # We cancel all and Reset.
                        # Buffer: use 2x spacing as buffer to avoid jitter at edges
                        buffer = (upper_bound - lower_bound) / self.num_grids # rough spacing
                        
                        if self.current_price > upper_bound + buffer or self.current_price < lower_bound - buffer:
                            logging.info(f"🔄 Price ${self.current_price:.2f} out of range (${lower_bound:.2f}-${upper_bound:.2f}). Auto-Recentering...")
                            self._recenter_grid()

                    except Exception as e:
                        logging.error(f"Status log error: {e}")

        except KeyboardInterrupt:
            self.shutdown()
        except Exception as e:
            logging.error(f"Critical error in main loop: {e}")
            # Auto-restart on critical websocket failure
            self.shutdown() 
            time.sleep(5)
            os.execv(sys.executable, ['python3'] + sys.argv)

    def _recenter_grid(self):
        """Cancel all orders and place a new grid around current price."""
        try:
            # 1. Cancel All
            logging.info("   └─ Cancelling all open orders...")
            self.exchange.cancel_all_orders(self.symbol)
            self.order_map = {}
            
            # 2. Dynamic Compounding: Use Realized Profit
            # We assume initial capital was what we started with. 
            # We add realized PnL to logic capital for sizing.
            # (Note: real balance check would be safer, but we are avoiding API calls)
            # self.capital is updated for the sizing logic
            current_equity_est = self.initial_capital + self.realized_pnl
            if current_equity_est > self.capital:
                logging.info(f"   └─ Compounding: Increasing capital base from ${self.capital:.2f} to ${current_equity_est:.2f}")
                self.capital = current_equity_est
            
            # 3. Re-Calculate and Place Grid
            # The _place_initial_grid status method will use self.capital and self.current_price
            if self._place_initial_grid():
                logging.info("   └─ ✅ Grid successfully recentered!")
            else:
                logging.error("   └─ ❌ Failed to recenter grid.")
        except Exception as e:
            logging.error(f"failed to recenter grid: {e}")

    def _on_price_update(self, price):
        """Callback for real-time price updates from WebSocket."""
        self.current_price = price
        self.last_price_update = time.time()
        # Note: We rely on Order Updates for trading logic, not price ticks.

    def _on_user_update(self, type, data):
        """Callback for order/account updates from WebSocket."""
        if type == 'ORDER':
            # data is the 'o' object from Binance stream
            status = data.get('X') # Order Status
            side = data.get('S')   # BUY or SELL
            
            if status == 'FILLED':
                fill_price = float(data.get('L')) # Last filled price
                qty = float(data.get('l'))        # Last filled qty
                logging.info(f"🔔 {side} FILLED @ ${fill_price} ({qty} {self.symbol})")
                
                # Update stats
                self.trade_count += 1
                
                # Place Counter Order Immediately
                self._handle_fill_event(side, fill_price, qty)
                
        elif type == 'ACCOUNT':
            # Optionally update balance here if needed
            pass 

    def _handle_fill_event(self, side, price, qty):
        """React to a fill by placing a counter-order and updating PnL."""
        # Simple logic: If BUY filled, place SELL higher. If SELL filled, place BUY lower.
        spacing = price * self.spacing_pct
        
        # Calculate approximate realized profit from this grid cycle
        # We assume if we Sell, we sold something we bought lower.
        # If we Buy, we are loading up for a future sell.
        # Strict grid PnL is realized on the closing leg.
        # For simplicity in this event loop: 
        # Every matched pair (Buy+Sell) generates profit = price * spacing_pct.
        # We count profit on the SELL side for Long grids, or logic based on reducing pos.
        # Let's just track "Grid Profit" as (Value * Spacing) whenever a trade happens, 
        # as it represents capturing a spread.
        trade_profit = (price * qty) * self.spacing_pct
        self.realized_pnl += trade_profit
        
        try:
            if side == 'BUY':
                # Place Sell
                sell_price = price + spacing
                self.exchange.place_limit_order(self.symbol, OrderSide.SELL, qty, sell_price)
                logging.info(f"   └─ Placed Counter SELL @ ${sell_price:.2f}")
                
            elif side == 'SELL':
                # Place Buy
                buy_price = price - spacing
                self.exchange.place_limit_order(self.symbol, OrderSide.BUY, qty, buy_price)
                logging.info(f"   └─ Placed Counter BUY @ ${buy_price:.2f}")
        except Exception as e:
            logging.error(f"Failed to place counter order: {e}")

    def shutdown(self, signum=None, frame=None):
        self.running = False
        if self.ws_manager:
            self.ws_manager.stop()
        logging.info("Shutdown complete.")
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description='HyperGridBot - Binance Futures')
    parser.add_argument('--config', default='config.json', help='Path to config file')
    parser.add_argument('--testnet', action='store_true', default=True, help='Use Binance testnet')
    parser.add_argument('--live', action='store_true', help='Use Binance mainnet (REAL MONEY)')
    args = parser.parse_args()
    
    # Load .env
    load_dotenv()
    
    # Load config
    if not os.path.exists(args.config):
        print(f"Config file not found: {args.config}")
        print("Copy config_example.json to config.json and update your settings.")
        sys.exit(1)
    
    with open(args.config) as f:
        config = json.load(f)
    
    # Determine testnet mode
    testnet = not args.live
    
    if not testnet:
        print(f"\n{Fore.RED}⚠️  WARNING: LIVE TRADING MODE ⚠️{Style.RESET_ALL}")
        print(f"{Fore.RED}You are about to trade with REAL MONEY!{Style.RESET_ALL}")
        confirm = input("Type 'CONFIRM' to continue: ")
        if confirm != 'CONFIRM':
            print("Aborted.")
            sys.exit(0)
    
    # Create and run bot
    bot = BinanceGridBot(config, testnet=testnet)
    bot.run()


if __name__ == '__main__':
    main()
