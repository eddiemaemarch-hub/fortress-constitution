"""IBKR Broker — Wraps existing ibkr_utils behind the unified broker interface.
Minimal new code. Delegates to connect_with_retry, place_order_with_retry, validate_entry.
"""
import os
import sys
import uuid
from datetime import datetime
from typing import List, Optional

sys.path.insert(0, os.path.dirname(__file__))
from broker_base import BrokerBase, Order, Fill, Position

LOG_DIR = os.path.expanduser("~/rudy/logs")
os.makedirs(LOG_DIR, exist_ok=True)


class IBKRBroker(BrokerBase):

    def __init__(self, port=7496, mode="paper", host="127.0.0.1", client_id=1):
        self.host = host
        self.port = port
        self.mode = mode
        self.client_id = client_id
        self.ib = None
        self._connect()

    def get_mode(self) -> str:
        return self.mode

    def _connect(self):
        """Connect using ibkr_utils with exponential backoff."""
        try:
            from ibkr_utils import connect_with_retry
            self.ib = connect_with_retry(
                host=self.host, port=self.port,
                client_id=self.client_id, max_retries=5,
                log_func=self._log,
            )
        except Exception as e:
            self._log(f"Connection failed: {e}")
            self.ib = None

    def _ensure_connected(self):
        """Health check before every order."""
        try:
            from ibkr_utils import ensure_connected
            self.ib = ensure_connected(
                self.ib, host=self.host, port=self.port,
                client_id=self.client_id, log_func=self._log,
            )
        except Exception as e:
            self._log(f"Reconnect failed: {e}")
            self.ib = None

    # ─── Order Execution ─────────────────────────────────────────────────

    def place_order(self, order: Order) -> Fill:
        """Place order on IBKR using place_order_with_retry."""
        from ibkr_utils import place_order_with_retry, validate_entry

        self._ensure_connected()
        if not self.ib:
            return Fill(order=order, status="failed",
                        reason="IBKR not connected", mode=self.mode)

        # Entry validation (BUY only)
        if order.action == "BUY":
            # Resolve system_id from system name
            try:
                import auditor
                sys_id = None
                for sid, sinfo in auditor.SYSTEMS.items():
                    if sinfo["name"].lower().replace(" ", "_") == order.system.lower():
                        sys_id = sid
                        break
                if sys_id is None:
                    sys_id = 1  # fallback

                approved, reason = validate_entry(
                    order.symbol, sys_id, order.qty,
                    order.limit_price or 0, log_func=self._log,
                )
                if not approved:
                    return Fill(order=order, status="blocked",
                                reason=reason, mode=self.mode)
            except Exception as e:
                self._log(f"Validation error (proceeding): {e}")

        # Build IBKR contract + order
        ibkr_contract, ibkr_order = self._build_ibkr_objects(order)
        if not ibkr_contract:
            return Fill(order=order, status="failed",
                        reason="Could not build IBKR contract", mode=self.mode)

        # Qualify contract
        try:
            qualified = self.ib.qualifyContracts(ibkr_contract)
            if not qualified:
                return Fill(order=order, status="failed",
                            reason=f"Contract not qualified: {order.symbol}", mode=self.mode)
        except Exception as e:
            return Fill(order=order, status="failed",
                        reason=f"Qualify error: {e}", mode=self.mode)

        # Place with retry
        trade = place_order_with_retry(
            self.ib, ibkr_contract, ibkr_order,
            max_retries=3, delay=2, log_func=self._log,
        )

        if trade is None:
            return Fill(order=order, status="failed",
                        reason="All retries exhausted", mode=self.mode)

        # Extract fill
        fill_price = trade.orderStatus.avgFillPrice or order.limit_price or 0
        status_map = {
            "Filled": "filled",
            "Submitted": "filled",
            "PreSubmitted": "filled",
        }
        fill_status = status_map.get(trade.orderStatus.status, "failed")

        return Fill(
            order=order,
            status=fill_status,
            fill_price=fill_price,
            fill_qty=order.qty,
            commission=0.65 * order.qty,
            order_id=str(trade.order.orderId),
            mode=self.mode,
            raw=trade,
        )

    def cancel_order(self, order_id: str) -> bool:
        self._ensure_connected()
        if not self.ib:
            return False
        try:
            for trade in self.ib.openTrades():
                if str(trade.order.orderId) == order_id:
                    self.ib.cancelOrder(trade.order)
                    return True
        except Exception as e:
            self._log(f"Cancel error: {e}")
        return False

    # ─── Position Management ─────────────────────────────────────────────

    def get_positions(self) -> List[Position]:
        self._ensure_connected()
        if not self.ib:
            return []

        positions = []
        try:
            for p in self.ib.positions():
                if p.position == 0:
                    continue
                c = p.contract
                pos = Position(
                    symbol=c.symbol,
                    system="unknown",  # IBKR doesn't track system
                    qty=abs(int(p.position)),
                    entry_price=p.avgCost / 100 if c.secType == "OPT" else p.avgCost,
                    entry_time="",
                    current_price=0,
                    high_water=0,
                    strike=getattr(c, "strike", None),
                    expiry=getattr(c, "lastTradeDateOrContractMonth", None),
                    right=getattr(c, "right", "C"),
                )
                positions.append(pos)
        except Exception as e:
            self._log(f"Position read error: {e}")

        return positions

    def get_account_value(self) -> float:
        self._ensure_connected()
        if not self.ib:
            return 0.0
        try:
            summary = self.ib.accountSummary()
            for item in summary:
                if item.tag == "NetLiquidation":
                    return float(item.value)
        except Exception as e:
            self._log(f"Account value error: {e}")
        return 0.0

    # ─── Helpers ─────────────────────────────────────────────────────────

    def _build_ibkr_objects(self, order: Order):
        """Build ib_insync Contract and Order from our unified Order."""
        try:
            from ib_insync import Option, Stock, MarketOrder, LimitOrder

            # Build contract
            if order.strike and order.expiry:
                contract = Option(
                    order.symbol, order.expiry,
                    order.strike, order.right, "SMART",
                )
            else:
                contract = Stock(order.symbol, "SMART", "USD")

            # Build order
            if order.order_type == "LMT" and order.limit_price:
                ibkr_order = LimitOrder(order.action, order.qty, order.limit_price)
            else:
                ibkr_order = MarketOrder(order.action, order.qty)

            ibkr_order.tif = "GTC"
            return contract, ibkr_order

        except Exception as e:
            self._log(f"Build error: {e}")
            return None, None

    def _log(self, msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[IBKR-{self.mode} {ts}] {msg}"
        print(line)
        try:
            with open(f"{LOG_DIR}/ibkr_broker.log", "a") as f:
                f.write(line + "\n")
        except Exception:
            pass
