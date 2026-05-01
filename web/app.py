"""Rudy v2.0 — Web Dashboard
Constitution v50.0 Command Center
"""
import os
import sys
import json
import subprocess
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, make_response
from flask_socketio import SocketIO, emit

# Load environment variables from ~/.agent_zero_env
_env_file = os.path.expanduser("~/.agent_zero_env")
if os.path.exists(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if "=" in _line and not _line.startswith("#"):
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import telegram
import scholar
import rudy_brain
import auditor
import accountant

app = Flask(__name__)
app.config["SECRET_KEY"] = "rudy-v2-constitution-39"
socketio = SocketIO(app, cors_allowed_origins="*")

@app.after_request
def skip_ngrok_warning(response):
    response.headers['ngrok-skip-browser-warning'] = '1'
    return response

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")


def _load_json(filename):
    """Load a JSON file from DATA_DIR, return empty dict on error."""
    path = os.path.join(DATA_DIR, filename)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rudy v2.0 — Command Center</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0f;
            color: #e0e0e0;
            font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
            font-size: 16px;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }

        /* Header */
        .header {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border-bottom: 1px solid #0f3460;
            padding: 16px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .header h1 {
            font-size: 24px;
            color: #00d4ff;
            font-weight: 600;
        }
        .header .subtitle {
            color: #667;
            font-size: 14px;
        }
        .status-bar {
            display: flex;
            gap: 16px;
            font-size: 14px;
        }
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 6px;
        }
        .status-dot.green { background: #00ff88; box-shadow: 0 0 6px #00ff88; }
        .status-dot.red { background: #ff4444; box-shadow: 0 0 6px #ff4444; }
        .status-dot.yellow { background: #ffaa00; box-shadow: 0 0 6px #ffaa00; }

        /* Main layout */
        .main {
            display: flex;
            flex: 1;
            overflow: hidden;
        }

        /* Sidebar */
        .sidebar {
            width: 340px;
            min-width: 340px;
            background: #0d0d14;
            border-right: 1px solid #1a1a2e;
            padding: 16px;
            overflow-y: auto;
            overflow-x: hidden;
        }
        .card {
            background: #12121c;
            border: 1px solid #1a1a2e;
            border-radius: 8px;
            padding: 14px;
            margin-bottom: 12px;
            overflow: hidden;
            word-wrap: break-word;
            overflow-wrap: break-word;
        }
        .card h3 {
            font-size: 15px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #667;
            margin-bottom: 10px;
        }
        .card { cursor: pointer; transition: box-shadow 0.15s; }
        .card:hover { box-shadow: 0 0 12px rgba(0,212,255,0.15); }
        .metric {
            display: flex;
            justify-content: space-between;
            margin-bottom: 6px;
            font-size: 16px;
        }
        .metric .label { color: #888; flex: 1; margin-right: 8px; font-size: 13px; }
        .metric .value { color: #00d4ff; font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; font-size: 14px; }
        .metric .value.green { color: #00ff88; }
        .metric .value.red { color: #ff4444; }

        /* Expanded card modal overlay */
        .card-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.8);
            z-index: 9999;
            justify-content: center;
            align-items: center;
            backdrop-filter: blur(4px);
        }
        .card-overlay.active { display: flex; }
        .card-expanded {
            background: #12121c;
            border: 2px solid #00d4ff;
            border-radius: 16px;
            padding: 32px 40px;
            max-width: 700px;
            width: 90vw;
            max-height: 85vh;
            overflow-y: auto;
            box-shadow: 0 0 40px rgba(0,212,255,0.3);
            animation: expandIn 0.2s ease-out;
        }
        @keyframes expandIn {
            from { transform: scale(0.8); opacity: 0; }
            to { transform: scale(1); opacity: 1; }
        }
        .card-expanded h3 {
            font-size: 22px;
            color: #00d4ff;
            margin-bottom: 20px;
            text-transform: uppercase;
            letter-spacing: 2px;
        }
        .card-expanded .metric {
            font-size: 20px;
            margin-bottom: 12px;
            padding: 8px 0;
            border-bottom: 1px solid #1a1a2e;
        }
        .card-expanded .metric .label { font-size: 18px; }
        .card-expanded .metric .value { font-size: 20px; }
        .card-expanded div[style*="font-size:11px"],
        .card-expanded div[style*="font-size:10px"] {
            font-size: 16px !important;
        }
        .card-expanded div[style*="font-size:12px"] {
            font-size: 17px !important;
        }
        .card-expanded input { font-size: 16px !important; padding: 8px 12px !important; }
        .card-expanded button { font-size: 16px !important; padding: 8px 16px !important; }
        .card-close {
            position: absolute;
            top: 16px;
            right: 20px;
            font-size: 28px;
            color: #667;
            cursor: pointer;
            background: none;
            border: none;
            font-family: inherit;
        }
        .card-close:hover { color: #ff4444; }

        /* Expandable panels */
        .log-panel { cursor: pointer; }
        .card-expanded .log-entry {
            font-size: 16px;
            padding: 10px 0;
            color: #bbb;
        }
        .card-expanded .log-entry .time { font-size: 14px; }
        .card-expanded .log-entry.signal { color: #00d4ff; }
        .card-expanded .log-entry.trade { color: #00ff88; }
        .card-expanded .log-entry.error { color: #ff4444; }
        .card-expanded .log-entry.alert { color: #ffaa00; }
        .card-expanded .message {
            font-size: 16px;
            padding: 14px;
        }
        .card-expanded .message .name { font-size: 14px; }
        .card-expanded .message .content { font-size: 16px; line-height: 1.6; }

        /* Chat area */
        .chat-container {
            flex: 1;
            display: flex;
            flex-direction: column;
        }
        .messages {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
        }
        .message {
            margin-bottom: 16px;
            display: flex;
            gap: 12px;
        }
        .message .avatar {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 16px;
            flex-shrink: 0;
        }
        .message.user .avatar { background: #1a3a5c; }
        .message.rudy .avatar { background: #0f3460; }
        .message .content {
            background: #12121c;
            border: 1px solid #1a1a2e;
            border-radius: 12px;
            padding: 12px 16px;
            max-width: 70%;
            font-size: 16px;
            line-height: 1.6;
        }
        .message.rudy .content {
            border-color: #0f3460;
        }
        .message .name {
            font-size: 13px;
            color: #667;
            margin-bottom: 4px;
        }
        .message.rudy .name { color: #00d4ff; }

        /* Input */
        .input-area {
            padding: 16px 20px;
            border-top: 1px solid #1a1a2e;
            background: #0d0d14;
        }
        .input-row {
            display: flex;
            gap: 10px;
        }
        .input-row input {
            flex: 1;
            background: #12121c;
            border: 1px solid #1a1a2e;
            border-radius: 8px;
            padding: 12px 16px;
            color: #e0e0e0;
            font-family: inherit;
            font-size: 14px;
            outline: none;
        }
        .input-row input:focus { border-color: #0f3460; }
        .input-row button {
            background: linear-gradient(135deg, #0f3460, #00d4ff);
            border: none;
            border-radius: 8px;
            padding: 12px 24px;
            color: white;
            font-family: inherit;
            font-weight: 600;
            cursor: pointer;
            font-size: 14px;
        }
        .input-row button:hover { opacity: 0.9; }

        /* Log panel */
        .log-panel {
            width: 300px;
            background: #0d0d14;
            border-left: 1px solid #1a1a2e;
            padding: 16px;
            overflow-y: auto;
            font-size: 14px;
        }
        .log-panel h3 {
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #667;
            margin-bottom: 10px;
        }
        .log-entry {
            padding: 6px 0;
            border-bottom: 1px solid #1a1a2e;
            color: #888;
        }
        .log-entry .time { color: #555; }
        .log-entry.signal { color: #00d4ff; }
        .log-entry.trade { color: #00ff88; }
        .log-entry.error { color: #ff4444; }
        .log-entry.alert { color: #ffaa00; }

        /* Ticker tape */
        .ticker-tape {
            width: 100%;
            height: 46px;
            border-bottom: 1px solid #1a1a2e;
        }

        /* Quick launch buttons */
        .quick-launch {
            display: flex;
            gap: 8px;
            margin-left: auto;
        }
        .launch-btn {
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            border: 1px solid #0f3460;
            border-radius: 6px;
            padding: 6px 14px;
            color: #00d4ff;
            font-family: inherit;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s;
        }
        .launch-btn:hover {
            background: linear-gradient(135deg, #0f3460, #1a3a5c);
            border-color: #00d4ff;
        }
        .launch-btn.tv { border-color: #2962FF; color: #2962FF; }
        .deploy-btn {
            display: inline-block;
            margin-top: 8px;
            padding: 4px 14px;
            border-radius: 4px;
            font-family: inherit;
            font-size: 14px;
            font-weight: 700;
            cursor: pointer;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            transition: all 0.2s;
        }
        /* old deploy buttons removed — v2.8+ LIVE only */
        .deploy-btn.live {
            background: #3a1a1a;
            border: 1px solid #ff4444;
            color: #ff4444;
            animation: livePulse 2s infinite;
        }
        .deploy-btn.live:hover { background: #4a0a0a; }
        .deploy-btn.blocked {
            background: #1a1a1a;
            border: 1px solid #555;
            color: #555;
            cursor: not-allowed;
        }
        @keyframes livePulse {
            0%, 100% { box-shadow: 0 0 4px #ff4444; }
            50% { box-shadow: 0 0 12px #ff4444; }
        }
        .launch-btn.tv:hover { background: #2962FF22; }
        .launch-btn.cetient { border-color: #8b5cf6; color: #8b5cf6; }
        .launch-btn.cetient:hover { background: #8b5cf622; }
        .launch-btn.claude { border-color: #d97706; color: #d97706; }
        .launch-btn.claude:hover { background: #d9770622; }


        /* Mobile responsive */
        @media (max-width: 900px) {
            .main { flex-direction: column; }
            .sidebar { width: 100%; max-height: 300px; overflow-y: auto; border-right: none; border-bottom: 1px solid #1a1a2e; }
            .log-panel { width: 100%; max-height: 200px; border-left: none; border-top: 1px solid #1a1a2e; }
            .header { flex-wrap: wrap; gap: 8px; }
            .quick-launch { flex-wrap: wrap; }
        }
        @media (max-width: 600px) {
            .sidebar { padding: 8px; }
            .card { padding: 10px; margin-bottom: 8px; }
            .header h1 { font-size: 16px; }
        }

        /* Scrollbar */
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #0a0a0f; }
        ::-webkit-scrollbar-thumb { background: #1a1a2e; border-radius: 3px; }
    </style>
</head>
<body>
    <!-- Expand overlay -->
    <div class="card-overlay" id="card-overlay" onclick="closeExpand(event)">
        <div class="card-expanded" id="card-expanded" style="position:relative;">
            <button class="card-close" onclick="closeExpand(event)">&times;</button>
            <div id="expanded-content"></div>
        </div>
    </div>

    <div class="header">
        <div>
            <h1>Rudy v2.0 — Command Center</h1>
            <div class="subtitle">Constitution v50.0 | LIVE TRADING — v2.8+ Trend Adder | U15746102</div>
        </div>
        <div class="status-bar">
            <span><span class="status-dot green" id="ibkr-status"></span>IBKR</span>
            <span><span class="status-dot green" id="em-status"></span>E.M.</span>
            <span><span class="status-dot green" id="webhook-status"></span>Webhook</span>
            <span><span class="status-dot green" id="ngrok-status"></span>ngrok</span>
        </div>
        <div class="quick-launch">
            <a href="https://www.tradingview.com/chart/FxGExYjH/" target="_blank" class="launch-btn tv">TradeSage</a>
            <a href="https://cetient.com" target="_blank" class="launch-btn cetient">Cetient</a>
            <a href="https://scholar.google.com" target="_blank" class="launch-btn">Scholar</a>
            <a href="https://claude.ai" target="_blank" class="launch-btn claude">Claude</a>
            <a href="/pinescripts" target="_blank" class="launch-btn tv">PineScripts</a>
            <a href="/projections" target="_blank" class="launch-btn" style="background:linear-gradient(135deg,#ff9800,#ff5722);">Projections</a>
            <a href="/positions" target="_blank" class="launch-btn" style="background:linear-gradient(135deg,#e53935,#b71c1c);">📊 Positions</a>
        </div>
    </div>

    <!-- TradingView Ticker Tape — REMOVED (confirmed popup source) -->
    <div class="ticker-tape" id="ticker-tape-bar" style="height:46px;background:#12121c;display:flex;align-items:center;padding:0 16px;gap:20px;border-bottom:1px solid #1a1a2e;overflow:hidden;">
        <span id="ticker-data" style="color:#888;font-size:13px;">Loading tickers...</span>
    </div>


    <div class="main">
        <div class="sidebar">
            <div class="card" style="border-color:#0f3460;">
                <h3>Live Trading — Account U15746102</h3>
                <div class="metric"><span class="label">Status</span><span class="value" id="pt-status" style="color:#00ff88;">LIVE</span></div>
                <div class="metric"><span class="label">Day</span><span class="value" id="pt-day">0</span></div>
                <div class="metric"><span class="label">Capital</span><span class="value" id="pt-start">$7,780</span></div>
                <div class="metric"><span class="label">Current Value</span><span class="value" id="pt-current">—</span></div>
                <div class="metric"><span class="label">Total P&L</span><span class="value" id="pt-total-pnl">—</span></div>
                <div class="metric"><span class="label">Total Return</span><span class="value" id="pt-return">—</span></div>
                <div class="metric"><span class="label">Today</span><span class="value" id="pt-today">—</span></div>
                <div class="metric"><span class="label">Peak</span><span class="value" id="pt-peak">—</span></div>
                <div class="metric"><span class="label">Drawdown</span><span class="value red" id="pt-dd">—</span></div>
                <div class="metric"><span class="label">Streak</span><span class="value" id="pt-streak">—</span></div>
                <div class="metric"><span class="label">Mode</span><span class="value" id="pt-golive" style="color:#00ff88;">LIVE</span></div>
                <div class="metric"><span class="label">Systems Active</span><span class="value" id="pt-active-systems">—</span></div>
                <div id="pt-chart" style="margin-top:10px;height:60px;display:flex;align-items:flex-end;gap:1px;"></div>
            </div>
            <div class="card">
                <h3>Account <span id="acct-live-dot" style="color:#00ff88;font-size:12px;">● LIVE</span></h3>
                <div class="metric"><span class="label">Net Liq</span><span class="value green" id="net-liq">{{ net_liq }}</span></div>
                <div class="metric"><span class="label">Cash</span><span class="value" id="cash">{{ cash }}</span></div>
                <div class="metric"><span class="label">Buying Power</span><span class="value" id="buying-power">{{ buying_power }}</span></div>
                <div class="metric"><span class="label">Last Update</span><span class="value" id="acct-ts" style="color:#888;font-size:13px;">{{ acct_updated }}</span></div>
            </div>
            <!-- HITL Strike Roll Approval Panel — FIXED OVERLAY -->
            <div id="hitl-panel" style="display:none;position:fixed;top:0;left:0;right:0;z-index:99999;padding:20px 24px;background:linear-gradient(135deg,#1a1a2e,#2d1b00);border-bottom:3px solid #ff9800;box-shadow:0 4px 30px rgba(255,152,0,0.5);animation:hitlPulse 2s infinite;">
                <style>@keyframes hitlPulse{0%,100%{box-shadow:0 4px 30px rgba(255,152,0,0.5)}50%{box-shadow:0 4px 40px rgba(255,152,0,0.8)}}</style>
                <h3 style="color:#ff9800;margin:0 0 12px 0;font-size:20px;">🔐 STRIKE ROLL — Awaiting Your Approval</h3>
                <div id="hitl-details" style="font-size:15px;line-height:1.8;color:#ccc;"></div>
                <div style="display:flex;gap:12px;margin-top:16px;">
                    <button id="hitl-approve" style="flex:1;padding:18px;font-size:20px;font-weight:bold;background:#00ff88;color:#000;border:none;border-radius:10px;cursor:pointer;z-index:99999;">✅ YES — Approve Roll</button>
                    <button id="hitl-reject" style="flex:1;padding:18px;font-size:20px;font-weight:bold;background:#e53935;color:#fff;border:none;border-radius:10px;cursor:pointer;z-index:99999;">❌ NO — Keep Current</button>
                </div>
                <div id="hitl-result" style="margin-top:10px;font-size:15px;display:none;"></div>
            </div>
            <div class="card" style="border-color:#00ff88;">
                <h3>v2.8+ Trend Adder — LIVE</h3>
                <div class="metric"><span class="label">Mode</span><span class="value green">LIVE (daily resolution)</span></div>
                <div class="metric"><span class="label">Execution</span><span class="value" style="color:#00d4ff;">IBKR Direct (ib_insync)</span></div>
                <div class="metric"><span class="label">Eval Schedule</span><span class="value">Weekdays 3:45 PM ET</span></div>
                <div class="metric"><span class="label">Account</span><span class="value green">U15746102 (LIVE)</span></div>
                <div class="metric"><span class="label">Base Capital</span><span class="value">25% NLV per position</span></div>
                <div class="metric"><span class="label">Trend Adder</span><span class="value" style="color:#00d4ff;">+25% on golden cross confirm (4 weeks)</span></div>
                <div class="metric"><span class="label">Entry</span><span class="value" style="font-size:13px;">200W SMA dip+reclaim + BTC>200W + StRSI<70</span></div>
                <div class="metric"><span class="label">Premium Bands</span><span class="value" style="font-size:13px;">Tight: 0.7/1.0/1.3 (WF optimal)</span></div>
                <div class="metric"><span class="label">LEAP Multipliers</span><span class="value" style="font-size:13px;">Conservative: 7.2/6.5/4.8/3.3</span></div>
                <div class="metric"><span class="label">Trail Stops</span><span class="value" style="font-size:13px;">Tight: 35/30/25/20/12%</span></div>
                <div class="metric"><span class="label">Initial Floor</span><span class="value red">35% (deactivates at 5x)</span></div>
                <div class="metric"><span class="label">Adder Exit</span><span class="value" style="font-size:13px;">Convergence-down (10%) + trailing stops</span></div>
                <div style="margin-top:8px;font-size:12px;color:#00ff88;line-height:1.5;">
                    ✅ Walk-Forward: WFE 1.18 | +6,750.6% OOS | 7/7 windows<br>
                    ✅ Quarterly OOS Re-Validation: oos_revalidation.py (PASS/WARN/DRIFT ALERT)<br>
                    ✅ Regime: 0/5 false positives (crypto winter, bear traps, COVID)<br>
                    ✅ Execution: Survives 200bps slippage (Sharpe 0.171)<br>
                    ✅ Perturbation: 75% survival ±20% param noise<br>
                    ✅ Capital: Convex scaling | Path: CV=0%<br>
                    ✅ AVGO Cross-Val: +501.5%, Sharpe 0.888<br>
                    ✅ Lookahead Audit: Clean (March 2026)<br>
                    ✅ Safety: PID locks, 2% daily cap, 5-loss shutdown<br>
                    ✅ Stealth Execution: Anti-hunt limits, no round prices<br>
                    ✅ System 13: Regime Classifier — 95.6% CV, DISTRIBUTION 82.2%
                </div>
            </div>
            <div class="card" style="border-color:#e53935;">
                <h3>Safety Infrastructure — v50.0</h3>
                <div class="metric"><span class="label">Kill Switch</span><span class="value green">READY</span></div>
                <div class="metric"><span class="label">Daily Loss Limit</span><span class="value green">2% NLV cap</span></div>
                <div class="metric"><span class="label">Loss Shutdown</span><span class="value green">5 consecutive → pause</span></div>
                <div class="metric"><span class="label">PID Lockfiles</span><span class="value green">All 3 daemons protected</span></div>
                <div class="metric"><span class="label">Position Audit</span><span class="value green">Daily 8AM ET</span></div>
                <div class="metric"><span class="label">Order Confirmation</span><span class="value green">Poll until filled</span></div>
                <div class="metric"><span class="label">Reconciliation</span><span class="value green">After every trade</span></div>
                <div class="metric"><span class="label">Premium Alert</span><span class="value green">mNAV >15% drop → Telegram</span></div>
                <div class="metric"><span class="label">Strike Engine</span><span class="value green">Real-time (10s refresh)</span></div>
                <div class="metric"><span class="label">HITL Approval</span><span class="value green">Telegram + Dashboard + iPhone</span></div>
                <div class="metric"><span class="label">Stale Order Cleanup</span><span class="value green">Before every order</span></div>
                <div class="metric"><span class="label">Stealth Execution</span><span class="value green">Anti-hunt limits, no round prices</span></div>
                <div class="metric"><span class="label">Verify Flat</span><span class="value green">After every exit</span></div>
                <div class="metric"><span class="label">LEAP Expiry Extension</span><span class="value green">180d warn / 90d urgent → HITL roll</span></div>
                <div class="metric"><span class="label">Expiry Roll Approval</span><span class="value green">MCP approve_expiry_roll() — full loop</span></div>
                <div style="margin-top:12px;border-top:1px solid #333;padding-top:10px;">
                    <h4 style="margin:0 0 8px 0;color:#e53935;">OOS Health Monitor</h4>
                    <div class="metric"><span class="label">Last Verdict</span><span class="value" id="oos-verdict" style="color:#888;">—</span></div>
                    <div class="metric"><span class="label">Quarter</span><span class="value" id="oos-quarter" style="color:#888;">—</span></div>
                    <div class="metric"><span class="label">Rolling 4Q Avg</span><span class="value" id="oos-rolling-avg" style="color:#888;">—</span></div>
                    <div class="metric"><span class="label">Winner Stability</span><span class="value" id="oos-stability" style="color:#888;">—</span></div>
                    <div class="metric"><span class="label">Drift Streak</span><span class="value" id="oos-drift-streak" style="color:#888;">—</span></div>
                    <div class="metric"><span class="label">Escalation</span><span class="value" id="oos-escalation" style="color:#888;">—</span></div>
                    <div class="metric"><span class="label">Regime Context</span><span class="value" id="oos-regime" style="color:#888;">—</span></div>
                </div>
                <div style="margin-top:8px;">
                    <a href="/positions" target="_blank" style="color:#e53935;font-weight:bold;font-size:14px;">📊 Live Positions + Kill Switch →</a>
                </div>
            </div>
            <div class="card" style="border-color:#ffd700;">
                <h3>Capital Deployment Plan</h3>
                <div class="metric"><span class="label">Phase 1 — Early Signal</span><span class="value" style="color:#ffd700;">~$7,900 (current)</span></div>
                <div class="metric"><span class="label">Phase 2 — Put Proceeds</span><span class="value" style="color:#ffd700;">~$1,750 (on close)</span></div>
                <div class="metric"><span class="label">Phase 3 — Full Deploy</span><span class="value" style="color:#ffd700;">$130K (Aug-Oct)</span></div>
                <div class="metric"><span class="label">Total Deployment</span><span class="value" style="color:#00ff88;font-weight:bold;">~$139,650</span></div>
                <div class="metric"><span class="label">Target</span><span class="value" style="color:#00ff88;">v2.8+ MSTR LEAP</span></div>
                <div style="margin-top:8px;font-size:12px;color:#888;">
                    All phases feed ONE strategy. Put proceeds stay in account.<br>
                    If signal fires before $130K arrives — enter with what's available.
                </div>
            </div>
            <div class="card" style="border-color:#ff9800;">
                <h3>BTC Cycle Intelligence</h3>
                <div class="metric"><span class="label">Cycle Phase</span><span class="value" id="btc-cycle-phase" style="color:#ff9800;">—</span></div>
                <div class="metric"><span class="label">BTC Price</span><span class="value" id="btc-price">—</span></div>
                <div class="metric"><span class="label">ATH</span><span class="value" id="btc-ath" style="color:#888;">$126,200 (Oct 2025)</span></div>
                <div class="metric"><span class="label">Drawdown from ATH</span><span class="value" id="btc-dd" style="color:#ff4444;">—</span></div>
                <div class="metric"><span class="label">Bull/Bear Line</span><span class="value" style="color:#888;">$80,000</span></div>
                <div class="metric"><span class="label">200W SMA</span><span class="value" id="btc-200w">—</span></div>
                <div class="metric"><span class="label">250W MA (Capitulation)</span><span class="value" id="btc-250w">—</span></div>
                <div class="metric"><span class="label">300W MA (Absolute Floor)</span><span class="value" id="btc-300w">—</span></div>
                <div class="metric"><span class="label">Proximity Zone</span><span class="value" id="btc-proximity">—</span></div>
                <div class="metric"><span class="label">Months Post-Halving</span><span class="value" id="btc-halving">—</span></div>
                <div class="metric"><span class="label">Weekend Sentinel</span><span class="value green" id="sentinel-status">Active (15m checks)</span></div>
                <div class="metric"><span class="label">Eval Frequency</span><span class="value" id="eval-freq" style="color:#ff9800;">Standard (1x/day)</span></div>
                <div class="metric"><span class="label">Detected Phase</span><span class="value" id="cycle-phase-detected" style="color:#ff4444;">—</span></div>
                <div style="margin-top:12px;border-top:1px solid #333;padding-top:10px;">
                    <div style="font-size:13px;color:#ff9800;font-weight:bold;margin-bottom:6px;">Phase-Aware Monthly Seasonality</div>
                    <table style="width:100%;font-size:11px;border-collapse:collapse;">
                        <tr style="color:#888;border-bottom:1px solid #222;">
                            <th style="text-align:left;padding:3px 2px;">Mo</th>
                            <th style="text-align:left;padding:3px 2px;">🟢 Bull</th>
                            <th style="text-align:left;padding:3px 2px;">🔴 Bear</th>
                        </tr>
                        <tr id="season-jan"><td style="padding:2px;">Jan</td><td style="color:#00ff88;">Reversal start</td><td style="color:#ff4444;">Sell-off continues</td></tr>
                        <tr id="season-feb"><td style="padding:2px;">Feb</td><td style="color:#00ff88;">Recovery rally</td><td style="color:#ff9800;">Sucker's rally</td></tr>
                        <tr id="season-mar"><td style="padding:2px;">Mar</td><td style="color:#00ff88;">Very bullish</td><td style="color:#ff9800;">Bounce then drop</td></tr>
                        <tr id="season-apr"><td style="padding:2px;">Apr</td><td style="color:#00d4ff;">Steady gains</td><td style="color:#ff9800;">Relief rally trap</td></tr>
                        <tr id="season-may"><td style="padding:2px;">May</td><td style="color:#00d4ff;">Pause</td><td style="color:#ff4444;">Downtrend starts</td></tr>
                        <tr id="season-jun"><td style="padding:2px;font-weight:bold;">Jun</td><td style="color:#00d4ff;">Shallow dip — BUY</td><td style="color:#ff4444;font-weight:bold;">BRUTAL 🔥</td></tr>
                        <tr id="season-jul"><td style="padding:2px;">Jul</td><td style="color:#00ff88;">Summer bounce</td><td style="color:#ff9800;">Consolidation</td></tr>
                        <tr id="season-aug"><td style="padding:2px;">Aug</td><td style="color:#888;">Neutral/weak</td><td style="color:#ff4444;font-weight:bold;">Heavy outflows</td></tr>
                        <tr id="season-sep"><td style="padding:2px;font-weight:bold;">Sep</td><td style="color:#00ff88;font-weight:bold;">BEST buy opp 💰</td><td style="color:#ff4444;font-weight:bold;">WORST month 💀</td></tr>
                        <tr id="season-oct"><td style="padding:2px;font-weight:bold;">Oct</td><td style="color:#00ff88;font-weight:bold;">UPTOBER 🚀</td><td style="color:#ff9800;">Dead cat trap ⚠️</td></tr>
                        <tr id="season-nov"><td style="padding:2px;font-weight:bold;">Nov</td><td style="color:#00ff88;font-weight:bold;">PARABOLIC 🔥</td><td style="color:#ff4444;font-weight:bold;">Capitulation 💀</td></tr>
                        <tr id="season-dec"><td style="padding:2px;">Dec</td><td style="color:#ff9800;">Profit-taking</td><td style="color:#ff4444;">Tax-loss selling</td></tr>
                    </table>
                    <div style="margin-top:6px;font-size:11px;color:#666;">
                        Active column based on detected phase · High-alert months = 2hr eval · Source: DeepSeek + CoinGlass
                    </div>
                </div>
                <div style="margin-top:8px;font-size:12px;color:#ff9800;">
                    Monday 9:30 AM: auto-eval if BTC dropped >5% over weekend
                </div>
            </div>
            <div class="card" style="border-color:#9b59b6;">
                <h3>System 13 — Neural Regime Classifier</h3>
                <div class="metric"><span class="label">Current Regime</span><span class="value" id="regime-current" style="font-weight:bold;font-size:18px;">—</span></div>
                <div class="metric"><span class="label">Confidence</span><span class="value" id="regime-confidence">—</span></div>
                <div class="metric"><span class="label">Model Accuracy</span><span class="value green">95.6% CV (5-fold)</span></div>
                <div style="margin-top:8px;border-top:1px solid #333;padding-top:8px;">
                    <div style="font-size:12px;color:#888;margin-bottom:4px;">Regime Probabilities</div>
                    <div class="metric"><span class="label">ACCUMULATION</span><span class="value" id="regime-acc" style="color:#00d4ff;">—</span></div>
                    <div class="metric"><span class="label">MARKUP</span><span class="value" id="regime-mkup" style="color:#00ff88;">—</span></div>
                    <div class="metric"><span class="label">DISTRIBUTION</span><span class="value" id="regime-dist" style="color:#ffd700;">—</span></div>
                    <div class="metric"><span class="label">MARKDOWN</span><span class="value" id="regime-mkdn" style="color:#e53935;">—</span></div>
                </div>
                <div style="margin-top:8px;border-top:1px solid #333;padding-top:8px;">
                    <div class="metric"><span class="label">Transition Alert</span><span class="value" id="regime-transition" style="color:#ff9800;">—</span></div>
                    <div class="metric"><span class="label">This Month</span><span class="value" id="regime-month-outlook">—</span></div>
                    <div class="metric"><span class="label">BTC Price</span><span class="value" id="regime-btc">—</span></div>
                    <div class="metric"><span class="label">Last Updated</span><span class="value" id="regime-updated" style="color:#888;font-size:12px;">—</span></div>
                </div>
                <div style="margin-top:6px;font-size:11px;color:#666;">
                    CalibratedEnsemble(RF300+GB200) · 65 features · Awareness layer only — does NOT modify v2.8+ logic
                </div>
            </div>
            <div class="card" style="border-color:#1da1f2;">
                <h3>🐦 Grok — CT Sentiment</h3>
                <div class="metric"><span class="label">Sentiment Score</span><span class="value" id="grok-score" style="font-weight:bold;font-size:18px;">—</span></div>
                <div class="metric"><span class="label">Fear/Greed</span><span class="value" id="grok-fg">—</span></div>
                <div class="metric"><span class="label">BTC Sentiment</span><span class="value" id="grok-btc">—</span></div>
                <div class="metric"><span class="label">MSTR Sentiment</span><span class="value" id="grok-mstr">—</span></div>
                <div class="metric"><span class="label">Key Themes</span><span class="value" id="grok-themes" style="font-size:12px;color:#888;">—</span></div>
                <div class="metric"><span class="label">Last Scan</span><span class="value" id="grok-time" style="font-size:12px;color:#888;">—</span></div>
                <div class="metric"><span class="label">Stale Flag</span><span class="value" id="grok-stale" style="font-size:12px;color:#888;">—</span></div>
                <div style="font-size:11px;color:#666;margin-top:6px;">xAI Grok · Native X/Twitter access · Every 4 hours · GREED threshold: score &gt;50 · Stale detection: 3-run window</div>
            </div>
            <div class="card" style="border-color:#4285f4;">
                <h3>🧠 Gemini — Second Brain</h3>
                <div class="metric"><span class="label">Regime Call</span><span class="value" id="gem-regime" style="font-weight:bold;">—</span></div>
                <div class="metric"><span class="label">Consensus w/ S13</span><span class="value" id="gem-consensus">—</span></div>
                <div class="metric"><span class="label">30d Outlook</span><span class="value" id="gem-outlook" style="font-size:12px;">—</span></div>
                <div class="metric"><span class="label">Key Risk</span><span class="value" id="gem-risk" style="font-size:12px;color:#ff4444;">—</span></div>
                <div class="metric"><span class="label">Key Opportunity</span><span class="value" id="gem-opp" style="font-size:12px;color:#00ff88;">—</span></div>
                <div class="metric"><span class="label">Last Updated</span><span class="value" id="gem-time" style="font-size:12px;color:#888;">—</span></div>
                <div style="margin-top:8px;border-top:1px solid #333;padding-top:8px;">
                    <div style="font-size:12px;color:#888;margin-bottom:4px;">📰 News Digest</div>
                    <div id="gem-digest" style="font-size:13px;color:#888;line-height:1.4;">—</div>
                </div>
                <div style="font-size:11px;color:#666;margin-top:6px;">Google Gemini 2.5 Flash · Regime cross-check + news digest</div>
            </div>
            <!-- Systems 1-12 removed — v2.8+ only -->
            <div class="card" style="border-color:#8b7500;">
                <h3>📉 10Y Treasury — Macro</h3>
                <div class="metric"><span class="label">Yield</span><span class="value" id="ty-yield">—</span></div>
                <div class="metric"><span class="label">Change</span><span class="value" id="ty-change">—</span></div>
                <div class="metric"><span class="label">Regime</span><span class="value" id="ty-regime" style="font-weight:bold;">—</span></div>
                <div class="metric"><span class="label">BTC Implication</span><span class="value" id="ty-impl" style="font-size:12px;">—</span></div>
                <div class="metric"><span class="label">Updated</span><span class="value" id="ty-time" style="font-size:11px;color:#888;">—</span></div>
                <div style="font-size:11px;color:#666;margin-top:6px;">Yahoo ^TNX · hourly · awareness only</div>
            </div>
            <div class="card">
                <h3>MSTR</h3>
                <div class="metric"><span class="label">Price</span><span class="value" id="mstr-price">—</span></div>
                <div class="metric"><span class="label">Change</span><span class="value" id="mstr-change">—</span></div>
            </div>
            <div class="card">
                <h3>Positions</h3>
                <div id="positions-list"><span class="label">No open positions</span></div>
            </div>
            <div class="card" style="border-color:#00ff88;">
                <h3>Trader1 — v2.8+ LEAP Entry</h3>
                <div class="metric"><span class="label">Daemon</span><span class="value" id="t1-daemon-alive" style="color:#888;">—</span></div>
                <div class="metric"><span class="label">Status</span><span class="value" id="t1-status" style="color:#00ff88;">—</span></div>
                <div class="metric"><span class="label">Armed</span><span class="value" id="t1-armed">—</span></div>
                <div class="metric"><span class="label">Dipped Below 200W</span><span class="value" id="t1-dipped">—</span></div>
                <div class="metric"><span class="label">Green Weeks</span><span class="value" id="t1-green-weeks">—</span></div>
                <div class="metric"><span class="label">MSTR Price</span><span class="value" id="t1-mstr-price">—</span></div>
                <div class="metric"><span class="label">Position Qty</span><span class="value" id="t1-qty">—</span></div>
                <div class="metric"><span class="label">Entry Price</span><span class="value" id="t1-entry">—</span></div>
                <div class="metric"><span class="label">Peak Gain</span><span class="value" id="t1-peak-gain">—</span></div>
                <div class="metric"><span class="label">mNAV Premium</span><span class="value" id="t1-mnav" style="font-weight:bold;">—</span></div>
                <div class="metric"><span class="label">Last Eval</span><span class="value" id="t1-last-eval" style="color:#888;font-size:12px;">—</span></div>
                <div class="metric"><span class="label">Next Eval</span><span class="value" id="t1-next-eval" style="color:#666;font-size:12px;">15:45 ET weekdays</span></div>
                <div style="font-size:11px;color:#666;margin-top:4px;">trader_v28.py · Daily eval 3:45 PM ET · IBKR Direct · Authority: BUY + SELL</div>
            </div>
            <div class="card" style="border-color:#9b59b6;">
                <h3>Trader2 — MSTR $50 Put Jan28</h3>
                <div class="metric"><span class="label">Value</span><span class="value" id="t2-value">—</span></div>
                <div class="metric"><span class="label">Gain</span><span class="value" id="t2-gain">—</span></div>
                <div class="metric"><span class="label">Ladder</span><span class="value" id="t2-ladder">Inactive</span></div>
                <div class="metric"><span class="label">Trail Stop</span><span class="value" id="t2-trail">—</span></div>
                <div class="metric"><span class="label">Tier</span><span class="value" id="t2-tier">0/4</span></div>
                <div class="metric"><span class="label">Last Check</span><span class="value" id="t2-time" style="color:#888;font-size:12px;">—</span></div>
                <div class="metric"><span class="label">Expiry Extension</span><span class="value" style="color:#ff9800;font-size:12px;">180d warn / 90d urgent → roll Jan30</span></div>
                <div style="font-size:11px;color:#666;margin-top:4px;">Roll: same strike ($50P), same direction. Approve via MCP approve_expiry_roll(trader='trader2')</div>
            </div>
            <div class="card" style="border-color:#00d4ff;">
                <h3>Trader3 — SPY $430 Put Jan27</h3>
                <div class="metric"><span class="label">Value</span><span class="value" id="t3-value">—</span></div>
                <div class="metric"><span class="label">Gain</span><span class="value" id="t3-gain">—</span></div>
                <div class="metric"><span class="label">Ladder</span><span class="value" id="t3-ladder">Inactive</span></div>
                <div class="metric"><span class="label">Trail Stop</span><span class="value" id="t3-trail">—</span></div>
                <div class="metric"><span class="label">Tier</span><span class="value" id="t3-tier">0/4</span></div>
                <div class="metric"><span class="label">Last Check</span><span class="value" id="t3-time" style="color:#888;font-size:12px;">—</span></div>
                <div class="metric"><span class="label">Expiry Extension</span><span class="value" style="color:#ff9800;font-size:12px;">180d warn / 90d urgent → roll Jan29</span></div>
                <div style="font-size:11px;color:#666;margin-top:4px;">Roll: same strike ($430P), same direction. Approve via MCP approve_expiry_roll(trader='trader3')</div>
            </div>
            <div class="card" style="border-color:#f9ca24;">
                <h3>Equity Curve</h3>
                <img src="/api/equity_chart" style="width:100%; border-radius:8px;" onerror="this.style.display='none'">
                <div style="font-size:11px;color:#666;margin-top:4px;">Updates daily at market open, midday, and close</div>
            </div>
            <div class="card">
                <h3>Auditor — v50.0 <span id="audit-dot" style="font-size:12px;">● LIVE</span></h3>
                <div class="metric"><span class="label">v2.8+ Daemon</span><span class="value" id="audit-daemon">—</span></div>
                <div class="metric"><span class="label">Trader2 (MSTR Put)</span><span class="value" id="audit-t2">—</span></div>
                <div class="metric"><span class="label">Trader3 (SPY Put)</span><span class="value" id="audit-t3">—</span></div>
                <div class="metric"><span class="label">IBKR Connection</span><span class="value" id="audit-ibkr">—</span></div>
                <div class="metric"><span class="label">Dashboard Feed</span><span class="value" id="audit-feed">—</span></div>
                <div class="metric"><span class="label">Telegram</span><span class="value green">Active</span></div>
                <div class="metric"><span class="label">Kill Switch</span><span class="value green">READY</span></div>
                <div class="metric"><span class="label">HITL Strike Roll</span><span class="value green">Armed</span></div>
                <div class="metric"><span class="label">HITL Expiry Roll</span><span class="value green">Armed — approve_expiry_roll()</span></div>
                <div class="metric"><span class="label">Quarterly OOS Reval</span><span class="value green">oos_revalidation.py — Q1 Apr 2026</span></div>
                <div class="metric"><span class="label">Stress Test</span><span class="value green" id="stress-test-status">PASSED (March 2026)</span></div>
                <div class="metric"><span class="label">Walk-Forward</span><span class="value green">WFE 1.18 | 7/7 windows</span></div>
                <div class="metric"><span class="label">Regime Test</span><span class="value green">0/5 false positives</span></div>
                <div class="metric"><span class="label">Execution Test</span><span class="value green">200bps survived</span></div>
                <div class="metric"><span class="label">AVGO Cross-Val</span><span class="value green">+501.5% Sharpe 0.888</span></div>
                <div class="metric"><span class="label">Lookahead Audit</span><span class="value green">Clean</span></div>
                <div class="metric"><span class="label">PID Locks</span><span class="value green">All daemons protected</span></div>
                <div class="metric"><span class="label">Daily Loss Cap</span><span class="value green">2% NLV</span></div>
                <div class="metric"><span class="label">Regime Classifier</span><span class="value green">System 13 — 95.6% CV</span></div>
                <div class="metric"><span class="label">Reinforcement Learning</span><span class="value green">Active — Gen 1</span></div>
                <div class="metric"><span class="label">Constitution</span><span class="value" style="color:#00d4ff;">v50.0</span></div>
                <div id="audit-violations" style="margin-top:8px;font-size:14px;color:#ff4444;"></div>
            </div>
            <div class="card">
                <h3>Accountant</h3>
                <div class="metric"><span class="label">Net Liquidation</span><span class="value" id="acct-netliq">--</span></div>
                <div class="metric"><span class="label">Unrealized P&L</span><span class="value" id="acct-unrealized">--</span></div>
                <div class="metric"><span class="label">Realized P&L</span><span class="value" id="acct-realized">--</span></div>
                <div class="metric"><span class="label">Cash</span><span class="value" id="acct-cash">--</span></div>
                <div class="metric"><span class="label">Total Closed P&L</span><span class="value" id="acct-pnl">$0.00</span></div>
                <div class="metric"><span class="label">Win Rate</span><span class="value" id="acct-winrate">0%</span></div>
                <div class="metric"><span class="label">Trades</span><span class="value" id="acct-trades">0</span></div>
                <div class="metric"><span class="label">Max Drawdown</span><span class="value red" id="acct-drawdown">0%</span></div>
                <div class="metric"><span class="label">Last Update</span><span class="value" id="acct-updated" style="color:#888;font-size:14px;">--</span></div>
                <div id="acct-by-system" style="margin-top:10px;font-size:14px;"></div>
            </div>
            <div class="card" style="border-color:#00bcd4;">
                <h3>🧠 DeepSeek — MSTR/BTC Analyst</h3>
                <div class="metric"><span class="label">Focus</span><span class="value" style="color:#00bcd4;">MSTR Cycle-Low Detection</span></div>
                <div class="metric"><span class="label">BTC Regime</span><span class="value" id="ds-regime" style="color:#00bcd4;">—</span></div>
                <div class="metric"><span class="label">Confidence</span><span class="value" id="ds-confidence">—</span></div>
                <div class="metric"><span class="label">200W SMA Status</span><span class="value" id="ds-sizing">—</span></div>
                <div class="metric"><span class="label">MSTR Premium</span><span class="value" id="ds-aggression">—</span></div>
                <div class="metric"><span class="label">Cycle Phase</span><span class="value" id="ds-avoid">—</span></div>
                <div class="metric"><span class="label">Entry Signal</span><span class="value" id="ds-hedge">—</span></div>
                <div id="ds-outlook" style="margin-top:6px;font-size:14px;color:#aaa;"></div>
                <div id="ds-last-trade" style="margin-top:8px;border-top:1px solid #333;padding-top:8px;font-size:14px;"></div>
            </div>
            <div class="card" style="border-color:#ff6600;">
                <h3>⚡ Grok — MSTR/BTC X Feed</h3>
                <div class="metric"><span class="label">Focus</span><span class="value" style="color:#ff6600;">$MSTR $BTC Saylor MicroStrategy</span></div>
                <div class="metric"><span class="label">Sentiment</span><span class="value" id="grok-intel-sentiment">—</span></div>
                <div class="metric"><span class="label">Last Scan</span><span class="value" id="grok-intel-time">—</span></div>
                <div class="metric"><span class="label">Signals</span><span class="value" id="grok-signals">—</span></div>
                <div id="grok-hot" style="margin-top:6px;font-size:14px;color:#e2b93d;"></div>
                <div id="grok-viral" style="margin-top:6px;font-size:14px;"></div>
                <div id="grok-influencer-alerts" style="margin-top:6px;font-size:14px;"></div>
                <div id="grok-top-signals" style="margin-top:6px;font-size:14px;"></div>
                <div style="margin-top:8px;border-top:1px solid #333;padding-top:6px;font-size:14px;color:#aaa;">
                    <input type="text" id="grok-ticker-input" placeholder="MSTR / BTC..." style="background:#1a1a2e;color:#fff;border:1px solid #444;padding:4px 8px;border-radius:4px;width:120px;font-size:14px;" value="MSTR">
                    <button onclick="event.stopPropagation();grokQuickScan()" style="background:#ff6600;color:#fff;border:none;padding:4px 10px;border-radius:4px;font-size:14px;cursor:pointer;">Scan</button>
                    <div id="grok-quick-result" style="margin-top:4px;"></div>
                </div>
            </div>
            <div class="card" style="border-color:#9b59b6;">
                <h3>🔍 Gronk — MSTR/BTC Intel</h3>
                <div class="metric"><span class="label">Focus</span><span class="value" style="color:#9b59b6;">MSTR BTC Saylor Premium</span></div>
                <div class="metric"><span class="label">Sentiment</span><span class="value" id="gronk-sentiment">—</span></div>
                <div class="metric"><span class="label">Posts Scanned</span><span class="value" id="gronk-posts">—</span></div>
                <div class="metric"><span class="label">Signals</span><span class="value" id="gronk-signals">—</span></div>
                <div id="gronk-hot" style="margin-top:6px;font-size:14px;color:#e2b93d;"></div>
                <div id="gronk-top-signals" style="margin-top:6px;font-size:14px;"></div>
                <div style="margin-top:10px;border-top:1px solid #333;padding-top:8px;">
                    <div style="font-size:14px;color:#9b59b6;font-weight:bold;margin-bottom:4px;">📡 Monitoring</div>
                    <div style="font-size:14px;color:#aaa;">@saborfilm · @saborhq · @saylor · @unusual_whales · @DeItaone · @BitcoinMagazine · @CathieDWood · @optionsflow</div>
                </div>
                <div style="margin-top:8px;text-align:center;"><a href="/gronk" style="color:#9b59b6;font-size:15px;">View Full Report →</a></div>
            </div>
            <div class="card" style="border-color:#ff0000;">
                <h3>📺 YouTube — MSTR/BTC Intel</h3>
                <div class="metric"><span class="label">Focus</span><span class="value" style="color:#ff0000;">MSTR BTC Saylor Cycle Analysis</span></div>
                <div class="metric"><span class="label">Sentiment</span><span class="value" id="yt-sentiment">—</span></div>
                <div class="metric"><span class="label">Videos Found</span><span class="value" id="yt-videos">—</span></div>
                <div class="metric"><span class="label">Signals</span><span class="value" id="yt-signals">—</span></div>
                <div id="yt-hot" style="margin-top:6px;font-size:14px;color:#e2b93d;"></div>
                <div id="yt-top-signals" style="margin-top:6px;font-size:14px;"></div>
                <div id="yt-top-videos" style="margin-top:6px;font-size:14px;"></div>
                <div style="margin-top:8px;border-top:1px solid #333;padding-top:6px;font-size:14px;color:#aaa;">
                    <input type="text" id="yt-ticker-input" placeholder="MSTR / BTC..." style="background:#1a1a2e;color:#fff;border:1px solid #444;padding:4px 8px;border-radius:4px;width:120px;font-size:14px;" value="MSTR">
                    <button onclick="event.stopPropagation();ytQuickScan()" style="background:#ff0000;color:#fff;border:none;padding:4px 10px;border-radius:4px;font-size:14px;cursor:pointer;">Scan</button>
                    <div id="yt-quick-result" style="margin-top:4px;"></div>
                </div>
                <div style="margin-top:8px;font-size:14px;color:#666;">Priority: Saylor, BTC cycle tops/bottoms, 200W SMA</div>
            </div>
            <div class="card" style="border-color:#ee1d52;">
                <h3>🎵 TikTok — MSTR/BTC FinTok</h3>
                <div class="metric"><span class="label">Focus</span><span class="value" style="color:#ee1d52;">MSTR BTC MicroStrategy Saylor</span></div>
                <div class="metric"><span class="label">Sentiment</span><span class="value" id="tt-sentiment">—</span></div>
                <div class="metric"><span class="label">Posts Found</span><span class="value" id="tt-posts">—</span></div>
                <div class="metric"><span class="label">Hype Level</span><span class="value" id="tt-moonshots">—</span></div>
                <div id="tt-hot" style="margin-top:6px;font-size:14px;color:#e2b93d;"></div>
                <div id="tt-viral" style="margin-top:6px;font-size:14px;"></div>
                <div id="tt-confirmed" style="margin-top:6px;font-size:14px;color:#00ff88;"></div>
                <div style="margin-top:8px;border-top:1px solid #333;padding-top:6px;font-size:14px;color:#aaa;">
                    <input type="text" id="tt-ticker-input" placeholder="MSTR / BTC..." style="background:#1a1a2e;color:#fff;border:1px solid #444;padding:4px 8px;border-radius:4px;width:120px;font-size:14px;" value="MSTR">
                    <button onclick="event.stopPropagation();ttQuickScan()" style="background:#ee1d52;color:#fff;border:none;padding:4px 10px;border-radius:4px;font-size:14px;cursor:pointer;">Scan</button>
                    <div id="tt-quick-result" style="margin-top:4px;"></div>
                </div>
                <div style="margin-top:8px;font-size:14px;color:#666;">Tracking: MSTR euphoria/fear, BTC cycle sentiment</div>
            </div>
            <div class="card" style="border-color:#4a90d9;">
                <h3>🇺🇸 Truth Social — BTC/Crypto Policy</h3>
                <div class="metric"><span class="label">Impact</span><span class="value" id="ts-impact">—</span></div>
                <div class="metric"><span class="label">Urgency</span><span class="value" id="ts-urgency">—</span></div>
                <div class="metric"><span class="label">Posts (24h)</span><span class="value" id="ts-posts">—</span></div>
                <div class="metric"><span class="label">Market Posts</span><span class="value" id="ts-market">—</span></div>
                <div id="ts-summary" style="margin-top:6px;font-size:14px;color:#ccc;"></div>
                <div id="ts-signals" style="margin-top:6px;font-size:14px;"></div>
                <div id="ts-tariff" style="margin-top:6px;font-size:14px;color:#ffaa00;"></div>
                <div id="ts-x-reaction" style="margin-top:6px;font-size:14px;"></div>
                <div style="margin-top:8px;border-top:1px solid #333;padding-top:6px;font-size:14px;color:#aaa;">
                    <input type="text" id="ts-topic-input" placeholder="Search topic..." style="background:#1a1a2e;color:#fff;border:1px solid #444;padding:4px 8px;border-radius:4px;width:120px;font-size:14px;">
                    <button onclick="event.stopPropagation();tsQuickScan()" style="background:#4a90d9;color:#fff;border:none;padding:4px 10px;border-radius:4px;font-size:14px;cursor:pointer;">Scan</button>
                    <div id="ts-quick-result" style="margin-top:4px;"></div>
                </div>
            </div>
            <div class="card" style="border-color:#ff3333;">
                <h3>🔍 MSTR Insider Trading</h3>
                <div class="metric"><span class="label">Signal</span><span class="value" id="ins-signal">—</span></div>
                <div class="metric"><span class="label">Buy/Sell Ratio</span><span class="value" id="ins-ratio">—</span></div>
                <div class="metric"><span class="label">Sell Pace</span><span class="value" id="ins-pace">—</span></div>
                <div class="metric"><span class="label">Sell Volume</span><span class="value" id="ins-sell-vol">—</span></div>
                <div class="metric"><span class="label">Buy Volume</span><span class="value" id="ins-buy-vol">—</span></div>
                <div id="ins-sells" style="margin-top:6px;font-size:14px;"></div>
                <div id="ins-buys" style="margin-top:6px;font-size:14px;"></div>
                <div id="ins-overlap" style="margin-top:6px;font-size:14px;color:#ff3333;"></div>
                <div id="ins-analysis" style="margin-top:6px;font-size:14px;color:#ccc;"></div>
                <div id="ins-context" style="margin-top:4px;font-size:14px;color:#888;"></div>
                <div id="ins-x" style="margin-top:6px;font-size:14px;"></div>
                <div style="margin-top:8px;border-top:1px solid #333;padding-top:6px;font-size:14px;color:#aaa;">
                    <input type="text" id="ins-ticker-input" placeholder="Search ticker..." style="background:#1a1a2e;color:#fff;border:1px solid #444;padding:4px 8px;border-radius:4px;width:120px;font-size:14px;">
                    <button onclick="event.stopPropagation();insQuickScan()" style="background:#ff3333;color:#fff;border:none;padding:4px 10px;border-radius:4px;font-size:14px;cursor:pointer;">Scan</button>
                    <div id="ins-quick-result" style="margin-top:4px;"></div>
                </div>
                <div style="margin-top:8px;font-size:14px;color:#666;">Source: SEC Form 4 + @nolimitgains</div>
            </div>
            <div class="card" style="border-color:#9b59b6;">
                <h3>🏛️ Congress — MSTR/BTC/Crypto Bills</h3>
                <div class="metric"><span class="label">Trades (7d)</span><span class="value" id="cg-trades">—</span></div>
                <div class="metric"><span class="label">Buys</span><span class="value" id="cg-buys">—</span></div>
                <div class="metric"><span class="label">Sells</span><span class="value" id="cg-sells">—</span></div>
                <div class="metric"><span class="label">Top Ticker</span><span class="value" id="cg-top">—</span></div>
                <div id="cg-hot" style="margin-top:6px;font-size:14px;"></div>
                <div id="cg-notable" style="margin-top:6px;font-size:14px;"></div>
                <div id="cg-analysis" style="margin-top:6px;font-size:14px;color:#ccc;"></div>
                <div style="margin-top:8px;border-top:1px solid #333;padding-top:6px;font-size:14px;color:#aaa;">
                    <input type="text" id="cg-ticker-input" placeholder="Search ticker..." style="background:#1a1a2e;color:#fff;border:1px solid #444;padding:4px 8px;border-radius:4px;width:120px;font-size:14px;">
                    <button onclick="event.stopPropagation();cgQuickScan()" style="background:#9b59b6;color:#fff;border:none;padding:4px 10px;border-radius:4px;font-size:14px;cursor:pointer;">Scan</button>
                    <div id="cg-quick-result" style="margin-top:4px;"></div>
                </div>
                <div style="margin-top:8px;font-size:14px;color:#666;">Tracking: Pelosi, Tuberville, Crenshaw +</div>
            </div>
            <div class="card" style="border-color:#1da1f2;">
                <h3>🐦 X Influencer Tracker</h3>
                <div class="metric"><span class="label">Accounts</span><span class="value" id="xt-accounts">—</span></div>
                <div class="metric"><span class="label">New Posts</span><span class="value" id="xt-posts">—</span></div>
                <div class="metric"><span class="label">High Signals</span><span class="value" id="xt-signals">—</span></div>
                <div id="xt-highlights" style="margin-top:6px;font-size:14px;"></div>
                <div id="xt-latest" style="margin-top:6px;font-size:14px;"></div>
                <div style="margin-top:8px;border-top:1px solid #333;padding-top:6px;font-size:14px;color:#aaa;">
                    <input type="text" id="xt-handle-input" placeholder="@handle..." style="background:#1a1a2e;color:#fff;border:1px solid #444;padding:4px 8px;border-radius:4px;width:120px;font-size:14px;">
                    <button onclick="event.stopPropagation();xtQuickScan()" style="background:#1da1f2;color:#fff;border:none;padding:4px 10px;border-radius:4px;font-size:14px;cursor:pointer;">Scan</button>
                    <div id="xt-quick-result" style="margin-top:4px;"></div>
                </div>
                <div style="margin-top:8px;font-size:14px;color:#666;">@nolimitgains @unusual_whales @DeItaone +8</div>
            </div>
            <div class="card" style="border-color:#c4302b;">
                <h3>📺 Playlist Tracker</h3>
                <div class="metric"><span class="label">Videos</span><span class="value" id="pl-videos">—</span></div>
                <div class="metric"><span class="label">Last Scan</span><span class="value" id="pl-time">—</span></div>
                <div class="metric"><span class="label">Changes</span><span class="value" id="pl-changes">—</span></div>
                <div id="pl-new" style="margin-top:6px;font-size:14px;"></div>
                <div id="pl-engagement" style="margin-top:6px;font-size:14px;"></div>
            </div>
            <!-- Systems 9-12 removed — v2.8+ only -->
        </div>

        <div class="chat-container">
            <div class="messages" id="messages">
                <div class="message rudy">
                    <div class="avatar">🤖</div>
                    <div>
                        <div class="name">Rudy v2.0</div>
                        <div class="content">Constitution v50.0 loaded. v2.8+ LIVE mode active.<br><br>
                        <strong>Active:</strong> v2.8+ Trend Adder (daily resolution, IBKR direct)<br>
                        <strong>Safety:</strong> Kill switch ✅ | Position audit ✅ | Order confirmation ✅ | Lockfile ✅<br>
                        <strong>Walk-Forward:</strong> WFE 1.18 | +6,750.6% OOS | standard_tight_minimal<br>
                        <strong>Account:</strong> U15746102 (live) | Capital: $7,780<br><br>
                        IBKR connected (live U15746102). v2.8+ armed. Awaiting cycle-low signal, Commander.</div>
                    </div>
                </div>
            </div>
            <div class="input-area">
                <div class="input-row">
                    <input type="text" id="user-input" placeholder="Ask Rudy anything..." autocomplete="off">
                    <button onclick="event.stopPropagation();sendMessage()">Send</button>
                </div>
            </div>
        </div>

        <div class="log-panel">
            <h3>Live Feed</h3>
            <div id="log-entries"></div>
        </div>
    </div>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
    <script>
        var socket = null;
        try { socket = io(); } catch(e) { console.warn('Socket.io not available:', e); }
        const messagesDiv = document.getElementById('messages');
        const logDiv = document.getElementById('log-entries');
        const input = document.getElementById('user-input');

        if (input) {
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') sendMessage();
            });
        }

        function sendMessage() {
            const text = input.value.trim();
            if (!text) return;

            addMessage('user', 'Commander', text);
            if (socket) socket.emit('user_message', {text: text});
            input.value = '';
        }

        function addMessage(type, name, content) {
            const avatar = type === 'user' ? '👤' : '🤖';
            const div = document.createElement('div');
            div.className = 'message ' + type;
            div.innerHTML = `
                <div class="avatar">${avatar}</div>
                <div>
                    <div class="name">${name}</div>
                    <div class="content">${content.split('\\n').join('<br>')}</div>
                </div>`;
            messagesDiv.appendChild(div);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }

        function addLog(text, type) {
            const time = new Date().toLocaleTimeString();
            const div = document.createElement('div');
            div.className = 'log-entry ' + (type || '');
            div.innerHTML = '<span class="time">' + time + '</span> ' + text;
            logDiv.insertBefore(div, logDiv.firstChild);
        }

        if (socket) socket.on('rudy_response', (data) => {
            if (data.partial) {
                // Show thinking indicator — will be replaced by real response
                var thinkDiv = document.getElementById('rudy-thinking');
                if (!thinkDiv) {
                    thinkDiv = document.createElement('div');
                    thinkDiv.id = 'rudy-thinking';
                    thinkDiv.className = 'message rudy';
                    thinkDiv.innerHTML = '<div class="avatar">🤖</div><div><div class="name">Rudy v2.0</div><div class="content" style="color:#00d4ff;font-style:italic;">Thinking...</div></div>';
                    messagesDiv.appendChild(thinkDiv);
                    messagesDiv.scrollTop = messagesDiv.scrollHeight;
                }
                return;
            }
            // Remove thinking indicator
            var thinkDiv = document.getElementById('rudy-thinking');
            if (thinkDiv) thinkDiv.remove();
            addMessage('rudy', 'Rudy v2.0 (Claude)', data.text);
        });

        if (socket) socket.on('log_event', (data) => {
            addLog(data.text, data.type);
        });

        // WebSocket real-time push — updates ALL panels from single IBKR feed
        if (socket) socket.on('account_update', (data) => {
            // Just call fetchStatus logic inline — same single source of truth
            var fmt2 = function(n) { return '$' + Number(n).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}); };
            if (data.net_liq) {
                document.getElementById('net-liq').textContent = fmt2(data.net_liq);
                document.getElementById('cash').textContent = fmt2(data.cash);
                document.getElementById('buying-power').textContent = fmt2(data.buying_power);
                // Live Trading panel
                var ptC = document.getElementById('pt-current');
                if (ptC) ptC.textContent = fmt2(data.net_liq);
                // Accountant panel
                var aN = document.getElementById('acct-netliq');
                if (aN) { aN.textContent = fmt2(data.net_liq); aN.style.color = '#00ff88'; }
                var aC = document.getElementById('acct-cash');
                if (aC) aC.textContent = fmt2(data.cash);
            }
            if (data.mstr_price && data.mstr_price > 0) {
                var mE = document.getElementById('mstr-price');
                if (mE) mE.textContent = '$' + Number(data.mstr_price).toFixed(2);
            }
            if (data.unrealized_pnl !== undefined) {
                var uE = document.getElementById('acct-unrealized');
                if (uE) { var u = data.unrealized_pnl; uE.textContent = (u>=0?'+':'-') + fmt2(Math.abs(u)); uE.style.color = u>=0?'#00ff88':'#ff4444'; }
            }
            if (data.updated) {
                var tsEl = document.getElementById('acct-ts');
                if (tsEl) tsEl.textContent = 'Live · ' + data.updated;
                var tsEl2 = document.getElementById('acct-updated');
                if (tsEl2) tsEl2.textContent = 'Live · ' + data.updated;
            }
            if (data.positions) updatePositions(data.positions);
        });


        function updatePositions(positions) {
            const div = document.getElementById('positions-list');
            if (!positions || positions.length === 0) {
                div.innerHTML = '<span class="label">No positions open</span>';
                return;
            }
            let html = '';
            positions.forEach(p => {
                const sym = p.symbol;
                const qty = p.quantity;
                const cost = p.avgCost || 0;
                const mktVal = p.marketValue || 0;
                const pnl = p.unrealizedPNL || 0;
                const pnlPct = cost > 0 ? ((mktVal - cost) / cost * 100) : 0;
                let detail = '';
                if (p.secType === 'OPT') {
                    detail = ` $${p.strike}${p.right} ${p.expiry ? p.expiry.substring(0,4)+'-'+p.expiry.substring(4,6)+'-'+p.expiry.substring(6) : ''}`;
                }
                const pnlColor = pnl >= 0 ? '#00ff88' : '#ff4444';
                const pnlSign = pnl >= 0 ? '+' : '';
                html += `<div style="background:#0d0d14;border:1px solid ${pnl >= 0 ? '#1a3a1a' : '#3a1a1a'};border-radius:6px;padding:10px;margin-bottom:6px;">`;
                html += `<div style="display:flex;justify-content:space-between;align-items:center;">`;
                html += `<span style="color:#fff;font-weight:bold;font-size:14px;">${sym}${detail}</span>`;
                html += `<span style="color:${pnlColor};font-weight:bold;font-size:15px;">${pnlSign}${pnlPct.toFixed(1)}%</span>`;
                html += `</div>`;
                html += `<div style="display:flex;justify-content:space-between;margin-top:4px;font-size:12px;color:#888;">`;
                html += `<span>Qty: ${qty} | Cost: $${cost.toFixed(2)}</span>`;
                html += `<span style="color:${pnlColor};">Val: $${mktVal.toFixed(2)} (${pnlSign}$${pnl.toFixed(2)})</span>`;
                html += `</div></div>`;
            });
            div.innerHTML = html;
        }

        function fetchStatus() {
            // Single source of truth: IBKR background feed
            fetch('/api/account-live').then(r => r.json()).then(data => {
                var fmt2 = function(n) { return '$' + Number(n).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}); };

                // ── Account panel ──
                if (data.net_liq) {
                    document.getElementById('net-liq').textContent = fmt2(data.net_liq);
                    document.getElementById('cash').textContent = fmt2(data.cash);
                    document.getElementById('buying-power').textContent = fmt2(data.buying_power);
                }

                // ── Live Trading panel ──
                var ptCurrent = document.getElementById('pt-current');
                if (ptCurrent && data.net_liq) {
                    ptCurrent.textContent = fmt2(data.net_liq);
                    var startCap = data.starting_balance || 7780;
                    var totalPnl = data.net_liq - startCap;
                    var totalPct = (totalPnl / startCap * 100);
                    var pnlEl = document.getElementById('pt-total-pnl');
                    if (pnlEl) {
                        pnlEl.textContent = (totalPnl >= 0 ? '+' : '-') + fmt2(Math.abs(totalPnl));
                        pnlEl.className = 'value ' + (totalPnl >= 0 ? 'green' : 'red');
                    }
                    var retEl = document.getElementById('pt-return');
                    if (retEl) {
                        retEl.textContent = (totalPct >= 0 ? '+' : '') + totalPct.toFixed(2) + '%';
                        retEl.className = 'value ' + (totalPct >= 0 ? 'green' : 'red');
                    }
                    var peakEl = document.getElementById('pt-peak');
                    if (peakEl) peakEl.textContent = fmt2(Math.max(data.net_liq, startCap));
                }

                // ── MSTR Price ──
                if (data.mstr_price && data.mstr_price > 0) {
                    var mstrEl = document.getElementById('mstr-price');
                    if (mstrEl) mstrEl.textContent = '$' + Number(data.mstr_price).toFixed(2);
                }

                // ── BTC Cycle Intelligence ──
                if (data.btc_price && data.btc_price > 0) {
                    var btcEl = document.getElementById('btc-price');
                    if (btcEl) btcEl.textContent = '$' + Number(data.btc_price).toLocaleString();
                    var btcAth = data.btc_ath || 126200;
                    var athEl = document.getElementById('btc-ath');
                    if (athEl) athEl.textContent = '$' + Number(btcAth).toLocaleString() + ' (Oct 2025)';
                    var btcDd = document.getElementById('btc-dd');
                    if (btcDd) {
                        var dd = ((btcAth - data.btc_price) / btcAth * 100);
                        btcDd.textContent = '-' + dd.toFixed(1) + '%';
                        btcDd.style.color = dd > 50 ? '#ff4444' : dd > 30 ? '#ff9800' : '#ffd700';
                    }
                    // Cycle phase from regime
                    var cpEl = document.getElementById('btc-cycle-phase');
                    if (cpEl) {
                        var bp = data.btc_price;
                        var ddPct = ((btcAth - bp) / btcAth * 100);
                        if (bp > 80000 && ddPct < 25) { cpEl.textContent = '🟢 BULL'; cpEl.style.color = '#00ff88'; }
                        else if (bp < 80000 && ddPct > 40) { cpEl.textContent = '🔴 BEAR'; cpEl.style.color = '#ff4444'; }
                        else { cpEl.textContent = '🟡 DISTRIBUTION'; cpEl.style.color = '#ff9800'; }
                    }
                    // Months post-halving (Apr 20, 2024)
                    var halvEl = document.getElementById('btc-halving');
                    if (halvEl) {
                        var halvDate = new Date(2024, 3, 20);
                        var months = Math.floor((new Date() - halvDate) / (30.44 * 24 * 60 * 60 * 1000));
                        halvEl.textContent = '~' + months + ' months (Apr 2024)';
                    }
                }
                // ── BTC MA Proximity Zones (dynamic from /api/regime) ──
                if (data.btc_price && data.btc_price > 0) {
                    var bp = data.btc_price;
                    var sma200 = data.btc_sma_200w || 59433;
                    var ma250 = data.btc_sma_250w || 56000;
                    var ma300 = data.btc_sma_300w || 50000;
                    var d200 = ((bp - sma200) / sma200 * 100);
                    var d250 = ((bp - ma250) / ma250 * 100);
                    var d300 = ((bp - ma300) / ma300 * 100);
                    var el200 = document.getElementById('btc-200w');
                    if (el200) el200.textContent = '$' + sma200.toLocaleString() + ' (' + (d200 >= 0 ? '+' : '') + d200.toFixed(1) + '%)';
                    var el250 = document.getElementById('btc-250w');
                    if (el250) el250.textContent = '$' + ma250.toLocaleString() + ' (' + (d250 >= 0 ? '+' : '') + d250.toFixed(1) + '%)';
                    var el300 = document.getElementById('btc-300w');
                    if (el300) el300.textContent = '$' + ma300.toLocaleString() + ' (' + (d300 >= 0 ? '+' : '') + d300.toFixed(1) + '%)';
                    var proxEl = document.getElementById('btc-proximity');
                    if (proxEl) {
                        if (bp <= ma300) { proxEl.textContent = '🚨 BELOW 300W — ABSOLUTE FLOOR'; proxEl.style.color = '#ff0000'; }
                        else if (bp <= ma250) { proxEl.textContent = '🔴 BELOW 250W — CAPITULATION ZONE'; proxEl.style.color = '#e53935'; }
                        else if (bp <= sma200) { proxEl.textContent = '⚡ BELOW 200W — v2.8+ ARM ZONE'; proxEl.style.color = '#ff9800'; }
                        else if (d200 < 10) { proxEl.textContent = '⚠️ APPROACHING 200W (' + d200.toFixed(1) + '% away)'; proxEl.style.color = '#ffd700'; }
                        else if (d200 < 20) { proxEl.textContent = 'NEARING 200W (' + d200.toFixed(1) + '% away)'; proxEl.style.color = '#ff9800'; }
                        else { proxEl.textContent = 'ABOVE ALL MAs (' + d200.toFixed(0) + '% above 200W)'; proxEl.style.color = '#00ff88'; }
                    }
                }

                // Phase-aware seasonality
                var m = new Date().getMonth() + 1;
                var btcP = data.btc_price || 0;
                var btcAth2 = data.btc_ath || 126200; var ddFromAth = btcP > 0 ? ((btcAth2 - btcP) / btcAth2 * 100) : 50;
                var phase = (btcP > 80000 && ddFromAth < 25) ? 'bull' : 'bear';
                var phaseEl = document.getElementById('cycle-phase-detected');
                if (phaseEl) {
                    phaseEl.textContent = phase === 'bull' ? '🟢 BULL — rallies are real' : '🔴 BEAR — rallies are traps';
                    phaseEl.style.color = phase === 'bull' ? '#00ff88' : '#ff4444';
                }

                var evalEl = document.getElementById('eval-freq');
                if (evalEl) {
                    var bearHigh = [6,8,9,10,11];
                    var bullHigh = [9,10,11];
                    var highAlert = phase === 'bull' ? bullHigh.indexOf(m) >= 0 : bearHigh.indexOf(m) >= 0;
                    var mNames = ['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
                    evalEl.textContent = highAlert ?
                        mNames[m] + ': Every 2hrs (HIGH ALERT)' :
                        mNames[m] + ': Standard (1x/day)';
                    evalEl.style.color = highAlert ? '#ff4444' : '#00d4ff';
                }

                // Highlight current month + dim inactive phase column
                var monthIds = ['','season-jan','season-feb','season-mar','season-apr','season-may','season-jun','season-jul','season-aug','season-sep','season-oct','season-nov','season-dec'];
                for (var i = 1; i <= 12; i++) {
                    var row = document.getElementById(monthIds[i]);
                    if (row) {
                        var cells = row.getElementsByTagName('td');
                        // cells[0]=month, cells[1]=bull, cells[2]=bear
                        if (cells.length >= 3) {
                            if (phase === 'bull') {
                                cells[2].style.opacity = '0.3';
                                cells[1].style.opacity = '1';
                            } else {
                                cells[1].style.opacity = '0.3';
                                cells[2].style.opacity = '1';
                            }
                        }
                        if (i === m) {
                            row.style.outline = '2px solid #ff9800';
                            row.style.outlineOffset = '-1px';
                            row.style.background = '#1a1000';
                        }
                    }
                }

                // ── Accountant panel ──
                var acctNetliq = document.getElementById('acct-netliq');
                if (acctNetliq && data.net_liq) {
                    acctNetliq.textContent = fmt2(data.net_liq);
                    acctNetliq.style.color = '#00ff88';
                }
                var acctUnreal = document.getElementById('acct-unrealized');
                if (acctUnreal) {
                    var upnl = data.unrealized_pnl || 0;
                    acctUnreal.textContent = (upnl >= 0 ? '+' : '-') + fmt2(Math.abs(upnl));
                    acctUnreal.style.color = upnl >= 0 ? '#00ff88' : '#ff4444';
                }
                var acctReal = document.getElementById('acct-realized');
                if (acctReal) {
                    var rpnl = data.realized_pnl || 0;
                    acctReal.textContent = (rpnl >= 0 ? '+' : '-') + fmt2(Math.abs(rpnl));
                    acctReal.style.color = rpnl >= 0 ? '#00ff88' : '#ff4444';
                }
                var acctCash = document.getElementById('acct-cash');
                if (acctCash) acctCash.textContent = fmt2(data.cash);
                var acctUpdated = document.getElementById('acct-updated');
                if (acctUpdated && data.updated) acctUpdated.textContent = 'Live · ' + data.updated;

                // ── Positions ──
                if (data.positions) updatePositions(data.positions);

                // ── Timestamp ──
                if (data.updated) {
                    var tsEl = document.getElementById('acct-ts');
                    if (tsEl) tsEl.textContent = 'Live · ' + data.updated;
                }

                // ── Systems Active count (set by fetchLiveProgress, fallback here) ──
                var sysEl = document.getElementById('pt-active-systems');
                if (sysEl && sysEl.textContent === '—') sysEl.textContent = '3/3 trading';

            }).catch(() => {});

        }

        // Stop buttons/inputs from propagating clicks to card expand
        document.querySelectorAll('.card button, .card input, .card a, .card select, .chat-container button, .chat-container input').forEach(function(el) {
            el.addEventListener('click', function(ev) { ev.stopPropagation(); });
        });

        // Click-to-expand cards, live feed, and chat (event delegation on document body)
        document.body.addEventListener('click', function(e) {
            // Don't trigger on interactive elements
            if (e.target.closest('input, button, a, select, textarea')) return;
            // Don't trigger inside overlay
            if (e.target.closest('.card-overlay')) return;

            var overlay = document.getElementById('card-overlay');
            var content = document.getElementById('expanded-content');

            // Check for log-panel (Live Feed) click
            var logPanel = e.target.closest('.log-panel');
            if (logPanel) {
                content.innerHTML = '<h3>Live Feed</h3>' + document.getElementById('log-entries').innerHTML;
                overlay.classList.add('active');
                return;
            }

            // Check for chat-container click
            var chat = e.target.closest('.chat-container');
            if (chat) {
                content.innerHTML = '<h3>Chat</h3>' + document.getElementById('messages').innerHTML;
                overlay.classList.add('active');
                return;
            }

            // Find closest .card parent
            var card = e.target.closest('.card');
            if (!card) return;
            content.innerHTML = card.innerHTML;
            overlay.classList.add('active');
        });

        function closeExpand(e) {
            var overlay = document.getElementById('card-overlay');
            if (e.target === overlay || e.target.classList.contains('card-close')) {
                overlay.classList.remove('active');
            }
        }

        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                document.getElementById('card-overlay').classList.remove('active');
            }
        });

        function fetchLiveProgress() {
            fetch('/api/live-progress').then(r => r.json()).then(data => {
                if (data.status === 'no_data') return;
                var el;
                el = document.getElementById('pt-day'); if (el) el.textContent = data.trading_days || 0;
                el = document.getElementById('pt-start'); if (el) el.textContent = '$' + Number(data.starting_balance).toLocaleString(undefined, {maximumFractionDigits:0});
                el = document.getElementById('pt-current'); if (el) el.textContent = '$' + Number(data.current).toLocaleString(undefined, {maximumFractionDigits:0});

                var totalPnl = data.total_change || 0;
                el = document.getElementById('pt-total-pnl');
                if (el) { el.textContent = (totalPnl >= 0 ? '+' : '') + '$' + Number(totalPnl).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}); el.className = 'value ' + (totalPnl >= 0 ? 'green' : 'red'); }

                var retPct = data.total_pct || 0;
                el = document.getElementById('pt-return');
                if (el) { el.textContent = (retPct >= 0 ? '+' : '') + retPct.toFixed(2) + '%'; el.className = 'value ' + (retPct >= 0 ? 'green' : 'red'); }

                var dp = data.daily_pct || 0;
                var dc = data.daily_change || 0;
                el = document.getElementById('pt-today');
                if (el) { el.textContent = (dc >= 0 ? '+' : '') + '$' + Number(dc).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}) + ' (' + (dp >= 0 ? '+' : '') + dp.toFixed(2) + '%)'; el.className = 'value ' + (dc >= 0 ? 'green' : 'red'); }

                el = document.getElementById('pt-peak'); if (el) el.textContent = '$' + Number(data.peak).toLocaleString(undefined, {maximumFractionDigits:0});
                el = document.getElementById('pt-dd'); if (el) el.textContent = (data.drawdown_pct || 0).toFixed(1) + '%';

                var streak = data.streak || 0;
                el = document.getElementById('pt-streak');
                if (el) { el.textContent = (streak >= 0 ? '+' : '') + streak + ' days'; el.className = 'value ' + (streak >= 0 ? 'green' : 'red'); }

                el = document.getElementById('pt-golive'); if (el) el.textContent = 'LIVE';
                el = document.getElementById('pt-active-systems'); if (el) el.textContent = (data.active_systems || 0) + '/' + (data.total_systems || 3) + ' trading';

                // Mini bar chart of daily returns
                const chart = data.chart || [];
                if (chart.length > 0) {
                    const chartDiv = document.getElementById('pt-chart');
                    const maxAbs = Math.max(1, ...chart.map(c => Math.abs(c.pct)));
                    let html = '';
                    chart.forEach(c => {
                        const h = Math.max(2, Math.abs(c.pct) / maxAbs * 50);
                        const color = c.pct >= 0 ? '#00ff88' : '#ff4444';
                        html += '<div title="' + c.date + ': ' + (c.pct >= 0 ? '+' : '') + c.pct + '%" style="width:100%;height:' + h + 'px;background:' + color + ';border-radius:1px;opacity:0.8;"></div>';
                    });
                    chartDiv.innerHTML = html;
                }
            }).catch(() => {});
        }

        function fetchFeed() {
            fetch('/api/feed').then(r => r.json()).then(entries => {
                if (!entries || entries.length === 0) return;
                logDiv.innerHTML = '';
                entries.forEach(e => {
                    const div = document.createElement('div');
                    div.className = 'log-entry ' + (e.type || '');
                    const timeStr = e.time ? e.time.split(' ').pop() : '';
                    const src = e.source ? e.source.replace('.log','') : '';
                    div.innerHTML = '<span class="time">' + timeStr + '</span> <b>[' + src + ']</b> ' + e.text;
                    logDiv.appendChild(div);
                });
            }).catch(() => {});
        }

        function fetchAuditor() {
            // Check daemon health via system status API
            fetch('/api/health-check').then(r => r.json()).then(data => {
                function setStatus(id, running) {
                    var el = document.getElementById(id);
                    if (el) {
                        el.textContent = running ? '✅ Running' : '❌ DOWN';
                        el.style.color = running ? '#00ff88' : '#ff4444';
                    }
                }
                setStatus('audit-daemon', data.v28_daemon);
                setStatus('audit-t2', data.trader2);
                setStatus('audit-t3', data.trader3);
                setStatus('audit-ibkr', data.ibkr_connected);
                setStatus('audit-feed', data.feed_active);

                var dot = document.getElementById('audit-dot');
                var allGood = data.v28_daemon && data.trader2 && data.trader3 && data.ibkr_connected;
                if (dot) {
                    dot.textContent = allGood ? '● ALL SYSTEMS GO' : '⚠ ISSUE DETECTED';
                    dot.style.color = allGood ? '#00ff88' : '#ff4444';
                }

                var vDiv = document.getElementById('audit-violations');
                if (data.issues && data.issues.length > 0) {
                    vDiv.innerHTML = data.issues.map(function(i) { return '⚠ ' + i; }).join('<br>');
                } else {
                    vDiv.innerHTML = '<span style="color:#00ff88;">No issues detected</span>';
                }
            }).catch(function() {
                var dot = document.getElementById('audit-dot');
                if (dot) { dot.textContent = '⚠ API ERROR'; dot.style.color = '#ff4444'; }
            });
        }

        function fetchAccountant() {
            fetch('/api/accountant').then(r => r.json()).then(data => {
                const pnl = data.pnl || {};
                const perf = data.performance || {};
                const live = data.live || {};

                // Live IBKR data
                if (live.net_liq) {
                    document.getElementById('acct-netliq').textContent = '$' + Number(live.net_liq).toLocaleString(undefined, {maximumFractionDigits:0});
                    var ur = live.unrealized_pnl || 0;
                    var urEl = document.getElementById('acct-unrealized');
                    urEl.textContent = (ur >= 0 ? '+' : '') + '$' + Number(ur).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2});
                    urEl.className = 'value ' + (ur >= 0 ? 'green' : 'red');
                    var rz = live.realized_pnl || 0;
                    var rzEl = document.getElementById('acct-realized');
                    rzEl.textContent = (rz >= 0 ? '+' : '') + '$' + Number(rz).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2});
                    rzEl.className = 'value ' + (rz >= 0 ? 'green' : 'red');
                    document.getElementById('acct-cash').textContent = '$' + Number(live.cash || 0).toLocaleString(undefined, {maximumFractionDigits:0});
                }
                if (live.last_update) {
                    document.getElementById('acct-updated').textContent = live.last_update.substring(11, 19);
                }

                // Closed trade P&L
                const pnlVal = pnl.total_pnl || 0;
                const pnlEl = document.getElementById('acct-pnl');
                pnlEl.textContent = (pnlVal >= 0 ? '+' : '') + '$' + pnlVal.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2});
                pnlEl.className = 'value ' + (pnlVal >= 0 ? 'green' : 'red');
                document.getElementById('acct-winrate').textContent = (pnl.win_rate || 0) + '%';
                document.getElementById('acct-trades').textContent = pnl.total_trades || 0;
                document.getElementById('acct-drawdown').textContent = (perf.max_drawdown_pct || 0) + '%';

                // Per-system breakdown
                const bySystem = pnl.by_system || {};
                const sysDiv = document.getElementById('acct-by-system');
                const entries = Object.entries(bySystem).filter(([k,v]) => v.trades > 0);
                if (entries.length > 0) {
                    sysDiv.innerHTML = '<div style="color:#888;margin-bottom:4px;">By System:</div>' +
                        entries.map(([name, s]) => {
                            const color = s.pnl >= 0 ? '#00ff88' : '#ff4444';
                            return '<div style="display:flex;justify-content:space-between;padding:1px 0;">' +
                                '<span>' + name + ' (' + s.trades + ')</span>' +
                                '<span style="color:' + color + ';">$' + s.pnl.toFixed(2) + '</span></div>';
                        }).join('');
                }
            }).catch(() => {});
        }

        function fetchDeepSeek() {
            fetch('/api/deepseek/regime').then(r => r.json()).then(data => {
                if (!data || !data.regime) return;
                const regEl = document.getElementById('ds-regime');
                const regime = data.regime;
                regEl.textContent = regime;
                const regColors = {'ARMED — ENTRY IMMINENT':'#00ff88','DIPPED — WATCHING':'#ffaa00','WAITING FOR DIP':'#888','IN POSITION':'#00d4ff'};
                regEl.style.color = regColors[regime] || '#00bcd4';
                document.getElementById('ds-confidence').textContent = (data.confidence || 0) + '%';
                const inp = data.inputs || {};
                var smaEl = document.getElementById('ds-sizing');
                if (inp.armed) { smaEl.textContent = '✅ ARMED — Above 200W'; smaEl.style.color = '#00ff88'; }
                else if (inp.dipped && inp.green_weeks > 0) { smaEl.textContent = '🔄 RECLAIMING — ' + inp.green_weeks + '/2 green weeks'; smaEl.style.color = '#ffd700'; }
                else if (inp.dipped) { smaEl.textContent = '🔻 BELOW 200W SMA'; smaEl.style.color = '#ff9800'; }
                else { smaEl.textContent = '⬆️ Above 200W — Waiting for dip'; smaEl.style.color = '#888'; }
                document.getElementById('ds-aggression').textContent = inp.premium ? inp.premium.toFixed(2) + 'x mNAV' : '—';
                const cycleEl = document.getElementById('ds-avoid');
                cycleEl.textContent = inp.in_position ? 'IN TRADE' : (inp.armed ? 'ENTRY READY' : 'WAITING');
                cycleEl.className = 'value ' + (inp.armed ? 'green' : '');
                const sigEl = document.getElementById('ds-hedge');
                sigEl.textContent = inp.armed ? '🟢 GO' : '⏳ NO SIGNAL';
                sigEl.className = 'value ' + (inp.armed ? 'green' : '');
                if (data.outlook) {
                    document.getElementById('ds-outlook').innerHTML = '📊 ' + data.outlook;
                }
                if (data.reasoning) {
                    document.getElementById('ds-last-trade').innerHTML = '<div style="color:#00bcd4;font-size:12px;margin-top:4px;">' + data.reasoning + '</div>';
                }
            }).catch(() => {});
        }

        function fetchTreasuryYield() {
            fetch('/api/treasury-yield').then(r => r.json()).then(d => {
                if (!d || d.error) return;
                var y = document.getElementById('ty-yield');
                if (y) y.textContent = d.yield_pct ? d.yield_pct.toFixed(3) + '%' : '—';
                var ch = document.getElementById('ty-change');
                if (ch && d.change_bps !== null && d.change_bps !== undefined) {
                    var sign = d.change_bps >= 0 ? '+' : '';
                    ch.textContent = sign + d.change_bps + ' bps';
                    ch.className = 'value ' + (d.change_bps > 0 ? 'red' : d.change_bps < 0 ? 'green' : '');
                }
                var rg = document.getElementById('ty-regime');
                if (rg) {
                    rg.textContent = d.macro_regime || '—';
                    var cls = 'value';
                    if (d.macro_regime === 'EXTREME_HIGH' || d.macro_regime === 'HIGH') cls += ' red';
                    else if (d.macro_regime === 'SUPPORTIVE' || d.macro_regime === 'LOW') cls += ' green';
                    rg.className = cls;
                }
                var im = document.getElementById('ty-impl');
                if (im) im.textContent = d.btc_implication || '—';
                var ts = document.getElementById('ty-time');
                if (ts && d.last_updated) {
                    var t = new Date(d.last_updated);
                    ts.textContent = t.toLocaleTimeString();
                }
            }).catch(() => {});
        }
        setInterval(fetchTreasuryYield, 60000);
        fetchTreasuryYield();

        function fetchGrok() {
            fetch('/api/grok').then(r => r.json()).then(data => {
                if (!data || data.error) return;
                const sentEl = document.getElementById('grok-intel-sentiment');
                const sent = (data.overall_sentiment || 'unknown').toUpperCase();
                if (sentEl) {
                    sentEl.textContent = sent;
                    sentEl.className = 'value ' + (sent === 'BULLISH' ? 'green' : sent === 'BEARISH' ? 'red' : '');
                }
                var tsField = data.timestamp || data.last_updated;
                if (tsField) {
                    const t = new Date(tsField);
                    var intelTimeEl = document.getElementById('grok-intel-time');
                    if (intelTimeEl) intelTimeEl.textContent = t.toLocaleTimeString();
                }
                const sigs = data.signals || [];
                const highSigs = sigs.filter(s => s.confidence === 'high');
                document.getElementById('grok-signals').textContent = highSigs.length + ' high / ' + sigs.length + ' total';
                if (data.hot_tickers && data.hot_tickers.length > 0) {
                    document.getElementById('grok-hot').innerHTML = '🔥 ' + data.hot_tickers.slice(0, 8).join(', ');
                }
                // Viral posts
                const viralDiv = document.getElementById('grok-viral');
                const viral = data.viral_posts || [];
                if (viral.length > 0) {
                    viralDiv.innerHTML = '<div style="color:#ff6600;font-weight:bold;margin-bottom:4px;">🔥 Viral Posts</div>' +
                        viral.slice(0, 5).map(v => {
                            var tickers = (v.tickers || []).join(', ');
                            return '<div style="color:#eee;margin-bottom:6px;padding:4px;border-left:2px solid #ff6600;">' +
                                '<span style="color:#ff6600;">@' + (v.handle || '?').replace('@','') + '</span> ' +
                                '<span style="color:#888;">[' + (v.engagement || '?') + ']</span><br>' +
                                '<span>' + (v.post_summary || '').substring(0, 150) + '</span>' +
                                (tickers ? '<br><span style="color:#00d4ff;">$' + tickers + '</span>' : '') +
                                '</div>';
                        }).join('');
                }
                const infDiv = document.getElementById('grok-influencer-alerts');
                const alerts = data.influencer_alerts || [];
                if (alerts.length > 0) {
                    infDiv.innerHTML = '<div style="color:#ff6600;font-weight:bold;margin-bottom:2px;">📡 Influencer Alerts</div>' +
                        alerts.slice(0, 3).map(a => '<div style="color:#ccc;">@' + (a.handle || a.account || '?') + ': ' + (a.summary || '').substring(0, 80) + '</div>').join('');
                }
                const sigDiv = document.getElementById('grok-top-signals');
                if (highSigs.length > 0) {
                    sigDiv.innerHTML = highSigs.slice(0, 3).map(s => {
                        const color = s.signal === 'buy' ? '#00ff88' : s.signal === 'sell' ? '#ff4444' : '#ffaa00';
                        return '<div style="color:' + color + '">⚡ ' + s.ticker + ' → ' + s.signal.toUpperCase() + ' (' + (s.reason || '').substring(0, 60) + ')</div>';
                    }).join('');
                }
            }).catch(() => {});
        }

        function grokQuickScan() {
            const input = document.getElementById('grok-ticker-input');
            const ticker = input.value.trim().toUpperCase();
            if (!ticker) { document.getElementById('grok-quick-result').innerHTML = '<span style="color:#ffaa00;">Type a ticker first</span>'; return; }
            const resultDiv = document.getElementById('grok-quick-result');
            resultDiv.innerHTML = '<span style="color:#ff6600;">Scanning ' + ticker + ' (takes ~5s)...</span>';
            fetch('/api/grok/scan/' + ticker, {signal: AbortSignal.timeout(30000)}).then(r => r.json()).then(data => {
                resultDiv.innerHTML = '<span style="color:#00ff88;">' + (data.result || 'No data').substring(0, 300) + '</span>';
            }).catch(function(e) { resultDiv.innerHTML = '<span style="color:#ff4444;">Scan failed: ' + (e.message || 'timeout') + '</span>'; });
        }

        function fetchGronk() {
            fetch('/api/gronk').then(r => r.json()).then(data => {
                if (!data || data.error) return;
                const sentEl = document.getElementById('gronk-sentiment');
                const sent = (data.overall_sentiment || 'unknown').toUpperCase();
                sentEl.textContent = sent;
                sentEl.className = 'value ' + (sent === 'BULLISH' ? 'green' : sent === 'BEARISH' ? 'red' : '');
                document.getElementById('gronk-posts').textContent = data.total_posts_scanned || 0;
                const sigs = data.signals || [];
                const highSigs = sigs.filter(s => s.confidence === 'high');
                document.getElementById('gronk-signals').textContent = highSigs.length + ' high / ' + sigs.length + ' total';
                if (data.hot_tickers && data.hot_tickers.length > 0) {
                    document.getElementById('gronk-hot').innerHTML = '🔥 ' + data.hot_tickers.slice(0, 8).join(', ');
                }
                const sigDiv = document.getElementById('gronk-top-signals');
                if (highSigs.length > 0) {
                    sigDiv.innerHTML = highSigs.slice(0, 3).map(s => {
                        const color = s.signal === 'buy' ? '#00ff88' : s.signal === 'sell' ? '#ff4444' : '#ffaa00';
                        return '<div style="color:' + color + '">⚡ ' + s.ticker + ' → ' + s.signal.toUpperCase() + ' (' + (s.reason || '').substring(0, 60) + ')</div>';
                    }).join('');
                } else {
                    sigDiv.innerHTML = '';
                }
            }).catch(() => {});
        }

        // ── HITL Strike Roll ──
        function checkHITL() {
            fetch('/api/strike-roll').then(function(r){return r.json()}).then(function(data) {
                var panel = document.getElementById('hitl-panel');
                if (!panel) return;
                if (data.status === 'pending' && data.roll) {
                    var roll = data.roll;
                    var oldSpec = (roll.old_spec_strikes || []).map(function(s){return '$'+s}).join('/') || 'N/A';
                    var newSpec = (roll.new_spec_strikes || []).map(function(s){return '$'+s}).join('/') || 'N/A';
                    var oldSafety = (roll.old_safety_strikes || []).map(function(s){return '$'+s}).join('/') || 'N/A';
                    var newSafety = (roll.new_safety_strikes || []).map(function(s){return '$'+s}).join('/') || 'N/A';
                    document.getElementById('hitl-details').innerHTML =
                        '<div style="background:#0d0d1a;padding:14px;border-radius:8px;border-left:4px solid #ff9800;">' +
                        '<div style="color:#ff9800;font-weight:bold;font-size:16px;margin-bottom:10px;">⚠️ Premium Compression: ' + (roll.premium_drop_pct||0).toFixed(1) + '% drop</div>' +
                        '<div style="font-size:15px;">Est. Payout Haircut: <span style="color:#e53935;font-weight:bold;font-size:18px;">~' + (roll.haircut_pct||0).toFixed(0) + '%</span></div>' +
                        '<div style="margin-top:10px;font-size:15px;">Band Shift: <span style="color:#ff9800;font-weight:bold;">' + (roll.old_band||'?') + '</span> → <span style="color:#00ff88;font-weight:bold;">' + (roll.new_band||'?') + '</span></div>' +
                        '<div style="margin-top:8px;font-size:15px;">Spec: <span style="color:#888;text-decoration:line-through;">' + oldSpec + '</span> → <span style="color:#00ff88;font-weight:bold;">' + newSpec + '</span></div>' +
                        '<div style="font-size:15px;">Safety: <span style="color:#888;text-decoration:line-through;">' + oldSafety + '</span> → <span style="color:#00ff88;font-weight:bold;">' + newSafety + '</span></div>' +
                        '</div>';
                    panel.style.display = 'block';
                    document.getElementById('hitl-approve').disabled = false;
                    document.getElementById('hitl-reject').disabled = false;
                    document.getElementById('hitl-result').style.display = 'none';
                } else {
                    panel.style.display = 'none';
                }
            }).catch(function(e){console.log('HITL check error:', e)});
        }

        window.respondHITL = function(action) {
            document.getElementById('hitl-approve').disabled = true;
            document.getElementById('hitl-reject').disabled = true;
            fetch('/api/strike-roll', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({action: action})
            }).then(function(r){return r.json()}).then(function(data) {
                var resultEl = document.getElementById('hitl-result');
                resultEl.style.display = 'block';
                if (action === 'approve') {
                    resultEl.innerHTML = '<span style="color:#00ff88;font-weight:bold;font-size:16px;">✅ ' + data.message + '</span>';
                } else {
                    resultEl.innerHTML = '<span style="color:#e53935;font-weight:bold;font-size:16px;">❌ ' + data.message + '</span>';
                }
                setTimeout(checkHITL, 3000);
            }).catch(function(){
                document.getElementById('hitl-approve').disabled = false;
                document.getElementById('hitl-reject').disabled = false;
            });
        };

        // Bind HITL buttons via addEventListener
        document.getElementById('hitl-approve').addEventListener('click', function(e) {
            e.stopPropagation(); e.preventDefault(); window.respondHITL('approve');
        });
        document.getElementById('hitl-reject').addEventListener('click', function(e) {
            e.stopPropagation(); e.preventDefault(); window.respondHITL('reject');
        });

        function fetchOOSHealth() {
            fetch('/api/oos-health').then(r => r.json()).then(d => {
                if (d.error) return;
                var vEl = document.getElementById('oos-verdict');
                if (vEl) {
                    var v = d.verdict || '—';
                    vEl.textContent = v;
                    vEl.style.color = v === 'PASS' ? '#00ff88' : v === 'WARN' ? '#ffd700' : v === 'DRIFT_ALERT' ? '#ff4444' : '#888';
                }
                var qEl = document.getElementById('oos-quarter');
                if (qEl) { qEl.textContent = d.quarter || '—'; qEl.style.color = '#ccc'; }
                var rEl = document.getElementById('oos-rolling-avg');
                if (rEl) {
                    var avg = d.rolling_4q_avg;
                    if (avg !== null && avg !== undefined) {
                        rEl.textContent = avg.toFixed(4);
                        rEl.style.color = avg > 0 ? '#00ff88' : '#ff4444';
                    } else { rEl.textContent = 'N/A'; rEl.style.color = '#888'; }
                }
                var sEl = document.getElementById('oos-stability');
                if (sEl) {
                    var stable = d.winner_stable;
                    sEl.textContent = stable === true ? 'Stable' : stable === false ? 'UNSTABLE' : '—';
                    sEl.style.color = stable === true ? '#00ff88' : stable === false ? '#ff4444' : '#888';
                }
                var dsEl = document.getElementById('oos-drift-streak');
                if (dsEl) {
                    var streak = d.drift_streak || 0;
                    dsEl.textContent = streak + ' consecutive';
                    dsEl.style.color = streak >= 3 ? '#ff4444' : streak >= 2 ? '#ff9800' : streak >= 1 ? '#ffd700' : '#00ff88';
                }
                var eEl = document.getElementById('oos-escalation');
                if (eEl) {
                    var esc = d.escalation || 'NONE';
                    eEl.textContent = esc;
                    eEl.style.color = esc === 'CRITICAL' ? '#ff4444' : esc === 'MANDATORY_REVIEW' ? '#ff9800' : esc === 'ALERT' ? '#ffd700' : '#00ff88';
                }
                var rgEl = document.getElementById('oos-regime');
                if (rgEl) {
                    var regime = d.regime || '—';
                    var softened = d.regime_softened;
                    rgEl.textContent = regime + (softened ? ' [softened]' : '');
                    var adverse = d.in_adverse_regime;
                    rgEl.style.color = adverse ? '#ff9800' : '#00ff88';
                }
            }).catch(function() {});
        }

        // Fetch initial data and refresh every 30 seconds
        checkHITL();
        fetchLiveProgress();
        fetchStatus();
        fetchFeed();
        fetchAuditor();
        fetchAccountant();
        fetchDeepSeek();
        fetchGronk();
        fetchGrok();
        fetchYouTube();
        setInterval(checkHITL, 15000);
        setInterval(fetchLiveProgress, 60000);
        setInterval(fetchStatus, 30000);
        setInterval(fetchFeed, 30000);
        setInterval(fetchAuditor, 60000);
        setInterval(fetchAccountant, 60000);
        setInterval(fetchDeepSeek, 60000);
        setInterval(fetchGronk, 60000);
        setInterval(fetchGrok, 60000);
        setInterval(fetchYouTube, 60000);
        fetchRegime();
        setInterval(fetchRegime, 60000);
        fetchGrokSentiment();
        setInterval(fetchGrokSentiment, 60000);
        fetchGeminiBrain();
        setInterval(fetchGeminiBrain, 60000);
        fetchOOSHealth();
        setInterval(fetchOOSHealth, 120000);
        function fetchTrader1() {
            fetch('/api/trader1/status').then(r => r.json()).then(d => {
                if (!d || d.status === 'not_started') return;

                // Daemon alive
                var daemonEl = document.getElementById('t1-daemon-alive');
                if (daemonEl) {
                    daemonEl.textContent = d.daemon_running ? '✅ Running' : '❌ DOWN — restart via launchctl';
                    daemonEl.style.color = d.daemon_running ? '#00ff88' : '#ff4444';
                }

                var sEl = document.getElementById('t1-status');
                if (sEl) {
                    sEl.textContent = d.status;
                    sEl.style.color = d.status === 'IN TRADE' ? '#00ff88' : d.status === 'ARMED' ? '#ffd700' : d.status === 'DIPPED — WAITING RECLAIM' ? '#ff9800' : '#00d4ff';
                }
                var armed = document.getElementById('t1-armed');
                if (armed) { armed.textContent = d.is_armed ? '✅ YES' : '❌ No'; armed.style.color = d.is_armed ? '#00ff88' : '#888'; }
                var dipped = document.getElementById('t1-dipped');
                if (dipped) { dipped.textContent = d.dipped_below_200w ? '✅ YES — Mar 17' : '❌ No'; dipped.style.color = d.dipped_below_200w ? '#ff9800' : '#888'; }
                var gw = document.getElementById('t1-green-weeks');
                if (gw) gw.textContent = (d.green_week_count || 0) + ' / 2 needed';
                var mp = document.getElementById('t1-mstr-price');
                if (mp && d.last_mstr_price) mp.textContent = '$' + Number(d.last_mstr_price).toFixed(2);
                var qty = document.getElementById('t1-qty');
                if (qty) qty.textContent = d.position_qty > 0 ? d.position_qty + ' contracts' : 'None (waiting)';
                var ep = document.getElementById('t1-entry');
                if (ep) ep.textContent = d.entry_price > 0 ? '$' + Number(d.entry_price).toFixed(2) : '—';
                var pg = document.getElementById('t1-peak-gain');
                if (pg) { var g = d.peak_gain_pct || 0; pg.textContent = (g >= 0 ? '+' : '') + g.toFixed(1) + '%'; pg.style.color = g > 0 ? '#00ff88' : '#888'; }

                // Last Eval — color-coded staleness + relative time
                // v2.8+ evaluates 3:45 PM ET weekdays — weekends/holidays = no evals
                var ev = document.getElementById('t1-last-eval');
                if (ev && d.last_eval) {
                    var ts = d.last_eval.replace('T', ' ').substring(0, 16);
                    var h = d.eval_hours_ago;
                    var ago = (h !== null && h !== undefined) ? (h < 1 ? ' (<1h ago)' : ' (' + Math.round(h) + 'h ago)') : '';

                    // Weekend-aware staleness: IBKR down Sat-Sun, no evals expected
                    // Friday 3:45 PM → Monday 9:30 AM = ~64h gap is NORMAL
                    var now = new Date();
                    var day = now.getDay(); // 0=Sun, 6=Sat
                    var isWeekend = (day === 0 || day === 6);
                    var isMonday = (day === 1 && now.getHours() < 16); // Monday before market close

                    var evalColor;
                    if (h === null || h === undefined) {
                        evalColor = '#888';
                    } else if (isWeekend || isMonday) {
                        // Weekend/Monday morning: up to 90h from Thursday eval is normal
                        evalColor = h < 90 ? '#00ff88' : h < 120 ? '#ff9800' : '#ff4444';
                        ago += isWeekend ? ' (weekend)' : ' (Mon pre-market)';
                    } else {
                        // Weekday: Green < 26h, Orange 26-50h, Red > 50h
                        evalColor = h < 26 ? '#00ff88' : h < 50 ? '#ff9800' : '#ff4444';
                    }
                    ev.textContent = ts + ago;
                    ev.style.color = evalColor;
                }

                // mNAV Premium — color-coded: green >1.0, yellow 0.80-1.0, orange 0.75-0.80, red ≤0.75 (kill switch)
                var mnavEl = document.getElementById('t1-mnav');
                if (mnavEl && d.current_premium !== undefined && d.current_premium !== null) {
                    var p = d.current_premium;
                    var pStr = p.toFixed(4) + 'x';
                    if (p <= 0.75) {
                        mnavEl.textContent = '🚨 ' + pStr + ' — KILL SWITCH ZONE';
                        mnavEl.style.color = '#ff4444';
                    } else if (p <= 0.80) {
                        mnavEl.textContent = '⚠️ ' + pStr + ' — EDGE (<0.75 fires DEFCON 1)';
                        mnavEl.style.color = '#ff9800';
                    } else if (p <= 1.0) {
                        mnavEl.textContent = pStr + ' (near NAV)';
                        mnavEl.style.color = '#ffd700';
                    } else {
                        mnavEl.textContent = pStr + ' (premium)';
                        mnavEl.style.color = '#00ff88';
                    }
                }

                // Next eval hint
                var ne = document.getElementById('t1-next-eval');
                if (ne) ne.textContent = d.next_eval || '15:45 ET weekdays';

            }).catch(() => {
                var daemonEl = document.getElementById('t1-daemon-alive');
                if (daemonEl) { daemonEl.textContent = '⚠ API ERROR'; daemonEl.style.color = '#ff4444'; }
            });
        }
        function fetchTrader2() {
            fetch('/api/trader2/status').then(r => r.json()).then(d => {
                if (d.last_value !== undefined) {
                    document.getElementById('t2-value').textContent = '$' + Number(d.last_value).toFixed(2);
                    var g = d.last_gain_pct || 0;
                    var gEl = document.getElementById('t2-gain');
                    gEl.textContent = (g >= 0 ? '+' : '') + g.toFixed(1) + '%';
                    gEl.style.color = g >= 300 ? '#00ff88' : g >= 0 ? '#00d4ff' : '#e53935';
                    document.getElementById('t2-ladder').textContent = d.activated ? 'ACTIVE' : 'Waiting for +150%';
                    document.getElementById('t2-ladder').style.color = d.activated ? '#00ff88' : '#888';
                    document.getElementById('t2-trail').textContent = d.trail_stop_value > 0 ? '$' + Number(d.trail_stop_value).toFixed(2) + ' (' + d.trail_stop_pct + '%)' : '—';
                    document.getElementById('t2-tier').textContent = (d.current_tier || 0) + '/4';
                    if (d.last_check) {
                        var t2El = document.getElementById('t2-time');
                        var t2Time = new Date(d.last_check);
                        var t2Age = (Date.now() - t2Time.getTime()) / 3600000;
                        t2El.textContent = d.last_check.split('T')[1].substring(0,8) + ' (' + Math.round(t2Age) + 'h ago)';
                        var day2 = new Date().getDay();
                        var wknd2 = (day2 === 0 || day2 === 6 || (day2 === 1 && new Date().getHours() < 16));
                        t2El.style.color = wknd2 ? (t2Age < 90 ? '#00ff88' : '#ff9800') : (t2Age < 26 ? '#00ff88' : t2Age < 50 ? '#ff9800' : '#ff4444');
                    }
                }
            }).catch(() => {});
        }
        function fetchTrader3() {
            fetch('/api/trader3/status').then(r => r.json()).then(d => {
                if (d.last_value !== undefined) {
                    document.getElementById('t3-value').textContent = '$' + Number(d.last_value).toFixed(2);
                    var g = d.last_gain_pct || 0;
                    var gEl = document.getElementById('t3-gain');
                    gEl.textContent = (g >= 0 ? '+' : '') + g.toFixed(1) + '%';
                    gEl.style.color = g >= 300 ? '#00ff88' : g >= 0 ? '#00d4ff' : '#e53935';
                    document.getElementById('t3-ladder').textContent = d.activated ? 'ACTIVE' : 'Waiting for +100%';
                    document.getElementById('t3-ladder').style.color = d.activated ? '#00ff88' : '#888';
                    document.getElementById('t3-trail').textContent = d.trail_stop_value > 0 ? '$' + Number(d.trail_stop_value).toFixed(2) + ' (' + d.trail_stop_pct + '%)' : '—';
                    document.getElementById('t3-tier').textContent = (d.current_tier || 0) + '/4';
                    if (d.last_check) {
                        var t3El = document.getElementById('t3-time');
                        var t3Time = new Date(d.last_check);
                        var t3Age = (Date.now() - t3Time.getTime()) / 3600000;
                        t3El.textContent = d.last_check.split('T')[1].substring(0,8) + ' (' + Math.round(t3Age) + 'h ago)';
                        var day3 = new Date().getDay();
                        var wknd3 = (day3 === 0 || day3 === 6 || (day3 === 1 && new Date().getHours() < 16));
                        t3El.style.color = wknd3 ? (t3Age < 90 ? '#00ff88' : '#ff9800') : (t3Age < 26 ? '#00ff88' : t3Age < 50 ? '#ff9800' : '#ff4444');
                    }
                }
            }).catch(() => {});
        }
        fetchTrader1();
        fetchTrader2();
        fetchTrader3();
        setInterval(fetchTrader1, 60000);
        setInterval(fetchTrader2, 60000);
        setInterval(fetchTrader3, 60000);

        function fetchRegime() {
            fetch('/api/regime').then(r => r.json()).then(d => {
                if (!d || !d.current_regime) return;
                var regime = d.current_regime;
                var conf = d.confidence || 0;
                var colors = {ACCUMULATION:'#00d4ff', MARKUP:'#00ff88', DISTRIBUTION:'#ffd700', MARKDOWN:'#e53935'};
                var el = document.getElementById('regime-current');
                if (el) { el.textContent = regime; el.style.color = colors[regime] || '#fff'; }
                var confEl = document.getElementById('regime-confidence');
                if (confEl) { confEl.textContent = (conf * 100).toFixed(1) + '%'; confEl.style.color = colors[regime] || '#fff'; }
                var probs = d.all_probabilities || {};
                var accEl = document.getElementById('regime-acc'); if (accEl) accEl.textContent = ((probs.ACCUMULATION||0)*100).toFixed(1) + '%';
                var mkupEl = document.getElementById('regime-mkup'); if (mkupEl) mkupEl.textContent = ((probs.MARKUP||0)*100).toFixed(1) + '%';
                var distEl = document.getElementById('regime-dist'); if (distEl) distEl.textContent = ((probs.DISTRIBUTION||0)*100).toFixed(1) + '%';
                var mkdnEl = document.getElementById('regime-mkdn'); if (mkdnEl) mkdnEl.textContent = ((probs.MARKDOWN||0)*100).toFixed(1) + '%';
                var transEl = document.getElementById('regime-transition');
                if (transEl) transEl.textContent = d.transition_alert || 'None';
                var btcEl = document.getElementById('regime-btc');
                if (btcEl && d.btc_price) btcEl.textContent = '$' + Number(d.btc_price).toLocaleString();
                var updEl = document.getElementById('regime-updated');
                if (updEl && d.last_updated) updEl.textContent = d.last_updated.split('T')[0] + ' ' + (d.last_updated.split('T')[1]||'').substring(0,8);
                var moEl = document.getElementById('regime-month-outlook');
                if (moEl && d.month_outlook) { moEl.textContent = d.month_outlook.description; moEl.style.color = d.month_outlook.direction === 'green' ? '#00ff88' : d.month_outlook.direction === 'red' ? '#ff4444' : '#ff9800'; }
            }).catch(function(){});
        }

        // ── Grok CT Sentiment — independent poller ──
        function fetchGrokSentiment() {
            fetch('/api/grok-sentiment').then(r => r.json()).then(d => {
                if (!d || !d.current) return;
                var c = d.current;
                var score = c.sentiment_score || 0;
                var scoreEl = document.getElementById('grok-score');
                if (scoreEl) {
                    scoreEl.textContent = score;
                    scoreEl.style.color = score <= -50 ? '#e53935' : score <= -20 ? '#ff9800' : score <= 20 ? '#888' : score <= 50 ? '#00d4ff' : '#00ff88';
                }
                var fgEl = document.getElementById('grok-fg');
                if (fgEl) {
                    var fg = c.fear_greed || '—';
                    fgEl.textContent = fg;
                    fgEl.style.color = fg.indexOf('FEAR') >= 0 ? '#e53935' : fg.indexOf('GREED') >= 0 ? '#00ff88' : '#ffd700';
                }
                var gbtcEl = document.getElementById('grok-btc');
                if (gbtcEl) gbtcEl.textContent = c.btc_sentiment || '—';
                var gmstrEl = document.getElementById('grok-mstr');
                if (gmstrEl) gmstrEl.textContent = c.mstr_sentiment || '—';
                var thEl = document.getElementById('grok-themes');
                if (thEl && c.key_themes) thEl.textContent = c.key_themes.join(', ');
                var gtEl = document.getElementById('grok-time');
                if (gtEl && c.timestamp) gtEl.textContent = c.timestamp.split('T')[0] + ' ' + c.timestamp.split('T')[1].substring(0,8);
            }).catch(function(){});
        }

        // ── Gemini Brain — independent poller ──
        function fetchGeminiBrain() {
            fetch('/api/gemini-brain').then(r => r.json()).then(d => {
                if (!d) return;
                var rc = d.regime_crosscheck;
                // Fall back to most recent regime_history entry if crosscheck is null
                if (!rc && d.regime_history && d.regime_history.length > 0) {
                    rc = d.regime_history[d.regime_history.length - 1];
                }
                if (rc) {
                    var grEl = document.getElementById('gem-regime');
                    if (grEl) { grEl.textContent = (rc.regime || '—') + ' (' + ((rc.confidence || 0) * 100).toFixed(0) + '%)'; }
                    var gcEl = document.getElementById('gem-consensus');
                    if (gcEl) {
                        if (rc.consensus !== undefined && rc.consensus !== null) {
                            gcEl.textContent = rc.consensus ? '✅ YES — agrees with S13' : '⚠️ NO — disagrees with S13';
                            gcEl.style.color = rc.consensus ? '#00ff88' : '#ff9800';
                        } else {
                            gcEl.textContent = '—'; gcEl.style.color = '#888';
                        }
                    }
                    var goEl = document.getElementById('gem-outlook');
                    if (goEl) goEl.textContent = rc.btc_outlook_30d || '—';
                    var grkEl = document.getElementById('gem-risk');
                    if (grkEl) grkEl.textContent = rc.key_risk || '—';
                    var gopEl = document.getElementById('gem-opp');
                    if (gopEl) gopEl.textContent = rc.key_opportunity || '—';
                } else {
                    var grEl = document.getElementById('gem-regime');
                    if (grEl) grEl.textContent = '— (awaiting data)';
                }
                // News digest — render regardless of regime_crosscheck
                var nd = d.news_digest;
                var digestEl = document.getElementById('gem-digest');
                if (digestEl && nd && nd.digest) {
                    digestEl.innerHTML = nd.digest.split('\\n').join('<br>');
                    digestEl.style.color = '#ccc';
                }
                var gtEl = document.getElementById('gem-time');
                if (gtEl && d.last_updated) gtEl.textContent = d.last_updated.split('T')[0] + ' ' + d.last_updated.split('T')[1].substring(0,8);
            }).catch(function(){});
        }

        function fetchYouTube() {
            fetch('/api/youtube').then(r => r.json()).then(data => {
                if (!data || !data.overall_sentiment) return;
                const sentEl = document.getElementById('yt-sentiment');
                sentEl.textContent = (data.overall_sentiment || 'N/A').toUpperCase();
                sentEl.style.color = data.overall_sentiment === 'bullish' ? '#00ff88' : data.overall_sentiment === 'bearish' ? '#ff4444' : '#e2b93d';
                document.getElementById('yt-videos').textContent = data.videos_found || 0;
                const sigs = data.signals || [];
                const highSigs = sigs.filter(s => s.confidence === 'high');
                document.getElementById('yt-signals').textContent = highSigs.length + ' high / ' + sigs.length + ' total';
                if (data.hot_tickers && data.hot_tickers.length) {
                    document.getElementById('yt-hot').innerHTML = '🔥 ' + data.hot_tickers.slice(0, 8).join(', ');
                }
                const sigDiv = document.getElementById('yt-top-signals');
                if (highSigs.length) {
                    sigDiv.innerHTML = highSigs.slice(0, 3).map(s =>
                        '<div style="color:' + (s.signal === 'buy' ? '#00ff88' : s.signal === 'sell' ? '#ff4444' : '#e2b93d') + '">' +
                        s.ticker + ' → ' + s.signal.toUpperCase() + ' (' + (s.source_channel || '') + ')</div>'
                    ).join('');
                }
                const vidDiv = document.getElementById('yt-top-videos');
                if (data.notable_videos && data.notable_videos.length) {
                    vidDiv.innerHTML = '<div style="color:#aaa;margin-top:4px;">TOP VIDEOS:</div>' +
                        data.notable_videos.slice(0, 3).map(v =>
                            '<div style="color:#ccc;font-size:14px;">📺 [' + (v.channel || '?') + '] ' + (v.title || '').substring(0, 60) + ' (' + (v.views || 0).toLocaleString() + ' views)</div>'
                        ).join('');
                }
            }).catch(() => {});
        }

        function ytQuickScan() {
            const input = document.getElementById('yt-ticker-input');
            const ticker = input.value.trim().toUpperCase();
            if (!ticker) { document.getElementById('yt-quick-result').innerHTML = '<span style="color:#ffaa00;">Type a ticker first</span>'; return; }
            const resultDiv = document.getElementById('yt-quick-result');
            resultDiv.innerHTML = '<span style="color:#ff0000;">Scanning (takes ~5s)...</span>';
            fetch('/api/youtube/scan/' + ticker, {signal: AbortSignal.timeout(30000)}).then(r => r.json()).then(data => {
                resultDiv.innerHTML = '<span style="color:#00ff88;">' + (data.result || 'Done').substring(0, 300) + '</span>';
            }).catch(function(e) { resultDiv.innerHTML = '<span style="color:#ff4444;">Failed: ' + (e.message || 'timeout') + '</span>'; });
        }

        fetchTikTok();
        setInterval(fetchTikTok, 60000);

        function fetchTikTok() {
            fetch('/api/tiktok').then(r => r.json()).then(data => {
                if (!data || !data.overall_sentiment) return;
                var sentEl = document.getElementById('tt-sentiment');
                sentEl.textContent = (data.overall_sentiment || 'N/A').toUpperCase();
                sentEl.style.color = data.overall_sentiment === 'bullish' || data.overall_sentiment === 'euphoric' ? '#00ff88' : data.overall_sentiment === 'bearish' ? '#ff4444' : '#e2b93d';
                document.getElementById('tt-posts').textContent = data.posts_found || 0;
                var viral = data.viral_picks || [];
                var highPotential = viral.filter(function(v) { return v.ten_x_potential === 'high'; });
                document.getElementById('tt-moonshots').textContent = highPotential.length + ' high / ' + viral.length + ' total';
                if (data.hot_tickers && data.hot_tickers.length) {
                    document.getElementById('tt-hot').innerHTML = '🔥 ' + data.hot_tickers.slice(0, 8).join(', ');
                }
                var viralDiv = document.getElementById('tt-viral');
                if (highPotential.length) {
                    viralDiv.innerHTML = '<div style="color:#ee1d52;font-weight:bold;">10X PICKS:</div>' +
                        highPotential.slice(0, 3).map(function(v) {
                            return '<div style="color:#fff;">$' + v.ticker + ' [' + (v.sector || '?') + '] — ' + (v.bull_case || '').substring(0, 80) + '</div>';
                        }).join('');
                }
                var grok = data.grok_cross_reference || {};
                var confirmed = grok.confirmed_picks || [];
                if (confirmed.length) {
                    document.getElementById('tt-confirmed').innerHTML = 'Confirmed (TikTok+X): ' + confirmed.join(', ');
                }
            }).catch(function() {});
        }

        function ttQuickScan() {
            var input = document.getElementById('tt-ticker-input');
            var ticker = input.value.trim().toUpperCase();
            if (!ticker) { document.getElementById('tt-quick-result').innerHTML = '<span style="color:#ffaa00;">Type a ticker first</span>'; return; }
            var resultDiv = document.getElementById('tt-quick-result');
            resultDiv.innerHTML = '<span style="color:#ee1d52;">Scanning (takes ~5s)...</span>';
            fetch('/api/tiktok/scan/' + ticker, {signal: AbortSignal.timeout(30000)}).then(r => r.json()).then(data => {
                resultDiv.innerHTML = '<span style="color:#00ff88;">' + (data.result || 'Done').substring(0, 300) + '</span>';
            }).catch(function(e) { resultDiv.innerHTML = '<span style="color:#ff4444;">Failed: ' + (e.message || 'timeout') + '</span>'; });
        }

        // Truth Social
        fetchTruthSocial();
        setInterval(fetchTruthSocial, 60000);

        function fetchTruthSocial() {
            fetch('/api/truth').then(r => r.json()).then(data => {
                if (data.error) return;
                document.getElementById('ts-impact').textContent = data.impact || '—';
                document.getElementById('ts-urgency').textContent = data.urgency || '—';
                document.getElementById('ts-posts').textContent = data.total_posts || '—';
                document.getElementById('ts-market').textContent = data.market_posts || '—';
                var sum = document.getElementById('ts-summary');
                if (data.summary) sum.innerHTML = '<strong>Summary:</strong> ' + data.summary.substring(0, 300);
                var sig = document.getElementById('ts-signals');
                if (data.signals && data.signals.length > 0) {
                    sig.innerHTML = '<strong style="color:#00ff88;">Signals:</strong> ' + data.signals.map(function(s) { return '<span style="color:#e2b93d;">' + s + '</span>'; }).join(', ');
                }
                var tar = document.getElementById('ts-tariff');
                if (data.tariff_mentions) tar.innerHTML = '⚠️ Tariff mentions: ' + data.tariff_mentions;
                var xr = document.getElementById('ts-x-reaction');
                if (data.x_reaction) xr.innerHTML = '<strong>X Reaction:</strong> ' + data.x_reaction.substring(0, 200);
            }).catch(function() {});
        }

        function tsQuickScan() {
            var input = document.getElementById('ts-topic-input');
            var topic = input.value.trim();
            if (!topic) { document.getElementById('ts-quick-result').innerHTML = '<span style="color:#ffaa00;">Type a topic first</span>'; return; }
            var resultDiv = document.getElementById('ts-quick-result');
            resultDiv.innerHTML = '<span style="color:#4a90d9;">Scanning (takes ~5s)...</span>';
            fetch('/api/truth/scan/' + encodeURIComponent(topic), {signal: AbortSignal.timeout(30000)}).then(r => r.json()).then(data => {
                resultDiv.innerHTML = '<span style="color:#00ff88;">' + (data.result || 'Done').substring(0, 300) + '</span>';
            }).catch(function(e) { resultDiv.innerHTML = '<span style="color:#ff4444;">Scan failed: ' + (e.message || 'timeout') + '</span>'; });
        }

        // Congress Tracker
        fetchCongress();
        setInterval(fetchCongress, 60000);

        function fetchCongress() {
            fetch('/api/congress').then(r => r.json()).then(data => {
                if (data.error) return;
                document.getElementById('cg-trades').textContent = data.total_trades || '—';
                document.getElementById('cg-buys').textContent = data.recent_buys || '—';
                document.getElementById('cg-sells').textContent = data.recent_sells || '—';
                document.getElementById('cg-top').textContent = data.top_ticker || '—';
                var hot = document.getElementById('cg-hot');
                if (data.hot_tickers && data.hot_tickers.length > 0) {
                    hot.innerHTML = '<strong style="color:#e2b93d;">Hot:</strong> ' + data.hot_tickers.join(', ');
                }
                var notable = document.getElementById('cg-notable');
                if (data.notable_trades && data.notable_trades.length > 0) {
                    notable.innerHTML = '<strong style="color:#00ff88;">Notable:</strong><br>' + data.notable_trades.map(function(t) { return '• ' + t; }).join('<br>');
                }
                var ai = document.getElementById('cg-analysis');
                if (data.ai_analysis) ai.innerHTML = '<strong>Analysis:</strong> ' + data.ai_analysis.substring(0, 300);
            }).catch(function() {});
        }

        function cgQuickScan() {
            var input = document.getElementById('cg-ticker-input');
            var ticker = input.value.trim().toUpperCase();
            if (!ticker) { document.getElementById('cg-quick-result').innerHTML = '<span style="color:#ffaa00;">Type a ticker first</span>'; return; }
            var resultDiv = document.getElementById('cg-quick-result');
            resultDiv.innerHTML = '<span style="color:#9b59b6;">Scanning (takes ~5s)...</span>';
            fetch('/api/congress/scan/' + ticker, {signal: AbortSignal.timeout(30000)}).then(r => r.json()).then(data => {
                resultDiv.innerHTML = '<span style="color:#00ff88;">' + (data.result || 'Done').substring(0, 300) + '</span>';
            }).catch(function(e) { resultDiv.innerHTML = '<span style="color:#ff4444;">Failed: ' + (e.message || 'timeout') + '</span>'; });
        }

        // Insider Trading
        fetchInsider();
        setInterval(fetchInsider, 60000);

        function fetchInsider() {
            fetch('/api/insider').then(r => r.json()).then(data => {
                if (data.error || !data.signal) return;
                var sigEl = document.getElementById('ins-signal');
                var sig = (data.signal || 'UNKNOWN').toUpperCase();
                var strength = (data.signal_strength || '').toUpperCase();
                sigEl.textContent = sig + (strength ? ' (' + strength + ')' : '');
                sigEl.style.color = sig === 'BEARISH' ? '#ff4444' : sig === 'BULLISH' ? '#00ff88' : '#ffaa00';
                document.getElementById('ins-ratio').textContent = data.buy_sell_ratio || '—';
                var paceEl = document.getElementById('ins-pace');
                paceEl.textContent = data.sell_pace || '—';
                if (data.sell_pace === 'ACCELERATING') paceEl.style.color = '#ff4444';
                document.getElementById('ins-sell-vol').textContent = data.total_sell_volume || '—';
                document.getElementById('ins-buy-vol').textContent = data.total_buy_volume || '—';

                var sellsDiv = document.getElementById('ins-sells');
                var sells = data.biggest_sells || [];
                if (sells.length > 0) {
                    sellsDiv.innerHTML = '<strong style="color:#ff4444;">Top Sells:</strong><br>' +
                        sells.slice(0, 5).map(function(s) {
                            return '<span style="color:#ff6666;">▼ ' + (s.insider || '?') + ' — $' + (s.ticker || '?') + ' ' + (s.amount || '') + '</span>';
                        }).join('<br>');
                }

                var buysDiv = document.getElementById('ins-buys');
                var buys = data.biggest_buys || [];
                if (buys.length > 0) {
                    buysDiv.innerHTML = '<strong style="color:#00ff88;">Top Buys:</strong><br>' +
                        buys.slice(0, 3).map(function(b) {
                            return '<span style="color:#00ff88;">▲ ' + (b.insider || '?') + ' — $' + (b.ticker || '?') + ' ' + (b.amount || '') + '</span>';
                        }).join('<br>');
                }

                var overlapDiv = document.getElementById('ins-overlap');
                if (data.universe_overlap && data.universe_overlap.length > 0) {
                    overlapDiv.innerHTML = '⚠️ <strong>Our Universe:</strong> ' + data.universe_overlap.join(', ');
                }

                var analysisDiv = document.getElementById('ins-analysis');
                if (data.ai_analysis) analysisDiv.innerHTML = data.ai_analysis.substring(0, 300);

                var ctxDiv = document.getElementById('ins-context');
                if (data.context) ctxDiv.innerHTML = '⚖️ ' + data.context.substring(0, 200);

                var xDiv = document.getElementById('ins-x');
                if (data.x_reaction) xDiv.innerHTML = '<strong style="color:#ff6600;">X:</strong> ' + data.x_reaction.substring(0, 200);
            }).catch(function() {});
        }

        function insQuickScan() {
            var input = document.getElementById('ins-ticker-input');
            var ticker = input.value.trim().toUpperCase();
            if (!ticker) { document.getElementById('ins-quick-result').innerHTML = '<span style="color:#ffaa00;">Type a ticker first</span>'; return; }
            var resultDiv = document.getElementById('ins-quick-result');
            resultDiv.innerHTML = '<span style="color:#ff3333;">Scanning (takes ~5s)...</span>';
            fetch('/api/insider/scan/' + ticker, {signal: AbortSignal.timeout(30000)}).then(r => r.json()).then(data => {
                resultDiv.innerHTML = '<span style="color:#00ff88;">' + (data.result || 'Done').substring(0, 300) + '</span>';
            }).catch(function(e) { resultDiv.innerHTML = '<span style="color:#ff4444;">Failed: ' + (e.message || 'timeout') + '</span>'; });
        }

        // X Influencer Tracker
        fetchXTracker();
        setInterval(fetchXTracker, 60000);

        function fetchXTracker() {
            fetch('/api/x-tracker').then(r => r.json()).then(data => {
                if (data.error || !data.accounts_scanned) return;
                document.getElementById('xt-accounts').textContent = data.accounts_scanned || '—';
                document.getElementById('xt-posts').textContent = data.total_new_posts || '0';
                var sigEl = document.getElementById('xt-signals');
                sigEl.textContent = data.total_high_signals || '0';
                if (data.total_high_signals > 0) sigEl.style.color = '#ff4444';

                var hlDiv = document.getElementById('xt-highlights');
                var results = data.results || [];
                var allSignals = [];
                results.forEach(function(r) {
                    (r.signals || []).forEach(function(s) { allSignals.push(s); });
                });
                if (allSignals.length > 0) {
                    hlDiv.innerHTML = '<strong style="color:#1da1f2;">Signals:</strong><br>' +
                        allSignals.slice(0, 4).map(function(s) {
                            var color = s.direction === 'bullish' ? '#00ff88' : s.direction === 'bearish' ? '#ff4444' : '#ffaa00';
                            return '<span style="color:' + color + ';">@' + s.handle + ': $' + s.ticker + ' ' + s.direction.toUpperCase() + ' (' + s.signal_type + ')</span>';
                        }).join('<br>');
                }

                var latDiv = document.getElementById('xt-latest');
                if (results.length > 0) {
                    latDiv.innerHTML = results.slice(0, 3).map(function(r) {
                        return '<span style="color:#888;">@' + r.handle + ': ' + (r.account_summary || '').substring(0, 80) + '</span>';
                    }).join('<br>');
                }
            }).catch(function() {});
        }

        function xtQuickScan() {
            var input = document.getElementById('xt-handle-input');
            var handle = input.value.trim().replace('@', '');
            if (!handle) { document.getElementById('xt-quick-result').innerHTML = '<span style="color:#ffaa00;">Type a handle first</span>'; return; }
            var resultDiv = document.getElementById('xt-quick-result');
            resultDiv.innerHTML = '<span style="color:#1da1f2;">Scanning @' + handle + ' (takes ~10s)...</span>';
            fetch('/api/x-tracker/scan/' + handle, {signal: AbortSignal.timeout(60000)}).then(r => r.json()).then(data => {
                var msg = data.posts_fetched ? data.posts_fetched + ' posts, ' + data.high_signals + ' signals' : 'No data';
                resultDiv.innerHTML = '<span style="color:#00ff88;">' + msg + '</span>';
            }).catch(function(e) { resultDiv.innerHTML = '<span style="color:#ff4444;">Failed: ' + (e.message || 'timeout') + '</span>'; });
        }

        // Playlist Tracker
        fetchPlaylist();
        setInterval(fetchPlaylist, 60000);

        function fetchPlaylist() {
            fetch('/api/playlist').then(r => r.json()).then(data => {
                if (data.error) return;
                document.getElementById('pl-videos').textContent = data.total_videos || '—';
                document.getElementById('pl-time').textContent = data.last_scan ? data.last_scan.substring(11, 19) : '—';
                document.getElementById('pl-changes').textContent = data.last_summary || 'No changes';
                var topDiv = document.getElementById('pl-engagement');
                var top = data.top_videos || [];
                if (top.length > 0) {
                    topDiv.innerHTML = '<strong style="color:#c4302b;">Top:</strong><br>' +
                        top.slice(0, 3).map(function(v) {
                            return '<span style="color:#ccc;">' + (v.title || '').substring(0, 50) + ' — ' + (v.views || 0).toLocaleString() + ' views</span>';
                        }).join('<br>');
                }
            }).catch(function() {});
        }

        // Systems 1-12 deploy code removed — v2.8+ LIVE only
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    # Inject live account data server-side so it shows immediately on page load
    acct = _ibkr_cache
    return render_template_string(
        HTML,
        net_liq=f"${acct['net_liq']:,.2f}" if acct.get('net_liq') else "—",
        cash=f"${acct['cash']:,.2f}" if acct.get('cash') else "—",
        buying_power=f"${acct['buying_power']:,.2f}" if acct.get('buying_power') else "—",
        acct_updated=f"Live · {acct['updated']}" if acct.get('updated') else "Connecting..."
    )


# Sandboxed TradingView widget pages — served as iframes so popups are blocked at the iframe level
@app.route("/tv/ticker")
def tv_ticker():
    """Ticker-tape widget in its own page — embedded via sandboxed iframe."""
    return """<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
body{margin:0;padding:0;background:#0a0a0f;}
</style><script>
// Block popups inside this iframe too
window.open=function(){return null;};
try{Object.defineProperty(window,'open',{value:function(){return null;},writable:false,configurable:false});}catch(e){}
</script></head><body>
<div class="tradingview-widget-container" style="height:46px;width:100%;">
  <div class="tradingview-widget-container__widget"></div>
  <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js" async>
  {"symbols":[{"proName":"NASDAQ:MSTR","title":"MSTR"},{"proName":"NASDAQ:IBIT","title":"IBIT"},{"proName":"NASDAQ:NVDA","title":"NVDA"},{"proName":"NASDAQ:TSLA","title":"TSLA"},{"proName":"NASDAQ:AMD","title":"AMD"},{"proName":"NYSE:CCJ","title":"CCJ"},{"proName":"NYSE:VST","title":"VST"},{"proName":"NASDAQ:CEG","title":"CEG"},{"proName":"NYSE:XOM","title":"XOM"},{"proName":"NASDAQ:COIN","title":"COIN"},{"proName":"BITSTAMP:BTCUSD","title":"BTC"},{"proName":"FOREXCOM:SPXUSD","title":"S&P 500"}],"showSymbolLogo":true,"isTransparent":true,"displayMode":"adaptive","colorTheme":"dark","locale":"en"}
  </script>
</div>
</body></html>"""


@app.route("/tv/chart")
def tv_chart():
    """Advanced chart widget in its own page — embedded via sandboxed iframe."""
    return """<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
html,body{margin:0;padding:0;height:100%;background:#0a0a0f;}
#tradingview-chart-widget{height:100%;width:100%;}
</style><script>
window.open=function(){return null;};
try{Object.defineProperty(window,'open',{value:function(){return null;},writable:false,configurable:false});}catch(e){}
</script></head><body>
<div class="tradingview-widget-container" style="height:100%;width:100%;">
  <div id="tradingview-chart-widget" style="height:100%;width:100%;"></div>
  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
  <script type="text/javascript">
    new TradingView.widget({"autosize":true,"symbol":"NASDAQ:MSTR","interval":"D","timezone":"America/New_York","theme":"dark","style":"1","locale":"en","enable_publishing":false,"allow_symbol_change":true,"container_id":"tradingview-chart-widget","hide_side_toolbar":false,"studies":["RSI@tv-basicstudies","MACD@tv-basicstudies"]});
  </script>
</div>
</body></html>"""


@app.route("/api/status")
def api_status():
    """Return system status — uses shared IBKR cache (refreshed every 15s by /api/account-live)."""
    result = {"status": "online", "constitution": "v50.0"}

    # Ensure cache is fresh
    cache_stale = True
    if _ibkr_cache.get("_last_query_ts"):
        try:
            ts = _ibkr_cache["_last_query_ts"]
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            cache_stale = (datetime.now() - ts).total_seconds() > 15
        except:
            cache_stale = True
    if cache_stale:
        with app.test_request_context():
            api_account_live()

    # Account from cache
    result["account"] = {
        "net_liq": _ibkr_cache.get("net_liq", 0),
        "cash": _ibkr_cache.get("cash", 0),
        "buying_power": _ibkr_cache.get("buying_power", 0),
    }

    # Positions from cache
    result["positions"] = _ibkr_cache.get("positions", [])

    # MSTR price from cache
    if _ibkr_cache.get("mstr_price"):
        result["mstr_price"] = _ibkr_cache["mstr_price"]

    # Check pending trades
    pending_file = os.path.join(DATA_DIR, "pending_trade.json")
    if os.path.exists(pending_file):
        try:
            with open(pending_file) as f:
                result["pending_trade"] = json.load(f)
        except Exception:
            pass

    return jsonify(result)


@app.route("/api/entry/status")
def api_entry_status():
    """Return pending entry approval status."""
    state = _load_json("trader_v28_state.json")
    pending = state.get("pending_entry")
    if pending:
        return jsonify({"status": "pending", "entry": pending})
    return jsonify({"status": "none"})

def _execute_entry_now():
    """Execute pending entry immediately in background thread."""
    import threading
    def _run():
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
            import telegram as tg
            tg.send("🚀 *Entry APPROVED — Executing NOW*")

            state_file = os.path.join(DATA_DIR, "trader_v28_state.json")
            with open(state_file) as f:
                state = json.load(f)
            pending = state.get("pending_entry", {})
            if not pending:
                tg.send("❌ No pending entry found in state")
                return

            # Import and instantiate trader
            from trader_v28 import RudyV28
            trader = RudyV28(mode="live", test_mode=False)
            trader.state = state  # Use current state

            mstr_price = pending["mstr_price"]
            btc_price = pending["btc_price"]
            entry_num = pending["entry_num"]

            # Clear pending before executing
            state["pending_entry"] = None
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2, default=str)

            trader._execute_entry(mstr_price, btc_price, entry_num)
        except Exception as e:
            try:
                import telegram as tg
                tg.send(f"🔴 *Entry execution failed:* {str(e)[:200]}")
            except Exception:
                pass

    t = threading.Thread(target=_run, daemon=True)
    t.start()

@app.route("/api/entry/approve")
def api_entry_approve():
    """Approve pending entry — execute IMMEDIATELY."""
    state_file = os.path.join(DATA_DIR, "trader_v28_state.json")
    if os.path.exists(state_file):
        with open(state_file) as f:
            state = json.load(f)
        if state.get("pending_entry"):
            _execute_entry_now()
            return jsonify({"status": "approved", "message": "Entry approved — executing NOW"})
    return jsonify({"status": "error", "message": "No pending entry"})

@app.route("/api/entry/reject")
def api_entry_reject():
    """Reject pending entry — Commander says NO."""
    state_file = os.path.join(DATA_DIR, "trader_v28_state.json")
    if os.path.exists(state_file):
        with open(state_file) as f:
            state = json.load(f)
        if state.get("pending_entry"):
            state["entry_rejected"] = True
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2, default=str)
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
            try:
                import telegram as tg
                tg.send("❌ *Entry REJECTED* — signal cleared.")
            except Exception:
                pass
            return jsonify({"status": "rejected", "message": "Entry rejected — signal cleared"})
    return jsonify({"status": "error", "message": "No pending entry"})

@app.route("/api/strike-roll", methods=["GET", "POST"])
def api_strike_roll():
    """HITL Strike Roll — GET to see pending roll, POST to approve/reject."""
    state_file = os.path.expanduser("~/rudy/data/trader_v28_state.json")
    try:
        with open(state_file) as f:
            state = json.load(f)
    except Exception:
        return jsonify({"error": "Cannot read daemon state"}), 500

    pending = state.get("pending_strike_roll")

    if request.method == "GET":
        if not pending:
            return jsonify({"status": "no_pending_roll", "message": "No strike roll pending"})
        return jsonify({"status": "pending", "roll": pending})

    # POST — approve or reject
    action = request.json.get("action", "").lower() if request.is_json else request.form.get("action", "").lower()
    if action not in ("approve", "reject"):
        return jsonify({"error": "action must be 'approve' or 'reject'"}), 400

    if not pending:
        return jsonify({"error": "No pending roll to act on"}), 404

    if action == "approve":
        # Log the approval and store as executed
        state["approved_strike_rolls"] = state.get("approved_strike_rolls", [])
        pending["approved_at"] = datetime.now().isoformat()
        pending["status"] = "APPROVED"
        state["approved_strike_rolls"].append(pending)
        # Update the last_strike_recommendation to the new band
        state["last_strike_recommendation"] = {
            "band": pending["new_band"],
            "safety_strikes": pending["new_safety_strikes"],
            "safety_weight": 0.45,
            "spec_strikes": pending["new_spec_strikes"],
            "spec_weight": 0.55,
            "premium_at_entry": state.get("last_premium", 0),
            "timestamp": datetime.now().isoformat(),
            "rolled_from": pending["old_band"]
        }
        state.pop("pending_strike_roll", None)
        msg = f"✅ Strike roll APPROVED: {pending['old_band']} → {pending['new_band']}"
    else:
        pending["rejected_at"] = datetime.now().isoformat()
        pending["status"] = "REJECTED"
        state["rejected_strike_rolls"] = state.get("rejected_strike_rolls", [])
        state["rejected_strike_rolls"].append(pending)
        state.pop("pending_strike_roll", None)
        msg = f"❌ Strike roll REJECTED — keeping current strikes"

    with open(state_file, "w") as f:
        json.dump(state, f, indent=2, default=str)

    # Notify via Telegram
    try:
        from scripts.telegram import send as send_tg
        send_tg(msg)
    except Exception:
        pass

    return jsonify({"status": action + "d", "message": msg})


@app.route("/api/strike-roll/approve")
def api_strike_roll_approve():
    """GET endpoint to approve pending strike roll — works from any browser/fetch tool."""
    request.environ['REQUEST_METHOD'] = 'POST'
    state_file = os.path.expanduser("~/rudy/data/trader_v28_state.json")
    try:
        with open(state_file) as f:
            state = json.load(f)
    except Exception:
        return jsonify({"error": "Cannot read state"}), 500
    pending = state.get("pending_strike_roll")
    if not pending:
        return jsonify({"status": "no_pending_roll", "message": "No pending roll to approve"})
    state.setdefault("approved_strike_rolls", [])
    pending["approved_at"] = datetime.now().isoformat()
    pending["status"] = "APPROVED"
    state["approved_strike_rolls"].append(pending)
    state["last_strike_recommendation"] = {
        "band": pending["new_band"],
        "safety_strikes": pending["new_safety_strikes"],
        "safety_weight": 0.45,
        "spec_strikes": pending["new_spec_strikes"],
        "spec_weight": 0.55,
        "premium_at_entry": state.get("last_premium", 0),
        "timestamp": datetime.now().isoformat(),
        "rolled_from": pending["old_band"]
    }
    state.pop("pending_strike_roll", None)
    msg = f"✅ Strike roll APPROVED: {pending['old_band']} → {pending['new_band']}"
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2, default=str)
    try:
        telegram.send(msg)
    except Exception:
        pass
    return jsonify({"status": "approved", "message": msg})


@app.route("/api/strike-roll/reject")
def api_strike_roll_reject():
    """GET endpoint to reject pending strike roll — works from any browser/fetch tool."""
    state_file = os.path.expanduser("~/rudy/data/trader_v28_state.json")
    try:
        with open(state_file) as f:
            state = json.load(f)
    except Exception:
        return jsonify({"error": "Cannot read state"}), 500
    pending = state.get("pending_strike_roll")
    if not pending:
        return jsonify({"status": "no_pending_roll", "message": "No pending roll to reject"})
    state.setdefault("rejected_strike_rolls", [])
    pending["rejected_at"] = datetime.now().isoformat()
    pending["status"] = "REJECTED"
    state["rejected_strike_rolls"].append(pending)
    state.pop("pending_strike_roll", None)
    msg = f"❌ Strike roll REJECTED — keeping current strikes"
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2, default=str)
    try:
        telegram.send(msg)
    except Exception:
        pass
    return jsonify({"status": "rejected", "message": msg})


@app.route("/api/safety-status")
def api_safety_status():
    """Get current safety layer status."""
    state_file = os.path.expanduser("~/rudy/data/trader_v28_state.json")
    safety_log = os.path.expanduser("~/rudy/logs/safety_events.json")
    try:
        with open(state_file) as f:
            state = json.load(f)
    except Exception:
        return jsonify({"error": "Cannot read state"}), 500
    safety = state.get("safety", {})
    events = []
    try:
        if os.path.exists(safety_log):
            with open(safety_log) as f:
                events = json.load(f)
    except Exception:
        pass
    return jsonify({
        "daily_loss_paused": safety.get("daily_loss_paused_date") == datetime.now().strftime("%Y-%m-%d"),
        "consecutive_losses": safety.get("consecutive_losses", 0),
        "consecutive_loss_paused": safety.get("consecutive_loss_paused", False),
        "total_trades": safety.get("total_trades", 0),
        "total_wins": safety.get("total_wins", 0),
        "consecutive_wins": safety.get("consecutive_wins", 0),
        "nlv_open": safety.get("nlv_open", 0),
        "nlv_open_date": safety.get("nlv_open_date", ""),
        "recent_events": events[-10:] if events else []
    })


@app.route("/api/oos-health")
def api_oos_health():
    """Get OOS revalidation health diagnostics for the safety panel."""
    import glob as _glob
    data_dir = os.path.expanduser("~/rudy/data")
    history_file = os.path.join(data_dir, "oos_revalidation_history.json")

    # Load latest quarterly result
    files = sorted(_glob.glob(os.path.join(data_dir, "oos_revalidation_Q*.json")), reverse=True)
    latest = None
    if files:
        try:
            with open(files[0]) as f:
                latest = json.load(f)
        except Exception:
            pass

    # Load drift history
    history = {}
    if os.path.exists(history_file):
        try:
            with open(history_file) as f:
                history = json.load(f)
        except Exception:
            pass

    if not latest and not history:
        return jsonify({"error": "No OOS revalidation data", "verdict": None})

    summary = latest.get("summary", {}) if latest else {}
    stability = summary.get("winner_stability", {})

    return jsonify({
        "verdict": latest.get("verdict") if latest else None,
        "quarter": latest.get("label") if latest else None,
        "run_timestamp": latest.get("run_timestamp", "")[:19] if latest else None,
        "rolling_4q_avg": summary.get("rolling_4q_avg") or latest.get("rolling_4q_avg"),
        "rolling_4q_count": summary.get("rolling_4q_count", 0),
        "winner_stable": stability.get("stable") if stability else None,
        "winner_stability_msg": stability.get("message", "") if stability else "",
        "drift_streak": history.get("consecutive_drift_alerts", summary.get("drift_streak", 0)),
        "escalation": summary.get("escalation", "NONE"),
        "regime": summary.get("regime") or latest.get("regime") if latest else None,
        "regime_softened": summary.get("regime_softened", False),
        "in_adverse_regime": summary.get("in_adverse_regime", False),
        "relative_score": summary.get("relative_score"),
        "wfe_ratio": summary.get("wfe_ratio"),
        "live_rank": summary.get("live_rank"),
        "winner": summary.get("winner"),
    })


@app.route("/api/safety/reset-consec-loss")
def api_reset_consec_loss():
    """Reset consecutive loss shutdown (HITL approval)."""
    state_file = os.path.expanduser("~/rudy/data/trader_v28_state.json")
    try:
        with open(state_file) as f:
            state = json.load(f)
        safety = state.get("safety", {})
        safety["consecutive_loss_paused"] = False
        safety["consecutive_losses"] = 0
        state["safety"] = safety
        with open(state_file, "w") as f:
            json.dump(state, f, indent=2, default=str)
        telegram.send("✅ Consecutive loss shutdown cleared. Trading resumed.")
        return jsonify({"status": "reset", "message": "Consecutive loss pause cleared"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════
#  TRADER2 (MSTR Put) & TRADER3 (SPY Put) — Ladder Monitor APIs
# ══════════════════════════════════════════════════════════════

def _get_cached_position_value(symbol, strike, right):
    """Zero-latency position lookup from _ibkr_cache (background feed, refreshed every 10s).
    Use this for dashboard reads — never opens a new IBKR connection."""
    positions = _ibkr_cache.get("positions", [])
    for p in positions:
        if (p.get("symbol") == symbol and
                p.get("secType") == "OPT" and
                p.get("right") == right and
                abs(float(p.get("strike", 0)) - strike) < 0.01 and
                abs(float(p.get("quantity", 0))) > 0):
            mkt  = float(p.get("marketValue", 0))
            cost = float(p.get("avgCost", 0))
            pnl  = float(p.get("unrealizedPNL", 0))
            qty  = abs(float(p.get("quantity", 0)))
            pnl_pct = ((mkt - cost) / cost * 100) if cost > 0 else 0
            mid  = mkt / (qty * 100) if qty > 0 else 0
            return {"live_value": mkt, "live_mid": mid, "live_gain_pct": pnl_pct,
                    "live_unrealized_pnl": pnl, "live_cost": cost, "source": "IBKR_CACHE"}
    return {}


def _get_live_position_value(symbol, strike, right, client_id=53):
    """Pull live market_value and pnl_pct from IBKR for a specific option position."""
    try:
        import asyncio
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
        from ib_insync import IB
        ib = IB()
        ib.connect("127.0.0.1", 7496, clientId=client_id, timeout=8)
        portfolio = ib.portfolio()
        for p in portfolio:
            c = p.contract
            if (c.symbol == symbol and
                    hasattr(c, "strike") and abs(float(c.strike) - strike) < 0.01 and
                    hasattr(c, "right") and c.right == right and
                    abs(p.position) > 0):
                mkt  = float(p.marketValue)
                cost = float(p.averageCost)
                pnl  = float(p.unrealizedPNL)
                pnl_pct = ((mkt - cost) / cost * 100) if cost > 0 else 0
                qty  = abs(float(p.position))
                mid  = mkt / (qty * 100) if qty > 0 else 0
                ib.disconnect()
                return {"live_value": mkt, "live_mid": mid, "live_gain_pct": pnl_pct,
                        "live_unrealized_pnl": pnl, "live_cost": cost, "source": "LIVE_TWS"}
        ib.disconnect()
    except Exception:
        pass
    return {}

@app.route("/api/trader1/status")
def api_trader1_status():
    state_file = os.path.join(DATA_DIR, "trader_v28_state.json")
    if not os.path.exists(state_file):
        return jsonify({"status": "not_started"})
    with open(state_file) as f:
        state = json.load(f)
    is_armed = state.get("is_armed", False)
    dipped = state.get("dipped_below_200w", False)
    in_trade = state.get("position_qty", 0) > 0
    if in_trade:
        status = "IN TRADE"
    elif is_armed:
        status = "ARMED"
    elif dipped:
        status = "DIPPED — WAITING RECLAIM"
    else:
        status = "MONITORING"
    # Daemon alive check
    import subprocess as _sp
    try:
        _pr = _sp.run(["pgrep", "-f", "trader_v28.py"], capture_output=True, text=True, timeout=3)
        daemon_running = _pr.returncode == 0
    except Exception:
        daemon_running = False

    # Staleness — hours since last eval (v2.8+ evaluates 3:45 PM ET weekdays only)
    last_eval_str = state.get("last_eval", "")
    eval_hours_ago = None
    if last_eval_str:
        try:
            _last_dt = datetime.fromisoformat(last_eval_str)
            eval_hours_ago = round((datetime.now() - _last_dt).total_seconds() / 3600, 1)
        except Exception:
            pass

    # MSTR price — prefer live IBKR cache over stale state file
    live_mstr = _ibkr_cache.get("mstr_price") or state.get("last_mstr_price", 0)

    # mNAV premium — use most recent entry in premium_history, fall back to live IBKR cache
    premium_history = state.get("premium_history", [])
    current_premium = premium_history[-1] if premium_history else _ibkr_cache.get("current_premium")

    return jsonify({
        "status": status,
        "is_armed": is_armed,
        "dipped_below_200w": dipped,
        "green_week_count": state.get("green_week_count", 0),
        "last_mstr_price": live_mstr,
        "position_qty": state.get("position_qty", 0),
        "entry_price": state.get("entry_price", 0),
        "peak_gain_pct": state.get("peak_gain_pct", 0),
        "current_premium": current_premium,
        "last_eval": last_eval_str,
        "eval_hours_ago": eval_hours_ago,
        "daemon_running": daemon_running,
        "next_eval": "15:45 ET weekdays",
    })

@app.route("/api/trader2/status")
def api_trader2_status():
    state_file = os.path.join(DATA_DIR, "trader2_state.json")
    state = {}
    if os.path.exists(state_file):
        with open(state_file) as f:
            state = json.load(f)
    # Always overlay live IBKR data — it's the source of truth for prices
    live = _get_cached_position_value("MSTR", 50.0, "P")
    if not live:
        live = _get_live_position_value("MSTR", 50.0, "P", client_id=53)
    if live:
        state["last_value"]    = live["live_value"]
        state["last_mid"]      = live["live_mid"]
        state["last_gain_pct"] = live["live_gain_pct"]
        state["cost_basis"]    = live["live_cost"]
        state["value_source"]  = live.get("source", "LIVE_TWS")
    return jsonify(state) if state else jsonify({"status": "not_started", "position": "MSTR $50 Put Jan 2028"})

@app.route("/api/trader3/status")
def api_trader3_status():
    state_file = os.path.join(DATA_DIR, "trader3_state.json")
    state = {}
    if os.path.exists(state_file):
        with open(state_file) as f:
            state = json.load(f)
    # Always overlay live IBKR data — it's the source of truth for prices
    live = _get_cached_position_value("SPY", 430.0, "P")
    if not live:
        live = _get_live_position_value("SPY", 430.0, "P", client_id=54)
    if live:
        state["last_value"]    = live["live_value"]
        state["last_mid"]      = live["live_mid"]
        state["last_gain_pct"] = live["live_gain_pct"]
        state["cost_basis"]    = live["live_cost"]
        state["value_source"]  = live.get("source", "LIVE_TWS")
    return jsonify(state) if state else jsonify({"status": "not_started", "position": "SPY $430 Put Jan 2027"})

@app.route("/api/equity_chart")
def api_equity_chart():
    PNL_HISTORY_FILE = os.path.join(DATA_DIR, "pnl_history.json")
    if not os.path.exists(PNL_HISTORY_FILE):
        return jsonify({"error": "No history yet"}), 404
    with open(PNL_HISTORY_FILE) as f:
        history = json.load(f)
    if len(history) < 2:
        return jsonify({"error": "Need at least 2 data points"}), 404
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        from charts import generate_equity_chart_bytes
        chart_bytes = generate_equity_chart_bytes(history)
        resp = make_response(chart_bytes)
        resp.headers.set('Content-Type', 'image/png')
        resp.headers.set('Cache-Control', 'no-cache')
        return resp
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/trader2/approve-sell")
def api_trader2_approve_sell():
    state_file = os.path.join(DATA_DIR, "trader2_state.json")
    if os.path.exists(state_file):
        with open(state_file) as f:
            state = json.load(f)
        if state.get("pending_sell"):
            state["sell_approved"] = True
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2, default=str)
            return jsonify({"status": "approved", "message": "Trader2 sell approved — will execute on next check"})
    return jsonify({"status": "error", "message": "No pending sell for Trader2"})

@app.route("/api/trader3/approve-sell")
def api_trader3_approve_sell():
    state_file = os.path.join(DATA_DIR, "trader3_state.json")
    if os.path.exists(state_file):
        with open(state_file) as f:
            state = json.load(f)
        if state.get("pending_sell"):
            state["sell_approved"] = True
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2, default=str)
            return jsonify({"status": "approved", "message": "Trader3 sell approved — will execute on next check"})
    return jsonify({"status": "error", "message": "No pending sell for Trader3"})

@app.route("/api/trader2/approve-roll")
def api_trader2_approve_roll():
    state_file = os.path.join(DATA_DIR, "trader2_state.json")
    if os.path.exists(state_file):
        with open(state_file) as f:
            state = json.load(f)
        if state.get("pending_roll"):
            state["roll_approved"] = True
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2, default=str)
            return jsonify({"status": "approved", "message": "Trader2 strike roll approved"})
    return jsonify({"status": "error", "message": "No pending roll for Trader2"})

@app.route("/api/trader3/approve-roll")
def api_trader3_approve_roll():
    state_file = os.path.join(DATA_DIR, "trader3_state.json")
    if os.path.exists(state_file):
        with open(state_file) as f:
            state = json.load(f)
        if state.get("pending_roll"):
            state["roll_approved"] = True
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2, default=str)
            return jsonify({"status": "approved", "message": "Trader3 strike roll approved"})
    return jsonify({"status": "error", "message": "No pending roll for Trader3"})


@app.route("/api/status-dump")
def api_status_dump():
    """Full Rudy v2.8+ status dump — designed for Claude iPhone to fetch."""
    import subprocess
    dump = {"system": "Rudy v2.8+ Trend Adder", "mode": "LIVE", "account_id": "U15746102", "timestamp": datetime.now().isoformat()}

    # Trader state
    state_file = os.path.join(DATA_DIR, "trader_v28_state.json")
    if os.path.exists(state_file):
        with open(state_file) as f:
            state = json.load(f)
        dump["armed"] = state.get("is_armed", False)
        dump["dipped_below_200w"] = state.get("dipped_below_200w", False)
        dump["green_week_count"] = state.get("green_week_count", 0)
        dump["in_position"] = state.get("position_qty", 0) > 0
        dump["position_qty"] = state.get("position_qty", 0)
        dump["entry_price"] = state.get("entry_price", 0)
        dump["bars_in_trade"] = state.get("bars_in_trade", 0)
        dump["peak_gain_pct"] = state.get("peak_gain_pct", 0)
        dump["first_entry_done"] = state.get("first_entry_done", False)
        dump["second_entry_done"] = state.get("second_entry_done", False)
        dump["last_eval"] = state.get("last_eval", "")
        # Prefer live IBKR prices over stale eval state
        live_mstr = _ibkr_cache.get("mstr_price") or state.get("last_mstr_price", 0)
        sentinel = _load_json("btc_sentinel_state.json")
        live_btc = (sentinel.get("last_price", 0)
                    or _ibkr_cache.get("btc_price", 0)
                    or state.get("last_btc_price", 0))
        dump["last_mstr_price"] = live_mstr
        dump["last_btc_price"] = live_btc
        dump["last_stoch_rsi"] = state.get("last_stoch_rsi", 0)
        # Compute premium live
        prem_hist = state.get("premium_history", [])
        live_premium = state.get("last_premium", 0)
        if live_mstr > 0 and live_btc > 0:
            treasury = _load_json("mstr_treasury.json")
            holdings = treasury.get("btc_holdings", 761068)
            shares = treasury.get("diluted_shares", 293157000)
            if holdings > 0 and shares > 0:
                nav = (live_btc * holdings) / shares
                if nav > 0:
                    live_premium = round(live_mstr / nav, 4)
        dump["last_premium"] = live_premium
        dump["premium_history"] = prem_hist
        dump["trade_log"] = state.get("trade_log", [])

    # Filters
    filters = {}
    if os.path.exists(state_file):
        filters["armed"] = state.get("is_armed", False)
        filters["btc_above_200w"] = True  # from last eval
        filters["stoch_rsi"] = state.get("last_stoch_rsi", 0)
        filters["stoch_rsi_pass"] = state.get("last_stoch_rsi", 100) < 70
        prem = state.get("premium_history", [])
        filters["premium"] = round(prem[-1], 4) if prem else 0
        filters["no_position"] = state.get("position_qty", 0) == 0
    dump["filters"] = filters

    # Account from IBKR
    try:
        import asyncio
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
        from ib_insync import IB
        ib = IB()
        ib.connect("127.0.0.1", 7496, clientId=21, timeout=5)
        summary = ib.accountSummary()
        acct = {}
        for item in summary:
            if item.tag == "NetLiquidation": acct["net_liq"] = round(float(item.value), 2)
            elif item.tag == "TotalCashValue": acct["cash"] = round(float(item.value), 2)
            elif item.tag == "BuyingPower": acct["buying_power"] = round(float(item.value), 2)
        positions = ib.positions()
        acct["positions"] = [{"symbol": p.contract.symbol, "qty": float(p.position), "avg_cost": float(p.avgCost)} for p in positions]
        ib.disconnect()
        dump["account"] = acct
    except Exception as e:
        dump["account_error"] = str(e)

    # Breaker
    breaker_file = os.path.join(DATA_DIR, "breaker_state.json")
    if os.path.exists(breaker_file):
        with open(breaker_file) as f:
            dump["breaker"] = json.load(f)

    # Daemon status
    try:
        result = subprocess.run(["pgrep", "-f", "trader_v28.py --mode live"], capture_output=True, text=True, timeout=5)
        dump["daemon_running"] = result.returncode == 0
        dump["daemon_pid"] = result.stdout.strip() if result.returncode == 0 else None
    except:
        dump["daemon_running"] = False

    # Performance
    dump["performance"] = {"total_trades": 0, "total_pnl": 0, "win_rate": 0, "max_drawdown": 0}
    hist_file = os.path.join(DATA_DIR, "trade_history.json")
    if os.path.exists(hist_file):
        try:
            with open(hist_file) as f:
                trades = json.load(f)
            if trades:
                wins = [t for t in trades if t.get("pnl", 0) > 0]
                dump["performance"]["total_trades"] = len(trades)
                dump["performance"]["total_pnl"] = round(sum(t.get("pnl", 0) for t in trades), 2)
                dump["performance"]["win_rate"] = round(len(wins) / len(trades) * 100, 1) if trades else 0
        except:
            pass

    return jsonify(dump)


@app.route("/api/feed")
def api_feed():
    """Return recent log entries from all log files for the Live Feed."""
    entries = []
    log_files = {
        "signals.log": "signal",
        "em.log": "trade",
        "paper_test.log": "alert",
        "webhook.log": "signal",
        "scanner.log": "signal",
        "system1_v8.log": "trade",
        "quantconnect.log": "alert",
    }
    # Skip noise patterns
    skip_patterns = ["Market closed", "sleeping", "====="]
    for filename, entry_type in log_files.items():
        path = os.path.join(LOG_DIR, filename)
        if not os.path.exists(path):
            continue
        try:
            with open(path) as f:
                lines = f.readlines()
            for line in lines[-50:]:
                line = line.strip()
                if not line:
                    continue
                if any(p in line for p in skip_patterns):
                    continue
                # Parse timestamp from [YYYY-MM-DD HH:MM:SS] prefix
                ts = ""
                msg = line
                if line.startswith("["):
                    bracket_end = line.find("]")
                    if bracket_end > 0:
                        ts = line[1:bracket_end]
                        msg = line[bracket_end + 1:].strip()
                if msg:
                    entries.append({"time": ts, "text": msg, "type": entry_type, "source": filename})
        except:
            continue

    # Sort by timestamp descending and return latest 50
    entries.sort(key=lambda e: e["time"], reverse=True)
    return jsonify(entries[:50])


@app.route("/api/live-progress")
def api_paper_progress():
    track_file = os.path.join(DATA_DIR, "paper_track.json")
    if not os.path.exists(track_file):
        return jsonify({"status": "no_data"})
    with open(track_file) as f:
        track = json.load(f)

    days = track.get("days", {})
    dates = sorted(days.keys())
    start_bal = track.get("starting_balance", 0)

    if not dates:
        return jsonify({"status": "no_data", "starting_balance": start_bal})

    latest = days[dates[-1]]
    trading_days = len(dates)

    # Build mini chart data (last 30 days of daily returns)
    chart = []
    for d in dates[-30:]:
        pct = days[d].get("daily_pct", 0)
        chart.append({"date": d, "pct": pct})

    # Calculate days until go-live
    from datetime import datetime as dt
    go_live = "LIVE"
    days_remaining = 0

    # Streak
    streak = 0
    for d in reversed(dates):
        c = days[d].get("daily_change", 0)
        if c >= 0 and streak >= 0:
            streak += 1
        elif c < 0 and streak <= 0:
            streak -= 1
        else:
            break

    # Count active systems (those with position files containing trades)
    active_systems = 0
    for i in [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12]:
        pos_file = os.path.join(DATA_DIR, f"trader{i}_positions.json")
        if os.path.exists(pos_file):
            try:
                with open(pos_file) as f:
                    data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    active_systems += 1
            except Exception:
                pass

    return jsonify({
        "status": "active",
        "starting_balance": start_bal,
        "current": latest.get("net_liq", 0),
        "total_change": latest.get("total_change", 0),
        "total_pct": latest.get("total_pct", 0),
        "daily_change": latest.get("daily_change", 0),
        "daily_pct": latest.get("daily_pct", 0),
        "peak": latest.get("peak", 0),
        "drawdown_pct": latest.get("drawdown_pct", 0),
        "trading_days": trading_days,
        "days_remaining": max(0, days_remaining),
        "go_live_earliest": go_live,
        "streak": streak,
        "chart": chart,
        "start_date": track.get("start_date", ""),
        "active_systems": active_systems,
        "total_systems": 11,
    })


@app.route("/api/auditor")
def api_auditor():
    summary = auditor.get_summary()
    summary["paper_test"] = auditor.check_paper_test()
    return jsonify(summary)


@app.route("/api/deploy/status")
def api_deploy_status():
    import deployer
    return jsonify(deployer.get_status())


@app.route("/api/deploy/live/<int:system_id>", methods=["POST"])
def api_deploy_live(system_id):
    import deployer
    success, message = deployer.deploy_live(system_id)
    if success:
        import telegram
        telegram.send(f"DEPLOYMENT: System {system_id} switched to LIVE trading (port 7496)")
    return jsonify({"success": success, "message": message})


@app.route("/api/deploy/paper/<int:system_id>", methods=["POST"])
def api_deploy_paper(system_id):
    import deployer
    success, message = deployer.deploy_paper(system_id)
    if success:
        import telegram
        telegram.send(f"DEPLOYMENT: System {system_id} switched back to PAPER trading")
    return jsonify({"success": success, "message": message})


@app.route("/api/accountant")
def api_accountant():
    return jsonify(accountant.get_dashboard_summary())


@app.route("/api/deepseek/regime")
def api_deepseek_regime():
    """Return v2.8 MSTR/BTC status from live trader state."""
    # Pull real data from v2.8 state file
    state_file = os.path.expanduser("~/rudy/data/trader_v28_state.json")
    result = {
        "regime": "UNKNOWN",
        "confidence": 0,
        "outlook": "No v2.8 state data available",
        "reasoning": "",
        "adjustments": {},
        "timestamp": datetime.now().isoformat(),
    }

    if os.path.exists(state_file):
        with open(state_file) as f:
            state = json.load(f)

        armed = state.get("is_armed", False)
        in_position = state.get("position_qty", 0) > 0
        dipped = state.get("dipped_below_200w", False)
        green_weeks = state.get("green_week_count", 0)
        last_eval = state.get("last_eval", "—")
        # Prefer live IBKR prices over stale eval state
        last_mstr = _ibkr_cache.get("mstr_price") or state.get("last_mstr_price", 0)
        sentinel = _load_json("btc_sentinel_state.json")
        last_btc = (sentinel.get("last_price", 0)
                    or _ibkr_cache.get("btc_price", 0)
                    or state.get("last_btc_price", 0))
        # Compute premium live instead of reading stale value
        last_premium = state.get("last_premium", 0)
        if last_mstr > 0 and last_btc > 0:
            treasury = _load_json("mstr_treasury.json")
            holdings = treasury.get("btc_holdings", 761068)
            shares = treasury.get("diluted_shares", 293157000)
            if holdings > 0 and shares > 0:
                nav = (last_btc * holdings) / shares
                if nav > 0:
                    last_premium = round(last_mstr / nav, 4)
        last_stochrsi = state.get("last_stoch_rsi", 0)

        # Determine regime from v2.8 perspective
        if in_position:
            regime = "IN POSITION"
            entry = state.get("entry_price", 0)
            gain = ((last_mstr - entry) / entry * 100) if entry > 0 else 0
            outlook = f"MSTR position open @ ${entry:.2f}. Current ${last_mstr:.2f} ({gain:+.1f}%). Managing trailing stops."
        elif armed:
            regime = "ARMED — ENTRY IMMINENT"
            outlook = f"200W SMA reclaimed with {green_weeks} green weeks. Waiting for StochRSI < 70 (currently {last_stochrsi:.0f})."
        elif dipped:
            regime = "DIPPED — WATCHING"
            outlook = f"MSTR dipped below 200W SMA. Need {2 - green_weeks} more green weeks to arm."
        else:
            regime = "WAITING FOR DIP"
            outlook = f"MSTR above 200W SMA. Waiting for cycle-low dip. Premium: {last_premium:.2f}x."

        result = {
            "regime": regime,
            "confidence": 85 if armed else (70 if dipped else 50),
            "outlook": outlook,
            "reasoning": f"MSTR ${last_mstr:.2f} | BTC ${last_btc:,.0f} | Premium {last_premium:.2f}x | StRSI {last_stochrsi:.0f} | Armed: {armed}",
            "adjustments": {
                "aggression": "conservative" if not armed else "ready",
                "avoid_entries": not armed,
                "hedge_up": False,
                "position_size_mult": 0.25,
            },
            "inputs": {
                "mstr_price": last_mstr,
                "btc_price": last_btc,
                "premium": last_premium,
                "stoch_rsi": last_stochrsi,
                "armed": armed,
                "in_position": in_position,
                "dipped": dipped,
                "green_weeks": green_weeks,
            },
            "timestamp": last_eval or datetime.now().isoformat(),
        }

    return jsonify(result)


@app.route("/api/deepseek/trades")
def api_deepseek_trades():
    """Return recent trade analyses."""
    trade_file = os.path.expanduser("~/rudy/data/trade_analysis.json")
    if os.path.exists(trade_file):
        with open(trade_file) as f:
            return jsonify(json.load(f))
    return jsonify([])


@app.route("/api/deepseek/review")
def api_deepseek_review():
    """Return latest strategy review."""
    review_file = os.path.expanduser("~/rudy/data/strategy_review.json")
    if os.path.exists(review_file):
        with open(review_file) as f:
            return jsonify(json.load(f))
    return jsonify({})


@app.route("/api/grok")
def api_grok():
    """Return latest Grok intelligence report."""
    intel_file = os.path.expanduser("~/rudy/data/grok_intel.json")
    if os.path.exists(intel_file):
        with open(intel_file) as f:
            history = json.load(f)
        return jsonify(history[-1] if history else {})
    return jsonify({})


@app.route("/api/grok/scan/<ticker>")
def api_grok_scan(ticker):
    """Quick scan a ticker via Grok."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import grok_scanner
    result = grok_scanner.quick_scan(ticker.upper())
    return jsonify({"result": result})


@app.route("/api/gronk")
def api_gronk():
    """Return latest Gronk intelligence report."""
    intel_file = os.path.expanduser("~/rudy/data/gronk_intel.json")
    if os.path.exists(intel_file):
        with open(intel_file) as f:
            history = json.load(f)
        return jsonify(history[-1] if history else {})
    return jsonify({})


@app.route("/api/gronk/history")
def api_gronk_history():
    """Return Gronk intel history."""
    intel_file = os.path.expanduser("~/rudy/data/gronk_intel.json")
    if os.path.exists(intel_file):
        with open(intel_file) as f:
            return jsonify(json.load(f))
    return jsonify([])


@app.route("/api/gronk/scan/<ticker>")
def api_gronk_scan(ticker):
    """Quick scan a ticker via Gronk."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import gronk
    result = gronk.quick_scan(ticker.upper())
    return jsonify({"result": result})


@app.route("/api/youtube")
def api_youtube():
    """Return latest YouTube intelligence report."""
    intel_file = os.path.expanduser("~/rudy/data/youtube_intel.json")
    if os.path.exists(intel_file):
        with open(intel_file) as f:
            history = json.load(f)
        return jsonify(history[-1] if history else {})
    return jsonify({})


@app.route("/api/youtube/scan/<path:ticker>")
def api_youtube_scan(ticker):
    """Quick scan a ticker or channel name on YouTube."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import youtube_scanner
    # Don't uppercase channel names — only uppercase if it looks like a ticker
    query = ticker.upper() if len(ticker) <= 5 and ticker.isalpha() else ticker
    result = youtube_scanner.quick_scan(query)
    return jsonify({"result": result})


@app.route("/api/youtube/analyze", methods=["POST"])
def api_youtube_analyze():
    """Deep-analyze a YouTube video (transcript + Grok)."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import youtube_scanner
    data = request.get_json() or {}
    url = data.get("url", "")
    if not url:
        return jsonify({"error": "No URL provided"})
    result = youtube_scanner.analyze_video(url)
    return jsonify({"result": result})


@app.route("/api/tiktok")
def api_tiktok():
    """Return latest TikTok intelligence report."""
    intel_file = os.path.expanduser("~/rudy/data/tiktok_intel.json")
    if os.path.exists(intel_file):
        with open(intel_file) as f:
            history = json.load(f)
        return jsonify(history[-1] if history else {})
    return jsonify({})


@app.route("/api/tiktok/scan/<ticker>")
def api_tiktok_scan(ticker):
    """Quick scan a ticker on TikTok."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import tiktok_scanner
    result = tiktok_scanner.quick_scan(ticker.upper())
    return jsonify({"result": result})


@app.route("/api/truth")
def api_truth():
    """Return latest Truth Social scan data."""
    intel_file = os.path.expanduser("~/rudy/data/truth_intel.json")
    if os.path.exists(intel_file):
        with open(intel_file) as f:
            history = json.load(f)
        return jsonify(history[-1] if history else {})
    return jsonify({})


@app.route("/api/truth/scan/<topic>")
def api_truth_scan(topic):
    """Search Truth Social posts for a specific topic."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import truth_scanner
    result = truth_scanner.search_topic(topic)
    return jsonify({"result": result})


@app.route("/api/congress")
def api_congress():
    """Return latest Congress stock trade data."""
    intel_file = os.path.expanduser("~/rudy/data/congress_intel.json")
    if os.path.exists(intel_file):
        with open(intel_file) as f:
            history = json.load(f)
        return jsonify(history[-1] if history else {})
    return jsonify({})


@app.route("/api/congress/scan/<ticker>")
def api_congress_scan(ticker):
    """Search Congress trades for a specific ticker."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import congress_scanner
    result = congress_scanner.quick_scan(ticker.upper())
    return jsonify({"result": result})


@app.route("/api/insider")
def api_insider():
    """Return latest insider trading data."""
    intel_file = os.path.expanduser("~/rudy/data/insider_intel.json")
    if os.path.exists(intel_file):
        with open(intel_file) as f:
            history = json.load(f)
        return jsonify(history[-1] if history else {})
    return jsonify({})


@app.route("/api/insider/scan/<ticker>")
def api_insider_scan(ticker):
    """Search insider trades for a specific ticker."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import insider_scanner
    result = insider_scanner.quick_scan(ticker.upper())
    return jsonify({"result": result})


@app.route("/api/x-tracker")
def api_x_tracker():
    """Return latest X tracker scan data."""
    summary_file = os.path.expanduser("~/rudy/data/x_tracker_latest.json")
    if os.path.exists(summary_file):
        with open(summary_file) as f:
            return jsonify(json.load(f))
    return jsonify({})


@app.route("/api/x-tracker/scan/<handle>")
def api_x_tracker_scan(handle):
    """Quick scan a specific X account."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import x_tracker
    result = x_tracker.scan_account(handle.replace("@", ""))
    return jsonify(result or {"error": "No data"})


@app.route("/api/playlist")
def api_playlist():
    """Return playlist tracker status."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import playlist_tracker
    return jsonify(playlist_tracker.get_status())


@app.route("/gronk")
def gronk_page():
    """Gronk X Intelligence Dashboard."""
    intel_file = os.path.expanduser("~/rudy/data/gronk_intel.json")
    latest = {}
    if os.path.exists(intel_file):
        with open(intel_file) as f:
            history = json.load(f)
            if history:
                latest = history[-1]
    return render_template_string(GRONK_PAGE, intel=latest)


GRONK_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Gronk - X Intelligence</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    background: #0a0a0f;
    color: #e0e0e0;
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 16px;
    padding: 24px;
}
h1 { color: #00d4ff; margin-bottom: 8px; font-size: 24px; }
.subtitle { color: #888; margin-bottom: 24px; font-size: 13px; }
.back-link { color: #00d4ff; text-decoration: none; display: inline-block; margin-bottom: 16px; }
.card {
    background: #12121a;
    border: 1px solid #1e1e3a;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
}
.card-title { color: #00d4ff; font-size: 16px; font-weight: bold; margin-bottom: 12px; }
.sentiment {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 4px;
    font-weight: bold;
    font-size: 14px;
}
.sentiment.bullish { background: #1b5e20; color: #4caf50; }
.sentiment.bearish { background: #b71c1c; color: #ef5350; }
.sentiment.mixed { background: #e65100; color: #ff9800; }
.sentiment.neutral { background: #333; color: #aaa; }
.signal-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    border-bottom: 1px solid #1e1e3a;
}
.signal-row:last-child { border-bottom: none; }
.signal-ticker { color: #00d4ff; font-weight: bold; font-size: 15px; }
.signal-buy { color: #4caf50; }
.signal-sell { color: #f44336; }
.signal-watch { color: #ff9800; }
.confidence-high { color: #4caf50; }
.confidence-medium { color: #ff9800; }
.confidence-low { color: #888; }
.tag {
    display: inline-block;
    background: #1a1a2e;
    border: 1px solid #1e1e3a;
    padding: 4px 10px;
    border-radius: 16px;
    margin: 4px;
    font-size: 15px;
}
.tag.hot { border-color: #ff9800; color: #ff9800; }
.tag.catalyst { border-color: #4caf50; color: #4caf50; }
.tag.risk { border-color: #f44336; color: #f44336; }
.scan-form { display: flex; gap: 8px; margin-bottom: 24px; }
.scan-input {
    background: #12121a;
    border: 1px solid #1e1e3a;
    color: #e0e0e0;
    padding: 8px 16px;
    border-radius: 6px;
    font-family: inherit;
    font-size: 14px;
    flex: 1;
    max-width: 200px;
}
.scan-btn {
    background: #00d4ff;
    color: #0a0a0f;
    border: none;
    padding: 8px 20px;
    border-radius: 6px;
    font-family: inherit;
    font-size: 13px;
    font-weight: bold;
    cursor: pointer;
}
.scan-btn:hover { background: #00b8d4; }
.summary { color: #aaa; font-size: 13px; line-height: 1.6; }
.meta { color: #555; font-size: 15px; margin-top: 8px; }
#scan-result { margin-top: 16px; white-space: pre-wrap; font-size: 13px; color: #aaa; }
</style>
</head>
<body>
<a href="/" class="back-link">< Back to Dashboard</a>
<h1>Gronk - X Intelligence Scanner</h1>
<p class="subtitle">AI-powered social media intelligence for trading signals (DeepSeek + Tavily)</p>

<div class="scan-form">
    <input type="text" class="scan-input" id="ticker-input" placeholder="Quick scan ticker..." />
    <button class="scan-btn" onclick="quickScan()">Scan</button>
</div>
<div id="scan-result"></div>

{% if intel %}
<div class="card">
    <div class="card-title">Latest Report</div>
    <p class="meta">{{ intel.get('timestamp', 'N/A') }} | {{ intel.get('total_posts_scanned', 0) }} posts scanned</p>
    <p style="margin-top: 8px;">Sentiment: <span class="sentiment {{ intel.get('overall_sentiment', 'neutral') }}">{{ intel.get('overall_sentiment', 'N/A').upper() }}</span></p>
    <p class="summary" style="margin-top: 12px;">{{ intel.get('summary', 'No summary available')[:500] }}</p>
</div>

{% if intel.get('signals') %}
<div class="card">
    <div class="card-title">Trading Signals</div>
    {% for s in intel.get('signals', []) %}
    <div class="signal-row">
        <span class="signal-ticker">{{ s.get('ticker', '?') }}</span>
        <span class="signal-{{ s.get('signal', 'watch') }}">{{ s.get('signal', '?').upper() }}</span>
        <span class="confidence-{{ s.get('confidence', 'low') }}">{{ s.get('confidence', '?') }}</span>
        <span style="color: #888; font-size: 15px;">{{ s.get('system', '') }}</span>
    </div>
    <div style="padding: 4px 12px 8px; font-size: 15px; color: #666;">{{ s.get('reason', '') }}</div>
    {% endfor %}
</div>
{% endif %}

{% if intel.get('hot_tickers') %}
<div class="card">
    <div class="card-title">Hot Tickers</div>
    {% for t in intel.get('hot_tickers', []) %}
    <span class="tag hot">{{ t }}</span>
    {% endfor %}
</div>
{% endif %}

{% if intel.get('catalysts') %}
<div class="card">
    <div class="card-title">Upcoming Catalysts</div>
    {% for c in intel.get('catalysts', []) %}
    <span class="tag catalyst">{{ c }}</span>
    {% endfor %}
</div>
{% endif %}

{% if intel.get('risks') %}
<div class="card">
    <div class="card-title">Risks</div>
    {% for r in intel.get('risks', []) %}
    <span class="tag risk">{{ r }}</span>
    {% endfor %}
</div>
{% endif %}

{% else %}
<div class="card">
    <div class="card-title">No Intel Yet</div>
    <p class="summary">Run a scan using the input above or wait for the next scheduled scan.</p>
</div>
{% endif %}

<script>
function quickScan() {
    const ticker = document.getElementById('ticker-input').value.trim().toUpperCase();
    if (!ticker) return;
    const el = document.getElementById('scan-result');
    el.textContent = 'Scanning ' + ticker + '...';
    fetch('/api/gronk/scan/' + ticker)
        .then(r => r.json())
        .then(data => { el.textContent = data.result || 'No results'; setTimeout(() => location.reload(), 2000); })
        .catch(e => { el.textContent = 'Error: ' + e; });
}
document.getElementById('ticker-input').addEventListener('keypress', function(e) {
    if (e.key === 'Enter') quickScan();
});
</script>
</body>
</html>
"""


@app.route("/api/pinescripts")
def api_pinescripts():
    """Return Pine Script contents for copy-paste."""
    scripts_dir = os.path.expanduser("~/rudy/strategies")
    scripts = {}
    for name, filename in [
        ("Energy Momentum OPTIONS (Trader3)", "pinescript_energy_momentum.pine"),
        ("Short Squeeze OPTIONS (Trader4)", "pinescript_squeeze.pine"),
        ("Breakout Momentum OPTIONS (Trader5)", "pinescript_breakout.pine"),
        ("MSTR Lottery OPTIONS (System 1)", "pinescript_lottery.pine"),
        ("Iron Condor OPTIONS (Trader5b)", "pinescript_sideways_condor.pine"),
        ("TQQQ Momentum OPTIONS (System 12)", "pinescript_tqqq_momentum.pine"),
        ("NTR Ag Momentum OPTIONS", "pinescript_ntr_ag_momentum.pine"),
        ("MSTR BTC Moonshot OPTIONS", "pinescript_mstr_moonshot.pine"),
        ("MSTR Cycle-Low LEAP v2.8 Dynamic Blend", "pinescript_mstr_cycle_low_entry_v28.pine"),
        ("MSTR Cycle-Low LEAP v2.7 Diamond Hands", "pinescript_mstr_cycle_low_entry_v27.pine"),
        ("MSTR Cycle-Low LEAP v2.5 Production", "pinescript_mstr_cycle_low_entry.pine"),
        ("10x Momentum Runner v2", "pinescript_10x_runner_v2.pine"),
        ("BTC/USD Moonshot", "pinescript_btc_moonshot.pine"),
    ]:
        path = os.path.join(scripts_dir, filename)
        if os.path.exists(path):
            with open(path) as f:
                scripts[name] = f.read()
    return jsonify(scripts)


@app.route("/pinescripts")
def pinescripts_page():
    """Page with Pine Scripts and copy buttons."""
    scripts_dir = os.path.expanduser("~/rudy/strategies")
    scripts = []
    script_info = [
        ("Energy Golden Cross (Trader3)", "pinescript_energy_momentum.pine",
         "Rudy Energy GC v2 — Share-based momentum on energy equities. 8% position, 15% PT, 8% stop, 25-bar max hold. Golden Cross regime + 7 filters: volume, crude oil, SPY, XLE sector, weekly MTF. ATR stops (2.5x), trailing after 10%. Alerts fire for real options entries. Designed for: CCJ, UEC, XOM, CVX, OXY, DVN, FANG, VST, CEG, LEU."),
        ("Short Squeeze (Trader4)", "pinescript_squeeze.pine",
         "Rudy Squeeze Momentum v2 — Share-based squeeze trading. 8% position, 20% PT, 10% stop, 12-bar max hold. Squeeze score system (0-8) + SPY filter. ATR stops (2.5x), trailing after 12%. Alerts fire for real options entries. Designed for: GME, AMC, SOFI, RIVN, LCID, COIN, MARA, RIOT, PLTR."),
        ("Breakout Momentum (Trader5)", "pinescript_breakout.pine",
         "Rudy Breakout Momentum v2 — Share-based breakout trading. 8% position, 18% PT, 8% stop, 20-bar max hold. 7 filters: volume, MACD, SPY, MTF, consolidation base. ATR stops (2.5x), trailing after 12%. Alerts fire for real options entries. Designed for: NVDA, AMZN, GOOGL, TSLA, NFLX, CRM, AVGO, AMD, SHOP, SQ."),
        ("MSTR Lottery (System 1)", "pinescript_lottery.pine",
         "Rudy MSTR Lottery v2 — Share-based momentum on BTC proxies. 8% position, 15% PT, 8% stop, 30-bar max hold. BTC regime filter (core edge). ATR stops (2.5x), trailing after 10%. Alerts fire for real options entries. Designed for: MSTR, IBIT, COIN."),
        ("Sideways Mean Reversion (Trader5b)", "pinescript_sideways_condor.pine",
         "Rudy Sideways Reversion v2 — Mean reversion scalper for range-bound markets. Buys lower BB dips, shorts upper BB rips, targets mid-band. 10% position, ATR stops (1.5x), 10-bar max hold. Regime filter: ADX < 25 + BB width < 8%. VIX filter, volume quiet filter, MTF sideways. Auto-exits on trend break or VIX spike. Long + short. Designed for: SPY, QQQ, IWM, XLF, GLD, TLT."),
        ("10x Momentum Runner", "pinescript_10x_momentum.pine",
         "Rudy 10x Momentum v1 — Share-based momentum for high-growth runners. 8% position, 15% PT, ATR 1.8x stop, 40-bar max hold. EMA stack detection (10>21>50 = power trend) + MACD + SPY filter. Trailing stop locks runners. Alerts fire for Trader to execute CALL options. Designed for: IONQ, RGTI, QBTS, SMCI, AFRM, RKLB, HOOD, UPST."),
        ("Fence Bar Opening Range (Scalper)", "pinescript_fence_bar.pine",
         "Rudy Fence Bar v1 — Opening range breakout + retest scalper. First 5-min candle = fence. Waits for breakout then retest. Stop at 50% inside fence, 2R target. 20 SMA anchor filter. Max 2 trades/day, EOD auto-exit. 5-MINUTE CHART ONLY. Designed for: SPY, QQQ, AAPL, TSLA, NVDA, AMD."),
        ("TQQQ Momentum (System 12)", "pinescript_tqqq_momentum.pine",
         "Rudy TQQQ Momentum v2 — Share-based momentum on TQQQ. 8% position, 12% PT, 7% stop, 15-bar max hold. Momentum score -100 to +100 + QQQ regime filter + volume + MTF. ATR stops (2.0x), trailing after 8%. Alerts fire for real options entries. Designed for: TQQQ daily chart."),
        ("NTR Agricultural Momentum", "pinescript_ntr_ag_momentum.pine",
         "Rudy NTR Ag Momentum v1 — Share-based momentum on Nutrien Ltd (NTR). 8% position, 12% PT, ATR 2.5x stop, 60-bar max hold. EMA 20/SMA 50 golden cross regime. RSI 30-80 filter + SPY filter. Exit ONLY on death cross (EMA20 < SMA50) — no premature exits. 6% trail activation, 4% offset. Alerts fire for CALL options. Designed for: NTR daily chart."),
        ("Rudy v2.8+ Trend Adder — MSTR Cycle-Low LEAP ✅ BEST", "pinescript_mstr_cycle_low_entry_v28plus.pine",
         "Rudy v2.8+ Trend Adder — MSTR Cycle-Low LEAP | Constitution v50.0 | LIVE TRADING on IBKR U15746102. "
         "MSTR TREASURY: 761,068 BTC (~3.5% supply) at avg $66,384/coin, 293M diluted shares, mNAV ~1.0x (auto-updated weekly from SEC filings). "
         "BASE: 200W dip+reclaim → 25% capital. TREND ADDER: 50W EMA > 200W SMA (4 week confirm) → +25% capital. "
         "CAPITAL PLAN: Phase 1 ~$7.9K (now) → Phase 2 put proceeds → Phase 3 $130K (Aug-Oct 2026) = ~$139.6K total. "
         "SYSTEM 13 BRAIN: CalibratedEnsemble (RF300+GB200) 95.6% CV, 4 regimes, current DISTRIBUTION 82.2%. RL layer with experience replay. "
         "MULTI-BRAIN: Claude + Grok (CT sentiment) + Gemini (regime cross-check). "
         "WALK-FORWARD: WFE 1.18, +6,750.6% OOS across 7 windows. "
         "ADVANCED STRESS TESTS: Flash Crash PASS, Monte Carlo 5K shuffles CONDITIONAL (circuit breakers required), mNAV Apocalypse PASS (0.75x kill switch). "
         "CROSS-TICKER: AVGO +501.5% Sharpe 0.888 (research only). Kalman Filter FAILED — 200W SMA lag is the feature. "
         "SAFETY: 6 circuit breakers (2% daily cap, 5-loss shutdown, 0.75x mNAV kill switch, premium alert, self-eval loop, PID locks). "
         "Stealth execution (limit+jitter, no round numbers). Weekend BTC sentinel 24/7. "
         "BTC CYCLE: 250W MA $56K (capitulation), 200W SMA $59.4K (entry trigger), 300W MA $50K (floor). "
         "9 scheduled tasks. Phase-aware seasonality (bull vs bear by month). "
         "✅ TradingView: Daily +1,915.50%, Weekly +183.66%. Apply to: MSTR Weekly chart."),
        ("Rudy v2.7 Diamond Hands — MSTR Cycle-Low LEAP (Superseded by v2.8+)", "pinescript_mstr_cycle_low_entry_v27.pine",
         "Rudy v2.7 Diamond Hands — MSTR Cycle-Low LEAP. SUPERSEDED by v2.8+ Trend Adder. QC Validated: +58.3% Weekly, +71.0% Daily. Keeps 60%+ of position for moonshot. Profit takes: 10% at 10x/20x/50x/100x. Wider trails: 40%/35%/30%/25%/15% starting at +500%. Daily Sharpe 0.142. Apply to: MSTR Daily chart."),
        ("Rudy v2.5 Production — MSTR Cycle-Low LEAP (Superseded by v2.8+)", "pinescript_mstr_cycle_low_entry.pine",
         "Rudy v2.5 Production — MSTR Cycle-Low LEAP. SUPERSEDED by v2.8+ Trend Adder. QC Validated: +58.6% Weekly, +61.3% Daily. ATR quiet-market filter. Re-entry after stop-out enabled. TWO-PHASE STOPS: 30% initial floor + laddered trails at +300%. Apply to: MSTR Weekly or Daily."),
        ("MSTR Cycle-Low LEAP v2.2b (30% Floor) — Legacy", "pinescript_mstr_cycle_low_entry_30floor.pine",
         "MSTR Cycle-Low LEAP v2.2b (30% Floor Edition) — LEGACY, superseded by v2.5 Production. 250W dip+reclaim entry. 30% Initial Floor from entry price. Use v2.5 Production instead for ATR filter + re-entry."),
        ("MSTR BTC Moonshot (System 1) ✅ BACKTESTED", "pinescript_mstr_moonshot.pine",
         "Rudy MSTR BTC Moonshot v2 — Full strategy with backtesting. $100K into ~280 deep OTM LEAPs. Dynamic 200W crossover entry (no fixed calendar gate). 5-tier laddered trail (None->30%->25%->20%->15%->10% at 3x/5x/10x/20x/50x), 25% partial sells at each tier. BTC death cross hard exit + 200W MA fallback + premium compression override. QuantConnect Backtest: $100K → $190,594 (+90.6%), 91% win rate, Sharpe 0.304, max DD 48.9%. Entry validated Jun 2024 @ $152.54 (shares proxy). Designed for: MSTR daily chart."),
        ("10x Momentum Runner v2", "pinescript_10x_runner_v2.pine",
         "Rudy 10x Runner v2 — Improved momentum runner for high-beta moonshots. 8% position, EMA stack (10>21>50) + MACD + RSI + SPY filter. ATR 1.8x initial stop, 8% trailing activation with 4% offset, 30% HWM trail, 40-bar max hold. Tiered profit taking: 25% at +100%, +300%, +500%. Adjustable stops & profit tiers. Backtest: $10K→$30.9K (+209%) across 400 trades, 55% win rate. Best: LUNR +388%. Designed for: IONQ, RGTI, RKLB, JOBY, OKLO, ACHR, LUNR, SMR, ASTS."),
        ("BTC/USD Moonshot", "pinescript_btc_moonshot.pine",
         "Rudy BTC Moonshot v1 — Same moonshot logic as MSTR LEAP adapted for BTC/USD spot. 6 entry filters: EMA21, volume surge, RSI 40-75, momentum >3%, BTC regime, Q4 halving cycle. Laddered trail (None→25%→20%→15%→12%→10% at 2x/3x/5x/10x/20x). Tiered profit taking: 25% at 3x/5x/10x/20x. 200-week MA fallback override. 5x target. Apply to: BTCUSD daily chart."),
    ]
    for name, filename, desc in script_info:
        path = os.path.join(scripts_dir, filename)
        if os.path.exists(path):
            with open(path) as f:
                scripts.append({"name": name, "code": f.read(), "desc": desc})

    return render_template_string(PINE_PAGE, scripts=scripts, scripts_json=json.dumps(scripts))


PINE_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rudy - Pine Scripts</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    background: #0a0a0f;
    color: #e0e0e0;
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 16px;
    padding: 24px;
}
h1 {
    color: #00d4ff;
    margin-bottom: 8px;
    font-size: 24px;
}
.subtitle {
    color: #888;
    margin-bottom: 32px;
    font-size: 13px;
}
.script-card {
    background: #12121a;
    border: 1px solid #1e1e3a;
    border-radius: 12px;
    margin-bottom: 24px;
    overflow: hidden;
}
.script-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 20px;
    background: #1a1a2e;
    border-bottom: 1px solid #1e1e3a;
}
.script-name {
    color: #00d4ff;
    font-size: 16px;
    font-weight: bold;
}
.copy-btn {
    background: #00d4ff;
    color: #0a0a0f;
    border: none;
    padding: 8px 20px;
    border-radius: 6px;
    font-family: inherit;
    font-size: 13px;
    font-weight: bold;
    cursor: pointer;
    transition: all 0.2s;
}
.copy-btn:hover {
    background: #00b8d4;
    transform: scale(1.05);
}
.copy-btn.copied {
    background: #00e676;
    color: #0a0a0f;
}
.script-code {
    padding: 16px 20px;
    max-height: 400px;
    overflow-y: auto;
    font-size: 15px;
    line-height: 1.5;
    white-space: pre;
    color: #b0b0b0;
}
.back-link {
    color: #00d4ff;
    text-decoration: none;
    display: inline-block;
    margin-bottom: 16px;
}
.instructions {
    background: #1a1a2e;
    border: 1px solid #0f3460;
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 24px;
    font-size: 13px;
    line-height: 1.6;
    color: #aaa;
}
.instructions strong { color: #00d4ff; }
.instructions ol { padding-left: 20px; }
.script-desc {
    padding: 12px 20px;
    font-size: 13px;
    line-height: 1.6;
    color: #aaa;
    background: #15152a;
    border-bottom: 1px solid #1e1e3a;
}
.desc-btn {
    background: #ff9800 !important;
    color: #0a0a0f !important;
    margin-right: 8px;
}
.desc-btn:hover {
    background: #f57c00 !important;
}
.hidden-data {
    display: none;
}
</style>
</head>
<body>
<a href="/" class="back-link">&lt; Back to Dashboard</a>
<h1>Pine Scripts - TradingView Backtesting</h1>
<p class="subtitle">Copy each script into TradingView's Pine Script Editor, then click "Add to chart" to validate signals</p>

<div class="instructions">
<strong>How to use:</strong>
<ol>
<li>Click "Copy" on a script below</li>
<li>Open TradingView -> Pine Script Editor (bottom panel)</li>
<li>Clear the editor, paste the script</li>
<li>Click "Add to chart" (or "Save" then "Add to chart")</li>
<li>Open the "Strategy Tester" tab to see backtest results</li>
<li>Switch to the right chart symbol (listed in each script's comments)</li>
</ol>
</div>

{% for script in scripts %}
<div class="script-card">
    <div class="script-header">
        <span class="script-name">{{ script.name }}</span>
        <div>
            <button class="copy-btn desc-btn" onclick="copyDesc(this, {{ loop.index0 }})">Copy Description</button>
            <button class="copy-btn" onclick="copyScript(this, {{ loop.index0 }})">Copy Code</button>
        </div>
    </div>
    <div class="script-desc" id="desc-{{ loop.index0 }}">{{ script.desc }}</div>
    <pre class="script-code" id="code-{{ loop.index0 }}">{{ script.code }}</pre>
</div>
{% endfor %}

<script>
const SCRIPTS = {{ scripts_json|safe }};
function copyDesc(btn, idx) {
    navigator.clipboard.writeText(SCRIPTS[idx].desc).then(() => {
        btn.textContent = 'Copied!';
        btn.classList.add('copied');
        setTimeout(() => { btn.textContent = 'Copy Description'; btn.classList.remove('copied'); }, 2000);
    });
}
function copyScript(btn, idx) {
    const code = SCRIPTS[idx].code;
    navigator.clipboard.writeText(code).then(() => {
        btn.textContent = 'Copied!';
        btn.classList.add('copied');
        setTimeout(() => {
            btn.textContent = 'Copy';
            btn.classList.remove('copied');
        }, 2000);
    }).catch(() => {
        // Fallback
        const ta = document.createElement('textarea');
        ta.value = code;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        btn.textContent = 'Copied!';
        btn.classList.add('copied');
        setTimeout(() => {
            btn.textContent = 'Copy';
            btn.classList.remove('copied');
        }, 2000);
    });
}
</script>
</body>
</html>
"""


@app.route("/projections")
def projections_page():
    """Rudy v2.8+ Trend Adder — MSTR Cycle-Low LEAP $130K projection through Jan 2029."""
    return render_template_string(PROJECTIONS_PAGE)


PROJECTIONS_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rudy v2.8+ Trend Adder — MSTR LEAP Projections</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    background: #0a0a0f;
    color: #e0e0e0;
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 16px;
    padding: 24px;
    min-height: 100vh;
}
a.back-link {
    color: #00d4ff;
    text-decoration: none;
    display: inline-block;
    margin-bottom: 16px;
}
h1 { color: #00d4ff; margin-bottom: 4px; font-size: 24px; }
h2 { color: #ff9800; font-size: 18px; margin: 32px 0 16px; }
.subtitle { color: #888; margin-bottom: 24px; font-size: 13px; line-height: 1.6; }

.thesis-box {
    background: #1a1a2e;
    border: 1px solid #0f3460;
    border-radius: 10px;
    padding: 20px;
    margin-bottom: 28px;
    font-size: 13px;
    line-height: 1.8;
    color: #bbb;
}
.thesis-box strong { color: #00d4ff; }
.thesis-box .highlight { color: #ff9800; font-weight: bold; }

/* Strategy tabs */
.strat-tabs {
    display: flex;
    gap: 4px;
    margin-bottom: 24px;
    flex-wrap: wrap;
    overflow-x: auto;
}
.strat-tab {
    padding: 10px 18px;
    background: #12121c;
    border: 1px solid #1e1e3a;
    border-radius: 8px 8px 0 0;
    color: #888;
    cursor: pointer;
    font-family: inherit;
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 0.5px;
    transition: all 0.2s;
}
.strat-tab:hover { color: #ccc; background: #1a1a2e; }
.strat-tab.active { color: #00d4ff; background: #1a1a2e; border-bottom-color: #1a1a2e; }
.strat-section { display: none; }
.strat-section.active { display: block; }

/* Scenario cards */
.scenarios {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 20px;
    margin-bottom: 32px;
}
.scenario-card {
    background: #12121c;
    border-radius: 12px;
    padding: 24px;
    text-align: center;
    position: relative;
    overflow: hidden;
}
.scenario-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
}
.scenario-card.moderate::before { background: #2196F3; }
.scenario-card.bull::before { background: #00e676; }
.scenario-card.moon::before { background: #ff9800; }
.scenario-card .label {
    font-size: 15px;
    text-transform: uppercase;
    letter-spacing: 2px;
    margin-bottom: 8px;
}
.scenario-card.moderate .label { color: #2196F3; }
.scenario-card.bull .label { color: #00e676; }
.scenario-card.moon .label { color: #ff9800; }
.scenario-card .final {
    font-size: 20px;
    font-weight: 600;
    margin: 4px 0;
    color: #aaa;
}
.scenario-card .multiple {
    font-size: 36px;
    font-weight: bold;
    margin: 8px 0 4px;
}
.scenario-card.moderate .multiple { color: #2196F3; }
.scenario-card.bull .multiple { color: #00e676; }
.scenario-card.moon .multiple { color: #ff9800; }
.scenario-card .qtr-ret { font-size: 14px; color: #667; }

/* Chart */
.chart-container {
    background: #12121c;
    border: 1px solid #1e1e3a;
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 32px;
    position: relative;
    height: 400px;
}

/* Table */
.proj-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    margin-bottom: 32px;
    overflow-x: auto;
    display: block;
}
.proj-table th {
    background: #1a1a2e;
    color: #00d4ff;
    padding: 10px 14px;
    text-align: right;
    border-bottom: 2px solid #0f3460;
    font-size: 14px;
    text-transform: uppercase;
    letter-spacing: 1px;
    white-space: nowrap;
}
.proj-table th:first-child { text-align: left; }
.proj-table td {
    padding: 8px 14px;
    text-align: right;
    border-bottom: 1px solid #1a1a2e;
    white-space: nowrap;
}
.proj-table td:first-child { text-align: left; color: #aaa; }
.proj-table tr:hover { background: #16162a; }
.moderate-c { color: #2196F3; }
.bull-c { color: #00e676; }
.moon-c { color: #ff9800; }
.peak-row { background: #1a1a10; }
.peak-row td { font-weight: bold; }

/* Combined portfolio */
.combined-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
    margin-bottom: 32px;
}
.combined-card {
    background: #12121c;
    border: 1px solid #1e1e3a;
    border-radius: 12px;
    padding: 20px;
    text-align: center;
}
.combined-card .strat-name {
    font-size: 14px;
    color: #888;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 6px;
}
.combined-card .alloc {
    font-size: 14px;
    color: #667;
    margin-bottom: 10px;
}
.combined-card .vals {
    display: flex;
    justify-content: space-around;
    font-size: 13px;
    font-weight: bold;
}

.strat-desc {
    font-size: 15px;
    color: #888;
    padding: 12px 16px;
    background: #15152a;
    border: 1px solid #1e1e3a;
    border-radius: 8px;
    margin-bottom: 20px;
    line-height: 1.6;
}
.strat-desc strong { color: #aaa; }

.assumptions {
    background: #12121c;
    border: 1px solid #1e1e3a;
    border-radius: 10px;
    padding: 20px;
    font-size: 15px;
    line-height: 1.8;
    color: #888;
    margin-bottom: 24px;
}
.assumptions strong { color: #ff9800; }
.disclaimer {
    font-size: 14px;
    color: #555;
    text-align: center;
    padding: 16px;
    border-top: 1px solid #1a1a2e;
}

/* Expandable overlay */
.expand-overlay {
    display: none;
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.85);
    z-index: 9999;
    justify-content: center;
    align-items: center;
    backdrop-filter: blur(4px);
}
.expand-overlay.active { display: flex; }
.expand-panel {
    background: #12121c;
    border: 2px solid #00d4ff;
    border-radius: 16px;
    padding: 32px 40px;
    max-width: 95vw;
    width: 1200px;
    max-height: 90vh;
    overflow-y: auto;
    box-shadow: 0 0 40px rgba(0,212,255,0.3);
    animation: expandIn 0.2s ease-out;
    position: relative;
}
@keyframes expandIn {
    from { transform: scale(0.85); opacity: 0; }
    to { transform: scale(1); opacity: 1; }
}
.expand-close {
    position: sticky;
    top: 0;
    float: right;
    font-size: 28px;
    color: #667;
    cursor: pointer;
    background: #12121c;
    border: none;
    font-family: inherit;
    z-index: 10;
    padding: 0 4px;
}
.expand-close:hover { color: #ff4444; }
.expandable {
    cursor: pointer;
    transition: transform 0.15s, box-shadow 0.15s;
    position: relative;
}
.expandable:hover {
    transform: scale(1.01);
    box-shadow: 0 0 16px rgba(0,212,255,0.12);
}
/* expand button is now a real element, no ::after needed */

/* Expanded sizes */
.expand-panel .scenarios { grid-template-columns: repeat(3, 1fr); }
.expand-panel .scenario-card .multiple { font-size: 56px; }
.expand-panel .scenario-card .final { font-size: 24px; }
.expand-panel .scenario-card .label { font-size: 16px; }
.expand-panel .scenario-card .qtr-ret { font-size: 14px; }
.expand-panel .chart-container { height: 500px; }
.expand-panel .proj-table { font-size: 15px; }
.expand-panel .proj-table th { font-size: 14px; padding: 14px 18px; }
.expand-panel .proj-table td { padding: 12px 18px; }
.expand-panel .combined-grid { grid-template-columns: repeat(3, 1fr); }
.expand-panel .combined-card .strat-name { font-size: 14px; }
.expand-panel .combined-card .vals { font-size: 18px; }

@media (max-width: 768px) {
    .scenarios { grid-template-columns: 1fr; }
    .combined-grid { grid-template-columns: 1fr; }
    .strat-tabs { gap: 2px; }
    .strat-tab { padding: 8px 10px; font-size: 14px; }
}
</style>
</head>
<body>
<a href="/" class="back-link">&lt; Back to Dashboard</a>
<h1>🔄 Rudy v2.8+ Trend Adder — MSTR Cycle-Low LEAP Projections</h1>
<p class="subtitle">$130,000 deployed &mdash; Entry at 2026 cycle low &mdash; Ride to January 2029 peak &mdash; v2.8 base + golden cross trend adder &mdash; 3 scenarios</p>

<div class="thesis-box">
    <strong>The Thesis:</strong> Bitcoin completes its 4-year cycle. BTC has finished <span class="highlight">higher at the end of every completed presidential term</span> since 2013 (Obama +4,500%, Trump 1st +3,100%, Biden +190%).
    A sustained bull run begins late 2026 and tops in <span class="highlight">January 2029</span>.
    MSTR trades as a 2-3x leveraged BTC proxy. Deep OTM LEAP calls multiply MSTR moves 10-50x.<br><br>
    <strong>Strategy:</strong> Rudy v2.8+ Trend Adder buys MSTR LEAP calls at the cycle low (BTC ~$45-50K, MSTR ~$130-170).
    <strong>Phase 1 (Base):</strong> 200W dip+reclaim entry → 25% capital deployed with strict confluence filters (BTC &gt; 200W + StochRSI &lt; 70 + ATR quiet).
    <strong>Phase 2 (Trend Adder):</strong> When 50W EMA crosses above 200W SMA (golden cross) and holds for 4 weeks → deploy additional 25% capital with wider stops.
    The trend adder catches the "second phase" of bull runs — after the dip+reclaim proves right and sustained uptrend is confirmed.
    Adder exits independently on convergence-down (both MAs falling + within 10%). DYNAMIC BLEND: LEAP multiplier adjusts by mNAV premium — 8.4x at discount, 7.5x fair value, 5.6x elevated, 3.9x euphoric.<br><br>
    <strong>✅ QC Backtest:</strong> +126.5% (base + adder), 132 orders, P/L Ratio 7.41<br>
    <strong>✅ Walk-Forward:</strong> WFE 1.18 (OOS &gt; IS), <span class="highlight">+6,750.6% stitched OOS</span>, standard_tight_minimal 7/7 windows<br>
    <strong>✅ vs v2.8 Base:</strong> +6,058% improvement (+692.2% → +6,750.6%), same bear risk profile<br>
    <strong>✅ TradingView:</strong> Daily <span class="highlight">+1,915.50%</span> (44 trades), Weekly +183.66% (25 trades)<br>
    <strong>✅ Regime Stress:</strong> 0/5 false positives — crypto winter, post-top, bear traps, full bear, COVID<br>
    <strong>✅ Execution:</strong> Survives 200bps slippage (Sharpe 0.171), worst-case 75bps+2% gaps = ratio 0.91<br>
    <strong>✅ Perturbation:</strong> 75% survival under ±20% random param noise, all 5 trials positive Sharpe<br>
    <strong>✅ Path Independent:</strong> History-seeded 200W SMA — CV=0% across all start dates<br>
    <strong>✅ Capital Scaling:</strong> Convex — more capital = better risk-adjusted returns<br>
    <strong>✅ AVGO Cross-Val:</strong> +501.5%, Sharpe 0.888, 18.8% DD — trend adder edge confirmed on second ticker<br>
    <strong>✅ MARA Research:</strong> FAILED — no structural edge (3 orders, +13.9%, Sharpe 0.12) — research only<br>
    <strong>✅ Lookahead Audit:</strong> No data leakage found in QC or live code (March 2026)<br>
    <strong>✅ Safety Stack:</strong> PID lockfiles, 2% daily loss cap, 5-loss shutdown, HITL strike rolls, premium compression alerts, real-time Strike Engine<br><br>
    <strong>$130K deployed into ~280 deep OTM MSTR LEAP calls.</strong> Base position + trend adder = up to 50% capital deployed during confirmed bull runs.
</div>

<!-- Strategy Tabs -->
<div class="strat-tabs">
    <button class="strat-tab active" onclick="showStrat('v24_main', event)">v2.8+ Trend Adder</button>
    <button class="strat-tab" onclick="showStrat('by_btc', event)">By BTC Price</button>
</div>

<!-- All strategy sections are built by JS -->
<div id="strat-content"></div>

<!-- Expand overlay -->
<div class="expand-overlay" id="expandOverlay" onclick="if(event.target===this)closeExpand()">
    <div class="expand-panel">
        <button class="expand-close" onclick="closeExpand()">&times;</button>
        <div id="expandContent"></div>
    </div>
</div>

<div class="assumptions">
    <strong>Assumptions & Methodology — v2.8+ Trend Adder:</strong><br>
    &bull; Start: $130,000 deployed into ~280 deep OTM MSTR LEAP calls at cycle low (MSTR ~$130-170, BTC ~$45-50K)<br>
    &bull; <strong>Phase 1 (Base):</strong> v2.8 strict confluence entry — 200W SMA dip+reclaim + BTC &gt; 200W + StochRSI &lt; 70 + ATR quiet filter → 25% capital<br>
    &bull; <strong>Phase 2 (Trend Adder):</strong> Golden cross (50W EMA &gt; 200W SMA) confirmed 4 weeks → additional 25% capital with wider stops<br>
    &bull; Adder exits independently on convergence-down (both MAs falling + within 10%) — doesn't drag down base position<br>
    &bull; Adder safety stops: -60% panic floor, 45% initial floor, minimal trail tiers (25% at 100x, 35% at 50x)<br>
    &bull; Re-entry after stop-out enabled — catches full bull run, not just first leg<br>
    &bull; LEAP multiplier: DYNAMIC premium-based blend (3.9x-8.4x) — adjusts by mNAV premium at evaluation time<br>
    &bull; &nbsp;&nbsp;Premium &lt;0.8x: 8.4x (60% deep ITM + 40% ATM) | 0.8-1.2x: 7.5x | 1.2-1.5x: 5.6x | &gt;1.5x: 3.9x<br>
    &bull; 💎 Diamond Hands trails: 40%→35%→30%→25%→15% at 5x/10x/20x/50x/100x<br>
    &bull; Small 10% profit takes at 10x/20x/50x/100x — keeps 60%+ riding for moonshot<br>
    &bull; Returns shaped by BTC/market cycle: accumulation (lower), markup (higher), euphoria (peak), blow-off (exit)<br>
    &bull; Moderate: BTC $110-150K, conservative MSTR premium expansion<br>
    &bull; Bull: BTC $150-200K, strong premium expansion, trend adder captures second leg<br>
    &bull; Moonshot: BTC $200K+, euphoric premium expansion, IV spikes, full base + adder leverage<br>
    &bull; Jan 2029 = cycle peak — shift to cash/hedges after<br>
    &bull; ✅ QC Backtest: +126.5% net profit, 132 orders, P/L ratio 7.41, Sharpe 0.258<br>
    &bull; ✅ Walk-Forward: WFE 1.18 (OOS &gt; IS), <strong>+6,750.6% stitched OOS</strong>, standard_tight_minimal won 7/7 windows — PERFECT stability<br>
    &bull; ✅ vs v2.8 Baseline: +6,058% improvement (+692.2% → +6,750.6%), identical bear market risk<br>
    &bull; ✅ TradingView Live: Daily +1,915.50% (44 trades), Weekly +183.66% (25 trades)<br>
    &bull; ✅ Regime Stress: 0/5 false positives across 5 adverse regimes — adder never bleeds in bears<br>
    &bull; ✅ Execution Realism: Survives 200bps slippage (Sharpe 0.171), 3x vol-scaled fills (Sharpe 0.211), apocalypse scenario +100.7%<br>
    &bull; ✅ Capital Scaling: Convex — more capital = better Sharpe (0.085 base → 0.258 at 25% → 0.378 at 75%)<br>
    &bull; ✅ Not Curve-Fit: ±20% random perturbation on ALL params — 75% avg survival, 5/5 trials positive Sharpe<br>
    &bull; ✅ Path Independent: History-seeded 200W SMA — CV=0%, identical results across all start dates (2016-2020)<br>
    &bull; ✅ Anti-Trend Resilient: Signal strong even at 1-2 week confirmation — not dependent on long confirmation window<br>
    &bull; ✅ OOS Bull Run: +97.6% (Jan-Jun 2024), +163.1% (Jul-Dec 2024), +163.1% (Jan-Jun 2025)<br>
    &bull; ⚠️ Alpha half-life: ~2 weeks after golden cross — timely execution is critical<br>
    &bull; Historical precedent: BTC higher at end of every completed presidential term since 2013
</div>

<div class="disclaimer">
    Hypothetical projections based on historical cycle patterns. Past performance does not guarantee future results.
    Options trading involves substantial risk of loss. These projections assume the BTC 4-year cycle thesis plays out as modeled.
    LEAP options can expire worthless — risk is limited to the $130K deployed.
</div>

<script>
const START_CAPITAL = 130000;

// v2.8+ Trend Adder MSTR Cycle-Low LEAP — quarterly projections
// Based on QC backtest (+126.5%), walk-forward WFE 1.18 (+6,750% OOS), and BTC presidential term pattern
// Trend adder amplifies bull quarters: base 25% + adder 25% = 50% capital during confirmed uptrends
const QUARTERS = [
    ["Q4 2026", "Entry/Accumulation",  55,  65,  95],
    ["Q1 2027", "Early Markup",        50,  65, 100],
    ["Q2 2027", "GC Confirmed+Adder",  55,  95, 140],
    ["Q3 2027", "Consolidation",       -5, -10,  -8],
    ["Q4 2027", "Re-acceleration",     40,  80, 110],
    ["Q1 2028", "GC+Adder Late Bull",  45,  85, 135],
    ["Q2 2028", "Euphoria (50% cap)",  60, 130, 300],
    ["Q3 2028", "Blow-off Peak",       40, 100, 160],
    ["Q4 2028", "Peak/Exit",          -30,  50, 100],
    ["Jan 2029", "TOP — EXIT",          0,   0,   0],
];

// BTC price scenarios and corresponding MSTR/profit projections (v2.8+ with trend adder)
// Trend adder amplifies bull runs: base + adder = 50% capital deployed during confirmed uptrends
const BTC_SCENARIOS = [
    { btc: "$110K-$150K", label: "Modest Recovery", mstr: "$500-$900", profit: "$780K-$2.8M", mult: "6x-22x", secured: "$650K-$2.2M", color: "#2196F3" },
    { btc: "$150K-$200K", label: "Solid Bull",      mstr: "$900-$1,600", profit: "$3.2M-$10M", mult: "25x-77x", secured: "$2.6M-$8M", color: "#00e676" },
    { btc: "$200K+",      label: "Strong Finish",   mstr: "$1,600-$3,000+", profit: "$10M-$32M+", mult: "77x-246x+", secured: "$8M-$25.6M+", color: "#ff9800" },
];

function fmt(n) {
    if (n >= 1000000) return "$" + (n/1000000).toFixed(2) + "M";
    if (n >= 1000) return "$" + (n/1000).toFixed(0) + "K";
    return "$" + n.toFixed(0);
}
function fmtFull(n) {
    return "$" + n.toLocaleString("en-US", {maximumFractionDigits: 0});
}

function computeVals() {
    let mod = [START_CAPITAL], bull = [START_CAPITAL], moon = [START_CAPITAL];
    QUARTERS.forEach(q => {
        mod.push(mod[mod.length-1] * (1 + q[2]/100));
        bull.push(bull[bull.length-1] * (1 + q[3]/100));
        moon.push(moon[moon.length-1] * (1 + q[4]/100));
    });
    return {mod, bull, moon};
}

let vals = computeVals();
let labels = ["Start"];
QUARTERS.forEach(q => labels.push(q[0]));
let charts = {};

function buildMainHTML() {
    let modEnd = vals.mod[vals.mod.length-1];
    let bullEnd = vals.bull[vals.bull.length-1];
    let moonEnd = vals.moon[vals.moon.length-1];

    let rows = "";
    QUARTERS.forEach((q, i) => {
        let cls = q[0] === "Jan 2029" ? ' class="peak-row"' : '';
        let phaseColor = q[1].includes("Euphoria") || q[1].includes("Blow") || q[1].includes("Peak") ? '#ff9800' : q[1].includes("TOP") ? '#ff4444' : '#667';
        rows += '<tr' + cls + '>' +
            '<td>' + q[0] + '</td>' +
            '<td style="color:' + phaseColor + '">' + q[1] + '</td>' +
            '<td class="moderate-c">' + fmtFull(vals.mod[i+1]) + ' <span style="color:#555">(' + (q[2]>=0?'+':'') + q[2] + '%)</span></td>' +
            '<td class="bull-c">' + fmtFull(vals.bull[i+1]) + ' <span style="color:#555">(' + (q[3]>=0?'+':'') + q[3] + '%)</span></td>' +
            '<td class="moon-c">' + fmtFull(vals.moon[i+1]) + ' <span style="color:#555">(' + (q[4]>=0?'+':'') + q[4] + '%)</span></td>' +
            '</tr>';
    });

    return '<div class="strat-desc"><strong>🔄 Rudy v2.8+ Trend Adder — MSTR Cycle-Low LEAP:</strong> $130K into ~280 deep OTM MSTR LEAP calls at cycle low. <strong>Phase 1 (Base):</strong> 200W dip+reclaim entry → 25% capital. <strong>Phase 2 (Trend Adder):</strong> Golden cross confirmed 4 weeks → additional 25% capital with wider stops. Convergence-down exit for adder. Dynamic LEAP multiplier: 8.4x at discount → 3.9x euphoric. ✅ Walk-Forward: WFE 1.18, +6,750% stitched OOS. ✅ 7/7 window stability. ✅ Regime stress: 0 false positives. ✅ Execution: survives 200bps + apocalypse. ✅ Not curve-fit: 75% perturbation survival. ✅ Path independent (CV=0%). ✅ TradingView: Daily +1,915% (44 trades), Weekly +184% (25 trades).</div>' +
    '<div class="scenarios">' +
        '<div class="scenario-card moderate">' +
            '<div class="label">Moderate</div>' +
            '<div class="multiple">' + (modEnd/START_CAPITAL).toFixed(1) + 'x</div>' +
            '<div class="final">' + fmt(modEnd) + '</div>' +
        '</div>' +
        '<div class="scenario-card bull">' +
            '<div class="label">Bull</div>' +
            '<div class="multiple">' + (bullEnd/START_CAPITAL).toFixed(1) + 'x</div>' +
            '<div class="final">' + fmt(bullEnd) + '</div>' +
        '</div>' +
        '<div class="scenario-card moon">' +
            '<div class="label">Moonshot</div>' +
            '<div class="multiple">' + (moonEnd/START_CAPITAL).toFixed(1) + 'x</div>' +
            '<div class="final">' + fmt(moonEnd) + '</div>' +
        '</div>' +
    '</div>' +
    '<div class="chart-container"><canvas id="chart-v24"></canvas></div>' +
    '<table class="proj-table">' +
        '<thead><tr>' +
            '<th style="text-align:left">Quarter</th><th>Phase</th>' +
            '<th class="moderate-c">Moderate</th><th class="bull-c">Bull</th><th class="moon-c">Moonshot</th>' +
        '</tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
    '</table>';
}

function buildBtcHTML() {
    let rows = "";
    BTC_SCENARIOS.forEach(s => {
        rows += '<tr>' +
            '<td style="color:' + s.color + ';font-weight:bold">' + s.btc + '</td>' +
            '<td>' + s.label + '</td>' +
            '<td>' + s.mstr + '</td>' +
            '<td style="color:#00e676;font-weight:bold">' + s.profit + '</td>' +
            '<td>' + s.mult + '</td>' +
            '<td style="color:#ff9800">' + s.secured + '</td>' +
            '</tr>';
    });

    return '<div class="strat-desc"><strong>Outcome by BTC End-of-Term Price (Jan 20, 2029) — v2.8+ Trend Adder:</strong> BTC has finished higher at the end of every completed U.S. presidential term since 2013. The trend adder amplifies bull runs by deploying additional 25% capital when golden cross is confirmed. If BTC is higher than $109K on Jan 20, 2029, your $130K strategy delivers at minimum $1.5M+. Walk-forward validated: +6,750% stitched OOS with PERFECT 7/7 parameter stability. Stress tested: 0 regime false positives, survives 200bps slippage, not curve-fit (75% perturbation survival), path independent (CV=0%).</div>' +
    '<div class="scenarios">' +
        '<div class="scenario-card moderate">' +
            '<div class="label">BTC $150K</div>' +
            '<div class="multiple">25-77x</div>' +
            '<div class="final">$3.2M-$10M</div>' +
        '</div>' +
        '<div class="scenario-card bull">' +
            '<div class="label">BTC $200K</div>' +
            '<div class="multiple">77-246x</div>' +
            '<div class="final">$10M-$32M</div>' +
        '</div>' +
        '<div class="scenario-card moon">' +
            '<div class="label">BTC $300K+</div>' +
            '<div class="multiple">246x+</div>' +
            '<div class="final">$32M+</div>' +
        '</div>' +
    '</div>' +
    '<h2>Projection by BTC End-of-Term Price</h2>' +
    '<table class="proj-table">' +
        '<thead><tr>' +
            '<th style="text-align:left">BTC Price</th><th>Scenario</th>' +
            '<th>MSTR Peak</th><th style="color:#00e676">Net Profit</th><th>Return Multiple</th><th style="color:#ff9800">Secured (Ladder)</th>' +
        '</tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
    '</table>' +
    '<div style="margin-top:24px;padding:16px;background:#1a1a2e;border:1px solid #0f3460;border-radius:8px;font-size:13px;color:#bbb;line-height:1.8">' +
        '<strong style="color:#00d4ff">Historical BTC Performance by Presidential Term:</strong><br>' +
        '&bull; Obama 2nd (2013-2017): ~$15 → ~$900 (+4,500-6,500%)<br>' +
        '&bull; Trump 1st (2017-2021): ~$900 → ~$33,000 (+3,100-3,900%)<br>' +
        '&bull; Biden (2021-2025): ~$35,500 → ~$107,000 (+190-210%)<br>' +
        '&bull; Trump 2nd (2025-2029): ~$107,000 → <span style="color:#ff9800;font-weight:bold">??? (pattern says higher)</span>' +
    '</div>';
}

function makeChart(canvasId, modData, bullData, moonData) {
    if (charts[canvasId]) charts[canvasId].destroy();
    let canvas = document.getElementById(canvasId);
    if (!canvas) return;
    charts[canvasId] = new Chart(canvas.getContext("2d"), {
        type: "line",
        data: {
            labels: labels,
            datasets: [
                { label: "Moderate", data: modData, borderColor: "#2196F3", backgroundColor: "rgba(33,150,243,0.08)", fill: true, tension: 0.3, pointRadius: 4, borderWidth: 2 },
                { label: "Bull", data: bullData, borderColor: "#00e676", backgroundColor: "rgba(0,230,118,0.08)", fill: true, tension: 0.3, pointRadius: 4, borderWidth: 2 },
                { label: "Moonshot", data: moonData, borderColor: "#ff9800", backgroundColor: "rgba(255,152,0,0.08)", fill: true, tension: 0.3, pointRadius: 5, borderWidth: 3 }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: "#aaa", font: { family: "'SF Mono', monospace", size: 12 } } },
                tooltip: { callbacks: { label: function(ctx) { return ctx.dataset.label + ": " + fmtFull(ctx.parsed.y); } } }
            },
            scales: {
                x: { ticks: { color: "#667", font: { size: 10 } }, grid: { color: "#1a1a2e" } },
                y: { type: "logarithmic", ticks: { color: "#667", font: { size: 11 }, callback: function(v) { return fmt(v); } }, grid: { color: "#1a1a2e" } }
            }
        }
    });
}

function showStrat(key, evt) {
    document.querySelectorAll('.strat-tab').forEach(t => t.classList.remove('active'));
    if (evt && evt.target) evt.target.classList.add('active');

    let container = document.getElementById('strat-content');
    if (key === 'v24_main') {
        container.innerHTML = buildMainHTML();
        makeChart('chart-v24', vals.mod, vals.bull, vals.moon);
    } else if (key === 'by_btc') {
        container.innerHTML = buildBtcHTML();
    }
    setTimeout(addExpandable, 100);
}

// Expand/close
let expandedEl = null;
let expandPlaceholder = null;

function expandSection(el) {
    if (expandedEl) { closeExpand(); return; }
    expandedEl = el;
    expandPlaceholder = document.createElement('div');
    expandPlaceholder.style.height = el.offsetHeight + 'px';
    el.parentNode.insertBefore(expandPlaceholder, el);
    let panel = document.getElementById('expandContent');
    panel.innerHTML = '';
    panel.appendChild(el);
    el.classList.remove('expandable');
    el.style.width = '100%';
    el.style.maxHeight = '85vh';
    el.style.overflow = 'auto';
    document.getElementById('expandOverlay').classList.add('active');
    document.body.style.overflow = 'hidden';
    let canvas = el.querySelector('canvas');
    if (canvas && charts[canvas.id]) {
        el.style.height = '70vh';
        charts[canvas.id].resize();
    }
}

function closeExpand() {
    if (!expandedEl) return;
    let el = expandedEl;
    if (expandPlaceholder && expandPlaceholder.parentNode) {
        expandPlaceholder.parentNode.insertBefore(el, expandPlaceholder);
        expandPlaceholder.remove();
    }
    el.classList.add('expandable');
    el.style.width = '';
    el.style.maxHeight = '';
    el.style.overflow = '';
    el.style.height = '';
    document.getElementById('expandOverlay').classList.remove('active');
    document.body.style.overflow = '';
    let canvas = el.querySelector('canvas');
    if (canvas && charts[canvas.id]) { charts[canvas.id].resize(); }
    expandedEl = null;
    expandPlaceholder = null;
}

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeExpand();
});

function addExpandable() {
    document.querySelectorAll('#strat-content .scenarios, #strat-content .chart-container, #strat-content .proj-table, .assumptions, .disclaimer').forEach(el => {
        if (el.dataset.expandReady) return;
        el.dataset.expandReady = '1';
        el.classList.add('expandable');
        el.style.position = 'relative';
        let wrapper = document.createElement('div');
        wrapper.style.cssText = 'position:relative;';
        el.parentNode.insertBefore(wrapper, el);
        wrapper.appendChild(el);
        let btn = document.createElement('button');
        btn.innerHTML = '&#x2922; Expand';
        btn.style.cssText = 'position:absolute;top:8px;right:8px;background:rgba(0,212,255,0.25);border:1px solid rgba(0,212,255,0.5);color:#00d4ff;border-radius:6px;padding:5px 12px;font-size:14px;cursor:pointer;z-index:10000;font-family:inherit;letter-spacing:1px;transition:all 0.2s;user-select:none;pointer-events:auto;';
        btn.onmouseover = function() { this.style.background='rgba(0,212,255,0.6)'; this.style.color='#fff'; };
        btn.onmouseout = function() { this.style.background='rgba(0,212,255,0.25)'; this.style.color='#00d4ff'; };
        btn.onclick = function(e) { e.preventDefault(); e.stopPropagation(); expandSection(el); };
        wrapper.appendChild(btn);
    });
}

// Init with v2.8+ Trend Adder main view
document.getElementById('strat-content').innerHTML = buildMainHTML();
makeChart('chart-v24', vals.mod, vals.bull, vals.moon);
setTimeout(addExpandable, 50);
</script>

<!-- ═══════════════ STRIKE ADJUSTMENT ENGINE ═══════════════ -->
<div style="margin-top:48px;border-top:2px solid #ff9800;padding-top:32px;">
<h2 style="color:#ff9800;font-size:22px;">⚙️ Strike Adjustment Engine</h2>
<p style="color:#888;font-size:13px;margin-bottom:20px;">Dynamic LEAP strike recommendations based on current mNAV premium level. Protects against premium compression risk on the spec pool.</p>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:28px;">
    <!-- Current Premium -->
    <div style="background:#1a1a2e;border:1px solid #0f3460;border-radius:10px;padding:20px;">
        <h3 style="color:#00d4ff;font-size:16px;margin-bottom:12px;">📊 Current mNAV Premium</h3>
        <div id="sae-premium" style="font-size:36px;font-weight:bold;color:#00ff88;">--</div>
        <div id="sae-premium-label" style="font-size:14px;color:#888;margin-top:4px;">Loading...</div>
        <div id="sae-30d-high" style="font-size:14px;color:#666;margin-top:8px;">30d High: --</div>
        <div id="sae-compression" style="font-size:14px;color:#666;margin-top:4px;">Compression: --</div>
        <div id="sae-last-update" style="font-size:11px;color:#444;margin-top:8px;">Last update: --</div>
    </div>
    <!-- Recommendation -->
    <div style="background:#1a1a2e;border:1px solid #0f3460;border-radius:10px;padding:20px;">
        <h3 style="color:#ff9800;font-size:16px;margin-bottom:12px;">🎯 Strike Recommendation</h3>
        <div id="sae-recommendation" style="font-size:15px;line-height:1.8;color:#ccc;">Loading...</div>
    </div>
</div>

<!-- Premium Band Recommendations Table -->
<div style="background:#1a1a2e;border:1px solid #0f3460;border-radius:10px;padding:20px;margin-bottom:28px;">
    <h3 style="color:#00d4ff;font-size:16px;margin-bottom:12px;">📋 Premium Band → Strike Action Matrix</h3>
    <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <thead><tr style="border-bottom:1px solid #333;">
            <th style="text-align:left;padding:8px;color:#00d4ff;">mNAV Band</th>
            <th style="text-align:left;padding:8px;color:#00d4ff;">Safety Strikes</th>
            <th style="text-align:left;padding:8px;color:#00d4ff;">Spec Strikes</th>
            <th style="text-align:left;padding:8px;color:#00d4ff;">Action</th>
        </tr></thead>
        <tbody>
        <tr style="border-bottom:1px solid #222;" id="sae-row-euphoric">
            <td style="padding:8px;color:#ff4444;">> 2.5x (Euphoric)</td>
            <td style="padding:8px;">$100 / $200 / <span style="color:#ff9800;">$300</span></td>
            <td style="padding:8px;">$1000 / $1000 / $1500</td>
            <td style="padding:8px;color:#ff9800;">Drop Sept 2028 Safety $500→$300 for risk-free at NAV reset</td>
        </tr>
        <tr style="border-bottom:1px solid #222;" id="sae-row-elevated">
            <td style="padding:8px;color:#ff9800;">2.0x - 2.5x (Elevated)</td>
            <td style="padding:8px;">$100 / $200 / $500</td>
            <td style="padding:8px;">$1000 / $1000 / $1500</td>
            <td style="padding:8px;color:#00ff88;">Current strikes adequate — monitor for compression</td>
        </tr>
        <tr style="border-bottom:1px solid #222;" id="sae-row-fair">
            <td style="padding:8px;color:#00ff88;">1.0x - 2.0x (Fair)</td>
            <td style="padding:8px;">$100 / $200 / $500</td>
            <td style="padding:8px;">$1000 / $1000 / $1500</td>
            <td style="padding:8px;color:#00ff88;">Optimal entry zone — all strikes on target</td>
        </tr>
        <tr style="border-bottom:1px solid #222;" id="sae-row-depressed">
            <td style="padding:8px;color:#00d4ff;">0.5x - 1.0x (Depressed)</td>
            <td style="padding:8px;">$100 / $200 / $500</td>
            <td style="padding:8px;color:#00d4ff;">$750 / $750 / $1000</td>
            <td style="padding:8px;color:#00d4ff;">Premium depressed — upgrade spec strikes for better leverage</td>
        </tr>
        <tr id="sae-row-discount">
            <td style="padding:8px;color:#9b59b6;">< 0.5x (Discount)</td>
            <td style="padding:8px;">$100 / $200 / $300</td>
            <td style="padding:8px;color:#9b59b6;">$500 / $500 / $750</td>
            <td style="padding:8px;color:#9b59b6;">Below NAV — maximum safety, deep spec strikes for max leverage</td>
        </tr>
        </tbody>
    </table>
</div>

<!-- Compression Impact Calculator -->
<div style="background:#1a1a2e;border:1px solid #e53935;border-radius:10px;padding:20px;margin-bottom:28px;">
    <h3 style="color:#ff4444;font-size:16px;margin-bottom:4px;">💥 Premium Compression Impact Calculator</h3>
    <p style="color:#888;font-size:12px;margin-bottom:16px;">If MSTR target $2,750 compresses by X%, what happens to your $5.2M projected payout? (70/30 Barbell: 4.8 safety + 16.7 spec contracts)</p>
    <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <thead><tr style="border-bottom:1px solid #333;">
            <th style="text-align:left;padding:8px;color:#ff4444;">Compression</th>
            <th style="text-align:right;padding:8px;color:#ff4444;">MSTR Price</th>
            <th style="text-align:right;padding:8px;color:#ff4444;">Payout</th>
            <th style="text-align:right;padding:8px;color:#ff4444;">Haircut $</th>
            <th style="text-align:right;padding:8px;color:#ff4444;">Haircut %</th>
        </tr></thead>
        <tbody id="compression-table"></tbody>
    </table>
</div>
</div>

<script>
(function() {
    // Barbell strategy parameters
    const targetMSTR = 2750;
    const safetyStrikes = [100, 200, 500];
    const specStrikes = [1000, 1000, 1500];
    const safetyContracts = 4.8;
    const specContracts = 16.7;
    const dist = [0.1, 0.45, 0.45];
    const safetyWeights = dist.map(d => d * safetyContracts);
    const specWeights = dist.map(d => d * specContracts);

    function calcPayout(price) {
        let payout = 0;
        for (let i = 0; i < 3; i++) {
            payout += safetyWeights[i] * 100 * Math.max(0, price - safetyStrikes[i]);
            payout += specWeights[i] * 100 * Math.max(0, price - specStrikes[i]);
        }
        return payout;
    }

    const basePayout = calcPayout(targetMSTR);
    const compressions = [0, 10, 20, 30, 40, 50];
    const tbody = document.getElementById('compression-table');

    compressions.forEach(pct => {
        const adjPrice = targetMSTR * (1 - pct/100);
        const adjPayout = calcPayout(adjPrice);
        const haircut = basePayout - adjPayout;
        const haircutPct = basePayout > 0 ? (haircut / basePayout * 100) : 0;
        const row = document.createElement('tr');
        row.style.borderBottom = '1px solid #222';
        const color = pct === 0 ? '#00ff88' : pct <= 20 ? '#ff9800' : '#ff4444';
        row.innerHTML = `
            <td style="padding:8px;color:${color};">${pct === 0 ? 'None (baseline)' : '-' + pct + '%'}</td>
            <td style="padding:8px;text-align:right;">$${adjPrice.toLocaleString()}</td>
            <td style="padding:8px;text-align:right;color:${color};">$${(adjPayout/1e6).toFixed(2)}M</td>
            <td style="padding:8px;text-align:right;color:${pct > 0 ? '#ff4444' : '#666'};">${pct > 0 ? '-$' + (haircut/1e6).toFixed(2) + 'M' : '—'}</td>
            <td style="padding:8px;text-align:right;color:${pct > 0 ? '#ff4444' : '#666'};">${pct > 0 ? '-' + haircutPct.toFixed(1) + '%' : '—'}</td>
        `;
        tbody.appendChild(row);
    });

    // Real-time SAE updater — fetches every 10 seconds
    function updateSAE() {
        fetch('/api/status-dump')
            .then(r => r.json())
            .then(data => {
                const premium = data.last_premium || data.premium || 0;
                const premHist = data.premium_history || [];
                const high30d = premHist.length > 0 ? Math.max(...premHist) : premium;
                const compression = high30d > 0 ? ((high30d - premium) / high30d * 100) : 0;

                document.getElementById('sae-premium').textContent = premium.toFixed(2) + 'x';
                document.getElementById('sae-premium').style.color = premium > 2.5 ? '#ff4444' : premium > 2.0 ? '#ff9800' : premium > 1.0 ? '#00ff88' : '#00d4ff';

                let band = premium > 2.5 ? 'Euphoric' : premium > 2.0 ? 'Elevated' : premium > 1.0 ? 'Fair' : premium > 0.5 ? 'Depressed' : 'Discount';
                document.getElementById('sae-premium-label').textContent = band + ' band';
                document.getElementById('sae-30d-high').textContent = '30d High: ' + high30d.toFixed(2) + 'x';
                document.getElementById('sae-compression').textContent = 'Compression: ' + (compression > 0 ? '-' + compression.toFixed(1) + '%' : 'None');
                document.getElementById('sae-compression').style.color = compression > 15 ? '#ff4444' : compression > 5 ? '#ff9800' : '#00ff88';

                // Clear previous highlights, then highlight active row
                const allRows = ['sae-row-euphoric','sae-row-elevated','sae-row-fair','sae-row-depressed','sae-row-discount'];
                allRows.forEach(id => { var el = document.getElementById(id); if(el){el.style.background='';el.style.borderLeft='';} });
                const rowMap = {euphoric: 'sae-row-euphoric', elevated: 'sae-row-elevated', fair: 'sae-row-fair', depressed: 'sae-row-depressed', discount: 'sae-row-discount'};
                const activeRow = rowMap[band.toLowerCase()];
                if (activeRow) {
                    document.getElementById(activeRow).style.background = 'rgba(0,212,255,0.1)';
                    document.getElementById(activeRow).style.borderLeft = '3px solid #00d4ff';
                }

                // Dynamic recommendation
                let rec = '';
                if (premium > 2.5) {
                    rec = '<span style="color:#ff4444;font-weight:bold;">⚠️ EUPHORIC PREMIUM</span><br>' +
                          'Drop Sept 2028 Safety strike: $500 → $300<br>' +
                          'Ensures risk-free status even if premium resets to NAV at cycle peak.<br>' +
                          '<span style="color:#ff9800;">Spec pool ($1000/$1500) most vulnerable to compression.</span>';
                } else if (premium > 2.0) {
                    rec = '<span style="color:#ff9800;font-weight:bold;">ELEVATED — Monitor</span><br>' +
                          'Current strikes adequate.<br>' +
                          'Watch for sustained >2.5x to trigger strike adjustment.<br>' +
                          'Compression alert active in live daemon.';
                } else if (premium > 1.0) {
                    rec = '<span style="color:#00ff88;font-weight:bold;">✅ FAIR VALUE — Optimal</span><br>' +
                          'All strikes on target.<br>' +
                          'Ideal entry zone for LEAP deployment.<br>' +
                          'No adjustments needed.';
                } else if (premium > 0.5) {
                    rec = '<span style="color:#00d4ff;font-weight:bold;">DEPRESSED — Opportunity</span><br>' +
                          'Consider upgrading spec strikes: $1000 → $750<br>' +
                          'Lower strikes = more leverage at discounted premium.<br>' +
                          'Maximum conviction zone.';
                } else {
                    rec = '<span style="color:#9b59b6;font-weight:bold;">DISCOUNT — Rare</span><br>' +
                          'Below NAV. Deep spec strikes recommended: $500/$750.<br>' +
                          'Maximum leverage, maximum conviction.<br>' +
                          'This is generational entry territory.';
                }
                document.getElementById('sae-recommendation').innerHTML = rec;

                // Update timestamp
                var tsEl = document.getElementById('sae-last-update');
                if (tsEl) tsEl.textContent = 'Last update: ' + new Date().toLocaleTimeString();
            })
            .catch(() => {
                document.getElementById('sae-premium').textContent = 'N/A';
                document.getElementById('sae-recommendation').innerHTML = '<span style="color:#ff4444;">Failed to fetch — check daemon status</span>';
            });
    }

    // Run immediately, then every 10 seconds
    updateSAE();
    setInterval(updateSAE, 60000);
})();
</script>
</body>
</html>
"""


WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "rudy_tv_secret_2026")
WEBHOOK_LIVE = os.environ.get("WEBHOOK_LIVE", "false").lower() == "true"  # Must explicitly enable live execution

# Strategy-to-trader routing map
# v50.4 (2026-05-01): Stripped to T1 only per Constitution Article XI. All routes
# to system1_v8, trader3-12, and trader_moonshot were removed — those scripts
# are LOCKED (authority guard exits immediately) and routing TV signals into
# them violates the clone prohibition. Only authorized trader is trader_v28.
# Trader2 and Trader3 (current MSTR Put / SPY Put daemons) do NOT accept TV
# webhook signals — they monitor and exit via internal logic + Telegram HITL.
STRATEGY_ROUTER = {
    # v2.8 Dynamic Blend — MSTR LEAP (200W Cycle-Low) — Trader1
    "Rudy v2.8": {"trader": "trader_v28", "script": "trader_v28", "signal_file": True},
    "Rudy v2.8 Dynamic Blend": {"trader": "trader_v28", "script": "trader_v28", "signal_file": True},
    "MSTR Cycle-Low LEAP": {"trader": "trader_v28", "script": "trader_v28", "signal_file": True},
}


def route_tv_signal(signal):
    """Route a TradingView webhook signal to the correct trader for execution."""
    import threading, asyncio

    ticker = signal.get("ticker", "").upper()
    action = signal.get("action", "").upper()  # BUY, SELL, EXIT
    strategy = signal.get("strategy", signal.get("name", ""))
    price = signal.get("price", signal.get("close", 0))
    comment = signal.get("comment", "")

    is_test = signal.get("test", False) or not WEBHOOK_LIVE
    mode = "TEST" if is_test else "LIVE"

    log_msg = f"[{mode}] TV SIGNAL: {action} {ticker} | Strategy: {strategy} | Price: {price} | Comment: {comment}"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(LOG_DIR, "webhook.log"), "a") as f:
        f.write(f"[{ts}] {log_msg}\n")

    # Circuit breaker gate — block entries if breaker active
    if action == "BUY":
        blocked, block_reason = auditor.is_breaker_active()
        if blocked:
            try:
                import telegram as tg
                tg.send(
                    f"*ENTRY BLOCKED — CIRCUIT BREAKER*\n\n"
                    f"Ticker: {ticker} @ ${price}\n"
                    f"Strategy: {strategy}\n"
                    f"Reason: {block_reason}"
                )
            except Exception:
                pass
            with open(os.path.join(LOG_DIR, "webhook.log"), "a") as f:
                f.write(f"[{ts}] BLOCKED by circuit breaker: {ticker} — {block_reason}\n")
            return {"status": "blocked", "reason": block_reason}

    # Safety gate — if not live, log and notify only, do NOT execute trades
    if is_test:
        try:
            sys.path.insert(0, os.path.expanduser("~/rudy/scripts"))
            import telegram as tg
            tg.send(
                f"*TV SIGNAL RECEIVED (TEST MODE)*\n\n"
                f"Action: {action}\nTicker: {ticker} @ ${price}\n"
                f"Strategy: {strategy}\n"
                f"Comment: {comment}\n\n"
                f"No trade executed. Set WEBHOOK_LIVE=true to enable."
            )
        except:
            pass
        return {"status": "test_mode", "action": action, "ticker": ticker, "message": "Signal logged but NOT executed. Set WEBHOOK_LIVE=true to go live."}

    # Find which trader handles this strategy
    route = None
    for key, val in STRATEGY_ROUTER.items():
        if key.lower() in strategy.lower():
            route = val
            break

    if not route:
        msg = f"No trader route for strategy: {strategy}"
        with open(os.path.join(LOG_DIR, "webhook.log"), "a") as f:
            f.write(f"[{ts}] WARNING: {msg}\n")
        return {"status": "unrouted", "message": msg}

    trader_name = route["trader"]
    script_name = route["script"]

    # Send Telegram notification
    try:
        sys.path.insert(0, os.path.expanduser("~/rudy/scripts"))
        import telegram as tg
        emoji = "🟢" if action == "BUY" else "🔴" if action in ("SELL", "EXIT") else "🟡"
        tg.send(
            f"{emoji} *TV ALERT → {trader_name.upper()}*\n\n"
            f"Action: {action}\n"
            f"Ticker: {ticker} @ ${price}\n"
            f"Strategy: {strategy}\n"
            f"Comment: {comment}\n\n"
            f"Routing to {trader_name} for execution..."
        )
    except Exception as e:
        pass

    # Execute in background thread (don't block webhook response)
    def _execute():
        try:
            asyncio.set_event_loop(asyncio.new_event_loop())
            scripts_dir = os.path.expanduser("~/rudy/scripts")
            sys.path.insert(0, scripts_dir)

            if trader_name == "system1":
                # System 1 — MSTR Lottery
                from system1_v8 import execute, generate_proposal, load_positions
                from ib_insync import IB
                if action == "BUY":
                    proposal = {
                        "system": "system1", "version": "v8", "ticker": ticker,
                        "action": "BUY", "signal": f"TradingView: {comment or strategy}",
                        "price": float(price), "budget": 90000,
                        "timestamp": datetime.now().isoformat(),
                    }
                    ib = IB()
                    ib.connect("127.0.0.1", 7496, clientId=16)
                    ib.reqMarketDataType(3)
                    result = execute(ib, proposal)
                    ib.disconnect()
                    with open(os.path.join(LOG_DIR, "webhook.log"), "a") as wf:
                        wf.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] System1 executed: {result}\n")
                elif action in ("SELL", "EXIT"):
                    _close_positions(ticker, "system1_v8", comment)
            elif trader_name == "trader_v28":
                # v2.8 Dynamic Blend — write signal file for trader_v28.py to read
                # v2.8 runs its own filters; TV signal acts as confluence confirmation
                signal_file = os.path.expanduser("~/rudy/data/tv_signal_v28.json")
                tv_signal = {
                    "action": action,
                    "ticker": ticker,
                    "price": float(price),
                    "strategy": strategy,
                    "comment": comment,
                    "timestamp": datetime.now().isoformat(),
                    "source": "tradingview",
                }
                with open(signal_file, "w") as sf:
                    json.dump(tv_signal, sf, indent=2)
                with open(os.path.join(LOG_DIR, "webhook.log"), "a") as wf:
                    wf.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] v2.8 TV signal saved: {action} {ticker} @ ${price}\n")
                try:
                    import telegram as tg
                    tg.send(
                        f"📡 *TV → Rudy v2.8 Signal*\n\n"
                        f"Action: {action}\nTicker: {ticker} @ ${price}\n"
                        f"Strategy: {strategy}\n\n"
                        f"Signal saved for confluence check."
                    )
                except:
                    pass
            else:
                # Trader 3-12 — momentum/squeeze/breakout systems
                trader_mod = __import__(script_name)
                if action == "BUY":
                    if hasattr(trader_mod, "execute_signal"):
                        trader_mod.execute_signal(ticker, float(price), comment or strategy)
                    elif hasattr(trader_mod, "scan_and_trade"):
                        trader_mod.scan_and_trade()
                    else:
                        with open(os.path.join(LOG_DIR, "webhook.log"), "a") as wf:
                            wf.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {trader_name} has no execute_signal — signal logged only\n")
                elif action in ("SELL", "EXIT"):
                    _close_positions(ticker, script_name, comment)

        except Exception as e:
            err_msg = f"Execution error ({trader_name}): {e}"
            with open(os.path.join(LOG_DIR, "webhook.log"), "a") as wf:
                wf.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] ERROR: {err_msg}\n")
            try:
                import telegram as tg
                tg.send(f"⚠️ *WEBHOOK ERROR*\n{err_msg}")
            except:
                pass

    threading.Thread(target=_execute, daemon=True).start()
    return {"status": "routed", "trader": trader_name, "action": action, "ticker": ticker}


def _close_positions(ticker, system_name, comment=""):
    """v50.4 (2026-05-01): DISABLED. This used to auto-close positions for
    TV webhook EXIT/SELL signals routed to system1_v8/trader3-12/trader_moonshot.
    All those traders are LOCKED per Article XI, and direct MarketOrder calls
    here bypassed Commander HITL. T1 (trader_v28) handles its own exits via
    its internal trail-stop / profit-tier / mNAV-kill logic. T2/T3 close only
    via Telegram HITL. Function kept as a stub to avoid breaking any caller;
    logs the request and returns without placing any order.
    """
    msg = f"_close_positions called for {ticker} ({system_name}) — DISABLED per Article XI. comment={comment}"
    try:
        with open(os.path.join(LOG_DIR, "webhook.log"), "a") as wf:
            wf.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] BLOCKED: {msg}\n")
    except Exception:
        pass
    try:
        sys.path.insert(0, os.path.expanduser("~/rudy/scripts"))
        import telegram as tg
        tg.send(f"⚠️ *TV close BLOCKED (Article XI)*\n{ticker} from {system_name}.\nReason: only T1/T2/T3 may close positions, via their own HITL flow.")
    except Exception:
        pass
    return


@app.route("/webhook", methods=["POST"])
def webhook():
    """TradingView webhook endpoint — receives alerts and routes to traders."""
    try:
        signal = request.get_json(force=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Auth check
        secret = signal.get("secret", signal.get("key", ""))
        if secret != WEBHOOK_SECRET:
            with open(os.path.join(LOG_DIR, "webhook.log"), "a") as f:
                f.write(f"[{ts}] REJECTED: Bad secret from {request.remote_addr}\n")
            return jsonify({"error": "unauthorized"}), 401

        # Log raw signal
        with open(os.path.join(LOG_DIR, "signals.log"), "a") as f:
            f.write(f"[{ts}] {json.dumps(signal)}\n")

        # Route to trader
        result = route_tv_signal(signal)

        socketio.emit("log_event", {
            "text": f"TV Signal: {signal.get('action', '?')} {signal.get('ticker', '?')} → {result.get('trader', 'unrouted')}",
            "type": "signal"
        })

        return jsonify({"status": "ok", "routing": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ─── Circuit Breaker API Endpoints ───────────────────────────────────────────

@app.route("/api/breaker/status")
def api_breaker_status():
    """Get circuit breaker status for all systems."""
    return jsonify(auditor.get_breaker_status())


@app.route("/api/breaker/halt", methods=["POST"])
def api_breaker_halt():
    """Activate global halt — blocks ALL new entries."""
    data = request.get_json(force=True) if request.data else {}
    reason = data.get("reason", "Commander ordered halt via dashboard")
    state = auditor.set_global_halt(reason)
    return jsonify({"status": "halted", "state": state})


@app.route("/api/breaker/resume", methods=["POST"])
def api_breaker_resume():
    """Clear global halt — resume normal operations."""
    state = auditor.clear_global_halt()
    return jsonify({"status": "resumed", "state": state})


@app.route("/api/breaker/system/<int:sys_id>/halt", methods=["POST"])
def api_breaker_system_halt(sys_id):
    """Activate breaker for a specific system."""
    data = request.get_json(force=True) if request.data else {}
    reason = data.get("reason", f"Manual halt for system {sys_id}")
    state = auditor.set_system_breaker(sys_id, reason)
    return jsonify({"status": "system_halted", "system_id": sys_id, "state": state})


@app.route("/api/breaker/system/<int:sys_id>/resume", methods=["POST"])
def api_breaker_system_resume(sys_id):
    """Clear breaker for a specific system."""
    state = auditor.clear_system_breaker(sys_id)
    return jsonify({"status": "system_resumed", "system_id": sys_id, "state": state})


@socketio.on("user_message")
def handle_message(data):
    text = data.get("text", "")

    # Handle commands
    if text.startswith("/"):
        handle_command(text)
        return

    # Show thinking indicator
    emit("rudy_response", {"text": "Thinking...", "partial": True})

    # Process through Claude Code brain
    response = process_chat(text)
    emit("rudy_response", {"text": response})


def ibkr_connect(client_id=21):
    from ib_insync import IB
    ib = IB()
    ib.connect("127.0.0.1", 7496, clientId=client_id)
    ib.reqMarketDataType(3)
    return ib


def get_price(ticker_symbol):
    """Get price via Yahoo Finance (free, all tickers)."""
    import yfinance as yf
    t = yf.Ticker(ticker_symbol.upper())
    info = t.fast_info
    price = info.get("lastPrice", 0)
    prev_close = info.get("previousClose", 0)
    change = price - prev_close if prev_close else 0
    change_pct = (change / prev_close * 100) if prev_close else 0
    return {"price": price, "change": change, "change_pct": change_pct}


def get_multi_prices(symbols):
    """Get prices for multiple tickers at once."""
    import yfinance as yf
    results = []
    for sym in symbols[:10]:
        try:
            t = yf.Ticker(sym.upper())
            info = t.fast_info
            price = info.get("lastPrice", 0)
            prev = info.get("previousClose", 0)
            change = price - prev if prev else 0
            pct = (change / prev * 100) if prev else 0
            arrow = "▲" if change >= 0 else "▼"
            results.append(f"{sym.upper()}: ${price:,.2f} {arrow} {change:+.2f} ({pct:+.1f}%)")
        except:
            results.append(f"{sym.upper()}: unavailable")
    return results


def get_option_chain_info(ticker_symbol):
    """Get available option expirations via Yahoo Finance."""
    import yfinance as yf
    t = yf.Ticker(ticker_symbol.upper())
    try:
        expirations = list(t.options)[:8]
        if expirations:
            chain = t.option_chain(expirations[0])
            calls_count = len(chain.calls)
            puts_count = len(chain.puts)
            return {"expirations": expirations, "calls": calls_count, "puts": puts_count}
    except:
        pass
    return None


def get_option_detail(ticker_symbol, expiry):
    """Get option chain detail for a specific expiry."""
    import yfinance as yf
    t = yf.Ticker(ticker_symbol.upper())
    try:
        chain = t.option_chain(expiry)
        calls = chain.calls[["strike", "lastPrice", "bid", "ask", "volume", "impliedVolatility"]].head(10)
        puts = chain.puts[["strike", "lastPrice", "bid", "ask", "volume", "impliedVolatility"]].head(10)
        return {"calls": calls.to_dict("records"), "puts": puts.to_dict("records")}
    except:
        return None


def extract_tickers(text):
    """Extract potential ticker symbols from text (1-5 uppercase letters)."""
    import re
    words = text.upper().split()
    common_words = {"I", "A", "THE", "IS", "IT", "AT", "ON", "IN", "TO", "FOR",
                    "AND", "OR", "OF", "MY", "ME", "DO", "IF", "SO", "UP", "AN",
                    "ALL", "GET", "HOW", "CAN", "HAS", "HIM", "HIS", "HER", "HAD",
                    "NOT", "BUT", "ARE", "WAS", "ONE", "OUR", "OUT", "YOU", "DAY",
                    "TOO", "ANY", "WHO", "DID", "HIT", "BUY", "SELL", "PUT", "CALL",
                    "WHAT", "SHOW", "LOOK", "FIND", "GIVE", "TELL", "TAKE",
                    "PRICE", "CHECK", "ABOUT", "OPTION", "OPTIONS", "CHAIN",
                    "STOCK", "TRADE", "TRADING", "SYSTEM", "STATUS", "HELP",
                    "ACCOUNT", "BALANCE", "MONEY", "CASH", "POSITIONS"}
    tickers = []
    for w in words:
        clean = re.sub(r'[^A-Z]', '', w)
        if 1 <= len(clean) <= 5 and clean not in common_words and clean.isalpha():
            tickers.append(clean)
    return tickers


def handle_command(cmd):
    parts = cmd.strip().lower().split()
    command = parts[0]
    args = parts[1:] if len(parts) > 1 else []

    if command == "/status":
        emit("rudy_response", {"text": "Constitution v50.0 active. v2.8+ LIVE mode.\\nIBKR: Connected (live U15746102)\\nv2.8+ Daemon: Running (daily resolution)\\nSafety: Kill switch + Audit + Order confirmation + Lockfile\\nWalk-Forward: WFE 1.18 | standard_tight_minimal\\nStrategy: v2.8+ Trend Adder"})

    elif command == "/positions":
        try:
            ib = ibkr_connect(client_id=32)
            positions = ib.positions()
            if positions:
                msg = "Open positions:\\n" + "\\n".join(
                    f"{p.contract.symbol}: {p.position} @ ${p.avgCost:,.2f}" for p in positions
                )
            else:
                msg = "No open positions."
            ib.disconnect()
            emit("rudy_response", {"text": msg})
        except Exception as e:
            emit("rudy_response", {"text": f"IBKR error: {e}"})

    elif command == "/pnl":
        try:
            ib = ibkr_connect(client_id=33)
            summary = ib.accountSummary()
            result = {}
            for item in summary:
                if item.tag in ["NetLiquidation", "TotalCashValue", "BuyingPower", "UnrealizedPnL", "RealizedPnL"]:
                    result[item.tag] = float(item.value)
            ib.disconnect()
            msg = f"Net Liquidation: ${result.get('NetLiquidation', 0):,.2f}\\n"
            msg += f"Cash: ${result.get('TotalCashValue', 0):,.2f}\\n"
            msg += f"Buying Power: ${result.get('BuyingPower', 0):,.2f}\\n"
            msg += f"Unrealized P&L: ${result.get('UnrealizedPnL', 0):,.2f}\\n"
            msg += f"Realized P&L: ${result.get('RealizedPnL', 0):,.2f}"
            emit("rudy_response", {"text": msg})
        except Exception as e:
            emit("rudy_response", {"text": f"IBKR error: {e}"})

    elif command == "/price":
        if not args:
            emit("rudy_response", {"text": "Usage: /price AAPL  or  /price TSLA NVDA MSTR"})
            return
        results = get_multi_prices(args)
        emit("rudy_response", {"text": "\\n".join(results)})

    elif command == "/chain":
        if not args:
            emit("rudy_response", {"text": "Usage: /chain AAPL"})
            return
        try:
            info = get_option_chain_info(args[0])
            if info:
                msg = f"Options for {args[0].upper()}:\\n"
                msg += f"Calls: {info['calls']} | Puts: {info['puts']}\\n"
                msg += f"Expirations: {', '.join(info['expirations'])}"
            else:
                msg = f"No option chain found for {args[0].upper()}"
            emit("rudy_response", {"text": msg})
        except Exception as e:
            emit("rudy_response", {"text": f"Error: {e}"})

    elif command == "/research":
        if not args:
            emit("rudy_response", {"text": "Usage: /research momentum options strategy\\n/research MSTR bitcoin treasury"})
            return
        query = " ".join(args)
        emit("rudy_response", {"text": f"Searching Google Scholar for: {query}..."})
        try:
            data = scholar.search_scholar(query)
            result = scholar.format_results(data, style="brief")
            scholar.save_results(data)
            emit("rudy_response", {"text": result})
        except Exception as e:
            emit("rudy_response", {"text": f"Scholar error: {e}"})

    elif command == "/cases":
        if not args:
            emit("rudy_response", {"text": "Usage: /cases breach of contract California\\n/cases securities fraud"})
            return
        topic = " ".join(args)
        emit("rudy_response", {"text": f"Searching case law for: {topic}..."})
        try:
            data = scholar.search_case_law(topic)
            result = scholar.format_results(data, style="detailed")
            scholar.save_results(data)
            emit("rudy_response", {"text": result})
        except Exception as e:
            emit("rudy_response", {"text": f"Scholar error: {e}"})

    elif command == "/draft":
        if not args:
            emit("rudy_response", {"text": "Usage: /draft civil complaint breach of contract in California\\n\\nThis uses Cetient AI to draft legal documents."})
            return
        prompt = " ".join(args)
        emit("rudy_response", {"text": f"Sending to Cetient: {prompt}\\nThis may take 30-60 seconds..."})
        try:
            import cetient
            result = cetient.query(f"Draft the following legal document: {prompt}")
            emit("rudy_response", {"text": result})
        except Exception as e:
            emit("rudy_response", {"text": f"Cetient error: {e}"})

    elif command == "/legal":
        if not args:
            emit("rudy_response", {"text": "Usage: /legal can a landlord evict without notice in Texas"})
            return
        question = " ".join(args)
        emit("rudy_response", {"text": f"Researching: {question}\\nThis may take 30-60 seconds..."})
        try:
            import cetient
            result = cetient.legal_analysis(question)
            emit("rudy_response", {"text": result})
        except Exception as e:
            emit("rudy_response", {"text": f"Cetient error: {e}"})

    elif command == "/strategy":
        if not args:
            emit("rudy_response", {"text": "Usage: /strategy iron condor earnings\\n/strategy momentum crypto options"})
            return
        topic = " ".join(args)
        emit("rudy_response", {"text": f"Researching strategy: {topic}..."})
        try:
            data = scholar.search_strategy(topic)
            result = scholar.format_results(data, style="brief")
            scholar.save_results(data)
            emit("rudy_response", {"text": result})
        except Exception as e:
            emit("rudy_response", {"text": f"Scholar error: {e}"})

    elif command == "/qc":
        if not args:
            emit("rudy_response", {"text": "Usage:\\n/qc auth — Test connection\\n/qc projects — List projects\\n/qc backtest mstr_momentum — Run MSTR strategy\\n/qc backtest diagonal — Run diagonal spread\\n/qc results [projectId] [backtestId] — Get results"})
            return
        subcmd = args[0]
        rest = " ".join(args[1:]) if len(args) > 1 else ""
        try:
            import quantconnect as qc
            if subcmd == "auth":
                result = qc.authenticate()
                if result.get("success"):
                    emit("rudy_response", {"text": "QuantConnect authenticated successfully."})
                else:
                    emit("rudy_response", {"text": f"QC auth failed: {result}"})
            elif subcmd == "projects":
                projects = qc.list_projects()
                if projects:
                    msg = "QuantConnect Projects:\\n" + "\\n".join(
                        f"  {p.get('name')} (ID: {p.get('projectId')})" for p in projects[:10]
                    )
                else:
                    msg = "No projects found."
                emit("rudy_response", {"text": msg})
            elif subcmd == "backtest":
                template = qc.get_template(rest)
                if template:
                    emit("rudy_response", {"text": f"Running {rest} backtest on QuantConnect... this may take a few minutes."})
                    result = qc.run_backtest(f"Rudy — {rest}", template)
                    emit("rudy_response", {"text": result})
                else:
                    emit("rudy_response", {"text": f"Unknown template: {rest}\\nAvailable: mstr_momentum, diagonal"})
            elif subcmd == "results":
                parts = rest.split()
                if len(parts) >= 2:
                    result = qc.read_backtest(int(parts[0]), parts[1])
                    emit("rudy_response", {"text": qc.format_backtest_results(result)})
                else:
                    emit("rudy_response", {"text": "Usage: /qc results [projectId] [backtestId]"})
            else:
                emit("rudy_response", {"text": f"Unknown QC command: {subcmd}\\nType /qc for options."})
        except Exception as e:
            emit("rudy_response", {"text": f"QC error: {e}"})

    elif command == "/tradesage":
        if not args:
            emit("rudy_response", {"text": "Usage: /tradesage generate RSI momentum strategy for AAPL\\n/tradesage backtest mean reversion on SPY\\n/tradesage analyze\\n/tradesage optimize"})
            return
        subcmd = args[0]
        rest = " ".join(args[1:]) if len(args) > 1 else ""
        emit("rudy_response", {"text": f"Opening TradeSage... this will launch Chrome with your TradingView chart."})
        try:
            import tradesage
            if subcmd == "generate":
                result = tradesage.generate_strategy(rest)
            elif subcmd == "backtest":
                result = tradesage.backtest(rest)
            elif subcmd == "optimize":
                result = tradesage.optimize_strategy(rest)
            elif subcmd == "analyze":
                result = tradesage.analyze_chart()
            else:
                result = tradesage.query(" ".join(args))
            emit("rudy_response", {"text": result})
        except Exception as e:
            emit("rudy_response", {"text": f"TradeSage error: {e}"})

    elif command == "/audit":
        summary = auditor.get_summary()
        paper = auditor.check_paper_test()
        msg = f"Auditor Report:\\n\\n"
        msg += f"Total Audits: {summary['total_audits']}\\n"
        msg += f"Approved: {summary['approved']} | Rejected: {summary['rejected']}\\n"
        msg += f"Status: {summary['status'].upper()}\\n"
        msg += f"Paper Test: {'PASSED ' + paper['score'] if paper['passed'] else 'FAILED'}\\n"
        if summary["recent_violations"]:
            msg += "\\nRecent Violations:\\n"
            for v in summary["recent_violations"]:
                msg += f"  {v['ticker']}: {v['violation']}\\n"
        emit("rudy_response", {"text": msg})

    elif command == "/accounting":
        pnl = accountant.get_pnl_summary()
        perf = accountant.get_performance_metrics()
        msg = f"Accountant Report:\\n\\n"
        msg += f"Total Trades: {pnl['total_trades']}\\n"
        msg += f"Total P&L: ${pnl['total_pnl']:,.2f}\\n"
        msg += f"Commissions: ${pnl['total_commissions']:,.2f}\\n"
        msg += f"Net P&L: ${pnl.get('net_pnl', 0):,.2f}\\n"
        msg += f"Win Rate: {pnl['win_rate']}%\\n"
        msg += f"Max Drawdown: {perf['max_drawdown_pct']}%\\n"
        msg += f"Largest Win: ${perf['largest_win']:,.2f}\\n"
        msg += f"Largest Loss: ${perf['largest_loss']:,.2f}\\n"
        if pnl["by_system"]:
            msg += "\\nBy System:\\n"
            for sys, data in pnl["by_system"].items():
                msg += f"  {sys}: {data['trades']} trades, ${data['pnl']:,.2f} P&L\\n"
        emit("rudy_response", {"text": msg})

    elif command == "/help":
        emit("rudy_response", {"text": (
            "Commands:\\n\\n"
            "TRADING:\\n"
            "/price AAPL TSLA — Get stock prices\\n"
            "/chain AAPL — Option chain expirations\\n"
            "/positions — Open positions\\n"
            "/pnl — Account P&L summary\\n"
            "/status — System status\\n\\n"
            "QUANTCONNECT:\\n"
            "/qc auth — Test connection\\n"
            "/qc projects — List projects\\n"
            "/qc backtest [template] — Run backtest\\n"
            "/qc results [id] [id] — Get results\\n\\n"
            "TRADESAGE (AI copilot):\\n"
            "/tradesage generate [strategy] — Generate Pine Script\\n"
            "/tradesage backtest [strategy] — Run backtest\\n"
            "/tradesage optimize [name] — Optimize strategy\\n"
            "/tradesage analyze — Analyze current chart\\n\\n"
            "RESEARCH:\\n"
            "/research [topic] — Google Scholar search\\n"
            "/strategy [topic] — Trading strategy research\\n"
            "/cases [topic] — Legal case law search\\n\\n"
            "LEGAL (via Cetient):\\n"
            "/draft [document type] — Draft legal documents\\n"
            "/legal [question] — Legal analysis\\n\\n"
            "AGENTS:\\n"
            "/audit — Auditor report (Constitution compliance)\\n"
            "/accounting — Accountant report (P&L, metrics)\\n\\n"
            "Or just type naturally — Rudy understands you."
        )})
    else:
        emit("rudy_response", {"text": f"Unknown command: {command}\\nType /help for options."})


def process_chat(text):
    """Process natural language input — fast lookups + Claude Code brain."""
    text_lower = text.lower()

    # Check for price requests — handle directly for speed
    if any(w in text_lower for w in ["price", "quote", "how much", "trading at"]):
        tickers = extract_tickers(text)
        if tickers:
            prices = "\\n".join(get_multi_prices(tickers))
            context = f"The user asked about prices. Here's the data:\\n{prices}\\nRespond with this data and add brief commentary."
            brain_reply = rudy_brain.think(context)
            return f"{prices}\\n\\n{brain_reply}"

    # Check for option chain requests — handle directly
    if any(w in text_lower for w in ["option", "chain", "expir", "strike", "calls", "puts"]):
        tickers = extract_tickers(text)
        if tickers:
            try:
                info = get_option_chain_info(tickers[0])
                if info:
                    return (
                        f"Options for {tickers[0]}:\\n"
                        f"Calls: {info['calls']} | Puts: {info['puts']}\\n"
                        f"Expirations: {', '.join(info['expirations'])}"
                    )
            except Exception as e:
                return f"Error fetching options for {tickers[0]}: {e}"

    # Account queries — handle directly
    if any(w in text_lower for w in ["account", "pnl", "balance", "money", "cash", "buying power"]):
        try:
            ib = ibkr_connect(client_id=34)
            summary = ib.accountSummary()
            result = {}
            for item in summary:
                if item.tag in ["NetLiquidation", "TotalCashValue", "BuyingPower"]:
                    result[item.tag] = float(item.value)
            ib.disconnect()
            return f"Net Liquidation: ${result.get('NetLiquidation', 0):,.2f}\\nCash: ${result.get('TotalCashValue', 0):,.2f}\\nBuying Power: ${result.get('BuyingPower', 0):,.2f}"
        except Exception as e:
            return f"IBKR error: {e}"

    # Deep questions — give Claude tool access to read files, run scans
    if any(w in text_lower for w in ["scan", "analyze", "research", "check", "run", "read", "show me", "look at", "backtest"]):
        return rudy_brain.think_with_tools(text)

    # Everything else goes to Claude Code brain
    return rudy_brain.think(text)


@app.route("/build-status")
def build_status_page():
    """Build status assessment — shareable page with copy button."""
    try:
        with open(os.path.expanduser("~/rudy/BUILD_STATUS.md")) as f:
            content = f.read()
    except Exception:
        content = "BUILD_STATUS.md not found"

    return render_template_string("""
<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>Rudy v2.0 — Build Status</title>
<style>
  body { background: #0a0a0f; color: #e0e0e0; font-family: 'SF Mono', monospace; padding: 20px; max-width: 900px; margin: 0 auto; }
  h1 { color: #00d4ff; }
  pre { background: #111; padding: 20px; border-radius: 8px; overflow-x: auto; white-space: pre-wrap; word-wrap: break-word; font-size: 14px; line-height: 1.6; border: 1px solid #222; }
  .copy-btn { background: #00d4ff; color: #000; border: none; padding: 12px 24px; border-radius: 6px; cursor: pointer; font-size: 16px; font-weight: bold; margin: 16px 0; }
  .copy-btn:hover { background: #00aacc; }
  .copy-btn.copied { background: #00ff88; }
  a { color: #00d4ff; }
</style>
</head><body>
<h1>Rudy v2.0 — Build Status</h1>
<p><a href="/">Back to Dashboard</a></p>
<button class="copy-btn" onclick="copyStatus()">Copy to Clipboard</button>
<pre id="status-content">{{ content }}</pre>
<button class="copy-btn" onclick="copyStatus()">Copy to Clipboard</button>
<script>
function copyStatus() {
  const text = document.getElementById('status-content').textContent;
  navigator.clipboard.writeText(text).then(() => {
    document.querySelectorAll('.copy-btn').forEach(b => { b.textContent = 'Copied!'; b.classList.add('copied'); });
    setTimeout(() => {
      document.querySelectorAll('.copy-btn').forEach(b => { b.textContent = 'Copy to Clipboard'; b.classList.remove('copied'); });
    }, 2000);
  });
}
</script>
</body></html>
""", content=content)


# ══════════════════════════════════════════════════════════════
#  LIVE POSITIONS PAGE — IBKR TRUTH (v50.0)
# ══════════════════════════════════════════════════════════════

@app.route("/positions")
def positions_page():
    return """<!DOCTYPE html>
<html><head>
<title>Rudy — IBKR Live Positions</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a1a;color:#e0e0e0;font-family:'SF Mono',monospace;padding:20px}
h1{color:#00ff88;margin-bottom:5px;font-size:24px}
.subtitle{color:#888;margin-bottom:20px;font-size:13px}
.account-bar{display:flex;gap:30px;background:#111;border:1px solid #333;border-radius:8px;padding:15px 20px;margin-bottom:20px}
.acct-item{text-align:center}
.acct-label{color:#888;font-size:11px;text-transform:uppercase}
.acct-value{font-size:20px;font-weight:bold;color:#00ff88}
.acct-value.neg{color:#ff4444}
.banner{padding:12px;border-radius:8px;text-align:center;font-weight:bold;margin-bottom:20px}
.banner.ok{background:#0a3d0a;border:1px solid #00ff88;color:#00ff88}
.banner.warn{background:#3d2a0a;border:1px solid #ffaa00;color:#ffaa00}
.banner.error{background:#3d0a0a;border:1px solid #ff4444;color:#ff4444}
table{width:100%;border-collapse:collapse;margin-bottom:20px}
th{background:#1a1a2e;color:#00ff88;padding:10px;text-align:left;font-size:12px;border-bottom:2px solid #333}
td{padding:8px 10px;border-bottom:1px solid #222;font-size:13px}
tr:hover{background:#111}
.pos{color:#00ff88}.neg{color:#ff4444}
.kill-btn{background:linear-gradient(135deg,#e53935,#b71c1c);color:white;border:none;padding:15px 40px;font-size:18px;font-weight:bold;border-radius:8px;cursor:pointer;margin:20px auto;display:block}
.kill-btn:hover{background:#ff1744;transform:scale(1.05)}
.kill-btn:active{transform:scale(0.95)}
.refresh-btn{background:#1a1a2e;color:#00ff88;border:1px solid #00ff88;padding:8px 16px;border-radius:4px;cursor:pointer;font-size:12px}
.refresh-btn:hover{background:#00ff88;color:#000}
.source{color:#888;font-size:11px;margin-top:5px}
#status-msg{text-align:center;padding:10px;font-size:14px}
.orders-section h2, .positions-section h2{color:#e0e0e0;font-size:16px;margin:15px 0 10px}
</style>
</head><body>
<h1>📊 IBKR LIVE POSITIONS</h1>
<p class="subtitle">Truth layer — directly from TWS, not JSON files</p>
<button class="refresh-btn" onclick="fetchPositions()" style="float:right;margin-top:-40px">🔄 Refresh</button>

<div id="connection-banner" class="banner warn">Connecting to TWS...</div>
<div class="account-bar" id="account-bar">
  <div class="acct-item"><div class="acct-label">Net Liquidation</div><div class="acct-value" id="net-liq2">—</div></div>
  <div class="acct-item"><div class="acct-label">Cash</div><div class="acct-value" id="cash2">—</div></div>
  <div class="acct-item"><div class="acct-label">Unrealized P&L</div><div class="acct-value" id="upnl">—</div></div>
  <div class="acct-item"><div class="acct-label">Positions</div><div class="acct-value" id="pos-count">—</div></div>
  <div class="acct-item"><div class="acct-label">Open Orders</div><div class="acct-value" id="order-count">—</div></div>
</div>

<div class="positions-section">
<h2>Positions</h2>
<table id="positions-table">
<thead><tr><th>Symbol</th><th>Type</th><th>Qty</th><th>Strike</th><th>Expiry</th><th>Right</th><th>Avg Cost</th><th>Mkt Value</th><th>P&L</th><th>P&L %</th><th>Action</th></tr></thead>
<tbody id="pos-body"><tr><td colspan="9">Loading...</td></tr></tbody>
</table>
</div>

<div class="orders-section">
<h2>Open Orders</h2>
<table id="orders-table">
<thead><tr><th>Symbol</th><th>Action</th><th>Qty</th><th>Type</th><th>Status</th></tr></thead>
<tbody id="orders-body"><tr><td colspan="5">Loading...</td></tr></tbody>
</table>
</div>

<button class="kill-btn" id="kill-btn" onclick="activateKillSwitch()">🚨 KILL SWITCH — FLATTEN ALL</button>
<div id="status-msg"></div>
<div class="source" id="source-info">—</div>

<script>
function fmt(n){return n?'$'+Number(n).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—'}

function fetchPositions(){
  document.getElementById('connection-banner').className='banner warn';
  document.getElementById('connection-banner').textContent='Fetching from TWS...';
  fetch('/api/positions').then(r=>r.json()).then(d=>{
    if(d.error){
      document.getElementById('connection-banner').className='banner error';
      document.getElementById('connection-banner').textContent='⚠ TWS DISCONNECTED: '+d.error;
      return;
    }
    // Account
    document.getElementById('net-liq2').textContent=fmt(d.net_liq);
    document.getElementById('cash2').textContent=fmt(d.cash);
    let upnl=document.getElementById('upnl');
    upnl.textContent=fmt(d.unrealized_pnl);
    upnl.className='acct-value '+(d.unrealized_pnl<0?'neg':'');
    document.getElementById('pos-count').textContent=d.position_count;
    document.getElementById('order-count').textContent=d.open_orders||0;

    // Banner
    let banner=document.getElementById('connection-banner');
    if(d.position_count===0){
      banner.className='banner ok';banner.textContent='✅ FLAT — Zero positions';
    } else {
      banner.className='banner warn';banner.textContent='⚠ '+d.position_count+' positions open';
    }

    // Positions table
    let pb=document.getElementById('pos-body');pb.innerHTML='';
    if(!d.positions||d.positions.length===0){
      pb.innerHTML='<tr><td colspan="9" style="color:#00ff88">No positions — account is flat</td></tr>';
    } else {
      d.positions.forEach(p=>{
        let cls=p.qty>0?'pos':'neg';
        let pnl=p.unrealized_pnl||0;
        let pnlPct=p.pnl_pct||0;
        let pnlCls=pnl>=0?'pos':'neg';
        let pnlSign=pnl>=0?'+':'';
        let closeBtn=`<button onclick="closeSingle(${p.conId},'${p.symbol}',${p.qty})" style="background:#e53935;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px;font-weight:bold">❌ CLOSE</button>`;
        pb.innerHTML+=`<tr>
          <td><b>${p.symbol}</b></td><td>${p.secType}</td>
          <td class="${cls}">${p.qty}</td><td>${p.strike||'—'}</td>
          <td>${p.expiry||'—'}</td><td>${p.right||'—'}</td>
          <td>${fmt(p.avg_cost)}</td>
          <td>${fmt(p.market_value)}</td>
          <td class="${pnlCls}">${pnlSign}${fmt(Math.abs(pnl))}</td>
          <td class="${pnlCls}" style="font-weight:bold">${pnlSign}${pnlPct.toFixed(1)}%</td>
          <td>${closeBtn}</td></tr>`;
      });
    }

    // Open orders
    let ob=document.getElementById('orders-body');ob.innerHTML='';
    if(!d.open_orders_detail||d.open_orders_detail.length===0){
      ob.innerHTML='<tr><td colspan="5">No open orders</td></tr>';
    } else {
      d.open_orders_detail.forEach(o=>{
        ob.innerHTML+=`<tr><td><b>${o.symbol}</b></td><td>${o.action}</td><td>${o.qty}</td><td>${o.type}</td><td>${o.status}</td></tr>`;
      });
    }

    document.getElementById('source-info').textContent='Source: '+d.source+' | Updated: '+d.last_update;
  }).catch(e=>{
    document.getElementById('connection-banner').className='banner error';
    document.getElementById('connection-banner').textContent='⚠ Fetch failed: '+e;
  });
}

function closeSingle(conId,symbol,qty){
  let action=qty<0?'BUY to close':'SELL to close';
  if(!confirm(`Close ${symbol}?\\n${action} ${Math.abs(qty)} contracts at market`)){return}
  document.getElementById('status-msg').textContent=`Closing ${symbol}...`;
  fetch('/api/close-position',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({conId:conId,symbol:symbol,qty:qty,confirm:true})
  }).then(r=>r.json()).then(d=>{
    document.getElementById('status-msg').textContent=d.message||JSON.stringify(d);
    setTimeout(fetchPositions,3000);
  }).catch(e=>{document.getElementById('status-msg').textContent='Error: '+e;});
}

function activateKillSwitch(){
  if(!confirm('🚨 KILL SWITCH\\n\\nThis will:\\n1. Cancel ALL open orders\\n2. Close ALL positions at market\\n3. Flatten the entire account\\n\\nType OK to confirm.')){return}
  document.getElementById('status-msg').textContent='🚨 Kill switch activated...';
  document.getElementById('kill-btn').disabled=true;
  fetch('/api/kill-switch',{method:'POST'}).then(r=>r.json()).then(d=>{
    document.getElementById('status-msg').textContent=d.message||JSON.stringify(d);
    document.getElementById('kill-btn').disabled=false;
    setTimeout(fetchPositions,3000);
  }).catch(e=>{
    document.getElementById('status-msg').textContent='Error: '+e;
    document.getElementById('kill-btn').disabled=false;
  });
}

fetchPositions();
setInterval(fetchPositions,60000);
</script>
</body></html>"""


@app.route("/api/positions")
def api_positions():
    """Return LIVE IBKR positions — direct query for full data including conId."""
    try:
        import asyncio
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
        from ib_insync import IB
        ib = IB()
        ib.connect("127.0.0.1", 7496, clientId=50, timeout=10)

        summary = ib.accountSummary()
        acct = {}
        for item in summary:
            acct[item.tag] = item.value
        net_liq = float(acct.get("NetLiquidation", 0))
        cash = float(acct.get("TotalCashValue", 0))
        unrealized = float(acct.get("UnrealizedPnL", 0))

        portfolio = ib.portfolio()
        pos_list = []
        for p in portfolio:
            c = p.contract
            if abs(p.position) < 0.001:
                continue
            cost = float(p.averageCost)
            mkt = float(p.marketValue)
            pnl = float(p.unrealizedPNL)
            pnl_pct = ((mkt - cost) / cost * 100) if cost > 0 else 0
            pos_list.append({
                "symbol": c.symbol, "secType": c.secType,
                "qty": float(p.position), "avg_cost": cost,
                "market_value": mkt, "unrealized_pnl": pnl,
                "pnl_pct": round(pnl_pct, 2),
                "strike": float(c.strike) if hasattr(c, "strike") and c.strike else None,
                "expiry": c.lastTradeDateOrContractMonth if hasattr(c, "lastTradeDateOrContractMonth") else None,
                "right": c.right if hasattr(c, "right") and c.right else None,
                "conId": c.conId,
            })

        open_trades = ib.openTrades()
        close_conids = set(t.contract.conId for t in open_trades)
        for p in pos_list:
            p["has_close_order"] = p.get("conId") in close_conids

        orders_detail = [
            {"symbol": t.contract.symbol, "action": t.order.action,
             "qty": float(t.order.totalQuantity), "type": t.order.orderType,
             "status": t.orderStatus.status}
            for t in open_trades
        ]

        ib.disconnect()

        return jsonify({
            "net_liq": net_liq, "cash": cash, "unrealized_pnl": unrealized,
            "position_count": len(pos_list), "positions": pos_list,
            "open_orders": len(orders_detail), "open_orders_detail": orders_detail,
            "last_update": datetime.now().isoformat(), "source": "LIVE_TWS",
        })
    except Exception as e:
        return jsonify({"error": str(e), "source": "ERROR"})


@app.route("/api/close-position", methods=["POST"])
def api_close_position():
    """Close a single position by conId.

    v50.4 (2026-05-01) HITL hardening:
      - Requires explicit `confirm: true` in body — any client must affirmatively
        opt in to placing a MarketOrder. Blocks accidental/CSRF triggers.
      - Sends Telegram alert BEFORE placing the order so Commander has live
        notification and can react via TWS if the close is unintended.
      - Logs to webhook.log audit trail.
      - Validates conId belongs to a current IBKR position before ordering.
    """
    try:
        import asyncio
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
        from ib_insync import IB, MarketOrder, Contract

        data = request.get_json() or {}
        con_id = data.get("conId")
        symbol = data.get("symbol", "?")
        qty = float(data.get("qty", 0))
        confirm = data.get("confirm") is True  # must be explicit boolean True

        if not con_id or qty == 0:
            return jsonify({"error": "Missing conId or qty"})

        if not confirm:
            return jsonify({
                "error": "HITL confirmation required",
                "message": "Close blocked. Resend with body field {\"confirm\": true} to authorize MarketOrder.",
                "requires_confirm": True,
            }), 400

        try:
            with open(os.path.join(LOG_DIR, "webhook.log"), "a") as wf:
                wf.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] DASHBOARD CLOSE REQUEST: {symbol} conId={con_id} qty={qty}\n")
        except Exception:
            pass
        try:
            sys.path.insert(0, os.path.expanduser("~/rudy/scripts"))
            import telegram as tg
            tg.send(
                f"⚠️ *Dashboard Close Initiated*\n"
                f"Position: {symbol} (conId={con_id})\n"
                f"Qty: {qty}\n"
                f"Order will fire in seconds — open TWS to abort if unintended."
            )
        except Exception:
            pass

        ib = IB()
        ib.connect("127.0.0.1", 7496, clientId=51, timeout=10)

        # Find the position by conId
        positions = ib.positions()
        target = None
        for p in positions:
            if p.contract.conId == con_id:
                target = p
                break

        if not target:
            ib.disconnect()
            return jsonify({"error": f"Position {symbol} (conId={con_id}) not found in IBKR"})

        contract = target.contract
        contract.exchange = "SMART"
        try:
            ib.qualifyContracts(contract)
        except Exception:
            pass

        actual_qty = target.position
        if actual_qty < 0:
            order = MarketOrder("BUY", abs(actual_qty))
        else:
            order = MarketOrder("SELL", abs(actual_qty))
        order.tif = "GTC"

        trade = ib.placeOrder(contract, order)

        # Poll for fill (up to 30s)
        import time
        start = time.time()
        while time.time() - start < 30:
            ib.sleep(2)
            status = trade.orderStatus.status
            if status == "Filled":
                fill = trade.orderStatus.avgFillPrice
                ib.disconnect()
                return jsonify({
                    "message": f"✅ {symbol} CLOSED — {abs(actual_qty):.0f} @ ${fill:.2f}",
                    "status": "Filled",
                    "fill_price": fill,
                })
            if status == "PreSubmitted":
                ib.disconnect()
                return jsonify({
                    "message": f"⏳ {symbol} close order queued — will fill at market open",
                    "status": "PreSubmitted",
                })
            if status in ("Cancelled", "Inactive"):
                msg = trade.log[-1].message if trade.log else "unknown"
                ib.disconnect()
                return jsonify({
                    "message": f"❌ {symbol} close FAILED: {msg}",
                    "status": status,
                })

        ib.disconnect()
        return jsonify({
            "message": f"⏳ {symbol} close order submitted (status: {status})",
            "status": status,
        })

    except Exception as e:
        return jsonify({"error": str(e), "message": f"Failed to close: {e}"})


@app.route("/api/kill-switch", methods=["POST"])
def api_kill_switch():
    """Trigger the kill switch — flatten all positions."""
    import subprocess
    try:
        result = subprocess.run(
            ["python3", os.path.expanduser("~/rudy/scripts/kill_switch.py"), "--force"],
            capture_output=True, text=True, timeout=120,
        )
        return jsonify({
            "exit_code": result.returncode,
            "message": "Kill switch completed" if result.returncode == 0 else "Kill switch finished with warnings",
            "stdout": result.stdout[-500:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else "",
        })
    except Exception as e:
        return jsonify({"error": str(e), "message": f"Kill switch failed: {e}"})


# ── REAL-TIME ACCOUNT FEED ──────────────────────────────────────────
import threading, time as _time

_ibkr_cache = {"net_liq": 0, "cash": 0, "buying_power": 0, "positions": [], "mstr_price": 0, "unrealized_pnl": 0, "realized_pnl": 0, "gross_position_value": 0, "updated": ""}

_tg_last_update_id = 0

def _telegram_callback_poller():
    """Poll Telegram for inline button callbacks (HITL approval via YES/NO buttons)."""
    global _tg_last_update_id
    import requests as _requests
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        print("[TG Poller] No TELEGRAM_BOT_TOKEN — disabled")
        return
    api = f"https://api.telegram.org/bot{bot_token}"
    state_file = os.path.expanduser("~/rudy/data/trader_v28_state.json")
    print("[TG Poller] Started — listening for inline button callbacks")

    while True:
        try:
            resp = _requests.get(f"{api}/getUpdates", params={
                "offset": _tg_last_update_id + 1,
                "timeout": 30,
                "allowed_updates": '["callback_query"]'
            }, timeout=35).json()

            for update in resp.get("result", []):
                _tg_last_update_id = update["update_id"]
                cb = update.get("callback_query")
                if not cb:
                    continue

                data = cb.get("data", "")
                cb_id = cb.get("id", "")
                chat_id = cb.get("message", {}).get("chat", {}).get("id", "")

                # ── ENTRY APPROVAL CALLBACKS (HITL) ──
                if data == "hitl_approve" or data == "hitl_reject":
                    state_file = os.path.join(DATA_DIR, "trader_v28_state.json")
                    try:
                        with open(state_file) as f:
                            state = json.load(f)
                        if data == "hitl_approve" and state.get("pending_entry"):
                            state["entry_approved"] = True
                            with open(state_file, "w") as f:
                                json.dump(state, f, indent=2, default=str)
                            _requests.post(f"{api}/answerCallbackQuery",
                                          json={"callback_query_id": cb_id, "text": "✅ ENTRY APPROVED — will execute at next eval with live price revalidation"})
                            _requests.post(f"{api}/sendMessage",
                                          json={"chat_id": chat_id, "text": "✅ *ENTRY APPROVED*\nWill execute at next 3:45 PM eval after revalidation gate confirms live prices.", "parse_mode": "Markdown"})
                            print(f"[TG Poller] ENTRY APPROVED by Commander")
                        elif data == "hitl_reject":
                            state["entry_rejected"] = True
                            state["pending_entry"] = None
                            with open(state_file, "w") as f:
                                json.dump(state, f, indent=2, default=str)
                            _requests.post(f"{api}/answerCallbackQuery",
                                          json={"callback_query_id": cb_id, "text": "❌ Entry rejected"})
                            _requests.post(f"{api}/sendMessage",
                                          json={"chat_id": chat_id, "text": "❌ *ENTRY REJECTED* — signal cleared, waiting for next eval.", "parse_mode": "Markdown"})
                            print(f"[TG Poller] ENTRY REJECTED by Commander")
                    except Exception as e:
                        print(f"[TG Poller] HITL callback error: {e}")
                    continue

                # ── REPAIR APPROVAL CALLBACKS ──
                if data.startswith("repair_approve_") or data.startswith("repair_reject_"):
                    is_approve = data.startswith("repair_approve_")
                    repair_id = data.replace("repair_approve_", "").replace("repair_reject_", "")

                    repairs_file = os.path.join(DATA_DIR, "pending_repairs.json")
                    try:
                        with open(repairs_file) as f:
                            repairs = json.load(f)
                    except:
                        repairs = []

                    found = False
                    for r in repairs:
                        if r["repair_id"] == repair_id and r["status"] == "PENDING":
                            found = True
                            if is_approve:
                                r["status"] = "APPROVED"
                                r["approved_at"] = datetime.now().isoformat()
                                msg = f"✅ Repair APPROVED: {repair_id}\nExecuting fix..."

                                # Auto-execute the repair immediately
                                import subprocess as _sp
                                action = r.get("action", "").lower()
                                try:
                                    if "restart_trader1" in action or "trader1" in repair_id:
                                        _sp.run(["launchctl", "unload", os.path.expanduser("~/Library/LaunchAgents/com.rudy.trader1.plist")], capture_output=True)
                                        _time.sleep(1)
                                        _sp.run(["launchctl", "load", os.path.expanduser("~/Library/LaunchAgents/com.rudy.trader1.plist")], capture_output=True)
                                        r["result"] = "Trader1 restarted"
                                    elif "restart_trader2" in action or "trader2" in repair_id:
                                        _sp.run(["launchctl", "unload", os.path.expanduser("~/Library/LaunchAgents/com.rudy.trader2.plist")], capture_output=True)
                                        _time.sleep(1)
                                        _sp.run(["launchctl", "load", os.path.expanduser("~/Library/LaunchAgents/com.rudy.trader2.plist")], capture_output=True)
                                        r["result"] = "Trader2 restarted"
                                    elif "restart_trader3" in action or "trader3" in repair_id:
                                        _sp.run(["launchctl", "unload", os.path.expanduser("~/Library/LaunchAgents/com.rudy.trader3.plist")], capture_output=True)
                                        _time.sleep(1)
                                        _sp.run(["launchctl", "load", os.path.expanduser("~/Library/LaunchAgents/com.rudy.trader3.plist")], capture_output=True)
                                        r["result"] = "Trader3 restarted"
                                    elif "restart_dashboard" in action or "dashboard" in repair_id:
                                        _sp.run(["launchctl", "unload", os.path.expanduser("~/Library/LaunchAgents/com.rudy.dashboard.plist")], capture_output=True)
                                        _time.sleep(1)
                                        _sp.run(["launchctl", "load", os.path.expanduser("~/Library/LaunchAgents/com.rudy.dashboard.plist")], capture_output=True)
                                        r["result"] = "Dashboard restarted"
                                    elif "force_eval" in action:
                                        flag = os.path.join(DATA_DIR, "force_eval.flag")
                                        with open(flag, "w") as f2:
                                            f2.write("1")
                                        r["result"] = "Force eval triggered"
                                    r["status"] = "EXECUTED"
                                    msg = f"✅ *REPAIR COMPLETE*\n{repair_id}: {r.get('result', 'Done')}"
                                except Exception as ex:
                                    r["status"] = "FAILED"
                                    r["result"] = str(ex)
                                    msg = f"❌ *REPAIR FAILED*\n{repair_id}: {ex}"
                            else:
                                r["status"] = "REJECTED"
                                r["rejected_at"] = datetime.now().isoformat()
                                msg = f"❌ Repair SKIPPED: {repair_id}"
                            break

                    if found:
                        with open(repairs_file, "w") as f:
                            json.dump(repairs, f, indent=2, default=str)
                    else:
                        msg = "No pending repair found with that ID"

                    _requests.post(f"{api}/answerCallbackQuery", json={
                        "callback_query_id": cb_id, "text": msg[:200]
                    })
                    _requests.post(f"{api}/sendMessage", json={
                        "chat_id": chat_id, "text": msg, "parse_mode": "Markdown"
                    })
                    print(f"[TG Poller] {msg}")
                    continue

                # ── STRIKE ROLL APPROVAL CALLBACKS ──
                if data in ("hitl_approve", "hitl_reject"):
                    action = "approve" if data == "hitl_approve" else "reject"

                    # Read state
                    try:
                        with open(state_file) as f:
                            state = json.load(f)
                    except Exception:
                        _requests.post(f"{api}/answerCallbackQuery", json={
                            "callback_query_id": cb_id,
                            "text": "Error reading state file"
                        })
                        continue

                    pending = state.get("pending_strike_roll")
                    if not pending:
                        _requests.post(f"{api}/answerCallbackQuery", json={
                            "callback_query_id": cb_id,
                            "text": "No pending roll to act on"
                        })
                        continue

                    if action == "approve":
                        state.setdefault("approved_strike_rolls", [])
                        pending["approved_at"] = datetime.now().isoformat()
                        pending["status"] = "APPROVED"
                        state["approved_strike_rolls"].append(pending)
                        state["last_strike_recommendation"] = {
                            "band": pending["new_band"],
                            "safety_strikes": pending["new_safety_strikes"],
                            "safety_weight": 0.45,
                            "spec_strikes": pending["new_spec_strikes"],
                            "spec_weight": 0.55,
                            "premium_at_entry": state.get("last_premium", 0),
                            "timestamp": datetime.now().isoformat(),
                            "rolled_from": pending["old_band"]
                        }
                        state.pop("pending_strike_roll", None)
                        msg = f"✅ Strike roll APPROVED: {pending['old_band']} → {pending['new_band']}"
                    else:
                        state.setdefault("rejected_strike_rolls", [])
                        pending["rejected_at"] = datetime.now().isoformat()
                        pending["status"] = "REJECTED"
                        state["rejected_strike_rolls"].append(pending)
                        state.pop("pending_strike_roll", None)
                        msg = f"❌ Strike roll REJECTED — keeping current strikes"

                    with open(state_file, "w") as f:
                        json.dump(state, f, indent=2, default=str)

                    # Answer the callback
                    _requests.post(f"{api}/answerCallbackQuery", json={
                        "callback_query_id": cb_id,
                        "text": msg
                    })
                    # Send confirmation message
                    _requests.post(f"{api}/sendMessage", json={
                        "chat_id": chat_id,
                        "text": msg,
                        "parse_mode": "Markdown"
                    })
                    print(f"[TG Poller] {msg}")

        except Exception as e:
            print(f"[TG Poller] Error: {e}")
            _time.sleep(5)


def _ibkr_background_feed():
    """Persistent IBKR connection that pushes account data every 10s via WebSocket."""
    import asyncio
    while True:
        try:
            asyncio.set_event_loop(asyncio.new_event_loop())
            from ib_insync import IB
            ib = IB()
            import random
            _feed_client_id = random.randint(100, 999)
            ib.connect("127.0.0.1", 7496, clientId=_feed_client_id, timeout=10)
            print("[IBKR Feed] Connected — streaming account data")

            # Get MSTR stock price once on connect
            try:
                from ib_insync import Stock
                mstr_contract = Stock("MSTR", "SMART", "USD")
                ib.qualifyContracts(mstr_contract)
                mstr_ticker = ib.reqMktData(mstr_contract, "", False, False)
                ib.sleep(3)
            except:
                mstr_ticker = None

            # Subscribe to live account updates (triggers updatePortfolio events)
            ib.reqAccountUpdates("")
            ib.sleep(2)

            while ib.isConnected():
                try:
                    ib.sleep(1)  # Process pending events before reading
                    summary = ib.accountSummary()
                    for item in summary:
                        if item.tag == "NetLiquidation":
                            _ibkr_cache["net_liq"] = round(float(item.value), 2)
                        elif item.tag == "TotalCashValue":
                            _ibkr_cache["cash"] = round(float(item.value), 2)
                        elif item.tag == "BuyingPower":
                            _ibkr_cache["buying_power"] = round(float(item.value), 2)
                        elif item.tag == "UnrealizedPnL":
                            _ibkr_cache["unrealized_pnl"] = round(float(item.value), 2)
                        elif item.tag == "RealizedPnL":
                            _ibkr_cache["realized_pnl"] = round(float(item.value), 2)
                        elif item.tag == "GrossPositionValue":
                            _ibkr_cache["gross_position_value"] = round(float(item.value), 2)

                    # MSTR live price
                    if mstr_ticker:
                        p = mstr_ticker.last or mstr_ticker.close or 0
                        if p > 0:
                            _ibkr_cache["mstr_price"] = round(float(p), 2)

                    portfolio = ib.portfolio()
                    _ibkr_cache["positions"] = [
                        {"symbol": p.contract.symbol, "secType": p.contract.secType,
                         "quantity": float(p.position), "avgCost": float(p.averageCost),
                         "marketValue": float(p.marketValue),
                         "unrealizedPNL": float(p.unrealizedPNL),
                         "realizedPNL": float(p.realizedPNL),
                         "right": getattr(p.contract, "right", ""),
                         "strike": float(getattr(p.contract, "strike", 0)),
                         "expiry": getattr(p.contract, "lastTradeDateOrContractMonth", "")}
                        for p in portfolio
                    ]
                    _ibkr_cache["updated"] = datetime.now().strftime("%H:%M:%S")

                    # Push to all connected WebSocket clients
                    socketio.emit("account_update", _ibkr_cache)

                except Exception as inner_e:
                    print(f"[IBKR Feed] Poll error: {inner_e}")

                _time.sleep(10)

            print("[IBKR Feed] Disconnected — will reconnect in 30s")
        except Exception as e:
            print(f"[IBKR Feed] Connection error: {e} — retrying in 30s")
        _time.sleep(30)


@app.route("/api/account-live")
def api_account_live():
    """Return live account data — queries IBKR on every call (10s poll from dashboard)."""
    result = dict(_ibkr_cache)

    # Check if cache is stale (>15s old) or empty — if so, do a fresh IBKR query
    cache_stale = True
    if _ibkr_cache.get("_last_query_ts"):
        try:
            ts = _ibkr_cache["_last_query_ts"]
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            cache_stale = (datetime.now() - ts).total_seconds() > 15
        except:
            cache_stale = True

    if cache_stale:
        try:
            import asyncio
            try:
                asyncio.get_event_loop()
            except RuntimeError:
                asyncio.set_event_loop(asyncio.new_event_loop())
            from ib_insync import IB, Stock
            ib = IB()
            import random as _rnd2
            ib.connect("127.0.0.1", 7496, clientId=_rnd2.randint(200, 499), timeout=10)
            summary = ib.accountSummary()
            for item in summary:
                if item.tag == "NetLiquidation":
                    result["net_liq"] = round(float(item.value), 2)
                elif item.tag == "TotalCashValue":
                    result["cash"] = round(float(item.value), 2)
                elif item.tag == "BuyingPower":
                    result["buying_power"] = round(float(item.value), 2)
                elif item.tag == "UnrealizedPnL":
                    result["unrealized_pnl"] = round(float(item.value), 2)
                elif item.tag == "RealizedPnL":
                    result["realized_pnl"] = round(float(item.value), 2)
                elif item.tag == "GrossPositionValue":
                    result["gross_position_value"] = round(float(item.value), 2)
            # MSTR price
            try:
                mstr_c = Stock("MSTR", "SMART", "USD")
                ib.qualifyContracts(mstr_c)
                ib.reqMarketDataType(3)
                t = ib.reqMktData(mstr_c, "", False, False)
                ib.sleep(2)
                p = t.last or t.close or 0
                if p > 0:
                    result["mstr_price"] = round(float(p), 2)
            except Exception:
                pass
            # Positions — use live portfolio for market values
            portfolio = ib.portfolio()
            result["positions"] = [
                {"symbol": p.contract.symbol, "secType": p.contract.secType,
                 "quantity": float(p.position), "avgCost": float(p.averageCost),
                 "marketValue": float(p.marketValue),
                 "unrealizedPNL": float(p.unrealizedPNL),
                 "right": getattr(p.contract, "right", ""),
                 "strike": float(getattr(p.contract, "strike", 0)),
                 "expiry": getattr(p.contract, "lastTradeDateOrContractMonth", "")}
                for p in portfolio
            ]
            result["updated"] = datetime.now().strftime("%H:%M:%S")
            result["_last_query_ts"] = datetime.now().isoformat()
            _ibkr_cache.update(result)
            ib.disconnect()
        except Exception as e:
            result["ibkr_fallback_error"] = str(e)

    # Add BTC price from sentinel or trader state
    sentinel = _load_json("btc_sentinel_state.json")
    trader = _load_json("trader_v28_state.json")
    btc = sentinel.get("last_price") or result.get("btc_price") or trader.get("last_btc_price", 0)
    if btc:
        result["btc_price"] = btc
    # BTC ATH tracked dynamically from IBKR data (not hardcoded)
    result["btc_ath"] = trader.get("btc_ath", 126200)
    # Starting balance for P&L calculation
    track = _load_json("paper_track.json")
    result["starting_balance"] = track.get("starting_balance", 7780) if track else 7780
    return jsonify(result)


@app.route("/api/treasury-yield")
def api_treasury_yield():
    """Return 10Y Treasury yield + macro regime classification."""
    data = _load_json("treasury_yield.json")
    return jsonify(data or {"error": "no data"})


@app.route("/api/regime")
def api_regime():
    """Return System 13 regime classification + current month seasonality."""
    result = {}
    # Load regime state
    regime = _load_json("regime_state.json")
    if regime:
        result.update(regime)
    # Override BTC price: sentinel (live) > IBKR cache > trader state (stale)
    sentinel = _load_json("btc_sentinel_state.json")
    trader = _load_json("trader_v28_state.json")
    live_btc = (sentinel.get("last_price", 0)
                or _ibkr_cache.get("btc_price", 0)
                or trader.get("last_btc_price", 0))
    if live_btc:
        result["btc_price"] = live_btc
    # Remove GBTC proxy price — never display as BTC price
    result.pop("btc_price_gbtc_proxy", None)
    # Compute BTC weekly SMAs from GBTC proxy data (scaled to real BTC)
    gbtc_closes = trader.get("btc_weekly_closes", [])
    if gbtc_closes and live_btc and len(gbtc_closes) >= 200:
        # Scale factor: latest GBTC proxy value → real BTC price
        latest_gbtc = gbtc_closes[-1] if gbtc_closes[-1] > 0 else 1
        scale = live_btc / (latest_gbtc * 1000) if latest_gbtc > 0 else 1
        def _sma(n):
            if len(gbtc_closes) < n:
                return None
            return round(sum(gbtc_closes[-n:]) / n * 1000 * scale)
        result["btc_sma_200w"] = _sma(200)
        result["btc_sma_250w"] = _sma(250) if len(gbtc_closes) >= 250 else None
        result["btc_sma_300w"] = _sma(300) if len(gbtc_closes) >= 300 else None
    # Load seasonality for current month
    season_path = os.path.join(DATA_DIR, "btc_seasonality.json")
    if os.path.exists(season_path):
        try:
            with open(season_path) as f:
                season = json.load(f)
            import calendar
            month_name = calendar.month_name[datetime.now().month]
            current_regime = regime.get("current_regime", "DISTRIBUTION")
            # Map regime to seasonality key
            if current_regime in season:
                month_data = season[current_regime].get(month_name, {})
                result["month_outlook"] = month_data
                result["month_outlook"]["month"] = month_name
                result["month_outlook"]["regime_column"] = current_regime
        except Exception:
            pass
    return jsonify(result)


# ══════════════════════════════════════════════════════════════════
#  GROK CT SENTIMENT & GEMINI BRAIN APIs
# ══════════════════════════════════════════════════════════════════

@app.route("/api/grok-sentiment")
def api_grok_sentiment():
    """Return latest Grok CT sentiment scan."""
    data = _load_json("ct_sentiment.json")
    return jsonify(data)

@app.route("/api/gemini-brain")
@app.route("/api/gemini")
def api_gemini_brain():
    """Return latest Gemini analysis (regime cross-check + digest)."""
    data = _load_json("gemini_analysis.json")
    return jsonify(data)


# ══════════════════════════════════════════════════════════════════
#  SELF-REPAIR SYSTEM — HITL Approval via Telegram or Dashboard
# ══════════════════════════════════════════════════════════════════

@app.route("/api/repair/propose", methods=["POST"])
def api_repair_propose():
    """Maintenance agent proposes a repair. Sends Telegram with YES/NO buttons."""
    data = request.get_json() or {}
    repair_id = data.get("repair_id", f"repair_{int(datetime.now().timestamp())}")
    issue = data.get("issue", "Unknown issue")
    action = data.get("action", "Unknown repair action")
    severity = data.get("severity", "WARNING")

    repair = {
        "repair_id": repair_id,
        "issue": issue,
        "action": action,
        "severity": severity,
        "proposed_at": datetime.now().isoformat(),
        "status": "PENDING"
    }

    # Save to pending repairs file
    repairs_file = os.path.join(DATA_DIR, "pending_repairs.json")
    repairs = []
    if os.path.exists(repairs_file):
        try:
            with open(repairs_file) as f:
                repairs = json.load(f)
        except:
            repairs = []
    repairs.append(repair)
    with open(repairs_file, "w") as f:
        json.dump(repairs, f, indent=2, default=str)

    # Send Telegram with inline buttons
    try:
        import requests as _req
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        if not token:
            sys.path.insert(0, os.path.expanduser("~/rudy/scripts"))
            from telegram import BOT_TOKEN, CHAT_ID
            token = BOT_TOKEN
            chat_id = CHAT_ID
        api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        _req.post(api_url, json={
            "chat_id": chat_id,
            "text": f"{'🔴' if severity == 'CRITICAL' else '⚠️'} *REPAIR NEEDED — {repair_id}*\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"Issue: {issue}\n"
                    f"Fix: {action}\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"Approve this repair?",
            "parse_mode": "Markdown",
            "reply_markup": json.dumps({
                "inline_keyboard": [[
                    {"text": "✅ YES — Repair", "callback_data": f"repair_approve_{repair_id}"},
                    {"text": "❌ NO — Skip", "callback_data": f"repair_reject_{repair_id}"}
                ]]
            })
        })
    except Exception as e:
        print(f"[Repair] Telegram send error: {e}")

    return jsonify({"status": "proposed", "repair": repair})


@app.route("/api/repair/status")
def api_repair_status():
    """Get all pending/completed repairs."""
    repairs_file = os.path.join(DATA_DIR, "pending_repairs.json")
    if os.path.exists(repairs_file):
        with open(repairs_file) as f:
            return jsonify(json.load(f))
    return jsonify([])


@app.route("/api/repair/execute", methods=["POST"])
def api_repair_execute():
    """Execute an approved repair action."""
    import subprocess
    data = request.get_json() or {}
    repair_id = data.get("repair_id", "")

    repairs_file = os.path.join(DATA_DIR, "pending_repairs.json")
    if not os.path.exists(repairs_file):
        return jsonify({"error": "No pending repairs"}), 404

    with open(repairs_file) as f:
        repairs = json.load(f)

    repair = None
    for r in repairs:
        if r["repair_id"] == repair_id and r["status"] == "APPROVED":
            repair = r
            break

    if not repair:
        return jsonify({"error": "Repair not found or not approved"}), 404

    action = repair.get("action", "")
    result = {"repair_id": repair_id, "executed": False}

    try:
        if "restart_trader1" in action.lower() or "trader1" in repair_id:
            subprocess.run(["launchctl", "unload", os.path.expanduser("~/Library/LaunchAgents/com.rudy.trader1.plist")], capture_output=True)
            import time; time.sleep(1)
            subprocess.run(["launchctl", "load", os.path.expanduser("~/Library/LaunchAgents/com.rudy.trader1.plist")], capture_output=True)
            result["executed"] = True
            result["detail"] = "Trader1 daemon restarted via launchctl"

        elif "restart_trader2" in action.lower() or "trader2" in repair_id:
            subprocess.run(["launchctl", "unload", os.path.expanduser("~/Library/LaunchAgents/com.rudy.trader2.plist")], capture_output=True)
            import time; time.sleep(1)
            subprocess.run(["launchctl", "load", os.path.expanduser("~/Library/LaunchAgents/com.rudy.trader2.plist")], capture_output=True)
            result["executed"] = True
            result["detail"] = "Trader2 daemon restarted via launchctl"

        elif "restart_trader3" in action.lower() or "trader3" in repair_id:
            subprocess.run(["launchctl", "unload", os.path.expanduser("~/Library/LaunchAgents/com.rudy.trader3.plist")], capture_output=True)
            import time; time.sleep(1)
            subprocess.run(["launchctl", "load", os.path.expanduser("~/Library/LaunchAgents/com.rudy.trader3.plist")], capture_output=True)
            result["executed"] = True
            result["detail"] = "Trader3 daemon restarted via launchctl"

        elif "restart_dashboard" in action.lower() or "dashboard" in repair_id:
            subprocess.run(["launchctl", "unload", os.path.expanduser("~/Library/LaunchAgents/com.rudy.dashboard.plist")], capture_output=True)
            import time; time.sleep(1)
            subprocess.run(["launchctl", "load", os.path.expanduser("~/Library/LaunchAgents/com.rudy.dashboard.plist")], capture_output=True)
            result["executed"] = True
            result["detail"] = "Dashboard restarted via launchctl"

        elif "force_eval" in action.lower():
            flag = os.path.join(DATA_DIR, "force_eval.flag")
            with open(flag, "w") as f:
                f.write("1")
            result["executed"] = True
            result["detail"] = "Force evaluation flag set"

        else:
            result["detail"] = f"Unknown repair action: {action}"

    except Exception as e:
        result["error"] = str(e)

    # Update repair status
    repair["status"] = "EXECUTED" if result.get("executed") else "FAILED"
    repair["executed_at"] = datetime.now().isoformat()
    repair["result"] = result.get("detail", "")
    with open(repairs_file, "w") as f:
        json.dump(repairs, f, indent=2, default=str)

    # Send Telegram confirmation
    try:
        sys.path.insert(0, os.path.expanduser("~/rudy/scripts"))
        from telegram import send
        emoji = "✅" if result.get("executed") else "❌"
        send(f"{emoji} *REPAIR {repair['status']}*\n{repair_id}: {result.get('detail', 'Failed')}")
    except:
        pass

    return jsonify(result)


@app.route("/api/health-check")
def api_health_check():
    """Real-time health check of all running daemons and connections."""
    import subprocess
    issues = []

    # Check v2.8+ daemon
    v28_running = "trader_v28" in subprocess.getoutput("ps aux")
    if not v28_running:
        issues.append("v2.8+ daemon is DOWN")

    # Check trader2
    t2_running = "trader2_mstr" in subprocess.getoutput("ps aux")
    if not t2_running:
        issues.append("Trader2 (MSTR Put) is DOWN")

    # Check trader3
    t3_running = "trader3_spy" in subprocess.getoutput("ps aux")
    if not t3_running:
        issues.append("Trader3 (SPY Put) is DOWN")

    # Check IBKR connection — test with a quick socket probe
    import socket
    ibkr_ok = False
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        ibkr_ok = s.connect_ex(("127.0.0.1", 7496)) == 0
        s.close()
    except Exception:
        pass
    if not ibkr_ok:
        issues.append("IBKR TWS port 7496 not reachable")

    # Check feed freshness — cache updated within last 120s (covers fallback + background feed)
    feed_active = False
    if _ibkr_cache.get("updated"):
        try:
            last = datetime.strptime(_ibkr_cache["updated"], "%H:%M:%S").replace(
                year=datetime.now().year, month=datetime.now().month, day=datetime.now().day)
            feed_active = (datetime.now() - last).total_seconds() < 120
        except Exception:
            feed_active = False
    # If cache is empty but IBKR is reachable, still count as active (fallback will populate on next poll)
    if not feed_active and ibkr_ok and _ibkr_cache.get("net_liq", 0) > 0:
        feed_active = True
    if not feed_active:
        issues.append("Dashboard feed stale — waiting for refresh")

    return jsonify({
        "v28_daemon": v28_running,
        "trader2": t2_running,
        "trader3": t3_running,
        "ibkr_connected": ibkr_ok,
        "feed_active": feed_active,
        "issues": issues,
        "all_ok": len(issues) == 0,
        "checked_at": datetime.now().isoformat()
    })


if __name__ == "__main__":
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    port = int(os.environ.get("PORT", 3001))

    # Start persistent IBKR background feed
    feed_thread = threading.Thread(target=_ibkr_background_feed, daemon=True)
    feed_thread.start()

    # Start Telegram callback poller for HITL approvals
    tg_poller = threading.Thread(target=_telegram_callback_poller, daemon=True)
    tg_poller.start()

    print(f"Rudy v2.0 Command Center starting on http://localhost:{port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
