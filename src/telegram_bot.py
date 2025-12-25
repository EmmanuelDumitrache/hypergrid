import logging
import requests
import threading
import time
import json

class TelegramNotifier:
    """Telegram bot with inline keyboard buttons for bot control."""
    
    # Conversation states for multi-step input
    STATE_NONE = 0
    STATE_AWAITING_LEVERAGE = 1
    STATE_AWAITING_GRIDS = 2
    STATE_AWAITING_SPACING = 3
    STATE_AWAITING_API_KEY = 4
    STATE_AWAITING_API_SECRET = 5
    
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.running = False
        self.command_handler = None
        self.callback_handler = None
        self.text_handler = None  # For conversation flow
        
        # Conversation state per user
        self.user_states = {}  # {chat_id: {'state': STATE_*, 'data': {}}}

    def send_message(self, message, reply_markup=None, chat_id=None):
        """Send a message with optional inline keyboard."""
        target_chat = chat_id or self.chat_id
        if not self.token or not target_chat:
            return

        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": target_chat,
                "text": message,
                "parse_mode": "Markdown"
            }
            if reply_markup:
                payload["reply_markup"] = json.dumps(reply_markup)
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            logging.error(f"Failed to send Telegram message: {e}")

    def send_main_menu(self, is_pro=False):
        """Send the main control panel with inline buttons."""
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📊 Status", "callback_data": "status"},
                    {"text": "📈 PnL", "callback_data": "pnl"}
                ],
                [
                    {"text": "⏸ Pause", "callback_data": "pause"},
                    {"text": "▶️ Resume", "callback_data": "resume"}
                ],
                [
                    {"text": "🎚 Preset", "callback_data": "preset_menu"}
                ],
                [
                    {"text": "❓ Help", "callback_data": "help"}
                ]
            ]
        }
        
        # Add Pro tier options if user is Pro
        if is_pro:
            keyboard["inline_keyboard"].insert(3, [
                {"text": "⚙️ Custom Settings", "callback_data": "custom_menu"}
            ])
        
        self.send_message("🤖 *HyperGridBot Control Panel*\n\nSelect an action:", reply_markup=keyboard)

    def send_preset_menu(self):
        """Send preset selection buttons."""
        keyboard = {
            "inline_keyboard": [
                [{"text": "⚖️ NEUTRAL", "callback_data": "preset_NEUTRAL"}],
                [{"text": "🛡️ ULTRA_SAFE", "callback_data": "preset_ULTRA_SAFE"}],
                [{"text": "🔥 AGGRESSIVE", "callback_data": "preset_AGGRESSIVE"}],
                [{"text": "◀️ Back", "callback_data": "main_menu"}]
            ]
        }
        self.send_message("🎚 *Select Trading Preset:*", reply_markup=keyboard)

    def send_custom_menu(self):
        """Send custom settings menu for Pro tier."""
        keyboard = {
            "inline_keyboard": [
                [{"text": "📊 Set Leverage", "callback_data": "custom_leverage"}],
                [{"text": "📈 Set Grid Count", "callback_data": "custom_grids"}],
                [{"text": "📏 Set Spacing", "callback_data": "custom_spacing"}],
                [{"text": "🔑 Set API Keys", "callback_data": "set_api_keys"}],
                [{"text": "◀️ Back", "callback_data": "main_menu"}]
            ]
        }
        self.send_message(
            "⚙️ *Custom Settings (Pro)*\n\n"
            "Configure your trading parameters:",
            reply_markup=keyboard
        )

    def send_pair_menu(self):
        """Send trading pair selection."""
        keyboard = {
            "inline_keyboard": [
                [{"text": "BNB/USDT", "callback_data": "pair_BNBUSDT"}],
                [{"text": "SOL/USDT", "callback_data": "pair_SOLUSDT"}],
                [{"text": "ETH/USDT", "callback_data": "pair_ETHUSDT"}],
                [{"text": "◀️ Back", "callback_data": "main_menu"}]
            ]
        }
        self.send_message("📊 *Select Trading Pair:*", reply_markup=keyboard)

    def set_user_state(self, chat_id, state, data=None):
        """Set conversation state for a user."""
        self.user_states[chat_id] = {
            'state': state,
            'data': data or {}
        }

    def get_user_state(self, chat_id):
        """Get conversation state for a user."""
        return self.user_states.get(chat_id, {'state': self.STATE_NONE, 'data': {}})

    def clear_user_state(self, chat_id):
        """Clear conversation state."""
        if chat_id in self.user_states:
            del self.user_states[chat_id]

    def answer_callback_query(self, callback_query_id, text=""):
        """Acknowledge a button press."""
        try:
            url = f"{self.base_url}/answerCallbackQuery"
            payload = {"callback_query_id": callback_query_id}
            if text:
                payload["text"] = text
            requests.post(url, json=payload, timeout=5)
        except Exception:
            pass

    def start_polling(self, command_handler_func, callback_handler_func=None, text_handler_func=None):
        """Start a background thread to poll for commands and button presses."""
        self.command_handler = command_handler_func
        self.callback_handler = callback_handler_func
        self.text_handler = text_handler_func
        self.running = True
        thread = threading.Thread(target=self._poll_updates, daemon=True)
        thread.start()
        logging.info("Telegram polling started")

    def stop(self):
        self.running = False

    def _poll_updates(self):
        offset = 0
        while self.running:
            try:
                url = f"{self.base_url}/getUpdates"
                params = {"offset": offset, "timeout": 30}
                response = requests.get(url, params=params, timeout=40)
                
                if response.status_code == 200:
                    data = response.json()
                    for result in data.get("result", []):
                        offset = result["update_id"] + 1
                        
                        # Handle text messages
                        message = result.get("message", {})
                        text = message.get("text", "")
                        chat_id = message.get("chat", {}).get("id")
                        
                        if text and chat_id:
                            # Check if in conversation state
                            user_state = self.get_user_state(chat_id)
                            
                            if user_state['state'] != self.STATE_NONE and self.text_handler:
                                # Handle conversation input
                                response_text = self.text_handler(
                                    chat_id, 
                                    text, 
                                    user_state['state'],
                                    user_state['data']
                                )
                                if response_text:
                                    self.send_message(response_text, chat_id=chat_id)
                            elif text.startswith("/") and self.command_handler:
                                # Handle slash commands
                                response_text = self.command_handler(text)
                                if response_text:
                                    self.send_message(response_text, chat_id=chat_id)
                        
                        # Handle button callbacks
                        callback_query = result.get("callback_query")
                        if callback_query and self.callback_handler:
                            callback_data = callback_query.get("data", "")
                            callback_id = callback_query.get("id")
                            cb_chat_id = callback_query.get("message", {}).get("chat", {}).get("id")
                            
                            self.answer_callback_query(callback_id)
                            
                            response_text = self.callback_handler(callback_data, cb_chat_id)
                            if response_text:
                                self.send_message(response_text, chat_id=cb_chat_id)
                
                time.sleep(1)
            except Exception as e:
                time.sleep(5)
