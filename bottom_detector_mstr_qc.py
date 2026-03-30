#!/usr/bin/env python3
"""
bottom_detector_mstr_qc.py
QuantConnect LEAN algorithm — MSTR bottom detection research tool.

NOT a trading strategy. Purpose: identify when MSTR is approaching
a cycle bottom to inform v2.8+ entry timing.

5-signal scoring system (0-5 score, higher = more bottom evidence):
  1. BTC proximity to 200W SMA (within 25% = cycle floor zone)
  2. MSTR weekly RSI < 30 (oversold)
  3. Selling volume exhaustion (volume declining on consecutive down weeks)
  4. Rate-of-change deceleration (selling momentum slowing)
  5. Extended consecutive down weeks (capitulation count >= 6)

Score >= 3 = Bottom Zone Alert
Score >= 4 = High Conviction Bottom Signal
Score  = 5 = Maximum Conviction (all signals firing)

Pass to terminal: python run_qc_bottom_detector.py
"""

from AlgorithmImports import *
import numpy as np


class MSTRBottomDetector(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2020, 1, 1)
        self.SetEndDate(2026, 3, 30)
        self.SetCash(100000)

        # Securities — weekly resolution
        self.mstr = self.AddEquity("MSTR", Resolution.Daily).Symbol
        self.btc  = self.AddCrypto("BTCUSD", Resolution.Daily, Market.Coinbase).Symbol

        # Consolidate to weekly bars
        self.mstr_weekly = RollingWindow[TradeBar](52)
        self.btc_weekly  = RollingWindow[TradeBar](210)  # 200W SMA needs 200 bars

        self.ConsolidateWeekly("MSTR",  self.OnMSTRWeekly)
        self.ConsolidateWeekly("BTCUSD", self.OnBTCWeekly)

        # Indicators on weekly bars
        self.rsi        = RelativeStrengthIndex(14)
        self.roc_4      = RateOfChange(4)    # 4-week rate of change
        self.roc_8      = RateOfChange(8)    # 8-week rate of change
        self.sma_200w   = SimpleMovingAverage(200)

        # State tracking
        self.consecutive_down  = 0
        self.prev_volume       = None
        self.volume_declining  = 0    # consecutive weeks of declining volume on down bars
        self.signals_history   = []
        self.bottom_alerts     = []

        # Scheduled weekly report
        self.Schedule.On(
            self.DateRules.WeekEnd("MSTR"),
            self.TimeRules.BeforeMarketClose("MSTR", 5),
            self.WeeklyEval
        )

        self.Debug("MSTR Bottom Detector initialized — research mode only")

    def ConsolidateWeekly(self, symbol, handler):
        self.Consolidate(symbol, Resolution.Daily, CalendarType.Weekly, handler)

    def OnMSTRWeekly(self, bar: TradeBar):
        self.mstr_weekly.Add(bar)
        self.rsi.Update(bar.EndTime, bar.Close)
        self.roc_4.Update(bar.EndTime, bar.Close)
        self.roc_8.Update(bar.EndTime, bar.Close)

        # Consecutive down weeks
        if self.mstr_weekly.Count >= 2:
            prev = self.mstr_weekly[1].Close
            if bar.Close < prev:
                self.consecutive_down += 1
                # Volume exhaustion: volume declining on a down bar
                if self.prev_volume and bar.Volume < self.prev_volume:
                    self.volume_declining += 1
                else:
                    self.volume_declining = 0
            else:
                self.consecutive_down = 0
                self.volume_declining = 0

        self.prev_volume = bar.Volume

    def OnBTCWeekly(self, bar: TradeBar):
        self.btc_weekly.Add(bar)
        self.sma_200w.Update(bar.EndTime, bar.Close)

    def WeeklyEval(self):
        if not self.rsi.IsReady or not self.sma_200w.IsReady:
            return
        if self.mstr_weekly.Count < 2:
            return

        mstr_price = self.mstr_weekly[0].Close
        btc_price  = self.btc_weekly[0].Close if self.btc_weekly.Count > 0 else 0
        ma_200w    = self.sma_200w.Current.Value
        rsi_val    = self.rsi.Current.Value
        roc4       = self.roc_4.Current.Value * 100 if self.roc_4.IsReady else 0
        roc8       = self.roc_8.Current.Value * 100 if self.roc_8.IsReady else 0

        # ── Signal 1: BTC near 200W SMA (within 25%) ──────────────────────────
        btc_dist = abs(btc_price - ma_200w) / ma_200w if ma_200w > 0 else 1
        sig1 = 1 if btc_dist <= 0.25 else 0

        # ── Signal 2: MSTR weekly RSI < 30 (oversold) ─────────────────────────
        sig2 = 1 if rsi_val < 30 else 0

        # ── Signal 3: Volume exhaustion (3+ weeks declining vol on down bars) ──
        sig3 = 1 if self.volume_declining >= 3 else 0

        # ── Signal 4: ROC deceleration (selling momentum slowing) ─────────────
        # ROC4 less negative than ROC8 = pace of decline slowing
        sig4 = 1 if (roc4 > roc8 and roc4 < 0 and roc8 < 0) else 0

        # ── Signal 5: Extended capitulation (6+ consecutive down weeks) ────────
        sig5 = 1 if self.consecutive_down >= 6 else 0

        score = sig1 + sig2 + sig3 + sig4 + sig5

        # Conviction label
        if score == 5:
            label = "MAXIMUM CONVICTION"
        elif score >= 4:
            label = "HIGH CONVICTION"
        elif score >= 3:
            label = "BOTTOM ZONE"
        elif score >= 2:
            label = "WATCH"
        else:
            label = "no signal"

        # Log all weeks for analysis
        entry = {
            "date":        self.Time.strftime("%Y-%m-%d"),
            "mstr":        round(mstr_price, 2),
            "btc":         round(btc_price, 2),
            "btc_200w":    round(ma_200w, 2),
            "btc_dist_pct":round(btc_dist * 100, 1),
            "rsi":         round(rsi_val, 1),
            "roc4":        round(roc4, 1),
            "roc8":        round(roc8, 1),
            "consec_down": self.consecutive_down,
            "vol_decline": self.volume_declining,
            "sig1_btc_200w": sig1,
            "sig2_rsi_os":   sig2,
            "sig3_vol_exh":  sig3,
            "sig4_roc_dec":  sig4,
            "sig5_cap_count":sig5,
            "score":   score,
            "label":   label,
        }
        self.signals_history.append(entry)

        # Alert on meaningful signals
        if score >= 3:
            self.bottom_alerts.append(entry)
            self.Debug(
                f"[{label}] {self.Time.strftime('%Y-%m-%d')} | "
                f"Score {score}/5 | MSTR ${mstr_price:.0f} | "
                f"RSI {rsi_val:.0f} | BTC {btc_dist*100:.0f}% from 200W | "
                f"Down {self.consecutive_down}wks"
            )

    def OnEndOfAlgorithm(self):
        self.Debug("\n" + "═"*60)
        self.Debug("  MSTR BOTTOM DETECTION — FULL RESULTS")
        self.Debug("═"*60)
        self.Debug(f"  Total weeks analyzed: {len(self.signals_history)}")
        self.Debug(f"  Bottom alerts fired:  {len(self.bottom_alerts)}")
        self.Debug("")
        self.Debug("  BOTTOM ZONE ALERTS (Score >= 3):")
        self.Debug(f"  {'Date':<12} {'MSTR':>7} {'BTC':>8} {'RSI':>5} "
                   f"{'Score':>6} {'Label':<20}")
        self.Debug(f"  {'─'*12} {'─'*7} {'─'*8} {'─'*5} {'─'*6} {'─'*20}")

        for a in self.bottom_alerts:
            self.Debug(
                f"  {a['date']:<12} ${a['mstr']:>6.0f} ${a['btc']:>7.0f} "
                f"{a['rsi']:>5.0f} {a['score']:>5}/5  {a['label']}"
            )

        self.Debug("")
        self.Debug("  SIGNAL BREAKDOWN (all bottom alerts):")
        for a in self.bottom_alerts:
            self.Debug(
                f"  {a['date']} | "
                f"BTC-200W:{a['sig1_btc_200w']} "
                f"RSI-OS:{a['sig2_rsi_os']} "
                f"Vol-Exh:{a['sig3_vol_exh']} "
                f"ROC-Dec:{a['sig4_roc_dec']} "
                f"Cap:{a['sig5_cap_count']} | "
                f"Down {a['consec_down']}wks"
            )

        self.Debug("═"*60)
        self.Debug("  Research only — NOT a trading strategy.")
        self.Debug("  Use signals as bottom zone awareness for v2.8+ timing.")
        self.Debug("═"*60)
