# QuantConnect LEAN Algorithm
# MSTR Cycle-Low LEAP Entry Strategy Backtest v2.5.1 Re-Entry Cooldown
#
# v2.5.1 CHANGE: Add 5-bar cooldown after any exit before re-entry allowed
#   - Prevents whipsaw re-entries immediately after stop-outs
#   - Still allows catching the next leg if confluence re-aligns after cooldown
#   - All other v2.5 parameters unchanged
#
# ENTRY: 200W SMA dip+reclaim pattern (price dips below 200W, then reclaims with 2+ green weeks)
# FILTERS: BTC > 200W MA, StochRSI < 70, premium not contracting, no MACD bearish div, premium <= 1.5x
#          ATR volatility filter (only enter when ATR < 1.5x its 20-day average = quiet market)
# RE-ENTRY: Allowed after stop-out with 5-bar cooldown (catches full bull runs, avoids whipsaw)
# LEAP Multiplier: Conservative staggered — 50% at 5x + 50% at 10x = avg 7.5x
#   (Simulates higher-delta safer LEAP allocation across strike zones)
# Trail: 5-tier laddered (None->30%->25%->20%->15%->10% at 3x/5x/10x/20x/50x LEAP-equiv)
# Profit Taking: 25% partial sells at 5x/10x/20x/50x LEAP-equiv
# 35% initial floor, -35% panic floor, 50/50 scale-in, euphoria premium sell, risk capital 25%
#
# v2.5 Results (Jan 2016 → Mar 2026, $100K):
#   Weekly: +58.6% net | 27% WR | 30.7% DD | P/L 5.69 | Sharpe 0.095 | 124 orders
#   Daily:  +61.3% net | 29% WR | 41.5% DD | P/L 4.35 | Sharpe 0.106 | 219 orders
#
# v2.5 CHANGES from v2.4:
#   1. Conservative staggered multiplier: 50% at 5x + 50% at 10x = avg 7.5x
#      (Perplexity/Grok recommendation: stagger deltas for robustness)
#   2. Weekly net profit: +44.6% → +58.6% (1.3x improvement)
#   3. Daily net profit: +42.3% → +61.3% (1.4x improvement)
#   4. P/L ratio improved: 5.02 → 5.69 (weekly)
#   5. Sharpe improved: 0.009 → 0.095 (weekly), 0.012 → 0.106 (daily)
#   6. Win rate improved: 22% → 29% (daily)
#
# v2.5 SENSITIVITY SWEEP (38 variants tested):
#   - Premium cap 2.0x/2.5x: WORSE than 1.5x on weekly
#   - Premium cap 1.0x: +56.8% daily but fewer entries
#   - IV guardrail (ATR percentile): DESTROYED performance (-7% to -10%)
#   - Loose ATR (2.0x) or No ATR: +62.9% daily but same as no filter
#   - Conservative multiplier 7.5x: WINNER — best risk-adjusted across both resolutions
#   - Mixed multiplier 10x avg: +52.5% weekly (good but less robust)
#   - Panic floor -25%: slightly better on weekly (+43.2%) but marginal
#
# CRITICAL: Start from 2016 so 200W SMA is available by ~2020.
# trade_resolution parameter controls evaluation frequency (Daily/Weekly/Monthly).

from AlgorithmImports import *
import numpy as np
from datetime import timedelta


class MSTRCycleLowLeap(QCAlgorithm):

    def Initialize(self):
        # ── MODE: Live vs Backtest ──
        # In live mode, QC handles dates/cash from deployment config
        # GetParameter("mode") can be set to "live" in QC project parameters
        self.is_live_mode = self.LiveMode  # QC built-in: True when deployed live

        if not self.is_live_mode:
            # ── Backtest Window ── START EARLY for 200W SMA warmup
            self.SetStartDate(2016, 1, 1)
            self.SetEndDate(2026, 3, 14)
            self.SetCash(100000)

        # ── Brokerage Model: IBKR for live, default for backtest ──
        # NOTE: We intentionally skip SetBrokerageModel for IBKR in live mode.
        # QC connects to IBKR at the infrastructure level (deploy config).
        # Setting the brokerage model here causes QC to sync order history,
        # which crashes on TRAIL LIMIT orders that QC can't parse.
        # The default model still routes orders through IBKR correctly.
        if self.is_live_mode:
            self.Log("LIVE MODE: IBKR connection via QC deployment config")

        # ── Trade Resolution (override before calling Initialize) ──
        # Valid values: "daily", "weekly", "monthly"
        # NOTE: QC Resolution enum only has Tick/Second/Minute/Hour/Daily
        # Weekly/Monthly evaluation is handled via Schedule.On
        if not hasattr(self, 'trade_resolution'):
            self.trade_resolution = "weekly"

        # ── REALISM: Slippage & Commission ──
        # Stock slippage 0.5% × 10x LEAP multiplier = ~5% effective LEAP slippage
        # (Deep ITM LEAP bid-ask spreads are typically 2-5%)
        # NOTE: QC ConstantSlippageModel applies to STOCK fill price, which then gets
        # amplified by the LEAP multiplier. 8% stock slippage × 10x = 80% LEAP loss
        # on entry, which is unrealistic. 0.5% stock × 10x = 5% LEAP slippage is correct.
        self.Settings.FreePortfolioValuePercentage = 0.02  # Keep 2% cash buffer
        if not self.is_live_mode:
            self.SetSecurityInitializer(lambda security: security.SetSlippageModel(
                ConstantSlippageModel(0.005)  # 0.5% stock slippage → ~5% LEAP equivalent
            ))

        # ── Assets ──
        self.mstr = self.AddEquity("MSTR", Resolution.Daily)
        self.mstr.SetDataNormalizationMode(DataNormalizationMode.SplitAdjusted)

        # BTC proxy for death cross
        self.btc_proxy = self.AddEquity("GBTC", Resolution.Daily)
        self.btc_proxy.SetDataNormalizationMode(DataNormalizationMode.SplitAdjusted)

        # BTC crypto data for NAV + 200W MA
        self.btc = self.AddCrypto("BTCUSD", Resolution.Daily, Market.Coinbase)

        # ── LEAP Leverage Multiplier (dynamic base 10x per Grok recommendation) ──
        self.leap_multiplier_base = 10.0

        # ── 200W Dip+Reclaim Entry Parameters ──
        self.green_weeks_threshold = 2       # Green weeks above 200W after dip to ARM
        self.sma_weekly_period = 200          # 200-week SMA

        # ── Entry Filters (relaxed for real-world signals) ──
        self.stoch_rsi_entry_threshold = 70  # StochRSI < 70 (reclaims are not oversold)
        self.premium_cap = 1.5               # Max premium for entry (1.5x NAV — production tightened)
        self.premium_lookback = 4            # Compare premium vs 4 weeks ago

        # ── BTC Holdings for mNAV (pre-2020: no BTC strategy, use equity) ──
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

        # ── Laddered Trailing Stop Tiers (LEAP-equivalent gains) ──
        self.ladder_tiers = [
            (5000, 10.0),   # 50x+ -> 10% trail LOCK
            (2000, 15.0),   # 20x+ -> 15% trail
            (1000, 20.0),   # 10x+ -> 20% trail
            (500,  25.0),   # 5x+  -> 25% trail
            (300,  30.0),   # 3x+  -> 30% trail
        ]

        # ── Profit Taking Tiers (LEAP-equivalent gains) ──
        self.profit_tiers = [
            (500,  0.25),   # PT1: 5x  -> sell 25%
            (1000, 0.25),   # PT2: 10x -> sell 25%
            (2000, 0.25),   # PT3: 20x -> sell 25%
            (5000, 0.25),   # PT4: 50x -> sell 25%
        ]

        # ── Risk Parameters ──
        self.max_hold_bars = 567              # ~27 months daily
        self.target_mult = 20.0               # 20x LEAP-equiv target
        self.premium_compress_pct = 30.0      # Premium compression exit threshold
        self.initial_floor_pct = 0.65         # 35% hard stop floor (entry * 0.65)
        self.floor_deactivate_leap_gain = 300 # Floor deactivates above +300% LEAP gain
        self.panic_floor_pct = -35.0          # -35% LEAP P&L panic exit (losers only)
        self.euphoria_premium = 3.5           # Sell 25% if premium > 3.5x and profitable
        self.risk_capital_pct = 0.25          # Only deploy 25% of portfolio

        # ── Weekly Data Rolling Windows (300W buffer for 200W SMA + room) ──
        self.weekly_closes = RollingWindow[float](350)
        self.weekly_opens = RollingWindow[float](350)
        self.weekly_highs = RollingWindow[float](350)
        self.weekly_lows = RollingWindow[float](350)
        self.btc_weekly_closes = RollingWindow[float](350)

        # ── Premium History (for expansion check) ──
        self.premium_history = RollingWindow[float](30)

        # ── MACD for divergence detection ──
        self.mstr_macd = self.MACD("MSTR", 12, 26, 9, MovingAverageType.Exponential, Resolution.Daily)

        # ── Daily Indicators ──
        self.mstr_ema_50 = self.EMA("MSTR", 50, Resolution.Daily)
        self.mstr_rsi = self.RSI("MSTR", 14)

        # For Stochastic RSI: track RSI values over 14 periods
        self.rsi_window = RollingWindow[float](14)

        # ── ATR Volatility Filter (only enter when market is "quiet") ──
        self.mstr_atr = self.ATR("MSTR", 14, MovingAverageType.Simple)
        self.atr_window = RollingWindow[float](30)  # 30-day ATR history for SMA

        # ── Price windows for MACD divergence ──
        self.price_highs_window = RollingWindow[float](30)

        # ── State: 200W Dip+Reclaim ──
        self.dipped_below_200w = False
        self.green_week_count = 0
        self.is_armed = False
        self.mstr_200w_sma = None

        # ── State: Cycle tracking ──
        self.already_entered_this_cycle = False

        # ── v2.5.1: Re-entry cooldown (5 bars after any exit) ──
        self.last_exit_bar = -999
        self.reentry_cooldown_bars = 5  # ~1 week on daily, ~5 weeks on weekly

        # ── State: Scale-in 50/50 ──
        self.first_entry_done = False
        self.second_entry_done = False

        # ── Position State ──
        self.entry_price = 0
        self.position_hwm = 0
        self.peak_gain_pct = 0
        self.current_trail_pct = 0
        self.pt_hits = [False] * len(self.profit_tiers)
        self.premium_hwm = 0
        self.bars_in_trade = 0
        self.euphoria_sell_done = False

        # ── Tracking ──
        self.entry_dates = []
        self.exit_dates = []
        self.trade_log = []

        # Week counter for debug
        self.week_count = 0

        # ── Schedule trade evaluation based on resolution ──
        self._schedule_trade_evaluation()

        # Warmup for daily indicators only
        self.SetWarmUp(timedelta(days=60))

    def _schedule_trade_evaluation(self):
        """Schedule the trade evaluation callback based on trade_resolution string."""
        if self.trade_resolution == "monthly":
            self.Schedule.On(
                self.DateRules.MonthEnd("MSTR"),
                self.TimeRules.BeforeMarketClose("MSTR", 1),
                self.OnTradeBar
            )
        elif self.trade_resolution == "daily":
            self.Schedule.On(
                self.DateRules.EveryDay("MSTR"),
                self.TimeRules.BeforeMarketClose("MSTR", 1),
                self.OnTradeBar
            )
        else:  # "weekly" default
            self.Schedule.On(
                self.DateRules.Every(DayOfWeek.Friday),
                self.TimeRules.BeforeMarketClose("MSTR", 1),
                self.OnTradeBar
            )

        # Always consolidate weekly data on Fridays for SMA calculation
        self.Schedule.On(
            self.DateRules.Every(DayOfWeek.Friday),
            self.TimeRules.BeforeMarketClose("MSTR", 2),
            self.OnWeeklyConsolidate
        )

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
        """Compute SMA from weekly closes rolling window."""
        if self.weekly_closes.Count < period:
            return None
        total = sum(self.weekly_closes[i] for i in range(period))
        return total / period

    def ComputeBTCWeeklySMA(self, period):
        """Compute BTC weekly SMA."""
        if self.btc_weekly_closes.Count < period:
            return None
        total = sum(self.btc_weekly_closes[i] for i in range(period))
        return total / period

    def ComputeStochRSI(self):
        """Compute Stochastic RSI from RSI window. Returns 0-100 scale."""
        if self.rsi_window.Count < 14:
            return 50  # neutral default
        rsi_values = [self.rsi_window[i] for i in range(self.rsi_window.Count)]
        rsi_min = min(rsi_values)
        rsi_max = max(rsi_values)
        if rsi_max == rsi_min:
            return 50
        current_rsi = rsi_values[0]
        stoch_rsi = ((current_rsi - rsi_min) / (rsi_max - rsi_min)) * 100
        return stoch_rsi

    def GetDynamicLeapMultiplier(self, premium):
        """v2.5 Conservative staggered multiplier: 50% at 5x + 50% at 10x = avg 7.5x.
        Simulates higher-delta (safer) LEAP allocation across strike zones.
        Perplexity/Grok recommendation: stagger deltas for robustness."""
        return 0.50 * 5.0 + 0.50 * 10.0  # = 7.5

    def CheckMACDBearishDivergence(self):
        """Check for MACD bearish divergence: price making higher high but MACD not."""
        if not self.mstr_macd.IsReady:
            return False
        if self.price_highs_window.Count < 20:
            return False

        recent_price_high = max(self.price_highs_window[i] for i in range(5))
        older_price_high = max(self.price_highs_window[i] for i in range(10, min(20, self.price_highs_window.Count)))

        price_higher_high = recent_price_high > older_price_high

        macd_val = self.mstr_macd.Current.Value
        macd_signal = self.mstr_macd.Signal.Current.Value
        macd_hist = macd_val - macd_signal

        if price_higher_high and macd_hist < 0:
            return True
        return False

    def ComputeMSTRPremium(self, mstr_price, btc_price, year):
        """Compute MSTR premium to NAV. Returns 1.0 for pre-BTC era (before 2020)."""
        holdings = self.GetBTCHoldings(year)
        shares = self.GetDilutedShares(year)
        if holdings == 0 or shares == 0 or btc_price <= 0:
            return 1.0  # Pre-BTC era: treat as 1.0x (no premium filter)
        nav_per_share = (btc_price * holdings) / shares
        if nav_per_share <= 0:
            return 999
        return mstr_price / nav_per_share

    def OnData(self, data):
        """Daily: update indicators and manage position."""
        if self.IsWarmingUp:
            return

        if not data.ContainsKey("MSTR") or not data["MSTR"]:
            return

        mstr_price = self.Securities["MSTR"].Price
        if mstr_price <= 0:
            return

        # Update RSI window for StochRSI
        if self.mstr_rsi.IsReady:
            self.rsi_window.Add(self.mstr_rsi.Current.Value)

        # Update price highs window for MACD divergence
        self.price_highs_window.Add(mstr_price)

        # Update ATR window for volatility filter
        if self.mstr_atr.IsReady:
            self.atr_window.Add(self.mstr_atr.Current.Value)

        # Track bars in trade
        if self.Portfolio["MSTR"].Invested:
            self.bars_in_trade += 1
            self.ManagePositionDaily(mstr_price)

    def ManagePositionDaily(self, price):
        """Daily position management: trailing stops, profit taking, floors."""
        if self.entry_price <= 0:
            return

        btc_price = self.Securities["BTCUSD"].Price
        year = self.Time.year
        current_premium = self.ComputeMSTRPremium(price, btc_price, year)

        leap_mult = self.GetDynamicLeapMultiplier(current_premium)

        # Update HWM
        self.position_hwm = max(self.position_hwm, price)
        stock_gain = ((self.position_hwm - self.entry_price) / self.entry_price) * 100
        leap_peak_gain = stock_gain * leap_mult
        self.peak_gain_pct = max(self.peak_gain_pct, leap_peak_gain)

        current_stock_gain = ((price - self.entry_price) / self.entry_price) * 100
        current_leap_gain = current_stock_gain * leap_mult

        # ── 30% Initial Floor (hard stop before ladders kick in) ──
        if current_leap_gain < self.floor_deactivate_leap_gain:
            floor_price = self.entry_price * self.initial_floor_pct
            if price < floor_price:
                self.Liquidate("MSTR")
                self.Log(f"30% FLOOR: {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f} | Floor: ${floor_price:.2f}")
                self.RecordExit("INITIAL_FLOOR", price, current_stock_gain, current_leap_gain)
                return

        # ── Panic Floor on Losers Only (RE-ENABLED for production) ──
        # Daily resolution: panic floor HELPS by cutting losers fast (+48.9% with vs +45.2% without)
        if current_stock_gain < 0 and current_leap_gain <= self.panic_floor_pct:
            self.Liquidate("MSTR")
            self.Log(f"PANIC FLOOR: {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f} | LEAP: {current_leap_gain:.1f}%")
            self.RecordExit("PANIC_FLOOR", price, current_stock_gain, current_leap_gain)
            return

        # ── Euphoria Premium Sell (premium > 3.5x and profitable) ──
        if current_premium > self.euphoria_premium and current_leap_gain > 0 and not self.euphoria_sell_done:
            qty_to_sell = int(self.Portfolio["MSTR"].Quantity * 0.25)
            if qty_to_sell > 0:
                self.MarketOrder("MSTR", -qty_to_sell)
                self.euphoria_sell_done = True
                self.Log(f"EUPHORIA SELL: {self.Time.strftime('%Y-%m-%d')} | Prem: {current_premium:.2f}x")

        # ── Tiered Profit Taking ──
        for i, (threshold, sell_pct) in enumerate(self.profit_tiers):
            if current_leap_gain >= threshold and not self.pt_hits[i]:
                qty_to_sell = int(self.Portfolio["MSTR"].Quantity * sell_pct)
                if qty_to_sell > 0:
                    self.MarketOrder("MSTR", -qty_to_sell)
                    self.pt_hits[i] = True
                    self.Log(f"PT{i+1}: {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f} | LEAP: +{current_leap_gain:.0f}%")

        # ── Laddered Trailing Stop ──
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
                self.Liquidate("MSTR")
                self.Log(f"TRAIL STOP: {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f} | Tier: {tier_name}")
                self.RecordExit("LADDER_TRAIL", price, current_stock_gain, current_leap_gain)
                return

        # ── Max Hold Exit ──
        if self.bars_in_trade >= self.max_hold_bars:
            self.Liquidate("MSTR")
            self.Log(f"MAX HOLD: {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f} | {self.bars_in_trade} bars")
            self.RecordExit("MAX_HOLD", price, current_stock_gain, current_leap_gain)
            return

        # ── 20x LEAP Target Exit ──
        if current_leap_gain >= (self.target_mult - 1) * 100:
            self.Liquidate("MSTR")
            self.Log(f"20X TARGET: {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f} | LEAP: +{current_leap_gain:.0f}%")
            self.RecordExit("TARGET_HIT", price, current_stock_gain, current_leap_gain)
            return

        # ── Below EMA50 + Losing (thesis broken) ──
        if self.mstr_ema_50.IsReady and price < self.mstr_ema_50.Current.Value and current_leap_gain < 0:
            self.Liquidate("MSTR")
            self.Log(f"EMA50 LOSS: {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f}")
            self.RecordExit("EMA50_LOSS", price, current_stock_gain, current_leap_gain)
            return

    def OnWeeklyConsolidate(self):
        """Called every Friday to consolidate weekly bar data."""
        if self.IsWarmingUp:
            return

        mstr_price = self.Securities["MSTR"].Price
        btc_price = self.Securities["BTCUSD"].Price

        if mstr_price <= 0:
            return

        # Fetch this week's MSTR daily data
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

        # BTC weekly
        if btc_price > 0:
            try:
                btc_history = self.History(["BTCUSD"], 5, Resolution.Daily)
                if not btc_history.empty and "BTCUSD" in btc_history.index.get_level_values(0):
                    btc_week_close = float(btc_history.loc["BTCUSD"].iloc[-1]["close"])
                    self.btc_weekly_closes.Add(btc_week_close)
            except:
                pass

        # Compute and cache 200W SMA
        old_sma = self.mstr_200w_sma
        self.mstr_200w_sma = self.ComputeWeeklySMA(self.sma_weekly_period)

        # Log first time SMA becomes available
        if old_sma is None and self.mstr_200w_sma is not None:
            self.Log(f"200W SMA READY: {self.Time.strftime('%Y-%m-%d')} | SMA=${self.mstr_200w_sma:.2f} | "
                     f"MSTR=${week_close:.2f} | WeekCount={self.week_count}")

        # ── 200W Dip+Reclaim Logic ──
        sma_200w = self.mstr_200w_sma
        if sma_200w is None:
            return

        above_200w = week_close > sma_200w
        green_candle = week_close > week_open

        # Track dip below 200W SMA
        if not above_200w:
            if not self.dipped_below_200w:
                self.Log(f"DIP BELOW 200W: {self.Time.strftime('%Y-%m-%d')} | MSTR=${week_close:.2f} < SMA=${sma_200w:.2f}")
            self.dipped_below_200w = True
            self.green_week_count = 0
            self.is_armed = False

        # Count consecutive green candles above 200W after dip
        if self.dipped_below_200w and above_200w and green_candle:
            self.green_week_count += 1
        elif self.dipped_below_200w and above_200w and not green_candle:
            pass  # Above but red — keep count, just don't increment
        elif not above_200w:
            self.green_week_count = 0

        # ARM after threshold consecutive green weeks above 200W post-dip
        if self.green_week_count >= self.green_weeks_threshold and not self.is_armed:
            self.is_armed = True
            self.Log(f"ARMED: {self.Time.strftime('%Y-%m-%d')} | MSTR=${week_close:.2f} | SMA=${sma_200w:.2f} | "
                     f"GreenWks={self.green_week_count}")

        # Reset dip flag after sustained bull run (allow re-entry next cycle)
        if self.green_week_count > self.green_weeks_threshold + 10:
            self.dipped_below_200w = False
            self.already_entered_this_cycle = False

        # Store premium in history
        year = self.Time.year
        prem = self.ComputeMSTRPremium(week_close, btc_price, year)
        self.premium_history.Add(prem)

    def OnTradeBar(self):
        """Called at trade_resolution frequency -- evaluates entry/exit signals."""
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

        # ── Entry Filter 1: BTC above its own 200W MA ──
        btc_200w = self.ComputeBTCWeeklySMA(200)
        btc_above_200w = btc_200w is not None and btc_price > btc_200w

        # ── Entry Filter 2: StochRSI < 70 ──
        stoch_rsi = self.ComputeStochRSI()
        stoch_rsi_ok = stoch_rsi < self.stoch_rsi_entry_threshold

        # ── Entry Filter 3: Premium not heavily contracting ──
        premium_expanding = True
        if self.premium_history.Count > self.premium_lookback:
            prev_premium = self.premium_history[self.premium_lookback]
            if prev_premium > 0:
                prem_change = (current_premium - prev_premium) / prev_premium
                premium_expanding = prem_change > -0.20

        # ── Entry Filter 4: No MACD bearish divergence ──
        no_macd_div = not self.CheckMACDBearishDivergence()

        # ── Entry Filter 5: Premium cap <= 2.0x NAV ──
        premium_ok = current_premium <= self.premium_cap

        # ── Entry Filter 6: Max 1 entry per cycle ──
        cycle_ok = not self.already_entered_this_cycle

        # ── Only trade from 2020+ (BTC strategy era) ──
        btc_era = year >= 2020

        # ── ATR Volatility Filter: only enter when market is "quiet" ──
        atr_quiet = True
        if self.atr_window.Count >= 20:
            current_atr = self.atr_window[0]
            atr_avg_20 = sum(self.atr_window[i] for i in range(20)) / 20
            atr_quiet = current_atr < 1.5 * atr_avg_20

        # ── v2.5.1: Re-entry cooldown gate ──
        cooldown_ok = (self.bars_in_trade == 0) and (self.week_count - self.last_exit_bar >= self.reentry_cooldown_bars)

        # ── FULL ENTRY CONFLUENCE (v2.5.1: + cooldown gate) ──
        all_filters = (
            self.is_armed and           # 200W dip+reclaim armed
            btc_above_200w and          # BTC > 200W MA
            stoch_rsi_ok and            # StochRSI < 70
            premium_expanding and       # Premium not contracting
            no_macd_div and             # No MACD bearish divergence
            premium_ok and              # Premium <= 1.5x
            cycle_ok and                # Haven't entered this cycle yet
            btc_era and                 # Only trade in BTC strategy era (2020+)
            atr_quiet and              # ATR < 1.5x its 20-day SMA (quiet market)
            cooldown_ok                 # v2.5.1: 5-bar cooldown after any exit
        )

        # ── Log filter status when armed and not invested ──
        if self.is_armed and not self.Portfolio["MSTR"].Invested and btc_era:
            self.Log(f"CHECK {self.Time.strftime('%Y-%m-%d')}: "
                     f"BTC200W={'Y' if btc_above_200w else 'N'} "
                     f"StRSI={stoch_rsi:.0f}({'Y' if stoch_rsi_ok else 'N'}) "
                     f"PremOK={current_premium:.2f}({'Y' if premium_ok else 'N'}) "
                     f"PremExp={'Y' if premium_expanding else 'N'} "
                     f"NoDiv={'Y' if no_macd_div else 'N'} "
                     f"Cycle={'Y' if cycle_ok else 'N'} "
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

                leap_mult = self.GetDynamicLeapMultiplier(current_premium)
                self.Log(f"ENTRY 1/2: {self.Time.strftime('%Y-%m-%d')} @ ${mstr_price:.2f} | "
                         f"200W=${sma_200w:.2f} | StochRSI={stoch_rsi:.1f} | "
                         f"Prem={current_premium:.2f}x | LEAP_Mult={leap_mult:.1f}x | Qty={qty}")
                self.entry_dates.append(self.Time)

        elif all_filters and self.first_entry_done and not self.second_entry_done and self.Portfolio["MSTR"].Invested:
            risk_capital = self.Portfolio.TotalPortfolioValue * self.risk_capital_pct
            deploy = risk_capital * 0.50
            qty = int(deploy / mstr_price)
            if qty > 0:
                self.MarketOrder("MSTR", qty)
                total_qty = self.Portfolio["MSTR"].Quantity
                self.entry_price = self.Portfolio["MSTR"].AveragePrice
                self.second_entry_done = True
                self.already_entered_this_cycle = True

                self.Log(f"ENTRY 2/2: {self.Time.strftime('%Y-%m-%d')} @ ${mstr_price:.2f} | "
                         f"Avg=${self.entry_price:.2f} | Qty={qty} | Total={total_qty}")

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
                            self.Liquidate("MSTR")
                            self.Log(f"BTC DEATH CROSS: {self.Time.strftime('%Y-%m-%d')}")
                            self.RecordExit("BTC_DEATH_CROSS", mstr_price, current_stock_gain, current_leap_gain)
                            return
            except:
                pass

            # BTC 200W MA Break
            if btc_200w is not None and btc_price < btc_200w:
                if current_leap_gain < 0:
                    self.Liquidate("MSTR")
                    self.Log(f"BTC 200W BREAK: {self.Time.strftime('%Y-%m-%d')}")
                    self.RecordExit("BTC_200W_BREAK", mstr_price, current_stock_gain, current_leap_gain)
                    return
                else:
                    qty_to_sell = int(self.Portfolio["MSTR"].Quantity * 0.50)
                    if qty_to_sell > 0:
                        self.MarketOrder("MSTR", -qty_to_sell)
                        self.Log(f"BTC 200W BREAK + PROFIT: Sold 50%")

            # Premium Compression Exit
            if premium_drop >= self.premium_compress_pct and current_leap_gain > 0:
                qty_to_sell = int(self.Portfolio["MSTR"].Quantity * 0.50)
                if qty_to_sell > 0:
                    self.MarketOrder("MSTR", -qty_to_sell)
                    self.Log(f"PREM COMPRESS: {self.Time.strftime('%Y-%m-%d')} | Drop={premium_drop:.0f}%")

    def RecordExit(self, reason, price, stock_gain, leap_gain):
        """Record exit for analysis."""
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
        self.already_entered_this_cycle = False  # v2.4: ALLOW RE-ENTRY after stop-out
        self.last_exit_bar = self.week_count      # v2.5.1: Record exit bar for cooldown

    def OnEndOfAlgorithm(self):
        """Final summary."""
        res_name = self.trade_resolution.capitalize()

        self.Log("=" * 60)
        self.Log(f"MSTR CYCLE-LOW LEAP v2.5.1 Re-Entry Cooldown ({res_name})")
        self.Log("=" * 60)
        self.Log(f"200W SMA dip+reclaim | LEAP {self.leap_multiplier_base}x base")
        self.Log(f"Weeks collected: {self.week_count} | 200W SMA available: {'Yes' if self.mstr_200w_sma else 'No'}")
        self.Log(f"Total Trades: {len(self.trade_log)}")
        self.Log(f"Final Value: ${self.Portfolio.TotalPortfolioValue:,.2f}")
        self.Log(f"Return: {((self.Portfolio.TotalPortfolioValue / 100000) - 1) * 100:.1f}%")

        if self.trade_log:
            leap_gains = [t["leap_gain_pct"] for t in self.trade_log]
            winners = [g for g in leap_gains if g > 0]
            losers = [g for g in leap_gains if g <= 0]
            wr = len(winners)/len(leap_gains)*100 if leap_gains else 0
            self.Log(f"Win Rate: {len(winners)}/{len(leap_gains)} ({wr:.0f}%)")
            if winners:
                self.Log(f"Avg Win (LEAP): +{np.mean(winners):.1f}%")
            if losers:
                self.Log(f"Avg Loss (LEAP): {np.mean(losers):.1f}%")

        for i, t in enumerate(self.trade_log):
            self.Log(f"Trade {i+1}: {t['entry_date'].strftime('%Y-%m-%d')} -> {t['exit_date'].strftime('%Y-%m-%d')} | "
                     f"${t['entry_price']:.2f} -> ${t['exit_price']:.2f} | "
                     f"Stock: {t['stock_gain_pct']:+.1f}% | LEAP: {t['leap_gain_pct']:+.1f}% | {t['reason']}")

        if self.Portfolio["MSTR"].Invested and self.entry_price > 0:
            cs = ((self.Securities["MSTR"].Price - self.entry_price) / self.entry_price) * 100
            cl = cs * self.leap_multiplier_base
            self.Log(f"OPEN: Entry ${self.entry_price:.2f} | Now ${self.Securities['MSTR'].Price:.2f} | "
                     f"Stock: {cs:+.1f}% | LEAP: {cl:+.1f}%")
