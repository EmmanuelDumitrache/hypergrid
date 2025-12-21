import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import {
    Activity, Play, Square, Save, RotateCcw, Monitor,
    TrendingUp, Zap, Server, Settings, FileText, Pause, Terminal as TerminalIcon, Calendar, Clock
} from 'lucide-react';
import Editor from "@monaco-editor/react";
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';

/* --- Components --- */

const TerminalView = () => {
    const terminalRef = useRef(null);
    const wsRef = useRef(null);

    useEffect(() => {
        if (!terminalRef.current) return;

        // Init XTerm
        const term = new Terminal({
            theme: {
                background: '#0b0f19',
                foreground: '#d4d4d4',
                cursor: '#ffffff',
                selectionBackground: 'rgba(255, 255, 255, 0.3)'
            },
            fontFamily: 'Menlo, Monaco, "Courier New", monospace',
            fontSize: 12,
            cursorBlink: true,
            cols: 80,
            rows: 24,
            allowProposedApi: true
        });

        const fitAddon = new FitAddon();
        term.loadAddon(fitAddon);
        term.open(terminalRef.current);
        fitAddon.fit();

        // Connect WS
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsTarget = window.location.port === "5173"
            ? "ws://localhost:5173/ws/terminal"
            : `${protocol}//${window.location.host}/ws/terminal`;

        const ws = new WebSocket(wsTarget);
        ws.binaryType = "arraybuffer";
        wsRef.current = ws;

        ws.onopen = () => {
            const dims = { type: "resize", cols: term.cols, rows: term.rows };
            ws.send(JSON.stringify(dims));
            ws.send('\n'); // Trigger prompt
        };

        ws.onmessage = (event) => {
            if (event.data instanceof ArrayBuffer) {
                term.write(new Uint8Array(event.data));
            } else {
                term.write(event.data);
            }
        };

        term.onData(data => {
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(data);
            }
        });

        const handleResize = () => {
            fitAddon.fit();
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
            }
        };

        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            ws.close();
            term.dispose();
        };

    }, []);

    return <div ref={terminalRef} className="h-full w-full bg-[#0b0f19] p-2" />;
};

const StatCard = ({ label, value, subtext, color = "blue", icon: Icon }) => (
    <div className={`bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col justify-between relative overflow-hidden group hover:border-${color}-500/50 transition-all`}>
        <div className={`absolute top-0 right-0 p-3 opacity-10 group-hover:opacity-20 transition-opacity text-${color}-400`}>
            {Icon && <Icon size={48} />}
        </div>
        <div>
            <span className="text-slate-400 text-xs font-medium uppercase tracking-wider">{label}</span>
            <div className="text-2xl font-bold text-slate-100 mt-1">{value}</div>
        </div>
        {subtext && <div className={`text-xs mt-2 font-medium ${subtext.includes('+') ? 'text-green-400' : 'text-slate-500'}`}>{subtext}</div>}
    </div>
);

const ProgressBar = ({ label, value, max = 100, color = "blue" }) => (
    <div className="w-full">
        <div className="flex justify-between text-xs mb-1">
            <span className="text-slate-400">{label}</span>
            <span className="text-slate-300">{value}%</span>
        </div>
        <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
            <div className={`h-full bg-${color}-500 transition-all duration-500`} style={{ width: `${Math.min(value, 100)}%` }} />
        </div>
    </div>
);

const LogViewer = () => {
    const [logs, setLogs] = useState([]);
    const bottomRef = useRef(null);

    useEffect(() => {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsTarget = window.location.port === "5173"
            ? "ws://localhost:5173/ws/logs"
            : `${protocol}//${window.location.host}/ws/logs`;

        const ws = new WebSocket(wsTarget);
        ws.onmessage = (e) => setLogs(p => [...p, e.data].slice(-200));
        return () => ws.close();
    }, []);

    useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [logs]);

    return (
        <div className="bg-[#0b0f19] text-green-400/90 font-mono text-[11px] p-3 rounded-lg h-full overflow-y-auto border border-slate-800/50 shadow-inner leading-relaxed">
            {logs.length === 0 && <div className="text-slate-600 italic">Waiting for logs...</div>}
            {logs.map((line, i) => (
                <div key={i} className="border-b border-slate-900/50 py-0.5 break-words hover:bg-white/5">{line}</div>
            ))}
            <div ref={bottomRef} />
        </div>
    );
};

const ConfigEditor = () => {
    const [code, setCode] = useState("{}");
    const [loading, setLoading] = useState(false);

    useEffect(() => { axios.get("/api/config").then(res => setCode(JSON.stringify(res.data, null, 4))); }, []);

    const handleSave = async () => {
        try {
            setLoading(true);
            const json = JSON.parse(code);
            await axios.post("/api/config", { config: json });
            setTimeout(() => setLoading(false), 500);
        } catch (e) {
            alert("Invalid JSON");
            setLoading(false);
        }
    };

    return (
        <div className="h-full flex flex-col bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
            <div className="bg-slate-950/50 p-2 flex justify-between items-center border-b border-slate-800">
                <span className="text-xs font-bold text-slate-400 px-2">config.json</span>
                <button onClick={handleSave} disabled={loading} className={`px-3 py-1 rounded text-xs font-bold flex items-center gap-2 transition-all ${loading ? 'bg-green-600 text-white' : 'bg-blue-600 hover:bg-blue-500 text-white'}`}>
                    <Save size={14} /> {loading ? "SAVED" : "SAVE"}
                </button>
            </div>
            <Editor height="100%" defaultLanguage="json" value={code} onChange={setCode} theme="vs-dark" options={{ minimap: { enabled: false }, fontSize: 12 }} />
        </div>
    );
};

function App() {
    const [data, setData] = useState(null);
    const [connected, setConnected] = useState(false);
    const [showTerminal, setShowTerminal] = useState(false);

    useEffect(() => {
        let ws;
        let reconnectTimeout;
        const connect = () => {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsTarget = window.location.port === "5173"
                ? "ws://localhost:5173/ws/dashboard"
                : `${protocol}//${window.location.host}/ws/dashboard`;

            try {
                ws = new WebSocket(wsTarget);
                ws.onopen = () => {
                    setConnected(true);
                    if (reconnectTimeout) clearTimeout(reconnectTimeout);
                };
                ws.onclose = () => {
                    setConnected(false);
                    reconnectTimeout = setTimeout(connect, 3000);
                };
                ws.onerror = (error) => {
                    console.error("WebSocket error:", error);
                    setConnected(false);
                };
                ws.onmessage = (e) => {
                    try {
                        const parsed = JSON.parse(e.data);
                        setData(parsed);
                    } catch (err) {
                        console.error("Failed to parse WebSocket message:", err);
                    }
                };
            } catch (error) {
                console.error("WebSocket connection error:", error);
                setConnected(false);
                reconnectTimeout = setTimeout(connect, 3000);
            }
        };
        connect();
        return () => {
            if (reconnectTimeout) clearTimeout(reconnectTimeout);
            ws?.close();
        };
    }, []);

    const controlBot = (action) => axios.post(`/api/control/${action}`);

    // Derived State
    const bot = data?.bot || {};
    const vps = data?.vps || {};
    const isRunning = bot.status === "running";
    const pnlColor = (bot.pnl || 0) >= 0 ? "green" : "red";

    // Timestamps
    const lastUpdate = bot.updated_at ? new Date(bot.updated_at).toLocaleTimeString() : "--:--:--";

    return (
        <div className="min-h-screen bg-[#020617] text-slate-200 font-sans selection:bg-blue-500/30 overflow-hidden flex flex-col">
            {/* Header */}
            <header className="h-16 border-b border-slate-800 bg-slate-950/50 backdrop-blur shrink-0 px-6 flex items-center justify-between z-10 relative">
                <div className="flex items-center gap-3">
                    <div className="bg-blue-600/20 p-2 rounded-lg"><Activity className="text-blue-400" size={20} /></div>
                    <div>
                        <h1 className="font-bold text-lg leading-none bg-gradient-to-r from-blue-400 to-cyan-300 bg-clip-text text-transparent">HyperGrid</h1>
                        <div className="flex items-center gap-2 mt-1">
                            <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
                            <span className="text-[10px] text-slate-500 font-mono tracking-tight">{connected ? 'SYSTEM ONLINE' : 'DISCONNECTED'}</span>
                            <span className="text-[10px] text-slate-600 px-2">|</span>
                            <span className={`text-[10px] flex items-center gap-1 ${((Date.now() / 1000) - (bot.timestamp || 0)) > 20 ? 'text-red-500 font-bold' : 'text-slate-400'}`}>
                                <Clock size={10} /> {((Date.now() / 1000) - (bot.timestamp || 0)) > 20 ? 'STALE DATA' : lastUpdate}
                            </span>
                        </div>
                    </div>
                </div>

                {/* Stale Data Overlay */}
                {((Date.now() / 1000) - (bot.timestamp || 0)) > 20 && bot.status === 'running' && (
                    <div className="absolute top-20 left-1/2 -translate-x-1/2 bg-red-500/90 text-white px-4 py-1 rounded-full text-xs font-bold shadow-lg z-50 animate-pulse">
                        ⚠️ WARNING: DATA IS LAGGY (>20s)
                    </div>
                )}

                <div className="flex items-center gap-4">
                    {/* Terminal Toggle */}
                    <button
                        onClick={() => setShowTerminal(prev => !prev)}
                        className={`p-2 rounded-lg transition-all border ${showTerminal ? 'bg-blue-600/20 border-blue-500 text-blue-400' : 'bg-slate-900 border-slate-700 text-slate-400 hover:text-slate-200'}`}
                        title="Toggle Terminal"
                    >
                        <div className="flex items-center gap-2">
                            <TerminalIcon size={14} />
                            <span className="text-xs font-bold hidden md:block">TERMINAL</span>
                        </div>
                    </button>

                    <div className="h-8 w-px bg-slate-800 mx-2"></div>

                    <div className="flex items-center gap-2 bg-slate-900/50 p-1.5 rounded-xl border border-slate-800/50">
                        <div className="px-4 border-r border-slate-800/50 flex flex-col items-end">
                            <span className="text-[10px] text-slate-500 font-bold uppercase">Bot Status</span>
                            <span className={`text-xs font-bold ${isRunning ? 'text-green-400' : 'text-red-400'}`}>{isRunning ? 'ACTIVE' : 'OFFLINE'}</span>
                        </div>
                        <div className="flex gap-1">
                            {!isRunning ? (
                                <button onClick={() => controlBot('start')} className="p-2 hover:bg-green-900/30 rounded-lg group transition-all" title="Start Bot">
                                    <Play size={20} className="text-slate-400 group-hover:text-green-400 transition-colors" />
                                </button>
                            ) : (
                                <>
                                    <button onClick={() => { controlBot('stop'); setTimeout(() => controlBot('start'), 2000); }} className="p-2 hover:bg-yellow-900/30 rounded-lg group transition-all" title="Restart Bot">
                                        <RotateCcw size={20} className="text-slate-400 group-hover:text-yellow-400 transition-colors" />
                                    </button>
                                    <button onClick={() => controlBot('stop')} className="p-2 hover:bg-red-900/30 rounded-lg group transition-all" title="Stop Bot">
                                        <Square size={20} className="text-slate-400 group-hover:text-red-400 transition-colors" />
                                    </button>
                                </>
                            )}
                        </div>
                    </div>
                </div>
            </header>

            {/* Split View Content */}
            <div className="flex-1 overflow-hidden flex flex-row relative">

                {/* Dashboard (Left/Main Panel) */}
                <main className={`flex-1 overflow-y-auto pt-6 pb-8 px-6 transition-all duration-300 ${showTerminal ? 'w-[65%]' : 'w-full'}`}>
                    <div className="max-w-[1600px] mx-auto grid grid-cols-12 gap-6">

                        {/* TOP METRICS ROW */}
                        <div className="col-span-12 grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
                            <StatCard
                                label="Account Balance"
                                value={`$${(bot.balance || 0).toFixed(2)}`}
                                subtext={`Available: $${(bot.available_balance || 0).toFixed(2)}`}
                                icon={Activity} color="blue"
                            />
                            <StatCard
                                label="Total PnL"
                                value={`$${(bot.pnl || 0).toFixed(2)}`}
                                subtext={`${(bot.pnl_pct || 0).toFixed(2)}% • Daily: $${(bot.pnl_daily || 0).toFixed(2)}`}
                                icon={TrendingUp} color={pnlColor}
                            />
                            <StatCard
                                label="Total Trades"
                                value={bot.total_trades || 0}
                                subtext={`${bot.trades_24h || 0} in 24h • ${(bot.win_rate || 0).toFixed(1)}% win rate`}
                                icon={Zap} color="purple"
                            />
                            <StatCard
                                label="Active Grids"
                                value={`${bot.active_grids || 0}/${bot.total_grids || 0}`}
                                subtext={`${(bot.grid_efficiency || 0).toFixed(1)}% efficiency`}
                                icon={Server} color="cyan"
                            />
                            <StatCard
                                label="Funding Rate"
                                value={`${((bot.funding_rate || 0) * 100).toFixed(4)}%`}
                                subtext={`${bot.mode === 'live' ? 'LIVE' : 'PAPER'} • ${bot.pair || 'SOL'}`}
                                icon={TrendingUp} color="green"
                            />
                            <StatCard
                                label="Margin Health"
                                value={`${(bot.margin_ratio || 0).toFixed(2)}x`}
                                subtext={`Used: $${(bot.margin_used || 0).toFixed(2)}`}
                                icon={Activity} color={bot.margin_ratio > 1.5 ? "green" : "yellow"}
                            />
                        </div>

                        {/* MIDDLE SECTION */}
                        <div className="col-span-12 lg:col-span-8 flex flex-col gap-6">
                            {/* Performance Metrics Card */}
                            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
                                <div className="flex justify-between items-center mb-6">
                                    <h3 className="font-bold text-slate-300 flex items-center gap-2"><Activity size={16} /> Performance Metrics</h3>
                                </div>
                                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                    <div className="bg-slate-950/50 p-4 rounded-lg border border-slate-800">
                                        <div className="text-xs text-slate-500 mb-1">Largest Win</div>
                                        <div className="text-lg font-bold text-green-400">${(bot.largest_win || 0).toFixed(2)}</div>
                                    </div>
                                    <div className="bg-slate-950/50 p-4 rounded-lg border border-slate-800">
                                        <div className="text-xs text-slate-500 mb-1">Largest Loss</div>
                                        <div className="text-lg font-bold text-red-400">${(bot.largest_loss || 0).toFixed(2)}</div>
                                    </div>
                                    <div className="bg-slate-950/50 p-4 rounded-lg border border-slate-800">
                                        <div className="text-xs text-slate-500 mb-1">Profit Factor</div>
                                        <div className="text-lg font-bold text-slate-300">{(bot.profit_factor || 0).toFixed(2)}</div>
                                    </div>
                                    <div className="bg-slate-950/50 p-4 rounded-lg border border-slate-800">
                                        <div className="text-xs text-slate-500 mb-1">Avg Trade Size</div>
                                        <div className="text-lg font-bold text-slate-300">{(bot.avg_trade_size || 0).toFixed(4)}</div>
                                    </div>
                                </div>
                            </div>

                            {/* Positions Table */}
                            <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
                                <div className="p-4 border-b border-slate-800 bg-slate-950/30">
                                    <h3 className="font-bold text-slate-300 text-sm">Active Positions</h3>
                                </div>
                                <div className="overflow-x-auto">
                                    <table className="w-full text-left text-xs">
                                        <thead className="bg-slate-950/50 text-slate-500">
                                            <tr>
                                                <th className="p-3 font-medium">Side</th>
                                                <th className="p-3 font-medium">Size</th>
                                                <th className="p-3 font-medium">Entry Price</th>
                                                <th className="p-3 font-medium">Mark Price</th>
                                                <th className="p-3 font-medium">Liq. Price</th>
                                                <th className="p-3 font-medium">Margin</th>
                                                <th className="p-3 font-medium">ROI %</th>
                                                <th className="p-3 font-medium">PnL</th>
                                            </tr>
                                        </thead>
                                        <tbody className="text-slate-300">
                                            {(bot.positions || []).length === 0 ? (
                                                <tr><td colSpan="8" className="p-8 text-center text-slate-600 italic">No active positions</td></tr>
                                            ) : (
                                                bot.positions.map((pos, i) => (
                                                    <tr key={i} className="border-t border-slate-800/50 hover:bg-slate-950/50">
                                                        <td className={`p-3 font-bold ${pos.side === 'LONG' ? 'text-green-400' : 'text-red-400'}`}>{pos.side}</td>
                                                        <td className="p-3">{pos.size.toFixed(4)} {pos.symbol}</td>
                                                        <td className="p-3">${pos.entry_price.toFixed(2)}</td>
                                                        <td className="p-3">${(pos.mark_price || bot.price || 0).toFixed(2)}</td>
                                                        <td className="p-3 text-slate-500">${(pos.liquidation_price || 0).toFixed(2)}</td>
                                                        <td className="p-3 text-slate-400">${(pos.margin_used || 0).toFixed(2)}</td>
                                                        <td className={`p-3 font-bold ${(pos.roi_pct || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                                            {(pos.roi_pct || 0).toFixed(2)}%
                                                        </td>
                                                        <td className={`p-3 font-bold ${pos.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                                            ${pos.unrealized_pnl.toFixed(2)}
                                                        </td>
                                                    </tr>
                                                ))
                                            )}
                                        </tbody>
                                    </table>
                                </div>
                            </div>

                            {/* Order History Table */}
                            <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
                                <div className="p-4 border-b border-slate-800 bg-slate-950/30">
                                    <h3 className="font-bold text-slate-300 text-sm">Recent Fills (24h)</h3>
                                </div>
                                <div className="overflow-x-auto">
                                    <table className="w-full text-left text-xs">
                                        <thead className="bg-slate-950/50 text-slate-500">
                                            <tr>
                                                <th className="p-3 font-medium">Time</th>
                                                <th className="p-3 font-medium">Side</th>
                                                <th className="p-3 font-medium">Price</th>
                                                <th className="p-3 font-medium">Size</th>
                                                <th className="p-3 font-medium">PnL</th>
                                            </tr>
                                        </thead>
                                        <tbody className="text-slate-300">
                                            {(bot.recent_fills || []).length === 0 ? (
                                                <tr><td colSpan="5" className="p-8 text-center text-slate-600 italic">No recent fills</td></tr>
                                            ) : (
                                                bot.recent_fills.slice(0, 20).map((fill, i) => {
                                                    const fillTime = new Date(fill.timestamp * 1000);
                                                    return (
                                                        <tr key={i} className="border-t border-slate-800/50 hover:bg-slate-950/50">
                                                            <td className="p-3 text-slate-400">{fillTime.toLocaleTimeString()}</td>
                                                            <td className={`p-3 font-bold ${fill.side === 'B' || fill.side === 'BUY' ? 'text-green-400' : 'text-red-400'}`}>
                                                                {fill.side === 'B' || fill.side === 'BUY' ? 'BUY' : 'SELL'}
                                                            </td>
                                                            <td className="p-3">${fill.price.toFixed(2)}</td>
                                                            <td className="p-3">{fill.size.toFixed(4)}</td>
                                                            <td className={`p-3 font-bold ${(fill.pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                                                ${(fill.pnl || 0).toFixed(2)}
                                                            </td>
                                                        </tr>
                                                    );
                                                })
                                            )}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>

                        {/* Right Sidebar */}
                        <div className="col-span-12 lg:col-span-4 flex flex-col gap-6">
                            <div className="h-[400px]">
                                <ConfigEditor />
                            </div>
                            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
                                <h3 className="font-bold text-slate-300 text-sm mb-4 flex items-center gap-2"><Server size={16} /> VPS Health</h3>
                                <div className="space-y-4">
                                    <ProgressBar label="CPU Load" value={vps.cpu || 0} color="purple" />
                                    <ProgressBar label="RAM Usage" value={vps.ram || 0} color="cyan" />
                                    <ProgressBar label="Disk Usage" value={vps.disk || 0} color="blue" />
                                    <div className="grid grid-cols-2 gap-2 mt-4 pt-4 border-t border-slate-800">
                                        <div className="bg-slate-950 p-2 rounded text-center">
                                            <div className="text-[10px] text-slate-500 uppercase">Net Down</div>
                                            <div className="text-xs font-mono text-slate-300">{(vps.net_recv / 1024 / 1024).toFixed(1)} MB</div>
                                        </div>
                                        <div className="bg-slate-950 p-2 rounded text-center">
                                            <div className="text-[10px] text-slate-500 uppercase">Net Up</div>
                                            <div className="text-xs font-mono text-slate-300">{(vps.net_sent / 1024 / 1024).toFixed(1)} MB</div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* BOTTOM LOGS (Only if terminal closed or user wants both) */}
                        {!showTerminal && (
                            <div className="col-span-12 h-64">
                                <div className="h-full bg-slate-900 border border-slate-800 rounded-xl flex flex-col overflow-hidden">
                                    <div className="p-3 bg-slate-950/50 border-b border-slate-800 flex justify-between items-center">
                                        <h3 className="font-bold text-slate-300 text-sm flex items-center gap-2"><FileText size={16} /> Live Logs</h3>
                                        <span className="text-[10px] text-slate-500 font-mono">/var/log/hypergrid/bot.log</span>
                                    </div>
                                    <div className="flex-1 overflow-hidden p-2">
                                        <LogViewer />
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </main>

                {/* Terminal Pane (Sidebar) */}
                {showTerminal && (
                    <div className="w-[35%] bg-[#0b0f19] border-l border-slate-800 flex flex-col transition-all duration-300 shadow-2xl z-20">
                        <div className="h-10 bg-slate-950 border-b border-slate-800 flex justify-between items-center px-4">
                            <span className="text-xs font-bold text-slate-400 flex items-center gap-2">
                                <span className="w-2 h-2 rounded-full bg-green-500"></span> root@vps:~
                            </span>
                            <button onClick={() => setShowTerminal(false)} className="text-slate-500 hover:text-slate-200">
                                <Square size={14} className="rotate-45" /> {/* Close Icon */}
                            </button>
                        </div>
                        <div className="flex-1 overflow-hidden p-2">
                            <TerminalView />
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

export default App;
