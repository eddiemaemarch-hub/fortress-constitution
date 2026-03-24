#!/usr/bin/env python3
"""Trader3 — SPY $430 Put (Jan 2027) — Laddered Trailing Stop + Take Profit

Monitors the existing SPY $430 Put position.
Activates laddered exit strategy once position is up +100%.
On close, proceeds stay in IBKR for v2.8+ MSTR LEAP deployment.

PRICE SOURCE: ALL prices from IBKR TWS (port 7496). No external APIs.

Position Details:
    Symbol: SPY
    Right: PUT
    Strike: $430
    Expiry: 2027-01-15
    Avg Cost: $4.95/share ($494.99 total)
    Qty: 1 contract (100 shares)

Ladder Strategy (activates at +100% gain):
    Tier 1: At +100% gain → Trail stop at 20% from peak
    Tier 2: At +300% gain → Tighten trail to 18%
    Tier 3: At +500% gain → Tighten trail to 15%
    Tier 4: At +800% gain → Tighten trail to 12%

    Note: Single contract — cannot split. Trail tightens at each tier.
    Full exit via trail stop with HITL approval.

Capital Deployment: Proceeds → v2.8+ MSTR LEAP (Phase 2 of capital plan).
HITL: All sell orders require Telegram approval before execution.

Usage:
    python3 trader3_spy_put.py              # Run as daemon
    python3 trader3_spy_put.py --test       # Check position, no trades
    python3 trader3_spy_put.py --status     # Show current state
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime

import schedule
from ib_insync import IB, Option, util

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Config ──
PORT = 7496
CLIENT_ID = 13  # Unique client ID (trader_v28=10, trader2=12)
STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "trader3_state.json")
LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "logs", "trader3.log")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
REGIME_STATE_FILE = os.path.join(DATA_DIR, "regime_state.json")

# ── System 13 Regime-Adaptive Trail Adjustments ──
# Puts BENEFIT from market drops. Regime awareness adjusts trail width.
REGIME_TRAIL_ADJUST = {
    "MARKDOWN": +5,      # Widen trail 5% — market falling = puts printing
    "DISTRIBUTION": +2,  # Slightly wider — late bull, puts have tailwind
    "ACCUMULATION": 0,   # Neutral
    "MARKUP": -3,         # Tighten trail 3% — market rising = puts losing
}

# Position details
SYMBOL = "SPY"
STRIKE = 430.0
RIGHT = "P"
EXPIRY = "20270115"
AVG_COST = 494.99  # Total cost basis
QTY = 1  # Contracts

# Activation threshold
ACTIVATION_PCT = 100  # Strategy activates at 100% gain (SPY puts spike & reverse fast, protect early)

# Ladder tiers
LADDER = [
    {"name": "Tier 1", "trigger_pct": 100,  "sell_frac": 0.0,  "trail_pct": 20},
    {"name": "Tier 2", "trigger_pct": 200,  "sell_frac": 0.0,  "trail_pct": 18},
    {"name": "Tier 3", "trigger_pct": 400,  "sell_frac": 0.0,  "trail_pct": 15},
    {"name": "Tier 4", "trigger_pct": 700,  "sell_frac": 0.0,  "trail_pct": 12},
]
# Note: sell_frac is 0 for all tiers because we have a single contract.
# The only sell is when the trail stop is hit → sell the entire contract.

RUNNER_TRAIL_PCT = 15

# ── LEAP Expiry Extension Protocol ──
EXPIRY_ROLL_WARNING_DAYS = 180   # 6 months out — early warning
EXPIRY_ROLL_URGENT_DAYS  = 90    # 3 months out — urgent
NEXT_EXPIRY = "20290119"         # SPY $430P Jan 2029 (2-yr forward roll)

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except:
        pass


def send_telegram(msg):
    try:
        sys.path.insert(0, os.path.expanduser("~/rudy/scripts"))
        import telegram as tg
        tg.send(msg)
    except Exception as e:
        log(f"Telegram error: {e}", "ERROR")


def get_regime():
    """Read System 13 regime from regime_state.json."""
    try:
        if os.path.exists(REGIME_STATE_FILE):
            with open(REGIME_STATE_FILE) as f:
                data = json.load(f)
            last_updated = data.get("last_updated", "")
            if last_updated:
                from datetime import timedelta
                updated_dt = datetime.fromisoformat(last_updated)
                if (datetime.now() - updated_dt).days > 7:
                    return {"regime": "UNKNOWN", "confidence": 0, "trail_adjust": 0, "phase": "unknown", "stale": True}
            regime = data.get("current_regime", "UNKNOWN")
            confidence = data.get("confidence", 0)
            trail_adjust = REGIME_TRAIL_ADJUST.get(regime, 0)
            phase = "bear" if regime in ("DISTRIBUTION", "MARKDOWN") else "bull"
            return {
                "regime": regime,
                "confidence": confidence,
                "trail_adjust": trail_adjust,
                "phase": phase,
                "rl_accuracy": data.get("rl_rolling_accuracy", 1.0),
                "stale": False,
            }
    except Exception:
        pass
    return {"regime": "UNKNOWN", "confidence": 0, "trail_adjust": 0, "phase": "unknown", "stale": True}


def build_stealth_order(ib, action, qty, contract):
    """Build limit order with anti-hunt offset. No round numbers, no predictable fills.
    Institutional Execution Intelligence (v50.0) — prevents front-running."""
    import random
    from ib_insync import LimitOrder, MarketOrder

    try:
        ib.reqMktData(contract, '', False, False)
        ib.sleep(2)
        ticker = ib.ticker(contract)

        bid = ticker.bid if ticker.bid and ticker.bid > 0 else 0
        ask = ticker.ask if ticker.ask and ticker.ask > 0 else 0

        if bid > 0 and ask > 0:
            mid = (bid + ask) / 2
            spread = ask - bid
            offset = round(random.uniform(0.05, 0.15), 2)  # options
            penny_jitter = round(random.uniform(0.01, 0.04), 2)

            if action == "BUY":
                price = round(mid + spread * 0.3 + penny_jitter, 2)
                price = min(price, round(ask + offset, 2))
            else:
                price = round(mid - spread * 0.3 - penny_jitter, 2)
                price = max(price, round(bid - offset, 2))

            cents = int(round(price * 100)) % 100
            if cents == 0 or cents == 50:
                price += 0.03

            order = LimitOrder(action, qty, price)
            order.tif = "GTC"
            log(f"🥷 Stealth: {action} {qty} @ ${price:.2f} (bid=${bid:.2f} ask=${ask:.2f})")
            ib.cancelMktData(contract)
            return order
        else:
            log("⚠️ No bid/ask — falling back to MarketOrder", "WARN")
            ib.cancelMktData(contract)
            return MarketOrder(action, qty)
    except Exception as e:
        log(f"⚠️ Stealth build failed ({e}) — MarketOrder fallback", "WARN")
        return MarketOrder(action, qty)


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {
            "activated": False,
            "current_tier": 0,
            "peak_value": 0,
            "peak_gain_pct": 0,
            "trail_stop_value": 0,
            "trail_stop_pct": 0,
            "contracts_remaining": QTY,
            "total_realized": 0,
            "tiers_hit": [],
            "pending_sell": None,
            "last_check": None,
            "history": []
        }


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


class Trader3:
    def __init__(self, test_mode=False):
        self.ib = IB()
        self.test_mode = test_mode
        self.state = load_state()

    def connect(self):
        try:
            self.ib.connect("127.0.0.1", PORT, clientId=CLIENT_ID, timeout=15)
            log(f"Connected to TWS on port {PORT}")
            return True
        except Exception as e:
            log(f"Connection failed: {e}", "ERROR")
            return False

    def disconnect(self):
        if self.ib.isConnected():
            self.ib.disconnect()

    def get_position_value(self):
        """Get current market value of the SPY put position from IBKR portfolio."""
        # Primary: use IBKR portfolio valuation (most accurate, matches account page)
        try:
            portfolio = self.ib.portfolio()
            for p in portfolio:
                c = p.contract
                if (c.symbol == SYMBOL and getattr(c, "strike", 0) == STRIKE
                        and getattr(c, "right", "") == RIGHT):
                    market_value = float(p.marketValue)
                    mid = market_value / (100 * self.state["contracts_remaining"])
                    log(f"Using IBKR portfolio value: ${market_value:.2f} (mid ${mid:.2f})")
                    return market_value, mid
        except Exception as e:
            log(f"Portfolio fetch failed: {e}, falling back to market data", "WARN")

        # Fallback: use market data mid price
        contract = Option(SYMBOL, EXPIRY, STRIKE, RIGHT, "SMART")
        self.ib.qualifyContracts(contract)
        ticker = self.ib.reqMktData(contract, "", False, False)
        self.ib.sleep(3)

        mid = None
        if ticker.bid and ticker.ask and ticker.bid > 0 and ticker.ask > 0:
            mid = (ticker.bid + ticker.ask) / 2
        elif ticker.last and ticker.last > 0:
            mid = ticker.last
        elif ticker.close and ticker.close > 0:
            mid = ticker.close

        self.ib.cancelMktData(contract)

        if mid is None:
            log("Could not get market data for SPY put", "ERROR")
            return None

        market_value = mid * 100 * self.state["contracts_remaining"]
        return market_value, mid

    def calculate_gain(self, market_value):
        cost_basis = AVG_COST * (self.state["contracts_remaining"] / QTY)
        if cost_basis <= 0:
            return 0
        return ((market_value - cost_basis) / cost_basis) * 100

    def check_position(self):
        """Main evaluation — check position and apply ladder logic."""
        if not self.ib.isConnected():
            if not self.connect():
                return

        result = self.get_position_value()
        if result is None:
            return

        market_value, mid_price = result
        gain_pct = self.calculate_gain(market_value)
        cost_basis = AVG_COST * (self.state["contracts_remaining"] / QTY)

        # ── System 13 Regime Awareness ──
        regime_info = get_regime()
        regime_tag = f"Regime={regime_info['regime']}({regime_info['confidence']:.0%})" if not regime_info['stale'] else "Regime=STALE"
        trail_adj = regime_info['trail_adjust']

        log(f"SPY $430P Jan27 | Mid: ${mid_price:.2f} | Value: ${market_value:.2f} | "
            f"Cost: ${cost_basis:.2f} | Gain: {gain_pct:+.1f}% | "
            f"Contracts: {self.state['contracts_remaining']} | {regime_tag} | TrailAdj: {trail_adj:+d}%")

        self.state["last_check"] = datetime.now().isoformat()
        self.state["last_value"] = market_value
        self.state["last_gain_pct"] = gain_pct
        self.state["last_mid"] = mid_price
        self.state["last_regime"] = regime_info["regime"]
        self.state["last_regime_confidence"] = regime_info["confidence"]

        # ── EXPIRY ROLL COMMANDER RESPONSE ──
        # MCP approve_expiry_roll tool writes these flags; daemon picks them up here.
        if self.state.get("expiry_roll_commander_approved"):
            self.state["expiry_roll_commander_approved"] = False
            save_state(self.state)
            log("Commander approved expiry roll — executing...")
            self.approve_expiry_roll()
            return
        if self.state.get("expiry_roll_commander_rejected"):
            self.state["expiry_roll_commander_rejected"] = False
            save_state(self.state)
            log("Commander rejected expiry roll — clearing pending state.")
            self.reject_expiry_roll()

        # ── LEAP EXPIRY EXTENSION CHECK ──
        self._check_expiry_extension(gain_pct, market_value, mid_price)

        # ── NOT YET ACTIVATED ──
        if not self.state["activated"]:
            if gain_pct >= ACTIVATION_PCT:
                self.state["activated"] = True
                self.state["peak_value"] = market_value
                self.state["peak_gain_pct"] = gain_pct
                tier = LADDER[0]
                effective_trail = max(5, tier["trail_pct"] + trail_adj)  # Floor at 5%
                trail_value = market_value * (1 - effective_trail / 100)
                self.state["trail_stop_value"] = trail_value
                self.state["trail_stop_pct"] = tier["trail_pct"]
                self.state["current_tier"] = 1
                self.state["tiers_hit"].append(tier["name"])

                send_telegram(
                    f"🎯 *TRADER3: LADDER ACTIVATED*\n"
                    f"SPY $430 Put Jan 2027\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"Gain: *+{gain_pct:.1f}%*\n"
                    f"Value: ${market_value:.2f}\n"
                    f"Cost: ${cost_basis:.2f}\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"Trail Stop: ${trail_value:.2f} ({tier['trail_pct']}% from peak)\n"
                    f"Next tier: +{LADDER[1]['trigger_pct']}% → tighten trail"
                )
                log(f"LADDER ACTIVATED at +{gain_pct:.1f}%")
            else:
                pct_to_activation = ACTIVATION_PCT - gain_pct
                log(f"Not activated yet. Need +{pct_to_activation:.1f}% more to reach +{ACTIVATION_PCT}%")
                save_state(self.state)
                return

        # ── ACTIVATED — Check ladder tiers ──
        if self.state["activated"]:
            # Update peak
            if market_value > self.state["peak_value"]:
                self.state["peak_value"] = market_value
                self.state["peak_gain_pct"] = gain_pct
                trail_pct = self.state["trail_stop_pct"]
                effective_trail = max(5, trail_pct + trail_adj)
                self.state["trail_stop_value"] = market_value * (1 - effective_trail / 100)
                log(f"New peak: ${market_value:.2f} (+{gain_pct:.1f}%) | "
                    f"Trail stop raised to ${self.state['trail_stop_value']:.2f} "
                    f"(base {trail_pct}% {trail_adj:+d}% regime = {effective_trail}%)")

            # Check new tiers
            current_tier_idx = self.state["current_tier"]
            if current_tier_idx < len(LADDER):
                next_tier = LADDER[current_tier_idx]
                if gain_pct >= next_tier["trigger_pct"]:
                    self._trigger_tier(next_tier, market_value, gain_pct, mid_price)

            # Check trail stop
            if market_value <= self.state["trail_stop_value"]:
                self._trigger_trail_stop(market_value, gain_pct, mid_price)

        save_state(self.state)

    def _trigger_tier(self, tier, market_value, gain_pct, mid_price):
        """Handle hitting a new ladder tier — tighten trail (single contract, no splits)."""
        regime_info = get_regime()
        adj = regime_info["trail_adjust"]
        effective_trail = max(5, tier["trail_pct"] + adj)
        self.state["trail_stop_pct"] = tier["trail_pct"]  # Store base trail
        self.state["trail_stop_value"] = self.state["peak_value"] * (1 - effective_trail / 100)
        log(f"Trail set: base {tier['trail_pct']}% {adj:+d}% regime = {effective_trail}% effective")
        self.state["current_tier"] = self.state["current_tier"] + 1
        self.state["tiers_hit"].append(tier["name"])

        send_telegram(
            f"📊 *TRADER3: {tier['name'].upper()} HIT*\n"
            f"SPY $430 Put Jan 2027\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Gain: *+{gain_pct:.1f}%*\n"
            f"Value: ${market_value:.2f}\n"
            f"Mid: ${mid_price:.2f}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Trail tightened: {tier['trail_pct']}% from peak\n"
            f"Trail Stop: ${self.state['trail_stop_value']:.2f}\n"
            f"Peak: ${self.state['peak_value']:.2f}"
        )
        log(f"{tier['name']} triggered at +{gain_pct:.1f}% | Trail: {tier['trail_pct']}%")

    def _trigger_trail_stop(self, market_value, gain_pct, mid_price):
        """Trail stop hit — HITL approval to sell."""
        remaining = self.state["contracts_remaining"]
        cost_basis = AVG_COST * (remaining / QTY)
        profit = market_value - cost_basis + self.state["total_realized"]

        self.state["pending_sell"] = {
            "qty": remaining,
            "tier": "TRAIL_STOP",
            "trigger_gain": gain_pct,
            "mid_at_trigger": mid_price,
            "timestamp": datetime.now().isoformat()
        }

        send_telegram(
            f"🔴 *TRADER3: TRAIL STOP HIT*\n"
            f"SPY $430 Put Jan 2027\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Value dropped to: ${market_value:.2f}\n"
            f"Trail Stop was: ${self.state['trail_stop_value']:.2f}\n"
            f"Peak was: ${self.state['peak_value']:.2f} (+{self.state['peak_gain_pct']:.1f}%)\n"
            f"Current Gain: *+{gain_pct:.1f}%*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🔔 *SELL ALL {remaining} contract(s)?*\n"
            f"Total P&L (incl. realized): ${profit:.2f}\n"
            f"Awaiting your approval..."
        )
        log(f"TRAIL STOP HIT at +{gain_pct:.1f}% | Peak was +{self.state['peak_gain_pct']:.1f}%")

    def execute_sell(self, qty):
        if self.test_mode:
            log(f"TEST MODE — would sell {qty} SPY $430P Jan27")
            return True

        contract = Option(SYMBOL, EXPIRY, STRIKE, RIGHT, "SMART")
        self.ib.qualifyContracts(contract)

        order = build_stealth_order(self.ib, "SELL", qty, contract)
        trade = self.ib.placeOrder(contract, order)
        self.ib.sleep(10)

        if trade.orderStatus.status == "Filled":
            fill_price = trade.orderStatus.avgFillPrice
            realized = fill_price * 100 * qty
            self.state["contracts_remaining"] -= qty
            self.state["total_realized"] += realized
            self.state["pending_sell"] = None

            send_telegram(
                f"✅ *TRADER3: SOLD {qty} contract(s)*\n"
                f"SPY $430 Put Jan 2027\n"
                f"Fill: ${fill_price:.2f}\n"
                f"Realized: ${realized:.2f}\n"
                f"Contracts remaining: {self.state['contracts_remaining']}\n"
                f"Total realized: ${self.state['total_realized']:.2f}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"💰 Proceeds stay in account for v2.8+ MSTR LEAP deployment"
            )
            log(f"SOLD {qty} @ ${fill_price:.2f} | Realized: ${realized:.2f}")
            save_state(self.state)
            return True
        else:
            log(f"Sell order not filled: {trade.orderStatus.status}", "ERROR")
            send_telegram(f"🔴 *TRADER3: SELL FAILED*\nStatus: {trade.orderStatus.status}")
            return False

    def approve_pending_sell(self):
        if not self.state.get("pending_sell"):
            return {"status": "error", "message": "No pending sell"}
        qty = self.state["pending_sell"]["qty"]
        return self.execute_sell(qty)

    def reject_pending_sell(self):
        tier = self.state.get("pending_sell", {}).get("tier", "unknown")
        self.state["pending_sell"] = None
        save_state(self.state)
        send_telegram(f"❌ *TRADER3: Sell rejected* ({tier})\nPosition held. Trail stop still active.")
        return {"status": "rejected", "tier": tier}

    # ══════════════════════════════════════════════════════════════
    #  LEAP EXPIRY EXTENSION — Roll same strike forward in flat market
    # ══════════════════════════════════════════════════════════════

    def _check_expiry_extension(self, gain_pct, market_value, mid_price):
        """LEAP Expiry Extension Protocol.

        Fires when approaching expiry and the market is flat (puts not activated).
        Proposes rolling to NEXT_EXPIRY (same strike) to preserve the thesis.
        HITL approval required before execution.
        """
        expiry_date = datetime.strptime(EXPIRY, "%Y%m%d")
        days_left = (expiry_date - datetime.now()).days

        is_flat = (not self.state.get("activated", False)
                   and gain_pct < (ACTIVATION_PCT * 0.5))
        if not is_flat:
            return

        if self.state.get("pending_expiry_roll"):
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
            return

        self.state["pending_expiry_roll"] = {
            "old_expiry": EXPIRY,
            "new_expiry": NEXT_EXPIRY,
            "strike": STRIKE,
            "days_left": days_left,
            "urgency": urgency,
            "gain_pct_at_proposal": gain_pct,
            "value_at_proposal": market_value,
            "timestamp": datetime.now().isoformat(),
        }
        save_state(self.state)

        send_telegram(
            f"{urgency} *TRADER3: LEAP EXPIRY EXTENSION*\n"
            f"SPY ${STRIKE:.0f} Put — flat market, time decay risk\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Days to expiry: *{days_left}d* ({EXPIRY})\n"
            f"Current gain: {gain_pct:+.1f}%\n"
            f"Position value: ${market_value:.2f}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📅 *PROPOSED ROLL*\n"
            f"Current: ${STRIKE:.0f}P {EXPIRY}\n"
            f"→ New:   ${STRIKE:.0f}P {NEXT_EXPIRY} (+2yr)\n"
            f"Same strike — buys time for thesis to play out.\n"
            f"Debit = cost of time premium extension.\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🔔 *Roll forward to avoid expiry loss?*\n"
            f"Verify {NEXT_EXPIRY} is available on IBKR before approving.",
            hitl=True
        )
        log(f"EXPIRY EXTENSION proposed: {EXPIRY}→{NEXT_EXPIRY} | {days_left}d left | Gain: {gain_pct:+.1f}%")

    def approve_expiry_roll(self):
        """Execute pending expiry roll — same strike, extended expiry. Called after HITL approval."""
        roll = self.state.get("pending_expiry_roll")
        if not roll:
            return {"status": "error", "message": "No pending expiry roll"}

        self.state["pending_roll"] = {
            "old_strike": roll["strike"],
            "old_expiry": roll["old_expiry"],
            "new_strike": roll["strike"],        # Same strike
            "new_expiry": roll["new_expiry"],
            "timestamp": datetime.now().isoformat(),
        }
        self.state["pending_expiry_roll"] = None
        save_state(self.state)
        return self.execute_roll()

    def reject_expiry_roll(self):
        """Decline the proposed expiry roll."""
        self.state["pending_expiry_roll"] = None
        save_state(self.state)
        send_telegram(
            f"❌ *TRADER3: Expiry roll rejected*\n"
            f"Keeping ${STRIKE:.0f}P {EXPIRY}\n"
            f"Will re-alert if within {EXPIRY_ROLL_URGENT_DAYS} days."
        )
        return {"status": "rejected"}

    # ══════════════════════════════════════════════════════════════
    #  STRIKE ROLL — Sell current contract, buy new strike
    # ══════════════════════════════════════════════════════════════

    def propose_strike_roll(self, new_strike, new_expiry=None):
        """Propose rolling to a different strike. Requires HITL approval."""
        new_expiry = new_expiry or EXPIRY
        self.state["pending_roll"] = {
            "old_strike": STRIKE,
            "old_expiry": EXPIRY,
            "new_strike": new_strike,
            "new_expiry": new_expiry,
            "timestamp": datetime.now().isoformat()
        }
        save_state(self.state)

        send_telegram(
            f"🔄 *TRADER3: STRIKE ROLL PROPOSED*\n"
            f"SPY Put\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Current: ${STRIKE} Put {EXPIRY}\n"
            f"→ New: ${new_strike} Put {new_expiry}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🔔 *Approve this roll?*\n"
            f"This will sell the current contract and buy the new one."
        )
        log(f"Strike roll proposed: ${STRIKE} → ${new_strike}")

    def execute_roll(self):
        """Execute a pending strike roll. Sell old, buy new."""
        roll = self.state.get("pending_roll")
        if not roll:
            return {"status": "error", "message": "No pending roll"}

        if self.test_mode:
            log(f"TEST MODE — would roll ${roll['old_strike']} → ${roll['new_strike']}")
            self.state["pending_roll"] = None
            save_state(self.state)
            return {"status": "test", "message": "Would execute roll"}

        old_contract = Option(SYMBOL, roll["old_expiry"], roll["old_strike"], RIGHT, "SMART")
        self.ib.qualifyContracts(old_contract)

        sell_order = build_stealth_order(self.ib, "SELL", self.state["contracts_remaining"], old_contract)
        sell_trade = self.ib.placeOrder(old_contract, sell_order)
        self.ib.sleep(10)

        if sell_trade.orderStatus.status != "Filled":
            send_telegram(f"🔴 *TRADER3: ROLL FAILED — Could not sell old contract*\n{sell_trade.orderStatus.status}")
            return {"status": "error", "message": f"Sell failed: {sell_trade.orderStatus.status}"}

        sell_price = sell_trade.orderStatus.avgFillPrice
        log(f"Sold old ${roll['old_strike']} @ ${sell_price:.2f}")

        new_contract = Option(SYMBOL, roll["new_expiry"], roll["new_strike"], RIGHT, "SMART")
        self.ib.qualifyContracts(new_contract)

        buy_order = build_stealth_order(self.ib, "BUY", self.state["contracts_remaining"], new_contract)
        buy_trade = self.ib.placeOrder(new_contract, buy_order)
        self.ib.sleep(10)

        if buy_trade.orderStatus.status != "Filled":
            send_telegram(
                f"🔴 *TRADER3: ROLL PARTIAL — Sold old but could not buy new!*\n"
                f"Sold ${roll['old_strike']} @ ${sell_price:.2f}\n"
                f"Failed to buy ${roll['new_strike']}: {buy_trade.orderStatus.status}\n"
                f"⚠️ MANUAL INTERVENTION NEEDED"
            )
            return {"status": "partial", "message": "Sold old, failed to buy new"}

        buy_price = buy_trade.orderStatus.avgFillPrice
        net_cost = (buy_price - sell_price) * 100 * self.state["contracts_remaining"]

        self.state["pending_roll"] = None
        self.state["roll_history"] = self.state.get("roll_history", [])
        self.state["roll_history"].append({
            "old_strike": roll["old_strike"],
            "new_strike": roll["new_strike"],
            "sell_price": sell_price,
            "buy_price": buy_price,
            "net_cost": net_cost,
            "timestamp": datetime.now().isoformat()
        })

        self.state["peak_value"] = 0
        self.state["peak_gain_pct"] = 0
        self.state["trail_stop_value"] = 0
        self.state["activated"] = False
        self.state["current_tier"] = 0
        self.state["tiers_hit"] = []

        save_state(self.state)

        send_telegram(
            f"✅ *TRADER3: STRIKE ROLLED*\n"
            f"SPY Put\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Sold ${roll['old_strike']} @ ${sell_price:.2f}\n"
            f"Bought ${roll['new_strike']} @ ${buy_price:.2f}\n"
            f"Net cost: ${net_cost:.2f}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Ladder reset — monitoring new position"
        )
        log(f"ROLLED: ${roll['old_strike']} → ${roll['new_strike']} | Net: ${net_cost:.2f}")
        return {"status": "success", "net_cost": net_cost}

    def reject_roll(self):
        self.state["pending_roll"] = None
        save_state(self.state)
        send_telegram(f"❌ *TRADER3: Roll rejected*\nKeeping current ${STRIKE} strike.")
        return {"status": "rejected"}

    def show_status(self):
        s = self.state
        print(f"\n{'='*50}")
        print(f"TRADER3 — SPY $430 Put Jan 2027")
        print(f"{'='*50}")
        print(f"Activated:          {s.get('activated', False)}")
        print(f"Current Tier:       {s.get('current_tier', 0)}/{len(LADDER)}")
        print(f"Contracts Left:     {s.get('contracts_remaining', QTY)}")
        print(f"Peak Value:         ${s.get('peak_value', 0):.2f}")
        print(f"Peak Gain:          +{s.get('peak_gain_pct', 0):.1f}%")
        print(f"Trail Stop:         ${s.get('trail_stop_value', 0):.2f} ({s.get('trail_stop_pct', 0)}%)")
        print(f"Total Realized:     ${s.get('total_realized', 0):.2f}")
        print(f"Last Value:         ${s.get('last_value', 0):.2f}")
        print(f"Last Gain:          +{s.get('last_gain_pct', 0):.1f}%")
        print(f"Last Check:         {s.get('last_check', 'Never')}")
        print(f"Tiers Hit:          {', '.join(s.get('tiers_hit', []))}")
        print(f"Pending Sell:       {s.get('pending_sell')}")
        print(f"{'='*50}\n")

    def run_daemon(self):
        log(f"\n{'='*60}")
        log(f"TRADER3 — SPY $430 Put Ladder Monitor STARTED")
        log(f"Activation: +{ACTIVATION_PCT}% gain")
        log(f"Cost Basis: ${AVG_COST:.2f}")
        log(f"{'='*60}\n")

        send_telegram(
            f"🤖 *Trader3 Daemon Started*\n"
            f"SPY $430 Put Jan 2027\n"
            f"Monitoring for +{ACTIVATION_PCT}% gain to activate ladder\n"
            f"Checking every 5 min during market hours"
        )

        for hour in range(9, 16):
            for minute in range(0, 60, 5):
                if hour == 9 and minute < 30:
                    continue
                time_str = f"{hour:02d}:{minute:02d}"
                schedule.every().monday.at(time_str).do(self.check_position)
                schedule.every().tuesday.at(time_str).do(self.check_position)
                schedule.every().wednesday.at(time_str).do(self.check_position)
                schedule.every().thursday.at(time_str).do(self.check_position)
                schedule.every().friday.at(time_str).do(self.check_position)

        schedule.every().monday.at("16:00").do(self.check_position)
        schedule.every().tuesday.at("16:00").do(self.check_position)
        schedule.every().wednesday.at("16:00").do(self.check_position)
        schedule.every().thursday.at("16:00").do(self.check_position)
        schedule.every().friday.at("16:00").do(self.check_position)

        log("Scheduled: Every 5 min, Mon-Fri 9:30 AM - 4:00 PM ET")
        self.check_position()

        while True:
            try:
                schedule.run_pending()
                time.sleep(15)
            except KeyboardInterrupt:
                log("Shutdown requested")
                self.disconnect()
                break
            except Exception as e:
                log(f"Scheduler error: {e}", "ERROR")
                time.sleep(60)


def main():
    parser = argparse.ArgumentParser(description="Trader3 — SPY Put Ladder Monitor")
    parser.add_argument("--test", action="store_true", help="Test mode — no trades")
    parser.add_argument("--status", action="store_true", help="Show current state")
    parser.add_argument("--check", action="store_true", help="Run one check and exit")
    args = parser.parse_args()

    # ── PID LOCKFILE — prevent duplicate daemons ──
    if not (args.test or args.status or args.check):
        lockfile = os.path.join(os.path.dirname(__file__), "..", "data", "trader3.pid")
        if os.path.exists(lockfile):
            try:
                with open(lockfile) as f:
                    old_pid = int(f.read().strip())
                os.kill(old_pid, 0)
                log(f"ABORT: Trader3 already running (PID {old_pid}). Delete {lockfile} to override.", "ERROR")
                sys.exit(1)
            except (ProcessLookupError, ValueError):
                pass
        os.makedirs(os.path.dirname(lockfile), exist_ok=True)
        with open(lockfile, "w") as f:
            f.write(str(os.getpid()))
        import atexit
        atexit.register(lambda: os.remove(lockfile) if os.path.exists(lockfile) else None)
        log(f"PID lockfile created: {lockfile} (PID {os.getpid()})")

    trader = Trader3(test_mode=args.test)

    if args.status:
        trader.show_status()
        return

    if args.check or args.test:
        if not trader.connect():
            sys.exit(1)
        trader.check_position()
        trader.show_status()
        trader.disconnect()
        return

    trader.run_daemon()


if __name__ == "__main__":
    main()
