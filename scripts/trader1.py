"""Trader1 — Autonomous Execution Engine for Rudy v2.0
Executes approved trades via IBKR TWS API.
Handles exits, 10x rule, stops, hedges — zero human input after approval.
"""
# ══════════════════════════════════════════════════════════════
# AUTHORITY LOCK — Rudy v2.0 Constitution v50.0
# This script is NOT authorized to execute trades.
# Authorized traders: trader_v28.py (Trader1/v2.8+),
#                     trader2_mstr_put.py (Trader2),
#                     trader3_spy_put.py (Trader3)
# To re-authorize this script, edit this block explicitly.
# ══════════════════════════════════════════════════════════════
import sys as _sys
_sys.exit(0)
import os
import sys
import json
import time
import threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import telegram
import memory

from ib_insync import *

LOG_DIR = os.path.expanduser("~/rudy/logs")
POSITIONS_FILE = os.path.expanduser("~/rudy/data/positions.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(os.path.dirname(POSITIONS_FILE), exist_ok=True)

# Constitution v50.0 parameters
TEN_X_SELL_PCT = 0.50  # Sell 50% at 10x
SURVIVAL_BREAKER_S1 = 75000
SURVIVAL_BREAKER_S2 = 7500

_ib = None


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(f"{LOG_DIR}/trader1.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")
    print(f"[Trader1 {ts}] {msg}")


def connect(port=7496, client_id=10):
    global _ib
    if _ib and _ib.isConnected():
        return _ib
    _ib = IB()
    _ib.connect("127.0.0.1", port, clientId=client_id)
    _ib.reqMarketDataType(3)  # Delayed data
    log(f"Connected to IBKR on port {port}")
    return _ib


def disconnect():
    global _ib
    if _ib:
        _ib.disconnect()
        _ib = None


def check_mstr_context():
    """Surface MSTR strategy context from memory before execution.
    Logs EMA analysis, entry signals, and risk assessment so trader1
    has full awareness of the macro setup when executing System 1.
    """
    try:
        mstr_memories = memory.recall_for_ticker("MSTR", n=5)
        strategy_ctx = [m for m in mstr_memories if m.get("type") == "mstr_strategy_analysis"]

        if strategy_ctx:
            latest = strategy_ctx[0]
            ema = latest.get("ema_analysis", {})
            signals = latest.get("entry_signals_to_watch", {})

            monthly = ema.get("monthly_200ema", {})
            weekly = ema.get("weekly_200ema", {})

            log(f"MSTR CONTEXT CHECK — Source: {latest.get('source', 'unknown')}")
            log(f"  Monthly 200 EMA: price {monthly.get('price_position', '?')} — {monthly.get('interpretation', 'N/A')[:120]}")
            log(f"  Weekly 200 EMA: price {weekly.get('price_position', '?')} (zone {weekly.get('ema_zone', '?')}) — {weekly.get('interpretation', 'N/A')[:120]}")
            log(f"  Combined Signal: {ema.get('combined_signal', 'N/A')[:150]}")
            log(f"  Entry Watch: {signals.get('weekly_200ema_reclaim', 'N/A')[:120]}")
            log(f"  BTC Check: {signals.get('btc_stabilization', 'N/A')}")
            log(f"  Premium: {signals.get('premium_compression', 'N/A')}")
            log(f"  Risk: {latest.get('risk_assessment', 'N/A')[:150]}")

            return latest
        else:
            log("MSTR CONTEXT CHECK — No strategy analysis found in memory")
            return None
    except Exception as e:
        log(f"MSTR context check error (non-fatal): {e}")
        return None


def execute_trade(trade_spec):
    """Execute an approved trade from E.M."""
    ib = connect()
    system = trade_spec.get("system", "")
    ticker = trade_spec.get("ticker", "")
    action = trade_spec.get("action", "BUY")

    log(f"Executing: {system} — {action} {ticker}")

    if system == "system1":
        # Surface MSTR context before executing lottery trades
        check_mstr_context()
        return execute_system1(ib, trade_spec)
    elif system == "system2":
        return execute_system2(ib, trade_spec)
    else:
        return execute_generic(ib, trade_spec)


def execute_system1(ib, spec):
    """System 1: MSTR Lottery — 3 call legs + tail hedge"""
    results = []

    for leg in spec.get("legs", []):
        contract = Option(
            leg["symbol"], leg["expiry"], leg["strike"],
            leg.get("right", "C"), "SMART"
        )
        ib.qualifyContracts(contract)

        qty = leg["quantity"]
        order = MarketOrder("BUY", qty)
        trade = ib.placeOrder(contract, order)
        ib.sleep(3)

        fill_price = trade.orderStatus.avgFillPrice if trade.orderStatus.avgFillPrice else 0
        results.append({
            "strike": leg["strike"],
            "qty": qty,
            "fill_price": fill_price,
            "status": trade.orderStatus.status
        })
        log(f"S1 leg: {leg['strike']} x{qty} filled @ {fill_price}")

        # Save position for 10x monitoring
        save_position({
            "system": "system1",
            "symbol": leg["symbol"],
            "strike": leg["strike"],
            "expiry": leg["expiry"],
            "right": "C",
            "qty": qty,
            "entry_price": fill_price,
            "entry_date": datetime.now().isoformat(),
        })

    # Execute tail hedge
    hedge = spec.get("hedge")
    if hedge:
        contract = Option(
            hedge["symbol"], hedge["expiry"], hedge["strike"],
            hedge.get("right", "P"), "SMART"
        )
        ib.qualifyContracts(contract)
        order = MarketOrder("BUY", hedge["quantity"])
        trade = ib.placeOrder(contract, order)
        ib.sleep(3)
        log(f"S1 hedge: {hedge['strike']}P x{hedge['quantity']}")

    telegram.send(
        f"🎯 *System 1 Executed*\n\n"
        + "\n".join(f"Strike ${r['strike']}: {r['qty']} @ ${r['fill_price']:.2f}" for r in results)
        + "\n\n10x monitoring active."
    )

    # Start 10x monitor in background
    threading.Thread(target=monitor_10x, daemon=True).start()

    return {"status": "executed", "legs": results}


def execute_system2(ib, spec):
    """System 2: Conservative Diagonal — single entry"""
    ticker = spec["ticker"]
    action = spec.get("action", "BUY")
    qty = spec.get("quantity", 1)

    if spec.get("type") == "diagonal":
        # Buy LEAP, sell short-dated
        long_leg = spec["long_leg"]
        short_leg = spec["short_leg"]

        long_contract = Option(ticker, long_leg["expiry"], long_leg["strike"], "C", "SMART")
        short_contract = Option(ticker, short_leg["expiry"], short_leg["strike"], "C", "SMART")
        ib.qualifyContracts(long_contract, short_contract)

        buy_trade = ib.placeOrder(long_contract, MarketOrder("BUY", qty))
        sell_trade = ib.placeOrder(short_contract, MarketOrder("SELL", qty))
        ib.sleep(3)

        result = {
            "status": "executed",
            "type": "diagonal",
            "long_fill": buy_trade.orderStatus.avgFillPrice,
            "short_fill": sell_trade.orderStatus.avgFillPrice,
        }
    else:
        # Pure LEAP
        contract = Option(ticker, spec["expiry"], spec["strike"], "C", "SMART")
        ib.qualifyContracts(contract)
        trade = ib.placeOrder(contract, MarketOrder(action, qty))
        ib.sleep(3)

        result = {
            "status": "executed",
            "type": "leap",
            "fill_price": trade.orderStatus.avgFillPrice,
        }

    save_position({
        "system": "system2",
        "symbol": ticker,
        "entry_date": datetime.now().isoformat(),
        **spec
    })

    log(f"S2 executed: {ticker} — {result}")
    return result


def execute_generic(ib, spec):
    """Generic stock/option order."""
    ticker = spec["ticker"]
    action = spec.get("action", "BUY")
    qty = spec.get("quantity", 1)

    contract = Stock(ticker, "SMART", "USD")
    ib.qualifyContracts(contract)
    trade = ib.placeOrder(contract, MarketOrder(action, qty))
    ib.sleep(3)

    return {
        "status": trade.orderStatus.status,
        "fill_price": trade.orderStatus.avgFillPrice,
    }


def monitor_10x():
    """Monitor System 1 positions for 10x rule.
    At 10x entry premium, auto-sell 50%.
    """
    log("10x monitor started")
    ib = connect(client_id=11)

    while True:
        positions = load_positions()
        s1_positions = [p for p in positions if p.get("system") == "system1" and not p.get("10x_triggered")]

        if not s1_positions:
            log("10x monitor: no active S1 positions to watch")
            break

        for pos in s1_positions:
            try:
                contract = Option(
                    pos["symbol"], pos["expiry"], pos["strike"],
                    pos.get("right", "C"), "SMART"
                )
                ib.qualifyContracts(contract)
                ticker = ib.reqMktData(contract)
                ib.sleep(3)

                current = ticker.last if ticker.last == ticker.last else ticker.close
                entry = pos["entry_price"]

                if entry > 0 and current >= entry * 10:
                    sell_qty = max(1, int(pos["qty"] * TEN_X_SELL_PCT))
                    order = MarketOrder("SELL", sell_qty)
                    trade = ib.placeOrder(contract, order)
                    ib.sleep(3)

                    profit = (current - entry) * sell_qty * 100
                    log(f"10x TRIGGERED: {pos['strike']} — sold {sell_qty} @ {current}")
                    telegram.send(
                        f"🔥 *10x Rule Triggered!*\n\n"
                        f"Strike: ${pos['strike']}\n"
                        f"Entry: ${entry:.2f} → Now: ${current:.2f}\n"
                        f"Sold {sell_qty} contracts\n"
                        f"Locked ~${profit:,.0f} profit\n"
                        f"Remainder riding free."
                    )

                    pos["10x_triggered"] = True
                    pos["10x_sell_qty"] = sell_qty
                    pos["10x_price"] = current
                    save_all_positions(positions)

                ib.cancelMktData(contract)
            except Exception as e:
                log(f"10x monitor error for {pos.get('strike')}: {e}")

        time.sleep(300)  # Check every 5 minutes


def check_survival_breakers(ib):
    """Check drawdown breakers per Constitution v50.0"""
    summary = ib.accountSummary()
    net_liq = 0
    for item in summary:
        if item.tag == "NetLiquidation":
            net_liq = float(item.value)
            break

    # This is paper trading — real breaker logic would track per-system equity
    # For now, log the check
    log(f"Breaker check: Net Liq = ${net_liq:,.2f}")
    return net_liq


def save_position(pos):
    positions = load_positions()
    positions.append(pos)
    save_all_positions(positions)


def load_positions():
    if not os.path.exists(POSITIONS_FILE):
        return []
    with open(POSITIONS_FILE) as f:
        return json.load(f)


def save_all_positions(positions):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2)


def get_positions():
    """Get positions from IBKR for E.M. /positions command."""
    ib = connect()
    ipos = ib.positions()
    result = []
    for p in ipos:
        result.append({
            "symbol": p.contract.symbol,
            "qty": p.position,
            "avg_price": p.avgCost,
        })
    return result


def get_account_summary():
    """Get account summary for E.M. /pnl command."""
    ib = connect()
    summary = ib.accountSummary()
    result = {}
    for item in summary:
        if item.tag == "NetLiquidation":
            result["net_liq"] = float(item.value)
        elif item.tag == "TotalCashValue":
            result["cash"] = float(item.value)
        elif item.tag == "BuyingPower":
            result["buying_power"] = float(item.value)
    return result


if __name__ == "__main__":
    ib = connect()
    summary = get_account_summary()
    print(f"Net Liq: ${summary['net_liq']:,.2f}")
    print(f"Cash: ${summary['cash']:,.2f}")
    disconnect()
