"""
User Manager - Handles multi-user bot instances and configuration.
Each user gets an isolated bot instance running in a separate thread.
"""
import os
import json
import logging
import threading
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime

from src.crypto_utils import encrypt_api_key, decrypt_api_key


@dataclass
class UserConfig:
    """User-specific configuration."""
    telegram_id: int
    binance_api_key_encrypted: str = ""
    binance_api_secret_encrypted: str = ""
    subscription_tier: str = "free"  # free, basic, pro
    subscription_expires_at: str = ""
    pair: str = "BNBUSDT"
    preset: str = "NEUTRAL"
    custom_leverage: Optional[int] = None
    custom_grids: Optional[int] = None
    custom_spacing: Optional[float] = None
    created_at: str = ""
    
    def is_subscribed(self) -> bool:
        """Check if user has active paid subscription."""
        if self.subscription_tier == "free":
            return False
        if not self.subscription_expires_at:
            return False
        try:
            expires = datetime.fromisoformat(self.subscription_expires_at)
            return datetime.now() < expires
        except:
            return False
    
    def can_trade_live(self) -> bool:
        """Check if user can trade with real money."""
        return self.is_subscribed() and self.binance_api_key_encrypted
    
    def can_use_custom(self) -> bool:
        """Check if user can use custom parameters (Pro tier)."""
        return self.subscription_tier == "pro" and self.is_subscribed()


class UserManager:
    """
    Manages multiple user bot instances.
    Stores user configs in a JSON file (can be migrated to Supabase later).
    """
    
    ALLOWED_PAIRS = ["BNBUSDT", "SOLUSDT", "ETHUSDT"]
    
    def __init__(self, config_dir: str = "user_data"):
        self.config_dir = config_dir
        self.users_file = os.path.join(config_dir, "users.json")
        self.users: Dict[int, UserConfig] = {}
        self.bot_instances: Dict[int, Any] = {}  # telegram_id -> BinanceGridBot
        self.bot_threads: Dict[int, threading.Thread] = {}
        
        os.makedirs(config_dir, exist_ok=True)
        self._load_users()
    
    def _load_users(self):
        """Load user configs from disk."""
        if not os.path.exists(self.users_file):
            return
        try:
            with open(self.users_file, 'r') as f:
                data = json.load(f)
            for tid, udata in data.items():
                self.users[int(tid)] = UserConfig(**udata)
            logging.info(f"Loaded {len(self.users)} user configs")
        except Exception as e:
            logging.error(f"Failed to load users: {e}")
    
    def _save_users(self):
        """Save user configs to disk."""
        try:
            data = {str(tid): asdict(u) for tid, u in self.users.items()}
            with open(self.users_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logging.error(f"Failed to save users: {e}")
    
    def get_user(self, telegram_id: int) -> Optional[UserConfig]:
        """Get user config by telegram ID."""
        return self.users.get(telegram_id)
    
    def create_user(self, telegram_id: int) -> UserConfig:
        """Create a new user with default config."""
        if telegram_id in self.users:
            return self.users[telegram_id]
        
        user = UserConfig(
            telegram_id=telegram_id,
            created_at=datetime.now().isoformat()
        )
        self.users[telegram_id] = user
        self._save_users()
        logging.info(f"Created new user: {telegram_id}")
        return user
    
    def update_user(self, telegram_id: int, **kwargs) -> Optional[UserConfig]:
        """Update user config fields."""
        user = self.users.get(telegram_id)
        if not user:
            return None
        
        for key, value in kwargs.items():
            if hasattr(user, key):
                setattr(user, key, value)
        
        self._save_users()
        return user
    
    def set_api_keys(self, telegram_id: int, api_key: str, api_secret: str) -> bool:
        """Encrypt and store user's Binance API keys."""
        user = self.users.get(telegram_id)
        if not user:
            return False
        
        try:
            user.binance_api_key_encrypted = encrypt_api_key(api_key)
            user.binance_api_secret_encrypted = encrypt_api_key(api_secret)
            self._save_users()
            logging.info(f"API keys set for user {telegram_id}")
            return True
        except Exception as e:
            logging.error(f"Failed to encrypt API keys: {e}")
            return False
    
    def get_api_keys(self, telegram_id: int) -> tuple:
        """Decrypt and return user's API keys."""
        user = self.users.get(telegram_id)
        if not user or not user.binance_api_key_encrypted:
            return None, None
        
        try:
            api_key = decrypt_api_key(user.binance_api_key_encrypted)
            api_secret = decrypt_api_key(user.binance_api_secret_encrypted)
            return api_key, api_secret
        except Exception as e:
            logging.error(f"Failed to decrypt API keys: {e}")
            return None, None
    
    def set_subscription(self, telegram_id: int, tier: str, expires_at: str) -> bool:
        """Set user subscription tier and expiry."""
        if tier not in ["free", "basic", "pro"]:
            return False
        return self.update_user(
            telegram_id, 
            subscription_tier=tier,
            subscription_expires_at=expires_at
        ) is not None
    
    def start_bot(self, telegram_id: int, bot_class, base_config: dict) -> bool:
        """Start a bot instance for a user."""
        user = self.users.get(telegram_id)
        if not user:
            logging.error(f"User {telegram_id} not found")
            return False
        
        if telegram_id in self.bot_instances:
            logging.warning(f"Bot already running for user {telegram_id}")
            return False
        
        # Determine if testnet (free tier = testnet only)
        testnet = not user.can_trade_live()
        
        # Get API keys
        if user.can_trade_live():
            api_key, api_secret = self.get_api_keys(telegram_id)
            if not api_key:
                logging.error(f"No API keys for user {telegram_id}")
                return False
        else:
            # Use testnet keys from environment
            api_key = os.getenv('BINANCE_TESTNET_API_KEY', '')
            api_secret = os.getenv('BINANCE_TESTNET_API_SECRET', '')
        
        # Build user-specific config
        user_config = base_config.copy()
        user_config['binance'] = {
            'api_key': api_key,
            'api_secret': api_secret
        }
        user_config['grid']['pair'] = user.pair
        user_config['grid']['preset'] = user.preset
        
        # Apply custom params for Pro tier
        if user.can_use_custom():
            if user.custom_leverage:
                user_config['grid']['leverage'] = user.custom_leverage
            if user.custom_grids:
                user_config['grid']['grids'] = user.custom_grids
            if user.custom_spacing:
                user_config['grid']['spacing_pct'] = user.custom_spacing
        
        try:
            bot = bot_class(user_config, testnet=testnet)
            self.bot_instances[telegram_id] = bot
            
            # Start in separate thread
            thread = threading.Thread(
                target=bot.run,
                name=f"bot-{telegram_id}",
                daemon=True
            )
            thread.start()
            self.bot_threads[telegram_id] = thread
            
            logging.info(f"Started bot for user {telegram_id} (testnet={testnet})")
            return True
        except Exception as e:
            logging.error(f"Failed to start bot for {telegram_id}: {e}")
            return False
    
    def stop_bot(self, telegram_id: int) -> bool:
        """Stop a user's bot instance."""
        bot = self.bot_instances.get(telegram_id)
        if not bot:
            return False
        
        try:
            bot.shutdown()
            del self.bot_instances[telegram_id]
            if telegram_id in self.bot_threads:
                del self.bot_threads[telegram_id]
            logging.info(f"Stopped bot for user {telegram_id}")
            return True
        except Exception as e:
            logging.error(f"Failed to stop bot for {telegram_id}: {e}")
            return False
    
    def get_bot_status(self, telegram_id: int) -> Optional[dict]:
        """Get status of a user's bot."""
        bot = self.bot_instances.get(telegram_id)
        if not bot:
            return None
        
        return {
            'running': bot.running,
            'paused': bot.paused,
            'symbol': bot.symbol,
            'price': bot.current_price,
            'realized_pnl': bot.realized_pnl,
            'net_position': bot.net_position,
            'preset': bot.current_preset
        }
