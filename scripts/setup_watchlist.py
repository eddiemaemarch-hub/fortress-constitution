"""Setup TWS Watchlist — Qualifies all Rudy universe contracts in TWS.
Run this once with TWS open to populate recent symbols and verify data access.
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))
from ib_insync import *

# All tickers across all systems
SYSTEM1 = ["MSTR", "IBIT"]
SYSTEM2_MOMENTUM = ["NVDA", "TSLA", "AMD", "META", "AVGO", "PLTR", "NFLX", "AMZN"]
ENERGY = ["CCJ", "UEC", "LEU", "VST", "CEG", "XOM", "CVX", "OXY", "DVN", "FANG"]
CRYPTO_RELATED = ["COIN", "MARA", "RIOT"]
SQUEEZE = ["GME", "AMC", "SOFI", "RIVN", "LCID"]

ALL_TICKERS = list(dict.fromkeys(
    SYSTEM1 + SYSTEM2_MOMENTUM + ENERGY + CRYPTO_RELATED + SQUEEZE
))


def setup(port=7496, client_id=99):
    ib = IB()
    ib.connect("127.0.0.1", port, clientId=client_id)
    print(f"Connected to TWS on port {port}")

    qualified = []
    failed = []

    for symbol in ALL_TICKERS:
        try:
            contract = Stock(symbol, "SMART", "USD")
            ib.qualifyContracts(contract)
            ticker = ib.reqMktData(contract)
            ib.sleep(1)
            price = ticker.marketPrice()
            status = f"${price:.2f}" if price and price > 0 else "delayed/no data"
            print(f"  ✓ {symbol:6s} — {status}")
            qualified.append(symbol)
        except Exception as e:
            print(f"  ✗ {symbol:6s} — {e}")
            failed.append(symbol)

    print(f"\nQualified: {len(qualified)}/{len(ALL_TICKERS)}")
    if failed:
        print(f"Failed: {', '.join(failed)}")

    print("\nAll contracts registered in TWS. Check your 'Recent' symbols in Workstation.")
    print("To create watchlists manually:")
    print(f"  System 1: {', '.join(SYSTEM1)}")
    print(f"  System 2: {', '.join(SYSTEM2_MOMENTUM)}")
    print(f"  Energy:   {', '.join(ENERGY)}")

    ib.disconnect()


if __name__ == "__main__":
    setup()
