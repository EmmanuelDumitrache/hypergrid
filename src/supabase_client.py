"""
Supabase client for HyperGridBot.
Handles user data, subscriptions, and config storage in Supabase.
"""
import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    logging.warning("Supabase not installed. Run: pip install supabase")


class SupabaseClient:
    """
    Wrapper for Supabase operations.
    Falls back to local JSON storage if Supabase is not configured.
    """
    
    def __init__(self):
        self.client: Optional[Client] = None
        self.enabled = False
        
        if not SUPABASE_AVAILABLE:
            return
        
        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_SERVICE_KEY')  # Use service key for server-side
        
        if url and key:
            try:
                self.client = create_client(url, key)
                self.enabled = True
                logging.info("Supabase client initialized")
            except Exception as e:
                logging.error(f"Failed to initialize Supabase: {e}")
    
    # ─────────────────────────────────────────────────────────────
    # USER OPERATIONS
    # ─────────────────────────────────────────────────────────────
    
    def get_user(self, telegram_id: int) -> Optional[Dict]:
        """Get user by telegram ID."""
        if not self.enabled:
            return None
        
        try:
            result = self.client.table('users').select('*').eq(
                'telegram_id', telegram_id
            ).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logging.error(f"Supabase get_user error: {e}")
            return None
    
    def create_user(self, telegram_id: int, username: str = None) -> Optional[Dict]:
        """Create a new user."""
        if not self.enabled:
            return None
        
        try:
            result = self.client.table('users').insert({
                'telegram_id': telegram_id,
                'telegram_username': username,
                'subscription_tier': 'free'
            }).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logging.error(f"Supabase create_user error: {e}")
            return None
    
    def update_user(self, telegram_id: int, **kwargs) -> bool:
        """Update user fields."""
        if not self.enabled:
            return False
        
        try:
            self.client.table('users').update(kwargs).eq(
                'telegram_id', telegram_id
            ).execute()
            return True
        except Exception as e:
            logging.error(f"Supabase update_user error: {e}")
            return False
    
    def set_api_keys(self, telegram_id: int, 
                     encrypted_key: str, encrypted_secret: str) -> bool:
        """Store encrypted API keys."""
        return self.update_user(
            telegram_id,
            binance_api_key_encrypted=encrypted_key,
            binance_api_secret_encrypted=encrypted_secret
        )
    
    # ─────────────────────────────────────────────────────────────
    # SUBSCRIPTION OPERATIONS
    # ─────────────────────────────────────────────────────────────
    
    def check_subscription(self, telegram_id: int) -> Dict:
        """Check user's subscription status."""
        user = self.get_user(telegram_id)
        if not user:
            return {'tier': 'free', 'active': False, 'expires_at': None}
        
        tier = user.get('subscription_tier', 'free')
        expires_at = user.get('subscription_expires_at')
        
        if tier == 'free' or not expires_at:
            return {'tier': 'free', 'active': False, 'expires_at': None}
        
        try:
            expires = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            active = datetime.now(expires.tzinfo) < expires
            return {'tier': tier, 'active': active, 'expires_at': expires_at}
        except:
            return {'tier': 'free', 'active': False, 'expires_at': None}
    
    def activate_subscription(self, telegram_id: int, tier: str, days: int = 30) -> bool:
        """Activate or extend subscription."""
        if tier not in ['basic', 'pro']:
            return False
        
        expires_at = (datetime.now() + timedelta(days=days)).isoformat()
        return self.update_user(
            telegram_id,
            subscription_tier=tier,
            subscription_expires_at=expires_at
        )
    
    # ─────────────────────────────────────────────────────────────
    # CONFIG OPERATIONS
    # ─────────────────────────────────────────────────────────────
    
    def get_user_config(self, telegram_id: int, pair: str = 'BNBUSDT') -> Optional[Dict]:
        """Get user's trading config for a pair."""
        if not self.enabled:
            return None
        
        user = self.get_user(telegram_id)
        if not user:
            return None
        
        try:
            result = self.client.table('user_configs').select('*').eq(
                'user_id', user['id']
            ).eq('pair', pair).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logging.error(f"Supabase get_user_config error: {e}")
            return None
    
    def update_user_config(self, telegram_id: int, pair: str, **kwargs) -> bool:
        """Update user's trading config."""
        if not self.enabled:
            return False
        
        user = self.get_user(telegram_id)
        if not user:
            return False
        
        try:
            # Upsert (insert or update)
            self.client.table('user_configs').upsert({
                'user_id': user['id'],
                'pair': pair,
                **kwargs
            }).execute()
            return True
        except Exception as e:
            logging.error(f"Supabase update_user_config error: {e}")
            return False
    
    # ─────────────────────────────────────────────────────────────
    # PAYMENT OPERATIONS
    # ─────────────────────────────────────────────────────────────
    
    def create_payment(self, telegram_id: int, amount: float, 
                       tier: str, tx_hash: str = None) -> Optional[str]:
        """Record a payment (pending confirmation)."""
        if not self.enabled:
            return None
        
        user = self.get_user(telegram_id)
        if not user:
            return None
        
        try:
            result = self.client.table('payments').insert({
                'user_id': user['id'],
                'amount_usdt': amount,
                'tier': tier,
                'tx_hash': tx_hash,
                'status': 'pending'
            }).execute()
            return result.data[0]['id'] if result.data else None
        except Exception as e:
            logging.error(f"Supabase create_payment error: {e}")
            return None
    
    def confirm_payment(self, payment_id: str) -> bool:
        """Confirm a payment and activate subscription."""
        if not self.enabled:
            return False
        
        try:
            # Get payment details
            result = self.client.table('payments').select(
                '*, users(telegram_id)'
            ).eq('id', payment_id).execute()
            
            if not result.data:
                return False
            
            payment = result.data[0]
            telegram_id = payment['users']['telegram_id']
            tier = payment['tier']
            days = payment.get('duration_days', 30)
            
            # Update payment status
            self.client.table('payments').update({
                'status': 'confirmed',
                'confirmed_at': datetime.now().isoformat()
            }).eq('id', payment_id).execute()
            
            # Activate subscription
            return self.activate_subscription(telegram_id, tier, days)
        except Exception as e:
            logging.error(f"Supabase confirm_payment error: {e}")
            return False
    
    # ─────────────────────────────────────────────────────────────
    # LOGGING
    # ─────────────────────────────────────────────────────────────
    
    def log_event(self, telegram_id: int, event_type: str, 
                  pair: str = None, details: dict = None):
        """Log a bot event for analytics."""
        if not self.enabled:
            return
        
        user = self.get_user(telegram_id)
        if not user:
            return
        
        try:
            self.client.table('bot_logs').insert({
                'user_id': user['id'],
                'event_type': event_type,
                'pair': pair,
                'details': details or {}
            }).execute()
        except Exception as e:
            logging.error(f"Supabase log_event error: {e}")


# Singleton instance
_supabase_client = None

def get_supabase() -> SupabaseClient:
    """Get the global Supabase client instance."""
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = SupabaseClient()
    return _supabase_client
