"""System 2 v5 — Multi-Strategy Engine (Production)
Constitution v50.0 | Any ticker EXCEPT MSTR/IBIT
$250 max risk per trade | $10k capital | $7,500 survival breaker

STRATEGY A: Diagonal Spreads (momentum)
  Signal: EMAs stacked + MACD bullish + RSI 40-65
  Universe: Tech momentum + Energy sector

STRATEGY B: Short Squeeze Detector
  Signal: Gap up >3% + Volume >2x avg + Cross above EMA21
  Universe: High short interest / volatile names

Backtested Results (2020-2025):
  Energy Momentum: $10k → $61.5k (+516%, Sharpe 0.98)
  Short Squeeze:   $10k → $36k  (+261%, 19% DD, Sharpe 0.55)
"""
import os
import sys
import json
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import telegram

import yfinance as yf

LOG_DIR = os.path.expanduser("~/rudy/logs")
POSITIONS_FILE = os.path.expanduser("~/rudy/data/system2_positions.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(os.path.dirname(POSITIONS_FILE), exist_ok=True)

# Constitution v50.0 parameters
CAPITAL = 10000
SURVIVAL_BREAKER = 7500
MAX_RISK_PER_TRADE = 250
MAX_POSITIONS = 2
EXCLUDED = ["MSTR", "IBIT"]

# Universe — top momentum growth stocks + energy sector
UNIVERSE_TECH = ["NVDA", "TSLA", "AMD", "META", "AVGO", "PLTR", "NFLX", "AMZN"]
UNIVERSE_ENERGY = ["CCJ", "UEC", "XOM", "CVX", "OXY", "DVN", "FANG", "VST", "CEG"]
UNIVERSE = UNIVERSE_TECH + UNIVERSE_ENERGY

# Squeeze universe — high short interest / volatile names
SQUEEZE_UNIVERSE = ["GME", "AMC", "TSLA", "NVDA", "AMD", "PLTR", "SOFI", "MARA", "COIN"]

# Entry parameters (same V4 signal logic)
RSI_LOW = 40
RSI_HIGH = 65

# Options parameters
LEAP_MIN_DTE = 180     # 6+ months for LEAP leg
LEAP_MAX_DTE = 545     # ~18 months max
SHORT_MIN_DTE = 21     # 3+ weeks for short leg
SHORT_MAX_DTE = 60     # ~2 months for short leg
LEAP_DELTA_TARGET = 0.70   # Deep ITM LEAP (high delta)
SHORT_DELTA_TARGET = 0.30  # OTM short call (low delta, income)

# Pyramid levels (on option value, not stock price)
PYRAMID_1_GAIN = 0.50   # LEAP up 50% → add 1 more contract
PYRAMID_2_GAIN = 1.00   # LEAP up 100% → add 1 more contract

# Profit take
PROFIT_TAKE_GAIN = 1.50  # LEAP up 150% → close 50%

# Exit
TRAIL_DD_EXIT = 0.40     # 40% drawdown on option value from high
MAX_LOSS_PCT = 0.50      # Exit if LEAP loses 50% of entry value (capped at $250 risk)
EMA50_EXIT = True        # Exit if underlying closes below EMA50


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[S2v4 {ts}] {msg}")
    with open(f"{LOG_DIR}/system2_v4.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def get_technicals(symbol):
    """Get all technical indicators from Yahoo Finance."""
    t = yf.Ticker(symbol)
    data = t.history(period="1y")
    if len(data) < 200:
        return None

    close = data["Close"]
    price = float(close.iloc[-1])

    ema10 = float(close.ewm(span=10).mean().iloc[-1])
    ema21 = float(close.ewm(span=21).mean().iloc[-1])
    ema50 = float(close.ewm(span=50).mean().iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1])

    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = float((100 - (100 / (1 + rs))).iloc[-1])

    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd_line = float((ema12 - ema26).iloc[-1])
    signal_line = float((ema12 - ema26).ewm(span=9).mean().iloc[-1])

    return {
        "price": price,
        "ema10": ema10,
        "ema21": ema21,
        "ema50": ema50,
        "sma200": sma200,
        "rsi": rsi,
        "macd": macd_line,
        "macd_signal": signal_line,
    }


def score_stock(tech):
    """Score a stock by momentum strength."""
    if tech is None:
        return -999
    price = tech["price"]
    sma200 = tech["sma200"]
    macd = tech["macd"]
    signal = tech["macd_signal"]
    momentum = ((price / sma200) - 1) * 100 if sma200 > 0 else 0
    macd_strength = (macd - signal) * 10
    return momentum + macd_strength


def check_entry(symbol):
    """Check if V4 entry conditions are met."""
    if symbol.upper() in EXCLUDED:
        return False, "Excluded (System 1 only)", None

    tech = get_technicals(symbol)
    if tech is None:
        return False, "Insufficient data", None

    p = tech["price"]
    emas_stacked = p > tech["ema10"] > tech["ema21"] > tech["ema50"] > tech["sma200"]
    macd_bullish = tech["macd"] > tech["macd_signal"]
    rsi_sweet = RSI_LOW <= tech["rsi"] <= RSI_HIGH

    if emas_stacked and macd_bullish and rsi_sweet:
        score = score_stock(tech)
        return True, f"EMAs stacked + MACD bull + RSI {tech['rsi']:.1f} | Score {score:.1f}", tech

    reasons = []
    if not emas_stacked:
        reasons.append("EMAs not stacked")
    if not macd_bullish:
        reasons.append("MACD bearish")
    if not rsi_sweet:
        reasons.append(f"RSI {tech['rsi']:.1f} outside {RSI_LOW}-{RSI_HIGH}")

    return False, " | ".join(reasons), tech


def scan_universe():
    """Scan all universe stocks and return ranked entry candidates."""
    candidates = []
    for symbol in UNIVERSE:
        signal, reason, tech = check_entry(symbol)
        if signal:
            score = score_stock(tech)
            candidates.append((symbol, score, reason, tech))
            log(f"SIGNAL: {symbol} — {reason}")
        else:
            log(f"No signal: {symbol} — {reason}")
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates


def generate_proposal(symbol, tech):
    """Generate a diagonal spread proposal for E.M. approval."""
    price = tech["price"]
    score = score_stock(tech)

    # Estimate strike targets
    leap_strike = round(price * 0.85, -1) or round(price * 0.85)  # ~15% ITM for high delta
    short_strike = round(price * 1.10, -1) or round(price * 1.10)  # ~10% OTM for income

    proposal = {
        "system": "system2",
        "version": "v4",
        "type": "diagonal",
        "ticker": symbol,
        "action": "BUY",
        "price": price,
        "score": score,
        "rsi": tech["rsi"],
        "structure": {
            "leap_strike": leap_strike,
            "leap_dte_target": "6-18 months",
            "short_strike": short_strike,
            "short_dte_target": "3-8 weeks",
            "description": f"Buy ${leap_strike}C LEAP + Sell ${short_strike}C monthly",
        },
        "risk": {
            "max_per_trade": MAX_RISK_PER_TRADE,
            "max_loss": "Net debit of diagonal (capped at $250)",
        },
        "rules": {
            "pyramid_1": f"Add 1 contract at +{PYRAMID_1_GAIN:.0%} LEAP value",
            "pyramid_2": f"Add 1 contract at +{PYRAMID_2_GAIN:.0%} LEAP value",
            "profit_take": f"Close 50% at +{PROFIT_TAKE_GAIN:.0%} LEAP value",
            "short_roll": "Roll short call monthly for income",
            "trail_stop": f"Exit if LEAP drops {TRAIL_DD_EXIT:.0%} from peak",
            "trend_exit": "Exit if underlying closes below EMA50",
        },
        "timestamp": datetime.now().isoformat(),
    }

    log(f"PROPOSAL: {symbol} diagonal @ ${price:.2f} | LEAP ${leap_strike}C / Short ${short_strike}C")
    return proposal


def get_squeeze_data(symbol):
    """Get volume, price, and EMA21 for squeeze detection."""
    t = yf.Ticker(symbol)
    data = t.history(period="3mo")
    if len(data) < 25:
        return None

    close = data["Close"]
    volume = data["Volume"]
    price = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])
    today_vol = float(volume.iloc[-1])
    avg_vol_20 = float(volume.rolling(20).mean().iloc[-1])
    ema21 = float(close.ewm(span=21).mean().iloc[-1])
    prev_ema21 = float(close.ewm(span=21).mean().iloc[-2])

    return {
        "price": price,
        "prev_close": prev_close,
        "volume": today_vol,
        "avg_volume_20": avg_vol_20,
        "ema21": ema21,
        "prev_ema21": prev_ema21,
    }


def check_squeeze(symbol):
    """Check if a short squeeze signal is triggered.
    Signal: Gap up >3% + Volume >2x 20-day avg + Price crosses above EMA21
    Backtested: $10k → $36k (+261%), 19% max DD, Sharpe 0.55
    """
    if symbol.upper() in EXCLUDED:
        return False, "Excluded", None

    data = get_squeeze_data(symbol)
    if data is None:
        return False, "Insufficient data", None

    gap_pct = (data["price"] - data["prev_close"]) / data["prev_close"]
    vol_ratio = data["volume"] / data["avg_volume_20"] if data["avg_volume_20"] > 0 else 0
    ema_cross = data["price"] > data["ema21"] and data["prev_close"] <= data["prev_ema21"]

    if gap_pct > 0.03 and vol_ratio > 2.0 and ema_cross:
        reason = f"SQUEEZE: Gap +{gap_pct:.1%} | Vol {vol_ratio:.1f}x | EMA21 cross"
        return True, reason, data

    reasons = []
    if gap_pct <= 0.03:
        reasons.append(f"Gap {gap_pct:.1%} (<3%)")
    if vol_ratio <= 2.0:
        reasons.append(f"Vol {vol_ratio:.1f}x (<2x)")
    if not ema_cross:
        reasons.append("No EMA21 cross")

    return False, " | ".join(reasons), data


def scan_squeeze_universe():
    """Scan squeeze universe for short squeeze signals."""
    candidates = []
    for symbol in SQUEEZE_UNIVERSE:
        signal, reason, data = check_squeeze(symbol)
        if signal:
            # Score by gap size * volume ratio
            score = (data["price"] - data["prev_close"]) / data["prev_close"] * \
                    (data["volume"] / data["avg_volume_20"])
            candidates.append((symbol, score * 100, reason, data))
            log(f"SQUEEZE SIGNAL: {symbol} — {reason}")
        else:
            log(f"No squeeze: {symbol} — {reason}")
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates


def generate_squeeze_proposal(symbol, data):
    """Generate a squeeze trade proposal."""
    price = data["price"]
    gap_pct = (price - data["prev_close"]) / data["prev_close"]
    vol_ratio = data["volume"] / data["avg_volume_20"] if data["avg_volume_20"] > 0 else 0

    proposal = {
        "system": "system2",
        "version": "v5",
        "type": "squeeze",
        "ticker": symbol,
        "action": "BUY",
        "price": price,
        "gap_pct": gap_pct,
        "vol_ratio": vol_ratio,
        "risk": {
            "max_per_trade": MAX_RISK_PER_TRADE,
            "stop_loss": "25% below entry (simulates 50% option loss)",
            "take_profit": "50% above entry (simulates 100% option gain)",
        },
        "timestamp": datetime.now().isoformat(),
    }

    log(f"SQUEEZE PROPOSAL: {symbol} @ ${price:.2f} | Gap +{gap_pct:.1%} | Vol {vol_ratio:.1f}x")
    return proposal


def save_position(pos):
    positions = load_positions()
    updated = False
    for i, p in enumerate(positions):
        if (p.get("symbol") == pos.get("symbol") and
                p.get("status") == "open" and
                p.get("entry_date") == pos.get("entry_date")):
            positions[i] = pos
            updated = True
            break
    if not updated:
        positions.append(pos)
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2)


def load_positions():
    if not os.path.exists(POSITIONS_FILE):
        return []
    with open(POSITIONS_FILE) as f:
        return json.load(f)


def get_open_positions():
    return [p for p in load_positions() if p.get("status") == "open"]


if __name__ == "__main__":
    print("System 2 v4 — Conservative Diagonal Spread Strategy")
    print(f"Universe: {', '.join(UNIVERSE)}")
    print(f"Excluded: {', '.join(EXCLUDED)}")
    print(f"Max risk/trade: ${MAX_RISK_PER_TRADE}")
    print(f"Structure: Buy LEAP call (70 delta) + Sell short call (30 delta)")
    print("\nScanning for entry signals...\n")
    candidates = scan_universe()
    if candidates:
        print(f"\n{'='*50}")
        print("TOP CANDIDATES:")
        for sym, score, reason, tech in candidates:
            print(f"  {sym}: Score {score:.1f} | ${tech['price']:.2f} | RSI {tech['rsi']:.1f}")
    else:
        print("\nNo entry signals found.")
