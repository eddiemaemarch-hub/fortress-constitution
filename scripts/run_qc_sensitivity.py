#!/usr/bin/env python3
"""Run MSTR Cycle-Low LEAP v2.3 Sensitivity Analysis on QuantConnect.

Two tests vs baseline (v2.3 Strict):
  Test A: Relaxed 2-of-3 core confluence (any 2 of: 200W reclaim, BTC>200W, StochRSI<70)
  Test B: Strict 3-of-3 + ATR volatility filter (only enter when ATR quiet)

Each test runs Weekly + Daily resolutions.
Baseline v2.3 results already known: Weekly +14.1%, Daily +29.9%.

Usage: python3 scripts/run_qc_sensitivity.py
       python3 scripts/run_qc_sensitivity.py poll
Requires QC_USER_ID and QC_API_TOKEN environment variables.
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

RESULTS_FILE = os.path.join(DATA_DIR, "qc_sensitivity_backtests.json")


# ═══════════════════════════════════════════════════════════════
# PATCHES: These modify the base algo to create test variants
# ═══════════════════════════════════════════════════════════════

# --- Test A: Relaxed 2-of-3 Core Confluence ---
# Replace the strict AND logic with 2-of-3 scoring on core conditions.
# Secondary filters (premium, MACD div, cycle, era) stay strict.

STRICT_ENTRY_BLOCK = '''        # ── FULL ENTRY CONFLUENCE ──
        all_filters = (
            self.is_armed and           # 200W dip+reclaim armed
            btc_above_200w and          # BTC > 200W MA
            stoch_rsi_ok and            # StochRSI < 70
            premium_expanding and       # Premium not contracting
            no_macd_div and             # No MACD bearish divergence
            premium_ok and              # Premium <= 2.0x
            cycle_ok and                # Haven't entered this cycle yet
            btc_era                     # Only trade in BTC strategy era (2020+)
        )'''

RELAXED_2OF3_BLOCK = '''        # ── RELAXED 2-of-3 CORE CONFLUENCE ──
        # Core conditions: need at least 2 of 3
        core_score = sum([
            self.is_armed,       # 200W dip+reclaim armed
            btc_above_200w,      # BTC > 200W MA
            stoch_rsi_ok,        # StochRSI < 70
        ])
        core_ok = core_score >= 2

        # Secondary filters still strict
        all_filters = (
            core_ok and                 # 2-of-3 core conditions
            premium_expanding and       # Premium not contracting
            no_macd_div and             # No MACD bearish divergence
            premium_ok and              # Premium <= 2.0x
            cycle_ok and                # Haven't entered this cycle yet
            btc_era                     # Only trade in BTC strategy era (2020+)
        )'''

# --- Test B: Strict + ATR Volatility Filter ---
# Add ATR indicator in Initialize and ATR check in entry conditions.

ATR_INIT_PATCH_AFTER = '''        # For Stochastic RSI: track RSI values over 14 periods
        self.rsi_window = RollingWindow[float](14)'''

ATR_INIT_INSERT = '''
        # ── ATR Volatility Filter (only enter when market is "quiet") ──
        self.mstr_atr = self.ATR("MSTR", 14, MovingAverageType.Simple)
        self.atr_window = RollingWindow[float](30)  # 30-day ATR history for SMA'''

ATR_ONDATA_PATCH_AFTER = '''        # Update price highs window for MACD divergence
        self.price_highs_window.Add(mstr_price)'''

ATR_ONDATA_INSERT = '''
        # Update ATR window for volatility filter
        if self.mstr_atr.IsReady:
            self.atr_window.Add(self.mstr_atr.Current.Value)'''

STRICT_ATR_ENTRY_BLOCK = '''        # ── FULL ENTRY CONFLUENCE + ATR FILTER ──
        # ATR volatility filter: only enter when ATR is below 1.5x its 20-day average
        atr_quiet = True
        if self.atr_window.Count >= 20:
            current_atr = self.atr_window[0]
            atr_avg_20 = sum(self.atr_window[i] for i in range(20)) / 20
            atr_quiet = current_atr < 1.5 * atr_avg_20

        all_filters = (
            self.is_armed and           # 200W dip+reclaim armed
            btc_above_200w and          # BTC > 200W MA
            stoch_rsi_ok and            # StochRSI < 70
            premium_expanding and       # Premium not contracting
            no_macd_div and             # No MACD bearish divergence
            premium_ok and              # Premium <= 2.0x
            cycle_ok and                # Haven't entered this cycle yet
            btc_era and                 # Only trade in BTC strategy era (2020+)
            atr_quiet                   # ATR < 1.5x its 20-day SMA (quiet market)
        )'''


def make_resolution_patch(base_content, resolution):
    """Hard-code the trade resolution."""
    return base_content.replace(
        '''if not hasattr(self, 'trade_resolution'):
            self.trade_resolution = "weekly"''',
        f'self.trade_resolution = "{resolution}"'
    )


def make_test_a(base_content):
    """Patch for Test A: 2-of-3 relaxed confluence."""
    return base_content.replace(STRICT_ENTRY_BLOCK, RELAXED_2OF3_BLOCK)


def make_test_b(base_content):
    """Patch for Test B: Strict + ATR filter."""
    # 1. Add ATR indicator initialization
    patched = base_content.replace(
        ATR_INIT_PATCH_AFTER,
        ATR_INIT_PATCH_AFTER + ATR_INIT_INSERT
    )
    # 2. Add ATR window update in OnData
    patched = patched.replace(
        ATR_ONDATA_PATCH_AFTER,
        ATR_ONDATA_PATCH_AFTER + ATR_ONDATA_INSERT
    )
    # 3. Replace entry confluence with ATR-augmented version
    patched = patched.replace(STRICT_ENTRY_BLOCK, STRICT_ATR_ENTRY_BLOCK)
    return patched


def delete_file(project_id, filename):
    """Delete a file from a QC project."""
    return _post("files/delete", {"projectId": project_id, "name": filename})


# ═══════════════════════════════════════════════════════════════
# VARIANTS: (name, test_type, resolution)
# ═══════════════════════════════════════════════════════════════
VARIANTS = [
    ("v2.3 Relaxed 2of3 Weekly", "test_a", "weekly"),
    ("v2.3 Relaxed 2of3 Daily",  "test_a", "daily"),
    ("v2.3 Strict+ATR Weekly",   "test_b", "weekly"),
    ("v2.3 Strict+ATR Daily",    "test_b", "daily"),
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

    # Read base algorithm
    with open(os.path.join(QC_DIR, "MSTRCycleLowLeap.py"), "r") as f:
        base_content = f.read()

    results = {}

    for name, test_type, resolution in VARIANTS:
        print(f"\n{'='*60}")
        print(f"📊 Starting: {name}")
        print(f"{'='*60}")

        # 1. Apply resolution patch
        patched = make_resolution_patch(base_content, resolution)

        # 2. Apply test-specific patches
        if test_type == "test_a":
            patched = make_test_a(patched)
        elif test_type == "test_b":
            patched = make_test_b(patched)

        # Verify patches applied
        if test_type == "test_a" and "core_score" not in patched:
            print(f"  ❌ Test A patch failed — 'core_score' not found in output")
            continue
        if test_type == "test_b" and "atr_quiet" not in patched:
            print(f"  ❌ Test B patch failed — 'atr_quiet' not found in output")
            continue

        # 3. Create project
        proj = create_project(name)
        if not proj.get("success"):
            print(f"  ❌ Create project failed: {proj}")
            continue
        project_id = proj.get("projects", [{}])[0].get("projectId")
        print(f"  ✅ Project created: ID {project_id}")

        # 4. Delete default main.py
        del_result = delete_file(project_id, "main.py")
        print(f"  🗑️  Deleted default main.py: {del_result.get('success', False)}")

        # 5. Upload patched algo
        result = add_file(project_id, "main.py", patched)
        print(f"  ✅ Uploaded patched main.py ({len(patched)} chars)")

        # 6. Compile
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

        # 7. Run backtest
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
            "test_type": test_type,
            "resolution": resolution,
            "status": "running",
        }

    # Save results
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n✅ Results saved to {RESULTS_FILE}")
    print(f"\nAll backtests launched. Poll with:")
    print(f"  python3 scripts/run_qc_sensitivity.py poll")

    return results


def poll_results():
    """Poll for completed backtest results."""
    if not os.path.exists(RESULTS_FILE):
        print("No sensitivity backtests found. Run this script first.")
        return

    with open(RESULTS_FILE) as f:
        results = json.load(f)

    print("\n" + "=" * 80)
    print("MSTR CYCLE-LOW LEAP v2.3 — SENSITIVITY ANALYSIS RESULTS")
    print("=" * 80)
    print(f"\n{'BASELINE (v2.3 Strict 3/3):':40s} Weekly +14.1% | Daily +29.9%")
    print("-" * 80)

    for name, info in results.items():
        bt_id = info.get("backtest_id", "")
        if not bt_id:
            # Try listing backtests to find completed ones
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
        else:
            print(f"\n📊 {name}")
            print(f"   ❌ Failed to read: {bt.get('error', 'unknown')}")

    print("\n" + "=" * 80)
    print("COMPARISON:")
    print("  If Relaxed 2/3 > Strict → loosen entry (edge is in any 2 factors)")
    print("  If Relaxed 2/3 < Strict → keep strict (3rd filter prevents losers)")
    print("  If Strict+ATR > Strict  → add ATR (quiet markets = better entries)")
    print("  If Strict+ATR < Strict  → skip ATR (filtering too many good entries)")
    print("=" * 80)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "poll":
        poll_results()
    else:
        run_all()
