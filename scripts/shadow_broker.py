"""Shadow Broker — Simulated execution engine.
No IBKR connection. No real money. Full ladder tracking.

Features:
- Simulates fills with 0.1% slippage + 150ms latency
- Tracks HWM and runs the full ladder on every price tick
- Fires Telegram alerts exactly as live would
- Detects signal storms (3+ identical signals in 5 seconds)
- Blocks duplicate positions
- Saves state to data/shadow_positions.json (survives restarts)
- compare_with_live() for Week 2 divergence checking
"""
import os
import sys
import json
import time
import uuid
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Optional, Dict

sys.path.insert(0, os.path.dirname(__file__))
from broker_base import BrokerBase, Order, Fill, Position
from stop_utils import get_laddered_trail_pct, LADDERED_SYSTEMS

DATA_DIR = os.path.expanduser("~/rudy/data")
LOG_DIR = os.path.expanduser("~/rudy/logs")
STATE_FILE = os.path.join(DATA_DIR, "shadow_positions.json")
SHADOW_LOG = os.path.join(LOG_DIR, "shadow_broker.log")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# Simulation parameters
SLIPPAGE_PCT = 0.005    # 0.5% stock slippage → ~5% LEAP equivalent (v2.2 production)
LATENCY_MS = 150        # 150ms simulated latency
COMMISSION_PER_CONTRACT = 0.65  # IBKR commission per contract

# Storm detection
STORM_WINDOW_SEC = 5
STORM_THRESHOLD = 3


class ShadowBroker(BrokerBase):

    def __init__(self):
        self.positions: List[Position] = []
        self.fills: List[Fill] = []
        self.exits: List[Dict] = []
        self.signal_log: List[Dict] = []  # for storm detection
        self.storms: List[Dict] = []
        self._starting_capital = 240000.0
        self._realized_pnl = 0.0
        self._load_state()

    def get_mode(self) -> str:
        return "shadow"

    # ─── Order Execution ─────────────────────────────────────────────────

    def place_order(self, order: Order) -> Fill:
        """Simulate order execution with slippage and storm detection."""

        # Check circuit breaker
        try:
            import auditor
            blocked, reason = auditor.is_breaker_active()
            if blocked and order.action == "BUY":
                self._log(f"BLOCKED {order.action} {order.symbol} — {reason}")
                return Fill(order=order, status="blocked", reason=reason, mode="shadow")
        except ImportError:
            pass

        # Storm detection
        if self._check_storm(order):
            reason = f"STORM: {order.symbol} × {STORM_THRESHOLD}+ signals in {STORM_WINDOW_SEC}s"
            self._log(f"🚨 SHADOW STORM: {reason}")
            self._send_telegram(f"🚨 *SHADOW STORM DETECTED*\n\n{reason}")
            return Fill(order=order, status="blocked", reason=reason, mode="shadow")

        # Duplicate check (BUY only)
        if order.action == "BUY":
            dupes = [p for p in self.positions if p.symbol == order.symbol and p.system == order.system]
            if dupes:
                reason = f"DUPLICATE: already have {order.symbol} in {order.system}"
                self._log(f"BLOCKED {order.action} {order.symbol} — {reason}")
                return Fill(order=order, status="blocked", reason=reason, mode="shadow")

        # Simulate latency
        time.sleep(LATENCY_MS / 1000)

        # Simulate fill price with slippage
        base_price = order.limit_price or 0.0
        if base_price <= 0:
            base_price = 5.00  # fallback for market orders without price

        if order.action == "BUY":
            fill_price = round(base_price * (1 + SLIPPAGE_PCT), 4)
        else:
            fill_price = round(base_price * (1 - SLIPPAGE_PCT), 4)

        slippage = abs(fill_price - base_price)
        commission = COMMISSION_PER_CONTRACT * order.qty
        order_id = f"SHD-{uuid.uuid4().hex[:8]}"

        fill = Fill(
            order=order,
            status="simulated",
            fill_price=fill_price,
            fill_qty=order.qty,
            slippage=slippage,
            commission=commission,
            order_id=order_id,
            mode="shadow",
        )

        self.fills.append(fill)

        # Track position
        if order.action == "BUY":
            pos = Position(
                symbol=order.symbol,
                system=order.system,
                qty=order.qty,
                entry_price=fill_price,
                entry_time=datetime.now().isoformat(),
                current_price=fill_price,
                high_water=fill_price,
                strike=order.strike,
                expiry=order.expiry,
                right=order.right,
                order_id=order_id,
            )
            self.positions.append(pos)
            self._log(f"BUY {order.symbol} x{order.qty} @ ${fill_price:.2f} | "
                      f"System: {order.system} | Slip: ${slippage:.4f} | ID: {order_id}")
            self._send_telegram(
                f"🟢 *SHADOW BUY*\n\n"
                f"{order.symbol} x{order.qty} @ ${fill_price:.2f}\n"
                f"System: {order.system}\n"
                f"Slippage: ${slippage:.4f} ({SLIPPAGE_PCT * 100}%)\n"
                f"ID: {order_id}"
            )

        elif order.action in ("SELL", "EXIT"):
            closed = self._close_position(order, fill_price)
            if closed:
                pnl = (fill_price - closed.entry_price) * closed.qty * 100
                self._realized_pnl += pnl
                self.exits.append({
                    "symbol": closed.symbol, "system": closed.system,
                    "entry_price": closed.entry_price, "exit_price": fill_price,
                    "qty": closed.qty, "pnl": pnl,
                    "exit_time": datetime.now().isoformat(),
                    "reason": order.comment or "manual",
                })
                self._log(f"SELL {order.symbol} x{order.qty} @ ${fill_price:.2f} | "
                          f"P&L: ${pnl:+,.0f} | System: {order.system}")
                emoji = "🟢" if pnl >= 0 else "🔴"
                self._send_telegram(
                    f"{emoji} *SHADOW SELL*\n\n"
                    f"{order.symbol} x{order.qty} @ ${fill_price:.2f}\n"
                    f"Entry: ${closed.entry_price:.2f} | P&L: ${pnl:+,.0f}\n"
                    f"System: {order.system}"
                )
            else:
                self._log(f"SELL {order.symbol} — no position found to close")

        self._save_state()
        return fill

    def cancel_order(self, order_id: str) -> bool:
        self._log(f"CANCEL {order_id} (shadow — no-op)")
        return True

    # ─── Position Management ─────────────────────────────────────────────

    def get_positions(self) -> List[Position]:
        return list(self.positions)

    def get_account_value(self) -> float:
        unrealized = sum(p.unrealized_pnl for p in self.positions)
        return self._starting_capital + self._realized_pnl + unrealized

    def _close_position(self, order: Order, fill_price: float) -> Optional[Position]:
        """Find and remove the matching position."""
        for i, pos in enumerate(self.positions):
            if pos.symbol == order.symbol and pos.system == order.system:
                closed = self.positions.pop(i)
                closed.current_price = fill_price
                return closed
        # Fallback: match by symbol only
        for i, pos in enumerate(self.positions):
            if pos.symbol == order.symbol:
                closed = self.positions.pop(i)
                closed.current_price = fill_price
                return closed
        return None

    # ─── Price Updates + Ladder Tracking ─────────────────────────────────

    def update_price(self, symbol: str, price: float, system: str = None):
        """Feed a price tick into the shadow engine. Updates HWM, checks ladder stops."""
        for pos in self.positions:
            if pos.symbol != symbol:
                continue
            if system and pos.system != system:
                continue

            pos.current_price = price

            # Update HWM
            if price > pos.high_water:
                pos.high_water = price

            # Check laddered trailing stop
            gain_pct = pos.gain_pct  # uses HWM
            trail_pct = get_laddered_trail_pct(pos.system, gain_pct)

            if trail_pct is not None:
                stop_level = pos.high_water * (1 - trail_pct / 100)
                if price <= stop_level:
                    self._log(f"LADDER STOP: {symbol} price ${price:.2f} <= stop ${stop_level:.2f} "
                              f"({trail_pct}% from HW ${pos.high_water:.2f}) | {pos.system}")
                    # Auto-close via SELL
                    sell_order = Order(
                        symbol=symbol, action="SELL", qty=pos.qty,
                        system=pos.system, limit_price=price,
                        comment=f"Laddered stop ({trail_pct}% trail from HWM)",
                    )
                    self.place_order(sell_order)
                    return
                else:
                    self._log(f"LADDER {symbol}: gain={gain_pct:.0f}% → trail={trail_pct}% "
                              f"(was {'None' if not hasattr(pos, '_last_trail') else pos._last_trail}) | "
                              f"stop=${stop_level:.2f}")
            else:
                self._log(f"LADDER {symbol}: gain={gain_pct:.0f}% → no stop (lottery mode) | {pos.system}")

        self._save_state()

    # ─── Storm Detection ─────────────────────────────────────────────────

    def _check_storm(self, order: Order) -> bool:
        """Detect signal storms: 3+ identical signals within 5 seconds."""
        now = datetime.now()
        self.signal_log.append({
            "symbol": order.symbol, "action": order.action,
            "system": order.system, "time": now,
        })

        # Clean old entries
        cutoff = now - timedelta(seconds=STORM_WINDOW_SEC)
        self.signal_log = [s for s in self.signal_log if s["time"] > cutoff]

        # Count identical recent signals
        matching = [s for s in self.signal_log
                    if s["symbol"] == order.symbol
                    and s["action"] == order.action
                    and s["system"] == order.system]

        if len(matching) >= STORM_THRESHOLD:
            self.storms.append({
                "symbol": order.symbol, "count": len(matching),
                "time": now.isoformat(),
            })
            return True
        return False

    # ─── Live Comparison ─────────────────────────────────────────────────

    def compare_with_live(self, live_fills: List[Dict]) -> Dict:
        """Compare shadow fills with live fills. Returns divergences.

        Args:
            live_fills: List of dicts with {symbol, action, fill_price, fill_time}

        Returns:
            {"clean": bool, "divergences": [str], "summary": str}
        """
        divergences = []
        matched = 0
        threshold = 0.10  # $0.10 max divergence

        for lf in live_fills:
            # Find matching shadow fill
            shadow = None
            for sf in self.fills:
                if (sf.order.symbol == lf["symbol"]
                    and sf.order.action == lf["action"]
                    and sf.is_success):
                    shadow = sf
                    break

            if not shadow:
                divergences.append(f"MISSING: Live fill {lf['symbol']} {lf['action']} has no shadow match")
                continue

            price_diff = abs(shadow.fill_price - lf["fill_price"])
            if price_diff > threshold:
                divergences.append(
                    f"PRICE: {lf['symbol']} shadow=${shadow.fill_price:.2f} "
                    f"live=${lf['fill_price']:.2f} diff=${price_diff:.2f}"
                )
            else:
                matched += 1

        return {
            "clean": len(divergences) == 0,
            "divergences": divergences,
            "matched": matched,
            "total_live": len(live_fills),
            "summary": f"{matched}/{len(live_fills)} matched, {len(divergences)} divergences",
        }

    # ─── State Persistence ───────────────────────────────────────────────

    def _save_state(self):
        state = {
            "positions": [p.to_dict() for p in self.positions],
            "realized_pnl": self._realized_pnl,
            "exits": self.exits[-50:],  # keep last 50
            "storms": self.storms[-20:],
            "last_updated": datetime.now().isoformat(),
        }
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    def _load_state(self):
        if not os.path.exists(STATE_FILE):
            return
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
            self.positions = [Position.from_dict(p) for p in state.get("positions", [])]
            self._realized_pnl = state.get("realized_pnl", 0.0)
            self.exits = state.get("exits", [])
            self.storms = state.get("storms", [])
            self._log(f"Loaded {len(self.positions)} shadow positions, "
                      f"P&L: ${self._realized_pnl:+,.0f}")
        except (json.JSONDecodeError, IOError) as e:
            self._log(f"Failed to load shadow state: {e}")

    # ─── Logging ─────────────────────────────────────────────────────────

    def _log(self, msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[Shadow {ts}] {msg}"
        print(line)
        try:
            with open(SHADOW_LOG, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _send_telegram(self, msg):
        try:
            import telegram
            telegram.send(msg)
        except Exception:
            pass

    # ─── Dashboard Data ──────────────────────────────────────────────────

    def get_dashboard_data(self) -> Dict:
        """Return data for shadow_dashboard.py display."""
        unrealized = sum(p.unrealized_pnl for p in self.positions)
        return {
            "mode": "SHADOW",
            "positions": [p.to_dict() for p in self.positions],
            "open_count": len(self.positions),
            "realized_pnl": self._realized_pnl,
            "unrealized_pnl": unrealized,
            "total_pnl": self._realized_pnl + unrealized,
            "account_value": self.get_account_value(),
            "recent_exits": self.exits[-5:],
            "storms": self.storms[-5:],
            "fills_today": len([f for f in self.fills
                                if f.fill_time and f.fill_time[:10] == datetime.now().strftime("%Y-%m-%d")]),
        }
