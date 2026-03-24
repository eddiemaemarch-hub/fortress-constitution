#!/usr/bin/env python3
"""Rudy v2.8+ Trend Adder — Standalone IBKR Direct Trader

MSTR Cycle-Low LEAP Entry Strategy — runs directly against TWS via ib_insync.
No QuantConnect dependency. Self-contained signal generation + execution.
v2.8+ = v2.8 Dynamic Blend + Golden Cross Trend Adder.
History-seeded 200W SMA. Stress tested. Execution validated.

Usage:
    # Test mode — connect, fetch data, show filter status, no trades:
    python3 trader_v28.py --test

    # Live trading daemon (daily evaluation):
    python3 trader_v28.py --mode live --resolution daily --confirm-live

    # Show current state:
    python3 trader_v28.py --status

Requires:
    - IBKR TWS running on port 7496 (live)
    - pip3 install ib_insync pandas numpy requests schedule

SECURITY:
    - Paper mode is DISABLED. Only live mode is permitted.
    - Lockfile prevents duplicate daemons.
    - MCP server reads from live port only.
"""

import os
import sys
import json
import time
import math
import argparse
import signal
import traceback
import fcntl
from datetime import datetime, timedelta
from collections import deque

import numpy as np
import pandas as pd
import requests
import schedule
from ib_insync import IB, Stock, Option, util

# ── Project imports ──
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from broker_base import Order, Fill

# ── BTC Phase-Aware Monthly Seasonality ──
# The SAME month behaves completely differently in bull vs bear markets.
# Source: DeepSeek analysis cross-referenced with CoinGlass/Bitbo/Bitcoin Suisse data.
# Trader1 reads the correct column based on detected cycle phase.
#
# Format: {month: {"bull": (behavior, action), "bear": (behavior, action)}}
BTC_SEASONALITY = {
    1:  {"bull": ("Reversal start; green but volatile",        "WATCH",  +15.0),
         "bear": ("Deep red; continuation of sell-off",        "BRACE",  -11.5)},
    2:  {"bull": ("Strong recovery rally",                     "WATCH",  +20.0),
         "bear": ("Sucker's rally; fades quickly",             "CAUTION", -6.6)},
    3:  {"bull": ("Very bullish; strong close",                "WATCH",  +25.0),
         "bear": ("High volatility; bounce before drop",       "BRACE",  -14.8)},
    4:  {"bull": ("Continuation; steady gains",                "HOLD",   +15.0),
         "bear": ("Relief rally peak — could be a trap",       "CAUTION", +4.4)},
    5:  {"bull": ("Mixed; pause before summer",                "HOLD",    +5.0),
         "bear": ("Bearish; often starts major downtrend",     "BRACE",   +1.6)},
    6:  {"bull": ("Shallow pullback — buying opportunity",     "BUY_DIP", -5.0),
         "bear": ("BRUTAL — long liquidations, miner capitul", "HIGH_ALERT", -16.6)},
    7:  {"bull": ("Summer bounce; strong recovery",            "WATCH",  +10.0),
         "bear": ("Minor consolidation before more pain",      "CAUTION", +10.4)},
    8:  {"bull": ("Neutral to weak",                           "HOLD",    +2.0),
         "bear": ("Consistently bearish; heavy outflows",      "HIGH_ALERT", -14.0)},
    9:  {"bull": ("Weakest month — BEST buying opportunity",   "BUY_DIP", -5.0),
         "bear": ("THE WORST month — devastating drops",       "HIGH_ALERT", -9.3)},
    10: {"bull": ("STRONGEST month — start of parabolic run",  "CRITICAL", +45.0),
         "bear": ("Dead cat trap — deceptive rally, traps bulls", "CAUTION", -3.9)},
    11: {"bull": ("MASSIVE gains — parabolic top formation",   "CRITICAL", +80.0),
         "bear": ("Cycle bottom — CAPITULATION",               "HIGH_ALERT", -13.6)},
    12: {"bull": ("Topping out; profit-taking begins",         "CAUTION", +10.0),
         "bear": ("Year-end tax-loss selling; low volume",     "BRACE",   -8.6)},
}

# Phase detection thresholds (FALLBACK ONLY — System 13 ML is primary)
# These are only used when regime_state.json is stale (>7 days).
# RULE: All live price data must come from IBKR. These are structural
# thresholds for the fallback detector, not display prices.
BTC_BULL_BEAR_LINE = 80000    # BTC above $80K = bull tendency, below = bear tendency
BTC_200W_SMA_APPROX = 59433  # Approximate — real 200W SMA computed from IBKR GBTC data
BTC_250W_MA_APPROX = 56000   # 250-week MA — historical capitulation level (cycle bottoms)
BTC_300W_MA_APPROX = 50000   # 300-week MA — absolute floor (worst-case wick target)

# High-alert months differ by phase:
# Bear: Jun, Aug, Sep, Nov (brutal months) + Oct (dead cat trap)
# Bull: Sep (best buy), Oct-Nov (parabolic — must catch entry FAST)
BEAR_HIGH_ALERT = {6, 8, 9, 10, 11}   # Check every 2hrs — dip zone + traps
BULL_HIGH_ALERT = {9, 10, 11}          # Check every 2hrs — entry zone + parabolic

# ── LEAP Expiry Extension Protocol ──
EXPIRY_ROLL_WARNING_DAYS = 180   # 6 months out — early warning, plan the roll
EXPIRY_ROLL_URGENT_DAYS  = 90    # 3 months out — urgent, execute soon

# ── Paths ──
LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
LOCKFILE = os.path.join(DATA_DIR, "trader_v28.lock")
STATE_FILE = os.path.join(DATA_DIR, "trader_v28_state.json")
TV_SIGNAL_FILE = os.path.join(DATA_DIR, "tv_signal_v28.json")
LOG_FILE = os.path.join(LOG_DIR, "trader_v28.log")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


def log(msg, level="INFO"):
    """Log to file and stdout."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def send_telegram(msg, hitl=False):
    """Send Telegram alert (best-effort). If hitl=True, sends with inline YES/NO buttons."""
    try:
        sys.path.insert(0, os.path.expanduser("~/rudy/scripts"))
        import telegram as tg
        if hitl:
            tg.send_hitl_approval(msg)
        else:
            tg.send(msg)
    except Exception:
        log(f"Telegram send failed (non-critical)", "WARN")


class RudyV28:
    """Rudy v2.8 Dynamic Blend — Standalone IBKR Trader.

    Trades MSTR stock as proxy, applies dynamic LEAP multiplier (3.9x–8.4x)
    based on mNAV premium. Same logic as QC algo, running directly on TWS.
    """

    def __init__(self, mode="paper", resolution="weekly", test_mode=False):
        self.mode = mode
        self.resolution = resolution  # "weekly" or "daily"
        self.test_mode = test_mode
        self.ib = None

        # ── TWS Connection ──
        self.port = 7496 if mode == "paper" else 7496
        self.client_id = 28  # unique client ID for v2.8

        # ── v2.8 Parameters (identical to QC version) ──
        self.sma_weekly_period = 200
        self.green_weeks_threshold = 2
        self.stoch_rsi_entry_threshold = 70
        self.premium_cap = 1.3  # tight band (walk-forward optimal)
        self.premium_lookback = 4

        # BTC holdings for mNAV — Updated March 22, 2026
        # Source: MSTR 8-K filings + The Wealth Continuum analysis
        # MSTR holds 761,000+ BTC at avg cost ~$75,696/coin ($57.6B total)
        # Continues aggressive weekly buys via preferred stock offerings
        self.btc_holdings = {
            2016: 0, 2017: 0, 2018: 0, 2019: 0,
            2020: 70784, 2021: 124391, 2022: 132500,
            2023: 189150, 2024: 446400, 2025: 499226, 2026: 761000,
        }
        # Diluted shares — updated for 2026 preferred stock dilution
        self.diluted_shares = {
            2016: 10500000, 2017: 10500000, 2018: 10800000, 2019: 11000000,
            2020: 11500000, 2021: 11500000, 2022: 11500000,
            2023: 14500000, 2024: 182000000, 2025: 330000000, 2026: 390000000,
        }

        # v2.8 Walk-Forward Optimal: TIGHT Laddered Trailing Stops
        # tight trails won 7/7 OOS windows (unanimous) — WFE 1.20
        self.ladder_tiers = [
            (10000, 12.0),   # 100x+ → 12% trail (tightest, lock the bag)
            (5000,  20.0),   # 50x+  → 20% trail
            (2000,  25.0),   # 20x+  → 25% trail
            (1000,  30.0),   # 10x+  → 30% trail
            (500,   35.0),   # 5x+   → 35% trail
        ]

        # v2.7 Diamond Hands: Small Profit Takes
        self.profit_tiers = [
            (1000,  0.10),   # 10x  → sell 10%
            (2000,  0.10),   # 20x  → sell 10%
            (5000,  0.10),   # 50x  → sell 10%
            (10000, 0.10),   # 100x → sell 10%
        ]

        # Risk parameters
        self.max_hold_bars = 567
        self.target_mult = 200.0
        self.initial_floor_pct = 0.65
        self.floor_deactivate_leap_gain = 500
        self.panic_floor_pct = -35.0
        self.euphoria_premium = 3.5
        self.risk_capital_pct = 0.25

        # ── v2.8+ TREND CONFIRMATION SCALE-UP ──
        # When 50W EMA crosses above 200W SMA and holds for confirm_weeks,
        # add another 25% capital as a "trend rider" with wider stops.
        # This gives the "scout + rider" effect inside one clean system.
        self.trend_adder_enabled = True
        self.trend_confirm_weeks = 4        # Golden cross must hold 4 weeks
        self.trend_convergence_pct = 15.0   # EMA50 within 15% of SMA200
        self.trend_adder_capital_pct = 0.25 # Deploy another 25% on confirmation
        self.trend_adder_panic_floor = -60.0  # Wider floor for trend position
        self.trend_adder_initial_floor = 0.55 # 45% floor (wider)
        # Trend adder uses convergence-down as primary exit, no tight trails
        self.trend_adder_ladder = [
            (10000, 25.0),  # Only trail at extreme gains
            (5000,  35.0),
        ]

        # ── State (loaded from disk or initialized) ──
        self.state = self._load_state()

    # ══════════════════════════════════════════════════════════════
    #  ORDER SAFETY — FILL CONFIRMATION & RECONCILIATION (v50.0)
    # ══════════════════════════════════════════════════════════════

    def cleanup_stale_orders(self, symbol="MSTR"):
        """Cancel any existing orders on the same symbol before placing new ones.
        Prevents 'Cannot have open orders on both sides' IBKR error."""
        if not self.ensure_connected():
            return
        try:
            trades = self.ib.openTrades()
            cancelled = 0
            for t in trades:
                if t.contract.symbol == symbol:
                    log(f"Cancelling stale order: {t.contract.symbol} {t.order.action} "
                        f"qty={t.order.totalQuantity} status={t.orderStatus.status}")
                    self.ib.cancelOrder(t.order)
                    cancelled += 1
            if cancelled:
                self.ib.sleep(2)
                log(f"Cancelled {cancelled} stale order(s) on {symbol}")
        except Exception as e:
            log(f"cleanup_stale_orders error: {e}", "WARN")

    def build_stealth_order(self, action, qty, contract):
        """Build a limit order with anti-hunt offset instead of a raw market order.

        Institutional Execution Intelligence (v50.0):
        - Never place orders at round number prices
        - Use limit orders with slight offset from mid price to avoid front-running
        - BUY: limit = ask + small random offset (0.01-0.03 for stock, 0.05-0.15 for options)
        - SELL: limit = bid - small random offset
        - Odd lot sizes blend in better than round numbers
        - Falls back to MarketOrder if price data unavailable
        """
        import random
        from ib_insync import LimitOrder, MarketOrder

        try:
            self.ib.reqMktData(contract, '', False, False)
            self.ib.sleep(2)
            ticker = self.ib.ticker(contract)

            bid = ticker.bid if ticker.bid and ticker.bid > 0 else 0
            ask = ticker.ask if ticker.ask and ticker.ask > 0 else 0
            last = ticker.last if ticker.last and ticker.last > 0 else 0

            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                spread = ask - bid

                # Determine offset based on security type
                is_option = getattr(contract, 'secType', '') == 'OPT'
                if is_option:
                    offset = round(random.uniform(0.05, 0.15), 2)
                else:
                    offset = round(random.uniform(0.01, 0.05), 2)

                # Avoid round numbers — add pennies to break patterns
                penny_jitter = round(random.uniform(0.01, 0.04), 2)

                if action == "BUY":
                    # Aggressive limit above mid but below ask + buffer
                    price = round(mid + spread * 0.3 + penny_jitter, 2)
                    # Cap at ask + offset (don't overpay wildly)
                    price = min(price, round(ask + offset, 2))
                else:
                    # Aggressive limit below mid but above bid - buffer
                    price = round(mid - spread * 0.3 - penny_jitter, 2)
                    # Floor at bid - offset (don't undersell wildly)
                    price = max(price, round(bid - offset, 2))

                # Ensure price doesn't end in .00 or .50 (obvious levels)
                cents = int(round(price * 100)) % 100
                if cents == 0 or cents == 50:
                    price += 0.03

                order = LimitOrder(action, qty, price)
                order.tif = "GTC"
                log(f"🥷 Stealth order: {action} {qty} @ ${price:.2f} "
                    f"(bid=${bid:.2f} ask=${ask:.2f} mid=${mid:.2f})")
                self.ib.cancelMktData(contract)
                return order
            else:
                log(f"⚠️ No bid/ask for stealth order — falling back to MarketOrder", "WARN")
                self.ib.cancelMktData(contract)
                order = MarketOrder(action, qty)
                order.tif = "GTC"
                return order

        except Exception as e:
            log(f"⚠️ Stealth order build failed ({e}) — falling back to MarketOrder", "WARN")
            order = MarketOrder(action, qty)
            order.tif = "GTC"
            return order

    def execute_with_confirmation(self, contract, order, timeout=120, max_retries=2):
        """Place order and poll until filled. Returns (success, fill_price, fill_qty, status).

        NO fire-and-forget. Polls every 2s until:
        - Filled → return success
        - Cancelled/Inactive → retry up to max_retries
        - Timeout → return failure
        """
        if not self.ensure_connected():
            return False, 0.0, 0, "DISCONNECTED"

        for attempt in range(max_retries + 1):
            try:
                trade = self.ib.placeOrder(contract, order)
                log(f"Order placed: {order.action} {order.totalQuantity} {contract.symbol} "
                    f"(attempt {attempt+1}/{max_retries+1})")

                # Poll for fill
                start = time.time()
                last_status = ""
                while time.time() - start < timeout:
                    self.ib.sleep(2)
                    status = trade.orderStatus.status

                    if status != last_status:
                        log(f"  Order status: {status} (elapsed {time.time()-start:.0f}s)")
                        last_status = status

                    if status == "Filled":
                        fill_price = trade.orderStatus.avgFillPrice
                        fill_qty = trade.orderStatus.filled
                        log(f"  ✅ FILLED: {fill_qty} @ ${fill_price:.2f}")
                        return True, fill_price, int(fill_qty), "Filled"

                    if status == "PreSubmitted":
                        # Market closed — order queued for open. This is OK.
                        if time.time() - start > 10:
                            log(f"  ⏳ PreSubmitted (market likely closed) — order queued for open")
                            return True, 0.0, 0, "PreSubmitted"

                    if status in ("Cancelled", "Inactive"):
                        log(f"  ❌ Order {status}: {trade.log[-1].message if trade.log else 'no message'}", "WARN")
                        break  # retry

                else:
                    # Timeout
                    log(f"  ⚠️ Order timeout after {timeout}s, status={status}", "WARN")
                    if status == "PreSubmitted":
                        return True, 0.0, 0, "PreSubmitted"
                    return False, 0.0, 0, f"Timeout({status})"

            except Exception as e:
                log(f"  Order execution error: {e}", "ERROR")

            if attempt < max_retries:
                log(f"  Retrying order (attempt {attempt+2}/{max_retries+1})...")
                self.ib.sleep(2)

        return False, 0.0, 0, "MaxRetriesExhausted"

    def reconcile_position(self, symbol="MSTR", expected_qty=None, action=""):
        """After any trade, verify IBKR actual position matches expected.
        Sends Telegram alert on mismatch."""
        if not self.ensure_connected():
            return
        try:
            positions = self.ib.positions()
            actual_qty = 0
            for p in positions:
                if p.contract.symbol == symbol and p.contract.secType == "STK":
                    actual_qty += int(p.position)

            state_qty = self.state.get("position_qty", 0)

            if expected_qty is not None and actual_qty != expected_qty:
                msg = (f"⚠️ POSITION MISMATCH after {action}\n"
                       f"Expected: {expected_qty}\n"
                       f"IBKR actual: {actual_qty}\n"
                       f"State file: {state_qty}")
                log(msg, "ERROR")
                send_telegram(msg)
                self.state["last_mismatch"] = {
                    "time": datetime.now().isoformat(),
                    "action": action,
                    "expected": expected_qty,
                    "actual": actual_qty,
                }
                self._save_state()
            else:
                log(f"  ✅ Position reconciled: {symbol} qty={actual_qty} (matches expected)")

        except Exception as e:
            log(f"reconcile_position error: {e}", "WARN")

    def verify_flat(self, symbol="MSTR"):
        """Verify we have NO position in a symbol. Used after exits."""
        if not self.ensure_connected():
            return False
        try:
            positions = self.ib.positions()
            for p in positions:
                if p.contract.symbol == symbol:
                    log(f"  ❌ NOT FLAT: {symbol} qty={p.position} still in IBKR", "WARN")
                    return False
            log(f"  ✅ FLAT: No {symbol} positions in IBKR")
            return True
        except Exception as e:
            log(f"verify_flat error: {e}", "WARN")
            return False

    # ══════════════════════════════════════════════════════════════
    #  CONNECTION
    # ══════════════════════════════════════════════════════════════

    def connect(self):
        """Connect to TWS with retry."""
        max_retries = 5
        for attempt in range(max_retries):
            try:
                self.ib = IB()
                self.ib.connect("127.0.0.1", self.port, clientId=self.client_id)
                accounts = self.ib.managedAccounts()
                log(f"Connected to TWS port {self.port} | Accounts: {accounts}")
                return True
            except Exception as e:
                wait = min(2 ** attempt, 30)
                log(f"Connection attempt {attempt+1}/{max_retries} failed: {e}", "WARN")
                if attempt < max_retries - 1:
                    time.sleep(wait)
        log("Failed to connect to TWS after all retries", "ERROR")
        send_telegram("🔴 Rudy v2.8+: Failed to connect to TWS")
        return False

    def ensure_connected(self):
        """Reconnect if disconnected."""
        if self.ib is None or not self.ib.isConnected():
            log("Reconnecting to TWS...")
            return self.connect()
        return True

    def disconnect(self):
        """Clean disconnect."""
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()
            log("Disconnected from TWS")

    # ══════════════════════════════════════════════════════════════
    #  DATA FETCHING
    # ══════════════════════════════════════════════════════════════

    def fetch_mstr_weekly_history(self, weeks=350):
        """Fetch MSTR weekly OHLC from IBKR."""
        if not self.ensure_connected():
            return None

        contract = Stock("MSTR", "SMART", "USD")
        self.ib.qualifyContracts(contract)

        # Request weekly bars — "10 Y" gives us enough for 200W SMA + buffer
        # Note: IBKR doesn't support ADJUSTED_LAST for weekly bars, use TRADES instead
        bars = self.ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="10 Y",
            barSizeSetting="1 week",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )

        if not bars:
            log("No weekly MSTR data returned", "ERROR")
            return None

        df = util.df(bars)
        log(f"Fetched {len(df)} weekly MSTR bars (oldest: {df.iloc[0]['date']})")
        return df

    def fetch_mstr_daily_history(self, days=250):
        """Fetch MSTR daily OHLC from IBKR."""
        if not self.ensure_connected():
            return None

        contract = Stock("MSTR", "SMART", "USD")
        self.ib.qualifyContracts(contract)

        bars = self.ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="1 Y",
            barSizeSetting="1 day",
            whatToShow="ADJUSTED_LAST",
            useRTH=True,
            formatDate=1,
        )

        if not bars:
            log("No daily MSTR data returned", "ERROR")
            return None

        df = util.df(bars)
        log(f"Fetched {len(df)} daily MSTR bars")
        return df

    def fetch_gbtc_daily_history(self):
        """Fetch GBTC daily data for BTC death cross detection."""
        if not self.ensure_connected():
            return None

        contract = Stock("GBTC", "SMART", "USD")
        self.ib.qualifyContracts(contract)

        bars = self.ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="1 Y",
            barSizeSetting="1 day",
            whatToShow="ADJUSTED_LAST",
            useRTH=True,
            formatDate=1,
        )

        if not bars:
            return None
        return util.df(bars)

    def fetch_mstr_price(self):
        """Get current MSTR price."""
        if not self.ensure_connected():
            return None

        contract = Stock("MSTR", "SMART", "USD")
        self.ib.qualifyContracts(contract)
        ticker = self.ib.reqMktData(contract)
        self.ib.sleep(2)
        price = ticker.marketPrice()
        self.ib.cancelMktData(contract)

        if math.isnan(price) or price <= 0:
            # Fallback: use last close from historical
            bars = self.ib.reqHistoricalData(
                contract, endDateTime="", durationStr="2 D",
                barSizeSetting="1 day", whatToShow="ADJUSTED_LAST",
                useRTH=True, formatDate=1,
            )
            if bars:
                price = bars[-1].close
        return price

    def fetch_btc_price(self):
        """Get current BTC price from CoinGecko."""
        try:
            r = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "bitcoin", "vs_currencies": "usd"},
                timeout=10,
            )
            data = r.json()
            return data["bitcoin"]["usd"]
        except Exception as e:
            log(f"CoinGecko BTC price fetch failed: {e}", "WARN")
            return None

    def fetch_btc_weekly_history(self):
        """Get BTC weekly closes using GBTC as proxy from IBKR.
        GBTC tracks BTC price. We convert to approximate BTC using known NAV ratios.
        For 200W SMA comparison we just need direction, not exact price."""
        if not self.ensure_connected():
            return []

        try:
            contract = Stock("GBTC", "SMART", "USD")
            self.ib.qualifyContracts(contract)

            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr="10 Y",
                barSizeSetting="1 week",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
            )

            if not bars:
                log("No GBTC weekly data — falling back to CoinGecko", "WARN")
                return self._fetch_btc_weekly_coingecko()

            df = util.df(bars)
            # GBTC is a BTC proxy — use raw closes for SMA comparison
            # The 200W SMA relationship (BTC vs its own 200W) holds on any BTC proxy
            weekly_closes = df["close"].tolist()
            log(f"Fetched {len(weekly_closes)} BTC weekly closes via GBTC proxy")
            return weekly_closes

        except Exception as e:
            log(f"GBTC weekly fetch failed: {e}", "WARN")
            return self._fetch_btc_weekly_coingecko()

    def _fetch_btc_weekly_coingecko(self):
        """Fallback: CoinGecko BTC history."""
        try:
            r = requests.get(
                "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
                params={"vs_currency": "usd", "days": "max"},
                timeout=30,
            )
            data = r.json()
            prices = data.get("prices", [])
            weekly = [prices[i][1] for i in range(6, len(prices), 7)]
            log(f"Fetched {len(weekly)} BTC weekly closes from CoinGecko")
            return weekly
        except Exception as e:
            log(f"CoinGecko fallback failed: {e}", "WARN")
            return []

    # ══════════════════════════════════════════════════════════════
    #  INDICATORS
    # ══════════════════════════════════════════════════════════════

    def compute_sma(self, values, period):
        """Compute SMA from a list of values."""
        if len(values) < period:
            return None
        return sum(values[-period:]) / period

    def compute_ema(self, values, period):
        """Compute EMA from a list of values."""
        if len(values) < period:
            return None
        k = 2 / (period + 1)
        ema = sum(values[:period]) / period
        for val in values[period:]:
            ema = val * k + ema * (1 - k)
        return ema

    def compute_rsi(self, closes, period=14):
        """Compute RSI."""
        if len(closes) < period + 1:
            return 50
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        recent = deltas[-(period):]
        gains = [d for d in recent if d > 0]
        losses = [-d for d in recent if d < 0]
        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0.001
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def compute_stoch_rsi(self, closes, rsi_period=14, stoch_period=14):
        """Compute Stochastic RSI (0-100)."""
        if len(closes) < rsi_period + stoch_period + 1:
            return 50

        # Calculate RSI series
        rsi_values = []
        for i in range(stoch_period + 1):
            end = len(closes) - i
            start = max(0, end - (rsi_period + 1))
            rsi = self.compute_rsi(closes[start:end], rsi_period)
            rsi_values.append(rsi)

        rsi_values.reverse()
        rsi_min = min(rsi_values)
        rsi_max = max(rsi_values)
        if rsi_max == rsi_min:
            return 50
        current_rsi = rsi_values[-1]
        return ((current_rsi - rsi_min) / (rsi_max - rsi_min)) * 100

    def compute_macd(self, closes, fast=12, slow=26, signal=9):
        """Compute MACD histogram."""
        if len(closes) < slow + signal:
            return 0, 0, 0

        ema_fast = self.compute_ema(closes, fast)
        ema_slow = self.compute_ema(closes, slow)
        macd_line = ema_fast - ema_slow

        # Simple signal approximation
        macd_values = []
        for i in range(signal + 1):
            end = len(closes) - i
            ef = self.compute_ema(closes[:end], fast)
            es = self.compute_ema(closes[:end], slow)
            if ef and es:
                macd_values.append(ef - es)
        macd_values.reverse()
        signal_line = sum(macd_values[-signal:]) / signal if len(macd_values) >= signal else macd_line
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    def compute_atr(self, highs, lows, closes, period=14):
        """Compute ATR."""
        if len(closes) < period + 1:
            return None
        true_ranges = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            true_ranges.append(tr)
        if len(true_ranges) < period:
            return None
        return sum(true_ranges[-period:]) / period

    # ══════════════════════════════════════════════════════════════
    #  PREMIUM & MULTIPLIER
    # ══════════════════════════════════════════════════════════════

    def compute_mstr_premium(self, mstr_price, btc_price, year=None):
        """Compute MSTR premium to NAV.
        Uses LIVE treasury data from mstr_treasury.json if available (auto-updated weekly).
        Falls back to hardcoded year-based dict for historical backtesting.
        """
        if year is None:
            year = datetime.now().year

        # Try live treasury data first (updated by mstr_treasury_updater.py)
        treasury_file = os.path.join(os.path.dirname(__file__), "..", "data", "mstr_treasury.json")
        live_holdings = None
        live_shares = None
        if year == datetime.now().year and os.path.exists(treasury_file):
            try:
                with open(treasury_file) as f:
                    treasury = json.load(f)
                live_holdings = treasury.get("btc_holdings", 0)
                live_shares = treasury.get("diluted_shares", 0)
            except Exception:
                pass

        if live_holdings and live_shares and live_holdings > 0 and live_shares > 0:
            holdings = live_holdings
            shares = live_shares
        else:
            # Fallback to hardcoded historical data (for backtesting or if treasury file missing)
            holdings = self.btc_holdings.get(year, self.btc_holdings.get(
                max(k for k in self.btc_holdings if k <= year), 761000))
            shares = self.diluted_shares.get(year, self.diluted_shares.get(
                max(k for k in self.diluted_shares if k <= year), 390000000))

        if holdings == 0 or shares == 0 or btc_price <= 0:
            return 1.0
        nav_per_share = (btc_price * holdings) / shares
        if nav_per_share <= 0:
            return 999
        return mstr_price / nav_per_share

    def get_dynamic_leap_multiplier(self, premium):
        """v2.8 Dynamic premium-based LEAP blend (walk-forward optimal: tight_conservative_tight).
        LOW (<0.7x):       7.2x — conservative multiplier at discount
        FAIR (0.7-1.0x):   6.5x — conservative at fair value
        ELEVATED (1.0-1.3x): 4.8x — reduced leverage at premium
        EUPHORIC (>1.3x):  3.3x — minimal leverage in euphoria
        """
        if premium < 0.7:
            return 7.2  # conservative LOW
        elif premium < 1.0:
            return 6.5  # conservative FAIR
        elif premium <= 1.3:
            return 4.8  # conservative ELEVATED
        else:
            return 3.3  # conservative EUPHORIC

    # ══════════════════════════════════════════════════════════════
    #  STRIKE ADJUSTMENT ENGINE — Premium Band → LEAP Strike Logic
    # ══════════════════════════════════════════════════════════════

    def get_strike_recommendation(self, premium, mstr_price):
        """Select LEAP strikes based on current mNAV premium band.
        Returns (band_name, safety_strikes, spec_strikes, allocation_note, block_entry).

        Premium Bands:
        - Discount  (<0.5x):  Deep ITM safety, aggressive spec — max opportunity
        - Depressed (0.5-1.0x): Conservative strikes, heavier safety weighting
        - Fair      (1.0-2.0x): Balanced barbell — standard deployment
        - Elevated  (2.0-2.5x): Reduce spec exposure, widen safety strikes
        - Euphoric  (>2.5x):   NO NEW ENTRIES — premium too stretched
        """
        if premium < 0.5:
            return (
                "DISCOUNT",
                {"strikes": [100, 200], "weight": 0.30},
                {"strikes": [500, 800], "weight": 0.70},
                "Max opportunity — deep discount, heavy spec allocation",
                False
            )
        elif premium < 1.0:
            return (
                "DEPRESSED",
                {"strikes": [100, 200, 500], "weight": 0.45},
                {"strikes": [800, 1000], "weight": 0.55},
                "Conservative — heavier safety weighting, moderate spec",
                False
            )
        elif premium < 2.0:
            return (
                "FAIR",
                {"strikes": [100, 200, 500], "weight": 0.35},
                {"strikes": [1000, 1500], "weight": 0.65},
                "Standard barbell — balanced safety/spec deployment",
                False
            )
        elif premium <= 2.5:
            return (
                "ELEVATED",
                {"strikes": [200, 500], "weight": 0.50},
                {"strikes": [800, 1000], "weight": 0.50},
                "Reduced spec — premium stretched, widen safety allocation",
                False
            )
        else:
            return (
                "EUPHORIC",
                {"strikes": [], "weight": 0},
                {"strikes": [], "weight": 0},
                "⛔ NO NEW ENTRIES — premium too stretched, wait for compression",
                True  # Block entry
            )

    def format_strike_telegram(self, band, safety, spec, note, premium):
        """Format strike recommendation for Telegram alert."""
        if band == "EUPHORIC":
            return (
                f"⚠️ *STRIKE ENGINE: ENTRY BLOCKED*\n"
                f"Premium Band: {band} ({premium:.2f}x)\n"
                f"{note}"
            )
        safety_str = "/".join(f"${s}" for s in safety["strikes"])
        spec_str = "/".join(f"${s}" for s in spec["strikes"])
        return (
            f"📊 *STRIKE RECOMMENDATION*\n"
            f"Premium Band: {band} ({premium:.2f}x)\n"
            f"Safety ({int(safety['weight']*100)}%): {safety_str}\n"
            f"Spec ({int(spec['weight']*100)}%): {spec_str}\n"
            f"_{note}_"
        )

    # ══════════════════════════════════════════════════════════════
    #  ENTRY FILTERS
    # ══════════════════════════════════════════════════════════════

    def check_entry_filters(self, mstr_price, btc_price, weekly_closes, daily_closes,
                            daily_highs, daily_lows, btc_weekly_closes, weekly_opens):
        """Check all v2.8 entry filters. Returns (all_pass, filter_status_dict)."""
        year = datetime.now().year
        premium = self.compute_mstr_premium(mstr_price, btc_price, year)

        # 1. 200W SMA and dip+reclaim
        sma_200w = self.compute_sma(weekly_closes, self.sma_weekly_period)
        armed = self.state.get("is_armed", False)

        # 2. BTC > 200W MA
        btc_200w = self.compute_sma(btc_weekly_closes, 200) if len(btc_weekly_closes) >= 200 else None
        btc_above_200w = btc_200w is not None and btc_price > btc_200w

        # 2b. BTC 250W MA (capitulation level) and 300W MA (absolute floor)
        btc_250w = self.compute_sma(btc_weekly_closes, 250) if len(btc_weekly_closes) >= 250 else None
        btc_300w = self.compute_sma(btc_weekly_closes, 300) if len(btc_weekly_closes) >= 300 else None

        # 3. StochRSI < 70
        stoch_rsi = self.compute_stoch_rsi(daily_closes)
        stoch_rsi_ok = stoch_rsi < self.stoch_rsi_entry_threshold

        # 4. Premium not contracting
        premium_history = self.state.get("premium_history", [])
        premium_expanding = True
        if len(premium_history) > self.premium_lookback:
            prev = premium_history[-(self.premium_lookback + 1)]
            if prev > 0:
                prem_change = (premium - prev) / prev
                premium_expanding = prem_change > -0.20

        # 5. No MACD bearish divergence
        macd_line, signal_line, histogram = self.compute_macd(daily_closes)
        # Simple divergence check: price making higher highs but MACD histogram negative
        no_macd_div = True
        if len(daily_closes) >= 20:
            recent_high = max(daily_closes[-5:])
            older_high = max(daily_closes[-20:-10]) if len(daily_closes) >= 20 else recent_high
            if recent_high > older_high and histogram < 0:
                no_macd_div = False

        # 6. Premium cap
        premium_ok = premium <= self.premium_cap

        # 7. Cycle check
        cycle_ok = not self.state.get("already_entered_this_cycle", False)

        # 8. BTC era (2020+)
        btc_era = year >= 2020

        # 9. ATR quiet
        atr_quiet = True
        if len(daily_closes) >= 35 and len(daily_highs) >= 35 and len(daily_lows) >= 35:
            current_atr = self.compute_atr(daily_highs[-15:], daily_lows[-15:], daily_closes[-15:])
            avg_atr_vals = []
            for offset in range(20):
                end = len(daily_closes) - offset
                if end >= 15:
                    a = self.compute_atr(daily_highs[end-15:end], daily_lows[end-15:end], daily_closes[end-15:end])
                    if a:
                        avg_atr_vals.append(a)
            if current_atr and avg_atr_vals:
                atr_avg = sum(avg_atr_vals) / len(avg_atr_vals)
                atr_quiet = current_atr < 1.5 * atr_avg

        all_pass = (
            armed and btc_above_200w and stoch_rsi_ok and
            premium_expanding and no_macd_div and premium_ok and
            cycle_ok and btc_era and atr_quiet
        )

        filters = {
            "armed": armed,
            "sma_200w": f"${sma_200w:.2f}" if sma_200w else "N/A",
            "btc_above_200w": btc_above_200w,
            "btc_200w": f"${btc_200w:.0f}" if btc_200w else "N/A",
            "btc_250w": f"${btc_250w:.0f}" if btc_250w else "N/A",
            "btc_300w": f"${btc_300w:.0f}" if btc_300w else "N/A",
            "stoch_rsi": f"{stoch_rsi:.0f}",
            "stoch_rsi_ok": stoch_rsi_ok,
            "premium": f"{premium:.2f}x",
            "premium_ok": premium_ok,
            "premium_expanding": premium_expanding,
            "no_macd_div": no_macd_div,
            "cycle_ok": cycle_ok,
            "btc_era": btc_era,
            "atr_quiet": atr_quiet,
            "all_pass": all_pass,
        }

        return all_pass, filters

    # ══════════════════════════════════════════════════════════════
    #  200W DIP+RECLAIM TRACKING
    # ══════════════════════════════════════════════════════════════

    def update_dip_reclaim(self, weekly_closes, weekly_opens):
        """Update the 200W dip+reclaim state from weekly data."""
        sma_200w = self.compute_sma(weekly_closes, self.sma_weekly_period)
        if sma_200w is None:
            return

        week_close = weekly_closes[-1]
        week_open = weekly_opens[-1] if weekly_opens else week_close
        above_200w = week_close > sma_200w
        green_candle = week_close > week_open

        dipped = self.state.get("dipped_below_200w", False)
        green_count = self.state.get("green_week_count", 0)

        # Track dip below 200W
        if not above_200w:
            if not dipped:
                log(f"DIP BELOW 200W: MSTR=${week_close:.2f} < SMA=${sma_200w:.2f}")
            dipped = True
            green_count = 0
            self.state["is_armed"] = False

        # Count green candles above 200W after dip
        if dipped and above_200w and green_candle:
            green_count += 1
        elif not above_200w:
            green_count = 0

        # ARM after threshold
        if green_count >= self.green_weeks_threshold and not self.state.get("is_armed", False):
            self.state["is_armed"] = True
            log(f"🔫 ARMED: MSTR=${week_close:.2f} | SMA=${sma_200w:.2f} | GreenWks={green_count}")
            send_telegram(f"🔫 Rudy v2.8 ARMED\nMSTR=${week_close:.2f}\n200W SMA=${sma_200w:.2f}\nGreen weeks: {green_count}")

        # Reset after sustained bull
        if green_count > self.green_weeks_threshold + 10:
            dipped = False
            self.state["already_entered_this_cycle"] = False

        self.state["dipped_below_200w"] = dipped
        self.state["green_week_count"] = green_count

    # ══════════════════════════════════════════════════════════════
    #  TREND CONFIRMATION SCALE-UP (v2.8+ Enhancement)
    # ══════════════════════════════════════════════════════════════

    def compute_50w_ema(self, weekly_closes):
        """Compute 50-week EMA from weekly closes."""
        if len(weekly_closes) < 50:
            return None
        return self.compute_ema(weekly_closes, 50)

    def check_trend_confirmation(self, weekly_closes):
        """Check if golden cross is confirmed: 50W EMA > 200W SMA + both rising + held N weeks.

        Returns (confirmed, converging_down, ema50, sma200, distance_pct)
        - confirmed: True if golden cross held for trend_confirm_weeks
        - converging_down: True if both lines falling + close together (exit signal for adder)
        """
        sma200 = self.compute_sma(weekly_closes, 200)
        ema50 = self.compute_50w_ema(weekly_closes)

        if sma200 is None or ema50 is None or sma200 <= 0:
            return False, False, ema50, sma200, 999

        distance = abs(ema50 - sma200) / sma200 * 100

        # Need slope lookback (3 weeks)
        if len(weekly_closes) < 204:
            return False, False, ema50, sma200, distance

        sma200_prev = self.compute_sma(weekly_closes[:-3], 200)
        ema50_prev = self.compute_ema(weekly_closes[:-3], 50)
        if sma200_prev is None or ema50_prev is None:
            return False, False, ema50, sma200, distance

        ema_rising = ema50 > ema50_prev
        sma_rising = sma200 > sma200_prev
        ema_falling = ema50 < ema50_prev
        sma_falling = sma200 < sma200_prev
        ema_above_sma = ema50 > sma200

        # Golden cross confirmation: EMA50 above SMA200 + both rising
        golden_cross_now = (ema_above_sma and ema_rising and sma_rising
                           and distance <= self.trend_convergence_pct)

        # Track consecutive weeks of golden cross
        gc_weeks = self.state.get("golden_cross_weeks", 0)
        if golden_cross_now:
            gc_weeks += 1
        else:
            gc_weeks = 0
        self.state["golden_cross_weeks"] = gc_weeks

        confirmed = gc_weeks >= self.trend_confirm_weeks

        if confirmed and not self.state.get("trend_confirmed_logged", False):
            log(f"🟡 TREND CONFIRMED: EMA50=${ema50:.2f} > SMA200=${sma200:.2f} | "
                f"Dist={distance:.1f}% | Held {gc_weeks} weeks")
            send_telegram(
                f"🟡 *TREND CONFIRMATION*\n"
                f"Golden cross held {gc_weeks} weeks\n"
                f"50W EMA: ${ema50:.2f}\n"
                f"200W SMA: ${sma200:.2f}\n"
                f"Distance: {distance:.1f}%"
            )
            self.state["trend_confirmed_logged"] = True

        # Reset log flag when confirmation breaks
        if not golden_cross_now:
            self.state["trend_confirmed_logged"] = False

        # Convergence-down: both lines falling + close together (adder exit)
        converging_down = (ema_falling and sma_falling and ema_above_sma
                          and distance <= self.trend_convergence_pct)

        return confirmed, converging_down, ema50, sma200, distance

    def _execute_trend_adder(self, mstr_price, btc_price):
        """Scale up: add 25% capital as trend rider position."""
        if self.test_mode:
            log(f"[TEST] Would add trend rider position @ ${mstr_price:.2f}")
            return

        if not self.ensure_connected():
            log("Cannot execute trend adder — TWS disconnected", "ERROR")
            return

        nlv = self._get_account_value()
        deploy = nlv * self.trend_adder_capital_pct
        qty = int(deploy / mstr_price)

        if qty <= 0:
            log(f"Trend adder qty=0 — insufficient capital (NLV=${nlv:.0f})", "WARN")
            return

        contract = Stock("MSTR", "SMART", "USD")
        self.ib.qualifyContracts(contract)

        self.cleanup_stale_orders("MSTR")

        order = self.build_stealth_order("BUY", qty, contract)
        success, fill_price, fill_qty, status = self.execute_with_confirmation(contract, order)

        if not success:
            log(f"❌ TREND ADDER FAILED: {status}", "ERROR")
            send_telegram(f"🔴 *Trend Adder FAILED*\nOrder not filled: {status}")
            return

        if fill_price <= 0:
            fill_price = mstr_price
        if fill_qty > 0:
            qty = fill_qty

        premium = self.compute_mstr_premium(mstr_price, btc_price)
        leap_mult = self.get_dynamic_leap_multiplier(premium)

        # Track adder separately
        self.state["trend_adder_active"] = True
        self.state["trend_adder_entry_price"] = fill_price
        self.state["trend_adder_qty"] = qty
        self.state["trend_adder_hwm"] = fill_price
        self.state["trend_adder_peak_gain"] = 0
        self.state["trend_adder_entry_date"] = datetime.now().isoformat()

        # Also update total position qty
        self.state["position_qty"] = self.state.get("position_qty", 0) + qty

        log(f"🟡 TREND ADDER: BUY {qty} MSTR @ ${fill_price:.2f} | "
            f"Prem={premium:.2f}x | LEAP={leap_mult:.1f}x | Total pos={self.state['position_qty']}")
        send_telegram(
            f"🟡 *TREND SCALE-UP*\n"
            f"Added {qty} MSTR @ ${fill_price:.2f}\n"
            f"Premium: {premium:.2f}x | LEAP: {leap_mult:.1f}x\n"
            f"Total position: {self.state['position_qty']} shares\n"
            f"Now deploying ~50% of capital"
        )
        self._save_state()
        self.reconcile_position("MSTR", expected_qty=self.state.get("position_qty", 0), action="TREND_ADDER")

    def _exit_trend_adder(self, reason, mstr_price):
        """Exit only the trend adder portion, keep base v2.8 position."""
        adder_qty = self.state.get("trend_adder_qty", 0)
        if adder_qty <= 0:
            return

        adder_entry = self.state.get("trend_adder_entry_price", mstr_price)
        stock_gain = ((mstr_price - adder_entry) / adder_entry) * 100 if adder_entry > 0 else 0
        premium = self.compute_mstr_premium(mstr_price, self.state.get("last_btc_price", 70000))
        leap_mult = self.get_dynamic_leap_multiplier(premium)
        leap_gain = stock_gain * leap_mult

        if not self.test_mode and self.ensure_connected():
            contract = Stock("MSTR", "SMART", "USD")
            self.ib.qualifyContracts(contract)
            self.cleanup_stale_orders("MSTR")

            order = self.build_stealth_order("SELL", adder_qty, contract)
            success, fill_price, fill_qty, status = self.execute_with_confirmation(contract, order)

            if not success:
                log(f"❌ TREND ADDER EXIT FAILED: {status}", "ERROR")
                send_telegram(f"🔴 *Trend Adder Exit FAILED*\n{reason}\nStatus: {status}")
                return
            if fill_price > 0:
                mstr_price = fill_price

        log(f"🟡 TREND ADDER EXIT [{reason}]: Sold {adder_qty} @ ${mstr_price:.2f} | "
            f"Stock: {stock_gain:+.1f}% | LEAP: {leap_gain:+.1f}%")
        send_telegram(
            f"🟡 *Trend Adder EXIT — {reason}*\n"
            f"Sold {adder_qty} MSTR @ ${mstr_price:.2f}\n"
            f"Stock: {stock_gain:+.1f}% | LEAP: {leap_gain:+.1f}%\n"
            f"Base v2.8 position still active"
        )

        # Record trade
        trades = self.state.get("trade_log", [])
        trades.append({
            "entry_date": self.state.get("trend_adder_entry_date", ""),
            "exit_date": datetime.now().isoformat(),
            "entry_price": adder_entry,
            "exit_price": mstr_price,
            "stock_gain_pct": stock_gain,
            "leap_gain_pct": leap_gain,
            "reason": f"TREND_ADDER_{reason}",
        })
        self.state["trade_log"] = trades

        # Reset adder state
        self.state["trend_adder_active"] = False
        self.state["trend_adder_qty"] = 0
        self.state["trend_adder_entry_price"] = 0
        self.state["trend_adder_hwm"] = 0
        self.state["trend_adder_peak_gain"] = 0
        self.state["position_qty"] = max(0, self.state.get("position_qty", 0) - adder_qty)
        self._save_state()

    def manage_trend_adder(self, mstr_price, btc_price, weekly_closes):
        """Manage the trend adder position — wider stops, convergence-down exit."""
        if not self.state.get("trend_adder_active", False):
            return

        adder_entry = self.state.get("trend_adder_entry_price", 0)
        if adder_entry <= 0:
            return

        premium = self.compute_mstr_premium(mstr_price, btc_price)
        leap_mult = self.get_dynamic_leap_multiplier(premium)

        # Update HWM
        hwm = max(self.state.get("trend_adder_hwm", adder_entry), mstr_price)
        self.state["trend_adder_hwm"] = hwm

        stock_gain_peak = ((hwm - adder_entry) / adder_entry) * 100
        leap_peak = stock_gain_peak * leap_mult
        self.state["trend_adder_peak_gain"] = max(self.state.get("trend_adder_peak_gain", 0), leap_peak)

        current_stock_gain = ((mstr_price - adder_entry) / adder_entry) * 100
        current_leap_gain = current_stock_gain * leap_mult

        # ── PRIMARY EXIT: Convergence turns down ──
        if len(weekly_closes) >= 204:
            _, converging_down, ema50, sma200, dist = self.check_trend_confirmation(weekly_closes)
            if converging_down:
                self._exit_trend_adder("CONVERGENCE_DOWN", mstr_price)
                return

        # ── Wider initial floor (45%) ──
        floor_price = adder_entry * self.trend_adder_initial_floor
        if mstr_price < floor_price:
            self._exit_trend_adder("FLOOR_45PCT", mstr_price)
            return

        # ── Wider panic floor (-60% LEAP) ──
        if current_stock_gain < 0 and current_leap_gain <= self.trend_adder_panic_floor:
            self._exit_trend_adder("PANIC_FLOOR_60", mstr_price)
            return

        # ── Safety trailing stops (very wide, only for extreme gains) ──
        peak = self.state.get("trend_adder_peak_gain", 0)
        for threshold, trail in self.trend_adder_ladder:
            if peak >= threshold:
                stop_level = hwm * (1 - trail / 100)
                if mstr_price < stop_level:
                    self._exit_trend_adder(f"TRAIL_{threshold}", mstr_price)
                    return
                break

    # ══════════════════════════════════════════════════════════════
    #  POSITION MANAGEMENT
    # ══════════════════════════════════════════════════════════════

    def manage_position(self, mstr_price, btc_price, daily_closes, gbtc_closes=None):
        """Daily position management — trails, profits, floors."""
        entry_price = self.state.get("entry_price", 0)
        if entry_price <= 0:
            return

        year = datetime.now().year
        premium = self.compute_mstr_premium(mstr_price, btc_price, year)
        leap_mult = self.get_dynamic_leap_multiplier(premium)

        # Update HWM
        hwm = max(self.state.get("position_hwm", entry_price), mstr_price)
        self.state["position_hwm"] = hwm

        stock_gain_from_hwm = ((hwm - entry_price) / entry_price) * 100
        leap_peak = stock_gain_from_hwm * leap_mult
        self.state["peak_gain_pct"] = max(self.state.get("peak_gain_pct", 0), leap_peak)

        current_stock_gain = ((mstr_price - entry_price) / entry_price) * 100
        current_leap_gain = current_stock_gain * leap_mult

        self.state["bars_in_trade"] = self.state.get("bars_in_trade", 0) + 1

        # ── 35% Initial Floor ──
        if current_leap_gain < self.floor_deactivate_leap_gain:
            floor_price = entry_price * self.initial_floor_pct
            if mstr_price < floor_price:
                self._execute_exit("INITIAL_FLOOR", mstr_price, current_stock_gain, current_leap_gain)
                return

        # ── Panic Floor on Losers ──
        if current_stock_gain < 0 and current_leap_gain <= self.panic_floor_pct:
            self._execute_exit("PANIC_FLOOR", mstr_price, current_stock_gain, current_leap_gain)
            return

        # ── Euphoria Premium Sell ──
        if (premium > self.euphoria_premium and current_leap_gain > 0
                and not self.state.get("euphoria_sell_done", False)):
            self._execute_partial_sell(0.15, "EUPHORIA_SELL", mstr_price, premium)
            self.state["euphoria_sell_done"] = True

        # ── Tiered Profit Taking ──
        pt_hits = self.state.get("pt_hits", [False] * len(self.profit_tiers))
        for i, (threshold, sell_pct) in enumerate(self.profit_tiers):
            if i < len(pt_hits) and current_leap_gain >= threshold and not pt_hits[i]:
                self._execute_partial_sell(sell_pct, f"PT{i+1}_{threshold}", mstr_price, premium)
                pt_hits[i] = True
        self.state["pt_hits"] = pt_hits

        # ── Laddered Trailing Stop ──
        peak = self.state.get("peak_gain_pct", 0)
        trail_pct = 0
        tier_name = "NONE"
        for threshold, trail in self.ladder_tiers:
            if peak >= threshold:
                trail_pct = trail
                tier_name = f"+{threshold}%"
                break

        if trail_pct > 0:
            stop_level = hwm * (1 - trail_pct / 100)
            if mstr_price < stop_level:
                self._execute_exit(f"TRAIL_STOP_{tier_name}", mstr_price, current_stock_gain, current_leap_gain)
                return

        # ── Max Hold Exit ──
        if self.state.get("bars_in_trade", 0) >= self.max_hold_bars:
            self._execute_exit("MAX_HOLD", mstr_price, current_stock_gain, current_leap_gain)
            return

        # ── Target Exit ──
        if current_leap_gain >= (self.target_mult - 1) * 100:
            self._execute_exit("TARGET_HIT", mstr_price, current_stock_gain, current_leap_gain)
            return

        # ── Below EMA50 + Losing ──
        if len(daily_closes) >= 50:
            ema50 = self.compute_ema(daily_closes, 50)
            if ema50 and mstr_price < ema50 and current_leap_gain < 0:
                self._execute_exit("EMA50_LOSS", mstr_price, current_stock_gain, current_leap_gain)
                return

        # ── BTC Death Cross (GBTC SMA50 < SMA200) ──
        if gbtc_closes and len(gbtc_closes) >= 200:
            sma50 = np.mean(gbtc_closes[-50:])
            sma200 = np.mean(gbtc_closes[-200:])
            prev_sma50 = np.mean(gbtc_closes[-51:-1])
            if sma50 < sma200 and prev_sma50 >= sma200:
                self._execute_exit("BTC_DEATH_CROSS", mstr_price, current_stock_gain, current_leap_gain)
                return

        # ── BTC 200W Break ──
        btc_weekly = self.state.get("btc_weekly_closes", [])
        btc_200w = self.compute_sma(btc_weekly, 200) if len(btc_weekly) >= 200 else None
        if btc_200w and btc_price < btc_200w:
            if current_leap_gain < 0:
                self._execute_exit("BTC_200W_BREAK", mstr_price, current_stock_gain, current_leap_gain)
                return
            else:
                self._execute_partial_sell(0.50, "BTC_200W_PROFIT_TRIM", mstr_price, premium)

        # ── Premium Compression ──
        premium_hwm = self.state.get("premium_hwm", premium)
        self.state["premium_hwm"] = max(premium_hwm, premium)
        if premium_hwm > 0:
            prem_drop = ((premium_hwm - premium) / premium_hwm) * 100
            if prem_drop >= 30 and current_leap_gain > 0:
                self._execute_partial_sell(0.50, "PREM_COMPRESS", mstr_price, premium)

        # ── LEAP Expiry Extension — handle MCP approval flags then check ──
        # MCP approve_expiry_roll tool writes these flags; daemon picks them up here.
        if self.state.get("expiry_roll_commander_approved"):
            self.state["expiry_roll_commander_approved"] = False
            self._save_state()
            self.approve_expiry_roll()
        elif self.state.get("expiry_roll_commander_rejected"):
            self.state["expiry_roll_commander_rejected"] = False
            self._save_state()
            self.reject_expiry_roll()
        else:
            self._check_expiry_extension(current_leap_gain, mstr_price)

    # ══════════════════════════════════════════════════════════════
    #  LEAP EXPIRY EXTENSION PROTOCOL
    # ══════════════════════════════════════════════════════════════

    def _check_expiry_extension(self, current_leap_gain, mstr_price):
        """LEAP Expiry Extension Protocol for Trader1.

        T1 trades MSTR stock as proxy but the Commander holds MSTR CALL LEAP options
        based on our strike recommendations. This protocol detects those option positions
        in IBKR and proposes a same-strike forward roll when approaching expiry.
        HITL approval required — Commander executes the roll manually on IBKR TWS.

        Fires at EXPIRY_ROLL_WARNING_DAYS (180d) and again at EXPIRY_ROLL_URGENT_DAYS (90d).
        """
        # Don't double-propose while one is pending
        if self.state.get("pending_expiry_roll"):
            return

        # Need live IBKR connection to scan for CALL positions
        if not self.ensure_connected():
            return

        try:
            positions = self.ib.positions()
        except Exception as e:
            log(f"_check_expiry_extension: positions query failed: {e}", "WARN")
            return

        # Find MSTR CALL options (long positions only)
        mstr_calls = [
            pos for pos in positions
            if (pos.contract.symbol == "MSTR"
                and pos.contract.secType == "OPT"
                and pos.contract.right == "C"
                and pos.position > 0)
        ]

        if not mstr_calls:
            return  # No LEAP position to monitor

        # Take the nearest-expiry call (most urgent)
        pos = sorted(mstr_calls,
                     key=lambda p: p.contract.lastTradeDateOrContractMonth)[0]
        expiry_str = pos.contract.lastTradeDateOrContractMonth
        strike = pos.contract.strike

        try:
            expiry_dt = datetime.strptime(expiry_str, "%Y%m%d")
            days_left = (expiry_dt - datetime.now()).days
        except Exception:
            return

        alerted_180 = self.state.get("expiry_roll_alerted_180d", False)
        alerted_90  = self.state.get("expiry_roll_alerted_90d", False)

        if days_left <= EXPIRY_ROLL_URGENT_DAYS and not alerted_90:
            urgency = "🚨 URGENT"
            self.state["expiry_roll_alerted_90d"] = True
        elif days_left <= EXPIRY_ROLL_WARNING_DAYS and not alerted_180:
            urgency = "⚠️ WARNING"
            self.state["expiry_roll_alerted_180d"] = True
        else:
            return  # Not within alert window

        # Proposed new expiry — roll out +2 years
        new_expiry_dt = expiry_dt + timedelta(days=730)
        new_expiry = new_expiry_dt.strftime("%Y%m%d")

        qty = int(abs(pos.position))

        self.state["pending_expiry_roll"] = {
            "old_expiry": expiry_str,
            "new_expiry": new_expiry,
            "strike": strike,
            "contracts": qty,
            "days_left": days_left,
            "urgency": urgency,
            "gain_pct_at_proposal": current_leap_gain,
            "mstr_price_at_proposal": mstr_price,
            "timestamp": datetime.now().isoformat(),
        }
        self._save_state()

        send_telegram(
            f"{urgency} *TRADER1: LEAP EXPIRY EXTENSION*\n"
            f"MSTR ${strike:.0f}C ×{qty} — {days_left}d to expiry — time decay risk\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Days to expiry: *{days_left}d* ({expiry_str})\n"
            f"MSTR price: ${mstr_price:.2f}\n"
            f"LEAP gain: {current_leap_gain:+.1f}%\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📅 *PROPOSED ROLL*\n"
            f"Current: ${strike:.0f}C {expiry_str} ×{qty}\n"
            f"→ New:   ${strike:.0f}C {new_expiry} ×{qty} (+2yr)\n"
            f"Same strike — buys time for thesis to play out.\n"
            f"Debit = cost of time premium extension.\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🔔 *Rudy will execute this roll automatically on approval.*\n"
            f"Verify {new_expiry} is liquid on IBKR, then:\n"
            f"YES → MCP approve_expiry_roll (Rudy executes)\n"
            f"NO  → MCP reject_expiry_roll",
            hitl=True
        )
        log(f"EXPIRY EXTENSION proposed: ${strike:.0f}C ×{qty} "
            f"{expiry_str}→{new_expiry} | {days_left}d left | "
            f"LEAP gain: {current_leap_gain:+.1f}%")

    def approve_expiry_roll(self):
        """Execute LEAP expiry roll automatically — sell old contract, buy new contract on IBKR.

        Same pattern as T2/T3 execute_roll(). Commander taps YES on Telegram;
        Rudy handles the sell-old / buy-new directly against TWS.

        Called after HITL approval via MCP approve_expiry_roll tool.
        """
        roll = self.state.get("pending_expiry_roll")
        if not roll:
            return {"status": "error", "message": "No pending expiry roll"}

        old_expiry = roll.get("old_expiry")
        new_expiry = roll.get("new_expiry")
        strike     = float(roll.get("strike", 0))
        qty        = int(roll.get("contracts", 1))

        if self.test_mode:
            log(f"TEST MODE — would roll ${strike:.0f}C {old_expiry} → {new_expiry} ×{qty}")
            self.state["pending_expiry_roll"] = None
            self._save_state()
            return {"status": "test", "message": "Would execute roll"}

        if not self.ensure_connected():
            send_telegram(
                f"🔴 *TRADER1: EXPIRY ROLL FAILED — IBKR not connected*\n"
                f"${strike:.0f}C {old_expiry} → {new_expiry}\n"
                f"⚠️ Manual intervention required — TWS not reachable"
            )
            return {"status": "error", "message": "IBKR not connected"}

        send_telegram(
            f"⚙️ *TRADER1: Executing LEAP roll…*\n"
            f"${strike:.0f}C {old_expiry} → {new_expiry} ×{qty}\n"
            f"Step 1/2: Selling old contract…"
        )

        # ── Step 1: Sell old contract ──
        old_contract = Option("MSTR", old_expiry, strike, "C", "SMART")
        try:
            self.ib.qualifyContracts(old_contract)
        except Exception as e:
            send_telegram(
                f"🔴 *TRADER1: ROLL FAILED — cannot qualify old contract*\n"
                f"${strike:.0f}C {old_expiry}: {e}\n"
                f"⚠️ Manual intervention required"
            )
            return {"status": "error", "message": f"qualifyContracts old failed: {e}"}

        sell_order = self.build_stealth_order(old_contract, "SELL", qty)
        success_sell, sell_price, sell_qty, sell_status = self.execute_with_confirmation(
            old_contract, sell_order, timeout=120, max_retries=2
        )

        if not success_sell:
            send_telegram(
                f"🔴 *TRADER1: ROLL FAILED — could not sell old contract*\n"
                f"${strike:.0f}C {old_expiry} — Status: {sell_status}\n"
                f"⚠️ NO changes made. Manual intervention required."
            )
            return {"status": "error", "message": f"Sell failed: {sell_status}"}

        log(f"ROLL step 1/2: sold ${strike:.0f}C {old_expiry} ×{sell_qty} @ ${sell_price:.2f}")

        # ── Step 2: Buy new contract ──
        send_telegram(
            f"⚙️ *TRADER1: Roll step 2/2 — Buying new contract…*\n"
            f"Sold ${strike:.0f}C {old_expiry} @ ${sell_price:.2f}\n"
            f"Buying ${strike:.0f}C {new_expiry} ×{qty}…"
        )

        new_contract = Option("MSTR", new_expiry, strike, "C", "SMART")
        try:
            self.ib.qualifyContracts(new_contract)
        except Exception as e:
            send_telegram(
                f"🔴 *TRADER1: ROLL PARTIAL — Sold old but new contract unavailable*\n"
                f"Sold ${strike:.0f}C {old_expiry} @ ${sell_price:.2f}\n"
                f"Cannot qualify ${strike:.0f}C {new_expiry}: {e}\n"
                f"⚠️ MANUAL INTERVENTION REQUIRED — buy the new contract!"
            )
            return {"status": "partial", "message": f"qualifyContracts new failed: {e}"}

        buy_order = self.build_stealth_order(new_contract, "BUY", qty)
        success_buy, buy_price, buy_qty, buy_status = self.execute_with_confirmation(
            new_contract, buy_order, timeout=120, max_retries=2
        )

        if not success_buy:
            send_telegram(
                f"🔴 *TRADER1: ROLL PARTIAL — Sold old but FAILED to buy new!*\n"
                f"Sold ${strike:.0f}C {old_expiry} @ ${sell_price:.2f}\n"
                f"Failed to buy ${strike:.0f}C {new_expiry} — Status: {buy_status}\n"
                f"⚠️ MANUAL INTERVENTION REQUIRED — buy the new contract!"
            )
            return {"status": "partial", "message": f"Sold old, buy failed: {buy_status}"}

        net_debit = (buy_price - sell_price) * 100 * qty

        # ── Update state ──
        self.state["pending_expiry_roll"]      = None
        self.state["expiry_roll_alerted_180d"] = False   # Reset for new expiry window
        self.state["expiry_roll_alerted_90d"]  = False

        roll_history = self.state.get("roll_history", [])
        roll_history.append({
            "type":        "expiry_roll",
            "old_expiry":  old_expiry,
            "new_expiry":  new_expiry,
            "strike":      strike,
            "contracts":   qty,
            "sell_price":  sell_price,
            "buy_price":   buy_price,
            "net_debit":   net_debit,
            "timestamp":   datetime.now().isoformat(),
        })
        self.state["roll_history"] = roll_history
        self._save_state()

        send_telegram(
            f"✅ *TRADER1: LEAP ROLLED*\n"
            f"MSTR ${strike:.0f}C ×{qty}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Sold {old_expiry} @ ${sell_price:.2f}\n"
            f"Bought {new_expiry} @ ${buy_price:.2f}\n"
            f"Net debit: ${net_debit:.2f}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Watching {new_expiry} — 180d/90d alerts reset."
        )
        log(f"EXPIRY ROLL complete: ${strike:.0f}C {old_expiry} → {new_expiry} ×{qty} | "
            f"Net debit: ${net_debit:.2f}")

        return {
            "status":     "executed",
            "old_expiry": old_expiry,
            "new_expiry": new_expiry,
            "strike":     strike,
            "contracts":  qty,
            "sell_price": sell_price,
            "buy_price":  buy_price,
            "net_debit":  net_debit,
        }

    def reject_expiry_roll(self):
        """Decline the proposed expiry roll — keep current expiry."""
        roll   = self.state.get("pending_expiry_roll") or {}
        strike = roll.get("strike", 0)
        expiry = roll.get("old_expiry", "?")

        self.state["pending_expiry_roll"] = None
        self._save_state()

        send_telegram(
            f"❌ *TRADER1: Expiry roll rejected*\n"
            f"Keeping ${strike:.0f}C {expiry}\n"
            f"Will re-alert when within {EXPIRY_ROLL_URGENT_DAYS} days."
        )
        log(f"EXPIRY ROLL rejected: keeping ${strike:.0f}C {expiry}")
        return {"status": "rejected"}

    # ══════════════════════════════════════════════════════════════
    #  ORDER EXECUTION
    # ══════════════════════════════════════════════════════════════

    def _get_position_qty(self):
        """Get current MSTR position quantity from IBKR."""
        if not self.ensure_connected():
            return self.state.get("position_qty", 0)
        positions = self.ib.positions()
        for pos in positions:
            if pos.contract.symbol == "MSTR" and pos.contract.secType == "STK":
                return int(pos.position)
        return 0

    def _get_account_value(self):
        """Get account NLV from IBKR."""
        if not self.ensure_connected():
            return 100000  # fallback
        summary = self.ib.accountSummary()
        for item in summary:
            if item.tag == "NetLiquidation":
                return float(item.value)
        return 100000

    def _execute_entry(self, mstr_price, btc_price, entry_num):
        """Execute a market buy on MSTR."""
        if self.test_mode:
            log(f"[TEST] Would BUY MSTR @ ${mstr_price:.2f} (entry {entry_num}/2)")
            return

        if not self.ensure_connected():
            log("Cannot execute entry — TWS disconnected", "ERROR")
            send_telegram(
                f"🚨 *Rudy v2.8+ ENTRY ABORTED — TWS DISCONNECTED*\n"
                f"SIGNAL FIRED but could not connect to IBKR TWS.\n"
                f"MSTR @ ${mstr_price:.2f} | Entry {entry_num}/2\n"
                f"⚠️ MANUAL INTERVENTION REQUIRED — restart TWS immediately."
            )
            return

        nlv = self._get_account_value()
        risk_capital = nlv * self.risk_capital_pct
        deploy = risk_capital * 0.50  # 50/50 scale-in
        qty = int(deploy / mstr_price)

        if qty <= 0:
            log(f"Entry qty=0 — insufficient capital (NLV=${nlv:.0f})", "ERROR")
            send_telegram(
                f"🚨 *Rudy v2.8+ ENTRY ABORTED — Insufficient Capital*\n"
                f"NLV: ${nlv:,.0f}\n"
                f"Risk Capital (25%): ${nlv * self.risk_capital_pct:,.0f}\n"
                f"Deploy (50%): ${nlv * self.risk_capital_pct * 0.50:,.0f}\n"
                f"MSTR Price: ${mstr_price:.2f}\n"
                f"Qty calculated: {qty} — entry BLOCKED\n"
                f"⚠️ Signal fired but no shares could be purchased. Fund the account."
            )
            return

        contract = Stock("MSTR", "SMART", "USD")
        self.ib.qualifyContracts(contract)

        # v50.0 Safety: cleanup stale orders, then execute with confirmation
        self.cleanup_stale_orders("MSTR")

        order = self.build_stealth_order("BUY", qty, contract)
        success, fill_price, fill_qty, status = self.execute_with_confirmation(contract, order)

        if not success:
            log(f"❌ ENTRY FAILED: Order not filled (status={status})", "ERROR")
            send_telegram(f"🔴 *Rudy v2.8+ ENTRY FAILED*\nOrder not filled: {status}")
            return

        if fill_price <= 0:
            fill_price = mstr_price  # fallback for PreSubmitted (market closed)
        if fill_qty > 0:
            qty = fill_qty  # use actual filled qty

        premium = self.compute_mstr_premium(mstr_price, btc_price)
        leap_mult = self.get_dynamic_leap_multiplier(premium)

        # ── STRIKE ADJUSTMENT ENGINE ──
        band, safety, spec, strike_note, block_entry = self.get_strike_recommendation(premium, mstr_price)
        if block_entry:
            log(f"⛔ ENTRY BLOCKED by Strike Engine — {band} band ({premium:.2f}x)", "WARN")
            send_telegram(self.format_strike_telegram(band, safety, spec, strike_note, premium))
            return  # Do NOT enter in euphoric premium

        # Store strike recommendation in state for reference
        self.state["last_strike_recommendation"] = {
            "band": band,
            "safety_strikes": safety["strikes"],
            "safety_weight": safety["weight"],
            "spec_strikes": spec["strikes"],
            "spec_weight": spec["weight"],
            "premium_at_entry": premium,
            "timestamp": datetime.now().isoformat()
        }

        if entry_num == 1:
            self.state["entry_price"] = fill_price
            self.state["position_hwm"] = fill_price
            self.state["peak_gain_pct"] = 0
            self.state["pt_hits"] = [False] * len(self.profit_tiers)
            self.state["premium_hwm"] = premium
            self.state["bars_in_trade"] = 0
            self.state["euphoria_sell_done"] = False
            self.state["first_entry_done"] = True
            self.state["second_entry_done"] = False
            self.state["position_qty"] = qty
        else:
            # Average in
            old_qty = self.state.get("position_qty", 0)
            old_price = self.state.get("entry_price", fill_price)
            total_qty = old_qty + qty
            self.state["entry_price"] = (old_price * old_qty + fill_price * qty) / total_qty
            self.state["second_entry_done"] = True
            self.state["already_entered_this_cycle"] = True
            self.state["position_qty"] = total_qty

        safety_str = "/".join(f"${s}" for s in safety["strikes"])
        spec_str = "/".join(f"${s}" for s in spec["strikes"])

        log(f"🟢 ENTRY {entry_num}/2: MSTR @ ${fill_price:.2f} | Qty={qty} | "
            f"Prem={premium:.2f}x | LEAP_Mult={leap_mult:.1f}x | Band={band}")
        send_telegram(
            f"🟢 *Rudy v2.8+ ENTRY {entry_num}/2*\n"
            f"MSTR @ ${fill_price:.2f}\n"
            f"Qty: {qty}\n"
            f"Premium: {premium:.2f}x | Band: {band}\n"
            f"LEAP Mult: {leap_mult:.1f}x\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📊 *Strike Recommendation*\n"
            f"Safety ({int(safety['weight']*100)}%): {safety_str}\n"
            f"Spec ({int(spec['weight']*100)}%): {spec_str}\n"
            f"_{strike_note}_"
        )
        self._save_state()

        # v50.0 Safety: reconcile position after entry
        self.reconcile_position("MSTR", expected_qty=self.state.get("position_qty", 0), action=f"ENTRY {entry_num}")

    def _execute_exit(self, reason, price, stock_gain, leap_gain):
        """Liquidate full MSTR position."""
        qty = self._get_position_qty()
        if qty <= 0:
            qty = self.state.get("position_qty", 0)

        if not self.test_mode and qty > 0 and self.ensure_connected():
            contract = Stock("MSTR", "SMART", "USD")
            self.ib.qualifyContracts(contract)

            # v50.0 Safety: cleanup stale orders, then execute with confirmation
            self.cleanup_stale_orders("MSTR")

            order = self.build_stealth_order("SELL", abs(qty), contract)
            success, fill_price_actual, fill_qty, status = self.execute_with_confirmation(contract, order)

            if not success:
                log(f"❌ EXIT ORDER FAILED: {status}", "ERROR")
                send_telegram(f"🔴 *Rudy v2.8 EXIT FAILED*\n{reason}\nOrder not filled: {status}")
                return

            if fill_price_actual > 0:
                price = fill_price_actual  # use actual fill price

        log(f"🔴 EXIT [{reason}]: MSTR @ ${price:.2f} | Stock: {stock_gain:+.1f}% | LEAP: {leap_gain:+.1f}%")
        send_telegram(
            f"🔴 *Rudy v2.8 EXIT — {reason}*\n"
            f"MSTR @ ${price:.2f}\n"
            f"Stock: {stock_gain:+.1f}%\n"
            f"LEAP: {leap_gain:+.1f}%"
        )

        # Record trade
        trades = self.state.get("trade_log", [])
        trades.append({
            "entry_date": self.state.get("entry_date", ""),
            "exit_date": datetime.now().isoformat(),
            "entry_price": self.state.get("entry_price", 0),
            "exit_price": price,
            "stock_gain_pct": stock_gain,
            "leap_gain_pct": leap_gain,
            "reason": reason,
        })
        self.state["trade_log"] = trades

        # Reset position state
        self.state["entry_price"] = 0
        self.state["position_hwm"] = 0
        self.state["peak_gain_pct"] = 0
        self.state["premium_hwm"] = 0
        self.state["bars_in_trade"] = 0
        self.state["first_entry_done"] = False
        self.state["second_entry_done"] = False
        self.state["euphoria_sell_done"] = False
        self.state["already_entered_this_cycle"] = False
        self.state["position_qty"] = 0
        # Also reset trend adder if base exits (full flatten)
        self.state["trend_adder_active"] = False
        self.state["trend_adder_qty"] = 0
        self.state["trend_adder_entry_price"] = 0
        self.state["trend_adder_hwm"] = 0
        self.state["trend_adder_peak_gain"] = 0
        self._save_state()

        # v50.0 Safety: verify we're actually flat
        if not self.test_mode:
            is_flat = self.verify_flat("MSTR")
            if not is_flat:
                send_telegram(f"⚠️ *EXIT WARNING*: Sold but MSTR position still shows in IBKR!")

    def _execute_partial_sell(self, sell_pct, reason, price, premium):
        """Sell a percentage of the position."""
        qty = self._get_position_qty()
        if qty <= 0:
            qty = self.state.get("position_qty", 0)

        sell_qty = int(qty * sell_pct)
        if sell_qty <= 0:
            return

        if not self.test_mode and self.ensure_connected():
            contract = Stock("MSTR", "SMART", "USD")
            self.ib.qualifyContracts(contract)

            # v50.0 Safety: cleanup stale orders, then execute with confirmation
            self.cleanup_stale_orders("MSTR")

            order = self.build_stealth_order("SELL", sell_qty, contract)
            success, fill_price, fill_qty, status = self.execute_with_confirmation(contract, order)

            if not success:
                log(f"❌ PARTIAL SELL FAILED: {status}", "ERROR")
                send_telegram(f"🔴 *Partial Sell FAILED*\n{reason}\nOrder not filled: {status}")
                return

            if fill_price > 0:
                price = fill_price
            if fill_qty > 0:
                sell_qty = int(fill_qty)

        expected_remaining = max(0, self.state.get("position_qty", qty) - sell_qty)
        self.state["position_qty"] = expected_remaining
        log(f"🟡 PARTIAL SELL [{reason}]: {sell_qty} shares @ ${price:.2f} | Prem={premium:.2f}x")
        send_telegram(f"🟡 *Partial Sell — {reason}*\n{sell_qty} shares @ ${price:.2f}")
        self._save_state()

        # v50.0 Safety: reconcile position after partial sell
        self.reconcile_position("MSTR", expected_qty=expected_remaining, action=f"PARTIAL_SELL({reason})")

    # ══════════════════════════════════════════════════════════════
    #  MAIN EVALUATION LOOP
    # ══════════════════════════════════════════════════════════════

    def check_tv_signal(self):
        """Check for TradingView webhook confluence signal.
        Returns (has_signal, signal_data) — signal is valid for 24 hours."""
        if not os.path.exists(TV_SIGNAL_FILE):
            return False, None
        try:
            with open(TV_SIGNAL_FILE) as f:
                signal = json.load(f)
            # Check signal freshness (valid for 24 hours)
            sig_time = datetime.fromisoformat(signal.get("timestamp", "2000-01-01"))
            age_hours = (datetime.now() - sig_time).total_seconds() / 3600
            if age_hours > 24:
                return False, None
            action = signal.get("action", "").upper()
            if action == "BUY":
                log(f"TV CONFLUENCE: BUY signal from TradingView ({age_hours:.1f}h ago)")
                return True, signal
            elif action in ("SELL", "EXIT"):
                log(f"TV CONFLUENCE: EXIT signal from TradingView ({age_hours:.1f}h ago)")
                return True, signal
        except Exception as e:
            log(f"TV signal check error: {e}", "WARN")
        return False, None

    def consume_tv_signal(self):
        """Remove the TV signal file after acting on it."""
        try:
            if os.path.exists(TV_SIGNAL_FILE):
                os.remove(TV_SIGNAL_FILE)
        except Exception:
            pass

    def evaluate(self):
        """Main evaluation — called on schedule (weekly or daily)."""
        log(f"\n{'='*60}")
        log(f"RUDY v2.8 EVALUATE ({self.resolution.upper()}) — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        log(f"{'='*60}")

        # ── SAFETY PRE-CHECK (does not modify strategy logic) ──
        if not self.check_daily_loss_limit():
            log("Evaluation SKIPPED — daily loss limit active")
            return
        if not self.check_consecutive_losses():
            log("Evaluation SKIPPED — consecutive loss shutdown active")
            return

        try:
            # Log cycle intelligence context
            self.log_seasonality_context()

            # Ensure IBKR connection is alive before fetching data
            if not self.ensure_connected():
                log("Cannot reconnect to TWS — skipping evaluation", "ERROR")
                send_telegram("🔴 Rudy v2.8+ evaluation skipped: TWS connection failed")
                return

            # Fetch all data
            mstr_price = self.fetch_mstr_price()
            btc_price = self.fetch_btc_price()

            if not mstr_price or not btc_price:
                log("Missing price data — skipping evaluation", "ERROR")
                send_telegram(
                    f"🔴 *Rudy v2.8+ EVAL SKIPPED — Missing Price Data*\n"
                    f"MSTR: {'$'+str(round(mstr_price,2)) if mstr_price else '❌ NONE'}\n"
                    f"BTC: {'$'+str(round(btc_price,0)) if btc_price else '❌ NONE'}\n"
                    f"Check IBKR TWS connection immediately."
                )
                return

            log(f"MSTR: ${mstr_price:.2f} | BTC: ${btc_price:,.0f}")

            # Fetch historical data
            weekly_df = self.fetch_mstr_weekly_history()
            daily_df = self.fetch_mstr_daily_history()
            gbtc_df = self.fetch_gbtc_daily_history()

            if weekly_df is None or daily_df is None:
                log("Missing historical data — skipping", "ERROR")
                send_telegram(
                    f"🔴 *Rudy v2.8+ EVAL SKIPPED — Missing Historical Data*\n"
                    f"Weekly bars: {'✅' if weekly_df is not None else '❌ NONE'}\n"
                    f"Daily bars: {'✅' if daily_df is not None else '❌ NONE'}\n"
                    f"IBKR may be rate-limiting historical data requests."
                )
                return

            weekly_closes = weekly_df["close"].tolist()
            weekly_opens = weekly_df["open"].tolist()
            daily_closes = daily_df["close"].tolist()
            daily_highs = daily_df["high"].tolist()
            daily_lows = daily_df["low"].tolist()
            gbtc_closes = gbtc_df["close"].tolist() if gbtc_df is not None else []

            # BTC weekly for 200W
            btc_weekly = self.fetch_btc_weekly_history()
            self.state["btc_weekly_closes"] = btc_weekly

            # Update premium history
            premium = self.compute_mstr_premium(mstr_price, btc_price)
            prem_hist = self.state.get("premium_history", [])
            prem_hist.append(premium)
            if len(prem_hist) > 30:
                prem_hist = prem_hist[-30:]
            self.state["premium_history"] = prem_hist

            # ── PREMIUM COMPRESSION ALERT ──
            if len(prem_hist) >= 5:
                prem_30d_high = max(prem_hist)
                if prem_30d_high > 0:
                    prem_drop_pct = ((prem_30d_high - premium) / prem_30d_high) * 100
                    already_alerted = self.state.get("premium_compression_alerted", False)

                    if prem_drop_pct > 15 and not already_alerted:
                        self.state["premium_compression_alerted"] = True
                        self.state["premium_compression_date"] = datetime.now().isoformat()

                        # Generate strike roll recommendation based on NEW band
                        band, safety, spec, strike_note, _ = self.get_strike_recommendation(premium, mstr_price)
                        entry_rec = self.state.get("last_strike_recommendation", {})
                        old_band = entry_rec.get("band", "N/A")
                        old_spec = entry_rec.get("spec_strikes", [])
                        old_safety = entry_rec.get("safety_strikes", [])

                        old_spec_str = "/".join(f"${s}" for s in old_spec) if old_spec else "N/A"
                        old_safety_str = "/".join(f"${s}" for s in old_safety) if old_safety else "N/A"
                        new_spec_str = "/".join(f"${s}" for s in spec["strikes"]) if spec["strikes"] else "N/A"
                        new_safety_str = "/".join(f"${s}" for s in safety["strikes"]) if safety["strikes"] else "N/A"

                        # Calculate payout haircut
                        haircut_pct = min(prem_drop_pct * 1.6, 80)  # ~1.6x leverage on spec LEAPs

                        # Store pending roll for HITL approval
                        self.state["pending_strike_roll"] = {
                            "old_band": old_band,
                            "new_band": band,
                            "old_spec_strikes": old_spec,
                            "new_spec_strikes": spec["strikes"],
                            "old_safety_strikes": old_safety,
                            "new_safety_strikes": safety["strikes"],
                            "premium_drop_pct": prem_drop_pct,
                            "haircut_pct": haircut_pct,
                            "timestamp": datetime.now().isoformat()
                        }
                        self._save_state()

                        send_telegram(
                            f"⚠️ *PREMIUM COMPRESSION ALERT*\n"
                            f"mNAV dropped {prem_drop_pct:.1f}% from 30-day high\n"
                            f"30d High: {prem_30d_high:.2f}x → Current: {premium:.2f}x\n"
                            f"Est. Payout Haircut: ~{haircut_pct:.0f}%\n"
                            f"━━━━━━━━━━━━━━━━\n"
                            f"📊 *STRIKE ROLL RECOMMENDATION*\n"
                            f"Band shift: {old_band} → {band}\n"
                            f"Old Spec: {old_spec_str}\n"
                            f"→ New Spec: {new_spec_str}\n"
                            f"Old Safety: {old_safety_str}\n"
                            f"→ New Safety: {new_safety_str}",
                            hitl=True
                        )
                        log(f"⚠️ PREMIUM COMPRESSION ALERT: {prem_30d_high:.2f}x → {premium:.2f}x ({prem_drop_pct:.1f}%) | Roll: {old_band}→{band}")

                    elif prem_drop_pct < 10 and already_alerted:
                        # Reset alert when premium recovers to within 10% of 30d high
                        self.state["premium_compression_alerted"] = False
                        log(f"Premium compression alert reset — recovered to {premium:.2f}x")

            # ── DEFCON 1: mNAV KILL SWITCH (0.75x) ──
            # If mNAV drops below 0.75x, MSTR is trading below its BTC NAV.
            # LEAPs lose all intrinsic value. Close ALL positions immediately.
            # Stress tested: safety net fails at 0.5x, so we kill at 0.75x with margin.
            if premium > 0 and premium < 0.75:
                has_position = self.state.get("entry_price", 0) > 0
                has_adder = self.state.get("adder_entry_price", 0) > 0
                already_killed = self.state.get("mnav_kill_triggered", False)

                if (has_position or has_adder) and not already_killed:
                    log(f"🚨 DEFCON 1: mNAV KILL SWITCH TRIGGERED — premium {premium:.2f}x < 0.75x", "CRITICAL")
                    send_telegram(
                        f"🚨🚨🚨 *DEFCON 1 — mNAV KILL SWITCH*\n"
                        f"━━━━━━━━━━━━━━━━\n"
                        f"mNAV Premium: *{premium:.2f}x* (below 0.75x threshold)\n"
                        f"MSTR trading BELOW Bitcoin NAV\n"
                        f"LEAPs losing intrinsic value rapidly\n"
                        f"━━━━━━━━━━━━━━━━\n"
                        f"⚠️ *CLOSING ALL POSITIONS*\n"
                        f"This is an automatic safety exit.\n"
                        f"Stress tests show total loss below 0.5x.\n"
                        f"Killing at 0.75x to preserve capital.\n"
                        f"━━━━━━━━━━━━━━━━\n"
                        f"Manual restart required after review."
                    )

                    # Close base position
                    if has_position:
                        self._execute_exit("mNAV KILL SWITCH — premium below 0.75x", mstr_price)

                    # Close adder position
                    if has_adder:
                        self._execute_adder_exit("mNAV KILL SWITCH — premium below 0.75x", mstr_price)

                    self.state["mnav_kill_triggered"] = True
                    self.state["mnav_kill_date"] = datetime.now().isoformat()
                    self.state["mnav_kill_premium"] = premium
                    self._save_state()

                    log("🚨 ALL POSITIONS CLOSED — mNAV kill switch. Manual restart required.")
                    return  # Stop evaluation — system is in emergency mode

                elif not has_position and not has_adder and not already_killed:
                    # No positions but premium is dangerous — block new entries
                    log(f"⚠️ mNAV {premium:.2f}x < 0.75x — ENTRY BLOCKED (DEFCON 1 zone)")
                    send_telegram(
                        f"⚠️ *mNAV ENTRY BLOCK*\n"
                        f"Premium {premium:.2f}x is below 0.75x threshold.\n"
                        f"No new entries permitted until premium recovers above 1.0x."
                    )
                    return  # Don't evaluate — no entries in DEFCON zone

            # Reset kill switch if premium recovers above 1.0x
            if premium >= 1.0 and self.state.get("mnav_kill_triggered", False):
                self.state["mnav_kill_triggered"] = False
                log(f"mNAV kill switch reset — premium recovered to {premium:.2f}x")
                send_telegram(f"✅ *mNAV Kill Switch Reset*\nPremium recovered to {premium:.2f}x\nEntries permitted again.")

            # Update 200W dip+reclaim
            self.update_dip_reclaim(weekly_closes, weekly_opens)

            # Check if we have a position
            has_position = self.state.get("entry_price", 0) > 0

            # Check TradingView confluence signal
            tv_has_signal, tv_signal = self.check_tv_signal()

            if has_position:
                # Manage existing position
                log("Managing existing position...")
                self.manage_position(mstr_price, btc_price, daily_closes, gbtc_closes)

                # ── TREND CONFIRMATION SCALE-UP ──
                # If we have a base position but no trend adder yet, check for golden cross
                if (self.trend_adder_enabled
                        and not self.state.get("trend_adder_active", False)
                        and len(weekly_closes) >= 204):
                    confirmed, _, ema50, sma200, dist = self.check_trend_confirmation(weekly_closes)
                    adder_status = f"GoldenCross={'Y' if confirmed else 'N'} EMA50=${ema50:.2f if ema50 else 0} Dist={dist:.1f}%"
                    log(f"TREND CHECK: {adder_status}")
                    self.state["trend_adder_status"] = adder_status

                    if confirmed:
                        log("TREND CONFIRMED — Scaling up position")
                        self._execute_trend_adder(mstr_price, btc_price)

                # Manage trend adder position (separate wider stops)
                if self.state.get("trend_adder_active", False):
                    self.manage_trend_adder(mstr_price, btc_price, weekly_closes)

                # TV EXIT signal — immediate sell if TV says exit while in position
                if tv_has_signal and tv_signal and tv_signal.get("action", "").upper() in ("SELL", "EXIT"):
                    log("TV EXIT SIGNAL — TradingView triggered exit confirmation")
                    send_telegram(
                        f"📡 *TV EXIT CONFIRMED*\n"
                        f"TradingView exit signal aligns with position.\n"
                        f"Price: ${mstr_price:.2f}"
                    )
                    self.consume_tv_signal()
            else:
                # Check entry filters
                all_pass, filters = self.check_entry_filters(
                    mstr_price, btc_price, weekly_closes, daily_closes,
                    daily_highs, daily_lows, btc_weekly, weekly_opens
                )

                # TV confluence status
                tv_buy = tv_has_signal and tv_signal and tv_signal.get("action", "").upper() == "BUY"

                # Log filter status with System 13 regime context
                regime_ml = self.state.get("regime_ml", {})
                regime_str = f"{regime_ml.get('regime', '?')}({regime_ml.get('confidence', 0)*100:.0f}%)" if regime_ml else "N/A"
                log(f"FILTERS: Armed={filters['armed']} | BTC200W={filters['btc_above_200w']} | "
                    f"StRSI={filters['stoch_rsi']}({filters['stoch_rsi_ok']}) | "
                    f"Prem={filters['premium']}({filters['premium_ok']}) | "
                    f"PremExp={filters['premium_expanding']} | NoDiv={filters['no_macd_div']} | "
                    f"ATR={filters['atr_quiet']} | ALL={filters['all_pass']} | "
                    f"TV={'BUY' if tv_buy else 'none'} | Regime={regime_str}")

                # Save live data to state for dashboard consumption
                self.state["last_mstr_price"] = mstr_price
                self.state["last_btc_price"] = btc_price
                try:
                    self.state["last_premium"] = round(float(filters.get("premium", 0)), 4)
                except (TypeError, ValueError):
                    self.state["last_premium"] = 0.0
                try:
                    self.state["last_stoch_rsi"] = round(float(filters.get("stoch_rsi", 0)), 1)
                except (TypeError, ValueError):
                    self.state["last_stoch_rsi"] = 0.0
                self.state["last_eval"] = datetime.now().isoformat()

                # Save System 13 regime context to state
                if regime_ml:
                    self.state["last_regime"] = regime_ml.get("regime", "UNKNOWN")
                    self.state["last_regime_confidence"] = regime_ml.get("confidence", 0)

                self._save_state()

                if all_pass:
                    first_done = self.state.get("first_entry_done", False)
                    second_done = self.state.get("second_entry_done", False)

                    confluence = "IBKR+TV" if tv_buy else "IBKR-only"
                    log(f"ENTRY SIGNAL — Confluence: {confluence}")

                    if tv_buy:
                        send_telegram(
                            f"🎯 *DOUBLE CONFLUENCE ENTRY*\n"
                            f"Both IBKR filters AND TradingView agree!\n"
                            f"MSTR: ${mstr_price:.2f} | Premium: {premium:.2f}x"
                        )
                        self.consume_tv_signal()

                    if not first_done:
                        self.state["entry_date"] = datetime.now().isoformat()
                        self.state["entry_confluence"] = confluence
                        self._execute_entry(mstr_price, btc_price, 1)
                    elif first_done and not second_done:
                        self._execute_entry(mstr_price, btc_price, 2)

            # Save state
            self.state["last_eval"] = datetime.now().isoformat()
            self.state["last_mstr_price"] = mstr_price
            self.state["last_btc_price"] = btc_price
            self._save_state()

            log(f"Evaluation complete. Next: {'position management' if has_position else 'waiting for signal'}")

        except (ConnectionError, OSError) as e:
            # Socket disconnect — force reconnect and retry once
            log(f"Connection lost during evaluation: {e}", "WARN")
            log("Attempting reconnect and retry...")
            self.ib = None  # Force fresh connection
            if self.ensure_connected():
                log("Reconnected — retrying evaluation")
                try:
                    self.evaluate()  # One retry
                except Exception as retry_e:
                    log(f"Retry also failed: {retry_e}", "ERROR")
                    send_telegram(f"🔴 Rudy v2.8+ evaluation failed after reconnect:\n{str(retry_e)[:200]}")
            else:
                send_telegram(f"🔴 Rudy v2.8+ evaluation error: Socket disconnect — TWS may be down")
        except Exception as e:
            log(f"Evaluation error: {e}", "ERROR")
            log(traceback.format_exc(), "ERROR")
            send_telegram(f"🔴 Rudy v2.8+ evaluation error:\n{str(e)[:200]}")

    # ══════════════════════════════════════════════════════════════
    #  SAFETY LAYER — Daily Loss Limit, Consecutive Loss Shutdown,
    #  Self-Evaluation Loop (does NOT modify v2.8+ strategy logic)
    # ══════════════════════════════════════════════════════════════

    SAFETY_LOG = os.path.join(LOG_DIR, "safety_events.json")
    DAILY_LOSS_LIMIT_PCT = 2.0        # Pause trading if down 2% intraday
    CONSECUTIVE_LOSS_LIMIT = 5        # Pause after 5 consecutive stop-outs
    SELF_EVAL_INTERVAL_HOURS = 4      # Self-evaluation every 4 hours

    # ══════════════════════════════════════════════════════════════
    #  CYCLE INTELLIGENCE — Seasonality + Sentinel Integration
    #  Does NOT modify entry/exit logic. Adjusts WHEN to check.
    # ══════════════════════════════════════════════════════════════

    def get_regime_state(self):
        """Read System 13 Neural Regime Classifier output.
        Returns dict with current_regime, confidence, all_probabilities, etc.
        Returns empty dict if unavailable or stale (>7 days old)."""
        regime_file = os.path.join(DATA_DIR, "regime_state.json")
        try:
            if os.path.exists(regime_file):
                with open(regime_file) as f:
                    data = json.load(f)
                # Check staleness — System 13 should update at least weekly
                last_updated = data.get("last_updated", "")
                if last_updated:
                    updated_dt = datetime.fromisoformat(last_updated)
                    if (datetime.now() - updated_dt).days > 7:
                        log("System 13 regime data is STALE (>7 days) — falling back to threshold", "WARN")
                        return {}
                return data
        except Exception:
            pass
        return {}

    def detect_cycle_phase(self, btc_price=0):
        """Detect market phase using System 13 ML classifier (primary) or
        BTC price thresholds (fallback). Returns 'bull' or 'bear' for seasonality,
        plus stores the full 4-regime detail in state."""

        # ── PRIMARY: System 13 Neural Regime Classifier ──
        regime = self.get_regime_state()
        if regime and regime.get("current_regime"):
            ml_regime = regime["current_regime"]
            ml_confidence = regime.get("confidence", 0)
            ml_probs = regime.get("all_probabilities", {})

            # Store full regime detail in state for dashboard/alerts
            self.state["regime_ml"] = {
                "regime": ml_regime,
                "confidence": ml_confidence,
                "probabilities": ml_probs,
                "source": "system_13",
            }

            # Map 4-regime to bull/bear for seasonality table
            if ml_regime in ("ACCUMULATION", "MARKUP"):
                return "bull"
            elif ml_regime in ("DISTRIBUTION", "MARKDOWN"):
                return "bear"

        # ── FALLBACK: Threshold-based detection ──
        log("System 13 unavailable — using threshold-based phase detection", "WARN")

        if btc_price <= 0:
            sentinel_file = os.path.join(DATA_DIR, "btc_sentinel_state.json")
            try:
                with open(sentinel_file) as f:
                    btc_price = json.load(f).get("last_price", 0)
            except Exception:
                pass
        if btc_price <= 0:
            btc_price = self.state.get("last_btc_price", 0)

        if btc_price <= 0:
            return "bear"  # Default to cautious

        above_bb_line = btc_price > BTC_BULL_BEAR_LINE
        # ATH from state (tracked dynamically from IBKR data), not hardcoded
        btc_ath = self.state.get("btc_ath", 126200)
        if btc_price > btc_ath:
            btc_ath = btc_price
            self.state["btc_ath"] = btc_ath
        dd_from_ath = (btc_ath - btc_price) / btc_ath * 100
        shallow_dd = dd_from_ath < 25

        if above_bb_line and shallow_dd:
            phase = "bull"
        elif not above_bb_line and dd_from_ath > 40:
            phase = "bear"
        else:
            phase = "bull" if btc_price > BTC_200W_SMA_APPROX * 1.5 else "bear"

        self.state["regime_ml"] = {
            "regime": "MARKUP" if phase == "bull" else "MARKDOWN",
            "confidence": 0,
            "probabilities": {},
            "source": "threshold_fallback",
        }
        return phase

    def get_cycle_context(self):
        """Return current month's phase-aware seasonality data and sentinel status."""
        month = datetime.now().month
        season = BTC_SEASONALITY.get(month, {})

        # Read sentinel state for weekend BTC moves
        sentinel_file = os.path.join(DATA_DIR, "btc_sentinel_state.json")
        sentinel = {}
        if os.path.exists(sentinel_file):
            try:
                with open(sentinel_file) as f:
                    sentinel = json.load(f)
            except Exception:
                pass

        btc_price = sentinel.get("last_price", 0) or self.state.get("last_btc_price", 0)
        phase = self.detect_cycle_phase(btc_price)
        phase_data = season.get(phase, ("Unknown", "WATCH", 0))
        behavior, action, avg_ret = phase_data

        # Determine if this is a high-alert month for the current phase
        high_alert_set = BULL_HIGH_ALERT if phase == "bull" else BEAR_HIGH_ALERT
        is_high_alert = month in high_alert_set

        # Proximity to key MAs (how close is BTC to trigger zones)
        btc_ath = self.state.get("btc_ath", 126200)
        dist_200w = ((btc_price - BTC_200W_SMA_APPROX) / BTC_200W_SMA_APPROX * 100) if btc_price > 0 else 0
        dist_250w = ((btc_price - BTC_250W_MA_APPROX) / BTC_250W_MA_APPROX * 100) if btc_price > 0 else 0
        dist_300w = ((btc_price - BTC_300W_MA_APPROX) / BTC_300W_MA_APPROX * 100) if btc_price > 0 else 0

        # Proximity zones for Telegram context
        proximity_zone = "ABOVE ALL MAs"
        if btc_price <= BTC_300W_MA_APPROX:
            proximity_zone = "🚨 BELOW 300W MA — ABSOLUTE FLOOR ZONE"
        elif btc_price <= BTC_250W_MA_APPROX:
            proximity_zone = "🔴 BELOW 250W MA — CAPITULATION ZONE"
        elif btc_price <= BTC_200W_SMA_APPROX:
            proximity_zone = "⚡ BELOW 200W SMA — v2.8+ ARM ZONE"
        elif dist_200w < 10:
            proximity_zone = f"⚠️ APPROACHING 200W SMA ({dist_200w:+.1f}%)"
        elif dist_200w < 20:
            proximity_zone = f"NEARING 200W SMA ({dist_200w:+.1f}%)"

        return {
            "month": month,
            "phase": phase,
            "behavior": behavior,
            "action": action,
            "avg_return": avg_ret,
            "is_high_alert": is_high_alert,
            "sentinel_btc": sentinel.get("last_price", 0),
            "sentinel_anchor": sentinel.get("anchor_price", 0),
            "sentinel_change_pct": sentinel.get("change_from_anchor_pct", 0),
            "sentinel_200w_sma": sentinel.get("sma_200w", 0),
            "dd_from_ath": ((btc_ath - btc_price) / btc_ath * 100) if btc_price > 0 else 0,
            "dist_200w_pct": dist_200w,
            "dist_250w_pct": dist_250w,
            "dist_300w_pct": dist_300w,
            "btc_250w_ma": BTC_250W_MA_APPROX,
            "btc_300w_ma": BTC_300W_MA_APPROX,
            "proximity_zone": proximity_zone,
        }

    def check_sentinel_for_early_eval(self):
        """Check if weekend BTC move warrants an early Monday evaluation.
        Called at 9:30 AM Monday. If BTC dropped >5% over weekend, run evaluate() now."""
        ctx = self.get_cycle_context()
        btc_change = ctx["sentinel_change_pct"]
        btc_price = ctx["sentinel_btc"]
        sma_200w = ctx["sentinel_200w_sma"]

        if abs(btc_change) < 5:
            log(f"Monday sentinel check: BTC moved {btc_change:+.1f}% over weekend — no early eval needed")
            return

        log(f"⚡ SENTINEL TRIGGER: BTC moved {btc_change:+.1f}% over weekend (${btc_price:,.0f})")

        # Check if BTC is near or below 200W SMA
        near_sma = sma_200w > 0 and btc_price < sma_200w * 1.15
        below_sma = sma_200w > 0 and btc_price < sma_200w

        if below_sma:
            log(f"🚨 BTC BELOW 200W SMA (${btc_price:,.0f} < ${sma_200w:,.0f}) — ENTRY SIGNAL ZONE")
            send_telegram(
                f"🚨 *MONDAY OPEN: BTC BELOW 200W SMA*\n"
                f"BTC: ${btc_price:,.0f} | 200W SMA: ${sma_200w:,.0f}\n"
                f"Weekend move: {btc_change:+.1f}%\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"⚡ v2.8+ entry signal may fire TODAY\n"
                f"Running immediate evaluation..."
            )
        elif near_sma:
            send_telegram(
                f"⚠️ *MONDAY OPEN: BTC Approaching 200W SMA*\n"
                f"BTC: ${btc_price:,.0f} | 200W SMA: ${sma_200w:,.0f}\n"
                f"Gap: {((btc_price - sma_200w) / sma_200w * 100):.1f}%\n"
                f"Weekend move: {btc_change:+.1f}%\n"
                f"Running early evaluation..."
            )
        else:
            send_telegram(
                f"⚡ *MONDAY OPEN: Significant BTC Move*\n"
                f"BTC: ${btc_price:,.0f} | Weekend: {btc_change:+.1f}%\n"
                f"Running early evaluation..."
            )

        # Run evaluation immediately
        log("Running early evaluation triggered by sentinel...")
        self.evaluate()

    def log_seasonality_context(self):
        """Log current month's phase-aware cycle intelligence at each evaluation.
        Includes System 13 regime classifier data when available."""
        ctx = self.get_cycle_context()
        month_names = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",
                       7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec"}
        month_name = month_names.get(ctx["month"], "?")
        phase_emoji = "🟢" if ctx["phase"] == "bull" else "🔴"
        alert_str = "⚡ HIGH ALERT" if ctx["is_high_alert"] else "Standard"

        log(f"CYCLE INTEL: {month_name} | Phase: {phase_emoji} {ctx['phase'].upper()} | "
            f"Action: {ctx['action']} | Hist avg: {ctx['avg_return']:+.1f}% | {alert_str}")
        log(f"  → {ctx['behavior']}")

        # System 13 regime detail
        regime_ml = self.state.get("regime_ml", {})
        if regime_ml and regime_ml.get("source") == "system_13":
            regime = regime_ml["regime"]
            conf = regime_ml["confidence"]
            probs = regime_ml.get("probabilities", {})
            regime_colors = {"ACCUMULATION": "🔵", "MARKUP": "🟢", "DISTRIBUTION": "🟡", "MARKDOWN": "🔴"}
            emoji = regime_colors.get(regime, "⚪")
            log(f"  → System 13: {emoji} {regime} ({conf*100:.1f}% confidence)")
            # Show transition pressure if any secondary regime is significant
            for r, p in sorted(probs.items(), key=lambda x: -x[1]):
                if r != regime and p > 0.10:
                    log(f"  → Transition pressure: {r} at {p*100:.1f}%")
        elif regime_ml:
            log(f"  → Phase detection: threshold fallback (System 13 unavailable)")

        if ctx["sentinel_btc"]:
            log(f"  → BTC: ${ctx['sentinel_btc']:,.0f} | ATH DD: {ctx['dd_from_ath']:.1f}%")

    def _log_safety_event(self, event_type, details):
        """Append safety event to log for dashboard consumption."""
        try:
            events = []
            if os.path.exists(self.SAFETY_LOG):
                with open(self.SAFETY_LOG) as f:
                    events = json.load(f)
            events.append({
                "time": datetime.now().isoformat(),
                "type": event_type,
                "details": details
            })
            # Keep last 100 events
            events = events[-100:]
            with open(self.SAFETY_LOG, "w") as f:
                json.dump(events, f, indent=2)
        except Exception:
            pass

    def check_daily_loss_limit(self):
        """Check if account is down more than 2% from today's opening NLV.
        Returns True if SAFE to trade, False if PAUSED."""
        today = datetime.now().strftime("%Y-%m-%d")
        safety = self.state.get("safety", {})

        # If already paused today, check if it's a new day
        if safety.get("daily_loss_paused_date") == today:
            log("⛔ DAILY LOSS LIMIT: Trading paused for today", "WARN")
            return False

        # Record opening NLV at first check of the day
        if safety.get("nlv_open_date") != today:
            try:
                if self.ensure_connected():
                    acct = self.ib.accountSummary()
                    for item in acct:
                        if item.tag == "NetLiquidation":
                            safety["nlv_open"] = float(item.value)
                            safety["nlv_open_date"] = today
                            self.state["safety"] = safety
                            self._save_state()
                            log(f"Daily NLV open recorded: ${safety['nlv_open']:,.2f}")
                            break
            except Exception as e:
                log(f"Could not fetch NLV for daily loss check: {e}", "WARN")
                return True  # Don't block on error

        nlv_open = safety.get("nlv_open", 0)
        if nlv_open <= 0:
            return True

        # Get current NLV
        try:
            if self.ensure_connected():
                acct = self.ib.accountSummary()
                nlv_current = 0
                for item in acct:
                    if item.tag == "NetLiquidation":
                        nlv_current = float(item.value)
                        break

                if nlv_current > 0:
                    daily_loss_pct = ((nlv_open - nlv_current) / nlv_open) * 100
                    if daily_loss_pct >= self.DAILY_LOSS_LIMIT_PCT:
                        safety["daily_loss_paused_date"] = today
                        self.state["safety"] = safety
                        self._save_state()

                        msg = (f"⛔ *DAILY LOSS LIMIT HIT*\n"
                               f"Open NLV: ${nlv_open:,.2f}\n"
                               f"Current NLV: ${nlv_current:,.2f}\n"
                               f"Loss: -{daily_loss_pct:.1f}%\n"
                               f"Trading paused until tomorrow.")
                        log(msg, "WARN")
                        send_telegram(msg)
                        self._log_safety_event("DAILY_LOSS_LIMIT", {
                            "nlv_open": nlv_open, "nlv_current": nlv_current,
                            "loss_pct": daily_loss_pct
                        })
                        return False
                    else:
                        log(f"Daily P&L: {'-' if daily_loss_pct > 0 else '+'}{abs(daily_loss_pct):.1f}% (limit: -{self.DAILY_LOSS_LIMIT_PCT}%)")
        except Exception as e:
            log(f"Daily loss check error: {e}", "WARN")

        return True

    def check_consecutive_losses(self):
        """Check if we've hit N consecutive stop-outs.
        Returns True if SAFE to trade, False if PAUSED."""
        safety = self.state.get("safety", {})

        if safety.get("consecutive_loss_paused", False):
            log("⛔ CONSECUTIVE LOSS SHUTDOWN: Awaiting manual restart", "WARN")
            return False

        consec = safety.get("consecutive_losses", 0)
        if consec >= self.CONSECUTIVE_LOSS_LIMIT:
            safety["consecutive_loss_paused"] = True
            self.state["safety"] = safety
            self._save_state()

            msg = (f"⛔ *CONSECUTIVE LOSS SHUTDOWN*\n"
                   f"{consec} consecutive stop-outs detected.\n"
                   f"Trading HALTED. Manual restart required.\n"
                   f"Approve via dashboard or Telegram to resume.")
            log(msg, "WARN")
            send_telegram(msg, hitl=True)
            self._log_safety_event("CONSECUTIVE_LOSS_SHUTDOWN", {
                "consecutive_losses": consec
            })
            return False

        return True

    def record_trade_outcome(self, is_win):
        """Track consecutive wins/losses for safety shutdown."""
        safety = self.state.get("safety", {})
        if is_win:
            safety["consecutive_losses"] = 0
            safety["consecutive_wins"] = safety.get("consecutive_wins", 0) + 1
        else:
            safety["consecutive_wins"] = 0
            safety["consecutive_losses"] = safety.get("consecutive_losses", 0) + 1
        safety["total_trades"] = safety.get("total_trades", 0) + 1
        safety["total_wins"] = safety.get("total_wins", 0) + (1 if is_win else 0)
        self.state["safety"] = safety
        self._save_state()
        log(f"Trade outcome: {'WIN' if is_win else 'LOSS'} | "
            f"Consecutive: {'W' if is_win else 'L'}{safety.get('consecutive_wins' if is_win else 'consecutive_losses', 0)} | "
            f"Overall: {safety.get('total_wins', 0)}/{safety.get('total_trades', 0)}")

    def self_evaluate(self):
        """Self-evaluation loop — runs every 4 hours.
        Compares recent performance against expectations.
        Does NOT modify v2.8+ parameters (they are LOCKED).
        Only alerts on anomalies."""
        log(f"\n{'='*40}")
        log(f"SELF-EVALUATION — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        log(f"{'='*40}")

        try:
            safety = self.state.get("safety", {})
            total_trades = safety.get("total_trades", 0)
            total_wins = safety.get("total_wins", 0)
            consec_losses = safety.get("consecutive_losses", 0)
            consec_wins = safety.get("consecutive_wins", 0)
            win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0

            # Check daemon health
            last_eval = self.state.get("last_eval", "")
            if last_eval:
                try:
                    last_dt = datetime.fromisoformat(last_eval)
                    hours_since = (datetime.now() - last_dt).total_seconds() / 3600
                    if hours_since > 24 and datetime.now().weekday() < 5:  # Weekday
                        msg = (f"⚠️ *SELF-EVAL: STALE DAEMON*\n"
                               f"Last evaluation was {hours_since:.0f} hours ago.\n"
                               f"Daemon may be stuck or disconnected.")
                        log(msg, "WARN")
                        send_telegram(msg)
                        self._log_safety_event("STALE_DAEMON", {"hours_since": hours_since})
                except Exception:
                    pass

            # Check win rate anomaly (only meaningful after 10+ trades)
            if total_trades >= 10:
                # v2.8+ expected win rate is ~24-30% (from backtest)
                if win_rate > 80:
                    msg = (f"⚠️ *SELF-EVAL: SUSPICIOUS WIN RATE*\n"
                           f"Win rate: {win_rate:.0f}% over {total_trades} trades\n"
                           f"Expected: 24-30% (from v2.8+ backtest)\n"
                           f"Possible lookahead bias or data issue!")
                    log(msg, "WARN")
                    send_telegram(msg)
                    self._log_safety_event("SUSPICIOUS_WIN_RATE", {
                        "win_rate": win_rate, "trades": total_trades
                    })
                elif win_rate < 10:
                    msg = (f"⚠️ *SELF-EVAL: POOR PERFORMANCE*\n"
                           f"Win rate: {win_rate:.0f}% over {total_trades} trades\n"
                           f"Expected: 24-30%\n"
                           f"Review recent trades for execution issues.")
                    log(msg, "WARN")
                    send_telegram(msg)
                    self._log_safety_event("POOR_PERFORMANCE", {
                        "win_rate": win_rate, "trades": total_trades
                    })

            # Check connection health
            connected = self.ib is not None and self.ib.isConnected()
            if not connected:
                msg = "⚠️ *SELF-EVAL: TWS DISCONNECTED* — Attempting reconnect..."
                log(msg, "WARN")
                send_telegram(msg)
                self._log_safety_event("TWS_DISCONNECTED", {})
                self.connect()

            # Check position reconciliation
            if self.state.get("entry_price", 0) > 0:
                try:
                    if self.ensure_connected():
                        positions = self.ib.positions()
                        mstr_qty = sum(int(p.position) for p in positions
                                       if p.contract.symbol == "MSTR" and p.contract.secType == "STK")
                        state_qty = self.state.get("position_qty", 0)
                        if mstr_qty != state_qty:
                            msg = (f"⚠️ *SELF-EVAL: POSITION MISMATCH*\n"
                                   f"IBKR: {mstr_qty} shares\n"
                                   f"State: {state_qty} shares\n"
                                   f"Investigate immediately!")
                            log(msg, "WARN")
                            send_telegram(msg)
                            self._log_safety_event("POSITION_MISMATCH", {
                                "ibkr": mstr_qty, "state": state_qty
                            })
                except Exception as e:
                    log(f"Self-eval position check error: {e}", "WARN")

            # Log summary
            summary = (f"Self-eval complete | Trades: {total_trades} | "
                       f"Wins: {total_wins} ({win_rate:.0f}%) | "
                       f"ConsecL: {consec_losses} ConsecW: {consec_wins} | "
                       f"Connected: {connected}")
            log(summary)
            self._log_safety_event("SELF_EVAL_OK", {
                "trades": total_trades, "win_rate": win_rate,
                "consec_losses": consec_losses, "connected": connected
            })

        except Exception as e:
            log(f"Self-evaluation error: {e}", "ERROR")

    def reset_consecutive_loss_pause(self):
        """Manual reset for consecutive loss shutdown (called via HITL)."""
        safety = self.state.get("safety", {})
        safety["consecutive_loss_paused"] = False
        safety["consecutive_losses"] = 0
        self.state["safety"] = safety
        self._save_state()
        log("Consecutive loss pause RESET by operator")
        send_telegram("✅ *Consecutive loss shutdown cleared.* Trading resumed.")
        self._log_safety_event("CONSEC_LOSS_RESET", {})

    # ══════════════════════════════════════════════════════════════
    #  DAEMON / SCHEDULER
    # ══════════════════════════════════════════════════════════════

    def run_daemon(self):
        """Run as scheduled daemon."""
        log(f"\n{'='*60}")
        log(f"RUDY v2.8+ TREND ADDER — STANDALONE DAEMON")
        log(f"Mode: {self.mode.upper()} | Resolution: {self.resolution}")
        log(f"Port: {self.port} | State: {STATE_FILE}")
        log(f"{'='*60}\n")

        send_telegram(
            f"🤖 *Rudy v2.8+ Daemon Started*\n"
            f"Mode: {self.mode.upper()}\n"
            f"Resolution: {self.resolution}\n"
            f"Port: {self.port}"
        )

        # ── Monday 9:30 AM: Sentinel check (weekend BTC moves → early eval) ──
        schedule.every().monday.at("09:30").do(self.check_sentinel_for_early_eval)
        log("Scheduled: Monday 9:30 AM sentinel check (early eval on weekend BTC moves)")

        # ── Core evaluation schedule ──
        if self.resolution == "weekly":
            schedule.every().friday.at("15:45").do(self.evaluate)
            log("Scheduled: Every Friday at 15:45 ET")
        elif self.resolution == "daily":
            schedule.every().monday.at("15:45").do(self.evaluate)
            schedule.every().tuesday.at("15:45").do(self.evaluate)
            schedule.every().wednesday.at("15:45").do(self.evaluate)
            schedule.every().thursday.at("15:45").do(self.evaluate)
            schedule.every().friday.at("15:45").do(self.evaluate)
            log("Scheduled: Every weekday at 15:45 ET")

        # ── Phase-aware high-alert month bonus evaluations ──
        # In bear markets: Jun, Aug, Sep, Oct, Nov → dip zone + traps
        # In bull markets: Sep, Oct, Nov → entry zone + parabolic
        # When high-alert, evaluate every 2 hours instead of once/day.
        ctx = self.get_cycle_context()
        current_month = datetime.now().month
        if ctx["is_high_alert"]:
            phase_emoji = "🟢" if ctx["phase"] == "bull" else "🔴"
            log(f"⚡ HIGH ALERT MONTH ({datetime.now().strftime('%B')}) — "
                f"Phase: {ctx['phase'].upper()} | {ctx['behavior']} | "
                f"Adding 2-hour eval schedule")
            for day_fn in [schedule.every().monday, schedule.every().tuesday,
                           schedule.every().wednesday, schedule.every().thursday,
                           schedule.every().friday]:
                day_fn.at("09:45").do(self.evaluate)
                day_fn.at("11:45").do(self.evaluate)
                day_fn.at("13:45").do(self.evaluate)
                # 15:45 already scheduled above
            log("Scheduled: High-alert evals at 09:45, 11:45, 13:45, 15:45 ET")
            send_telegram(
                f"⚡ *HIGH ALERT MONTH: {datetime.now().strftime('%B')}*\n"
                f"Phase: {phase_emoji} {ctx['phase'].upper()}\n"
                f"Behavior: {ctx['behavior']}\n"
                f"Action: {ctx['action']} | Hist avg: {ctx['avg_return']:+.1f}%\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"Evaluation frequency: every 2 hours\n"
                f"Catching signals faster."
            )

        # Self-evaluation every 4 hours during market hours (10am, 2pm)
        schedule.every().monday.at("10:00").do(self.self_evaluate)
        schedule.every().monday.at("14:00").do(self.self_evaluate)
        schedule.every().tuesday.at("10:00").do(self.self_evaluate)
        schedule.every().tuesday.at("14:00").do(self.self_evaluate)
        schedule.every().wednesday.at("10:00").do(self.self_evaluate)
        schedule.every().wednesday.at("14:00").do(self.self_evaluate)
        schedule.every().thursday.at("10:00").do(self.self_evaluate)
        schedule.every().thursday.at("14:00").do(self.self_evaluate)
        schedule.every().friday.at("10:00").do(self.self_evaluate)
        schedule.every().friday.at("14:00").do(self.self_evaluate)
        log("Scheduled: Self-evaluation every 4 hours (10:00, 14:00 ET weekdays)")

        # Run first evaluation immediately
        log("Running initial evaluation...")
        self.evaluate()

        # Keep running
        _force_eval_file = os.path.join(DATA_DIR, "force_eval.json")
        while True:
            try:
                # ── Force eval signal from MCP / Commander ──
                if os.path.exists(_force_eval_file):
                    try:
                        os.remove(_force_eval_file)
                        log("Force eval triggered by Commander via MCP")
                        self.evaluate()
                    except Exception as _fe_e:
                        log(f"Force eval error: {_fe_e}", "ERROR")

                schedule.run_pending()
                time.sleep(30)
            except KeyboardInterrupt:
                log("Shutdown requested")
                self.disconnect()
                break
            except Exception as e:
                log(f"Scheduler error: {e}", "ERROR")
                time.sleep(60)

    # ══════════════════════════════════════════════════════════════
    #  STATE PERSISTENCE
    # ══════════════════════════════════════════════════════════════

    def _load_state(self):
        """Load state from disk."""
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    state = json.load(f)
                log(f"Loaded state from {STATE_FILE}")
                return state
            except Exception as e:
                log(f"Failed to load state: {e}", "WARN")
        return {
            "is_armed": False,
            "dipped_below_200w": False,
            "green_week_count": 0,
            "already_entered_this_cycle": False,
            "first_entry_done": False,
            "second_entry_done": False,
            "entry_price": 0,
            "position_hwm": 0,
            "peak_gain_pct": 0,
            "premium_hwm": 0,
            "bars_in_trade": 0,
            "euphoria_sell_done": False,
            "position_qty": 0,
            "premium_history": [],
            "btc_weekly_closes": [],
            "trade_log": [],
            "pt_hits": [False] * 4,
            # Trend confirmation scale-up
            "golden_cross_weeks": 0,
            "trend_adder_active": False,
            "trend_adder_entry_price": 0,
            "trend_adder_qty": 0,
            "trend_adder_hwm": 0,
            "trend_adder_peak_gain": 0,
            "trend_confirmed_logged": False,
        }

    def _save_state(self):
        """Save state to disk."""
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(self.state, f, indent=2, default=str)
        except Exception as e:
            log(f"Failed to save state: {e}", "ERROR")

    def show_status(self):
        """Display current status."""
        print(f"\n{'='*60}")
        print(f"  RUDY v2.8+ DYNAMIC BLEND + TREND ADDER — STATUS")
        print(f"{'='*60}")
        print(f"  Mode:        {self.mode}")
        print(f"  Resolution:  {self.resolution}")
        print(f"  Armed:       {self.state.get('is_armed', False)}")
        print(f"  Dipped:      {self.state.get('dipped_below_200w', False)}")
        print(f"  Green Weeks: {self.state.get('green_week_count', 0)}")
        print(f"  In Position: {'YES' if self.state.get('entry_price', 0) > 0 else 'NO'}")

        if self.state.get("entry_price", 0) > 0:
            print(f"  Entry Price: ${self.state['entry_price']:.2f}")
            print(f"  Position Qty:{self.state.get('position_qty', 0)}")
            print(f"  HWM:         ${self.state.get('position_hwm', 0):.2f}")
            print(f"  Bars Held:   {self.state.get('bars_in_trade', 0)}")

        print(f"\n  ── Trend Confirmation Scale-Up ──")
        print(f"  Enabled:     {self.trend_adder_enabled}")
        gc_weeks = self.state.get('golden_cross_weeks', 0)
        print(f"  Golden Cross: {gc_weeks}/{self.trend_confirm_weeks} weeks ({'CONFIRMED' if gc_weeks >= self.trend_confirm_weeks else 'waiting'})")
        print(f"  Adder Active:{self.state.get('trend_adder_active', False)}")
        if self.state.get("trend_adder_active", False):
            ae = self.state.get('trend_adder_entry_price', 0)
            print(f"  Adder Entry: ${ae:.2f}")
            print(f"  Adder Qty:   {self.state.get('trend_adder_qty', 0)}")
            print(f"  Adder HWM:   ${self.state.get('trend_adder_hwm', 0):.2f}")

        print(f"\n  Last Eval:   {self.state.get('last_eval', 'Never')}")
        print(f"  Last MSTR:   ${self.state.get('last_mstr_price', 0):.2f}")
        print(f"  Last BTC:    ${self.state.get('last_btc_price', 0):,.0f}")
        print(f"  Trades:      {len(self.state.get('trade_log', []))}")
        print(f"{'='*60}\n")


# ══════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Rudy v2.8 Dynamic Blend — Direct IBKR Trader")
    parser.add_argument("--mode", choices=["live"], default="live",
                        help="Trading mode (only live permitted)")
    parser.add_argument("--resolution", choices=["weekly", "daily"], default="weekly",
                        help="Evaluation frequency (default: weekly)")
    parser.add_argument("--test", action="store_true",
                        help="Test mode — connect, fetch data, show filters, no trades")
    parser.add_argument("--status", action="store_true",
                        help="Show current state and exit")
    parser.add_argument("--eval-once", action="store_true",
                        help="Run one evaluation and exit (no daemon)")
    parser.add_argument("--confirm-live", action="store_true",
                        help="Skip interactive live mode confirmation (for daemon startup)")

    args = parser.parse_args()

    if args.mode == "live" and not args.confirm_live:
        print("\n" + "=" * 60)
        print("  ⚠️  LIVE MODE — REAL MONEY AT RISK")
        print("=" * 60)
        confirm = input("Type 'LIVE' to confirm: ")
        if confirm != "LIVE":
            print("Cancelled.")
            sys.exit(1)

    # ── Lockfile: prevent duplicate daemons ──
    lock_fd = None
    if not args.test and not args.status:
        try:
            lock_fd = open(LOCKFILE, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_fd.write(f"{os.getpid()}\n")
            lock_fd.flush()
            log("Lockfile acquired — no duplicate daemons allowed")
        except (IOError, OSError):
            print(f"❌ BLOCKED: Another trader_v28 instance is already running.")
            print(f"   Lockfile: {LOCKFILE}")
            print(f"   Kill the other instance first, or delete the lockfile.")
            sys.exit(1)

    trader = RudyV28(mode=args.mode, resolution=args.resolution, test_mode=args.test)

    if args.status:
        trader.show_status()
        return

    if args.test:
        log("TEST MODE — no orders will be placed")
        if not trader.connect():
            log("Could not connect to TWS", "ERROR")
            sys.exit(1)
        trader.evaluate()
        trader.disconnect()
        return

    if args.eval_once:
        if not trader.connect():
            sys.exit(1)
        trader.evaluate()
        trader.disconnect()
        return

    # Daemon mode
    trader.run_daemon()


if __name__ == "__main__":
    main()
