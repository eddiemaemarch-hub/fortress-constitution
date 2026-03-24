# QuantConnect LEAN Algorithm
# MSTR Cycle-HIGH PUT LEAP Strategy v1.0
#
# THE MIRROR: Inverse of the Cycle-Low CALL strategy.
# Buys PUT LEAPs when MSTR is at euphoric cycle highs, profits from the crash.
#
# ENTRY: Price far above 200W SMA (>50% above) + signs of topping:
#   1. MSTR was >50% above 200W SMA (euphoric extension)
#   2. Price breaks back below a short-term EMA (momentum shift)
#   3. BTC showing weakness (below its own 200W MA or death cross forming)
#   4. StochRSI > 80 (overbought) OR rolling over from overbought
#   5. Premium contracting (mNAV premium falling from highs)
#   6. ATR elevated (volatility expanding = distribution phase)
#
# EXIT: Price drops to/near 200W SMA (cycle low = take profit on puts)
#   - Laddered profit taking as price drops
#   - Panic floor if price rips higher (puts lose value)
#   - Re-entry allowed after stop-out
#
# LEAP Multiplier: Conservative 7.5x (same as v2.5 calls)

from AlgorithmImports import *
import numpy as np
from datetime import timedelta


class MSTRCycleHighPut(QCAlgorithm):

    def Initialize(self):
        self.is_live_mode = self.LiveMode

        if not self.is_live_mode:
            self.SetStartDate(2016, 1, 1)
            self.SetEndDate(2026, 3, 14)
            self.SetCash(100000)

        # Trade Resolution
        if not hasattr(self, 'trade_resolution'):
            self.trade_resolution = "weekly"

        # Slippage & Commission
        self.Settings.FreePortfolioValuePercentage = 0.02
        if not self.is_live_mode:
            self.SetSecurityInitializer(lambda security: security.SetSlippageModel(
                ConstantSlippageModel(0.005)
            ))

        # Assets
        self.mstr = self.AddEquity("MSTR", Resolution.Daily)
        self.mstr.SetDataNormalizationMode(DataNormalizationMode.SplitAdjusted)
        self.btc_proxy = self.AddEquity("GBTC", Resolution.Daily)
        self.btc_proxy.SetDataNormalizationMode(DataNormalizationMode.SplitAdjusted)
        self.btc = self.AddCrypto("BTCUSD", Resolution.Daily, Market.Coinbase)

        # LEAP Multiplier (conservative staggered — same as v2.5 calls)
        self.leap_multiplier = 7.5

        # ── CYCLE HIGH ENTRY PARAMETERS ──
        self.extension_threshold = 0.50    # Price must be >50% above 200W SMA to be "euphoric"
        self.breakdown_ema = 21            # Short-term EMA for momentum breakdown
        self.stoch_rsi_overbought = 80     # StochRSI overbought threshold
        self.premium_peak_drop = 0.15      # Premium must drop >15% from its recent peak
        self.sma_weekly_period = 200       # 200-week SMA

        # ── EXIT PARAMETERS (PUT version) ──
        # For puts: profit when price DROPS, loss when price RISES
        self.initial_ceiling_pct = 1.35    # Stop loss: exit if price rises 35% above entry
        self.panic_ceiling_pct = 35.0      # Panic exit if PUT LEAP P&L drops below -35%
        self.target_drop_pct = 50.0        # Target: 50% drop from entry = huge put profit

        # ── Laddered Trailing Stop (PUT version — trails the LOW) ──
        # As price drops, we trail from the LOW water mark (best for puts)
        self.ladder_tiers = [
            (5000, 10.0),   # 50x+ PUT gain -> 10% trail from low
            (2000, 15.0),   # 20x+ -> 15% trail
            (1000, 20.0),   # 10x+ -> 20% trail
            (500,  25.0),   # 5x+  -> 25% trail
            (300,  30.0),   # 3x+  -> 30% trail
        ]

        # ── Profit Taking Tiers (PUT LEAP gains) ──
        self.profit_tiers = [
            (500,  0.25),   # PT1: 5x PUT gain -> sell 25%
            (1000, 0.25),   # PT2: 10x -> sell 25%
            (2000, 0.25),   # PT3: 20x -> sell 25%
            (5000, 0.25),   # PT4: 50x -> sell 25%
        ]

        # Risk
        self.risk_capital_pct = 0.25
        self.max_hold_bars = 567

        # BTC Holdings for mNAV
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

        # Weekly Rolling Windows
        self.weekly_closes = RollingWindow[float](350)
        self.weekly_opens = RollingWindow[float](350)
        self.weekly_highs = RollingWindow[float](350)
        self.weekly_lows = RollingWindow[float](350)
        self.btc_weekly_closes = RollingWindow[float](350)

        # Premium History
        self.premium_history = RollingWindow[float](30)

        # Indicators
        self.mstr_macd = self.MACD("MSTR", 12, 26, 9, MovingAverageType.Exponential, Resolution.Daily)
        self.mstr_ema_21 = self.EMA("MSTR", 21, Resolution.Daily)
        self.mstr_ema_50 = self.EMA("MSTR", 50, Resolution.Daily)
        self.mstr_rsi = self.RSI("MSTR", 14)
        self.rsi_window = RollingWindow[float](14)
        self.mstr_atr = self.ATR("MSTR", 14, MovingAverageType.Simple)
        self.atr_window = RollingWindow[float](30)
        self.price_highs_window = RollingWindow[float](30)

        # State: Cycle High Detection
        self.was_euphoric = False           # Was price >50% above 200W?
        self.euphoric_peak_premium = 0      # Peak premium during euphoric phase
        self.mstr_200w_sma = None
        self.already_entered_this_cycle = False

        # Position State (PUT — inverted)
        self.entry_price = 0
        self.position_lwm = 0               # Low water mark (for puts, lower = better)
        self.peak_put_gain_pct = 0
        self.current_trail_pct = 0
        self.pt_hits = [False] * len(self.profit_tiers)
        self.premium_lwm = 0
        self.bars_in_trade = 0

        # Scale-in
        self.first_entry_done = False
        self.second_entry_done = False

        # Tracking
        self.entry_dates = []
        self.exit_dates = []
        self.trade_log = []
        self.week_count = 0

        self._schedule_trade_evaluation()
        self.SetWarmUp(timedelta(days=60))

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

    def GetBTCHoldings(self, year):
        if year in self.btc_holdings_history:
            return self.btc_holdings_history[year]
        if year < 2016: return 0
        return self.btc_holdings_history.get(max(k for k in self.btc_holdings_history if k <= year), 738731)

    def GetDilutedShares(self, year):
        if year in self.diluted_shares_history:
            return self.diluted_shares_history[year]
        if year < 2016: return 10500000
        return self.diluted_shares_history.get(max(k for k in self.diluted_shares_history if k <= year), 374000000)

    def ComputeWeeklySMA(self, period):
        if self.weekly_closes.Count < period: return None
        return sum(self.weekly_closes[i] for i in range(period)) / period

    def ComputeBTCWeeklySMA(self, period):
        if self.btc_weekly_closes.Count < period: return None
        return sum(self.btc_weekly_closes[i] for i in range(period)) / period

    def ComputeStochRSI(self):
        if self.rsi_window.Count < 14: return 50
        rsi_values = [self.rsi_window[i] for i in range(self.rsi_window.Count)]
        rsi_min, rsi_max = min(rsi_values), max(rsi_values)
        if rsi_max == rsi_min: return 50
        return ((rsi_values[0] - rsi_min) / (rsi_max - rsi_min)) * 100

    def ComputeMSTRPremium(self, mstr_price, btc_price, year):
        holdings = self.GetBTCHoldings(year)
        shares = self.GetDilutedShares(year)
        if holdings == 0 or shares == 0 or btc_price <= 0: return 1.0
        nav_per_share = (btc_price * holdings) / shares
        if nav_per_share <= 0: return 999
        return mstr_price / nav_per_share

    def CheckMACDBearishDivergence(self):
        if not self.mstr_macd.IsReady: return False
        if self.price_highs_window.Count < 20: return False
        recent_high = max(self.price_highs_window[i] for i in range(5))
        older_high = max(self.price_highs_window[i] for i in range(10, min(20, self.price_highs_window.Count)))
        price_higher_high = recent_high > older_high
        macd_hist = self.mstr_macd.Current.Value - self.mstr_macd.Signal.Current.Value
        return price_higher_high and macd_hist < 0

    def OnData(self, data):
        if self.IsWarmingUp: return
        if not data.ContainsKey("MSTR") or not data["MSTR"]: return

        mstr_price = self.Securities["MSTR"].Price
        if mstr_price <= 0: return

        if self.mstr_rsi.IsReady:
            self.rsi_window.Add(self.mstr_rsi.Current.Value)
        self.price_highs_window.Add(mstr_price)
        if self.mstr_atr.IsReady:
            self.atr_window.Add(self.mstr_atr.Current.Value)

        # PUT position management (SHORT stock = simulated PUT)
        if self.Portfolio["MSTR"].Invested:
            self.bars_in_trade += 1
            self.ManagePositionDaily(mstr_price)

    def ManagePositionDaily(self, price):
        """Daily PUT position management. For puts: profit when price DROPS."""
        if self.entry_price <= 0: return

        # PUT P&L: inverse of stock — price dropping = profit
        stock_change = ((self.entry_price - price) / self.entry_price) * 100  # Positive when price drops
        put_leap_gain = stock_change * self.leap_multiplier

        # Update low water mark (lower price = better for puts)
        self.position_lwm = min(self.position_lwm, price) if self.position_lwm > 0 else price
        best_stock_drop = ((self.entry_price - self.position_lwm) / self.entry_price) * 100
        self.peak_put_gain_pct = max(self.peak_put_gain_pct, best_stock_drop * self.leap_multiplier)

        # ── Panic Ceiling: exit if price rises too much (puts losing) ──
        if stock_change < 0 and put_leap_gain <= -self.panic_ceiling_pct:
            self.Liquidate("MSTR")
            self.Log(f"PUT PANIC: {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f} | PUT LEAP: {put_leap_gain:.1f}%")
            self.RecordExit("PANIC_CEILING", price, stock_change, put_leap_gain)
            return

        # ── Initial Ceiling Stop (price rises 35% above entry = puts dead) ──
        ceiling_price = self.entry_price * self.initial_ceiling_pct
        if price > ceiling_price and put_leap_gain < 0:
            self.Liquidate("MSTR")
            self.Log(f"CEILING STOP: {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f} > ${ceiling_price:.2f}")
            self.RecordExit("CEILING_STOP", price, stock_change, put_leap_gain)
            return

        # ── Tiered Profit Taking (as price drops, bank put gains) ──
        for i, (threshold, sell_pct) in enumerate(self.profit_tiers):
            if put_leap_gain >= threshold and not self.pt_hits[i]:
                qty_to_cover = int(abs(self.Portfolio["MSTR"].Quantity) * sell_pct)
                if qty_to_cover > 0:
                    self.MarketOrder("MSTR", qty_to_cover)  # Buy to cover (reduce short)
                    self.pt_hits[i] = True
                    self.Log(f"PUT PT{i+1}: {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f} | PUT LEAP: +{put_leap_gain:.0f}%")

        # ── Laddered Trailing Stop (from low water mark) ──
        trail_pct = 0
        for threshold, trail in self.ladder_tiers:
            if self.peak_put_gain_pct >= threshold:
                trail_pct = trail
                break

        if trail_pct > 0:
            self.current_trail_pct = trail_pct
            # For puts: stop triggers when price bounces UP from low
            stop_level = self.position_lwm * (1 + trail_pct / 100)
            if price > stop_level:
                self.Liquidate("MSTR")
                self.Log(f"PUT TRAIL: {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f} | LWM: ${self.position_lwm:.2f}")
                self.RecordExit("PUT_TRAIL", price, stock_change, put_leap_gain)
                return

        # ── Max Hold ──
        if self.bars_in_trade >= self.max_hold_bars:
            self.Liquidate("MSTR")
            self.Log(f"MAX HOLD: {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f}")
            self.RecordExit("MAX_HOLD", price, stock_change, put_leap_gain)
            return

        # ── Price drops to/below 200W SMA = cycle low reached, take remaining profit ──
        if self.mstr_200w_sma and price < self.mstr_200w_sma and put_leap_gain > 0:
            self.Liquidate("MSTR")
            self.Log(f"200W TARGET: {self.Time.strftime('%Y-%m-%d')} @ ${price:.2f} < 200W ${self.mstr_200w_sma:.2f}")
            self.RecordExit("200W_TARGET", price, stock_change, put_leap_gain)
            return

    def OnWeeklyConsolidate(self):
        if self.IsWarmingUp: return
        mstr_price = self.Securities["MSTR"].Price
        btc_price = self.Securities["BTCUSD"].Price
        if mstr_price <= 0: return

        history = self.History(["MSTR"], 5, Resolution.Daily)
        if history.empty: return
        try:
            mstr_data = history.loc["MSTR"] if "MSTR" in history.index.get_level_values(0) else None
        except: return
        if mstr_data is None or len(mstr_data) == 0: return

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
                    self.btc_weekly_closes.Add(float(btc_history.loc["BTCUSD"].iloc[-1]["close"]))
            except: pass

        self.mstr_200w_sma = self.ComputeWeeklySMA(self.sma_weekly_period)

        # Track euphoric extension above 200W
        sma_200w = self.mstr_200w_sma
        if sma_200w and sma_200w > 0:
            extension = (week_close - sma_200w) / sma_200w
            if extension > self.extension_threshold:
                self.was_euphoric = True

            # Reset euphoric flag if price drops back near 200W
            if extension < 0.10:
                self.was_euphoric = False
                self.already_entered_this_cycle = False

        # Premium tracking
        year = self.Time.year
        prem = self.ComputeMSTRPremium(week_close, btc_price, year)
        self.premium_history.Add(prem)
        if self.was_euphoric:
            self.euphoric_peak_premium = max(self.euphoric_peak_premium, prem)

    def OnTradeBar(self):
        if self.IsWarmingUp: return
        mstr_price = self.Securities["MSTR"].Price
        btc_price = self.Securities["BTCUSD"].Price
        if mstr_price <= 0 or btc_price <= 0: return

        sma_200w = self.mstr_200w_sma
        if sma_200w is None or sma_200w <= 0: return

        year = self.Time.year
        current_premium = self.ComputeMSTRPremium(mstr_price, btc_price, year)
        btc_era = year >= 2020

        # ═══ CYCLE HIGH ENTRY CONDITIONS (all must be true) ═══

        # 1. Was euphoric (price was >50% above 200W SMA at some point)
        cond_was_euphoric = self.was_euphoric

        # 2. Momentum breakdown: price below EMA21 (short-term trend broken)
        cond_momentum_break = self.mstr_ema_21.IsReady and mstr_price < self.mstr_ema_21.Current.Value

        # 3. StochRSI rolling over from overbought (was >80, now declining)
        stoch_rsi = self.ComputeStochRSI()
        cond_stoch_rolling = stoch_rsi > 50  # Still elevated but rolling over
        # Alternative: check if it WAS overbought recently
        if self.rsi_window.Count >= 5:
            recent_rsis = [self.rsi_window[i] for i in range(min(5, self.rsi_window.Count))]
            was_overbought = max(recent_rsis) > 65
            cond_stoch_rolling = was_overbought and stoch_rsi < self.stoch_rsi_overbought

        # 4. Premium contracting from peak
        cond_premium_contracting = False
        if self.euphoric_peak_premium > 0 and current_premium < self.euphoric_peak_premium:
            prem_drop = (self.euphoric_peak_premium - current_premium) / self.euphoric_peak_premium
            cond_premium_contracting = prem_drop > self.premium_peak_drop

        # 5. MACD bearish divergence (nice to have, not required)
        cond_macd_bearish = self.CheckMACDBearishDivergence()

        # 6. ATR elevated (volatility expanding = distribution)
        cond_atr_elevated = True
        if self.atr_window.Count >= 20:
            current_atr = self.atr_window[0]
            atr_avg_20 = sum(self.atr_window[i] for i in range(20)) / 20
            cond_atr_elevated = current_atr > 1.0 * atr_avg_20  # Above average volatility

        # 7. BTC weakness
        btc_200w = self.ComputeBTCWeeklySMA(200)
        cond_btc_weak = btc_200w is not None and btc_price < btc_200w * 1.3  # BTC not far above 200W

        # 8. Cycle lock
        cond_cycle_ok = not self.already_entered_this_cycle

        # ═══ FULL PUT ENTRY CONFLUENCE ═══
        # Core: must have been euphoric + momentum breaking + premium contracting
        # At least 2 of: StochRSI rolling, MACD bearish, ATR elevated
        core_ok = cond_was_euphoric and cond_momentum_break and cond_premium_contracting
        secondary_score = sum([cond_stoch_rolling, cond_macd_bearish, cond_atr_elevated])
        secondary_ok = secondary_score >= 2

        all_filters = core_ok and secondary_ok and cond_cycle_ok and btc_era

        # Log when conditions are close
        if cond_was_euphoric and not self.Portfolio["MSTR"].Invested and btc_era:
            self.Log(f"PUT CHECK {self.Time.strftime('%Y-%m-%d')}: "
                     f"Euph={'Y' if cond_was_euphoric else 'N'} "
                     f"MomBrk={'Y' if cond_momentum_break else 'N'} "
                     f"PremDrop={'Y' if cond_premium_contracting else 'N'} "
                     f"StochRoll={'Y' if cond_stoch_rolling else 'N'} "
                     f"MACDdiv={'Y' if cond_macd_bearish else 'N'} "
                     f"ATRelev={'Y' if cond_atr_elevated else 'N'} "
                     f"BTCwk={'Y' if cond_btc_weak else 'N'} "
                     f"ALL={'Y' if all_filters else 'N'}")

        # ═══ ENTRY: SHORT MSTR (simulates buying PUT LEAPs) ═══
        if all_filters and not self.Portfolio["MSTR"].Invested and not self.first_entry_done:
            risk_capital = self.Portfolio.TotalPortfolioValue * self.risk_capital_pct
            deploy = risk_capital * 0.50
            qty = int(deploy / mstr_price)
            if qty > 0:
                self.MarketOrder("MSTR", -qty)  # SHORT = simulated PUT
                self.entry_price = mstr_price
                self.position_lwm = mstr_price
                self.peak_put_gain_pct = 0
                self.current_trail_pct = 0
                self.pt_hits = [False] * len(self.profit_tiers)
                self.bars_in_trade = 0
                self.first_entry_done = True
                self.second_entry_done = False

                self.Log(f"PUT ENTRY 1/2: {self.Time.strftime('%Y-%m-%d')} @ ${mstr_price:.2f} | "
                         f"200W=${sma_200w:.2f} | Ext={((mstr_price-sma_200w)/sma_200w*100):.0f}% | "
                         f"Prem={current_premium:.2f}x | Qty={qty}")
                self.entry_dates.append(self.Time)

        elif all_filters and self.first_entry_done and not self.second_entry_done and self.Portfolio["MSTR"].Invested:
            risk_capital = self.Portfolio.TotalPortfolioValue * self.risk_capital_pct
            deploy = risk_capital * 0.50
            qty = int(deploy / mstr_price)
            if qty > 0:
                self.MarketOrder("MSTR", -qty)  # Add to short
                self.entry_price = abs(self.Portfolio["MSTR"].AveragePrice)
                self.second_entry_done = True
                self.already_entered_this_cycle = True
                self.Log(f"PUT ENTRY 2/2: {self.Time.strftime('%Y-%m-%d')} @ ${mstr_price:.2f}")

        # ═══ WEEKLY EXIT CHECKS ═══
        if self.Portfolio["MSTR"].Invested and self.entry_price > 0:
            stock_change = ((self.entry_price - mstr_price) / self.entry_price) * 100
            put_leap_gain = stock_change * self.leap_multiplier

            # BTC reclaims 200W strongly = bear thesis broken
            if btc_200w is not None and btc_price > btc_200w * 1.2 and put_leap_gain < 0:
                self.Liquidate("MSTR")
                self.Log(f"BTC BULL EXIT: {self.Time.strftime('%Y-%m-%d')} | BTC reclaimed 200W")
                self.RecordExit("BTC_BULL", mstr_price, stock_change, put_leap_gain)
                return

            # Price back above EMA50 while losing = thesis broken
            if self.mstr_ema_50.IsReady and mstr_price > self.mstr_ema_50.Current.Value and put_leap_gain < 0:
                self.Liquidate("MSTR")
                self.Log(f"EMA50 BULL EXIT: {self.Time.strftime('%Y-%m-%d')} @ ${mstr_price:.2f}")
                self.RecordExit("EMA50_BULL", mstr_price, stock_change, put_leap_gain)
                return

    def RecordExit(self, reason, price, stock_change, put_gain):
        self.exit_dates.append(self.Time)
        self.trade_log.append({
            "entry_date": self.entry_dates[-1] if self.entry_dates else None,
            "exit_date": self.Time,
            "entry_price": self.entry_price,
            "exit_price": price,
            "stock_change_pct": stock_change,
            "put_leap_gain_pct": put_gain,
            "reason": reason,
        })
        self.entry_price = 0
        self.position_lwm = 0
        self.peak_put_gain_pct = 0
        self.current_trail_pct = 0
        self.premium_lwm = 0
        self.bars_in_trade = 0
        self.first_entry_done = False
        self.second_entry_done = False
        self.euphoric_peak_premium = 0
        self.already_entered_this_cycle = False  # Allow re-entry

    def OnEndOfAlgorithm(self):
        res_name = self.trade_resolution.capitalize()
        self.Log("=" * 60)
        self.Log(f"MSTR CYCLE-HIGH PUT v1.0 ({res_name})")
        self.Log("=" * 60)
        self.Log(f"Cycle high PUT LEAP | Mult {self.leap_multiplier}x")
        self.Log(f"Weeks collected: {self.week_count}")
        self.Log(f"Total Trades: {len(self.trade_log)}")
        self.Log(f"Final Value: ${self.Portfolio.TotalPortfolioValue:,.2f}")
        self.Log(f"Return: {((self.Portfolio.TotalPortfolioValue / 100000) - 1) * 100:.1f}%")

        if self.trade_log:
            gains = [t["put_leap_gain_pct"] for t in self.trade_log]
            winners = [g for g in gains if g > 0]
            losers = [g for g in gains if g <= 0]
            wr = len(winners)/len(gains)*100 if gains else 0
            self.Log(f"Win Rate: {len(winners)}/{len(gains)} ({wr:.0f}%)")
            if winners: self.Log(f"Avg Win (PUT LEAP): +{np.mean(winners):.1f}%")
            if losers: self.Log(f"Avg Loss (PUT LEAP): {np.mean(losers):.1f}%")

        for i, t in enumerate(self.trade_log):
            self.Log(f"Trade {i+1}: {t['entry_date'].strftime('%Y-%m-%d')} -> {t['exit_date'].strftime('%Y-%m-%d')} | "
                     f"${t['entry_price']:.2f} -> ${t['exit_price']:.2f} | "
                     f"Stock: {t['stock_change_pct']:+.1f}% | PUT LEAP: {t['put_leap_gain_pct']:+.1f}% | {t['reason']}")
