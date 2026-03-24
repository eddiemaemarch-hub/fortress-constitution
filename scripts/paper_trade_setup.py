#!/usr/bin/env python3
"""IBKR Paper Trading Setup — Rudy v2.2 Production
Connects to TWS paper trading, verifies account, tests SELL permissions,
and configures the v2.2 production parameters.

Usage: python3 scripts/paper_trade_setup.py
Requires: IBKR TWS running with API enabled on port 7496 (paper)
"""
import os
import sys
import json
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "paper_setup.log")
CONFIG_FILE = os.path.join(DATA_DIR, "v22_production_config.json")

# v2.2 Production Configuration
V22_CONFIG = {
    "version": "2.2",
    "trade_resolution": "daily",
    "leap_multiplier_base": 10.0,
    "premium_cap": 1.5,
    "panic_floor_enabled": True,
    "panic_floor_pct": -25.0,
    "slippage_stock_pct": 0.005,
    "sma_period": 200,
    "stoch_rsi_threshold": 70,
    "initial_floor_pct": 30,
    "scale_in": "50/50",
    "max_entries_per_cycle": 1,
    "euphoria_sell_premium": 3.5,
    "risk_capital_pct": 25,
    "target_capital": 130000,
    "broker_mode": "paper",
    "broker_port": 7496,
    "qc_backtest_result": "+31.2% net (Daily, 10x LEAP, 0.5% slippage, panic floor ON)",
    "trail_tiers": [
        {"min_gain_pct": 0, "trail_pct": None, "label": "No stop"},
        {"min_gain_pct": 200, "trail_pct": 30, "label": "3x: 30% trail"},
        {"min_gain_pct": 400, "trail_pct": 25, "label": "5x: 25% trail + sell 25%"},
        {"min_gain_pct": 900, "trail_pct": 20, "label": "10x: 20% trail + sell 25%"},
        {"min_gain_pct": 1900, "trail_pct": 15, "label": "20x: 15% trail + sell 25%"},
        {"min_gain_pct": 4900, "trail_pct": 10, "label": "50x: 10% trail + sell final 25%"},
    ],
}


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def send_telegram(msg):
    """Send Telegram alert."""
    try:
        import telegram
        telegram.send(msg)
    except Exception:
        pass


def setup():
    log("=" * 60)
    log("IBKR PAPER TRADING SETUP — Rudy v2.2 Production")
    log("=" * 60)

    # Step 1: Save v2.2 config
    log("\n📋 Step 1: Saving v2.2 production config...")
    V22_CONFIG["setup_time"] = datetime.now().isoformat()
    with open(CONFIG_FILE, "w") as f:
        json.dump(V22_CONFIG, f, indent=2)
    log(f"  ✅ Config saved to {CONFIG_FILE}")
    for key, val in V22_CONFIG.items():
        if key not in ("trail_tiers", "setup_time"):
            log(f"  • {key}: {val}")

    # Step 2: Connect to IBKR Paper
    log("\n🔌 Step 2: Connecting to IBKR TWS Paper Trading...")
    try:
        from ibkr_utils import connect_with_retry
    except ImportError:
        log("  ❌ Cannot import ibkr_utils — make sure ib_insync is installed")
        log("  Install: pip3 install ib_insync")
        return False

    ib = connect_with_retry(
        host="127.0.0.1",
        port=7496,  # Paper trading
        client_id=10,  # Use separate client ID for setup
        max_retries=3,
        log_func=log
    )

    if ib is None:
        log("  ❌ FAILED to connect to IBKR TWS")
        log("  Make sure TWS is running with:")
        log("    • API enabled (Edit → Global Config → API → Settings)")
        log("    • Socket port 7496 (paper trading)")
        log("    • 'Allow connections from localhost' checked")
        send_telegram("*IBKR PAPER SETUP FAILED*\nCannot connect to TWS on port 7496.\nCheck TWS is running with API enabled.")
        return False

    log("  ✅ Connected to IBKR TWS Paper Trading")

    # Step 3: Verify account
    log("\n💰 Step 3: Verifying account...")
    try:
        account_values = ib.accountValues()
        nlv = None
        cash = None
        for av in account_values:
            if av.tag == "NetLiquidation" and av.currency == "USD":
                nlv = float(av.value)
            if av.tag == "TotalCashValue" and av.currency == "USD":
                cash = float(av.value)

        if nlv:
            log(f"  Net Liquidation Value: ${nlv:,.2f}")
        if cash:
            log(f"  Total Cash: ${cash:,.2f}")

        if nlv and nlv >= 100000:
            log(f"  ✅ Account has ${nlv:,.0f} — sufficient for $130k target")
        elif nlv:
            log(f"  ⚠️  Account has ${nlv:,.0f} — target is $130k. Reset paper account if needed.")
        else:
            log("  ⚠️  Could not read Net Liquidation Value")
    except Exception as e:
        log(f"  ⚠️  Account read error: {e}")

    # Step 4: Check existing positions
    log("\n📊 Step 4: Checking existing positions...")
    try:
        positions = ib.positions()
        if positions:
            for pos in positions:
                log(f"  • {pos.contract.symbol} {pos.contract.secType}: {pos.position} shares @ avg ${pos.avgCost:.2f}")
        else:
            log("  No open positions (clean slate)")
    except Exception as e:
        log(f"  ⚠️  Position read error: {e}")

    # Step 5: SELL Permission Test
    log("\n🧪 Step 5: SELL Permission Test...")
    log("  Testing if paper account can place SELL orders...")
    try:
        from ib_insync import Stock, MarketOrder

        # First, buy 1 share of MSTR to test
        mstr = Stock("MSTR", "SMART", "USD")
        ib.qualifyContracts(mstr)

        # Try a limit sell at a very high price (won't fill, just tests permissions)
        from ib_insync import LimitOrder
        test_order = LimitOrder("SELL", 1, 99999.99)
        test_order.tif = "DAY"

        log("  Placing test SELL order (MSTR, 1 share @ $99,999.99 limit — won't fill)...")
        trade = ib.placeOrder(mstr, test_order)
        ib.sleep(3)

        status = trade.orderStatus.status
        log(f"  Order status: {status}")

        if status in ("Submitted", "PreSubmitted", "Filled"):
            log("  ✅ SELL PERMISSION TEST PASSED — paper account can sell")
            # Cancel the test order
            ib.cancelOrder(trade.order)
            ib.sleep(1)
            log("  ✅ Test order cancelled")
        elif status in ("Cancelled", "Inactive", "ApiCancelled"):
            log(f"  ❌ SELL PERMISSION TEST FAILED — status: {status}")
            log("  You may need to enable 'Sell Short' in TWS paper account settings")
        else:
            log(f"  ⚠️  Unexpected status: {status} — check TWS")
            # Cancel anyway
            try:
                ib.cancelOrder(trade.order)
            except:
                pass

    except Exception as e:
        log(f"  ❌ SELL test error: {e}")
        log("  This may be expected if no MSTR position exists in paper account")

    # Step 6: Test MSTR data feed
    log("\n📈 Step 6: Testing MSTR market data...")
    try:
        mstr = Stock("MSTR", "SMART", "USD")
        ib.qualifyContracts(mstr)
        ib.reqMarketDataType(3)  # Delayed data
        ticker = ib.reqMktData(mstr)
        ib.sleep(3)

        if ticker.last and ticker.last > 0:
            log(f"  MSTR Last: ${ticker.last:.2f}")
        elif ticker.close and ticker.close > 0:
            log(f"  MSTR Close: ${ticker.close:.2f}")
        else:
            log(f"  MSTR delayed data: bid=${ticker.bid}, ask=${ticker.ask}")

        ib.cancelMktData(mstr)
    except Exception as e:
        log(f"  ⚠️  Market data error: {e}")

    # Step 7: Test LEAP option chain
    log("\n🎯 Step 7: Checking MSTR LEAP option chain...")
    try:
        chains = ib.reqSecDefOptParams(mstr.symbol, "", mstr.secType, mstr.conId)
        if chains:
            for chain in chains:
                if chain.exchange == "SMART":
                    expirations = sorted(chain.expirations)
                    # Find LEAPs (>12 months out)
                    leaps = [exp for exp in expirations if exp >= "20270301"]
                    if leaps:
                        log(f"  Available LEAP expirations: {', '.join(leaps[:5])}")
                        log(f"  Strike range: {min(chain.strikes):.0f} - {max(chain.strikes):.0f}")
                        log(f"  Total strikes: {len(chain.strikes)}")
                    else:
                        log(f"  No LEAPs >12mo found. Nearest expirations: {', '.join(expirations[:5])}")
                    break
        else:
            log("  ⚠️  No option chains returned")
    except Exception as e:
        log(f"  ⚠️  Option chain error: {e}")

    # Disconnect
    log("\n🔌 Disconnecting...")
    ib.disconnect()
    log("  ✅ Disconnected from IBKR TWS")

    # Summary
    log("\n" + "=" * 60)
    log("SETUP COMPLETE — v2.2 Production Config")
    log("=" * 60)
    log(f"Config file: {CONFIG_FILE}")
    log(f"Log file: {LOG_FILE}")
    log("")
    log("NEXT STEPS:")
    log("  1. Load Pine Script v2.2 on TradingView (Daily MSTR chart)")
    log("  2. Set alerts per ~/rudy/docs/tradingview_alert_setup.txt")
    log("  3. Start paper_monitor.py for automated signal watching")
    log("  4. Wait for 200W SMA dip+reclaim signal")
    log("  5. On signal: manually review, then approve LEAP entry")
    log("")

    send_telegram(
        "*IBKR PAPER SETUP COMPLETE*\n\n"
        "v2.2 Production Config Loaded:\n"
        f"• LEAP Mult: {V22_CONFIG['leap_multiplier_base']}x\n"
        f"• Premium Cap: {V22_CONFIG['premium_cap']}x\n"
        f"• Panic Floor: {V22_CONFIG['panic_floor_pct']}%\n"
        f"• Resolution: {V22_CONFIG['trade_resolution']}\n"
        f"• Target Capital: ${V22_CONFIG['target_capital']:,}\n\n"
        "Waiting for 200W SMA dip+reclaim signal."
    )

    return True


if __name__ == "__main__":
    try:
        setup()
    except Exception as e:
        log(f"FATAL ERROR: {e}")
        import traceback
        log(traceback.format_exc())
        send_telegram(f"*IBKR PAPER SETUP FATAL ERROR*\n{e}")
