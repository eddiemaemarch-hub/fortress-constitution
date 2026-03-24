#!/usr/bin/env python3
"""Run MSTR Cycle-HIGH PUT LEAP v1.0 Backtest on QuantConnect.

Tests the inverse PUT strategy on both Weekly and Daily resolutions.

Usage: python3 scripts/run_qc_put_backtest.py
       python3 scripts/run_qc_put_backtest.py poll
Requires QC_USER_ID and QC_API_TOKEN environment variables.
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.expanduser("~/rudy/scripts"))
from quantconnect import (
    authenticate, create_project, add_file, compile_project,
    create_backtest, read_backtest, _post
)

QC_DIR = os.path.expanduser("~/rudy/quantconnect")
DATA_DIR = os.path.expanduser("~/rudy/data")
os.makedirs(DATA_DIR, exist_ok=True)

RESULTS_FILE = os.path.join(DATA_DIR, "qc_put_backtests.json")


def delete_file(project_id, filename):
    """Delete a file from a QC project."""
    return _post("files/delete", {"projectId": project_id, "name": filename})


def make_resolution_patch(content, resolution):
    """Hard-code the trade resolution."""
    return content.replace(
        """if not hasattr(self, 'trade_resolution'):
            self.trade_resolution = "weekly\"""",
        f'self.trade_resolution = "{resolution}"'
    )


VARIANTS = [
    ("MSTR CycleHigh PUT v1.0 Weekly", "weekly"),
    ("MSTR CycleHigh PUT v1.0 Daily",  "daily"),
]


def run_all():
    if not os.environ.get("QC_USER_ID") or not os.environ.get("QC_API_TOKEN"):
        print("ERROR: Set QC_USER_ID and QC_API_TOKEN environment variables first.")
        sys.exit(1)

    auth = authenticate()
    if not auth.get("success"):
        print(f"Auth failed: {auth}")
        sys.exit(1)
    print("✅ Authenticated with QuantConnect")

    # Read PUT strategy
    with open(os.path.join(QC_DIR, "MSTRCycleHighPut.py"), "r") as f:
        base_content = f.read()

    results = {}

    for name, resolution in VARIANTS:
        print(f"\n{'='*60}")
        print(f"📊 Starting: {name}")
        print(f"{'='*60}")

        # 1. Apply resolution patch
        patched = make_resolution_patch(base_content, resolution)

        # Verify patch applied
        if f'self.trade_resolution = "{resolution}"' not in patched:
            print(f"  ❌ Resolution patch failed")
            continue

        # 2. Create project
        proj = create_project(name)
        if not proj.get("success"):
            print(f"  ❌ Create project failed: {proj}")
            continue
        project_id = proj.get("projects", [{}])[0].get("projectId")
        print(f"  ✅ Project created: ID {project_id}")

        # 3. Delete default main.py
        del_result = delete_file(project_id, "main.py")
        print(f"  🗑️  Deleted default main.py: {del_result.get('success', False)}")

        # 4. Upload patched algo
        result = add_file(project_id, "main.py", patched)
        print(f"  ✅ Uploaded patched main.py ({len(patched)} chars)")

        # 5. Compile
        compile_result = compile_project(project_id)
        if not compile_result.get("success"):
            print(f"  ❌ Compile failed: {compile_result}")
            continue
        compile_id = compile_result.get("compileId", "")
        state = compile_result.get("state", "")
        print(f"  ✅ Compiled: {compile_id} ({state})")

        if state == "InQueue":
            print(f"  ⏳ Compile queued, waiting 15s...")
            time.sleep(15)

        # 6. Run backtest
        bt = create_backtest(project_id, compile_id, name)
        if not bt.get("success"):
            print(f"  ❌ Backtest failed to start: {bt}")
            continue
        backtest_id = bt.get("backtestId", "")
        print(f"  🚀 Backtest started: {backtest_id}")

        results[name] = {
            "project_id": project_id,
            "compile_id": compile_id,
            "backtest_id": backtest_id,
            "resolution": resolution,
            "status": "running",
        }

        # Brief pause between variants
        time.sleep(3)

    # Save results
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n✅ Results saved to {RESULTS_FILE}")
    print(f"\nBoth backtests launched. Poll with:")
    print(f"  python3 scripts/run_qc_put_backtest.py poll")

    return results


def poll_results():
    """Poll for completed backtest results."""
    if not os.path.exists(RESULTS_FILE):
        print("No PUT backtests found. Run this script first.")
        return

    with open(RESULTS_FILE) as f:
        results = json.load(f)

    print("\n" + "=" * 80)
    print("MSTR CYCLE-HIGH PUT LEAP v1.0 — BACKTEST RESULTS")
    print("=" * 80)

    for name, info in results.items():
        bt_id = info.get("backtest_id", "")
        if not bt_id:
            bt_list = _post("backtests/read", {"projectId": info["project_id"]})
            if bt_list.get("success"):
                backtests = bt_list.get("backtests", [])
                if backtests:
                    bt_id = backtests[0].get("backtestId", "")
                    info["backtest_id"] = bt_id

        if not bt_id:
            print(f"\n📊 {name}")
            print(f"   ⏳ No backtest ID yet — still compiling?")
            continue

        bt = read_backtest(info["project_id"], bt_id)
        if bt.get("success"):
            backtest = bt.get("backtest", bt)
            status = backtest.get("status", backtest.get("completed", "unknown"))

            stats = backtest.get("statistics", {})
            total_return = stats.get("Net Profit", "N/A")
            win_rate = stats.get("Win Rate", "N/A")
            sharpe = stats.get("Sharpe Ratio", "N/A")
            max_dd = stats.get("Drawdown", "N/A")
            total_trades = stats.get("Total Orders", "N/A")
            annual = stats.get("Compounding Annual Return", "N/A")
            pl_ratio = stats.get("Profit-Loss Ratio", "N/A")

            print(f"\n📊 {name}")
            print(f"   Status: {status}")
            print(f"   Net Profit: {total_return}")
            print(f"   Annual Return: {annual}")
            print(f"   Win Rate: {win_rate}")
            print(f"   Sharpe: {sharpe}")
            print(f"   Max DD: {max_dd}")
            print(f"   Total Orders: {total_trades}")
            print(f"   P/L Ratio: {pl_ratio}")

            # Show logs if available
            logs = backtest.get("logs", [])
            if logs:
                print(f"\n   --- Trade Log (last entries) ---")
                for log_entry in logs[-20:]:
                    if any(kw in str(log_entry) for kw in ["PUT ENTRY", "PANIC", "CEILING", "TRAIL", "TARGET", "BULL EXIT", "MAX HOLD", "Trade "]):
                        print(f"   {log_entry}")
        else:
            print(f"\n📊 {name}")
            print(f"   ❌ Failed to read: {bt.get('error', 'unknown')}")

    # Save updated results
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 80)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "poll":
        poll_results()
    else:
        run_all()
