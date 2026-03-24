# QuantConnect LEAN Algorithm
# MARA Cycle-Low LEAP Entry Strategy Backtest v2.8+ TREND ADDER
#
# Adapted from MSTR v2.8+ for Marathon Digital Holdings (MARA).
# MARA is a BTC miner with high BTC beta but no BTC treasury premium.
# Instead of mNAV premium, uses price/200W-SMA ratio as valuation metric.
#
# DAILY resolution (confirmed working on TradingView daily chart).

from AlgorithmImports import *
import numpy as np
from datetime import timedelta


class MARACycleLowLeap(QCAlgorithm):

    def Initialize(self):
        self.is_live_mode = self.LiveMode

        if not self.is_live_mode:
            self.SetStartDate(2019, 1, 1)
            self.SetEndDate(2025, 12, 31)
            self.SetCash(100000)

        if not hasattr(self, 'trade_resolution'):
            self.trade_resolution = "daily"

        # ── REALISM ──
        self.Settings.FreePortfolioValuePercentage = 0.02
        if not self.is_live_mode:
            self.SetSecurityInitializer(lambda security: security.SetSlippageModel(
                ConstantSlippageModel(0.005)
            ))

        # ── Assets ──
        self.mara = self.AddEquity("MARA", Resolution.Daily)
        self.mara.SetDataNormalizationMode(DataNormalizationMode.SplitAdjusted)
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
        self.premium_cap = 3.0  # MARA can trade at higher price/SMA ratios than MSTR
        self.premium_lookback = 4

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
        self.euphoria_premium = 5.0  # MARA runs hotter than MSTR
        self.risk_capital_pct = 0.25

        # ══════════════════════════════════════════════════════════
        # TREND ADDER PARAMETERS
        # ══════════════════════════════════════════════════════════
        self.trend_adder_enabled = True
        self.trend_confirm_weeks = 4
        self.trend_convergence_pct = 15.0
        self.trend_adder_capital_pct = 0.25
        self.trend_adder_panic_floor = -60.0
        self.trend_adder_initial_floor = 0.55
        self.trend_adder_ladder = [
            (10000, 25.0),
            (5000,  35.0),
        ]

        # ── Weekly Data Rolling Windows ──
        self.weekly_closes = RollingWindow[float](350)
        self.weekly_opens = RollingWindow[float](350)
        self.weekly_highs = RollingWindow[float](350)
        self.weekly_lows = RollingWindow[float](350)
        self.btc_weekly_closes = RollingWindow[float](350)

        # ── Premium History (price/SMA ratio for MARA) ──
        self.premium_history = RollingWindow[float](30)

        # ── Daily Indicators ──
        self.mara_macd = self.MACD("MARA", 12, 26, 9, MovingAverageType.Exponential, Resolution.Daily)
        self.mara_ema_50 = self.EMA("MARA", 50, Resolution.Daily)
        self.mara_rsi = self.RSI("MARA", 14)
        self.rsi_window = RollingWindow[float](14)
        self.mara_atr = self.ATR("MARA", 14, MovingAverageType.Simple)
        self.atr_window = RollingWindow[float](30)
        self.price_highs_window = RollingWindow[float](30)

        # ── State: 200W Dip+Reclaim ──
        self.dipped_below_200w = False
        self.green_week_count = 0
        self.is_armed = False
        self.mara_200w_sma = None

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
        self.base_qty = 0

        # ── Schedule ──
        self._schedule_trade_evaluation()
        self.SetWarmUp(timedelta(days=60))

        # ── Seed rolling windows from historical data ──
        self._seed_weekly_history()

    def _seed_weekly_history(self):
        """Pre-populate rolling windows with historical weekly data."""
        try:
            mara_hist = self.History(self.Symbol("MARA"), 350 * 7, Resolution.Daily)
            if mara_hist.empty:
                self.Log("SEED: No MARA history available")
                return

            if "MARA" in mara_hist.index.get_level_values(0):
                mara_data = mara_hist.loc["MARA"]
            else:
                mara_data = mara_hist

            mara_data = mara_data.copy()
            mara_data.index = mara_data.index.tz_localize(None) if hasattr(mara_data.index, 'tz_localize') and mara_data.index.tz is not None else mara_data.index
            weekly = mara_data.resample('W-FRI')

            weekly_o = weekly['open'].first().dropna()
            weekly_c = weekly['close'].last().dropna()
            weekly_h = weekly['high'].max().dropna()
            weekly_l = weekly['low'].min().dropna()

            count = 0
            for idx in weekly_c.index:
                if idx in weekly_o.index and idx in weekly_h.index and idx in weekly_l.index:
                    self.weekly_closes.Add(float(weekly_c[idx]))
                    self.weekly_opens.Add(float(weekly_o[idx]))
                    self.weekly_highs.Add(float(weekly_h[idx]))
                    self.weekly_lows.Add(float(weekly_l[idx]))
                    count += 1

            self.mara_200w_sma = self.ComputeWeeklySMA(self.sma_weekly_period)
            self.week_count = count

            self.Log(f"SEED: Loaded {count} weekly bars for MARA | "
                     f"200W SMA={'$' + f'{self.mara_200w_sma:.2f}' if self.mara_200w_sma else 'Not ready'}")

            # Seed BTC weekly closes
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
                self.Log(f"SEED: BTC history unavailable ({e})")

        except Exception as e:
            self.Log(f"SEED: History seeding failed ({e})")

    def _schedule_trade_evaluation(self):
        # MARA uses daily resolution
        self.Schedule.On(self.DateRules.EveryDay("MARA"),
            self.TimeRules.BeforeMarketClose("MARA", 1), self.OnTradeBar)

        self.Schedule.On(self.DateRules.Every(DayOfWeek.Friday),
            self.TimeRules.BeforeMarketClose("MARA", 2), self.OnWeeklyConsolidate)

    # ══════════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════════

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
        closes = [self.weekly_closes[i] for i in range(min(self.weekly_closes.Count, 200))]
        closes.reverse()
        if len(closes) < 50:
            return None
        ema = sum(closes[:50]) / 50.0
        k = 2.0 / (50.0 + 1.0)
        for price in closes[50:]:
            ema = price * k + ema * (1.0 - k)
        return ema

    def CheckGoldenCross(self):
        """Check if 50W EMA > 200W SMA with both rising."""
        ema50 = self.Compute50WEMA()
        sma200 = self.mara_200w_sma

        if ema50 is None or sma200 is None or sma200 <= 0:
            return False, False, None, None, 0

        distance_pct = ((ema50 - sma200) / sma200) * 100.0
        is_golden = ema50 > sma200

        if self.weekly_closes.Count < 54:
            return is_golden, False, ema50, sma200, distance_pct

        closes_prev = [self.weekly_closes[i] for i in range(4, min(self.weekly_closes.Count, 204))]
        closes_prev.reverse()
        if len(closes_prev) >= 50:
            ema50_prev = sum(closes_prev[:50]) / 50.0
            k = 2.0 / 51.0
            for price in closes_prev[50:]:
                ema50_prev = price * k + ema50_prev * (1.0 - k)
        else:
            ema50_prev = ema50

        if self.weekly_closes.Count >= 204:
            sma200_prev = sum(self.weekly_closes[i] for i in range(4, 204)) / 200.0
        else:
            sma200_prev = sma200

        ema50_falling = ema50 < ema50_prev
        sma200_falling = sma200 < sma200_prev

        converging_down = (ema50_falling and sma200_falling and
                          abs(distance_pct) < self.trend_convergence_pct)

        return is_golden, converging_down, ema50, sma200, distance_pct

    def ComputeMARAPremium(self, mara_price):
        """MARA 'premium' = price / 200W SMA ratio.
        Unlike MSTR, MARA has no BTC treasury NAV.
        Price/SMA ratio captures how extended MARA is above its long-term trend."""
        if self.mara_200w_sma is None or self.mara_200w_sma <= 0:
            return 1.0
        return mara_price / self.mara_200w_sma

    def GetDynamicLeapMultiplier(self, premium):
        """MARA dynamic LEAP blend based on price/SMA ratio.
        MARA typically trades at higher ratios than MSTR, so bands are wider."""
        if premium < 1.0:
            return 0.60 * 6.0 + 0.40 * 12.0  # 8.4 — below SMA, max leverage
        elif premium < 1.5:
            return 0.50 * 5.0 + 0.50 * 10.0  # 7.5 — fair value
        elif premium <= 2.5:
            return 0.60 * 4.0 + 0.40 * 8.0   # 5.6 — elevated
        else:
            return 0.70 * 3.0 + 0.30 * 6.0   # 3.9 — euphoric

    def CheckMACDBearishDivergence(self):
        if not self.mara_macd.IsReady:
            return False
        if self.price_highs_window.Count < 20:
            return False
        recent_price_high = max(self.price_highs_window[i] for i in range(5))
        older_price_high = max(self.price_highs_window[i] for i in range(10, min(20, self.price_highs_window.Count)))
        price_higher_high = recent_price_high > older_price_high
        macd_hist = self.mara_macd.Current.Value - self.mara_macd.Signal.Current.Value
        return price_higher_high and macd_hist < 0

    # ══════════════════════════════════════════════════════════
    # DAILY DATA & POSITION MANAGEMENT
    # ══════════════════════════════════════════════════════════

    def OnData(self, data):
        if self.IsWarmingUp:
            return
        if not data.ContainsKey("MARA") or not data["MARA"]:
            return

        mara_price = self.Securities["MARA"].Price
        if mara_price <= 0:
            return

        if self.mara_rsi.IsReady:
            self.rsi_window.Add(self.mara_rsi.Current.Value)
        self.price_highs_window.Add(mara_price)
        if self.mara_atr.IsReady:
            self.atr_window.Add(self.mara_atr.Current.Value)

        if self.Portfolio["MARA"].Invested:
            self.bars_in_trade += 1
            self.ManagePositionDaily(mara_price)

    def ManagePositionDaily(self, price):
        """Daily position management for BASE position."""
        if self.entry_price <= 0:
            return

        current_premium = self.ComputeMARAPremium(price)
        leap_mult = self.GetDynamicLeapMultiplier(current_premium)

        self.position_hwm = max(self.position_hwm, price)
        stock_gain = ((self.position_hwm - self.entry_price) / self.entry_price) * 100
        leap_peak_gain = stock_gain * leap_mult
        self.peak_gain_pct = max(self.peak_gain_pct, leap_peak_gain)

        current_stock_gain = ((price - self.entry_price) / self.entry_price) * 100
        current_leap_gain = current_stock_gain * leap_mult

        if self.trend_adder_active and self.trend_adder_entry_price > 0:
            self.ManageTrendAdderDaily(price, current_premium, leap_mult)

        # ── Initial Floor ──
        if current_leap_gain < self.floor_deactivate_leap_gain:
            floor_price = self.entry_price * self.initial_floor_pct
            if price < floor_price:
                self.LiquidateAll("INITIAL_FLOOR", price, current_stock_gain, current_leap_gain)
                return

        # ── Panic Floor ──
        if current_stock_gain < 0 and current_leap_gain <= self.panic_floor_pct:
            self.LiquidateAll("PANIC_FLOOR", price, current_stock_gain, current_leap_gain)
            return

        # ── Euphoria Sell ──
        if current_premium > self.euphoria_premium and current_leap_gain > 0 and not self.euphoria_sell_done:
            base_qty = self.Portfolio["MARA"].Quantity
            if self.trend_adder_active:
                base_qty -= self.trend_adder_qty
            qty_to_sell = int(base_qty * 0.15)
            if qty_to_sell > 0:
                self.MarketOrder("MARA", -qty_to_sell)
                self.euphoria_sell_done = True

        # ── Tiered Profit Taking ──
        for i, (threshold, sell_pct) in enumerate(self.profit_tiers):
            if current_leap_gain >= threshold and not self.pt_hits[i]:
                base_qty = self.Portfolio["MARA"].Quantity
                if self.trend_adder_active:
                    base_qty -= self.trend_adder_qty
                qty_to_sell = int(base_qty * sell_pct)
                if qty_to_sell > 0:
                    self.MarketOrder("MARA", -qty_to_sell)
                    self.pt_hits[i] = True

        # ── Laddered Trailing Stop ──
        trail_pct = 0
        for threshold, trail in self.ladder_tiers:
            if self.peak_gain_pct >= threshold:
                trail_pct = trail
                break

        if trail_pct > 0:
            self.current_trail_pct = trail_pct
            stop_level = self.position_hwm * (1 - trail_pct / 100)
            if price < stop_level:
                self.LiquidateAll("LADDER_TRAIL", price, current_stock_gain, current_leap_gain)
                return

        # ── Max Hold ──
        if self.bars_in_trade >= self.max_hold_bars:
            self.LiquidateAll("MAX_HOLD", price, current_stock_gain, current_leap_gain)
            return

        # ── Target Exit ──
        if current_leap_gain >= (self.target_mult - 1) * 100:
            self.LiquidateAll("TARGET_HIT", price, current_stock_gain, current_leap_gain)
            return

        # ── Below EMA50 + Losing ──
        if self.mara_ema_50.IsReady and price < self.mara_ema_50.Current.Value and current_leap_gain < 0:
            self.LiquidateAll("EMA50_LOSS", price, current_stock_gain, current_leap_gain)
            return

    def ManageTrendAdderDaily(self, price, current_premium, leap_mult):
        if self.trend_adder_entry_price <= 0:
            return

        self.trend_adder_hwm = max(self.trend_adder_hwm, price)
        adder_stock_gain = ((self.trend_adder_hwm - self.trend_adder_entry_price) / self.trend_adder_entry_price) * 100
        adder_leap_peak = adder_stock_gain * leap_mult
        self.trend_adder_peak_gain = max(self.trend_adder_peak_gain, adder_leap_peak)

        adder_current_stock = ((price - self.trend_adder_entry_price) / self.trend_adder_entry_price) * 100
        adder_current_leap = adder_current_stock * leap_mult

        if adder_current_stock < 0 and adder_current_leap <= self.trend_adder_panic_floor:
            self.ExitTrendAdder("ADDER_PANIC", price, adder_current_stock, adder_current_leap)
            return

        if adder_current_leap < 500:
            floor_price = self.trend_adder_entry_price * self.trend_adder_initial_floor
            if price < floor_price:
                self.ExitTrendAdder("ADDER_FLOOR", price, adder_current_stock, adder_current_leap)
                return

        for threshold, trail in self.trend_adder_ladder:
            if self.trend_adder_peak_gain >= threshold:
                stop = self.trend_adder_hwm * (1 - trail / 100)
                if price < stop:
                    self.ExitTrendAdder("ADDER_TRAIL", price, adder_current_stock, adder_current_leap)
                    return
                break

    def ExitTrendAdder(self, reason, price, stock_gain, leap_gain):
        if self.trend_adder_qty > 0:
            self.MarketOrder("MARA", -self.trend_adder_qty)
            self.Log(f"ADDER EXIT ({reason}): {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f} | "
                     f"Stock: {stock_gain:+.1f}% | LEAP: {leap_gain:+.1f}%")
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
        self.Liquidate("MARA")
        self.Log(f"{reason}: {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f} | "
                 f"Stock: {stock_gain:+.1f}% | LEAP: {leap_gain:+.1f}%")
        self.RecordExit(reason, price, stock_gain, leap_gain)

        if self.trend_adder_active:
            adder_sg = ((price - self.trend_adder_entry_price) / self.trend_adder_entry_price * 100) if self.trend_adder_entry_price > 0 else 0
            leap_mult = self.GetDynamicLeapMultiplier(self.ComputeMARAPremium(price))
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

        mara_price = self.Securities["MARA"].Price
        btc_price = self.Securities["BTCUSD"].Price
        if mara_price <= 0:
            return

        history = self.History(["MARA"], 5, Resolution.Daily)
        if history.empty:
            return

        try:
            mara_data = history.loc["MARA"] if "MARA" in history.index.get_level_values(0) else None
        except:
            return
        if mara_data is None or len(mara_data) == 0:
            return

        week_open = float(mara_data.iloc[0]["open"])
        week_close = float(mara_data.iloc[-1]["close"])
        week_high = float(mara_data["high"].max())
        week_low = float(mara_data["low"].min())

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

        old_sma = self.mara_200w_sma
        self.mara_200w_sma = self.ComputeWeeklySMA(self.sma_weekly_period)

        if old_sma is None and self.mara_200w_sma is not None:
            self.Log(f"200W SMA READY: {self.Time.strftime('%Y-%m-%d')} | SMA=${self.mara_200w_sma:.2f}")

        sma_200w = self.mara_200w_sma
        if sma_200w is None:
            return

        above_200w = week_close > sma_200w
        green_candle = week_close > week_open

        if not above_200w:
            if not self.dipped_below_200w:
                self.Log(f"DIP BELOW 200W: {self.Time.strftime('%Y-%m-%d')} | MARA=${week_close:.2f} < SMA=${sma_200w:.2f}")
            self.dipped_below_200w = True
            self.green_week_count = 0
            self.is_armed = False

        if self.dipped_below_200w and above_200w and green_candle:
            self.green_week_count += 1
        elif not above_200w:
            self.green_week_count = 0

        if self.green_week_count >= self.green_weeks_threshold and not self.is_armed:
            self.is_armed = True
            self.Log(f"ARMED: {self.Time.strftime('%Y-%m-%d')} | MARA=${week_close:.2f} | SMA=${sma_200w:.2f}")

        if self.green_week_count > self.green_weeks_threshold + 10:
            self.dipped_below_200w = False
            self.already_entered_this_cycle = False

        prem = self.ComputeMARAPremium(week_close)
        self.premium_history.Add(prem)

        # ── Track Golden Cross Weeks ──
        if self.trend_adder_enabled and self.Portfolio["MARA"].Invested and self.entry_price > 0:
            is_golden, converging_down, ema50, sma200, dist_pct = self.CheckGoldenCross()

            if is_golden:
                self.golden_cross_weeks += 1
            else:
                self.golden_cross_weeks = 0

            if self.golden_cross_weeks >= self.trend_confirm_weeks and not self.trend_confirmed_logged:
                self.Log(f"GOLDEN CROSS CONFIRMED: {self.Time.strftime('%Y-%m-%d')} | "
                         f"EMA50=${ema50:.2f} > SMA200=${sma200:.2f} | Dist={dist_pct:.1f}%")
                self.trend_confirmed_logged = True

            if self.trend_adder_active and converging_down:
                adder_sg = ((mara_price - self.trend_adder_entry_price) / self.trend_adder_entry_price * 100)
                leap_mult = self.GetDynamicLeapMultiplier(prem)
                adder_lg = adder_sg * leap_mult
                self.ExitTrendAdder("CONVERGENCE_DOWN", mara_price, adder_sg, adder_lg)

    # ══════════════════════════════════════════════════════════
    # TRADE EVALUATION
    # ══════════════════════════════════════════════════════════

    def OnTradeBar(self):
        if self.IsWarmingUp:
            return

        mara_price = self.Securities["MARA"].Price
        btc_price = self.Securities["BTCUSD"].Price
        if mara_price <= 0 or btc_price <= 0:
            return

        sma_200w = self.mara_200w_sma
        if sma_200w is None:
            return

        year = self.Time.year
        current_premium = self.ComputeMARAPremium(mara_price)

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

        all_filters = (
            self.is_armed and btc_above_200w and stoch_rsi_ok and
            premium_expanding and no_macd_div and premium_ok and
            cycle_ok and btc_era and atr_quiet
        )

        if self.is_armed and not self.Portfolio["MARA"].Invested and btc_era:
            self.Log(f"CHECK {self.Time.strftime('%Y-%m-%d')}: "
                     f"BTC200W={'Y' if btc_above_200w else 'N'} "
                     f"StRSI={stoch_rsi:.0f}({'Y' if stoch_rsi_ok else 'N'}) "
                     f"PremOK={current_premium:.2f}({'Y' if premium_ok else 'N'}) "
                     f"ALL={'Y' if all_filters else 'N'}")

        # ── Scale-in Entry (50/50) ──
        if all_filters and not self.Portfolio["MARA"].Invested and not self.first_entry_done:
            risk_capital = self.Portfolio.TotalPortfolioValue * self.risk_capital_pct
            deploy = risk_capital * 0.50
            qty = int(deploy / mara_price)
            if qty > 0:
                self.MarketOrder("MARA", qty)
                self.entry_price = mara_price
                self.position_hwm = mara_price
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
                self.Log(f"ENTRY 1/2: {self.Time.strftime('%Y-%m-%d')} @ ${mara_price:.2f} | "
                         f"LEAP_Mult={leap_mult:.1f}x | Qty={qty}")
                self.entry_dates.append(self.Time)

        elif all_filters and self.first_entry_done and not self.second_entry_done and self.Portfolio["MARA"].Invested:
            risk_capital = self.Portfolio.TotalPortfolioValue * self.risk_capital_pct
            deploy = risk_capital * 0.50
            qty = int(deploy / mara_price)
            if qty > 0:
                self.MarketOrder("MARA", qty)
                self.entry_price = self.Portfolio["MARA"].AveragePrice
                self.second_entry_done = True
                self.already_entered_this_cycle = True
                self.base_qty += qty
                self.Log(f"ENTRY 2/2: {self.Time.strftime('%Y-%m-%d')} @ ${mara_price:.2f}")

        # ── TREND ADDER ENTRY ──
        if (self.trend_adder_enabled and self.Portfolio["MARA"].Invested and
            self.entry_price > 0 and not self.trend_adder_active and
            self.golden_cross_weeks >= self.trend_confirm_weeks and btc_era):

            adder_capital = self.Portfolio.TotalPortfolioValue * self.trend_adder_capital_pct
            adder_qty = int(adder_capital / mara_price)
            if adder_qty > 0:
                self.MarketOrder("MARA", adder_qty)
                self.trend_adder_active = True
                self.trend_adder_entry_price = mara_price
                self.trend_adder_qty = adder_qty
                self.trend_adder_hwm = mara_price
                self.trend_adder_peak_gain = 0

                is_golden, _, ema50, sma200, dist_pct = self.CheckGoldenCross()
                self.Log(f"TREND ADDER: {self.Time.strftime('%Y-%m-%d')} @ ${mara_price:.2f} | "
                         f"Qty={adder_qty} | GC={self.golden_cross_weeks}w")

        # ── Exit Checks ──
        if self.Portfolio["MARA"].Invested and self.entry_price > 0:
            leap_mult = self.GetDynamicLeapMultiplier(current_premium)
            current_stock_gain = ((mara_price - self.entry_price) / self.entry_price) * 100
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
                            self.LiquidateAll("BTC_DEATH_CROSS", mara_price, current_stock_gain, current_leap_gain)
                            return
            except:
                pass

            # BTC 200W Break
            if btc_200w is not None and btc_price < btc_200w:
                if current_leap_gain < 0:
                    self.LiquidateAll("BTC_200W_BREAK", mara_price, current_stock_gain, current_leap_gain)
                    return
                else:
                    base_qty = self.Portfolio["MARA"].Quantity
                    if self.trend_adder_active:
                        base_qty -= self.trend_adder_qty
                    qty_to_sell = int(base_qty * 0.50)
                    if qty_to_sell > 0:
                        self.MarketOrder("MARA", -qty_to_sell)

            # Premium Compression Exit
            if premium_drop >= self.premium_compress_pct and current_leap_gain > 0:
                base_qty = self.Portfolio["MARA"].Quantity
                if self.trend_adder_active:
                    base_qty -= self.trend_adder_qty
                qty_to_sell = int(base_qty * 0.50)
                if qty_to_sell > 0:
                    self.MarketOrder("MARA", -qty_to_sell)

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
        self.Log("=" * 60)
        self.Log("MARA CYCLE-LOW LEAP v2.8+ TREND ADDER (Daily)")
        self.Log("=" * 60)
        self.Log(f"Weeks: {self.week_count} | 200W SMA: {'Yes' if self.mara_200w_sma else 'No'}")
        self.Log(f"Base Trades: {len(self.trade_log)} | Adder Trades: {len(self.adder_trade_log)}")
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
            entry_str = t['entry_date'].strftime('%Y-%m-%d') if hasattr(t['entry_date'], 'strftime') else str(t['entry_date'])
            exit_str = t['exit_date'].strftime('%Y-%m-%d') if hasattr(t['exit_date'], 'strftime') else str(t['exit_date'])
            self.Log(f"Base {i+1}: {entry_str} -> {exit_str} | "
                     f"${t['entry_price']:.2f} -> ${t['exit_price']:.2f} | "
                     f"Stock: {t['stock_gain_pct']:+.1f}% | LEAP: {t['leap_gain_pct']:+.1f}% | {t['reason']}")

        for i, t in enumerate(self.adder_trade_log):
            exit_str = t['exit_date'].strftime('%Y-%m-%d') if hasattr(t['exit_date'], 'strftime') else str(t['exit_date'])
            self.Log(f"Adder {i+1}: ${t['entry_price']:.2f} -> ${t['exit_price']:.2f} | "
                     f"Stock: {t['stock_gain_pct']:+.1f}% | LEAP: {t['leap_gain_pct']:+.1f}% | {t['reason']}")

        if self.Portfolio["MARA"].Invested and self.entry_price > 0:
            cs = ((self.Securities["MARA"].Price - self.entry_price) / self.entry_price) * 100
            cl = cs * self.leap_multiplier_base
            self.Log(f"OPEN: Entry ${self.entry_price:.2f} | Now ${self.Securities['MARA'].Price:.2f} | "
                     f"Stock: {cs:+.1f}% | LEAP: {cl:+.1f}%")
