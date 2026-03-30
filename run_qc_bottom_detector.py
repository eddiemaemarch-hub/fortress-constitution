#!/usr/bin/env python3
"""
run_qc_bottom_detector.py
Submits bottom_detector_mstr_qc.py to QuantConnect API and prints results.

Usage:
    python3 run_qc_bottom_detector.py

Requires:
    - QC_USER_ID and QC_API_TOKEN in ~/.agent_zero_env
    - bottom_detector_mstr_qc.py in same directory
"""

import os
import sys
import time
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load credentials from same place all other QC scripts use
load_dotenv(Path.home() / ".agent_zero_env")
QC_USER_ID  = os.getenv("QC_USER_ID")
QC_API_TOKEN = os.getenv("QC_API_TOKEN")

if not QC_USER_ID or not QC_API_TOKEN:
    print("ERROR: QC_USER_ID or QC_API_TOKEN not found in ~/.agent_zero_env")
    sys.exit(1)

BASE_URL = "https://www.quantconnect.com/api/v2"
AUTH     = (QC_USER_ID, QC_API_TOKEN)
ALGO_FILE = Path(__file__).parent / "bottom_detector_mstr_qc.py"
PROJECT_NAME = "MSTR-Bottom-Detector"


def api(method, endpoint, **kwargs):
    url = f"{BASE_URL}/{endpoint}"
    resp = getattr(requests, method)(url, auth=AUTH, **kwargs)
    resp.raise_for_status()
    return resp.json()


def create_project():
    print(f"  Creating project: {PROJECT_NAME}...")
    data = api("post", "projects/create", json={"name": PROJECT_NAME, "language": "Py"})
    pid = data["projects"][0]["projectId"]
    print(f"  Project ID: {pid}")
    return pid


def upload_code(pid):
    code = ALGO_FILE.read_text()
    print(f"  Uploading algorithm ({len(code)} chars)...")
    api("post", "files/create", json={
        "projectId": pid,
        "name": "main.py",
        "content": code
    })
    print("  Upload complete.")


def compile_project(pid):
    print("  Compiling...")
    data = api("post", "compile/create", json={"projectId": pid})
    compile_id = data["compileId"]
    # Poll for completion
    for _ in range(30):
        time.sleep(2)
        status = api("get", f"compile/read?projectId={pid}&compileId={compile_id}")
        state = status.get("state", "")
        if state == "BuildSuccess":
            print("  Compile: SUCCESS")
            return compile_id
        elif state == "BuildError":
            print(f"  Compile ERROR: {status.get('logs', '')}")
            sys.exit(1)
    print("  Compile timeout")
    sys.exit(1)


def run_backtest(pid, compile_id):
    print("  Launching backtest...")
    data = api("post", "backtests/create", json={
        "projectId":  pid,
        "compileId":  compile_id,
        "backtestName": "BottomDetector-Run"
    })
    bt_id = data["backtestId"]
    print(f"  Backtest ID: {bt_id}")

    # Poll until complete
    dots = 0
    while True:
        time.sleep(5)
        status = api("get", f"backtests/read?projectId={pid}&backtestId={bt_id}")
        progress = status.get("progress", 0)
        completed = status.get("completed", False)
        dots += 1
        print(f"\r  Running{'.' * (dots % 4):<4} {progress*100:.0f}%", end="", flush=True)
        if completed:
            print()
            break

    return bt_id, status


def print_results(status):
    print(f"\n{'═'*65}")
    print(f"  MSTR BOTTOM DETECTOR — QC BACKTEST RESULTS")
    print(f"{'═'*65}")

    stats = status.get("statistics", {})
    runtime_stats = status.get("runtimeStatistics", {})

    # Print key stats
    for key in ["Total Trades", "Total Return", "Annual Return",
                "Sharpe Ratio", "Max Drawdown", "Win Rate"]:
        val = stats.get(key, runtime_stats.get(key, "—"))
        print(f"  {key:<25} {val}")

    print(f"\n  BOTTOM DETECTION SIGNALS (from debug log):")
    print(f"  {'─'*65}")

    # Extract bottom alert lines from log
    logs = status.get("debugLog", "") or ""
    lines = logs.split("\n")
    in_results = False
    for line in lines:
        if "BOTTOM DETECTION" in line or "═" in line or in_results:
            in_results = True
            print(f"  {line}")
        if in_results and "research only" in line.lower():
            break

    print(f"\n{'═'*65}")


def main():
    print("=" * 65)
    print("  MSTR BOTTOM DETECTOR — QuantConnect Submission")
    print("  Research only — NOT a trading strategy")
    print("=" * 65 + "\n")

    if not ALGO_FILE.exists():
        print(f"ERROR: {ALGO_FILE} not found")
        sys.exit(1)

    pid        = create_project()
    upload_code(pid)
    compile_id = compile_project(pid)
    bt_id, status = run_backtest(pid, compile_id)
    print_results(status)

    print(f"\n  View full results at:")
    print(f"  https://www.quantconnect.com/terminal/#open/{pid}/backtests/{bt_id}")
    print()


if __name__ == "__main__":
    main()
