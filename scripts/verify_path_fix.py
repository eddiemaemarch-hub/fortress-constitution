#!/usr/bin/env python3
"""Quick verification: does history seeding fix path dependency?

Re-runs the start-date sensitivity test with the seeded algo.
If all start dates converge to similar results → fix works.
"""
import os, sys, re, json, time
from datetime import datetime
from hashlib import sha256
from base64 import b64encode
import requests

QC_API_TOKEN = "a5e10d30d2c0f483c2c62a124375b2fcf4e0f907d54ab3ae863e7450e50b7688"
QC_USER_ID = "473242"
QC_BASE = "https://www.quantconnect.com/api/v2"
PROJECT_ID = 29065184

ALGO_PATH = os.path.expanduser("~/rudy/quantconnect/MSTRCycleLowLeap_v28plus.py")
DATA_DIR = os.path.expanduser("~/rudy/data")
RESULTS_FILE = os.path.join(DATA_DIR, "path_fix_results.json")


def _auth():
    ts = str(int(time.time()))
    h = sha256(f"{QC_API_TOKEN}:{ts}".encode()).hexdigest()
    a = b64encode(f"{QC_USER_ID}:{h}".encode()).decode()
    return {"Authorization": f"Basic {a}", "Timestamp": ts, "Content-Type": "application/json"}


def _post(ep, data=None):
    for attempt in range(3):
        try:
            r = requests.post(f"{QC_BASE}/{ep}", headers=_auth(), json=data or {}, timeout=60)
            if r.status_code == 429:
                time.sleep(10 * (2 ** attempt))
                continue
            return r.json()
        except Exception as e:
            if attempt < 2:
                time.sleep(10)
            else:
                raise
    return {"success": False}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def parse_stat(stats, key, default=0.0):
    val = stats.get(key, str(default))
    if isinstance(val, (int, float)):
        return float(val)
    val = val.replace("%", "").replace("$", "").replace(",", "").strip()
    try:
        return float(val)
    except:
        return default


def run_backtest(code, name):
    result = _post("files/update", {"projectId": PROJECT_ID, "name": "main.py", "content": code})
    if not result.get("success"):
        _post("files/create", {"projectId": PROJECT_ID, "name": "main.py", "content": code})

    cr = _post("compile/create", {"projectId": PROJECT_ID})
    cid = cr.get("compileId", "")
    state = cr.get("state", "")

    if state != "BuildSuccess":
        for i in range(40):
            time.sleep(3)
            check = _post("compile/read", {"projectId": PROJECT_ID, "compileId": cid})
            state = check.get("state", "")
            if state == "BuildSuccess":
                break
            if state == "BuildError":
                log(f"  BUILD ERROR: {check.get('errors', [])}")
                return None
    if state != "BuildSuccess":
        return None

    bt = _post("backtests/create", {"projectId": PROJECT_ID, "compileId": cid, "backtestName": name})
    btid = bt.get("backtest", {}).get("backtestId") or bt.get("backtestId", "")
    if not btid:
        return None

    for i in range(240):
        time.sleep(2)
        r = _post("backtests/read", {"projectId": PROJECT_ID, "backtestId": btid})
        b = r.get("backtest", r)
        if b.get("status") == "Completed" or (isinstance(b.get("progress", 0), (int, float)) and b.get("progress", 0) >= 1.0):
            time.sleep(2)
            r = _post("backtests/read", {"projectId": PROJECT_ID, "backtestId": btid})
            return r.get("backtest", r).get("statistics", {})
        if i % 15 == 0 and i > 0:
            log(f"  Progress: {b.get('progress', 0)}")
    return None


if __name__ == "__main__":
    log("PATH DEPENDENCY FIX VERIFICATION")
    log("=" * 60)

    with open(ALGO_PATH) as f:
        base_code = f.read()

    start_dates = [
        (2016, 1, 1, "2016 (original)"),
        (2017, 1, 1, "2017"),
        (2018, 1, 1, "2018"),
        (2019, 1, 1, "2019"),
        (2020, 1, 1, "2020 (BTC era start)"),
    ]

    results = []
    for y, m, d, desc in start_dates:
        log(f"\n  [Start: {y} — {desc}]...")

        patched = re.sub(
            r"self\.SetStartDate\(\d+,\s*\d+,\s*\d+\)",
            f"self.SetStartDate({y}, {m}, {d})",
            base_code,
        )

        stats = run_backtest(patched, f"PATHFIX-{y}")
        time.sleep(5)

        r = {"start_year": y, "description": desc}
        if stats:
            r["net"] = parse_stat(stats, "Net Profit")
            r["dd"] = parse_stat(stats, "Drawdown")
            r["sharpe"] = parse_stat(stats, "Sharpe Ratio")
            r["orders"] = int(parse_stat(stats, "Total Orders"))
            log(f"    Net={r['net']:+.1f}% | DD={r['dd']:.1f}% | Sharpe={r['sharpe']:.3f} | Orders={r['orders']}")
        else:
            log(f"    FAILED")

        results.append(r)

    # Save
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)

    # Report
    print("\n" + "=" * 70)
    print("PATH DEPENDENCY FIX — BEFORE vs AFTER")
    print("=" * 70)
    print(f"\n{'Start':<8} {'BEFORE':>12} {'AFTER':>12} {'Δ':>10} {'Orders Before':>14} {'Orders After':>14}")
    print("─" * 72)

    before = {2016: 126.5, 2017: 62.5, 2018: 62.5, 2019: 62.5, 2020: None}
    before_orders = {2016: 132, 2017: 56, 2018: 56, 2019: 56, 2020: None}

    nets_after = []
    for r in results:
        y = r["start_year"]
        b = before.get(y)
        bo = before_orders.get(y)
        if "net" in r:
            nets_after.append(r["net"])
            b_str = f"{b:+.1f}%" if b is not None else "N/A"
            a_str = f"{r['net']:+.1f}%"
            delta = f"{r['net'] - b:+.1f}%" if b is not None else "NEW"
            bo_str = str(bo) if bo is not None else "N/A"
            ao_str = str(r["orders"])
            print(f"{y:<8} {b_str:>12} {a_str:>12} {delta:>10} {bo_str:>14} {ao_str:>14}")

    if len(nets_after) >= 2:
        spread = max(nets_after) - min(nets_after)
        avg = sum(nets_after) / len(nets_after)
        cv = spread / avg * 100 if avg > 0 else 999
        print(f"\n  BEFORE: CV = 76% (spread 64.1%)")
        print(f"  AFTER:  CV = {cv:.0f}% (spread {spread:.1f}%)")
        if cv < 30:
            print(f"  ✅ PATH DEPENDENCY FIXED — results converge across start dates")
        elif cv < 50:
            print(f"  ⚠️ IMPROVED but some residual spread")
        else:
            print(f"  ❌ Still path dependent — seeding didn't fully resolve")
    print()
