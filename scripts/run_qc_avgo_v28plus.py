"""Run AVGO v2.8+ Trend Adder backtest + walk-forward analysis on QuantConnect.

RESEARCH ONLY — does not modify any live trading code.

Walk-forward windows:
  Full:  2016-01-01 to 2025-12-31 (full backtest)
  IS1:   2016-01-01 to 2020-12-31 (in-sample)
  OOS1:  2021-01-01 to 2022-12-31 (out-of-sample)
  IS2:   2018-01-01 to 2022-12-31 (in-sample)
  OOS2:  2023-01-01 to 2025-12-31 (out-of-sample)
"""
import os, sys, time, json
from hashlib import sha256
from base64 import b64encode
from datetime import datetime

QC_API_TOKEN = "a5e10d30d2c0f483c2c62a124375b2fcf4e0f907d54ab3ae863e7450e50b7688"
QC_USER_ID = "473242"
QC_BASE = "https://www.quantconnect.com/api/v2"

ALGO_PATH = os.path.expanduser("~/rudy/quantconnect/AVGOCycleLowLeap_v28plus.py")
OUTPUT_PATH = os.path.expanduser("~/rudy/data/avgo_v28plus_backtest.json")

# Walk-forward windows
WINDOWS = [
    {"name": "FULL",  "start": (2016, 1, 1),  "end": (2025, 12, 31)},
    {"name": "IS1",   "start": (2016, 1, 1),  "end": (2020, 12, 31)},
    {"name": "OOS1",  "start": (2021, 1, 1),  "end": (2022, 12, 31)},
    {"name": "IS2",   "start": (2018, 1, 1),  "end": (2022, 12, 31)},
    {"name": "OOS2",  "start": (2023, 1, 1),  "end": (2025, 12, 31)},
]


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _auth_headers():
    timestamp = str(int(time.time()))
    hashed = sha256(f"{QC_API_TOKEN}:{timestamp}".encode()).hexdigest()
    auth = b64encode(f"{QC_USER_ID}:{hashed}".encode()).decode()
    return {"Authorization": f"Basic {auth}", "Timestamp": timestamp, "Content-Type": "application/json"}


def _post(endpoint, data=None):
    import requests
    r = requests.post(f"{QC_BASE}/{endpoint}", headers=_auth_headers(), json=data or {}, timeout=60)
    return r.json()


def patch_dates(code, start, end):
    """Replace SetStartDate/SetEndDate in code."""
    import re
    code = re.sub(
        r'self\.SetStartDate\(\d+,\s*\d+,\s*\d+\)',
        f'self.SetStartDate({start[0]}, {start[1]}, {start[2]})',
        code
    )
    code = re.sub(
        r'self\.SetEndDate\(\d+,\s*\d+,\s*\d+\)',
        f'self.SetEndDate({end[0]}, {end[1]}, {end[2]})',
        code
    )
    return code


def run_single_backtest(algo_code, window_name):
    """Create project, upload, compile, run backtest, poll for results."""
    project_name = f"AVGO_v28plus_{window_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    log(f"\n{'='*60}")
    log(f"WINDOW: {window_name} — {project_name}")
    log(f"{'='*60}")

    # Create project
    result = _post("projects/create", {"name": project_name, "language": "Py"})
    if not result.get("success"):
        log(f"Project create failed: {result}")
        return None
    project_id = result.get("projects", [{}])[0].get("projectId")
    log(f"Project: {project_id}")

    # Upload code
    result = _post("files/create", {"projectId": project_id, "name": "main.py", "content": algo_code})
    if not result.get("success"):
        result = _post("files/update", {"projectId": project_id, "name": "main.py", "content": algo_code})
    log(f"Upload: {'OK' if result.get('success') else result}")

    # Compile
    log("Compiling...")
    compile_result = _post("compile/create", {"projectId": project_id})
    compile_id = compile_result.get("compileId", "")
    state = compile_result.get("state", "")
    log(f"Compile ID: {compile_id} | State: {state}")

    if state != "BuildSuccess":
        for i in range(60):
            time.sleep(3)
            check = _post("compile/read", {"projectId": project_id, "compileId": compile_id})
            state = check.get("state", "")
            if state == "BuildSuccess":
                break
            if state == "BuildError":
                errors = check.get("errors", [])
                log(f"BUILD ERROR: {errors}")
                return None
            if i % 5 == 0:
                log(f"  Compile: {state}")

    if state != "BuildSuccess":
        log("Compile timed out")
        return None
    log(f"Compile SUCCESS")

    # Launch backtest
    bt_name = f"AVGO v2.8+ {window_name}"
    bt_result = _post("backtests/create", {
        "projectId": project_id, "compileId": compile_id, "backtestName": bt_name
    })
    if not bt_result.get("success"):
        log(f"Launch failed: {bt_result}")
        return None

    backtest_id = bt_result.get("backtest", {}).get("backtestId") or bt_result.get("backtestId", "")
    if not backtest_id:
        log(f"No backtest ID: {json.dumps(bt_result, indent=2)}")
        return None
    log(f"Backtest ID: {backtest_id}")

    # Poll for completion
    for i in range(300):  # up to 10 minutes
        time.sleep(2)
        result = _post("backtests/read", {"projectId": project_id, "backtestId": backtest_id})
        bt = result.get("backtest", result)
        status = bt.get("status", "")
        progress = bt.get("progress", 0)

        if status == "Completed" or (isinstance(progress, (int, float)) and progress >= 1.0):
            stats = bt.get("statistics", {})
            log(f"\nCOMPLETED — {window_name}")
            log(f"{'='*40}")
            for k, v in stats.items():
                log(f"  {k}: {v}")

            # Extract log for trade detail
            log_entries = []
            try:
                log_result = _post("backtests/read", {
                    "projectId": project_id,
                    "backtestId": backtest_id,
                })
                log_entries = log_result.get("backtest", {}).get("logs", [])
            except:
                pass

            return {
                "window": window_name,
                "project_id": project_id,
                "backtest_id": backtest_id,
                "statistics": stats,
                "status": "Completed",
                "logs": log_entries[-100:] if log_entries else [],
            }

        if i % 15 == 0:
            log(f"  Progress: {progress} | Status: {status}")

    log("Backtest timed out after 10 minutes")
    return {
        "window": window_name,
        "project_id": project_id,
        "backtest_id": backtest_id,
        "statistics": {},
        "status": "Timeout",
    }


def compute_walk_forward_metrics(results):
    """Compute walk-forward efficiency ratios."""
    metrics = {}

    def get_return(window_name):
        for r in results:
            if r and r["window"] == window_name:
                stats = r.get("statistics", {})
                for k, v in stats.items():
                    if "return" in k.lower() or "net profit" in k.lower():
                        try:
                            return float(v.replace("%", "").replace("$", "").replace(",", ""))
                        except:
                            pass
        return None

    def get_stat(window_name, keyword):
        for r in results:
            if r and r["window"] == window_name:
                stats = r.get("statistics", {})
                for k, v in stats.items():
                    if keyword.lower() in k.lower():
                        try:
                            return float(v.replace("%", "").replace("$", "").replace(",", ""))
                        except:
                            pass
        return None

    # Walk-forward efficiency: OOS return / IS return
    is1_ret = get_stat("IS1", "compounding annual")
    oos1_ret = get_stat("OOS1", "compounding annual")
    is2_ret = get_stat("IS2", "compounding annual")
    oos2_ret = get_stat("OOS2", "compounding annual")

    if is1_ret and oos1_ret and is1_ret != 0:
        metrics["wf_efficiency_1"] = oos1_ret / is1_ret
    if is2_ret and oos2_ret and is2_ret != 0:
        metrics["wf_efficiency_2"] = oos2_ret / is2_ret

    metrics["is1_annual_return"] = is1_ret
    metrics["oos1_annual_return"] = oos1_ret
    metrics["is2_annual_return"] = is2_ret
    metrics["oos2_annual_return"] = oos2_ret

    # Sharpe comparison
    metrics["is1_sharpe"] = get_stat("IS1", "sharpe")
    metrics["oos1_sharpe"] = get_stat("OOS1", "sharpe")
    metrics["is2_sharpe"] = get_stat("IS2", "sharpe")
    metrics["oos2_sharpe"] = get_stat("OOS2", "sharpe")

    # Max drawdown comparison
    metrics["is1_drawdown"] = get_stat("IS1", "drawdown")
    metrics["oos1_drawdown"] = get_stat("OOS1", "drawdown")
    metrics["is2_drawdown"] = get_stat("IS2", "drawdown")
    metrics["oos2_drawdown"] = get_stat("OOS2", "drawdown")

    return metrics


def main():
    log("AVGO v2.8+ TREND ADDER — QC BACKTEST + WALK-FORWARD ANALYSIS")
    log(f"Output: {OUTPUT_PATH}")

    with open(ALGO_PATH) as f:
        base_code = f.read()

    all_results = []

    for window in WINDOWS:
        patched_code = patch_dates(base_code, window["start"], window["end"])
        result = run_single_backtest(patched_code, window["name"])
        all_results.append(result)

    # Compute walk-forward metrics
    wf_metrics = compute_walk_forward_metrics(all_results)

    log(f"\n{'='*60}")
    log("WALK-FORWARD ANALYSIS SUMMARY")
    log(f"{'='*60}")
    for k, v in wf_metrics.items():
        log(f"  {k}: {v}")

    # Build output
    output = {
        "strategy": "AVGO_v28plus_TrendAdder",
        "ticker": "AVGO",
        "description": "Broadcom v2.8+ Cycle-Low LEAP with Trend Adder. "
                       "Adapted from MARA template. Uses price/200W-SMA ratio "
                       "instead of mNAV. BTC filter replaced with SPY > 200W SMA.",
        "timestamp": datetime.now().isoformat(),
        "windows": [],
        "walk_forward_metrics": wf_metrics,
        "adaptations": {
            "premium_metric": "price / 200W SMA ratio (replaces mNAV)",
            "market_filter": "SPY > 200W SMA (replaces BTC > 200W SMA)",
            "death_cross": "SPY 50/200 death cross (replaces BTC/GBTC death cross)",
            "leap_multiplier": "Lower than MSTR/MARA (AVGO lower vol)",
            "premium_bands": "< 1.0 / 1.0-1.3 / 1.3-2.0 / 2.0+",
            "slippage": "0.3% (AVGO highly liquid)",
            "euphoria_threshold": "3.0x (price/SMA ratio)",
        },
    }

    for r in all_results:
        if r:
            # Don't include logs in the output to keep it clean
            r_clean = {k: v for k, v in r.items() if k != "logs"}
            output["windows"].append(r_clean)
        else:
            output["windows"].append({"status": "Failed"})

    # Save
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)

    log(f"\nResults saved to: {OUTPUT_PATH}")

    # Print comparison table
    log(f"\n{'='*60}")
    log("COMPARISON TABLE")
    log(f"{'='*60}")
    log(f"{'Window':<8} {'Return':<12} {'Sharpe':<10} {'Drawdown':<12} {'Trades':<8} {'WinRate':<8}")
    log("-" * 58)

    for r in all_results:
        if r and r.get("statistics"):
            stats = r["statistics"]
            name = r["window"]
            ret = "?"
            sharpe = "?"
            dd = "?"
            trades = "?"
            wr = "?"
            for k, v in stats.items():
                if "net profit" in k.lower():
                    ret = v
                if "sharpe" in k.lower():
                    sharpe = v
                if "drawdown" in k.lower():
                    dd = v
                if "total trades" in k.lower():
                    trades = v
                if "win rate" in k.lower():
                    wr = v
            log(f"{name:<8} {ret:<12} {sharpe:<10} {dd:<12} {trades:<8} {wr:<8}")

    return output


if __name__ == "__main__":
    main()
