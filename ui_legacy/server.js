const express = require('express');
const fs = require('fs');
const path = require('path');
const app = express();
const PORT = 8080;

const LOG_FILE = path.join(__dirname, '../logs/bot.log');

app.get('/', (req, res) => {
    res.send(`
        <html>
        <head>
            <title>HyperGrid Dashboard</title>
            <meta http-equiv="refresh" content="5">
            <style>
                body { background: #1a1a1a; color: #0f0; font-family: monospace; padding: 20px; }
                .log-box { background: #000; padding: 10px; border: 1px solid #333; height: 80vh; overflow-y: scroll; white-space: pre-wrap; }
                h1 { color: #fff; }
            </style>
        </head>
        <body>
            <h1>HyperGrid Bot Status</h1>
            <div class="log-box" id="logs">Loading logs...</div>
            <script>
                fetch('/logs').then(r => r.text()).then(t => {
                    const el = document.getElementById('logs');
                    el.innerText = t;
                    el.scrollTop = el.scrollHeight;
                });
            </script>
        </body>
        </html>
    `);
});

app.get('/logs', (req, res) => {
    // Read last 2KB of logs
    if (fs.existsSync(LOG_FILE)) {
        const stats = fs.statSync(LOG_FILE);
        const size = stats.size;
        const readSize = Math.min(size, 1024 * 50); // Last 50KB
        const buffer = Buffer.alloc(readSize);
        const fd = fs.openSync(LOG_FILE, 'r');
        fs.readSync(fd, buffer, 0, readSize, size - readSize);
        fs.closeSync(fd);
        res.send(buffer.toString());
    } else {
        res.send("No logs found yet.");
    }
});

app.listen(PORT, '127.0.0.1', () => {
    console.log(`UI running on port ${PORT} (Local only, proxied by Nginx)`);
});
