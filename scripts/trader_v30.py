#!/usr/bin/env python3
"""Rudy v3.0 Trend Convergence — Standalone IBKR Direct Trader

MSTR Trend Convergence Entry Strategy — runs directly against TWS via ib_insync.
No QuantConnect dependency. Self-contained signal generation + execution.

Entry: Golden cross (50W EMA > 200W SMA) + both rising + convergence < 15% + green candle.
Exit:  Convergence-down (both 50W EMA and 200W SMA falling + close together). Primary exit.
       Trailing stops are wide safety nets only.

Usage:
    # Test mode — connect, fetch data, show filter status, no trades:
    python3 trader_v30.py --test

    # Paper trading daemon (weekly evaluation):
    python3 trader_v30.py --mode paper --resolution weekly

    # Paper trading daemon (daily evaluation):
    python3 trader_v30.py --mode paper --resolution daily

    # Show current state:
    python3 trader_v30.py --status

Requires:
    - IBKR TWS running on port 7496 (paper) or 7496 (live)
    - pip3 install ib_insync pandas numpy requests schedule
"""
# ══════════════════════════════════════════════════════════════
# AUTHORITY LOCK — Rudy v2.0 Constitution v50.0
# This script is NOT authorized to execute trades.
# Authorized traders: trader_v28.py (Trader1/v2.8+),
#                     trader2_mstr_put.py (Trader2),
#                     trader3_spy_put.py (Trader3)
# To re-authorize this script, edit this block explicitly.
# ══════════════════════════════════════════════════════════════
import sys as _sys
_sys.exit(0)

import os
import sys
import json
import time
import math
import argparse
import signal
import traceback
from datetime import datetime, timedelta
from collections import deque

import numpy as np
import pandas as pd
import requests
import schedule
from ib_insync import IB, Stock, util

# ── Project imports ──
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from broker_base import Order, Fill

# ── Paths ──
LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
STATE_FILE = os.path.join(DATA_DIR, "trader_v30_state.json")
TV_SIGNAL_FILE = os.path.join(DATA_DIR, "tv_signal_v30.json")
LOG_FILE = os.path.join(LOG_DIR, "trader_v30.log")
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


def send_telegram(msg):
    """Send Telegram alert (best-effort)."""
    try:
        sys.path.insert(0, os.path.expanduser("~/rudy/scripts"))
        import telegram as tg
        tg.send(msg)
    except Exception:
        log(f"Telegram send failed (non-critical)", "WARN")


class RudyV30:
    """Rudy v3.0 Trend Convergence — Standalone IBKR Trader.

    Trades MSTR stock as proxy, applies dynamic LEAP multiplier (3.3x-7.2x)
    based on mNAV premium. Entry on golden cross convergence, exit on
    convergence-down. Same execution infrastructure as v2.8.
    """

    def __init__(self, mode="paper", resolution="weekly", test_mode=False):
        self.mode = mode
        self.resolution = resolution  # "weekly" or "daily"
        self.test_mode = test_mode
        self.ib = None

        # ── TWS Connection ──
        self.port = 7496 if mode == "paper" else 7496
        self.client_id = 30  # unique client ID for v3.0

        # ── v3.0 Convergence Parameters (walk-forward optimal: tight_short_quick_moderate) ──
        self.sma_weekly_period = 200
        self.ema_weekly_period = 50
        self.convergence_threshold = 15.0   # % distance for convergence entry
        self.divergence_threshold = 25.0    # % distance for divergence exit
        self.slope_lookback = 3             # weeks to measure slope
        self.green_candles_required = 1     # green weekly candles needed
        self.require_golden_cross = True    # EMA50 must be above SMA200

        self.stoch_rsi_entry_threshold = 80
        self.premium_cap = 2.0              # wider than v2.8 (1.3)
        self.premium_lookback = 4

        # BTC holdings for mNAV
        self.btc_holdings = {
            2016: 0, 2017: 0, 2018: 0, 2019: 0,
            2020: 70784, 2021: 124391, 2022: 132500,
            2023: 189150, 2024: 446400, 2025: 499226, 2026: 738731,
        }
        self.diluted_shares = {
            2016: 10500000, 2017: 10500000, 2018: 10800000, 2019: 11000000,
            2020: 11500000, 2021: 11500000, 2022: 11500000,
            2023: 14500000, 2024: 182000000, 2025: 330000000, 2026: 374000000,
        }

        # v3.0 Walk-Forward Optimal: WIDE Laddered Trailing Stops (safety nets only)
        # Convergence-down is the primary exit — trails are last resort
        self.ladder_tiers = [
            (10000, 25.0),   # 100x+ → 25% trail
            (5000,  35.0),   # 50x+  → 35% trail
        ]

        # v3.0 Minimal Profit Takes — only at extreme gains
        self.profit_tiers = [
            (5000,  0.10),   # 50x  → sell 10%
            (10000, 0.15),   # 100x → sell 15%
        ]

        # LEAP multipliers: tight_conservative_tight (same as v2.8)
        # LOW (<0.7x): 7.2x | FAIR (0.7-1.0x): 6.5x | ELEVATED (1.0-1.3x): 4.8x | EUPHORIC (>1.3x): 3.3x

        # Risk parameters — WIDER than v2.8
        self.max_hold_bars = 700            # 700 bars (v2.8: 567)
        self.target_mult = 200.0
        self.initial_floor_pct = 0.55       # 45% loss floor (v2.8: 0.65 = 35%)
        self.floor_deactivate_leap_gain = 500
        self.panic_floor_pct = -60.0        # -60% LEAP (v2.8: -35%)
        self.euphoria_premium = 3.5
        self.risk_capital_pct = 0.25
        self.premium_compress_pct = 50.0    # 50% drop (v2.8: 30%)
        self.disable_ema50_exit = True      # EMA50 loss exit DISABLED in v3.0

        # Convergence-specific: min SMA slope for entry
        self.min_sma_slope_pct = 0.0

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

    def execute_with_confirmation(self, contract, order, timeout=120, max_retries=2):
        """Place order and poll until filled. Returns (success, fill_price, fill_qty, status).

        NO fire-and-forget. Polls every 2s until:
        - Filled -> return success
        - Cancelled/Inactive -> retry up to max_retries
        - Timeout -> return failure
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
                        log(f"  FILLED: {fill_qty} @ ${fill_price:.2f}")
                        return True, fill_price, int(fill_qty), "Filled"

                    if status == "PreSubmitted":
                        # Market closed — order queued for open. This is OK.
                        if time.time() - start > 10:
                            log(f"  PreSubmitted (market likely closed) — order queued for open")
                            return True, 0.0, 0, "PreSubmitted"

                    if status in ("Cancelled", "Inactive"):
                        log(f"  Order {status}: {trade.log[-1].message if trade.log else 'no message'}", "WARN")
                        break  # retry

                else:
                    # Timeout
                    log(f"  Order timeout after {timeout}s, status={status}", "WARN")
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
                msg = (f"POSITION MISMATCH after {action}\n"
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
                log(f"  Position reconciled: {symbol} qty={actual_qty} (matches expected)")

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
                    log(f"  NOT FLAT: {symbol} qty={p.position} still in IBKR", "WARN")
                    return False
            log(f"  FLAT: No {symbol} positions in IBKR")
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
        send_telegram("Rudy v3.0: Failed to connect to TWS")
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
        """Compute MSTR premium to NAV."""
        if year is None:
            year = datetime.now().year

        holdings = self.btc_holdings.get(year, self.btc_holdings.get(
            max(k for k in self.btc_holdings if k <= year), 738731))
        shares = self.diluted_shares.get(year, self.diluted_shares.get(
            max(k for k in self.diluted_shares if k <= year), 374000000))

        if holdings == 0 or shares == 0 or btc_price <= 0:
            return 1.0
        nav_per_share = (btc_price * holdings) / shares
        if nav_per_share <= 0:
            return 999
        return mstr_price / nav_per_share

    def get_dynamic_leap_multiplier(self, premium):
        """v3.0 Dynamic premium-based LEAP blend (tight_conservative_tight).
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
    #  v3.0 CONVERGENCE INDICATORS
    # ══════════════════════════════════════════════════════════════

    def compute_50w_ema(self, weekly_closes):
        """Compute 50W EMA from weekly closes list."""
        return self.compute_ema(weekly_closes, self.ema_weekly_period)

    def check_convergence(self, weekly_closes):
        """Check if 50W EMA and 200W SMA are converging with both rising.
        Requires golden cross (EMA50 > SMA200) + both slopes positive + distance < threshold.
        Returns (converging_up, converging_down, distance_pct, ema50, sma200)
        """
        if len(weekly_closes) < self.sma_weekly_period + self.slope_lookback:
            return False, False, 0.0, None, None

        # Current values
        sma200 = self.compute_sma(weekly_closes, self.sma_weekly_period)
        ema50 = self.compute_50w_ema(weekly_closes)

        if sma200 is None or ema50 is None or sma200 <= 0:
            return False, False, 0.0, ema50, sma200

        # Distance between EMA50 and SMA200 as percentage
        distance_pct = abs(ema50 - sma200) / sma200 * 100

        # Compute slopes over lookback period
        # SMA200 slope
        sma200_prev = self.compute_sma(
            weekly_closes[:-self.slope_lookback], self.sma_weekly_period
        )
        # EMA50 slope
        ema50_prev = self.compute_50w_ema(weekly_closes[:-self.slope_lookback])

        if sma200_prev is None or ema50_prev is None:
            return False, False, distance_pct, ema50, sma200

        sma200_rising = sma200 > sma200_prev
        ema50_rising = ema50 > ema50_prev
        sma200_falling = sma200 < sma200_prev
        ema50_falling = ema50 < ema50_prev

        # Golden cross check
        golden_cross = ema50 > sma200

        # SMA slope percentage check
        sma_slope_ok = True
        if self.min_sma_slope_pct > 0 and sma200_prev > 0:
            sma_slope_actual = ((sma200 - sma200_prev) / sma200_prev) * 100
            sma_slope_ok = sma_slope_actual >= self.min_sma_slope_pct

        # Converging UP: golden cross + both rising + close together
        converging_up = (
            golden_cross
            and sma200_rising
            and ema50_rising
            and distance_pct <= self.convergence_threshold
            and sma_slope_ok
        ) if self.require_golden_cross else (
            sma200_rising
            and ema50_rising
            and distance_pct <= self.convergence_threshold
            and sma_slope_ok
        )

        # Converging DOWN: both falling + close together (primary exit signal)
        converging_down = (
            sma200_falling
            and ema50_falling
            and distance_pct <= self.divergence_threshold
        )

        return converging_up, converging_down, distance_pct, ema50, sma200

    def update_convergence_state(self, weekly_closes, weekly_opens):
        """Update convergence tracking: green candles, armed state, re-entry counter.
        Called every evaluation. Replaces v2.8's update_dip_reclaim."""

        converging_up, converging_down, distance_pct, ema50, sma200 = \
            self.check_convergence(weekly_closes)

        if ema50 is None or sma200 is None:
            return

        week_close = weekly_closes[-1]
        week_open = weekly_opens[-1] if weekly_opens else week_close
        green_candle = week_close > week_open

        # Track convergence state
        prev_converging_up = self.state.get("is_converging_up", False)
        self.state["is_converging_up"] = converging_up
        self.state["mstr_50w_ema"] = ema50
        self.state["mstr_200w_sma"] = sma200
        self.state["convergence_distance_pct"] = round(distance_pct, 2)

        # Count green candles during convergence-up
        green_count = self.state.get("green_candle_count", 0)
        if converging_up and green_candle:
            green_count += 1
        elif not converging_up:
            green_count = 0
        self.state["green_candle_count"] = green_count

        # ARM when convergence-up + enough green candles
        was_armed = self.state.get("is_armed", False)
        if converging_up and green_count >= self.green_candles_required:
            if not was_armed:
                self.state["is_armed"] = True
                convergence_entries = self.state.get("convergence_entries", 0)
                log(f"ARMED: Convergence-up detected | EMA50=${ema50:.2f} SMA200=${sma200:.2f} "
                    f"dist={distance_pct:.1f}% green={green_count} entries={convergence_entries}")
                send_telegram(
                    f"Rudy v3.0 ARMED\n"
                    f"MSTR=${week_close:.2f}\n"
                    f"50W EMA=${ema50:.2f}\n"
                    f"200W SMA=${sma200:.2f}\n"
                    f"Distance: {distance_pct:.1f}%\n"
                    f"Green candles: {green_count}"
                )
        elif not converging_up:
            # Disarm when convergence breaks
            if was_armed:
                log(f"DISARMED: Convergence-up broken | EMA50=${ema50:.2f} SMA200=${sma200:.2f} "
                    f"dist={distance_pct:.1f}%")
            self.state["is_armed"] = False
            self.state["already_entered_this_cycle"] = False

        # Track convergence-down for exit signal
        self.state["is_converging_down"] = converging_down
        if converging_down:
            log(f"CONVERGENCE-DOWN: EMA50=${ema50:.2f} SMA200=${sma200:.2f} dist={distance_pct:.1f}%")

    # ══════════════════════════════════════════════════════════════
    #  ENTRY FILTERS
    # ══════════════════════════════════════════════════════════════

    def check_entry_filters(self, mstr_price, btc_price, weekly_closes, daily_closes,
                            daily_highs, daily_lows, btc_weekly_closes, weekly_opens):
        """Check all v3.0 entry filters. Returns (all_pass, filter_status_dict)."""
        year = datetime.now().year
        premium = self.compute_mstr_premium(mstr_price, btc_price, year)

        # 1. Convergence armed (replaces 200W dip+reclaim)
        armed = self.state.get("is_armed", False)
        ema50 = self.state.get("mstr_50w_ema", 0)
        sma200 = self.state.get("mstr_200w_sma", 0)
        convergence_dist = self.state.get("convergence_distance_pct", 0)

        # 2. BTC > 200W MA
        btc_200w = self.compute_sma(btc_weekly_closes, 200) if len(btc_weekly_closes) >= 200 else None
        btc_above_200w = btc_200w is not None and btc_price > btc_200w

        # 3. StochRSI < threshold (80 for v3.0)
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
        no_macd_div = True
        if len(daily_closes) >= 20:
            recent_high = max(daily_closes[-5:])
            older_high = max(daily_closes[-20:-10]) if len(daily_closes) >= 20 else recent_high
            if recent_high > older_high and histogram < 0:
                no_macd_div = False

        # 6. Premium cap (2.0 for v3.0, wider than v2.8's 1.3)
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
            "ema50": f"${ema50:.2f}" if ema50 else "N/A",
            "sma_200w": f"${sma200:.2f}" if sma200 else "N/A",
            "convergence_dist": f"{convergence_dist:.1f}%",
            "btc_above_200w": btc_above_200w,
            "btc_200w": f"${btc_200w:.0f}" if btc_200w else "N/A",
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
    #  POSITION MANAGEMENT
    # ══════════════════════════════════════════════════════════════

    def manage_position(self, mstr_price, btc_price, daily_closes, weekly_closes,
                        gbtc_closes=None):
        """Daily position management — convergence exit, trails, profits, floors.

        v3.0 differences from v2.8:
        - PRIMARY EXIT: Convergence-down (both 50W EMA and 200W SMA falling + close)
        - EMA50 loss exit: DISABLED
        - Panic floor: -60% LEAP (wider than v2.8's -35%)
        - Initial floor: 0.55 (45% loss, wider than v2.8's 35%)
        - Premium compression: 50% drop threshold (v2.8: 30%)
        - Only 2 trail tiers (wide safety nets)
        """
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

        # ── PRIMARY EXIT: Convergence-Down ──
        # Both 50W EMA and 200W SMA falling + close together
        if self.state.get("is_converging_down", False):
            ema50 = self.state.get("mstr_50w_ema", 0)
            sma200 = self.state.get("mstr_200w_sma", 0)
            dist = self.state.get("convergence_distance_pct", 0)
            log(f"CONVERGENCE-DOWN EXIT: EMA50=${ema50:.2f} SMA200=${sma200:.2f} dist={dist:.1f}%")
            self._execute_exit("CONVERGENCE_DOWN", mstr_price, current_stock_gain, current_leap_gain)
            return

        # ── 45% Initial Floor (wider than v2.8's 35%) ──
        if current_leap_gain < self.floor_deactivate_leap_gain:
            floor_price = entry_price * self.initial_floor_pct
            if mstr_price < floor_price:
                self._execute_exit("INITIAL_FLOOR", mstr_price, current_stock_gain, current_leap_gain)
                return

        # ── Panic Floor on Losers (-60% LEAP, wider than v2.8's -35%) ──
        if current_stock_gain < 0 and current_leap_gain <= self.panic_floor_pct:
            self._execute_exit("PANIC_FLOOR", mstr_price, current_stock_gain, current_leap_gain)
            return

        # ── Euphoria Premium Sell ──
        if (premium > self.euphoria_premium and current_leap_gain > 0
                and not self.state.get("euphoria_sell_done", False)):
            self._execute_partial_sell(0.15, "EUPHORIA_SELL", mstr_price, premium)
            self.state["euphoria_sell_done"] = True

        # ── Tiered Profit Taking (minimal — only at 50x and 100x) ──
        pt_hits = self.state.get("pt_hits", [False] * len(self.profit_tiers))
        for i, (threshold, sell_pct) in enumerate(self.profit_tiers):
            if i < len(pt_hits) and current_leap_gain >= threshold and not pt_hits[i]:
                self._execute_partial_sell(sell_pct, f"PT{i+1}_{threshold}", mstr_price, premium)
                pt_hits[i] = True
        self.state["pt_hits"] = pt_hits

        # ── Laddered Trailing Stop (wide safety nets — 2 tiers only) ──
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

        # ── Max Hold Exit (700 bars, wider than v2.8's 567) ──
        if self.state.get("bars_in_trade", 0) >= self.max_hold_bars:
            self._execute_exit("MAX_HOLD", mstr_price, current_stock_gain, current_leap_gain)
            return

        # ── Target Exit ──
        if current_leap_gain >= (self.target_mult - 1) * 100:
            self._execute_exit("TARGET_HIT", mstr_price, current_stock_gain, current_leap_gain)
            return

        # ── EMA50 Loss Exit: DISABLED in v3.0 ──
        # v2.8 had: if price < EMA50 and losing -> exit
        # v3.0: convergence-down is the primary exit, EMA50 loss is too tight

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

        # ── Premium Compression (50% drop, wider than v2.8's 30%) ──
        premium_hwm = self.state.get("premium_hwm", premium)
        self.state["premium_hwm"] = max(premium_hwm, premium)
        if premium_hwm > 0:
            prem_drop = ((premium_hwm - premium) / premium_hwm) * 100
            if prem_drop >= self.premium_compress_pct and current_leap_gain > 0:
                self._execute_partial_sell(0.50, "PREM_COMPRESS", mstr_price, premium)

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
            return

        nlv = self._get_account_value()
        risk_capital = nlv * self.risk_capital_pct
        deploy = risk_capital * 0.50  # 50/50 scale-in
        qty = int(deploy / mstr_price)

        if qty <= 0:
            log(f"Entry qty=0 — insufficient capital (NLV=${nlv:.0f})", "WARN")
            return

        contract = Stock("MSTR", "SMART", "USD")
        self.ib.qualifyContracts(contract)

        # Safety: cleanup stale orders, then execute with confirmation
        self.cleanup_stale_orders("MSTR")

        from ib_insync import MarketOrder
        order = MarketOrder("BUY", qty)
        order.tif = "GTC"
        success, fill_price, fill_qty, status = self.execute_with_confirmation(contract, order)

        if not success:
            log(f"ENTRY FAILED: Order not filled (status={status})", "ERROR")
            send_telegram(f"*Rudy v3.0 ENTRY FAILED*\nOrder not filled: {status}")
            return

        if fill_price <= 0:
            fill_price = mstr_price  # fallback for PreSubmitted (market closed)
        if fill_qty > 0:
            qty = fill_qty  # use actual filled qty

        premium = self.compute_mstr_premium(mstr_price, btc_price)
        leap_mult = self.get_dynamic_leap_multiplier(premium)

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

        convergence_entries = self.state.get("convergence_entries", 0) + 1
        self.state["convergence_entries"] = convergence_entries

        log(f"ENTRY {entry_num}/2: MSTR @ ${fill_price:.2f} | Qty={qty} | "
            f"Prem={premium:.2f}x | LEAP_Mult={leap_mult:.1f}x | ConvEntry#{convergence_entries}")
        send_telegram(
            f"*Rudy v3.0 ENTRY {entry_num}/2*\n"
            f"MSTR @ ${fill_price:.2f}\n"
            f"Qty: {qty}\n"
            f"Premium: {premium:.2f}x\n"
            f"LEAP Mult: {leap_mult:.1f}x\n"
            f"Convergence entry #{convergence_entries}"
        )
        self._save_state()

        # Safety: reconcile position after entry
        self.reconcile_position("MSTR", expected_qty=self.state.get("position_qty", 0), action=f"ENTRY {entry_num}")

    def _execute_exit(self, reason, price, stock_gain, leap_gain):
        """Liquidate full MSTR position."""
        qty = self._get_position_qty()
        if qty <= 0:
            qty = self.state.get("position_qty", 0)

        if not self.test_mode and qty > 0 and self.ensure_connected():
            contract = Stock("MSTR", "SMART", "USD")
            self.ib.qualifyContracts(contract)

            # Safety: cleanup stale orders, then execute with confirmation
            self.cleanup_stale_orders("MSTR")

            from ib_insync import MarketOrder
            order = MarketOrder("SELL", abs(qty))
            order.tif = "GTC"
            success, fill_price_actual, fill_qty, status = self.execute_with_confirmation(contract, order)

            if not success:
                log(f"EXIT ORDER FAILED: {status}", "ERROR")
                send_telegram(f"*Rudy v3.0 EXIT FAILED*\n{reason}\nOrder not filled: {status}")
                return

            if fill_price_actual > 0:
                price = fill_price_actual  # use actual fill price

        log(f"EXIT [{reason}]: MSTR @ ${price:.2f} | Stock: {stock_gain:+.1f}% | LEAP: {leap_gain:+.1f}%")
        send_telegram(
            f"*Rudy v3.0 EXIT — {reason}*\n"
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
        self._save_state()

        # Safety: verify we're actually flat
        if not self.test_mode:
            is_flat = self.verify_flat("MSTR")
            if not is_flat:
                send_telegram(f"*EXIT WARNING*: Sold but MSTR position still shows in IBKR!")

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

            # Safety: cleanup stale orders, then execute with confirmation
            self.cleanup_stale_orders("MSTR")

            from ib_insync import MarketOrder
            order = MarketOrder("SELL", sell_qty)
            order.tif = "GTC"
            success, fill_price, fill_qty, status = self.execute_with_confirmation(contract, order)

            if not success:
                log(f"PARTIAL SELL FAILED: {status}", "ERROR")
                send_telegram(f"*Partial Sell FAILED*\n{reason}\nOrder not filled: {status}")
                return

            if fill_price > 0:
                price = fill_price
            if fill_qty > 0:
                sell_qty = int(fill_qty)

        expected_remaining = max(0, self.state.get("position_qty", qty) - sell_qty)
        self.state["position_qty"] = expected_remaining
        log(f"PARTIAL SELL [{reason}]: {sell_qty} shares @ ${price:.2f} | Prem={premium:.2f}x")
        send_telegram(f"*Partial Sell — {reason}*\n{sell_qty} shares @ ${price:.2f}")
        self._save_state()

        # Safety: reconcile position after partial sell
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
        log(f"RUDY v3.0 EVALUATE ({self.resolution.upper()}) — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        log(f"{'='*60}")

        try:
            # Fetch all data
            mstr_price = self.fetch_mstr_price()
            btc_price = self.fetch_btc_price()

            if not mstr_price or not btc_price:
                log("Missing price data — skipping evaluation", "ERROR")
                return

            log(f"MSTR: ${mstr_price:.2f} | BTC: ${btc_price:,.0f}")

            # Fetch historical data
            weekly_df = self.fetch_mstr_weekly_history()
            daily_df = self.fetch_mstr_daily_history()
            gbtc_df = self.fetch_gbtc_daily_history()

            if weekly_df is None or daily_df is None:
                log("Missing historical data — skipping", "ERROR")
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

            # Update convergence state (replaces v2.8's update_dip_reclaim)
            self.update_convergence_state(weekly_closes, weekly_opens)

            # Check if we have a position
            has_position = self.state.get("entry_price", 0) > 0

            # Check TradingView confluence signal
            tv_has_signal, tv_signal = self.check_tv_signal()

            if has_position:
                # Manage existing position (pass weekly_closes for convergence checks)
                log("Managing existing position...")
                self.manage_position(mstr_price, btc_price, daily_closes, weekly_closes, gbtc_closes)

                # TV EXIT signal — immediate sell if TV says exit while in position
                if tv_has_signal and tv_signal and tv_signal.get("action", "").upper() in ("SELL", "EXIT"):
                    log("TV EXIT SIGNAL — TradingView triggered exit confirmation")
                    send_telegram(
                        f"*TV EXIT CONFIRMED*\n"
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

                # Log filter status
                log(f"FILTERS: Armed={filters['armed']} | EMA50={filters['ema50']} | "
                    f"SMA200={filters['sma_200w']} | ConvDist={filters['convergence_dist']} | "
                    f"BTC200W={filters['btc_above_200w']} | "
                    f"StRSI={filters['stoch_rsi']}({filters['stoch_rsi_ok']}) | "
                    f"Prem={filters['premium']}({filters['premium_ok']}) | "
                    f"PremExp={filters['premium_expanding']} | NoDiv={filters['no_macd_div']} | "
                    f"ATR={filters['atr_quiet']} | ALL={filters['all_pass']} | "
                    f"TV={'BUY' if tv_buy else 'none'}")

                # Save live data to state for dashboard consumption
                self.state["last_mstr_price"] = mstr_price
                self.state["last_btc_price"] = btc_price
                self.state["last_premium"] = round(filters.get("premium", 0), 4)
                self.state["last_stoch_rsi"] = round(filters.get("stoch_rsi", 0), 1)
                self.state["last_eval"] = datetime.now().isoformat()
                self._save_state()

                if all_pass:
                    first_done = self.state.get("first_entry_done", False)
                    second_done = self.state.get("second_entry_done", False)

                    confluence = "IBKR+TV" if tv_buy else "IBKR-only"
                    log(f"ENTRY SIGNAL — Confluence: {confluence}")

                    if tv_buy:
                        send_telegram(
                            f"*DOUBLE CONFLUENCE ENTRY*\n"
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

            log(f"Evaluation complete. Next: {'position management' if has_position else 'waiting for convergence signal'}")

        except Exception as e:
            log(f"Evaluation error: {e}", "ERROR")
            log(traceback.format_exc(), "ERROR")
            send_telegram(f"Rudy v3.0 evaluation error:\n{str(e)[:200]}")

    # ══════════════════════════════════════════════════════════════
    #  DAEMON / SCHEDULER
    # ══════════════════════════════════════════════════════════════

    def run_daemon(self):
        """Run as scheduled daemon."""
        log(f"\n{'='*60}")
        log(f"RUDY v3.0 TREND CONVERGENCE — STANDALONE DAEMON")
        log(f"Mode: {self.mode.upper()} | Resolution: {self.resolution}")
        log(f"Port: {self.port} | State: {STATE_FILE}")
        log(f"{'='*60}\n")

        send_telegram(
            f"*Rudy v3.0 Daemon Started*\n"
            f"Mode: {self.mode.upper()}\n"
            f"Resolution: {self.resolution}\n"
            f"Port: {self.port}"
        )

        # Schedule based on resolution
        if self.resolution == "weekly":
            # Every Friday at 3:45 PM ET (15 min before close)
            schedule.every().friday.at("15:45").do(self.evaluate)
            log("Scheduled: Every Friday at 15:45 ET")
        elif self.resolution == "daily":
            # Every weekday at 3:45 PM ET
            schedule.every().monday.at("15:45").do(self.evaluate)
            schedule.every().tuesday.at("15:45").do(self.evaluate)
            schedule.every().wednesday.at("15:45").do(self.evaluate)
            schedule.every().thursday.at("15:45").do(self.evaluate)
            schedule.every().friday.at("15:45").do(self.evaluate)
            log("Scheduled: Every weekday at 15:45 ET")

        # Run first evaluation immediately
        log("Running initial evaluation...")
        self.evaluate()

        # Keep running
        while True:
            try:
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
            "is_converging_up": False,
            "is_converging_down": False,
            "mstr_50w_ema": 0,
            "mstr_200w_sma": 0,
            "convergence_distance_pct": 0,
            "green_candle_count": 0,
            "convergence_entries": 0,
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
            "pt_hits": [False] * 2,
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
        print(f"  RUDY v3.0 TREND CONVERGENCE — STATUS")
        print(f"{'='*60}")
        print(f"  Mode:          {self.mode}")
        print(f"  Resolution:    {self.resolution}")
        print(f"  Armed:         {self.state.get('is_armed', False)}")
        print(f"  Converging Up: {self.state.get('is_converging_up', False)}")
        print(f"  Converging Dn: {self.state.get('is_converging_down', False)}")
        print(f"  50W EMA:       ${self.state.get('mstr_50w_ema', 0):.2f}")
        print(f"  200W SMA:      ${self.state.get('mstr_200w_sma', 0):.2f}")
        print(f"  Conv Distance: {self.state.get('convergence_distance_pct', 0):.1f}%")
        print(f"  Green Candles: {self.state.get('green_candle_count', 0)}")
        print(f"  Conv Entries:  {self.state.get('convergence_entries', 0)}")
        print(f"  In Position:   {'YES' if self.state.get('entry_price', 0) > 0 else 'NO'}")

        if self.state.get("entry_price", 0) > 0:
            print(f"  Entry Price:   ${self.state['entry_price']:.2f}")
            print(f"  Position Qty:  {self.state.get('position_qty', 0)}")
            print(f"  HWM:           ${self.state.get('position_hwm', 0):.2f}")
            print(f"  Bars Held:     {self.state.get('bars_in_trade', 0)}")

        print(f"  Last Eval:     {self.state.get('last_eval', 'Never')}")
        print(f"  Last MSTR:     ${self.state.get('last_mstr_price', 0):.2f}")
        print(f"  Last BTC:      ${self.state.get('last_btc_price', 0):,.0f}")
        print(f"  Trades:        {len(self.state.get('trade_log', []))}")
        print(f"{'='*60}\n")


# ══════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Rudy v3.0 Trend Convergence — Direct IBKR Trader")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper",
                        help="Trading mode (default: paper)")
    parser.add_argument("--resolution", choices=["weekly", "daily"], default="weekly",
                        help="Evaluation frequency (default: weekly)")
    parser.add_argument("--test", action="store_true",
                        help="Test mode — connect, fetch data, show filters, no trades")
    parser.add_argument("--status", action="store_true",
                        help="Show current state and exit")
    parser.add_argument("--eval-once", action="store_true",
                        help="Run one evaluation and exit (no daemon)")

    args = parser.parse_args()

    if args.mode == "live":
        print("\n" + "=" * 60)
        print("  LIVE MODE — REAL MONEY AT RISK")
        print("=" * 60)
        confirm = input("Type 'LIVE' to confirm: ")
        if confirm != "LIVE":
            print("Cancelled.")
            sys.exit(1)

    trader = RudyV30(mode=args.mode, resolution=args.resolution, test_mode=args.test)

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
