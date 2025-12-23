import logging
import requests
import threading
import time

class TelegramNotifier:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.running = False
        self.command_handler = None

    def send_message(self, message):
        """Send a message to the configured chat ID."""
        if not self.token or not self.chat_id:
            return

        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            logging.error(f"Failed to send Telegram message: {e}")

    def start_polling(self, command_handler_func):
        """Start a background thread to poll for commands."""
        self.command_handler = command_handler_func
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
                        message = result.get("message", {})
                        text = message.get("text", "")
                        
                        if text.startswith("/") and self.command_handler:
                            # Execute command and get response
                            response_text = self.command_handler(text)
                            if response_text:
                                self.send_message(response_text)
                
                time.sleep(1)
            except Exception as e:
                # logging.error(f"Telegram polling error: {e}") 
                time.sleep(5)
