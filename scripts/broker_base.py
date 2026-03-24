"""Broker Base — Abstract interface for all broker implementations.
One interface, two implementations: ShadowBroker and IBKRBroker.
Every trader script calls broker.place_order(order). The factory decides what happens.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any


@dataclass
class Order:
    """Unified order object — used by all broker implementations."""
    symbol: str
    action: str                    # BUY, SELL, EXIT
    qty: int
    order_type: str = "MKT"       # MKT, LMT, TRAIL
    system: str = "unknown"
    limit_price: Optional[float] = None
    trail_pct: Optional[float] = None
    # Option fields
    strike: Optional[float] = None
    expiry: Optional[str] = None
    right: str = "C"              # C or P
    # Metadata
    comment: str = ""
    timestamp: Optional[str] = None
    # v2.2 Production — premium tracking
    premium_pct: Optional[float] = None          # Actual mNAV premium (e.g., 1.3 = 1.3x)
    leap_multiplier: Optional[float] = None      # Effective LEAP multiplier used

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()
        self.action = self.action.upper()
        self.symbol = self.symbol.upper()


@dataclass
class Fill:
    """Unified fill result — returned by all broker implementations."""
    order: Order
    status: str                    # filled, simulated, blocked, failed, rejected
    fill_price: float = 0.0
    fill_qty: int = 0
    fill_time: Optional[str] = None
    reason: str = ""               # for blocked/failed
    slippage: float = 0.0
    commission: float = 0.0
    order_id: Optional[str] = None
    mode: str = "unknown"          # shadow, paper, live
    raw: Optional[Any] = None      # broker-specific data (Trade object for IBKR)

    def __post_init__(self):
        if self.fill_time is None:
            self.fill_time = datetime.now().isoformat()

    @property
    def cost(self):
        """Total cost including commission (options are 100x)."""
        return self.fill_price * self.fill_qty * 100 + self.commission

    @property
    def is_success(self):
        return self.status in ("filled", "simulated")


@dataclass
class Position:
    """Tracked position — used by shadow broker and position tracking."""
    symbol: str
    system: str
    qty: int
    entry_price: float
    entry_time: str
    current_price: float = 0.0
    high_water: float = 0.0
    strike: Optional[float] = None
    expiry: Optional[str] = None
    right: str = "C"
    order_id: Optional[str] = None

    @property
    def gain_pct(self):
        if self.entry_price <= 0:
            return 0.0
        return ((self.high_water - self.entry_price) / self.entry_price) * 100

    @property
    def current_gain_pct(self):
        if self.entry_price <= 0:
            return 0.0
        return ((self.current_price - self.entry_price) / self.entry_price) * 100

    @property
    def unrealized_pnl(self):
        return (self.current_price - self.entry_price) * self.qty * 100

    def to_dict(self):
        return {
            "symbol": self.symbol, "system": self.system, "qty": self.qty,
            "entry_price": self.entry_price, "entry_time": self.entry_time,
            "current_price": self.current_price, "high_water": self.high_water,
            "strike": self.strike, "expiry": self.expiry, "right": self.right,
            "order_id": self.order_id,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class BrokerBase(ABC):
    """Abstract broker interface. Implement place_order and get_positions."""

    @abstractmethod
    def place_order(self, order: Order) -> Fill:
        """Place an order. Returns a Fill with status."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by ID."""
        ...

    @abstractmethod
    def get_positions(self) -> List[Position]:
        """Get all open positions."""
        ...

    @abstractmethod
    def get_account_value(self) -> float:
        """Get current account net liquidation value."""
        ...

    @abstractmethod
    def get_mode(self) -> str:
        """Return current mode: shadow, paper, live."""
        ...
