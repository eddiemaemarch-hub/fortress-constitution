"""Run v2.8 Dynamic Blend backtests on QuantConnect — Weekly + Daily"""
import os, sys, time, json, requests
from hashlib import sha256
from base64 import b64encode

QC_API_TOKEN = "a5e10d30d2c0f483c2c62a124375b2fcf4e0f907d54ab3ae863e7450e50b7688"
QC_USER_ID = "473242"
QC_BASE = "https://www.quantconnect.com/api/v2"

WEEKLY_PROJECT_ID = 29065184
DAILY_PROJECT_ID = 29064069

def _auth_headers():
    timestamp = str(int(time.time()))
    hashed = sha256(f"{QC_API_TOKEN}:{timestamp}".encode()).hexdigest()
    auth = b64encode(f"{QC_USER_ID}:{hashed}".encode()).decode()
    return {"Authorization": f"Basic {auth}", "Timestamp": timestamp, "Content-Type": "application/json"}

def _post(endpoint, data=None):
    r = requests.post(f"{QC_BASE}/{endpoint}", headers=_auth_headers(), json=data or {}, timeout=30)
    return r.json()

def log(msg):
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# Read the v2.8 algorithm
algo_path = os.path.expanduser("~/rudy/quantconnect/MSTRCycleLowLeap_v28_dynamic.py")
with open(algo_path) as f:
    algo_code = f.read()

def run_backtest(project_id, resolution, name):
    """Upload code, compile, and run backtest for a given resolution."""
    patched = algo_code.replace(
        'self.trade_resolution = "weekly"',
        f'self.trade_resolution = "{resolution}"'
    )

    log(f"\n{'='*60}")
    log(f"v2.8 DYNAMIC BLEND — {resolution.upper()}")
    log(f"{'='*60}")

    # Upload
    log("Uploading...")
    result = _post("files/create", {"projectId": project_id, "name": "main.py", "content": patched})
    if not result.get("success"):
        result = _post("files/update", {"projectId": project_id, "name": "main.py", "content": patched})
    log(f"Upload: {'OK' if result.get('success') else result}")

    # Compile (create once, then poll via compile/read)
    log("Compiling...")
    compile_result = _post("compile/create", {"projectId": project_id})
    compile_id = compile_result.get("compileId", "")
    state = compile_result.get("state", "")
    log(f"Compile ID: {compile_id} | State: {state}")

    # Poll compile status using compile/read
    if state != "BuildSuccess":
        for i in range(60):
            time.sleep(3)
            check = _post("compile/read", {"projectId": project_id, "compileId": compile_id})
            state = check.get("state", "")
            log(f"  Compile: {state}")
            if state == "BuildSuccess":
                break
            if state == "BuildError":
                errors = check.get("errors", [])
                log(f"  BUILD ERROR: {errors}")
                return None

    if state != "BuildSuccess":
        log("Compile timed out")
        return None

    log(f"Compile SUCCESS: {compile_id}")

    # Launch backtest
    log(f"Launching backtest: {name}")
    bt_result = _post("backtests/create", {
        "projectId": project_id, "compileId": compile_id, "backtestName": name
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
    for i in range(180):  # up to 6 minutes
        time.sleep(2)
        result = _post("backtests/read", {"projectId": project_id, "backtestId": backtest_id})
        bt = result.get("backtest", result)
        status = bt.get("status", "")
        progress = bt.get("progress", 0)

        if status == "Completed" or (isinstance(progress, (int, float)) and progress >= 1.0):
            stats = bt.get("statistics", {})
            log(f"\nCOMPLETED — {name}")
            log(f"{'='*40}")
            for k, v in stats.items():
                log(f"  {k}: {v}")
            return result

        if i % 10 == 0:
            log(f"  Progress: {progress} | Status: {status}")

    log("Backtest timed out")
    return None


if __name__ == "__main__":
    log("RUDY v2.8 DYNAMIC BLEND — QC BACKTEST")

    weekly_result = run_backtest(WEEKLY_PROJECT_ID, "weekly", "v2.8 Dynamic Blend WEEKLY")
    daily_result = run_backtest(DAILY_PROJECT_ID, "daily", "v2.8 Dynamic Blend DAILY")

    log(f"\n{'='*60}")
    log("COMPARISON: v2.8 DYNAMIC vs v2.7 DIAMOND HANDS")
    log(f"{'='*60}")
    log("v2.7 Weekly: +58.3% | 28% WR | 30.7% DD | Sharpe 0.095")
    log("v2.7 Daily:  +71.0% | 36% WR | 32.9% DD | Sharpe 0.142")
    log("")

    for label, result in [("Weekly", weekly_result), ("Daily", daily_result)]:
        if result:
            bt = result.get("backtest", result)
            stats = bt.get("statistics", {})
            net = stats.get("Net Profit", "?")
            wr = stats.get("Win Rate", "?")
            dd = stats.get("Drawdown", "?")
            sharpe = stats.get("Sharpe Ratio", "?")
            trades = stats.get("Total Trades", "?")
            log(f"v2.8 {label}: Net={net} | WR={wr} | DD={dd} | Sharpe={sharpe} | Trades={trades}")
        else:
            log(f"v2.8 {label}: FAILED")
