#!/usr/bin/env python3
"""Run all 3 MSTR Cycle-Low LEAP backtests on QuantConnect (Monthly, Weekly, Daily).
Usage: python3 scripts/run_qc_backtests.py
Requires QC_USER_ID and QC_API_TOKEN environment variables.

CRITICAL: Uploads code as 'main.py' to override QC's default template.
Also deletes the default main.py before uploading to avoid conflicts.
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.expanduser("~/rudy/scripts"))
from quantconnect import (
    authenticate, create_project, add_file, compile_project,
    create_backtest, read_backtest, list_projects, log, _post
)

QC_DIR = os.path.expanduser("~/rudy/quantconnect")
DATA_DIR = os.path.expanduser("~/rudy/data")
os.makedirs(DATA_DIR, exist_ok=True)

# Each variant: (name, resolution_line)
VARIANTS = [
    ("MSTR CycleLow v2.2 Monthly", 'self.trade_resolution = "monthly"'),
    ("MSTR CycleLow v2.2 Weekly",  'self.trade_resolution = "weekly"'),
    ("MSTR CycleLow v2.2 Daily",   'self.trade_resolution = "daily"'),
]


def make_merged_algo(base_content, resolution_line):
    """Create a single main.py file with the resolution hard-coded in the base class.
    This avoids subclass + import issues on QC cloud.
    """
    # Replace the default resolution assignment with the hard-coded one
    merged = base_content.replace(
        '''if not hasattr(self, 'trade_resolution'):
            self.trade_resolution = "weekly"''',
        resolution_line
    )
    return merged


def delete_file(project_id, filename):
    """Delete a file from a QC project."""
    result = _post("files/delete", {
        "projectId": project_id,
        "name": filename,
    })
    return result


def run_all():
    # Check credentials
    if not os.environ.get("QC_USER_ID") or not os.environ.get("QC_API_TOKEN"):
        print("ERROR: Set QC_USER_ID and QC_API_TOKEN environment variables first.")
        print("  export QC_USER_ID='your_user_id'")
        print("  export QC_API_TOKEN='your_api_token'")
        sys.exit(1)

    # Authenticate
    auth = authenticate()
    if not auth.get("success"):
        print(f"Auth failed: {auth}")
        sys.exit(1)
    print("✅ Authenticated with QuantConnect")

    # Read base algorithm
    with open(os.path.join(QC_DIR, "MSTRCycleLowLeap.py"), "r") as f:
        base_content = f.read()

    results = {}

    for name, resolution_line in VARIANTS:
        print(f"\n{'='*60}")
        print(f"📊 Starting backtest: {name}")
        print(f"{'='*60}")

        # 1. Create project
        proj = create_project(name)
        if not proj.get("success"):
            print(f"  ❌ Create project failed: {proj}")
            continue
        project_id = proj.get("projects", [{}])[0].get("projectId")
        print(f"  ✅ Project created: ID {project_id}")

        # 2. Delete default main.py
        del_result = delete_file(project_id, "main.py")
        print(f"  🗑️  Deleted default main.py: {del_result.get('success', False)}")

        # 3. Create merged algorithm with resolution hard-coded
        merged_content = make_merged_algo(base_content, resolution_line)

        # 4. Upload as main.py
        result = add_file(project_id, "main.py", merged_content)
        print(f"  ✅ Uploaded merged main.py ({len(merged_content)} chars)")

        # 5. Compile
        compile_result = compile_project(project_id)
        if not compile_result.get("success"):
            print(f"  ❌ Compile failed: {compile_result}")
            continue
        compile_id = compile_result.get("compileId", "")
        state = compile_result.get("state", "")
        print(f"  ✅ Compiled: {compile_id} ({state})")

        # Wait for compilation
        if state == "InQueue":
            print(f"  ⏳ Compile queued, waiting 15s...")
            time.sleep(15)

        # 6. Run backtest
        bt = create_backtest(project_id, compile_id, f"v2.2 {name}")
        if not bt.get("success"):
            print(f"  ❌ Backtest failed to start: {bt}")
            continue
        backtest_id = bt.get("backtestId", "")
        print(f"  🚀 Backtest started: {backtest_id}")

        results[name] = {
            "project_id": project_id,
            "compile_id": compile_id,
            "backtest_id": backtest_id,
            "status": "running",
        }

    # Save results for later polling
    results_file = os.path.join(DATA_DIR, "qc_v22_backtests.json")
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n✅ Results saved to {results_file}")
    print(f"\nAll backtests launched. Check results with:")
    print(f"  python3 scripts/run_qc_backtests.py poll")

    return results


def poll_results():
    """Poll for completed backtest results."""
    results_file = os.path.join(DATA_DIR, "qc_v22_backtests.json")
    if not os.path.exists(results_file):
        print("No backtests found. Run run_qc_backtests.py first.")
        return

    with open(results_file) as f:
        results = json.load(f)

    print("\n" + "=" * 80)
    print("MSTR CYCLE-LOW LEAP v2.2 — BACKTEST RESULTS")
    print("=" * 80)

    for name, info in results.items():
        bt = read_backtest(info["project_id"], info["backtest_id"])
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

            print(f"\n📊 {name}")
            print(f"   Status: {status}")
            print(f"   Net Profit: {total_return}")
            print(f"   Annual Return: {annual}")
            print(f"   Win Rate: {win_rate}")
            print(f"   Sharpe: {sharpe}")
            print(f"   Max DD: {max_dd}")
            print(f"   Total Orders: {total_trades}")
        else:
            print(f"\n📊 {name}")
            print(f"   ❌ Failed to read: {bt.get('error', 'unknown')}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "poll":
        poll_results()
    else:
        run_all()
