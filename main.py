from src.bot import main_entry_point

# Actually, src.bot has the if __name__ == "__main__" logic.
# But deploy.sh calls main.py.
# I will make main.py import the bot class and run it, or just symlink.
# Let's make main.py the real entry.

import sys
import os
from src.bot import HyperGridBot
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.json', help='Path to config file')
    parser.add_argument('--paper', action='store_true', help='Run in paper trading mode')
    args = parser.parse_args()

    # Reuse logic from bot.py or just instantiate
    config_path = args.config
    if not os.path.exists(config_path):
        if os.path.exists('config_example.json'):
             print(f"Config {config_path} not found. Using config_example.json")
             config_path = 'config_example.json'
        # We don't fail here to allow help etc, but bot will check.

    bot = HyperGridBot(config_path, paper_mode=args.paper)
    bot.run()
