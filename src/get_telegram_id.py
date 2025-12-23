import requests
import sys

def get_chat_id(token):
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    print(f"Checking for updates via: {url}")
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if not data.get('ok'):
            print(f"❌ Error: {data.get('description')}")
            return

        results = data.get('result', [])
        if not results:
            print("⚠️ No updates found. Please send a message (e.g., 'Hello') to your bot first!")
            return

        last_msg = results[-1]['message']
        chat_id = last_msg['chat']['id']
        username = last_msg['from']['username']
        
        print(f"\n✅ SUCCESS!")
        print(f"👤 User: {username}")
        print(f"🆔 Chat ID: {chat_id}")
        print(f"\nAdd this to your .env file:")
        print(f"TELEGRAM_CHAT_ID={chat_id}")
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 src/get_telegram_id.py <YOUR_BOT_TOKEN>")
        sys.exit(1)
    
    get_chat_id(sys.argv[1])
