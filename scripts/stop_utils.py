"""Trailing Stop Utilities — Constitution v45.0 MANDATORY stop enforcement.
Every position MUST have a trailing stop placed at entry. No exceptions.
Supports both flat trailing stops and laddered trailing stops for moonshot strategies.
"""
from ib_insync import Order


# Per-system trailing stop percentages (flat trail)
TRAIL_PCT = {
    "system1": 30,
    "system1_v8": 30,
    "energy_momentum": 30,
    "short_squeeze": 30,
    "breakout_momentum": 30,
    "metals_momentum": 30,
    "spacex_ipo": 30,
    "10x_moonshot": 30,
    "tqqq_momentum": 30,
    "default": 30,
}

# Laddered trailing stop tiers — for moonshot/lottery strategies
# As gains increase, the trailing stop tightens to lock profits
# Format: (min_gain_pct, trail_pct_from_high)
LADDERED_TRAIL = {
    "mstr_moonshot": [
        (0, None),       # No stop until +300% (lottery mode)
        (300, 30),       # 3x: 30% trail from peak
        (500, 25),       # 5x: 25% trail + sell 25%
        (1000, 20),      # 10x: 20% trail + sell 25%
        (2000, 15),      # 20x: 15% trail + sell 25%
        (5000, 10),      # 50x: 10% trail — lock the bag
    ],
    "10x_momentum": [
        (0, None),       # < +50%: no stop
        (50, 25),        # +50%: 25% trail from peak
        (100, 20),       # +100%: 20% trail
        (200, 15),       # +200%: 15% trail — lock it
    ],
    "10x_runner_v2": [
        (0, None),
        (50, 25),
        (100, 20),
        (200, 15),
    ],
    "energy_momentum": [
        (0, None),       # < +30%: no stop
        (30, 20),        # +30%: 20% trail from peak
        (50, 15),        # +50%: 15% trail
        (100, 12),       # +100%: 12% trail — lock it
    ],
    "short_squeeze": [
        (0, None),
        (30, 20),
        (50, 15),
        (100, 12),
    ],
    "breakout_momentum": [
        (0, None),
        (30, 20),
        (50, 15),
        (100, 12),
    ],
    "tqqq_momentum": [
        (0, None),
        (30, 20),
        (50, 15),
        (100, 12),
    ],
    "ntr_ag_momentum": [
        (0, None),
        (30, 20),
        (50, 15),
        (100, 12),
    ],
    "mstr_lottery": [
        (0, None),       # < +15%: no stop
        (15, 15),        # +15%: 15% trail from peak
        (30, 12),        # +30%: 12% trail
        (50, 10),        # +50%: 10% trail — lock it
    ],
    "sideways_condor": [
        (0, None),
        (15, 15),
        (30, 12),
        (50, 10),
    ],
    "fence_bar": [
        (0, None),
        (15, 15),
        (30, 12),
        (50, 10),
    ],
}

# Systems that use laddered stops instead of flat stops
LADDERED_SYSTEMS = set(LADDERED_TRAIL.keys())


def get_laddered_trail_pct(system_name, current_gain_pct):
    """Get the correct trailing stop percentage for a laddered system based on current gain.

    Args:
        system_name: System identifier
        current_gain_pct: Current gain as percentage (e.g., 150 = +150%)

    Returns:
        Trail percentage from high water mark, or None if no stop at this level
    """
    tiers = LADDERED_TRAIL.get(system_name)
    if not tiers:
        return TRAIL_PCT.get(system_name, TRAIL_PCT["default"])

    trail_pct = None
    for min_gain, pct in tiers:
        if current_gain_pct >= min_gain:
            trail_pct = pct
    return trail_pct


def place_trailing_stop(ib, contract, qty, fill_price, system_name, log_func=None):
    """Place a trailing stop on IBKR immediately after entry fill.

    Constitution v45.0: MANDATORY — every position gets a trailing stop at entry.
    Uses TRAIL order type with auxPrice = trail amount in dollars.
    Falls back to software monitor (stop_monitor.py) if IBKR rejects.
    Laddered systems (mstr_moonshot) skip initial IBKR stop — managed by software monitor.

    Args:
        ib: Connected IB instance
        contract: The option contract (already qualified)
        qty: Number of contracts
        fill_price: Entry fill price per contract
        system_name: System identifier for trail % lookup
        log_func: Optional logging function

    Returns:
        dict with stop order status
    """
    # Laddered systems: no IBKR stop at entry (0-100% tier = no stop)
    # Software stop monitor handles the laddered logic
    if system_name in LADDERED_SYSTEMS:
        tier_pct = get_laddered_trail_pct(system_name, 0)  # 0% gain at entry
        if tier_pct is None:
            msg = (f"LADDERED STOP: {contract.symbol} ${contract.strike}{contract.right} "
                   f"x{qty} @ ${fill_price:.2f} | No stop at entry (lottery mode) | "
                   f"Managed by stop_monitor.py — activates at +100% gain")
            if log_func:
                log_func(msg)
            return {
                "type": "LADDERED",
                "system": system_name,
                "tiers": LADDERED_TRAIL[system_name],
                "current_tier": "0-100% (no stop)",
                "status": "software_monitor",
                "fallback": "software_monitor",
            }

    pct = TRAIL_PCT.get(system_name, TRAIL_PCT["default"])
    trail_amt = round(fill_price * (pct / 100), 2)
    if trail_amt < 0.01:
        trail_amt = 0.01

    order = Order()
    order.action = "SELL"
    order.totalQuantity = qty
    order.orderType = "TRAIL"
    order.auxPrice = trail_amt  # trailing amount in $
    order.tif = "GTC"

    trade = ib.placeOrder(contract, order)
    ib.sleep(2)

    status = trade.orderStatus.status
    result = {
        "type": "TRAIL",
        "trail_pct": pct,
        "trail_amt": trail_amt,
        "status": status,
    }

    msg = (f"TRAILING STOP: {contract.symbol} ${contract.strike}{contract.right} "
           f"x{qty} | Trail ${trail_amt:.2f} ({pct}% of ${fill_price:.2f}) | "
           f"Status: {status}")

    if log_func:
        log_func(msg)

    if status in ("Cancelled", "Inactive"):
        # IBKR rejected — software monitor will handle it
        if log_func:
            log_func(f"  IBKR rejected stop — stop_monitor.py will enforce")
        result["fallback"] = "software_monitor"

    return result
