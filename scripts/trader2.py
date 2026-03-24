"""Trader2 — System 2 v4 Diagonal Spread Execution Engine
Constitution v50.0 | Conservative Diagonal Spreads
Structure: Buy LEAP call (high delta) + Sell short-dated call (OTM income)
Handles: diagonal entry, short leg rolling, pyramids, profit-taking, exits
$250 max risk per trade | Zero human input after approval.
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
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import telegram
import system2_v4

from ib_insync import *
import yfinance as yf

LOG_DIR = os.path.expanduser("~/rudy/logs")
os.makedirs(LOG_DIR, exist_ok=True)

_ib = None


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(f"{LOG_DIR}/trader2.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")
    print(f"[Trader2 {ts}] {msg}")


def connect(port=7496, client_id=20):
    global _ib
    if _ib and _ib.isConnected():
        return _ib
    _ib = IB()
    _ib.connect("127.0.0.1", port, clientId=client_id)
    _ib.reqMarketDataType(3)
    log(f"Connected to IBKR on port {port}")
    return _ib


def disconnect():
    global _ib
    if _ib:
        _ib.disconnect()
        _ib = None


def get_price_yf(symbol):
    """Get current price from Yahoo Finance."""
    t = yf.Ticker(symbol)
    data = t.history(period="1d")
    if not data.empty:
        return float(data["Close"].iloc[-1])
    return float(t.info.get("regularMarketPrice", 0))


def get_option_price(ib, contract):
    """Get option ask price from IBKR."""
    ib.qualifyContracts(contract)
    ticker = ib.reqMktData(contract)
    ib.sleep(3)
    ask = ticker.ask if ticker.ask == ticker.ask and ticker.ask > 0 else None
    bid = ticker.bid if ticker.bid == ticker.bid and ticker.bid > 0 else None
    last = ticker.last if ticker.last == ticker.last and ticker.last > 0 else None
    ib.cancelMktData(contract)
    return ask, bid, last


def find_option_chain(ib, symbol):
    """Get option chain info from IBKR."""
    stock = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(stock)
    chains = ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
    if not chains:
        return None
    return chains[0]


def select_leap_expiry(chain):
    """Select LEAP expiry: 6-18 months out, prefer furthest."""
    today = datetime.now().date()
    valid = []
    for e in sorted(chain.expirations):
        dte = (datetime.strptime(e, "%Y%m%d").date() - today).days
        if system2_v4.LEAP_MIN_DTE <= dte <= system2_v4.LEAP_MAX_DTE:
            valid.append((e, dte))
    if not valid:
        return None, 0
    # Pick furthest out for maximum theta protection
    expiry, dte = valid[-1]
    return expiry, dte


def select_short_expiry(chain):
    """Select short call expiry: 3-8 weeks out."""
    today = datetime.now().date()
    valid = []
    for e in sorted(chain.expirations):
        dte = (datetime.strptime(e, "%Y%m%d").date() - today).days
        if system2_v4.SHORT_MIN_DTE <= dte <= system2_v4.SHORT_MAX_DTE:
            valid.append((e, dte))
    if not valid:
        return None, 0
    # Pick ~30-45 DTE sweet spot
    target = 35
    best = min(valid, key=lambda x: abs(x[1] - target))
    return best[0], best[1]


def select_leap_strike(chain, price):
    """Select LEAP strike: ~15% ITM (high delta ~0.70)."""
    strikes = sorted(chain.strikes)
    target = price * 0.85  # 15% ITM
    # Find closest strike at or below target
    itm_strikes = [s for s in strikes if s <= target]
    if itm_strikes:
        return itm_strikes[-1]  # Highest ITM strike at or below target
    # Fallback: ATM
    return min(strikes, key=lambda s: abs(s - price))


def select_short_strike(chain, price):
    """Select short call strike: ~10% OTM (low delta ~0.30)."""
    strikes = sorted(chain.strikes)
    target = price * 1.10  # 10% OTM
    otm_strikes = [s for s in strikes if s >= target]
    if otm_strikes:
        return otm_strikes[0]  # Lowest OTM strike at or above target
    return max(strikes)


def execute_entry(proposal):
    """Execute approved System 2 v4 diagonal spread via IBKR."""
    ib = connect()
    symbol = proposal["ticker"]
    price = proposal["price"]

    log(f"EXECUTING System 2 v4 Diagonal: {symbol} @ ${price:.2f}")

    # Get live price
    live_price = get_price_yf(symbol)
    if live_price <= 0:
        live_price = price

    # Get option chain
    chain = find_option_chain(ib, symbol)
    if not chain:
        log("ERROR: No option chain found")
        telegram.send(f"❌ No option chain for {symbol}")
        return {"status": "error", "reason": "No option chain"}

    # Select expirations
    leap_expiry, leap_dte = select_leap_expiry(chain)
    short_expiry, short_dte = select_short_expiry(chain)

    if not leap_expiry:
        log("ERROR: No valid LEAP expiry found")
        telegram.send(f"❌ No LEAP expiry (6-18mo) for {symbol}")
        return {"status": "error", "reason": "No LEAP expiry"}

    if not short_expiry:
        log("ERROR: No valid short expiry found")
        telegram.send(f"❌ No short expiry (3-8wk) for {symbol}")
        return {"status": "error", "reason": "No short expiry"}

    # Select strikes
    leap_strike = select_leap_strike(chain, live_price)
    short_strike = select_short_strike(chain, live_price)

    # Ensure short strike > leap strike (proper diagonal)
    if short_strike <= leap_strike:
        short_strike = min(s for s in sorted(chain.strikes) if s > leap_strike)

    log(f"LEAP: ${leap_strike}C exp {leap_expiry} ({leap_dte} DTE)")
    log(f"SHORT: ${short_strike}C exp {short_expiry} ({short_dte} DTE)")

    # Get option prices
    leap_contract = Option(symbol, leap_expiry, leap_strike, "C", "SMART")
    short_contract = Option(symbol, short_expiry, short_strike, "C", "SMART")

    leap_ask, leap_bid, leap_last = get_option_price(ib, leap_contract)
    short_ask, short_bid, short_last = get_option_price(ib, short_contract)

    # Use best available prices
    leap_cost = leap_ask or leap_last or 5.00  # per share
    short_credit = short_bid or short_last or 1.00  # per share

    net_debit = (leap_cost - short_credit) * 100  # per contract

    log(f"LEAP ask: ${leap_cost:.2f} | SHORT bid: ${short_credit:.2f} | Net debit: ${net_debit:.0f}")

    # Size position: max risk $250 per trade, max 50% of capital
    max_contracts_by_risk = max(1, int(system2_v4.MAX_RISK_PER_TRADE / net_debit)) if net_debit > 0 else 1
    max_contracts_by_capital = max(1, int((system2_v4.CAPITAL * 0.50) / (leap_cost * 100)))
    qty = min(max_contracts_by_risk, max_contracts_by_capital)

    log(f"Quantity: {qty} contracts (risk: ${net_debit * qty:.0f})")

    # Execute: Buy LEAP call
    ib.qualifyContracts(leap_contract)
    leap_order = MarketOrder("BUY", qty)
    leap_trade = ib.placeOrder(leap_contract, leap_order)
    ib.sleep(5)

    leap_fill = leap_trade.orderStatus.avgFillPrice
    if not leap_fill or leap_fill != leap_fill:
        leap_fill = leap_cost

    # Execute: Sell short call
    ib.qualifyContracts(short_contract)
    short_order = MarketOrder("SELL", qty)
    short_trade = ib.placeOrder(short_contract, short_order)
    ib.sleep(5)

    short_fill = short_trade.orderStatus.avgFillPrice
    if not short_fill or short_fill != short_fill:
        short_fill = short_credit

    total_debit = (leap_fill - short_fill) * 100 * qty

    # Save position
    position = {
        "system": "system2_v4",
        "type": "diagonal",
        "symbol": symbol,
        "status": "open",
        "entry_date": datetime.now().isoformat(),
        "underlying_price": live_price,
        "leap": {
            "strike": leap_strike,
            "expiry": leap_expiry,
            "dte": leap_dte,
            "fill_price": leap_fill,
            "quantity": qty,
        },
        "short": {
            "strike": short_strike,
            "expiry": short_expiry,
            "dte": short_dte,
            "fill_price": short_fill,
            "quantity": qty,
        },
        "net_debit": total_debit,
        "leap_entry_value": leap_fill,
        "leap_high_value": leap_fill,
        "pyramid_count": 0,
        "profit_taken": False,
        "short_rolls": 0,
        "total_premium_collected": short_fill * 100 * qty,
        "score": proposal.get("score", 0),
    }
    system2_v4.save_position(position)

    log(f"DIAGONAL FILLED: {symbol} | LEAP ${leap_strike}C x{qty} @ ${leap_fill:.2f} | "
        f"SHORT ${short_strike}C x{qty} @ ${short_fill:.2f} | Net debit: ${total_debit:,.0f}")

    telegram.send(
        f"💰 *System 2 v4 — Diagonal Executed*\n\n"
        f"*{symbol}* @ ${live_price:.2f}\n\n"
        f"📗 BUY {qty}x ${leap_strike}C {leap_expiry}\n"
        f"   ({leap_dte} DTE) @ ${leap_fill:.2f}\n\n"
        f"📕 SELL {qty}x ${short_strike}C {short_expiry}\n"
        f"   ({short_dte} DTE) @ ${short_fill:.2f}\n\n"
        f"Net debit: ${total_debit:,.0f}\n"
        f"Max risk: ${total_debit:,.0f}\n\n"
        f"Trader2 monitoring + rolling shorts monthly. 📈"
    )

    # Start position monitor
    threading.Thread(target=monitor_diagonal, args=(position,), daemon=True).start()

    return {
        "status": "executed",
        "symbol": symbol,
        "type": "diagonal",
        "qty": qty,
        "leap_fill": leap_fill,
        "short_fill": short_fill,
        "net_debit": total_debit,
    }


def monitor_diagonal(position):
    """Monitor a diagonal spread position.
    Handles: short leg rolling, pyramids, profit-taking, exits.
    """
    symbol = position["symbol"]
    log(f"Diagonal monitor started: {symbol}")

    ib = connect(client_id=21)

    while True:
        try:
            # Reload position
            positions = system2_v4.load_positions()
            pos = None
            for p in positions:
                if (p.get("symbol") == symbol and p.get("status") == "open"
                        and p.get("entry_date") == position.get("entry_date")):
                    pos = p
                    break

            if pos is None:
                log(f"Diagonal monitor: {symbol} position closed, stopping")
                break

            # Get underlying price
            underlying = get_price_yf(symbol)
            if underlying <= 0:
                time.sleep(60)
                continue

            # Get current LEAP value
            leap = pos["leap"]
            leap_contract = Option(symbol, leap["expiry"], leap["strike"], "C", "SMART")
            leap_ask, leap_bid, leap_last = get_option_price(ib, leap_contract)
            leap_current = leap_bid or leap_last or leap["fill_price"]

            # Get EMA50 for trend check
            tech = system2_v4.get_technicals(symbol)
            ema50 = tech["ema50"] if tech else underlying

            leap_entry = pos["leap_entry_value"]
            leap_gain = (leap_current - leap_entry) / leap_entry if leap_entry > 0 else 0

            # Update LEAP high watermark
            leap_high = pos.get("leap_high_value", leap_entry)
            if leap_current > leap_high:
                leap_high = leap_current
                pos["leap_high_value"] = leap_high

            leap_dd = (leap_high - leap_current) / leap_high if leap_high > 0 else 0
            pyramid_count = pos.get("pyramid_count", 0)
            profit_taken = pos.get("profit_taken", False)

            log(f"Diagonal {symbol}: Underlying ${underlying:.2f} | "
                f"LEAP ${leap_current:.2f} ({leap_gain:+.0%}) | "
                f"DD {leap_dd:.0%} | Pyramids {pyramid_count}")

            # === ROLL SHORT LEG ===
            short = pos["short"]
            short_expiry_date = datetime.strptime(short["expiry"], "%Y%m%d").date()
            days_to_expiry = (short_expiry_date - datetime.now().date()).days

            if days_to_expiry <= 5:
                # Roll: buy back short, sell new one
                log(f"ROLLING short leg: {days_to_expiry} DTE remaining")
                old_short = Option(symbol, short["expiry"], short["strike"], "C", "SMART")
                old_ask, old_bid, old_last = get_option_price(ib, old_short)
                buyback_cost = old_ask or old_last or 0.10

                # Buy back old short
                ib.qualifyContracts(old_short)
                buyback_order = MarketOrder("BUY", short["quantity"])
                ib.placeOrder(old_short, buyback_order)
                ib.sleep(5)

                # Find new short expiry and strike
                chain = find_option_chain(ib, symbol)
                if chain:
                    new_expiry, new_dte = select_short_expiry(chain)
                    new_strike = select_short_strike(chain, underlying)

                    if new_expiry and new_strike > leap["strike"]:
                        new_short = Option(symbol, new_expiry, new_strike, "C", "SMART")
                        new_ask, new_bid, new_last = get_option_price(ib, new_short)
                        new_credit = new_bid or new_last or 0.50

                        ib.qualifyContracts(new_short)
                        sell_order = MarketOrder("SELL", short["quantity"])
                        ib.placeOrder(new_short, sell_order)
                        ib.sleep(5)

                        roll_credit = (new_credit - buyback_cost) * 100 * short["quantity"]
                        pos["short"] = {
                            "strike": new_strike,
                            "expiry": new_expiry,
                            "dte": new_dte,
                            "fill_price": new_credit,
                            "quantity": short["quantity"],
                        }
                        pos["short_rolls"] = pos.get("short_rolls", 0) + 1
                        pos["total_premium_collected"] = pos.get("total_premium_collected", 0) + new_credit * 100 * short["quantity"]

                        log(f"ROLLED: ${short['strike']}C → ${new_strike}C {new_expiry} | Credit: ${roll_credit:,.0f}")
                        telegram.send(
                            f"🔄 *Short Leg Rolled — {symbol}*\n\n"
                            f"Closed: ${short['strike']}C {short['expiry']}\n"
                            f"Opened: ${new_strike}C {new_expiry} ({new_dte} DTE)\n"
                            f"Roll credit: ${roll_credit:,.0f}\n"
                            f"Total premium collected: ${pos['total_premium_collected']:,.0f}\n"
                            f"Rolls: #{pos['short_rolls']}"
                        )

            # === PYRAMID: +50% LEAP value, add 1 contract ===
            if leap_gain > system2_v4.PYRAMID_1_GAIN and pyramid_count == 0:
                chain = find_option_chain(ib, symbol)
                if chain:
                    new_leap = Option(symbol, leap["expiry"], leap["strike"], "C", "SMART")
                    ib.qualifyContracts(new_leap)
                    pyr_order = MarketOrder("BUY", 1)
                    ib.placeOrder(new_leap, pyr_order)
                    ib.sleep(5)

                    pos["leap"]["quantity"] = leap["quantity"] + 1
                    pos["pyramid_count"] = 1
                    system2_v4.save_position(pos)

                    log(f"PYRAMID 1: {symbol} +1 LEAP @ ${leap_current:.2f} | +{leap_gain:.0%}")
                    telegram.send(
                        f"📈 *Pyramid 1 — {symbol} Diagonal*\n\n"
                        f"LEAP up {leap_gain:.0%}!\n"
                        f"Added 1x ${leap['strike']}C {leap['expiry']}\n"
                        f"Total LEAPs: {pos['leap']['quantity']}"
                    )

            # === PYRAMID 2: +100% LEAP value ===
            elif leap_gain > system2_v4.PYRAMID_2_GAIN and pyramid_count == 1:
                new_leap = Option(symbol, leap["expiry"], leap["strike"], "C", "SMART")
                ib.qualifyContracts(new_leap)
                pyr_order = MarketOrder("BUY", 1)
                ib.placeOrder(new_leap, pyr_order)
                ib.sleep(5)

                pos["leap"]["quantity"] = leap["quantity"] + 1
                pos["pyramid_count"] = 2
                system2_v4.save_position(pos)

                log(f"PYRAMID 2: {symbol} +1 LEAP @ ${leap_current:.2f} | +{leap_gain:.0%}")
                telegram.send(
                    f"🔥 *Pyramid 2 — {symbol} Diagonal*\n\n"
                    f"LEAP doubled from entry!\n"
                    f"Added 1x ${leap['strike']}C\n"
                    f"Total LEAPs: {pos['leap']['quantity']}"
                )

            # === PROFIT TAKE: +150%, close 50% of LEAPs ===
            if leap_gain > system2_v4.PROFIT_TAKE_GAIN and not profit_taken:
                current_qty = pos["leap"]["quantity"]
                sell_qty = max(1, current_qty // 2)

                leap_sell = Option(symbol, leap["expiry"], leap["strike"], "C", "SMART")
                ib.qualifyContracts(leap_sell)
                sell_order = MarketOrder("SELL", sell_qty)
                ib.placeOrder(leap_sell, sell_order)
                ib.sleep(5)

                profit = (leap_current - leap_entry) * 100 * sell_qty
                pos["leap"]["quantity"] = current_qty - sell_qty
                pos["profit_taken"] = True
                system2_v4.save_position(pos)

                log(f"PROFIT TAKE: {symbol} -{sell_qty} LEAPs @ ${leap_current:.2f} | Locked ${profit:,.0f}")
                telegram.send(
                    f"💵 *Profit Take — {symbol} Diagonal*\n\n"
                    f"LEAP up {leap_gain:.0%}!\n"
                    f"Sold {sell_qty}x ${leap['strike']}C @ ${leap_current:.2f}\n"
                    f"Locked: ${profit:,.0f}\n"
                    f"Remaining {pos['leap']['quantity']} LEAPs riding."
                )

            # === EXIT CONDITIONS ===
            should_exit = False
            exit_reason = ""

            # 40% drawdown on LEAP from peak
            if leap_dd > system2_v4.TRAIL_DD_EXIT:
                should_exit = True
                exit_reason = f"LEAP trail stop: {leap_dd:.0%} drop from ${leap_high:.2f}"

            # LEAP lost 50%+ of entry value
            elif leap_gain < -system2_v4.MAX_LOSS_PCT:
                should_exit = True
                exit_reason = f"Max loss: LEAP down {leap_gain:.0%}"

            # Underlying broke below EMA50
            elif system2_v4.EMA50_EXIT and underlying < ema50 * 0.97:
                should_exit = True
                exit_reason = f"Underlying ${underlying:.2f} below EMA50 ${ema50:.2f}"

            if should_exit:
                # Close entire diagonal: sell LEAPs + buy back shorts
                leap_qty = pos["leap"]["quantity"]
                short_qty = pos["short"]["quantity"]

                if leap_qty > 0:
                    leap_close = Option(symbol, leap["expiry"], leap["strike"], "C", "SMART")
                    ib.qualifyContracts(leap_close)
                    ib.placeOrder(leap_close, MarketOrder("SELL", leap_qty))
                    ib.sleep(5)

                if short_qty > 0:
                    short_close = Option(symbol, pos["short"]["expiry"], pos["short"]["strike"], "C", "SMART")
                    ib.qualifyContracts(short_close)
                    ib.placeOrder(short_close, MarketOrder("BUY", short_qty))
                    ib.sleep(5)

                pnl = (leap_current - leap_entry) * 100 * leap_qty
                total_premium = pos.get("total_premium_collected", 0)

                pos["status"] = "closed"
                pos["exit_date"] = datetime.now().isoformat()
                pos["exit_leap_value"] = leap_current
                pos["pnl_leap"] = pnl
                pos["pnl_total"] = pnl + total_premium
                system2_v4.save_position(pos)

                log(f"DIAGONAL EXIT: {symbol} | LEAP PnL ${pnl:,.0f} | "
                    f"Premium collected: ${total_premium:,.0f} | "
                    f"Total PnL: ${pnl + total_premium:,.0f} | {exit_reason}")
                telegram.send(
                    f"🚪 *System 2 v4 — Diagonal Closed*\n\n"
                    f"{symbol}\n"
                    f"Reason: {exit_reason}\n\n"
                    f"LEAP PnL: ${pnl:,.0f}\n"
                    f"Premium collected: ${total_premium:,.0f}\n"
                    f"Rolls: {pos.get('short_rolls', 0)}\n"
                    f"*Total PnL: ${pnl + total_premium:,.0f}*"
                )
                break

            system2_v4.save_position(pos)

        except Exception as e:
            log(f"Diagonal monitor error {symbol}: {e}")

        time.sleep(300)  # Check every 5 minutes


def check_survival_breaker():
    """Check if System 2 has hit the $7,500 survival breaker."""
    ib = connect()
    positions = system2_v4.get_open_positions()
    total_value = 0

    for pos in positions:
        leap = pos.get("leap", {})
        leap_contract = Option(pos["symbol"], leap["expiry"], leap["strike"], "C", "SMART")
        ask, bid, last = get_option_price(ib, leap_contract)
        value = (bid or last or 0) * 100 * leap.get("quantity", 0)
        total_value += value

    if total_value > 0 and total_value < system2_v4.SURVIVAL_BREAKER:
        log(f"SURVIVAL BREAKER: ${total_value:,.0f} < ${system2_v4.SURVIVAL_BREAKER:,.0f}")
        telegram.send(
            f"🛑 *SURVIVAL BREAKER — System 2*\n\n"
            f"Portfolio value: ${total_value:,.0f}\n"
            f"Below ${system2_v4.SURVIVAL_BREAKER:,.0f} floor\n"
            f"ALL System 2 trading halted."
        )
        return True
    return False


def get_s2_positions():
    """Get System 2 diagonal positions for E.M. display."""
    positions = system2_v4.get_open_positions()
    result = []
    for pos in positions:
        leap = pos.get("leap", {})
        short = pos.get("short", {})
        underlying = get_price_yf(pos["symbol"])
        leap_entry = pos.get("leap_entry_value", 0)
        result.append({
            "symbol": pos["symbol"],
            "type": "diagonal",
            "leap": f"${leap.get('strike')}C x{leap.get('quantity')} ({leap.get('expiry')})",
            "short": f"${short.get('strike')}C x{short.get('quantity')} ({short.get('expiry')})",
            "underlying": underlying,
            "net_debit": pos.get("net_debit", 0),
            "premium_collected": pos.get("total_premium_collected", 0),
            "rolls": pos.get("short_rolls", 0),
            "pyramids": pos.get("pyramid_count", 0),
        })
    return result


def resume_monitors():
    """Resume monitors for any open diagonal positions (called on startup)."""
    positions = system2_v4.get_open_positions()
    for pos in positions:
        log(f"Resuming diagonal monitor for {pos['symbol']}")
        threading.Thread(target=monitor_diagonal, args=(pos,), daemon=True).start()
    if positions:
        log(f"Resumed {len(positions)} diagonal monitors")
    else:
        log("No open diagonal positions to monitor")


if __name__ == "__main__":
    print("Trader2 — System 2 v4 Diagonal Spread Engine")
    print(f"Capital: ${system2_v4.CAPITAL:,}")
    print(f"Max risk/trade: ${system2_v4.MAX_RISK_PER_TRADE}")
    print(f"Structure: Buy LEAP call + Sell short call (roll monthly)")
    print(f"Survival breaker: ${system2_v4.SURVIVAL_BREAKER:,}")
    print(f"Universe: {', '.join(system2_v4.UNIVERSE)}")
    print()
    resume_monitors()
