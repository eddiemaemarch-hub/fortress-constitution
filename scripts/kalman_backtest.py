#!/usr/bin/env python3
"""
Kalman Filter Backtest for Rudy v2.8+ MSTR Strategy
====================================================
RESEARCH ONLY — does NOT modify v2.8+ entry/exit logic.

Replaces the 200-week SMA with an adaptive Kalman filter for trend
estimation. Tests whether faster adaptation catches cycle lows earlier
and improves risk-adjusted returns.

State model:
    x = [price_level, trend_slope]
    F = [[1, 1], [0, 1]]  (random walk + drift)
    H = [[1, 0]]           (observe price only)
    Q = diag(q_level, q_slope)  (process noise — tunable)
    R = [[r]]               (observation noise — tunable)
"""

import json
import os
import sys
import warnings
from datetime import datetime, timedelta
from itertools import product as iterproduct

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
#  DATA LOADING
# ---------------------------------------------------------------------------

def fetch_mstr_weekly(start="2014-01-01", end="2025-12-31"):
    """Download MSTR daily data from Yahoo Finance, resample to weekly."""
    import yfinance as yf
    ticker = yf.Ticker("MSTR")
    df = ticker.history(start=start, end=end, interval="1d")
    df = df[["Open", "High", "Low", "Close"]].dropna()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    # Resample to weekly (Friday close) for consistent alignment
    weekly = df.resample("W-FRI").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
    }).dropna()
    return weekly


def fetch_btc_weekly(start="2014-01-01", end="2025-12-31"):
    """Download BTC-USD daily data from Yahoo Finance, resample to weekly."""
    import yfinance as yf
    ticker = yf.Ticker("BTC-USD")
    df = ticker.history(start=start, end=end, interval="1d")
    df = df[["Close"]].dropna()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    weekly = df.resample("W-FRI").agg({"Close": "last"}).dropna()
    weekly.columns = ["BTC_Close"]
    return weekly


def load_btc_from_state():
    """Load BTC weekly closes from trader_v28_state.json (GBTC proxy)."""
    path = "/Users/eddiemae/rudy/data/trader_v28_state.json"
    if os.path.exists(path):
        with open(path) as f:
            state = json.load(f)
        return state.get("btc_weekly_closes", [])
    return []


# ---------------------------------------------------------------------------
#  KALMAN FILTER
# ---------------------------------------------------------------------------

class KalmanTrendFilter:
    """Linear Kalman filter for price trend estimation.

    State: [level, slope]  — level tracks price, slope tracks weekly drift.
    """

    def __init__(self, q_level=1.0, q_slope=0.01, r_obs=10.0):
        self.q_level = q_level
        self.q_slope = q_slope
        self.r_obs = r_obs

        # State transition
        self.F = np.array([[1.0, 1.0],
                           [0.0, 1.0]])
        # Observation model
        self.H = np.array([[1.0, 0.0]])

        # Initial state
        self.x = np.array([0.0, 0.0])
        self.P = np.eye(2) * 1000.0
        self.initialized = False

        # Store history
        self.level_history = []
        self.slope_history = []

    def reset(self, initial_price=None):
        self.x = np.array([initial_price or 0.0, 0.0])
        self.P = np.eye(2) * 1000.0
        self.initialized = initial_price is not None
        self.level_history = []
        self.slope_history = []

    @property
    def Q(self):
        return np.array([[self.q_level, 0.0],
                         [0.0, self.q_slope]])

    @property
    def R(self):
        return np.array([[self.r_obs]])

    def update(self, observation):
        """Run one predict+update step. Returns (filtered_level, slope)."""
        if not self.initialized:
            self.x = np.array([observation, 0.0])
            self.P = np.eye(2) * 1000.0
            self.initialized = True
            self.level_history.append(observation)
            self.slope_history.append(0.0)
            return observation, 0.0

        # Predict
        x_pred = self.F @ self.x
        P_pred = self.F @ self.P @ self.F.T + self.Q

        # Update
        z = np.array([observation])
        y = z - self.H @ x_pred
        S = self.H @ P_pred @ self.H.T + self.R
        K = P_pred @ self.H.T @ np.linalg.inv(S)

        self.x = x_pred + (K @ y).flatten()
        self.P = (np.eye(2) - K @ self.H) @ P_pred

        level = self.x[0]
        slope = self.x[1]
        self.level_history.append(level)
        self.slope_history.append(slope)
        return level, slope

    def run_on_series(self, prices):
        """Run filter on full price series. Returns (levels, slopes)."""
        self.reset(prices[0] if len(prices) > 0 else None)
        levels = []
        slopes = []
        for p in prices:
            lev, slp = self.update(p)
            levels.append(lev)
            slopes.append(slp)
        return np.array(levels), np.array(slopes)


# ---------------------------------------------------------------------------
#  v2.8+ STRATEGY PARAMETERS (mirrored from constitution + trader)
# ---------------------------------------------------------------------------

# BTC holdings / shares for mNAV premium calculation
BTC_HOLDINGS = {
    2016: 0, 2017: 0, 2018: 0, 2019: 0,
    2020: 70784, 2021: 124391, 2022: 132500,
    2023: 189150, 2024: 446400, 2025: 499226, 2026: 738731,
}
DILUTED_SHARES = {
    2016: 10500000, 2017: 10500000, 2018: 10800000, 2019: 11000000,
    2020: 11500000, 2021: 11500000, 2022: 11500000,
    2023: 14500000, 2024: 182000000, 2025: 330000000, 2026: 374000000,
}

# Dynamic LEAP blend (tight_conservative_tight — WF optimal)
DYNAMIC_BLEND = [
    (0.7, 7.2),    # LOW: premium < 0.7 -> 7.2x
    (1.0, 6.5),    # FAIR: 0.7-1.0 -> 6.5x
    (1.3, 4.8),    # ELEVATED: 1.0-1.3 -> 4.8x
    (999, 3.3),    # EUPHORIC: >1.3 -> 3.3x
]

# Laddered trailing stops (TIGHT — won 7/7 OOS)
LADDER_TIERS = [
    (10000, 12.0),   # 100x+ -> 12% trail
    (5000,  20.0),   # 50x+  -> 20%
    (2000,  25.0),   # 20x+  -> 25%
    (1000,  30.0),   # 10x+  -> 30%
    (500,   35.0),   # 5x+   -> 35%
]

PROFIT_TIERS = [
    (1000,  0.10),
    (2000,  0.10),
    (5000,  0.10),
    (10000, 0.10),
]

PANIC_FLOOR_PCT = -35.0
EUPHORIA_PREMIUM = 3.5
INITIAL_FLOOR_PCT = 0.65
FLOOR_DEACTIVATE = 500
MAX_HOLD_BARS = 567
STOCH_RSI_THRESHOLD = 70
GREEN_WEEKS_THRESHOLD = 2
SLIPPAGE_PCT = 0.005
TREND_ADDER_CAPITAL_PCT = 0.25
TREND_CONFIRM_WEEKS = 4


# ---------------------------------------------------------------------------
#  HELPER FUNCTIONS
# ---------------------------------------------------------------------------

def compute_sma(prices, period):
    if len(prices) < period:
        return None
    return np.mean(prices[-period:])


def compute_ema(prices, period):
    if len(prices) < period:
        return None
    mult = 2.0 / (period + 1)
    ema = np.mean(prices[:period])
    for p in prices[period:]:
        ema = (p - ema) * mult + ema
    return ema


def compute_stoch_rsi(closes, rsi_period=14, stoch_period=14):
    """Compute StochRSI from close prices."""
    if len(closes) < rsi_period + stoch_period + 1:
        return 50.0  # neutral default
    # RSI
    deltas = np.diff(closes[-(rsi_period + stoch_period + 1):])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    rsi_values = []
    avg_gain = np.mean(gains[:rsi_period])
    avg_loss = np.mean(losses[:rsi_period])
    for i in range(rsi_period, len(deltas)):
        avg_gain = (avg_gain * (rsi_period - 1) + gains[i]) / rsi_period
        avg_loss = (avg_loss * (rsi_period - 1) + losses[i]) / rsi_period
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - 100 / (1 + rs))

    if len(rsi_values) < stoch_period:
        return 50.0
    recent = rsi_values[-stoch_period:]
    lo = min(recent)
    hi = max(recent)
    if hi == lo:
        return 50.0
    return ((rsi_values[-1] - lo) / (hi - lo)) * 100


def get_premium(mstr_price, btc_price, year):
    holdings = BTC_HOLDINGS.get(year, BTC_HOLDINGS.get(
        max(k for k in BTC_HOLDINGS if k <= year), 0))
    shares = DILUTED_SHARES.get(year, DILUTED_SHARES.get(
        max(k for k in DILUTED_SHARES if k <= year), 1))
    if holdings == 0 or shares == 0 or btc_price <= 0:
        return 1.0
    nav = (btc_price * holdings) / shares
    if nav <= 0:
        return 999.0
    return mstr_price / nav


def get_leap_multiplier(premium):
    for threshold, mult in DYNAMIC_BLEND:
        if premium < threshold:
            return mult
    return 3.3


# ---------------------------------------------------------------------------
#  BACKTEST ENGINE
# ---------------------------------------------------------------------------

class BacktestResult:
    def __init__(self):
        self.trades = []
        self.equity_curve = []
        self.total_return = 0
        self.cagr = 0
        self.max_drawdown = 0
        self.sharpe = 0
        self.num_trades = 0


def run_backtest(mstr_df, btc_df, use_kalman=True,
                 q_level=1.0, q_slope=0.01, r_obs=10.0,
                 start_capital=10000, start_idx=None, end_idx=None):
    """
    Run the v2.8+ strategy backtest.

    If use_kalman=True, replaces 200W SMA with Kalman filter.
    If use_kalman=False, uses original 200W SMA.
    """
    # Align data
    common_idx = mstr_df.index.intersection(btc_df.index)
    min_bars = 35 if use_kalman else 210
    if len(common_idx) < min_bars:
        return None

    mstr = mstr_df.loc[common_idx].copy()
    btc = btc_df.loc[common_idx].copy()

    if start_idx is not None:
        mstr = mstr.iloc[start_idx:]
        btc = btc.iloc[start_idx:]
    if end_idx is not None:
        mstr = mstr.iloc[:end_idx]
        btc = btc.iloc[:end_idx]

    mstr_closes = mstr["Close"].values
    mstr_opens = mstr["Open"].values
    btc_closes = btc["BTC_Close"].values
    dates = mstr.index

    n = len(mstr_closes)
    if n < min_bars:
        return None

    # Pre-compute trend estimates
    if use_kalman:
        kf_mstr = KalmanTrendFilter(q_level=q_level, q_slope=q_slope, r_obs=r_obs)
        mstr_trend, mstr_slope = kf_mstr.run_on_series(mstr_closes)

        kf_btc = KalmanTrendFilter(q_level=q_level, q_slope=q_slope, r_obs=r_obs)
        btc_trend, btc_slope = kf_btc.run_on_series(btc_closes)
    else:
        # 200W SMA baseline
        mstr_trend = np.full(n, np.nan)
        btc_trend = np.full(n, np.nan)
        mstr_slope = np.zeros(n)
        btc_slope = np.zeros(n)
        for i in range(n):
            if i >= 199:
                mstr_trend[i] = np.mean(mstr_closes[i - 199:i + 1])
                btc_trend[i] = np.mean(btc_closes[i - 199:i + 1])
                if i >= 200:
                    mstr_slope[i] = mstr_trend[i] - mstr_trend[i - 1]

    # Pre-compute daily-resolution StochRSI from weekly closes
    # (weekly closes serve as our "daily" proxy for backtest)
    stoch_rsi_vals = np.full(n, 50.0)
    for i in range(30, n):
        stoch_rsi_vals[i] = compute_stoch_rsi(mstr_closes[:i + 1])

    # State — LEAP-leveraged capital model
    # Instead of tracking shares, we track "LEAP position value" which is
    # capital * (1 + stock_return * leap_multiplier). This correctly models
    # the amplified returns of LEAP options.
    capital = start_capital
    in_position = False
    entry_price = 0
    position_capital = 0     # capital deployed into this position
    entry_leap_mult = 1.0    # LEAP multiplier at entry (locked)
    position_hwm_price = 0   # stock price HWM for trail calculations
    peak_leap_gain = 0
    bars_in_trade = 0
    dipped_below = False
    green_count = 0
    is_armed = False
    euphoria_done = False
    pt_hits = [False] * len(PROFIT_TIERS)
    cycle_entered = False
    remaining_pct = 1.0      # fraction of original position still held

    # Trend adder state
    trend_adder_active = False
    trend_adder_capital = 0
    trend_adder_entry = 0
    trend_adder_leap_mult = 1.0
    trend_adder_hwm = 0
    trend_confirm_count = 0

    trades = []
    equity = [capital]
    weekly_returns = []

    def get_position_value(price_now):
        """Get current mark-to-market value of LEAP position."""
        if not in_position or position_capital <= 0:
            return 0
        stock_return = (price_now - entry_price) / entry_price
        leap_return = stock_return * entry_leap_mult
        # LEAP value can go to zero but not negative (option floor)
        value = position_capital * remaining_pct * max(0, 1 + leap_return)
        return value

    def get_trend_adder_value(price_now):
        if not trend_adder_active or trend_adder_capital <= 0:
            return 0
        stock_return = (price_now - trend_adder_entry) / trend_adder_entry
        leap_return = stock_return * trend_adder_leap_mult
        return trend_adder_capital * max(0, 1 + leap_return)

    def current_equity():
        eq = capital + get_position_value(mstr_closes[i]) + get_trend_adder_value(mstr_closes[i])
        return eq

    def apply_slippage(price, direction="buy"):
        if direction == "buy":
            return price * (1 + SLIPPAGE_PCT)
        return price * (1 - SLIPPAGE_PCT)

    # Main loop (start after enough history for 200W SMA / Kalman warmup)
    if use_kalman:
        start_bar = min(30, n - 1)  # Kalman needs minimal warmup
    else:
        start_bar = min(205, n - 1)  # 200W SMA needs 200 bars

    for i in range(start_bar, n):
        year = dates[i].year
        price = mstr_closes[i]
        btc_price = btc_closes[i]
        trend_level = mstr_trend[i]
        slope = mstr_slope[i]
        btc_trend_level = btc_trend[i]

        if np.isnan(trend_level) or np.isnan(btc_trend_level):
            eq = current_equity()
            if len(equity) > 0:
                weekly_returns.append((eq - equity[-1]) / equity[-1] if equity[-1] > 0 else 0)
            equity.append(eq)
            continue

        # ── DIP + RECLAIM TRACKING ──
        above_trend = price > trend_level
        green_candle = price > mstr_opens[i]

        if not above_trend:
            if not dipped_below:
                # New dip — allow re-entry in next cycle
                cycle_entered = False
            dipped_below = True
            green_count = 0
            is_armed = False

        if dipped_below and above_trend and green_candle:
            green_count += 1

        if not above_trend:
            green_count = 0

        if green_count >= GREEN_WEEKS_THRESHOLD and not is_armed:
            is_armed = True

        if green_count > GREEN_WEEKS_THRESHOLD + 10:
            dipped_below = False
            # Do NOT reset cycle_entered here — one entry per full cycle
            # cycle_entered resets only when a new dip below trend happens

        # ── ENTRY FILTERS ──
        btc_above_trend = btc_price > btc_trend_level
        stoch_ok = stoch_rsi_vals[i] < STOCH_RSI_THRESHOLD

        # ── ENTRY ──
        if (not in_position and is_armed and btc_above_trend
                and stoch_ok and not cycle_entered and year >= 2016):
            buy_price = apply_slippage(price, "buy")
            premium = get_premium(price, btc_price, year)
            leap_mult = get_leap_multiplier(premium)

            # Deploy all available capital (50/50 scale-in averaged)
            position_capital = capital
            capital = 0
            entry_price = buy_price
            entry_leap_mult = leap_mult
            position_hwm_price = buy_price
            peak_leap_gain = 0
            bars_in_trade = 0
            euphoria_done = False
            pt_hits = [False] * len(PROFIT_TIERS)
            remaining_pct = 1.0
            in_position = True
            cycle_entered = True
            is_armed = False

            trades.append({
                "type": "ENTRY",
                "date": str(dates[i].date()),
                "price": round(buy_price, 2),
                "premium": round(premium, 2),
                "leap_mult": round(leap_mult, 1),
                "signal": "kalman" if use_kalman else "sma200w",
            })

        # ── POSITION MANAGEMENT ──
        if in_position:
            bars_in_trade += 1

            # Compute gains
            stock_gain = ((price - entry_price) / entry_price) * 100
            leap_gain = stock_gain * entry_leap_mult

            # HWM tracking
            position_hwm_price = max(position_hwm_price, price)
            hwm_stock_gain = ((position_hwm_price - entry_price) / entry_price) * 100
            peak_leap_gain = max(peak_leap_gain, hwm_stock_gain * entry_leap_mult)

            premium = get_premium(price, btc_price, year)
            exited = False

            # Initial floor (35% stock price drop from entry)
            if leap_gain < FLOOR_DEACTIVATE:
                floor_price = entry_price * INITIAL_FLOOR_PCT
                if price < floor_price:
                    exit_value = get_position_value(apply_slippage(price, "sell"))
                    capital += exit_value
                    trades.append({"type": "EXIT_FLOOR", "date": str(dates[i].date()),
                                   "price": round(price, 2), "leap_gain": round(leap_gain, 1)})
                    in_position = False
                    exited = True

            # Panic floor (-35% LEAP P&L)
            if not exited and stock_gain < 0 and leap_gain <= PANIC_FLOOR_PCT:
                exit_value = get_position_value(apply_slippage(price, "sell"))
                capital += exit_value
                trades.append({"type": "EXIT_PANIC", "date": str(dates[i].date()),
                               "price": round(price, 2), "leap_gain": round(leap_gain, 1)})
                in_position = False
                exited = True

            # Euphoria sell (partial 15%)
            if not exited and premium > EUPHORIA_PREMIUM and leap_gain > 0 and not euphoria_done:
                sell_frac = 0.15
                exit_value = get_position_value(apply_slippage(price, "sell")) * sell_frac
                capital += exit_value
                remaining_pct *= (1 - sell_frac)
                euphoria_done = True

            # Profit tiers
            if not exited:
                for ti, (thresh, pct) in enumerate(PROFIT_TIERS):
                    if leap_gain >= thresh and not pt_hits[ti]:
                        exit_value = get_position_value(apply_slippage(price, "sell")) * pct
                        capital += exit_value
                        remaining_pct *= (1 - pct)
                        pt_hits[ti] = True

            # Laddered trail (based on peak LEAP gain, triggered by stock price)
            if not exited and peak_leap_gain > 0:
                trail_pct = 0
                for thresh, trail in LADDER_TIERS:
                    if peak_leap_gain >= thresh:
                        trail_pct = trail
                        break
                if trail_pct > 0:
                    stop_level = position_hwm_price * (1 - trail_pct / 100)
                    if price < stop_level:
                        exit_value = get_position_value(apply_slippage(price, "sell"))
                        capital += exit_value
                        trades.append({"type": "EXIT_TRAIL", "date": str(dates[i].date()),
                                       "price": round(price, 2), "leap_gain": round(leap_gain, 1)})
                        in_position = False
                        exited = True

            # Max hold
            if not exited and bars_in_trade >= MAX_HOLD_BARS:
                exit_value = get_position_value(apply_slippage(price, "sell"))
                capital += exit_value
                trades.append({"type": "EXIT_MAXHOLD", "date": str(dates[i].date()),
                               "price": round(price, 2), "leap_gain": round(leap_gain, 1)})
                in_position = False
                exited = True

            # BTC death cross (50W < 200W SMA on BTC)
            if not exited and i >= 200:
                btc_sma50 = np.mean(btc_closes[i - 49:i + 1])
                btc_sma200 = np.mean(btc_closes[i - 199:i + 1])
                if i >= 201:
                    prev_btc50 = np.mean(btc_closes[i - 50:i])
                    if btc_sma50 < btc_sma200 and prev_btc50 >= btc_sma200:
                        exit_value = get_position_value(apply_slippage(price, "sell"))
                        capital += exit_value
                        trades.append({"type": "EXIT_BTC_DC", "date": str(dates[i].date()),
                                       "price": round(price, 2), "leap_gain": round(leap_gain, 1)})
                        in_position = False
                        exited = True

            if exited:
                position_capital = 0
                position_hwm_price = 0
                peak_leap_gain = 0
                bars_in_trade = 0
                remaining_pct = 1.0

        # ── TREND ADDER (Kalman slope positive 4+ weeks) ──
        if use_kalman and in_position and not trend_adder_active:
            if slope > 0:
                trend_confirm_count += 1
            else:
                trend_confirm_count = 0

            if trend_confirm_count >= TREND_CONFIRM_WEEKS and capital > 0:
                adder_cap = min(capital, start_capital * TREND_ADDER_CAPITAL_PCT)
                if adder_cap > 100:
                    buy_price = apply_slippage(price, "buy")
                    trend_adder_capital = adder_cap
                    trend_adder_entry = buy_price
                    trend_adder_leap_mult = get_leap_multiplier(get_premium(price, btc_price, year))
                    trend_adder_hwm = buy_price
                    capital -= adder_cap
                    trend_adder_active = True
                    trades.append({"type": "TREND_ADDER_ENTRY", "date": str(dates[i].date()),
                                   "price": round(buy_price, 2)})

        # Manage trend adder
        if trend_adder_active and trend_adder_capital > 0:
            trend_adder_hwm = max(trend_adder_hwm, price)
            ta_stock_gain = ((price - trend_adder_entry) / trend_adder_entry) * 100
            ta_leap = ta_stock_gain * trend_adder_leap_mult

            # Exit on slope reversal or -60% panic
            if slope < 0 and trend_confirm_count == 0:
                exit_value = get_trend_adder_value(apply_slippage(price, "sell"))
                capital += exit_value
                trades.append({"type": "TREND_ADDER_EXIT", "date": str(dates[i].date()),
                               "price": round(price, 2), "leap_gain": round(ta_leap, 1)})
                trend_adder_capital = 0
                trend_adder_active = False
            elif ta_leap <= -60:
                exit_value = get_trend_adder_value(apply_slippage(price, "sell"))
                capital += exit_value
                trend_adder_capital = 0
                trend_adder_active = False

        # Close trend adder if main position closed
        if not in_position and trend_adder_active:
            exit_value = get_trend_adder_value(apply_slippage(price, "sell"))
            capital += exit_value
            trend_adder_capital = 0
            trend_adder_active = False
            trend_confirm_count = 0

        eq = current_equity()
        if len(equity) > 0 and equity[-1] > 0:
            weekly_returns.append((eq - equity[-1]) / equity[-1])
        equity.append(eq)

    # ── FINAL LIQUIDATION ──
    if in_position:
        exit_value = get_position_value(apply_slippage(mstr_closes[-1], "sell"))
        capital += exit_value
        in_position = False
    if trend_adder_active:
        exit_value = get_trend_adder_value(apply_slippage(mstr_closes[-1], "sell"))
        capital += exit_value
        trend_adder_active = False

    final_equity = capital
    equity.append(final_equity)

    # ── METRICS ──
    result = BacktestResult()
    result.trades = trades
    result.equity_curve = equity
    result.num_trades = len([t for t in trades if t["type"] == "ENTRY"])

    total_return = (final_equity - start_capital) / start_capital * 100
    result.total_return = total_return

    years = max((dates[-1] - dates[start_bar]).days / 365.25, 1)
    if final_equity > 0 and start_capital > 0:
        result.cagr = ((final_equity / start_capital) ** (1 / years) - 1) * 100
    else:
        result.cagr = -100

    # Max drawdown
    eq_arr = np.array(equity)
    peak = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - peak) / np.where(peak > 0, peak, 1)
    result.max_drawdown = float(np.min(dd)) * 100

    # Sharpe (annualized from weekly returns)
    if len(weekly_returns) > 10:
        wr = np.array(weekly_returns)
        mean_r = np.mean(wr)
        std_r = np.std(wr)
        result.sharpe = (mean_r / std_r * np.sqrt(52)) if std_r > 0 else 0
    else:
        result.sharpe = 0

    return result


# ---------------------------------------------------------------------------
#  WALK-FORWARD ANALYSIS
# ---------------------------------------------------------------------------

def walk_forward_analysis(mstr_df, btc_df, start_capital=10000):
    """7 anchored expanding windows. Optimize Q/R on IS, test on OOS."""
    common_idx = mstr_df.index.intersection(btc_df.index)
    mstr_aligned = mstr_df.loc[common_idx]
    btc_aligned = btc_df.loc[common_idx]
    n = len(common_idx)

    # Define windows (anchored expanding)
    # ~52 weeks per year, data from ~2014. We want 2016-2025 test range.
    # This is a very low-frequency strategy (1-3 trades per decade),
    # so OOS windows must be wide enough to capture at least one trade cycle.
    oos_size = 78  # ~1.5 years OOS (wider to capture infrequent signals)
    usable_start = 110  # Kalman needs less warmup than 200W SMA
    usable_end = n
    usable_range = usable_end - usable_start

    n_windows = 7
    window_step = max(1, (usable_range - oos_size) // n_windows)

    # Parameter grid for Kalman Q/R optimization
    q_level_grid = [0.5, 1.0, 2.0, 5.0]
    q_slope_grid = [0.005, 0.01, 0.05]
    r_obs_grid = [5.0, 10.0, 25.0, 50.0]

    windows = []
    for w in range(n_windows):
        is_start = 0  # anchored
        is_end = usable_start + w * window_step
        oos_start = is_end
        oos_end = min(oos_start + oos_size, n)
        if oos_end <= oos_start + 10:
            break
        windows.append((is_start, is_end, oos_start, oos_end))

    results = []
    is_sharpes = []
    oos_sharpes = []
    oos_returns = []

    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD ANALYSIS — {len(windows)} anchored expanding windows")
    print(f"{'='*70}")

    for wi, (is_s, is_e, oos_s, oos_e) in enumerate(windows):
        is_dates = (common_idx[is_s], common_idx[is_e - 1])
        oos_dates = (common_idx[oos_s], common_idx[min(oos_e - 1, n - 1)])

        print(f"\n  Window {wi+1}/{len(windows)}: IS {is_dates[0].date()}..{is_dates[1].date()} | "
              f"OOS {oos_dates[0].date()}..{oos_dates[1].date()}")

        # Grid search on IS
        best_sharpe = -999
        best_params = (1.0, 0.01, 10.0)

        is_mstr = mstr_aligned.iloc[is_s:is_e].copy()
        is_btc = btc_aligned.iloc[is_s:is_e].copy()
        oos_mstr = mstr_aligned.iloc[oos_s:oos_e].copy()
        oos_btc = btc_aligned.iloc[oos_s:oos_e].copy()

        for ql, qs, ro in iterproduct(q_level_grid, q_slope_grid, r_obs_grid):
            res = run_backtest(is_mstr, is_btc,
                               use_kalman=True, q_level=ql, q_slope=qs, r_obs=ro,
                               start_capital=start_capital)
            if res and res.sharpe > best_sharpe and res.num_trades > 0:
                best_sharpe = res.sharpe
                best_params = (ql, qs, ro)

        # Run OOS with best params
        oos_res = run_backtest(oos_mstr, oos_btc,
                               use_kalman=True,
                               q_level=best_params[0],
                               q_slope=best_params[1],
                               r_obs=best_params[2],
                               start_capital=start_capital)

        is_sharpe = best_sharpe
        oos_sharpe = oos_res.sharpe if oos_res else 0
        oos_ret = oos_res.total_return if oos_res else 0

        is_sharpes.append(is_sharpe)
        oos_sharpes.append(oos_sharpe)
        oos_returns.append(oos_ret)

        oos_trades = oos_res.num_trades if oos_res else 0

        print(f"    Best IS params: Q_level={best_params[0]}, Q_slope={best_params[1]}, R={best_params[2]}")
        print(f"    IS Sharpe: {is_sharpe:.2f} | OOS Sharpe: {oos_sharpe:.2f} | OOS Return: {oos_ret:+.1f}% | OOS Trades: {oos_trades}")

        results.append({
            "window": wi + 1,
            "is_period": f"{is_dates[0].date()} to {is_dates[1].date()}",
            "oos_period": f"{oos_dates[0].date()} to {oos_dates[1].date()}",
            "best_params": {"q_level": best_params[0], "q_slope": best_params[1], "r_obs": best_params[2]},
            "is_sharpe": round(is_sharpe, 3),
            "oos_sharpe": round(oos_sharpe, 3),
            "oos_return_pct": round(oos_ret, 2),
            "oos_trades": oos_trades,
        })

    # WFE
    mean_is = np.mean(is_sharpes) if is_sharpes else 0
    mean_oos = np.mean(oos_sharpes) if oos_sharpes else 0
    wfe = mean_oos / mean_is if mean_is != 0 else 0

    # Stitched OOS return (compounded)
    stitched = 1.0
    for r in oos_returns:
        stitched *= (1 + r / 100)
    stitched_ret = (stitched - 1) * 100

    print(f"\n  {'─'*50}")
    print(f"  Mean IS Sharpe:      {mean_is:.3f}")
    print(f"  Mean OOS Sharpe:     {mean_oos:.3f}")
    print(f"  WFE (OOS/IS):        {wfe:.3f}")
    print(f"  Stitched OOS Return: {stitched_ret:+.1f}%")

    return {
        "windows": results,
        "mean_is_sharpe": round(mean_is, 3),
        "mean_oos_sharpe": round(mean_oos, 3),
        "wfe": round(wfe, 3),
        "stitched_oos_return_pct": round(stitched_ret, 2),
    }


# ---------------------------------------------------------------------------
#  MAIN
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("  KALMAN FILTER BACKTEST — Rudy v2.8+ MSTR Strategy")
    print("  RESEARCH ONLY — does NOT modify v2.8+ entry/exit logic")
    print("=" * 70)

    # ── Load data ──
    print("\nLoading data...")
    mstr_df = fetch_mstr_weekly(start="2014-01-01", end="2025-12-31")
    btc_df = fetch_btc_weekly(start="2014-01-01", end="2025-12-31")
    print(f"  MSTR weekly bars: {len(mstr_df)} ({mstr_df.index[0].date()} to {mstr_df.index[-1].date()})")
    print(f"  BTC  weekly bars: {len(btc_df)} ({btc_df.index[0].date()} to {btc_df.index[-1].date()})")

    # ── Full Backtest: Kalman v2.8+ ──
    print("\n" + "=" * 70)
    print("  FULL BACKTEST: Kalman v2.8+ (Q_level=1.0, Q_slope=0.01, R=10.0)")
    print("=" * 70)

    kalman_res = run_backtest(mstr_df, btc_df, use_kalman=True,
                              q_level=1.0, q_slope=0.01, r_obs=10.0,
                              start_capital=10000)

    print(f"\n  Total Return:   {kalman_res.total_return:+.1f}%")
    print(f"  CAGR:           {kalman_res.cagr:+.1f}%")
    print(f"  Max Drawdown:   {kalman_res.max_drawdown:.1f}%")
    print(f"  Sharpe Ratio:   {kalman_res.sharpe:.3f}")
    print(f"  Num Trades:     {kalman_res.num_trades}")
    print(f"  Trade Log:")
    for t in kalman_res.trades:
        print(f"    {t['date']} | {t['type']:25s} | ${t.get('price', 0):>10.2f} | "
              f"LEAP: {t.get('leap_gain', ''):>8}%")

    # ── Full Backtest: Original v2.8+ (200W SMA) ──
    print("\n" + "=" * 70)
    print("  FULL BACKTEST: Original v2.8+ (200-Week SMA)")
    print("=" * 70)

    sma_res = run_backtest(mstr_df, btc_df, use_kalman=False,
                           start_capital=10000)

    print(f"\n  Total Return:   {sma_res.total_return:+.1f}%")
    print(f"  CAGR:           {sma_res.cagr:+.1f}%")
    print(f"  Max Drawdown:   {sma_res.max_drawdown:.1f}%")
    print(f"  Sharpe Ratio:   {sma_res.sharpe:.3f}")
    print(f"  Num Trades:     {sma_res.num_trades}")
    print(f"  Trade Log:")
    for t in sma_res.trades:
        print(f"    {t['date']} | {t['type']:25s} | ${t.get('price', 0):>10.2f} | "
              f"LEAP: {t.get('leap_gain', ''):>8}%")

    # ── Walk-Forward Analysis ──
    wfa = walk_forward_analysis(mstr_df, btc_df, start_capital=10000)

    # ── Comparison Table ──
    print("\n" + "=" * 70)
    print("  COMPARISON: Kalman v2.8+ vs Original v2.8+ (200W SMA)")
    print("=" * 70)
    print(f"\n  {'Metric':<25s} {'Kalman':>15s} {'200W SMA':>15s} {'Delta':>12s}")
    print(f"  {'─'*67}")

    metrics = [
        ("Total Return %", kalman_res.total_return, sma_res.total_return),
        ("CAGR %", kalman_res.cagr, sma_res.cagr),
        ("Max Drawdown %", kalman_res.max_drawdown, sma_res.max_drawdown),
        ("Sharpe Ratio", kalman_res.sharpe, sma_res.sharpe),
        ("Num Trades", kalman_res.num_trades, sma_res.num_trades),
    ]
    for name, k_val, s_val in metrics:
        delta = k_val - s_val
        sign = "+" if delta >= 0 else ""
        print(f"  {name:<25s} {k_val:>15.2f} {s_val:>15.2f} {sign}{delta:>10.2f}")

    print(f"\n  Walk-Forward (Kalman):")
    print(f"    WFE:                {wfa['wfe']:.3f}")
    print(f"    Stitched OOS Ret:   {wfa['stitched_oos_return_pct']:+.1f}%")
    print(f"    Mean IS Sharpe:     {wfa['mean_is_sharpe']:.3f}")
    print(f"    Mean OOS Sharpe:    {wfa['mean_oos_sharpe']:.3f}")

    # Compare with v2.8+ WFA from constitution
    print(f"\n  v2.8+ Original WFA (from constitution):")
    print(f"    WFE:                1.200")
    print(f"    Stitched OOS Ret:   +692.2%")

    # ── Save Results ──
    output = {
        "run_date": datetime.now().isoformat(),
        "description": "Kalman filter backtest for v2.8+ MSTR strategy (RESEARCH ONLY)",
        "data_range": {
            "mstr": f"{mstr_df.index[0].date()} to {mstr_df.index[-1].date()}",
            "btc": f"{btc_df.index[0].date()} to {btc_df.index[-1].date()}",
            "mstr_bars": len(mstr_df),
            "btc_bars": len(btc_df),
        },
        "kalman_backtest": {
            "total_return_pct": round(kalman_res.total_return, 2),
            "cagr_pct": round(kalman_res.cagr, 2),
            "max_drawdown_pct": round(kalman_res.max_drawdown, 2),
            "sharpe": round(kalman_res.sharpe, 3),
            "num_trades": kalman_res.num_trades,
            "trades": kalman_res.trades,
            "default_params": {"q_level": 1.0, "q_slope": 0.01, "r_obs": 10.0},
        },
        "sma_backtest": {
            "total_return_pct": round(sma_res.total_return, 2),
            "cagr_pct": round(sma_res.cagr, 2),
            "max_drawdown_pct": round(sma_res.max_drawdown, 2),
            "sharpe": round(sma_res.sharpe, 3),
            "num_trades": sma_res.num_trades,
            "trades": sma_res.trades,
        },
        "walk_forward": wfa,
        "comparison": {
            "kalman_vs_sma_return_delta": round(kalman_res.total_return - sma_res.total_return, 2),
            "kalman_vs_sma_sharpe_delta": round(kalman_res.sharpe - sma_res.sharpe, 3),
            "kalman_vs_sma_drawdown_delta": round(kalman_res.max_drawdown - sma_res.max_drawdown, 2),
            "kalman_wfe": wfa["wfe"],
            "original_v28_wfe": 1.20,
            "recommendation": "",  # filled below
        },
    }

    # Recommendation
    kalman_better_sharpe = kalman_res.sharpe > sma_res.sharpe
    kalman_better_return = kalman_res.total_return > sma_res.total_return
    kalman_better_dd = kalman_res.max_drawdown > sma_res.max_drawdown  # less negative = better
    kalman_wfe_ok = wfa["wfe"] > 0.5

    if kalman_better_sharpe and kalman_better_return and kalman_wfe_ok:
        output["comparison"]["recommendation"] = (
            "PROMISING: Kalman filter shows improvement in both return and Sharpe with WFE > 0.5. "
            "Consider further testing with live paper data before replacing 200W SMA."
        )
    elif kalman_better_sharpe or kalman_better_return:
        output["comparison"]["recommendation"] = (
            "MIXED: Kalman shows partial improvement. Not sufficient to justify replacing "
            "the validated 200W SMA approach. Keep as research reference."
        )
    else:
        output["comparison"]["recommendation"] = (
            "NO IMPROVEMENT: Kalman filter does not outperform the 200W SMA baseline. "
            "Keep the original v2.8+ strategy unchanged."
        )

    print(f"\n  Recommendation: {output['comparison']['recommendation']}")

    results_path = "/Users/eddiemae/rudy/data/kalman_backtest_results.json"
    with open(results_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to: {results_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
