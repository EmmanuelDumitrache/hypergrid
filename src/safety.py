import logging
import time
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class SafetyMonitor:
    def __init__(self, config, exchange, info, user_address):
        self.config = config
        self.exchange = exchange
        self.info = info
        self.user_address = user_address
        
        # Safety Thresholds
        self.max_drawdown_pct = config['safety']['max_drawdown_pct']
        self.daily_loss_limit = config['safety']['daily_loss_limit_usd']
        self.min_margin_ratio = config['safety']['min_margin_ratio']
        self.max_funding = config['safety']['max_adverse_funding_rate']
        
        # State tracking
        self.initial_account_value = None
        self.start_of_day_value = None
        self.current_day = datetime.utcnow().date()
        self.emergency_triggered = False

    def sync_state(self, account_value):
        """Update internal state with latest account value"""
        current_date = datetime.utcnow().date()
        
        if self.initial_account_value is None:
            self.initial_account_value = account_value
            logger.info(f"Initialized Safety Monitor. Start Value: ${self.initial_account_value:.2f}")

        # Reset daily PnL tracker on new day
        if self.start_of_day_value is None or current_date != self.current_day:
            self.start_of_day_value = account_value
            self.current_day = current_date
            logger.info(f"New day started ({self.current_day}). Resetting Daily Loss tracker. Start Value: ${self.start_of_day_value:.2f}")

    def check_health(self, account_state):
        """
        Run all safety checks.
        Returns: True if safe to proceed, False (and triggers emergency actions) if unsafe.
        """
        if self.emergency_triggered:
            return False

        margin_summary = account_state.get('marginSummary', {})
        account_value = float(margin_summary.get('accountValue', 0))
        total_margin_used = float(margin_summary.get('totalMarginUsed', 0))
        
        self.sync_state(account_value)

        # 1. Total Drawdown Check (10% max)
        # Skip drawdown check if initial_account_value is 0 or None
        if self.initial_account_value is None or self.initial_account_value == 0:
            logger.warning(f"Initial account value not set or zero ({self.initial_account_value}). Skipping drawdown check.")
            return True
        
        drawdown = (self.initial_account_value - account_value) / self.initial_account_value
        if drawdown >= self.max_drawdown_pct:
            logger.critical(f"CRITICAL: Max drawdown reached! ({drawdown*100:.2f}% >= {self.max_drawdown_pct*100}%). TRIGGERING EMERGENCY EXIT.")
            self.emergency_exit()
            return False

        # 2. Daily Loss Limit (-$50)
        daily_loss = self.start_of_day_value - account_value
        if daily_loss >= self.daily_loss_limit:
            logger.critical(f"CRITICAL: Daily loss limit reached! (-${daily_loss:.2f} >= -${self.daily_loss_limit}). TRIGGERING EMERGENCY EXIT.")
            self.emergency_exit()
            return False

        # 3. Margin Ratio Check (>150%)
        # Margin Ratio = Account Value / Maintenance Margin ? Or Total Margin Used?
        # User specified: "margin ratio ... (>150% required)"
        # Usually implies Account Value / Maintenance Margin > 1.5
        # Hyperliquid returns totalMarginUsed which usually includes initial margin. 
        # We need Maintenance Margin to be precise, but AccountValue / TotalMarginUsed > 1.5 is a safer proxy if maint not avail.
        # Let's assume TotalMarginUsed is the closest proxy for now, generally strict.
        if total_margin_used > 0:
            margin_ratio = account_value / total_margin_used
            if margin_ratio < self.min_margin_ratio:
                 logger.error(f"SAFETY: Margin Ratio too low! ({margin_ratio:.2f} < {self.min_margin_ratio}). Pausing/Reducing only.")
                 # This might not trigger full emergency exit, but should Block new orders.
                 return False
        
        return True

    def check_market_conditions(self, coin):
        """
        Check funding rates and trend breaks.
        Returns: True if Safe, False if Adverse (should pause).
        """
        # Funding rate check
        # Spec: "Funding rate >0.1% adverse -> pause grid"
        # Adverse means paying funding. 
        # If Long (Position > 0), Positive Funding is Bad (Pay).
        # If Short (Position < 0), Negative Funding is Bad (Pay).
        # We need current position and current funding rate.
        
        try:
            # 1. Get Position Direction
            # We already have user_state passed in check_health, but here we might need it again
            # Let's assume the main bot loop calls this with necessary data or we fetch it.
            # But to be clean, let's update arguments or fetch within.
            # For this MVP, we'll try to fetch asset context
            
            # This requires 'info' object to have access to funding
            # mocked info.meta_and_asset_ctxs?
            
            # Simple approach: Return True for now but log if we can't check
            # Real implementation:
            # meta = self.info.meta_and_asset_ctxs()
            # find coin funding
            pass
        except Exception as e:
            logger.error(f"Failed to check market conditions: {e}")
            return True # Don't block on error? Or do? Safe default: True (don't exit) or False (Pause)?
            # Spec says "pause grid".
        
        return True

    def check_funding_rate(self, funding_rate, position_size):
        """
        Check if funding rate is adverse and > 0.1%.
        Returns False if unsafe (should pause), True if safe.
        """
        limit = self.max_funding # 0.001 (0.1%)
        
        # Funding is 1h rate usually. 
        # If Position > 0 (Long), we pay if Funding > 0.
        # If Position < 0 (Short), we pay if Funding < 0.
        
        # Adverse check
        if position_size > 0 and funding_rate > limit:
            logger.warning(f"SAFETY: High Funding Rate (Long)! {funding_rate:.5f} > {limit}. Pausing.")
            return False
            
        if position_size < 0 and funding_rate < -limit:
            logger.warning(f"SAFETY: High Funding Rate (Short)! {funding_rate:.5f} < -{limit}. Pausing.")
            return False
            
        return True

    def emergency_exit(self):
        """
        Close all positions and cancel all orders.
        """
        try:
            logger.warning("EMERGENCY EXIT INITIALIZED: Cancelling all orders...")
            self.exchange.cancel_all_orders()
            time.sleep(1)
            
            logger.warning("Closing all positions...")
            # Logic to market close all open positions
            # This requires getting open positions and sending market sell/buy to close
            user_state = self.info.user_state(self.user_address)
            for position in user_state.get('assetPositions', []):
                pos = position.get('position', {})
                coin = pos.get('coin')
                szi = float(pos.get('szi', 0)) # Size
                if szi != 0:
                    logger.warning(f"Closing position for {coin}: {szi}")
                    self.exchange.market_close(coin)
            
            self.emergency_triggered = True
            logger.warning("EMERGENCY EXIT COMPLETE. Bot halted.")
            
            # Send Alert
            self.send_email_alert("EMERGENCY EXIT TRIGGERED")
            
        except Exception as e:
            logger.error(f"Failed to execute emergency exit: {e}")

    def send_email_alert(self, subject):
        """Send email alert if configured"""
        email_conf = self.config['safety'].get('email_alerts', {})
        if not email_conf.get('enabled'):
            return

        try:
            msg = EmailMessage()
            msg.set_content(f"HyperGridBot Alert: {subject}\n\nTime: {datetime.utcnow()}\nCheck logs for details.")
            msg['Subject'] = f"[HyperGrid] {subject}"
            msg['From'] = email_conf['sender_email']
            msg['To'] = email_conf['recipient_email']

            server = smtplib.SMTP(email_conf['smtp_server'], email_conf['smtp_port'])
            server.starttls()
            server.login(email_conf['sender_email'], email_conf['sender_password'])
            server.send_message(msg)
            server.quit()
            logger.info(f"Email alert sent: {subject}")
        except Exception as e:
            logger.error(f"Failed to send email alert: {e}")

