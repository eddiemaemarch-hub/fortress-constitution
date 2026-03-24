#!/usr/bin/env python3
"""
Candlestick Filter Walk-Forward Backtest — Rudy v2.8+ Research

Tests whether adding bullish weekly candlestick pattern confirmation to
the v2.8+ entry signal improves out-of-sample risk-adjusted returns.

4 MODES tested across 7 walk-forward windows:
  none       — baseline v2.8+ (no candlestick gate)
  strict     — entry bar must show a bullish pattern
  window_3   — bullish pattern within last 3 bars
  high_prob  — only Hammer or Engulfing count (entry bar)

Walk-Forward: 7 anchored OOS windows (same as existing WF validation)
  Each window: train 2016→cutoff, OOS = cutoff→cutoff+18m

Metrics compared per mode:
  - OOS Net Return %
  - OOS Max Drawdown %
  - Sharpe Ratio
  - Trade Count (fewer but higher-quality = OK if return/DD improves)
  - WFE Score (OOS / IS ratio)
  - Entry delay (avg bars from armed → entry, candlestick modes may delay)

Usage:
    python3 backtest_candlestick_v28plus.py          # full run
    python3 backtest_candlestick_v28plus.py --report # print existing results only
"""
import os, sys, re, json, time, argparse
from datetime import datetime, date
from hashlib import sha256
from base64 import b64encode
import requests

# ── QC Config ──
QC_API_TOKEN = "a5e10d30d2c0f483c2c62a124375b2fcf4e0f907d54ab3ae863e7450e50b7688"
QC_USER_ID   = "473242"
QC_BASE      = "https://www.quantconnect.com/api/v2"
PROJECT_ID   = 29065184

ALGO_PATH    = os.path.expanduser("~/rudy/quantconnect/MSTRCycleLowLeap_v28plus_candlestick.py")
DATA_DIR     = os.path.expanduser("~/rudy/data")
RESULTS_FILE = os.path.join(DATA_DIR, "candlestick_wf_results.json")
os.makedirs(DATA_DIR, exist_ok=True)

# ── Walk-Forward Windows ──
# Anchored: IS always starts 2016. OOS window = 18 months each.
WF_WINDOWS = [
    {"name": "W1", "oos_start": (2021, 7,  1), "oos_end": (2022, 12, 31)},
    {"name": "W2", "oos_start": (2022, 7,  1), "oos_end": (2023, 12, 31)},
    {"name": "W3", "oos_start": (2023, 1,  1), "oos_end": (2024,  6, 30)},
    {"name": "W4", "oos_start": (2023, 7,  1), "oos_end": (2024, 12, 31)},
    {"name": "W5", "oos_start": (2024, 1,  1), "oos_end": (2025,  6, 30)},
    {"name": "W6", "oos_start": (2024, 7,  1), "oos_end": (2025, 12, 31)},
    {"name": "W7", "oos_start": (2025, 1,  1), "oos_end": (2026,  3, 14)},
]

# ── Candlestick Modes ──
MODES = ["none", "strict", "window_3", "high_prob"]


# ═══════════════════════════════════════════════════════════════
# QC API HELPERS
# ═══════════════════════════════════════════════════════════════

def _auth():
    ts = str(int(time.time()))
    h  = sha256(f"{QC_API_TOKEN}:{ts}".encode()).hexdigest()
    a  = b64encode(f"{QC_USER_ID}:{h}".encode()).decode()
    return {"Authorization": f"Basic {a}", "Timestamp": ts, "Content-Type": "application/json"}


def _post(ep, data=None):
    for attempt in range(3):
        try:
            r = requests.post(f"{QC_BASE}/{ep}", headers=_auth(), json=data or {}, timeout=60)
            if r.status_code == 429:
                wait = 10 * (2 ** attempt)
                log(f"  Rate limited — waiting {wait}s...")
                time.sleep(wait)
                continue
            return r.json()
        except Exception as e:
            if attempt < 2:
                log(f"  API error: {e} — retrying in 10s")
                time.sleep(10)
            else:
                raise
    return {"success": False}


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def parse_stat(stats, key, default=0.0):
    val = stats.get(key, str(default))
    if isinstance(val, (int, float)):
        return float(val)
    val = str(val).replace("%", "").replace("$", "").replace(",", "").strip()
    try:
        return float(val)
    except Exception:
        return default


# ═══════════════════════════════════════════════════════════════
# CODE PATCHING
# ═══════════════════════════════════════════════════════════════

def patch_dates(code, start_y, start_m, start_d, end_y, end_m, end_d):
    code = re.sub(
        r"self\.SetStartDate\(\d+,\s*\d+,\s*\d+\)",
        f"self.SetStartDate({start_y}, {start_m}, {start_d})", code)
    code = re.sub(
        r"self\.SetEndDate\(\d+,\s*\d+,\s*\d+\)",
        f"self.SetEndDate({end_y}, {end_m}, {end_d})", code)
    return code


def patch_mode(code, mode):
    """Inject the candlestick_mode parameter."""
    return re.sub(
        r'self\.candlestick_mode\s*=\s*"[^"]*"',
        f'self.candlestick_mode = "{mode}"',
        code)


# ═══════════════════════════════════════════════════════════════
# BACKTEST RUNNER
# ═══════════════════════════════════════════════════════════════

def run_backtest(code, name):
    """Upload code, compile, run backtest. Returns statistics dict or None."""
    # Upload
    result = _post("files/update", {"projectId": PROJECT_ID, "name": "main.py", "content": code})
    if not result.get("success"):
        _post("files/create", {"projectId": PROJECT_ID, "name": "main.py", "content": code})

    # Compile
    cr  = _post("compile/create", {"projectId": PROJECT_ID})
    cid = cr.get("compileId", "")

    for _ in range(60):
        time.sleep(3)
        check = _post("compile/read", {"projectId": PROJECT_ID, "compileId": cid})
        state = check.get("state", "")
        if state == "BuildSuccess":
            break
        if state == "BuildError":
            log(f"  BUILD ERROR: {check.get('errors', [])}", "ERROR")
            return None
    else:
        log("  Compile timeout", "ERROR")
        return None

    # Launch backtest
    bt   = _post("backtests/create", {"projectId": PROJECT_ID, "compileId": cid, "backtestName": name})
    btid = bt.get("backtest", {}).get("backtestId") or bt.get("backtestId", "")
    if not btid:
        log(f"  No backtestId returned: {bt}", "ERROR")
        return None

    # Poll until complete — hard wall-clock timeout of 8 minutes per backtest
    deadline = time.time() + 480
    i = 0
    while time.time() < deadline:
        time.sleep(3)
        try:
            r = _post("backtests/read", {"projectId": PROJECT_ID, "backtestId": btid})
        except Exception as e:
            log(f"  Poll error: {e}", "WARN")
            i += 1
            continue
        b = r.get("backtest", r)
        progress = b.get("progress", 0)
        status   = b.get("status", "")
        if status == "Completed" or (isinstance(progress, (int, float)) and progress >= 1.0):
            time.sleep(2)
            r     = _post("backtests/read", {"projectId": PROJECT_ID, "backtestId": btid})
            stats = r.get("backtest", r).get("statistics", {})
            log(f"  ✅ Complete | Return={stats.get('Net Profit','?')} | DD={stats.get('Drawdown','?')}")
            return stats
        if status in ("RuntimeError", "Error"):
            log(f"  QC runtime error: {b.get('error','?')}", "ERROR")
            return None
        if i % 20 == 0 and i > 0:
            elapsed = int(time.time() - (deadline - 480))
            log(f"  Polling... {elapsed}s elapsed | progress={progress} | status={status}")
        i += 1

    log(f"  ⏰ 8-min wall-clock timeout — skipping window", "WARN")
    return None


# ═══════════════════════════════════════════════════════════════
# WALK-FORWARD EXECUTION
# ═══════════════════════════════════════════════════════════════

def run_walk_forward(base_code, modes_to_run=None):
    """Run all 4 modes × 7 windows. Returns results dict."""
    if modes_to_run is None:
        modes_to_run = MODES

    # Resume from partial results if file exists
    results = {}
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE) as f:
                results = json.load(f)
            log(f"Resuming from {RESULTS_FILE} — {list(results.keys())} already have data")
        except Exception:
            results = {}

    for mode in modes_to_run:
        log(f"\n{'='*60}")
        log(f"MODE: {mode.upper()}")
        log(f"{'='*60}")
        results[mode] = {"windows": []}

        for win in WF_WINDOWS:
            name = win["name"]
            os_y, os_m, os_d = win["oos_start"]
            oe_y, oe_m, oe_d = win["oos_end"]

            # Skip if already completed in a previous run
            existing_wins = results.get(mode, {}).get("windows", [])
            if any(w.get("window") == name and w.get("status") == "OK" for w in existing_wins):
                log(f"  Skipping {name} (already completed)")
                continue

            # IS: 2016-01-01 → oos_start
            # OOS: oos_start → oos_end
            code = patch_dates(base_code, os_y, os_m, os_d, oe_y, oe_m, oe_d)
            code = patch_mode(code, mode)

            run_name = f"CS_{mode}_{name}_{os_y}{os_m:02d}"
            log(f"\n  Window {name}: OOS {os_y}-{os_m:02d} → {oe_y}-{oe_m:02d} | Mode={mode}")

            stats = run_backtest(code, run_name)
            if stats is None:
                log(f"  FAILED — skipping {name}", "WARN")
                results[mode]["windows"].append({
                    "window": name, "oos_start": win["oos_start"],
                    "oos_end": win["oos_end"], "status": "FAILED"})
                continue

            net_return  = parse_stat(stats, "Net Profit")
            drawdown    = parse_stat(stats, "Drawdown")
            sharpe      = parse_stat(stats, "Sharpe Ratio")
            trades      = parse_stat(stats, "Total Trades")
            win_rate    = parse_stat(stats, "Win Rate")

            results[mode]["windows"].append({
                "window":     name,
                "oos_start":  win["oos_start"],
                "oos_end":    win["oos_end"],
                "net_return": net_return,
                "drawdown":   drawdown,
                "sharpe":     sharpe,
                "trades":     int(trades),
                "win_rate":   win_rate,
                "status":     "OK",
            })

            log(f"  {name}: Return={net_return:.1f}% | DD={drawdown:.1f}% | "
                f"Sharpe={sharpe:.3f} | Trades={int(trades)}")

            # Save partial results after every window
            with open(RESULTS_FILE, "w") as f:
                json.dump(results, f, indent=2, default=str)

            # Throttle between runs
            time.sleep(5)

        # Aggregate across windows
        ok_wins = [w for w in results[mode]["windows"] if w.get("status") == "OK"]
        if ok_wins:
            results[mode]["aggregate"] = {
                "avg_return":   sum(w["net_return"] for w in ok_wins) / len(ok_wins),
                "avg_drawdown": sum(w["drawdown"]   for w in ok_wins) / len(ok_wins),
                "avg_sharpe":   sum(w["sharpe"]     for w in ok_wins) / len(ok_wins),
                "total_trades": sum(w["trades"]     for w in ok_wins),
                "windows_ok":   len(ok_wins),
                "windows_total":len(WF_WINDOWS),
            }

    return results


# ═══════════════════════════════════════════════════════════════
# REPORT GENERATION
# ═══════════════════════════════════════════════════════════════

def print_report(results):
    """Print comparison table: modes vs aggregate OOS metrics."""
    if not results:
        print("No results available.")
        return

    print("\n" + "=" * 80)
    print("CANDLESTICK FILTER WALK-FORWARD COMPARISON — MSTR v2.8+")
    print("=" * 80)
    print(f"\n{'Mode':<14} {'Avg OOS Ret':>12} {'Avg DD':>9} {'Avg Sharpe':>11} "
          f"{'Trades':>8} {'Windows OK':>12}")
    print("-" * 80)

    baseline = None
    for mode in MODES:
        agg = results.get(mode, {}).get("aggregate", {})
        if not agg:
            print(f"{mode:<14} {'NO DATA':>12}")
            continue

        ret = agg["avg_return"]
        dd  = agg["avg_drawdown"]
        sh  = agg["avg_sharpe"]
        tr  = agg["total_trades"]
        w   = f"{agg['windows_ok']}/{agg['windows_total']}"

        if mode == "none":
            baseline = agg

        # Delta vs baseline
        delta = ""
        if baseline and mode != "none":
            d_ret = ret - baseline["avg_return"]
            d_dd  = dd  - baseline["avg_drawdown"]
            d_sh  = sh  - baseline["avg_sharpe"]
            delta = (f"  [Δ ret={d_ret:+.1f}%  Δ dd={d_dd:+.1f}%  Δ sharpe={d_sh:+.3f}]")

        print(f"{mode:<14} {ret:>+11.1f}% {dd:>8.1f}% {sh:>11.3f} {tr:>8} {w:>12}{delta}")

    print("=" * 80)

    # Per-window detail
    for mode in MODES:
        wins = results.get(mode, {}).get("windows", [])
        if not wins:
            continue
        print(f"\n  {mode.upper()} — per window:")
        print(f"    {'Win':<5} {'OOS Period':<20} {'Return':>9} {'DD':>8} {'Sharpe':>9} {'Trades':>8}")
        for w in wins:
            if w.get("status") != "OK":
                print(f"    {w['window']:<5} FAILED")
                continue
            period = f"{w['oos_start'][0]}-{w['oos_start'][1]:02d} → {w['oos_end'][0]}-{w['oos_end'][1]:02d}"
            print(f"    {w['window']:<5} {period:<20} "
                  f"{w['net_return']:>+8.1f}% {w['drawdown']:>7.1f}% "
                  f"{w['sharpe']:>9.3f} {w['trades']:>8}")

    # Verdict
    print("\n" + "─" * 80)
    print("VERDICT:")
    available = [m for m in MODES if results.get(m, {}).get("aggregate")]
    if not available:
        print("  No completed modes to compare.")
        return
    best_ret    = max(available, key=lambda m: results.get(m, {}).get("aggregate", {}).get("avg_return", -999))
    best_sharpe = max(available, key=lambda m: results.get(m, {}).get("aggregate", {}).get("avg_sharpe", -999))
    best_dd     = min(available, key=lambda m: results.get(m, {}).get("aggregate", {}).get("avg_drawdown", 999))
    print(f"  Best OOS Return:  {best_ret} ({results.get(best_ret,{}).get('aggregate',{}).get('avg_return',0):+.1f}%)")
    print(f"  Best Sharpe:      {best_sharpe} ({results.get(best_sharpe,{}).get('aggregate',{}).get('avg_sharpe',0):.3f})")
    print(f"  Lowest Drawdown:  {best_dd} ({results.get(best_dd,{}).get('aggregate',{}).get('avg_drawdown',0):.1f}%)")

    add_to_system = False
    none_ret = results.get("none", {}).get("aggregate", {}).get("avg_return", 0)
    none_sh  = results.get("none", {}).get("aggregate", {}).get("avg_sharpe", 0)
    for m in ["strict", "window_3", "high_prob"]:
        agg = results.get(m, {}).get("aggregate", {})
        if agg.get("avg_return", 0) > none_ret + 5 and agg.get("avg_sharpe", 0) > none_sh + 0.05:
            add_to_system = True
            print(f"\n  ⚡ RECOMMENDATION: '{m}' mode beats baseline by "
                  f">5% return AND >0.05 Sharpe — CONSIDER adding as awareness layer")

    if not add_to_system:
        print("\n  ✅ Baseline (no candlestick gate) holds up — v2.8+ filters are sufficient.")
        print("  Candlestick patterns DO NOT materially improve OOS performance on weekly MSTR.")
    print("─" * 80)


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Candlestick filter walk-forward backtest")
    parser.add_argument("--report", action="store_true", help="Print existing results, no new runs")
    parser.add_argument("--mode", choices=MODES, help="Run a single mode only (for debugging)")
    args = parser.parse_args()

    # Report only
    if args.report:
        if os.path.exists(RESULTS_FILE):
            with open(RESULTS_FILE) as f:
                results = json.load(f)
            print_report(results)
        else:
            print("No results file found. Run without --report first.")
        return

    # Load base algo code
    algo_path = os.path.expanduser(ALGO_PATH)
    if not os.path.exists(algo_path):
        print(f"ERROR: Algo file not found: {algo_path}")
        sys.exit(1)
    with open(algo_path) as f:
        base_code = f.read()

    log(f"Loaded algo: {algo_path} ({len(base_code)} chars)")
    log(f"Modes to test: {[args.mode] if args.mode else MODES}")
    log(f"WF windows: {len(WF_WINDOWS)}")
    log(f"Total runs: {(1 if args.mode else len(MODES)) * len(WF_WINDOWS)}")

    # Run
    modes_to_run = [args.mode] if args.mode else MODES

    results = run_walk_forward(base_code, modes_to_run)

    # Save
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)
    log(f"\nResults saved → {RESULTS_FILE}")

    # Print
    print_report(results)


if __name__ == "__main__":
    main()
