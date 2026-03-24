# QuantConnect LEAN Algorithm
# MSTR Cycle-Low LEAP Strategy v2.8+ CANDLESTICK FILTER VARIANT
# Research only — NOT deployed. Tests whether adding bullish weekly candlestick
# pattern confirmation to v2.8+ entry improves OOS risk-adjusted returns.
# Modes: none (baseline) | strict (pattern on entry bar) |
#         window_3 (pattern in last 3 bars) | high_prob (hammer/engulfing only)
#
# v2.8+ = v2.8 Dynamic Blend + Trend Confirmation Scale-Up (Option B)
#
# BASE (v2.8): 200W dip+reclaim entry → 25% capital → LEAP multiplied returns
# TREND ADDER: After base entry, if golden cross (50W EMA > 200W SMA, both rising)
#   holds for N weeks → deploy additional 25% capital with wider stops.
#   Exit adder on: convergence-down (both EMAs falling + close), wider floors.
#
# The trend adder catches the "second phase" of bull runs — after the dip+reclaim
# proves right and the golden cross confirms sustained uptrend.
#
# CRITICAL: Start from 2016 so 200W SMA is available by ~2020.

from AlgorithmImports import *
import numpy as np
from datetime import timedelta


class MSTRCycleLowLeap(QCAlgorithm):

    def Initialize(self):
        self.is_live_mode = self.LiveMode

        if not self.is_live_mode:
            self.SetStartDate(2016, 1, 1)
            self.SetEndDate(2026, 3, 14)
            self.SetCash(100000)

        if self.is_live_mode:
            self.Log("LIVE MODE: IBKR connection via QC deployment config")

        if not hasattr(self, 'trade_resolution'):
            self.trade_resolution = "weekly"

        # ── REALISM ──
        self.Settings.FreePortfolioValuePercentage = 0.02
        if not self.is_live_mode:
            self.SetSecurityInitializer(lambda security: security.SetSlippageModel(
                ConstantSlippageModel(0.005)
            ))

        # ── Assets ──
        self.mstr = self.AddEquity("MSTR", Resolution.Daily)
        self.mstr.SetDataNormalizationMode(DataNormalizationMode.SplitAdjusted)
        self.btc_proxy = self.AddEquity("GBTC", Resolution.Daily)
        self.btc_proxy.SetDataNormalizationMode(DataNormalizationMode.SplitAdjusted)
        self.btc = self.AddCrypto("BTCUSD", Resolution.Daily, Market.Coinbase)

        # ── LEAP Multiplier ──
        self.leap_multiplier_base = 10.0

        # ── 200W Dip+Reclaim Entry Parameters ──
        self.green_weeks_threshold = 2
        self.sma_weekly_period = 200

        # ── Entry Filters ──
        self.stoch_rsi_entry_threshold = 70
        self.premium_cap = 1.5
        self.premium_lookback = 4

        # ── BTC Holdings for mNAV ──
        self.btc_holdings_history = {
            2016: 0, 2017: 0, 2018: 0, 2019: 0,
            2020: 70784, 2021: 124391, 2022: 132500,
            2023: 189150, 2024: 446400, 2025: 499226, 2026: 738731,
        }
        self.diluted_shares_history = {
            2016: 10500000, 2017: 10500000, 2018: 10800000, 2019: 11000000,
            2020: 11500000, 2021: 11500000, 2022: 11500000,
            2023: 14500000, 2024: 182000000, 2025: 330000000, 2026: 374000000,
        }

        # ── v2.7 DIAMOND HANDS: Wider Laddered Trailing Stops ──
        self.ladder_tiers = [
            (10000, 15.0), (5000, 25.0), (2000, 30.0), (1000, 35.0), (500, 40.0),
        ]

        # ── v2.7 DIAMOND HANDS: Small Profit Takes ──
        self.profit_tiers = [
            (1000, 0.10), (2000, 0.10), (5000, 0.10), (10000, 0.10),
        ]

        # ── Risk Parameters ──
        self.max_hold_bars = 567
        self.target_mult = 200.0
        self.premium_compress_pct = 30.0
        self.initial_floor_pct = 0.65
        self.floor_deactivate_leap_gain = 500
        self.panic_floor_pct = -35.0
        self.euphoria_premium = 3.5
        self.risk_capital_pct = 0.25

        # ══════════════════════════════════════════════════════════
        # TREND ADDER PARAMETERS (Option B)
        # ══════════════════════════════════════════════════════════
        self.trend_adder_enabled = True
        self.trend_confirm_weeks = 4          # Golden cross must hold N weeks
        self.trend_convergence_pct = 15.0     # Distance threshold for convergence-down exit
        self.trend_adder_capital_pct = 0.25   # Additional 25% capital
        self.trend_adder_panic_floor = -60.0  # Wider panic floor for adder
        self.trend_adder_initial_floor = 0.55 # 45% hard stop floor (entry × 0.55)
        self.trend_adder_ladder = [           # Safety-only trail tiers
            (10000, 25.0),  # 100x+ → 25% trail
            (5000,  35.0),  # 50x+  → 35% trail
        ]

        # ── Candlestick Filter Parameters ──
        # Injected by walk-forward script via regex patch. Default = "none" (baseline)
        # "none"      : No candlestick gate — identical to v2.8+ baseline
        # "strict"    : Entry bar MUST have a recognised bullish pattern
        # "window_3"  : Any of the last 3 weekly bars must have a bullish pattern
        # "high_prob" : Only Hammer or Bullish Engulfing count (highest reliability)
        self.candlestick_mode = "none"
        self.candlestick_lookback = 3   # weeks to scan in window_3 mode

        # ── Weekly Data Rolling Windows ──
        self.weekly_closes = RollingWindow[float](350)
        self.weekly_opens = RollingWindow[float](350)
        self.weekly_highs = RollingWindow[float](350)
        self.weekly_lows = RollingWindow[float](350)
        self.btc_weekly_closes = RollingWindow[float](350)

        # ── Premium History ──
        self.premium_history = RollingWindow[float](30)

        # ── Daily Indicators ──
        self.mstr_macd = self.MACD("MSTR", 12, 26, 9, MovingAverageType.Exponential, Resolution.Daily)
        self.mstr_ema_50 = self.EMA("MSTR", 50, Resolution.Daily)
        self.mstr_rsi = self.RSI("MSTR", 14)
        self.rsi_window = RollingWindow[float](14)
        self.mstr_atr = self.ATR("MSTR", 14, MovingAverageType.Simple)
        self.atr_window = RollingWindow[float](30)
        self.price_highs_window = RollingWindow[float](30)

        # ── State: 200W Dip+Reclaim ──
        self.dipped_below_200w = False
        self.green_week_count = 0
        self.is_armed = False
        self.mstr_200w_sma = None

        # ── State: Cycle tracking ──
        self.already_entered_this_cycle = False

        # ── State: Scale-in 50/50 ──
        self.first_entry_done = False
        self.second_entry_done = False

        # ── Base Position State ──
        self.entry_price = 0
        self.position_hwm = 0
        self.peak_gain_pct = 0
        self.current_trail_pct = 0
        self.pt_hits = [False] * len(self.profit_tiers)
        self.premium_hwm = 0
        self.bars_in_trade = 0
        self.euphoria_sell_done = False

        # ── Trend Adder State ──
        self.golden_cross_weeks = 0
        self.trend_adder_active = False
        self.trend_adder_entry_price = 0
        self.trend_adder_qty = 0
        self.trend_adder_hwm = 0
        self.trend_adder_peak_gain = 0
        self.trend_confirmed_logged = False

        # ── Tracking ──
        self.entry_dates = []
        self.exit_dates = []
        self.trade_log = []
        self.adder_trade_log = []
        self.week_count = 0
        # Track base qty separately so adder exits don't liquidate base
        self.base_qty = 0

        # ── Schedule ──
        self._schedule_trade_evaluation()
        self.SetWarmUp(timedelta(days=60))

        # ── Seed rolling windows from historical data ──
        # This eliminates path dependency: 200W SMA is ready from day 1
        # regardless of algorithm start date.
        self._seed_weekly_history()

    def _seed_weekly_history(self):
        """Pre-populate rolling windows with historical weekly data.

        Without this, the 200W SMA requires ~4 years of live data collection
        before it produces a value. By seeding from QC's history API, the SMA
        is ready from algorithm start — eliminating start-date path dependency.
        """
        try:
            # Fetch 350 weeks (~6.7 years) of weekly history for MSTR
            mstr_hist = self.History(self.Symbol("MSTR"), 350 * 7, Resolution.Daily)
            if mstr_hist.empty:
                self.Log("SEED: No MSTR history available — will build from scratch")
                return

            # Resample daily to weekly (Friday close)
            if "MSTR" in mstr_hist.index.get_level_values(0):
                mstr_data = mstr_hist.loc["MSTR"]
            else:
                mstr_data = mstr_hist

            # Group by week (W-FRI = week ending Friday)
            mstr_data = mstr_data.copy()
            mstr_data.index = mstr_data.index.tz_localize(None) if hasattr(mstr_data.index, 'tz_localize') and mstr_data.index.tz is not None else mstr_data.index
            weekly = mstr_data.resample('W-FRI')

            weekly_o = weekly['open'].first().dropna()
            weekly_c = weekly['close'].last().dropna()
            weekly_h = weekly['high'].max().dropna()
            weekly_l = weekly['low'].min().dropna()

            # Add oldest first so newest ends up at index 0 in the rolling window
            count = 0
            for idx in weekly_c.index:
                if idx in weekly_o.index and idx in weekly_h.index and idx in weekly_l.index:
                    self.weekly_closes.Add(float(weekly_c[idx]))
                    self.weekly_opens.Add(float(weekly_o[idx]))
                    self.weekly_highs.Add(float(weekly_h[idx]))
                    self.weekly_lows.Add(float(weekly_l[idx]))
                    count += 1

            # Compute initial 200W SMA
            self.mstr_200w_sma = self.ComputeWeeklySMA(self.sma_weekly_period)
            self.week_count = count

            self.Log(f"SEED: Loaded {count} weekly bars for MSTR | "
                     f"200W SMA={'$' + f'{self.mstr_200w_sma:.2f}' if self.mstr_200w_sma else 'Not ready'}")

            # Also seed BTC weekly closes
            try:
                btc_hist = self.History(self.Symbol("BTCUSD"), 350 * 7, Resolution.Daily)
                if not btc_hist.empty:
                    if "BTCUSD" in btc_hist.index.get_level_values(0):
                        btc_data = btc_hist.loc["BTCUSD"]
                    else:
                        btc_data = btc_hist
                    btc_data = btc_data.copy()
                    btc_data.index = btc_data.index.tz_localize(None) if hasattr(btc_data.index, 'tz_localize') and btc_data.index.tz is not None else btc_data.index
                    btc_weekly_c = btc_data.resample('W-FRI')['close'].last().dropna()
                    btc_count = 0
                    for idx in btc_weekly_c.index:
                        self.btc_weekly_closes.Add(float(btc_weekly_c[idx]))
                        btc_count += 1
                    self.Log(f"SEED: Loaded {btc_count} weekly bars for BTCUSD")
            except Exception as e:
                self.Log(f"SEED: BTC history unavailable ({e}) — will build from scratch")

        except Exception as e:
            self.Log(f"SEED: History seeding failed ({e}) — falling back to live collection")

    def _schedule_trade_evaluation(self):
        if self.trade_resolution == "monthly":
            self.Schedule.On(self.DateRules.MonthEnd("MSTR"),
                self.TimeRules.BeforeMarketClose("MSTR", 1), self.OnTradeBar)
        elif self.trade_resolution == "daily":
            self.Schedule.On(self.DateRules.EveryDay("MSTR"),
                self.TimeRules.BeforeMarketClose("MSTR", 1), self.OnTradeBar)
        else:
            self.Schedule.On(self.DateRules.Every(DayOfWeek.Friday),
                self.TimeRules.BeforeMarketClose("MSTR", 1), self.OnTradeBar)

        self.Schedule.On(self.DateRules.Every(DayOfWeek.Friday),
            self.TimeRules.BeforeMarketClose("MSTR", 2), self.OnWeeklyConsolidate)

    # ══════════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════════

    def GetBTCHoldings(self, year):
        if year in self.btc_holdings_history:
            return self.btc_holdings_history[year]
        if year < 2016:
            return 0
        return self.btc_holdings_history.get(max(k for k in self.btc_holdings_history if k <= year), 738731)

    def GetDilutedShares(self, year):
        if year in self.diluted_shares_history:
            return self.diluted_shares_history[year]
        if year < 2016:
            return 10500000
        return self.diluted_shares_history.get(max(k for k in self.diluted_shares_history if k <= year), 374000000)

    def ComputeWeeklySMA(self, period):
        if self.weekly_closes.Count < period:
            return None
        total = sum(self.weekly_closes[i] for i in range(period))
        return total / period

    def ComputeBTCWeeklySMA(self, period):
        if self.btc_weekly_closes.Count < period:
            return None
        total = sum(self.btc_weekly_closes[i] for i in range(period))
        return total / period

    def ComputeStochRSI(self):
        if self.rsi_window.Count < 14:
            return 50
        rsi_values = [self.rsi_window[i] for i in range(self.rsi_window.Count)]
        rsi_min = min(rsi_values)
        rsi_max = max(rsi_values)
        if rsi_max == rsi_min:
            return 50
        return ((rsi_values[0] - rsi_min) / (rsi_max - rsi_min)) * 100

    def Compute50WEMA(self):
        """Compute 50-week EMA from weekly closes."""
        if self.weekly_closes.Count < 50:
            return None
        # EMA: start with SMA of first 50, then apply EMA formula
        closes = [self.weekly_closes[i] for i in range(min(self.weekly_closes.Count, 200))]
        closes.reverse()  # oldest first
        if len(closes) < 50:
            return None
        # SMA seed
        ema = sum(closes[:50]) / 50.0
        k = 2.0 / (50.0 + 1.0)
        for price in closes[50:]:
            ema = price * k + ema * (1.0 - k)
        return ema

    def CheckGoldenCross(self):
        """Check if 50W EMA > 200W SMA with both rising.
        Returns (is_golden, converging_down, ema50, sma200, distance_pct)"""
        ema50 = self.Compute50WEMA()
        sma200 = self.mstr_200w_sma

        if ema50 is None or sma200 is None or sma200 <= 0:
            return False, False, None, None, 0

        distance_pct = ((ema50 - sma200) / sma200) * 100.0

        # Golden cross: EMA50 above SMA200
        is_golden = ema50 > sma200

        # Check slopes (need previous values — approximate from last few weeks)
        if self.weekly_closes.Count < 54:
            return is_golden, False, ema50, sma200, distance_pct

        # Compute EMA50 from 4 weeks ago for slope
        closes_prev = [self.weekly_closes[i] for i in range(4, min(self.weekly_closes.Count, 204))]
        closes_prev.reverse()
        if len(closes_prev) >= 50:
            ema50_prev = sum(closes_prev[:50]) / 50.0
            k = 2.0 / 51.0
            for price in closes_prev[50:]:
                ema50_prev = price * k + ema50_prev * (1.0 - k)
        else:
            ema50_prev = ema50

        # SMA200 from 4 weeks ago
        if self.weekly_closes.Count >= 204:
            sma200_prev = sum(self.weekly_closes[i] for i in range(4, 204)) / 200.0
        else:
            sma200_prev = sma200

        ema50_falling = ema50 < ema50_prev
        sma200_falling = sma200 < sma200_prev

        # Convergence-down: both falling AND close together
        converging_down = (ema50_falling and sma200_falling and
                          abs(distance_pct) < self.trend_convergence_pct)

        return is_golden, converging_down, ema50, sma200, distance_pct

    def GetDynamicLeapMultiplier(self, premium):
        """v2.8 DYNAMIC premium-based LEAP blend."""
        if premium < 0.8:
            return 0.60 * 6.0 + 0.40 * 12.0  # 8.4
        elif premium < 1.2:
            return 0.50 * 5.0 + 0.50 * 10.0  # 7.5
        elif premium <= 1.5:
            return 0.60 * 4.0 + 0.40 * 8.0   # 5.6
        else:
            return 0.70 * 3.0 + 0.30 * 6.0   # 3.9

    def ComputeMSTRPremium(self, mstr_price, btc_price, year):
        holdings = self.GetBTCHoldings(year)
        shares = self.GetDilutedShares(year)
        if holdings == 0 or shares == 0 or btc_price <= 0:
            return 1.0
        nav_per_share = (btc_price * holdings) / shares
        if nav_per_share <= 0:
            return 999
        return mstr_price / nav_per_share

    def CheckMACDBearishDivergence(self):
        if not self.mstr_macd.IsReady:
            return False
        if self.price_highs_window.Count < 20:
            return False
        recent_price_high = max(self.price_highs_window[i] for i in range(5))
        older_price_high = max(self.price_highs_window[i] for i in range(10, min(20, self.price_highs_window.Count)))
        price_higher_high = recent_price_high > older_price_high
        macd_hist = self.mstr_macd.Current.Value - self.mstr_macd.Signal.Current.Value
        return price_higher_high and macd_hist < 0

    # ══════════════════════════════════════════════════════════
    # CANDLESTICK PATTERN DETECTION — Weekly MSTR bars only
    # ══════════════════════════════════════════════════════════

    def DetectBullishPattern(self, bar_idx=0):
        """Detect bullish candlestick pattern on a weekly MSTR bar.
        bar_idx=0 → current bar, bar_idx=1 → prior bar, etc.
        Returns (pattern_found: bool, pattern_name: str)
        Requires at least bar_idx+2 bars in rolling windows (needs prior bar for engulfing).
        """
        need = bar_idx + 2
        if (self.weekly_closes.Count < need or self.weekly_opens.Count < need or
                self.weekly_highs.Count < need or self.weekly_lows.Count < need):
            return False, "INSUFFICIENT_DATA"

        # Current bar (index 0 = most recent in RollingWindow)
        c  = self.weekly_closes[bar_idx]
        o  = self.weekly_opens[bar_idx]
        h  = self.weekly_highs[bar_idx]
        l  = self.weekly_lows[bar_idx]

        # Prior bar
        pc = self.weekly_closes[bar_idx + 1]
        po = self.weekly_opens[bar_idx + 1]
        ph = self.weekly_highs[bar_idx + 1]
        pl = self.weekly_lows[bar_idx + 1]

        rng   = h - l
        if rng < 0.001:
            return False, "FLAT_BAR"

        body        = abs(c - o)
        lower_wick  = min(o, c) - l
        upper_wick  = h - max(o, c)
        bull_close  = c > o
        prior_bull  = pc > po
        prior_body  = abs(pc - po)
        prior_rng   = ph - pl if ph > pl else 0.001

        # ── 1. Hammer / Bullish Pin Bar ──
        # Long lower wick (≥2× body), small upper wick, close in upper 50% of range
        if (lower_wick >= 2.0 * max(body, rng * 0.02) and
                lower_wick >= 0.40 * rng and
                upper_wick <= 0.35 * rng and
                c >= l + 0.50 * rng):
            return True, "HAMMER"

        # ── 2. Bullish Engulfing ──
        # Prior: bearish. Current body fully engulfs prior body, strong bull close.
        if (bull_close and not prior_bull and
                prior_body > 0.15 * prior_rng and
                o <= pc and c >= po and
                body >= prior_body * 0.8):
            return True, "ENGULFING"

        # ── 3. Dragonfly Doji ──
        # Body ≤10% of range, lower wick ≥65% of range (indecision at lows → bull)
        if (body / rng <= 0.10 and lower_wick >= 0.65 * rng):
            return True, "DOJI_DRAGON"

        # ── 4. Morning Star (simplified 2-bar) ──
        # Prior: large bearish body. Current: bullish close above 50% of prior bar.
        if (bull_close and not prior_bull and
                prior_body >= 0.30 * prior_rng and
                c > (po + pc) / 2.0):
            return True, "MORNING_STAR"

        # ── 5. Bullish Harami ──
        # Prior: large bearish bar. Current: small bullish body contained inside.
        if (bull_close and not prior_bull and
                o > pc and o < po and
                c > pc and c < po and
                body <= 0.50 * prior_body):
            return True, "HARAMI"

        return False, "NONE"

    def ComputeCandlestickOk(self):
        """Gate entry based on candlestick_mode.
        Returns (ok: bool, reason: str) for logging."""
        mode = self.candlestick_mode

        if mode == "none":
            return True, "CS_OFF"

        if mode == "strict":
            found, name = self.DetectBullishPattern(bar_idx=0)
            return found, f"CS_STRICT:{name}"

        if mode == "window_3":
            for i in range(self.candlestick_lookback):
                found, name = self.DetectBullishPattern(bar_idx=i)
                if found:
                    return True, f"CS_WIN3:{name}@bar{i}"
            return False, "CS_WIN3:NONE"

        if mode == "high_prob":
            # Only Hammer and Engulfing on the CURRENT bar
            found, name = self.DetectBullishPattern(bar_idx=0)
            if found and name in ("HAMMER", "ENGULFING"):
                return True, f"CS_HIGHPROB:{name}"
            return False, f"CS_HIGHPROB:REJECTED({name})"

        # Unknown mode — pass through
        return True, f"CS_UNKNOWN_MODE:{mode}"

    # ══════════════════════════════════════════════════════════
    # DAILY DATA & POSITION MANAGEMENT
    # ══════════════════════════════════════════════════════════

    def OnData(self, data):
        if self.IsWarmingUp:
            return
        if not data.ContainsKey("MSTR") or not data["MSTR"]:
            return

        mstr_price = self.Securities["MSTR"].Price
        if mstr_price <= 0:
            return

        if self.mstr_rsi.IsReady:
            self.rsi_window.Add(self.mstr_rsi.Current.Value)
        self.price_highs_window.Add(mstr_price)
        if self.mstr_atr.IsReady:
            self.atr_window.Add(self.mstr_atr.Current.Value)

        if self.Portfolio["MSTR"].Invested:
            self.bars_in_trade += 1
            self.ManagePositionDaily(mstr_price)

    def ManagePositionDaily(self, price):
        """Daily position management for BASE position."""
        if self.entry_price <= 0:
            return

        btc_price = self.Securities["BTCUSD"].Price
        year = self.Time.year
        current_premium = self.ComputeMSTRPremium(price, btc_price, year)
        leap_mult = self.GetDynamicLeapMultiplier(current_premium)

        # Update HWM (base position)
        self.position_hwm = max(self.position_hwm, price)
        stock_gain = ((self.position_hwm - self.entry_price) / self.entry_price) * 100
        leap_peak_gain = stock_gain * leap_mult
        self.peak_gain_pct = max(self.peak_gain_pct, leap_peak_gain)

        current_stock_gain = ((price - self.entry_price) / self.entry_price) * 100
        current_leap_gain = current_stock_gain * leap_mult

        # Also manage trend adder daily
        if self.trend_adder_active and self.trend_adder_entry_price > 0:
            self.ManageTrendAdderDaily(price, current_premium, leap_mult)

        # ── Initial Floor (base) ──
        if current_leap_gain < self.floor_deactivate_leap_gain:
            floor_price = self.entry_price * self.initial_floor_pct
            if price < floor_price:
                self.LiquidateAll("INITIAL_FLOOR", price, current_stock_gain, current_leap_gain)
                return

        # ── Panic Floor on Losers (base) ──
        if current_stock_gain < 0 and current_leap_gain <= self.panic_floor_pct:
            self.LiquidateAll("PANIC_FLOOR", price, current_stock_gain, current_leap_gain)
            return

        # ── Euphoria Premium Sell ──
        if current_premium > self.euphoria_premium and current_leap_gain > 0 and not self.euphoria_sell_done:
            base_qty = self.Portfolio["MSTR"].Quantity
            if self.trend_adder_active:
                base_qty -= self.trend_adder_qty
            qty_to_sell = int(base_qty * 0.15)
            if qty_to_sell > 0:
                self.MarketOrder("MSTR", -qty_to_sell)
                self.euphoria_sell_done = True
                self.Log(f"EUPHORIA SELL: {self.Time.strftime('%Y-%m-%d')} | Prem: {current_premium:.2f}x")

        # ── Tiered Profit Taking (base only) ──
        for i, (threshold, sell_pct) in enumerate(self.profit_tiers):
            if current_leap_gain >= threshold and not self.pt_hits[i]:
                base_qty = self.Portfolio["MSTR"].Quantity
                if self.trend_adder_active:
                    base_qty -= self.trend_adder_qty
                qty_to_sell = int(base_qty * sell_pct)
                if qty_to_sell > 0:
                    self.MarketOrder("MSTR", -qty_to_sell)
                    self.pt_hits[i] = True
                    self.Log(f"PT{i+1}: {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f} | LEAP: +{current_leap_gain:.0f}%")

        # ── Laddered Trailing Stop (base) ──
        trail_pct = 0
        tier_name = "NONE"
        for threshold, trail in self.ladder_tiers:
            if self.peak_gain_pct >= threshold:
                trail_pct = trail
                tier_name = f"+{threshold}%"
                break

        if trail_pct > 0:
            self.current_trail_pct = trail_pct
            stop_level = self.position_hwm * (1 - trail_pct / 100)
            if price < stop_level:
                self.LiquidateAll("LADDER_TRAIL", price, current_stock_gain, current_leap_gain)
                return

        # ── Max Hold Exit ──
        if self.bars_in_trade >= self.max_hold_bars:
            self.LiquidateAll("MAX_HOLD", price, current_stock_gain, current_leap_gain)
            return

        # ── Target Exit ──
        if current_leap_gain >= (self.target_mult - 1) * 100:
            self.LiquidateAll("TARGET_HIT", price, current_stock_gain, current_leap_gain)
            return

        # ── Below EMA50 + Losing ──
        if self.mstr_ema_50.IsReady and price < self.mstr_ema_50.Current.Value and current_leap_gain < 0:
            self.LiquidateAll("EMA50_LOSS", price, current_stock_gain, current_leap_gain)
            return

    def ManageTrendAdderDaily(self, price, current_premium, leap_mult):
        """Daily management of the trend adder position."""
        if self.trend_adder_entry_price <= 0:
            return

        # Update adder HWM
        self.trend_adder_hwm = max(self.trend_adder_hwm, price)
        adder_stock_gain = ((self.trend_adder_hwm - self.trend_adder_entry_price) / self.trend_adder_entry_price) * 100
        adder_leap_peak = adder_stock_gain * leap_mult
        self.trend_adder_peak_gain = max(self.trend_adder_peak_gain, adder_leap_peak)

        adder_current_stock = ((price - self.trend_adder_entry_price) / self.trend_adder_entry_price) * 100
        adder_current_leap = adder_current_stock * leap_mult

        # ── Adder Panic Floor (-60%) ──
        if adder_current_stock < 0 and adder_current_leap <= self.trend_adder_panic_floor:
            self.ExitTrendAdder("ADDER_PANIC", price, adder_current_stock, adder_current_leap)
            return

        # ── Adder Initial Floor (45% stop) ──
        if adder_current_leap < 500:  # Only active below +500%
            floor_price = self.trend_adder_entry_price * self.trend_adder_initial_floor
            if price < floor_price:
                self.ExitTrendAdder("ADDER_FLOOR", price, adder_current_stock, adder_current_leap)
                return

        # ── Adder Trailing Stops (safety only) ──
        for threshold, trail in self.trend_adder_ladder:
            if self.trend_adder_peak_gain >= threshold:
                stop = self.trend_adder_hwm * (1 - trail / 100)
                if price < stop:
                    self.ExitTrendAdder("ADDER_TRAIL", price, adder_current_stock, adder_current_leap)
                    return
                break

    def ExitTrendAdder(self, reason, price, stock_gain, leap_gain):
        """Exit only the trend adder position, keep base."""
        if self.trend_adder_qty > 0:
            self.MarketOrder("MSTR", -self.trend_adder_qty)
            self.Log(f"ADDER EXIT ({reason}): {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f} | "
                     f"Stock: {stock_gain:+.1f}% | LEAP: {leap_gain:+.1f}%")

            leap_mult = self.GetDynamicLeapMultiplier(
                self.ComputeMSTRPremium(price, self.Securities["BTCUSD"].Price, self.Time.year))
            self.adder_trade_log.append({
                "entry_date": "adder",
                "exit_date": self.Time,
                "entry_price": self.trend_adder_entry_price,
                "exit_price": price,
                "stock_gain_pct": stock_gain,
                "leap_gain_pct": leap_gain,
                "reason": reason,
            })

        self.trend_adder_active = False
        self.trend_adder_entry_price = 0
        self.trend_adder_qty = 0
        self.trend_adder_hwm = 0
        self.trend_adder_peak_gain = 0
        self.trend_confirmed_logged = False

    def LiquidateAll(self, reason, price, stock_gain, leap_gain):
        """Exit EVERYTHING — base + adder."""
        self.Liquidate("MSTR")
        self.Log(f"{reason}: {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f} | "
                 f"Stock: {stock_gain:+.1f}% | LEAP: {leap_gain:+.1f}%")
        self.RecordExit(reason, price, stock_gain, leap_gain)

        # Also reset adder state
        if self.trend_adder_active:
            adder_sg = ((price - self.trend_adder_entry_price) / self.trend_adder_entry_price * 100) if self.trend_adder_entry_price > 0 else 0
            leap_mult = self.GetDynamicLeapMultiplier(
                self.ComputeMSTRPremium(price, self.Securities["BTCUSD"].Price, self.Time.year))
            self.adder_trade_log.append({
                "entry_date": "adder",
                "exit_date": self.Time,
                "entry_price": self.trend_adder_entry_price,
                "exit_price": price,
                "stock_gain_pct": adder_sg,
                "leap_gain_pct": adder_sg * leap_mult,
                "reason": f"{reason}_WITH_BASE",
            })
        self.trend_adder_active = False
        self.trend_adder_entry_price = 0
        self.trend_adder_qty = 0
        self.trend_adder_hwm = 0
        self.trend_adder_peak_gain = 0
        self.trend_confirmed_logged = False
        self.golden_cross_weeks = 0

    # ══════════════════════════════════════════════════════════
    # WEEKLY CONSOLIDATION
    # ══════════════════════════════════════════════════════════

    def OnWeeklyConsolidate(self):
        if self.IsWarmingUp:
            return

        mstr_price = self.Securities["MSTR"].Price
        btc_price = self.Securities["BTCUSD"].Price
        if mstr_price <= 0:
            return

        history = self.History(["MSTR"], 5, Resolution.Daily)
        if history.empty:
            return

        try:
            mstr_data = history.loc["MSTR"] if "MSTR" in history.index.get_level_values(0) else None
        except:
            return
        if mstr_data is None or len(mstr_data) == 0:
            return

        week_open = float(mstr_data.iloc[0]["open"])
        week_close = float(mstr_data.iloc[-1]["close"])
        week_high = float(mstr_data["high"].max())
        week_low = float(mstr_data["low"].min())

        self.weekly_closes.Add(week_close)
        self.weekly_opens.Add(week_open)
        self.weekly_highs.Add(week_high)
        self.weekly_lows.Add(week_low)
        self.week_count += 1

        if btc_price > 0:
            try:
                btc_history = self.History(["BTCUSD"], 5, Resolution.Daily)
                if not btc_history.empty and "BTCUSD" in btc_history.index.get_level_values(0):
                    btc_week_close = float(btc_history.loc["BTCUSD"].iloc[-1]["close"])
                    self.btc_weekly_closes.Add(btc_week_close)
            except:
                pass

        old_sma = self.mstr_200w_sma
        self.mstr_200w_sma = self.ComputeWeeklySMA(self.sma_weekly_period)

        if old_sma is None and self.mstr_200w_sma is not None:
            self.Log(f"200W SMA READY: {self.Time.strftime('%Y-%m-%d')} | SMA=${self.mstr_200w_sma:.2f}")

        sma_200w = self.mstr_200w_sma
        if sma_200w is None:
            return

        above_200w = week_close > sma_200w
        green_candle = week_close > week_open

        if not above_200w:
            if not self.dipped_below_200w:
                self.Log(f"DIP BELOW 200W: {self.Time.strftime('%Y-%m-%d')} | MSTR=${week_close:.2f} < SMA=${sma_200w:.2f}")
            self.dipped_below_200w = True
            self.green_week_count = 0
            self.is_armed = False

        if self.dipped_below_200w and above_200w and green_candle:
            self.green_week_count += 1
        elif not above_200w:
            self.green_week_count = 0

        if self.green_week_count >= self.green_weeks_threshold and not self.is_armed:
            self.is_armed = True
            self.Log(f"ARMED: {self.Time.strftime('%Y-%m-%d')} | MSTR=${week_close:.2f} | SMA=${sma_200w:.2f}")

        if self.green_week_count > self.green_weeks_threshold + 10:
            self.dipped_below_200w = False
            self.already_entered_this_cycle = False

        year = self.Time.year
        prem = self.ComputeMSTRPremium(week_close, btc_price, year)
        self.premium_history.Add(prem)

        # ── Track Golden Cross Weeks ──
        if self.trend_adder_enabled and self.Portfolio["MSTR"].Invested and self.entry_price > 0:
            is_golden, converging_down, ema50, sma200, dist_pct = self.CheckGoldenCross()

            if is_golden:
                self.golden_cross_weeks += 1
            else:
                self.golden_cross_weeks = 0

            # Log golden cross confirmation
            if self.golden_cross_weeks >= self.trend_confirm_weeks and not self.trend_confirmed_logged:
                self.Log(f"GOLDEN CROSS CONFIRMED: {self.Time.strftime('%Y-%m-%d')} | "
                         f"EMA50=${ema50:.2f} > SMA200=${sma200:.2f} | Dist={dist_pct:.1f}% | "
                         f"Weeks={self.golden_cross_weeks}")
                self.trend_confirmed_logged = True

            # Convergence-down exit for adder
            if self.trend_adder_active and converging_down:
                adder_sg = ((mstr_price - self.trend_adder_entry_price) / self.trend_adder_entry_price * 100)
                leap_mult = self.GetDynamicLeapMultiplier(prem)
                adder_lg = adder_sg * leap_mult
                self.ExitTrendAdder("CONVERGENCE_DOWN", mstr_price, adder_sg, adder_lg)

    # ══════════════════════════════════════════════════════════
    # TRADE EVALUATION (ENTRY + WEEKLY EXITS)
    # ══════════════════════════════════════════════════════════

    def OnTradeBar(self):
        if self.IsWarmingUp:
            return

        mstr_price = self.Securities["MSTR"].Price
        btc_price = self.Securities["BTCUSD"].Price
        if mstr_price <= 0 or btc_price <= 0:
            return

        sma_200w = self.mstr_200w_sma
        if sma_200w is None:
            return

        year = self.Time.year
        current_premium = self.ComputeMSTRPremium(mstr_price, btc_price, year)

        # ── Entry Filters ──
        btc_200w = self.ComputeBTCWeeklySMA(200)
        btc_above_200w = btc_200w is not None and btc_price > btc_200w
        stoch_rsi = self.ComputeStochRSI()
        stoch_rsi_ok = stoch_rsi < self.stoch_rsi_entry_threshold

        premium_expanding = True
        if self.premium_history.Count > self.premium_lookback:
            prev_premium = self.premium_history[self.premium_lookback]
            if prev_premium > 0:
                prem_change = (current_premium - prev_premium) / prev_premium
                premium_expanding = prem_change > -0.20

        no_macd_div = not self.CheckMACDBearishDivergence()
        premium_ok = current_premium <= self.premium_cap
        cycle_ok = not self.already_entered_this_cycle
        btc_era = year >= 2020

        atr_quiet = True
        if self.atr_window.Count >= 20:
            current_atr = self.atr_window[0]
            atr_avg_20 = sum(self.atr_window[i] for i in range(20)) / 20
            atr_quiet = current_atr < 1.5 * atr_avg_20

        # ── Candlestick Gate ──
        cs_ok, cs_reason = self.ComputeCandlestickOk()

        all_filters = (
            self.is_armed and btc_above_200w and stoch_rsi_ok and
            premium_expanding and no_macd_div and premium_ok and
            cycle_ok and btc_era and atr_quiet and cs_ok
        )

        if self.is_armed and not self.Portfolio["MSTR"].Invested and btc_era:
            self.Log(f"CHECK {self.Time.strftime('%Y-%m-%d')}: "
                     f"BTC200W={'Y' if btc_above_200w else 'N'} "
                     f"StRSI={stoch_rsi:.0f}({'Y' if stoch_rsi_ok else 'N'}) "
                     f"PremOK={current_premium:.2f}({'Y' if premium_ok else 'N'}) "
                     f"CS={cs_reason} "
                     f"ALL={'Y' if all_filters else 'N'}")

        # ── Scale-in Entry Logic (50/50) ──
        if all_filters and not self.Portfolio["MSTR"].Invested and not self.first_entry_done:
            risk_capital = self.Portfolio.TotalPortfolioValue * self.risk_capital_pct
            deploy = risk_capital * 0.50
            qty = int(deploy / mstr_price)
            if qty > 0:
                self.MarketOrder("MSTR", qty)
                self.entry_price = mstr_price
                self.position_hwm = mstr_price
                self.peak_gain_pct = 0
                self.current_trail_pct = 0
                self.pt_hits = [False] * len(self.profit_tiers)
                self.premium_hwm = current_premium
                self.bars_in_trade = 0
                self.euphoria_sell_done = False
                self.first_entry_done = True
                self.second_entry_done = False
                self.base_qty = qty
                self.golden_cross_weeks = 0
                self.trend_confirmed_logged = False

                leap_mult = self.GetDynamicLeapMultiplier(current_premium)
                self.Log(f"ENTRY 1/2: {self.Time.strftime('%Y-%m-%d')} @ ${mstr_price:.2f} | "
                         f"LEAP_Mult={leap_mult:.1f}x | Qty={qty}")
                self.entry_dates.append(self.Time)

        elif all_filters and self.first_entry_done and not self.second_entry_done and self.Portfolio["MSTR"].Invested:
            risk_capital = self.Portfolio.TotalPortfolioValue * self.risk_capital_pct
            deploy = risk_capital * 0.50
            qty = int(deploy / mstr_price)
            if qty > 0:
                self.MarketOrder("MSTR", qty)
                self.entry_price = self.Portfolio["MSTR"].AveragePrice
                self.second_entry_done = True
                self.already_entered_this_cycle = True
                self.base_qty += qty
                self.Log(f"ENTRY 2/2: {self.Time.strftime('%Y-%m-%d')} @ ${mstr_price:.2f} | Total={self.base_qty}")

        # ── TREND ADDER ENTRY ──
        if (self.trend_adder_enabled and self.Portfolio["MSTR"].Invested and
            self.entry_price > 0 and not self.trend_adder_active and
            self.golden_cross_weeks >= self.trend_confirm_weeks and btc_era):

            adder_capital = self.Portfolio.TotalPortfolioValue * self.trend_adder_capital_pct
            adder_qty = int(adder_capital / mstr_price)
            if adder_qty > 0:
                self.MarketOrder("MSTR", adder_qty)
                self.trend_adder_active = True
                self.trend_adder_entry_price = mstr_price
                self.trend_adder_qty = adder_qty
                self.trend_adder_hwm = mstr_price
                self.trend_adder_peak_gain = 0

                is_golden, _, ema50, sma200, dist_pct = self.CheckGoldenCross()
                self.Log(f"TREND ADDER ENTRY: {self.Time.strftime('%Y-%m-%d')} @ ${mstr_price:.2f} | "
                         f"Qty={adder_qty} | GC_weeks={self.golden_cross_weeks} | "
                         f"EMA50=${ema50:.2f} SMA200=${sma200:.2f} Dist={dist_pct:.1f}%")

        # ── Weekly/Bar Exit Checks ──
        if self.Portfolio["MSTR"].Invested and self.entry_price > 0:
            leap_mult = self.GetDynamicLeapMultiplier(current_premium)
            current_stock_gain = ((mstr_price - self.entry_price) / self.entry_price) * 100
            current_leap_gain = current_stock_gain * leap_mult

            self.premium_hwm = max(self.premium_hwm, current_premium)
            premium_drop = ((self.premium_hwm - current_premium) / self.premium_hwm * 100) if self.premium_hwm > 0 else 0

            # BTC Death Cross
            try:
                gbtc_history = self.History(["GBTC"], 200, Resolution.Daily)
                if not gbtc_history.empty and "GBTC" in gbtc_history.index.get_level_values(0):
                    gbtc_closes = gbtc_history.loc["GBTC"]["close"].values
                    if len(gbtc_closes) >= 200:
                        sma_50 = np.mean(gbtc_closes[-50:])
                        sma_200_val = np.mean(gbtc_closes[-200:])
                        prev_sma_50 = np.mean(gbtc_closes[-51:-1])
                        if sma_50 < sma_200_val and prev_sma_50 >= sma_200_val:
                            self.LiquidateAll("BTC_DEATH_CROSS", mstr_price, current_stock_gain, current_leap_gain)
                            return
            except:
                pass

            # BTC 200W MA Break
            if btc_200w is not None and btc_price < btc_200w:
                if current_leap_gain < 0:
                    self.LiquidateAll("BTC_200W_BREAK", mstr_price, current_stock_gain, current_leap_gain)
                    return
                else:
                    base_qty = self.Portfolio["MSTR"].Quantity
                    if self.trend_adder_active:
                        base_qty -= self.trend_adder_qty
                    qty_to_sell = int(base_qty * 0.50)
                    if qty_to_sell > 0:
                        self.MarketOrder("MSTR", -qty_to_sell)
                        self.Log(f"BTC 200W BREAK + PROFIT: Sold 50% of base")

            # Premium Compression Exit
            if premium_drop >= self.premium_compress_pct and current_leap_gain > 0:
                base_qty = self.Portfolio["MSTR"].Quantity
                if self.trend_adder_active:
                    base_qty -= self.trend_adder_qty
                qty_to_sell = int(base_qty * 0.50)
                if qty_to_sell > 0:
                    self.MarketOrder("MSTR", -qty_to_sell)
                    self.Log(f"PREM COMPRESS: {self.Time.strftime('%Y-%m-%d')} | Drop={premium_drop:.0f}%")

    def RecordExit(self, reason, price, stock_gain, leap_gain):
        self.exit_dates.append(self.Time)
        self.trade_log.append({
            "entry_date": self.entry_dates[-1] if self.entry_dates else None,
            "exit_date": self.Time,
            "entry_price": self.entry_price,
            "exit_price": price,
            "stock_gain_pct": stock_gain,
            "leap_gain_pct": leap_gain,
            "reason": reason,
        })
        self.entry_price = 0
        self.position_hwm = 0
        self.peak_gain_pct = 0
        self.current_trail_pct = 0
        self.premium_hwm = 0
        self.bars_in_trade = 0
        self.first_entry_done = False
        self.second_entry_done = False
        self.euphoria_sell_done = False
        self.already_entered_this_cycle = False
        self.base_qty = 0

    def OnEndOfAlgorithm(self):
        res_name = self.trade_resolution.capitalize()
        self.Log("=" * 60)
        self.Log(f"MSTR CYCLE-LOW LEAP v2.8+ TREND ADDER ({res_name})")
        self.Log("=" * 60)
        self.Log(f"Weeks collected: {self.week_count} | 200W SMA: {'Yes' if self.mstr_200w_sma else 'No'}")
        self.Log(f"Base Trades: {len(self.trade_log)} | Adder Trades: {len(self.adder_trade_log)}")
        self.Log(f"Final Value: ${self.Portfolio.TotalPortfolioValue:,.2f}")
        self.Log(f"Return: {((self.Portfolio.TotalPortfolioValue / 100000) - 1) * 100:.1f}%")

        if self.trade_log:
            leap_gains = [t["leap_gain_pct"] for t in self.trade_log]
            winners = [g for g in leap_gains if g > 0]
            losers = [g for g in leap_gains if g <= 0]
            wr = len(winners)/len(leap_gains)*100 if leap_gains else 0
            self.Log(f"Base Win Rate: {len(winners)}/{len(leap_gains)} ({wr:.0f}%)")
            if winners:
                self.Log(f"Base Avg Win (LEAP): +{np.mean(winners):.1f}%")
            if losers:
                self.Log(f"Base Avg Loss (LEAP): {np.mean(losers):.1f}%")

        for i, t in enumerate(self.trade_log):
            entry_str = t['entry_date'].strftime('%Y-%m-%d') if hasattr(t['entry_date'], 'strftime') else str(t['entry_date'])
            exit_str = t['exit_date'].strftime('%Y-%m-%d') if hasattr(t['exit_date'], 'strftime') else str(t['exit_date'])
            self.Log(f"Base {i+1}: {entry_str} -> {exit_str} | "
                     f"${t['entry_price']:.2f} -> ${t['exit_price']:.2f} | "
                     f"Stock: {t['stock_gain_pct']:+.1f}% | LEAP: {t['leap_gain_pct']:+.1f}% | {t['reason']}")

        for i, t in enumerate(self.adder_trade_log):
            exit_str = t['exit_date'].strftime('%Y-%m-%d') if hasattr(t['exit_date'], 'strftime') else str(t['exit_date'])
            self.Log(f"Adder {i+1}: Entry ${t['entry_price']:.2f} -> Exit ${t['exit_price']:.2f} | "
                     f"Stock: {t['stock_gain_pct']:+.1f}% | LEAP: {t['leap_gain_pct']:+.1f}% | {t['reason']}")

        if self.Portfolio["MSTR"].Invested and self.entry_price > 0:
            cs = ((self.Securities["MSTR"].Price - self.entry_price) / self.entry_price) * 100
            cl = cs * self.leap_multiplier_base
            self.Log(f"OPEN BASE: Entry ${self.entry_price:.2f} | Now ${self.Securities['MSTR'].Price:.2f} | "
                     f"Stock: {cs:+.1f}% | LEAP: {cl:+.1f}%")
            if self.trend_adder_active:
                as_ = ((self.Securities["MSTR"].Price - self.trend_adder_entry_price) / self.trend_adder_entry_price) * 100
                al = as_ * self.leap_multiplier_base
                self.Log(f"OPEN ADDER: Entry ${self.trend_adder_entry_price:.2f} | "
                         f"Stock: {as_:+.1f}% | LEAP: {al:+.1f}%")
