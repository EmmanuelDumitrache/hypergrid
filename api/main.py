import os
import sys
import time
import json
import logging
import subprocess
import signal
import psutil
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Setup Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HyperGridAPI")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../config.json"))
STATE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../state.json"))
LOG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../logs/bot.log"))

# --- Bot Manager ---
class BotManager:
    def __init__(self, bot_script_path="main.py"):
        self.process = None
        self.bot_script = bot_script_path
        self.running = False
        self.start_time = None

    def start_bot(self):
        if self.process and self.process.poll() is None:
            return {"status": "already_running", "pid": self.process.pid}

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        try:
            # Determine path to main.py
            script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", self.bot_script))
            self.process = subprocess.Popen(
                ["python3", script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, 
                env=env,
                text=True,
                cwd=os.path.dirname(script_path)
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
            self.process.terminate() # SIGTERM
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill() # SIGKILL
            
            self.process = None
            self.running = False
            self.start_time = None
            return {"status": "stopped"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_status(self):
        status = "stopped"
        pid = None
        uptime = 0
        
        if self.process:
            ret = self.process.poll()
            if ret is None:
                status = "running"
                pid = self.process.pid
                uptime = time.time() - self.start_time if self.start_time else 0
            else:
                self.running = False
        
        return {"status": status, "pid": pid, "uptime": uptime}

bot_manager = BotManager()

# --- Connection Manager for WebSockets ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

# --- Endpoints ---

@app.get("/status")
def get_status():
    proc = bot_manager.get_status()
    return proc

class ConfigUpdate(BaseModel):
    config: dict

@app.get("/config")
def get_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

@app.post("/config")
def update_config(data: ConfigUpdate):
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(data.config, f, indent=4)
        return {"status": "saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/control/{action}")
def control_bot(action: str):
    if action == "start":
        return bot_manager.start_bot()
    elif action == "stop":
        return bot_manager.stop_bot()
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

# --- WebSockets ---

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    try:
        if os.path.exists(LOG_PATH):
            with open(LOG_PATH, 'r') as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(size - 4000, 0), 0)
                await websocket.send_text(f.read())
                
                while True:
                    line = f.readline()
                    if line:
                        await websocket.send_text(line)
                    else:
                        await asyncio.sleep(0.1)
        else:
            while True: await asyncio.sleep(1)
            
    except WebSocketDisconnect:
        pass

@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # 1. VPS Stats
            vps_stats = {
                "cpu": psutil.cpu_percent(interval=None),
                "ram": psutil.virtual_memory().percent,
                "disk": psutil.disk_usage('/').percent,
                "net_sent": psutil.net_io_counters().bytes_sent,
                "net_recv": psutil.net_io_counters().bytes_recv
            }
            
            # 2. Bot Process Status
            proc_status = bot_manager.get_status()
            
            # 3. Application State (from state.json)
            app_state = {}
            if os.path.exists(STATE_PATH):
                try:
                    with open(STATE_PATH, 'r') as f:
                        app_state = json.load(f)
                except:
                    pass
            
            # Combine
            payload = {
                "vps": vps_stats,
                "bot": {**proc_status, **app_state}, 
                "timestamp": time.time()
            }
            
            await websocket.send_json(payload)
            await asyncio.sleep(1) # 1Hz update
            
    except WebSocketDisconnect:
        pass

# --- Terminal ---
import pty
import select
import struct
import fcntl
import termios

@app.websocket("/ws/terminal")
async def websocket_terminal(websocket: WebSocket):
    await websocket.accept()
    
    # Fork a child process
    # master_fd: file descriptor for the master end of the PTY
    # slave_fd: file descriptor for the slave end of the PTY
    pid, master_fd = pty.fork()

    if pid == 0:
        # Child Process (Shell)
        # Set environment
        os.environ["TERM"] = "xterm-256color"
        # os.environ["COLUMNS"] = "80"
        # os.environ["LINES"] = "24"
        
        # Change to project root if possible (optional)
        try:
            os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        except:
            pass
            
        # Exec bash
        os.execvp("/bin/bash", ["/bin/bash"])
    else:
        # Parent Process (WebSocket Handler)
        loop = asyncio.get_event_loop()

        def read_from_pty():
            try:
                data = os.read(master_fd, 1024)
                if data:
                    asyncio.ensure_future(websocket.send_bytes(data))
                else:
                    # EOF
                    pass 
            except OSError:
                pass

        # Register reader
        loop.add_reader(master_fd, read_from_pty)

        try:
            while True:
                # Receive input from WebSocket (from xterm.js)
                data = await websocket.receive_text()
                
                # Check for resize event (custom protocol: {"type": "resize", "cols": 80, "rows": 24})
                # For now assuming raw input if string, but let's parse JSON if looks like it?
                # Actually xterm.js usually sends raw strings for keys.
                # Let's wrap resize in a try/json to be safe or use a convention.
                # Convention: If starts with '{', try parse.
                
                if data.startswith("{"):
                    try:
                        cmd = json.loads(data)
                        if cmd.get("type") == "resize":
                            cols = cmd.get("cols", 80)
                            rows = cmd.get("rows", 24)
                            # Set window size
                            winsize = struct.pack("HHHH", rows, cols, 0, 0)
                            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                            continue
                    except:
                        pass
                
                # Write to PTY
                os.write(master_fd, data.encode())
                
        except WebSocketDisconnect:
            pass
        finally:
            loop.remove_reader(master_fd)
            os.close(master_fd)
            # Kill child
            try:
                os.kill(pid, signal.SIGTERM)
                os.waitpid(pid, 0)
            except:
                pass
