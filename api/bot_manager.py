import subprocess
import os
import signal
import psutil
import logging
import threading
import time

logger = logging.getLogger("api")

class BotManager:
    def __init__(self, bot_script_path="main.py"):
        self.process = None
        self.bot_script = bot_script_path
        self.log_file = "logs/bot.log"
        self.running = False
        self.start_time = None

    def start_bot(self):
        if self.process and self.process.poll() is None:
            return {"status": "already_running", "pid": self.process.pid}

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        # Spawn process
        try:
            # We call the main.py from the api/ folder's parent usually
            # Assuming CWD is set correctly in docker/server
            self.process = subprocess.Popen(
                ["python3", self.bot_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, 
                env=env,
                text=True
                # We do NOT pipe stdout if we want it to go to file naturally? 
                # The bot code configures logging to file AND stdout.
                # If we want to capture it here, we pipe. 
                # Better: Let the bot write to file, and we tail the file.
                # But we also want to avoid zombie processes.
            )
            self.running = True
            self.start_time = time.time()
            return {"status": "started", "pid": self.process.pid}
        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            return {"status": "error", "message": str(e)}

    def stop_bot(self):
        if not self.process:
            return {"status": "not_running"}

        try:
            # Try graceful SIGINT first
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            
            self.process = None
            self.running = False
            self.start_time = None
            return {"status": "stopped"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_status(self):
        if self.process:
            ret = self.process.poll()
            if ret is None:
                # Running
                try:
                    p = psutil.Process(self.process.pid)
                    return {
                        "status": "running",
                        "pid": self.process.pid,
                        "cpu_percent": p.cpu_percent(interval=None),
                        "memory_info": p.memory_info()._asdict(),
                        "uptime": time.time() - self.start_time
                    }
                except psutil.NoSuchProcess:
                    return {"status": "crashed"}
            else:
                self.running = False
                return {"status": "stopped", "exit_code": ret}
        return {"status": "stopped"}

bot_manager = BotManager(os.path.abspath(os.path.join(os.path.dirname(__file__), "../main.py")))
