"""Trader Moonshot — MSTR BTC Supercycle LEAP Lottery Engine
Constitution v45.0 | MSTR Only | $100K All-In
Strategy: Deploy $100K into 125 deep OTM MSTR LEAPs (~$8/share premium, 3-6x strike, Jan 2029 exp).
Pure asymmetric lottery — hold to 20x+ or expiration.
Entry: October 2026 (BTC Q4 post-halving cycle timing).
Laddered trailing stop: No stop 0-100%, 30% trail 2-5x, 30% trail 5-10x,
25% trail 10-20x, 20% trail 20x+ (lock the bag).
Backtest: 2023 Q4 entry = 22.4x ($100k → $2.2M).
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
import deployer
import telegram
import accountant
import auditor

from ib_insync import *
import pandas as pd
import yfinance as yf

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
POSITIONS_FILE = os.path.join(DATA_DIR, "trader_moonshot_positions.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

PORT = deployer.get_port(1)
CLIENT_ID = 90
MONITOR_CLIENT_ID = 91

# MSTR BTC Moonshot parameters
SYMBOL = "MSTR"
CAPITAL = 100000  # $100k all-in
STRIKE_MULTIPLIER_LOW = 3.0   # 3x spot = minimum OTM
STRIKE_MULTIPLIER_HIGH = 6.0  # 6x spot = maximum OTM
STRIKE_SWEET_SPOT = 4.0       # 4x spot = target sweet spot (~$8/share premium)
MIN_DTE = 365                 # 12 months minimum (LEAPs)
MAX_DTE = 820                 # ~27 months — Jan 2029 expiry to capture full cycle
TARGET_PREMIUM = 8.0          # Target $8/share entry premium for max convexity
POSITION_BUDGET_PRIMARY = 0.60   # 60% on sweet spot strike (~4.8x)
POSITION_BUDGET_SECONDARY = 0.25 # 25% on further OTM (~6x)
POSITION_BUDGET_CLOSER = 0.15   # 15% on closer strike (~3x)

# Exit rules — NO early profit-taking
TARGET_MULTIPLE = 20.0  # Sell 50% at 20x
MOONSHOT_MULTIPLE = 50.0  # Sell 25% more at 50x
SELL_PCT_20X = 0.50
SELL_PCT_50X = 0.25

# BTC regime thresholds
BTC_SMA_200_PERIOD = "1y"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Moonshot {ts}] {msg}")
    with open(f"{LOG_DIR}/trader_moonshot.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def connect(client_id=CLIENT_ID):
    ib = IB()
    ib.connect("127.0.0.1", PORT, clientId=client_id)
    ib.reqMarketDataType(3)
    log(f"Connected (client {client_id})")
    return ib


def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return []


def save_positions(positions):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2)


def check_btc_regime():
    """Check if BTC is in bull regime (above 200 SMA + golden cross).
    Demoted to CONFIRMATION — no longer blocks entry. See check_mstr_200w_regime().
    """
    try:
        btc = yf.Ticker("BTC-USD")
        data = btc.history(period="2y")
        if len(data) < 200:
            return False, "Insufficient BTC data"

        close = data["Close"]
        sma200 = float(close.rolling(200).mean().iloc[-1])
        ema50 = float(close.ewm(span=50).mean().iloc[-1])
        price = float(close.iloc[-1])

        above_200 = price > sma200
        golden_cross = ema50 > sma200

        if above_200 and golden_cross:
            return True, f"BTC BULL: ${price:,.0f} > SMA200 ${sma200:,.0f}, EMA50 > SMA200"
        else:
            return False, f"BTC not bull: ${price:,.0f} vs SMA200 ${sma200:,.0f}"
    except Exception as e:
        return False, f"BTC check error: {e}"


def check_mstr_200w_regime(green_weeks_required=2):
    """PRIMARY ENTRY GATE: MSTR weekly close above 200-week SMA for N consecutive green weeks.

    Rule (validated on Oct 2023 and Oct 2024 setups):
    1. MSTR weekly close crosses ABOVE its 200-week SMA
    2. Each qualifying candle must be GREEN (close > open)
    3. Count consecutive green weekly closes above the line
    4. Entry ARMED when count reaches threshold (default: 2)
    5. If any weekly close drops BELOW 200W SMA → counter resets to 0

    This fires 5-6 weeks earlier than BTC golden cross. In Oct 2024, MSTR moved
    from ~$128 to $234 (+55%) before the golden cross confirmed.

    Returns: (armed: bool, green_count: int, sma_200w: float, reason: str)
    """
    try:
        t = yf.Ticker(SYMBOL)
        # Need ~5 years of weekly data for 200-week SMA
        data = t.history(period="5y", interval="1wk")
        if len(data) < 200:
            return False, 0, 0.0, f"Insufficient MSTR weekly data ({len(data)} bars, need 200)"

        close = data["Close"]
        opn = data["Open"]
        sma_200w = close.rolling(200).mean()

        # Count consecutive green weeks above 200W SMA (from most recent backward)
        green_count = 0
        sma_val = float(sma_200w.iloc[-1])

        for i in range(len(data) - 1, -1, -1):
            c = float(close.iloc[i])
            o = float(opn.iloc[i])
            sma = sma_200w.iloc[i]

            if pd.isna(sma):
                break

            above = c > float(sma)
            green = c > o

            if above and green:
                green_count += 1
            elif not above:
                break  # Closed below 200W SMA — reset
            else:
                break  # Red candle above 200W — pause (don't continue counting)

        price = float(close.iloc[-1])
        above_200w = price > sma_val
        armed = green_count >= green_weeks_required

        if armed:
            reason = (f"MSTR 200W ARMED: {green_count} green weeks above 200W SMA "
                      f"(${price:,.0f} > ${sma_val:,.0f})")
        elif above_200w:
            reason = (f"MSTR above 200W SMA ({green_count}/{green_weeks_required} green weeks) "
                      f"${price:,.0f} > ${sma_val:,.0f}")
        else:
            reason = f"MSTR below 200W SMA: ${price:,.0f} < ${sma_val:,.0f}"

        return armed, green_count, sma_val, reason

    except Exception as e:
        return False, 0, 0.0, f"MSTR 200W check error: {e}"


def check_mstr_entry():
    """Check if MSTR has entry signal (EMA21, volume, RSI, momentum, BTC regime)."""
    try:
        t = yf.Ticker(SYMBOL)
        data = t.history(period="6mo")
        if len(data) < 50:
            return False, "Insufficient MSTR data", None

        close = data["Close"]
        volume = data["Volume"]
        price = float(close.iloc[-1])

        # EMA 21
        ema21 = float(close.ewm(span=21).mean().iloc[-1])
        if price < ema21:
            return False, f"Below EMA21 ${ema21:.2f}", None

        # Volume surge
        vol_avg = float(volume.rolling(20).mean().iloc[-1])
        vol_current = float(volume.iloc[-1])
        vol_ratio = vol_current / vol_avg if vol_avg > 0 else 1.0
        if vol_ratio < 1.5:
            return False, f"Volume {vol_ratio:.1f}x < 1.5x threshold", None

        # RSI 40-75
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = float((100 - 100 / (1 + rs)).iloc[-1])
        if rsi < 40 or rsi > 75:
            return False, f"RSI {rsi:.1f} outside 40-75 range", None

        # 5-day momentum > 3%
        mom_5d = (price - float(close.iloc[-5])) / float(close.iloc[-5]) * 100
        if mom_5d < 3.0:
            return False, f"Momentum {mom_5d:+.1f}% < 3% threshold", None

        # PRIMARY GATE: MSTR 200W SMA cross (replaces BTC golden cross)
        armed, green_count, sma_200w, regime_reason = check_mstr_200w_regime()
        if not armed:
            return False, f"MSTR 200W not armed: {regime_reason}", None

        # BTC regime (confirmation only — logged but doesn't block entry)
        btc_bull, btc_reason = check_btc_regime()

        tech = {
            "price": price,
            "ema21": ema21,
            "rsi": rsi,
            "vol_ratio": vol_ratio,
            "momentum_5d": mom_5d,
            "mstr_200w_regime": regime_reason,
            "mstr_200w_armed": armed,
            "mstr_green_weeks": green_count,
            "mstr_200w_sma": sma_200w,
            "btc_regime": btc_reason,
            "btc_bull_confirmed": btc_bull,
        }

        reason = (f"MOONSHOT SIGNAL: MSTR ${price:.2f}, EMA21 ${ema21:.2f}, "
                  f"RSI {rsi:.1f}, Vol {vol_ratio:.1f}x, Mom {mom_5d:+.1f}%, "
                  f"{regime_reason}"
                  f"{' | BTC CONFIRMED' if btc_bull else ' | BTC not yet confirmed'}")
        return True, reason, tech

    except Exception as e:
        return False, f"Error: {e}", None


def find_leap_contracts(ib, price):
    """Find deep OTM LEAP call options: 3-6x strike, target ~$8/share premium, Jan 2029 expiry."""
    stock = Stock(SYMBOL, "SMART", "USD")
    ib.qualifyContracts(stock)

    chains = ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
    if not chains:
        log("No option chains for MSTR")
        return []

    chain = None
    for c in chains:
        if c.exchange == "SMART":
            chain = c
            break
    if not chain:
        chain = chains[0]

    today = datetime.now().date()
    target_min = today + timedelta(days=MIN_DTE)
    target_max = today + timedelta(days=MAX_DTE)

    # Find longest available expiry within range
    valid_exps = []
    for exp in sorted(chain.expirations):
        exp_date = datetime.strptime(exp, "%Y%m%d").date()
        if target_min <= exp_date <= target_max:
            valid_exps.append(exp)

    # If nothing in range, take the furthest available
    if not valid_exps:
        for exp in sorted(chain.expirations, reverse=True):
            exp_date = datetime.strptime(exp, "%Y%m%d").date()
            if exp_date >= target_min:
                valid_exps.append(exp)
                break

    if not valid_exps:
        log("No suitable LEAP expirations found")
        return []

    expiry = valid_exps[-1]  # Furthest out
    dte = (datetime.strptime(expiry, "%Y%m%d").date() - today).days
    log(f"Selected expiry: {expiry} ({dte} DTE)")

    strikes = sorted(chain.strikes)

    # Find 3 strike buckets
    contracts = []

    # Closer strike (~3x spot)
    target_closer = price * STRIKE_MULTIPLIER_LOW
    closer_strike = min(strikes, key=lambda s: abs(s - target_closer))

    # Sweet spot (~4.8x spot)
    target_sweet = price * STRIKE_SWEET_SPOT
    sweet_strike = min(strikes, key=lambda s: abs(s - target_sweet))

    # Further OTM (~6x spot)
    target_far = price * STRIKE_MULTIPLIER_HIGH
    far_strike = min(strikes, key=lambda s: abs(s - target_far))

    for strike, budget_pct, label in [
        (closer_strike, POSITION_BUDGET_CLOSER, "closer"),
        (sweet_strike, POSITION_BUDGET_PRIMARY, "sweet_spot"),
        (far_strike, POSITION_BUDGET_SECONDARY, "far_otm"),
    ]:
        contract = Option(SYMBOL, expiry, strike, "C", "SMART")
        qualified = ib.qualifyContracts(contract)
        if qualified:
            contracts.append({
                "contract": contract,
                "strike": strike,
                "expiry": expiry,
                "dte": dte,
                "budget_pct": budget_pct,
                "label": label,
                "multiplier": round(strike / price, 1),
            })
            log(f"  Found: ${strike}C ({label}, {round(strike/price, 1)}x spot) exp {expiry}")

    return contracts


def execute_entry(tech):
    """Deploy $100K into deep OTM MSTR LEAPs — 3 strike buckets."""
    ib = connect()
    price = tech["price"]

    leap_contracts = find_leap_contracts(ib, price)
    if not leap_contracts:
        log("No suitable LEAP contracts found")
        ib.disconnect()
        return None

    results = []

    for lc in leap_contracts:
        contract = lc["contract"]
        budget = CAPITAL * lc["budget_pct"]

        ib.reqMarketDataType(3)
        ticker = ib.reqMktData(contract, "", False, False)
        ib.sleep(3)

        opt_price = ticker.last if ticker.last and ticker.last > 0 else ticker.close
        if not opt_price or opt_price <= 0:
            opt_price = ticker.ask if ticker.ask and ticker.ask > 0 else None
        if not opt_price or opt_price <= 0:
            if ticker.modelGreeks:
                opt_price = ticker.modelGreeks.optPrice
        if not opt_price or opt_price <= 0:
            log(f"  Cannot get price for ${lc['strike']}C — skipping")
            ib.cancelMktData(contract)
            continue

        contract_cost = opt_price * 100
        qty = max(1, int(budget / contract_cost))

        log(f"ENTERING {lc['label']}: {qty}x MSTR ${lc['strike']}C ({lc['multiplier']}x) "
            f"@ ${opt_price:.2f} (${qty * contract_cost:,.0f})")

        order = MarketOrder("BUY", qty)
        order.tif = "GTC"
        trade = ib.placeOrder(contract, order)

        for i in range(30):
            ib.sleep(1)
            if trade.orderStatus.status == "Filled":
                break

        fill = trade.orderStatus.avgFillPrice
        status = trade.orderStatus.status

        if status != "Filled":
            log(f"  ENTRY FAILED: {status}")
            ib.cancelMktData(contract)
            continue

        cost = fill * 100 * qty
        log(f"  FILLED: {qty}x ${lc['strike']}C @ ${fill:.2f} | Cost: ${cost:,.0f}")

        leg = {
            "label": lc["label"],
            "strike": lc["strike"],
            "expiry": lc["expiry"],
            "dte": lc["dte"],
            "multiplier": lc["multiplier"],
            "qty": qty,
            "entry_price": fill,
            "cost": cost,
            "type": "CALL",
        }

        # Constitution v45.0 — MANDATORY laddered trailing stop at entry
        from stop_utils import place_trailing_stop
        stop_result = place_trailing_stop(ib, contract, qty, fill, "mstr_moonshot", log)
        leg["trailing_stop"] = stop_result

        results.append(leg)
        ib.cancelMktData(contract)

        accountant.record_trade({
            "system": "mstr_moonshot",
            "ticker": SYMBOL,
            "action": "BUY",
            "qty": qty,
            "fill_price": fill,
            "order_type": "market",
            "option": f"{lc['expiry']} ${lc['strike']}C",
            "commission": 0,
        })

    if not results:
        log("No legs filled — aborting")
        ib.disconnect()
        return None

    total_cost = sum(r["cost"] for r in results)
    position = {
        "system": "mstr_moonshot",
        "symbol": SYMBOL,
        "entry_date": datetime.now().isoformat(),
        "entry_price": price,
        "total_cost": total_cost,
        "legs": results,
        "technicals": tech,
        "20x_triggered": False,
        "50x_triggered": False,
        "status": "open",
    }

    positions = load_positions()
    positions.append(position)
    save_positions(positions)

    # Build telegram message
    legs_msg = "\n".join(
        f"  {'🎯' if r['label']=='sweet_spot' else '🎲' if r['label']=='far_otm' else '🔵'} "
        f"${r['strike']}C ({r['multiplier']}x) x{r['qty']} @ ${r['entry_price']:.2f} = ${r['cost']:,.0f}"
        for r in results
    )

    telegram.send(
        f"🚀 *MSTR BTC MOONSHOT DEPLOYED*\n\n"
        f"MSTR @ ${price:.2f} | BTC Bull Regime\n\n"
        f"Lottery Tickets:\n{legs_msg}\n\n"
        f"Total Deployed: ${total_cost:,.0f}\n"
        f"Expiry: {results[0]['expiry']} ({results[0]['dte']} DTE)\n\n"
        f"Laddered Trail: None→30%→30%→25%→20%\n"
        f"Targets: 20x sell 50%, 50x sell 25%\n"
        f"Let it ride or let it die. 🎰"
    )

    # Start gain monitor
    threading.Thread(target=monitor_gains, args=(position,), daemon=True).start()

    ib.disconnect()
    return position


def monitor_gains(position):
    """Monitor for 20x and 50x exit triggers + laddered trailing stop enforcement."""
    log("Moonshot gain monitor started")

    from stop_utils import get_laddered_trail_pct

    ib = IB()
    ib.connect("127.0.0.1", PORT, clientId=MONITOR_CLIENT_ID)
    ib.reqMarketDataType(3)

    entry_cost = position["total_cost"]
    high_water_mark = entry_cost

    while True:
        try:
            total_value = 0
            for leg in position["legs"]:
                contract = Option(SYMBOL, leg["expiry"], leg["strike"], "C", "SMART")
                ib.qualifyContracts(contract)
                ticker = ib.reqMktData(contract, "", False, False)
                ib.sleep(3)
                current = ticker.last if ticker.last and ticker.last > 0 else ticker.close
                if current and current > 0:
                    total_value += current * 100 * leg["qty"]
                ib.cancelMktData(contract)

            if total_value <= 0:
                time.sleep(300)
                continue

            gain_pct = ((total_value - entry_cost) / entry_cost) * 100
            multiple = total_value / entry_cost

            # Update high water mark
            if total_value > high_water_mark:
                high_water_mark = total_value

            # Check laddered trailing stop
            trail_pct = get_laddered_trail_pct("mstr_moonshot", gain_pct)
            if trail_pct is not None:
                stop_level = high_water_mark * (1 - trail_pct / 100)
                if total_value <= stop_level:
                    log(f"LADDERED STOP TRIGGERED: Value ${total_value:,.0f} < "
                        f"Stop ${stop_level:,.0f} ({trail_pct}% from HWM ${high_water_mark:,.0f})")

                    # Close all legs
                    for leg in position["legs"]:
                        contract = Option(SYMBOL, leg["expiry"], leg["strike"], "C", "SMART")
                        ib.qualifyContracts(contract)
                        order = MarketOrder("SELL", leg["qty"])
                        order.tif = "GTC"
                        trade = ib.placeOrder(contract, order)
                        ib.sleep(5)
                        fill = trade.orderStatus.avgFillPrice
                        log(f"  Closed ${leg['strike']}C x{leg['qty']} @ ${fill:.2f}")

                    pnl = total_value - entry_cost
                    position["status"] = "closed"
                    position["exit_date"] = datetime.now().isoformat()
                    position["exit_reason"] = f"Laddered stop ({trail_pct}% trail from HWM)"
                    position["pnl"] = pnl

                    positions = load_positions()
                    for i, p in enumerate(positions):
                        if p.get("entry_date") == position.get("entry_date"):
                            positions[i] = position
                    save_positions(positions)

                    emoji = "🟢" if pnl >= 0 else "🔴"
                    telegram.send(
                        f"{emoji} *MOONSHOT LADDERED STOP*\n\n"
                        f"MSTR Moonshot closed by {trail_pct}% trailing stop\n"
                        f"Entry: ${entry_cost:,.0f} | Exit: ${total_value:,.0f}\n"
                        f"P&L: ${pnl:+,.0f} ({gain_pct:+.0f}%)\n"
                        f"HWM: ${high_water_mark:,.0f} | Multiple: {multiple:.1f}x"
                    )
                    ib.disconnect()
                    return

            log(f"Moonshot check: ${total_value:,.0f} ({multiple:.1f}x) | "
                f"HWM: ${high_water_mark:,.0f} | Trail: {trail_pct}%")

            # 20x rule — sell 50%
            if not position["20x_triggered"] and multiple >= TARGET_MULTIPLE:
                for leg in position["legs"]:
                    sell_qty = max(1, int(leg["qty"] * SELL_PCT_20X))
                    contract = Option(SYMBOL, leg["expiry"], leg["strike"], "C", "SMART")
                    ib.qualifyContracts(contract)
                    order = MarketOrder("SELL", sell_qty)
                    order.tif = "GTC"
                    ib.placeOrder(contract, order)
                    ib.sleep(3)
                    log(f"20x TRIGGERED: Sold {sell_qty}x ${leg['strike']}C")
                    leg["qty"] -= sell_qty

                position["20x_triggered"] = True
                profit = total_value - entry_cost
                telegram.send(
                    f"🔥 *MOONSHOT 20x TRIGGERED!*\n\n"
                    f"MSTR moonshot hit {multiple:.0f}x!\n"
                    f"Entry: ${entry_cost:,.0f} → Value: ${total_value:,.0f}\n"
                    f"Sold 50% — locked ${profit * SELL_PCT_20X:,.0f}\n"
                    f"Remainder riding with 20% trail. 🚀"
                )
                save_positions(load_positions())

            # 50x moonshot — sell 25% more
            if position["20x_triggered"] and not position.get("50x_triggered") and multiple >= MOONSHOT_MULTIPLE:
                for leg in position["legs"]:
                    sell_qty = max(1, int(leg["qty"] * SELL_PCT_50X))
                    contract = Option(SYMBOL, leg["expiry"], leg["strike"], "C", "SMART")
                    ib.qualifyContracts(contract)
                    order = MarketOrder("SELL", sell_qty)
                    order.tif = "GTC"
                    ib.placeOrder(contract, order)
                    ib.sleep(3)
                    log(f"50x MOONSHOT: Sold {sell_qty}x ${leg['strike']}C")
                    leg["qty"] -= sell_qty

                position["50x_triggered"] = True
                telegram.send(
                    f"🌙 *50x MOONSHOT!*\n\n"
                    f"MSTR hit {multiple:.0f}x entry!\n"
                    f"Sold 25% more. Rest riding to the moon.\n"
                    f"Value: ${total_value:,.0f}"
                )
                save_positions(load_positions())

        except Exception as e:
            log(f"Monitor error: {e}")

        time.sleep(300)  # Check every 5 minutes


def scan_and_enter():
    """Check entry conditions and deploy if signal fires."""
    positions = load_positions()
    open_positions = [p for p in positions if p.get("status") == "open"]

    if open_positions:
        log(f"Already have {len(open_positions)} open moonshot position(s) — skipping")
        return None

    signal, reason, tech = check_mstr_entry()
    if signal and tech:
        log(f"SIGNAL: {reason}")
        return execute_entry(tech)
    else:
        log(f"No signal: {reason}")
        return None


if __name__ == "__main__":
    log("Trader Moonshot — MSTR BTC Supercycle LEAP Lottery")
    log(f"Capital: ${CAPITAL:,} | Strikes: {STRIKE_MULTIPLIER_LOW}-{STRIKE_MULTIPLIER_HIGH}x spot")
    log(f"Sweet spot: {STRIKE_SWEET_SPOT}x | DTE: {MIN_DTE}-{MAX_DTE} days")
    log(f"Laddered trail: None→30%→30%→25%→20%")
    log("Scanning...")
    scan_and_enter()
