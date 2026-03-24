"""IBKR TWS API client for Rudy v2.0 — uses ib_insync"""
from ib_insync import *


def connect(port=7496, client_id=1):
    """Connect to TWS. 7496=paper, 7496=live."""
    ib = IB()
    ib.connect("127.0.0.1", port, clientId=client_id)
    print(f"Connected to IBKR on port {port}")
    print(f"Accounts: {ib.managedAccounts()}")
    return ib


def get_mstr_contract():
    return Stock("MSTR", "SMART", "USD")


def get_mstr_price(ib):
    contract = get_mstr_contract()
    ib.qualifyContracts(contract)
    ticker = ib.reqMktData(contract)
    ib.sleep(2)
    return ticker.marketPrice()


def get_option_chain(ib, symbol="MSTR"):
    contract = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(contract)
    chains = ib.reqSecDefOptParams(contract.symbol, "", contract.secType, contract.conId)
    return chains


def get_options(ib, symbol, expiry, strikes, right="C"):
    """Get option contracts for given strikes."""
    contracts = []
    for strike in strikes:
        c = Option(symbol, expiry, strike, right, "SMART")
        contracts.append(c)
    ib.qualifyContracts(*contracts)
    return contracts


def get_option_prices(ib, contracts):
    """Get market data for option contracts."""
    tickers = []
    for c in contracts:
        t = ib.reqMktData(c)
        tickers.append(t)
    ib.sleep(3)
    return [(t.contract.strike, t.bid, t.ask, t.last) for t in tickers]


def place_order(ib, contract, action, qty, order_type="MKT", limit_price=None):
    """Place an order. Returns trade object."""
    if order_type == "MKT":
        order = MarketOrder(action, qty)
    else:
        order = LimitOrder(action, qty, limit_price)
    trade = ib.placeOrder(contract, order)
    return trade


def get_positions(ib):
    return ib.positions()


def get_account_summary(ib):
    return ib.accountSummary()


def disconnect(ib):
    ib.disconnect()


if __name__ == "__main__":
    ib = connect()
    price = get_mstr_price(ib)
    print(f"MSTR: ${price}")
    disconnect(ib)
