#!/usr/bin/env python3
"""Rudy v2.5 Sensitivity Sweep — Backtest EVERY idea.

Variants tested (all on Weekly + Daily resolution):

BASELINE: v2.4 Production (Strict+ATR+Reentry, premium_cap=1.5x)
  - Already known: Weekly +44.6%, Daily +42.3%

GROUP A: PREMIUM CAP TUNING
  A1: Premium cap 2.0x (Perplexity/Grok recommendation)
  A2: Premium cap 2.5x (aggressive — catch more entries)
  A3: Premium cap 1.0x (ultra-strict — only buy at/below NAV)

GROUP B: RE-ENTRY CAPS
  B1: Max 2 re-entries per cycle (Grok recommendation)
  B2: Max 3 re-entries per cycle
  B3: No re-entry (original v2.3 cycle lock)

GROUP C: IV GUARDRAIL (Perplexity recommendation)
  C1: Skip entry if ATR > 80th percentile of 252-day range (proxy for high IV)
  C2: Skip entry if ATR > 90th percentile (less strict)

GROUP D: DELTA STAGGERING (Perplexity/Grok recommendation)
  D1: Mixed multiplier: 25% at 5x, 50% at 10x, 25% at 15x (avg ~10x)
  D2: Conservative multiplier: 50% at 5x, 50% at 10x (avg 7.5x)

GROUP E: PANIC FLOOR TUNING
  E1: Panic floor -25% (tighter — cut losers faster)
  E2: Panic floor -50% (looser — give more room)
  E3: No panic floor (let ladders handle everything)

GROUP F: ATR MULTIPLIER TUNING
  F1: ATR < 1.2x SMA (stricter quiet filter)
  F2: ATR < 2.0x SMA (looser quiet filter)
  F3: No ATR filter (remove entirely)

GROUP G: COMBINED BEST IDEAS
  G1: Premium 2.0x + 2 re-entry cap + IV guardrail (80th pctl)
  G2: Premium 2.0x + panic floor -25% + ATR 1.2x
  G3: Premium 2.0x + mixed multiplier + 2 re-entry cap

Total: 18 variants × 2 resolutions = 36 backtests
(Plus baseline = 38 total, but baseline already known)

Usage:
  QC_USER_ID=473242 QC_API_TOKEN=xxx python3 scripts/run_qc_v25_sweep.py
  QC_USER_ID=473242 QC_API_TOKEN=xxx python3 scripts/run_qc_v25_sweep.py poll
"""
import os
import sys
import json
import time
import copy

sys.path.insert(0, os.path.expanduser("~/rudy/scripts"))
from quantconnect import (
    authenticate, create_project, add_file, compile_project,
    create_backtest, read_backtest, log, _post
)

QC_DIR = os.path.expanduser("~/rudy/quantconnect")
DATA_DIR = os.path.expanduser("~/rudy/data")
os.makedirs(DATA_DIR, exist_ok=True)
RESULTS_FILE = os.path.join(DATA_DIR, "qc_v25_sweep.json")


def read_base_algo():
    with open(os.path.join(QC_DIR, "MSTRCycleLowLeap.py")) as f:
        return f.read()


def patch_resolution(code, resolution):
    """Set trade resolution."""
    return code.replace(
        """if not hasattr(self, 'trade_resolution'):
            self.trade_resolution = "weekly\"""",
        f'self.trade_resolution = "{resolution}"'
    )


def patch_premium_cap(code, cap):
    """Change premium cap."""
    return code.replace(
        "self.premium_cap = 1.5",
        f"self.premium_cap = {cap}"
    )


def patch_reentry_cap(code, max_reentries):
    """Cap re-entries per cycle. Replace unlimited re-entry with counter."""
    if max_reentries == 0:
        # No re-entry: remove the re-entry line in RecordExit
        return code.replace(
            "self.already_entered_this_cycle = False  # v2.4: ALLOW RE-ENTRY after stop-out",
            "# v2.5: NO RE-ENTRY (cycle lock stays)"
        )
    # Add counter-based re-entry
    # 1. Add counter in Initialize
    code = code.replace(
        "self.already_entered_this_cycle = False\n",
        f"self.already_entered_this_cycle = False\n        self.reentry_count = 0\n        self.max_reentries = {max_reentries}\n",
        1  # only first occurrence
    )
    # 2. Replace unlimited re-entry with capped
    code = code.replace(
        "self.already_entered_this_cycle = False  # v2.4: ALLOW RE-ENTRY after stop-out",
        "self.reentry_count += 1\n"
        "        if self.reentry_count < self.max_reentries:\n"
        "            self.already_entered_this_cycle = False  # v2.5: capped re-entry\n"
        "        # else: stay locked out"
    )
    return code


def patch_iv_guardrail(code, percentile):
    """Add IV guardrail using ATR percentile as proxy.
    Skip entry if current ATR is above the Nth percentile of its 252-day range."""
    # We already have atr_window with 30 days. Extend to 252.
    code = code.replace(
        "self.atr_window = RollingWindow[float](30)",
        "self.atr_window = RollingWindow[float](260)"
    )
    # Add IV check after ATR quiet check
    iv_check = f"""
        # ── IV Guardrail: skip entry if ATR in top {100-percentile}% of 252-day range ──
        iv_ok = True
        if self.atr_window.Count >= 252:
            atr_values = sorted([self.atr_window[i] for i in range(252)])
            threshold_idx = int(len(atr_values) * {percentile / 100.0})
            iv_ok = self.atr_window[0] < atr_values[min(threshold_idx, len(atr_values)-1)]
"""
    # Insert before the all_filters block
    code = code.replace(
        "        # ── FULL ENTRY CONFLUENCE (v2.4: + ATR filter, re-entry allowed) ──",
        iv_check + "\n        # ── FULL ENTRY CONFLUENCE (v2.5: + IV guardrail) ──"
    )
    # Add iv_ok to filters
    code = code.replace(
        "            atr_quiet                   # ATR < 1.5x its 20-day SMA (quiet market)",
        "            atr_quiet and               # ATR < 1.5x its 20-day SMA (quiet market)\n"
        "            iv_ok                       # IV guardrail: ATR not in extreme range"
    )
    return code


def patch_mixed_multiplier(code, profile="mixed"):
    """Replace single 10x multiplier with staggered delta simulation.
    mixed:        25% at 5x, 50% at 10x, 25% at 15x = avg 10x
    conservative: 50% at 5x, 50% at 10x = avg 7.5x
    """
    if profile == "mixed":
        new_method = '''    def GetDynamicLeapMultiplier(self, premium):
        """v2.5 Mixed delta multiplier: 25% at 5x + 50% at 10x + 25% at 15x = avg 10x.
        Simulates staggered delta allocation across strike zones."""
        # Weighted average multiplier (constant — delta mix doesn't change with premium)
        return 0.25 * 5.0 + 0.50 * 10.0 + 0.25 * 15.0  # = 10.0'''
    else:  # conservative
        new_method = '''    def GetDynamicLeapMultiplier(self, premium):
        """v2.5 Conservative delta multiplier: 50% at 5x + 50% at 10x = avg 7.5x.
        Simulates higher-delta (safer) LEAP allocation."""
        return 0.50 * 5.0 + 0.50 * 10.0  # = 7.5'''

    # Replace the existing GetDynamicLeapMultiplier method
    import re
    code = re.sub(
        r'    def GetDynamicLeapMultiplier\(self, premium\):.*?return self\.leap_multiplier_base \* boost',
        new_method,
        code,
        flags=re.DOTALL
    )
    return code


def patch_panic_floor(code, floor_pct):
    """Change panic floor percentage. None = disable."""
    if floor_pct is None:
        # Disable panic floor entirely
        code = code.replace(
            "self.panic_floor_pct = -35.0",
            "self.panic_floor_pct = -999.0  # DISABLED"
        )
    else:
        code = code.replace(
            "self.panic_floor_pct = -35.0",
            f"self.panic_floor_pct = {floor_pct}"
        )
    return code


def patch_atr_mult(code, mult):
    """Change ATR quiet filter multiplier. None = disable filter."""
    if mult is None:
        # Remove ATR from entry confluence
        code = code.replace(
            "            atr_quiet                   # ATR < 1.5x its 20-day SMA (quiet market)\n",
            ""
        )
        # Remove trailing 'and' from cycle_ok line
        code = code.replace(
            "            btc_era and                 # Only trade in BTC strategy era (2020+)",
            "            btc_era                     # Only trade in BTC strategy era (2020+)"
        )
    else:
        code = code.replace(
            "atr_quiet = current_atr < 1.5 * atr_avg_20",
            f"atr_quiet = current_atr < {mult} * atr_avg_20"
        )
    return code


# ═══════════════════════════════════════════════════════════════
# VARIANT DEFINITIONS
# ═══════════════════════════════════════════════════════════════

def build_variants():
    """Build all variant definitions. Returns list of (name, patch_fn)."""
    variants = []

    # GROUP A: Premium Cap
    variants.append(("A1-PremCap2.0", lambda c: patch_premium_cap(c, 2.0)))
    variants.append(("A2-PremCap2.5", lambda c: patch_premium_cap(c, 2.5)))
    variants.append(("A3-PremCap1.0", lambda c: patch_premium_cap(c, 1.0)))

    # GROUP B: Re-entry Cap
    variants.append(("B1-Reentry2x", lambda c: patch_reentry_cap(c, 2)))
    variants.append(("B2-Reentry3x", lambda c: patch_reentry_cap(c, 3)))
    variants.append(("B3-NoReentry", lambda c: patch_reentry_cap(c, 0)))

    # GROUP C: IV Guardrail
    variants.append(("C1-IV80pctl", lambda c: patch_iv_guardrail(c, 80)))
    variants.append(("C2-IV90pctl", lambda c: patch_iv_guardrail(c, 90)))

    # GROUP D: Delta Staggering (multiplier profiles)
    variants.append(("D1-MixedMult", lambda c: patch_mixed_multiplier(c, "mixed")))
    variants.append(("D2-ConservMult", lambda c: patch_mixed_multiplier(c, "conservative")))

    # GROUP E: Panic Floor
    variants.append(("E1-Panic25", lambda c: patch_panic_floor(c, -25.0)))
    variants.append(("E2-Panic50", lambda c: patch_panic_floor(c, -50.0)))
    variants.append(("E3-NoPanic", lambda c: patch_panic_floor(c, None)))

    # GROUP F: ATR Multiplier
    variants.append(("F1-ATR1.2x", lambda c: patch_atr_mult(c, 1.2)))
    variants.append(("F2-ATR2.0x", lambda c: patch_atr_mult(c, 2.0)))
    variants.append(("F3-NoATR", lambda c: patch_atr_mult(c, None)))

    # GROUP G: Combined Best Ideas
    def combo_g1(c):
        c = patch_premium_cap(c, 2.0)
        c = patch_reentry_cap(c, 2)
        c = patch_iv_guardrail(c, 80)
        return c
    variants.append(("G1-Prem2+Re2+IV80", combo_g1))

    def combo_g2(c):
        c = patch_premium_cap(c, 2.0)
        c = patch_panic_floor(c, -25.0)
        c = patch_atr_mult(c, 1.2)
        return c
    variants.append(("G2-Prem2+Pan25+ATR1.2", combo_g2))

    def combo_g3(c):
        c = patch_premium_cap(c, 2.0)
        c = patch_mixed_multiplier(c, "mixed")
        c = patch_reentry_cap(c, 2)
        return c
    variants.append(("G3-Prem2+Mix+Re2", combo_g3))

    return variants


def delete_file(project_id, filename):
    return _post("files/delete", {"projectId": project_id, "name": filename})


def run_all():
    if not os.environ.get("QC_USER_ID") or not os.environ.get("QC_API_TOKEN"):
        print("ERROR: Set QC_USER_ID and QC_API_TOKEN environment variables first.")
        sys.exit(1)

    auth = authenticate()
    if not auth.get("success"):
        print(f"Auth failed: {auth}")
        sys.exit(1)
    print("✅ Authenticated with QuantConnect\n")

    base_code = read_base_algo()
    variants = build_variants()

    # Load existing results if any (for resume)
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            results = json.load(f)
        print(f"📂 Loaded {len(results)} existing results (resuming)\n")
    else:
        results = {}

    total = len(variants) * 2  # Weekly + Daily for each
    launched = 0

    for name, patch_fn in variants:
        for resolution in ["weekly", "daily"]:
            full_name = f"v25-{name}-{resolution.title()}"

            # Skip if already done
            if full_name in results and results[full_name].get("backtest_id"):
                print(f"⏭️  Skipping {full_name} (already launched)")
                continue

            print(f"\n{'='*60}")
            print(f"📊 [{launched+1}/{total}] {full_name}")
            print(f"{'='*60}")

            # Apply patches
            try:
                patched = patch_resolution(base_code, resolution)
                patched = patch_fn(patched)
            except Exception as e:
                print(f"  ❌ Patch failed: {e}")
                results[full_name] = {"status": "patch_error", "error": str(e)}
                continue

            # Create project
            proj = create_project(full_name)
            if not proj.get("success"):
                err = proj.get("errors", [])
                if "Too many" in str(err) or "rate" in str(err).lower():
                    print(f"  ⏳ Rate limited — waiting 15s...")
                    time.sleep(15)
                    proj = create_project(full_name)
                if not proj.get("success"):
                    print(f"  ❌ Create project failed: {proj}")
                    results[full_name] = {"status": "create_error", "error": str(proj)}
                    continue

            project_id = proj.get("projects", [{}])[0].get("projectId")
            print(f"  ✅ Project: {project_id}")

            # Delete default + upload patched
            delete_file(project_id, "main.py")
            add_file(project_id, "main.py", patched)
            print(f"  ✅ Uploaded ({len(patched)} chars)")

            # Compile
            compile_result = compile_project(project_id)
            if not compile_result.get("success"):
                print(f"  ❌ Compile failed: {compile_result}")
                results[full_name] = {"status": "compile_error", "error": str(compile_result)}
                continue

            compile_id = compile_result.get("compileId", "")
            state = compile_result.get("state", "")
            print(f"  ✅ Compiled: {state}")

            if state == "InQueue":
                print(f"  ⏳ Waiting for compile...")
                time.sleep(10)

            # Run backtest
            bt = create_backtest(project_id, compile_id, full_name)
            if not bt.get("success"):
                err = bt.get("errors", [])
                if "slow down" in str(err).lower() or "Too many" in str(err):
                    print(f"  ⏳ Rate limited — waiting 15s...")
                    time.sleep(15)
                    bt = create_backtest(project_id, compile_id, full_name)
                if not bt.get("success"):
                    print(f"  ❌ Backtest failed: {bt}")
                    results[full_name] = {"status": "backtest_error", "error": str(bt)}
                    continue

            backtest_id = bt.get("backtestId", "")
            print(f"  🚀 Backtest: {backtest_id}")

            results[full_name] = {
                "project_id": project_id,
                "compile_id": compile_id,
                "backtest_id": backtest_id,
                "resolution": resolution,
                "variant": name,
                "status": "running",
            }

            # Save after each launch
            with open(RESULTS_FILE, "w") as f:
                json.dump(results, f, indent=2)

            launched += 1

            # Brief pause between launches to avoid rate limits
            time.sleep(3)

    print(f"\n\n{'='*60}")
    print(f"✅ Launched {launched} backtests")
    print(f"{'='*60}")
    print(f"\nPoll results with:")
    print(f"  python3 scripts/run_qc_v25_sweep.py poll")


def poll_results():
    if not os.path.exists(RESULTS_FILE):
        print("No sweep results found. Run the sweep first.")
        return

    with open(RESULTS_FILE) as f:
        results = json.load(f)

    print("\n" + "=" * 100)
    print("RUDY v2.5 SENSITIVITY SWEEP — ALL RESULTS")
    print("=" * 100)
    print(f"\n{'BASELINE v2.4:':45s} Weekly +44.6% | Daily +42.3%")
    print("-" * 100)
    print(f"{'Variant':<45s} {'Net Profit':>10s} {'WR':>6s} {'MaxDD':>8s} {'P/L':>6s} {'Orders':>7s} {'Sharpe':>8s}")
    print("-" * 100)

    completed = 0
    running = 0
    errors = 0

    for name, info in sorted(results.items()):
        bt_id = info.get("backtest_id", "")
        pid = info.get("project_id", "")

        if not bt_id or not pid:
            print(f"  {name:<43s} {'ERROR':>10s}")
            errors += 1
            continue

        bt = read_backtest(pid, bt_id)
        if bt.get("success"):
            backtest = bt.get("backtest", bt)
            stats = backtest.get("statistics", {})

            net = stats.get("Net Profit", "?")
            wr = stats.get("Win Rate", "?")
            dd = stats.get("Drawdown", "?")
            pl = stats.get("Profit-Loss Ratio", "?")
            orders = stats.get("Total Orders", "?")
            sharpe = stats.get("Sharpe Ratio", "?")
            progress = backtest.get("progress", 0)

            if progress < 1.0 and net == "?":
                print(f"  {name:<43s} {'RUNNING':>10s} ({progress*100:.0f}%)")
                running += 1
            else:
                print(f"  {name:<43s} {net:>10s} {wr:>6s} {dd:>8s} {pl:>6s} {orders:>7s} {sharpe:>8s}")
                completed += 1

                # Update stored result
                info["status"] = "completed"
                info["net_profit"] = net
                info["win_rate"] = wr
                info["max_dd"] = dd
                info["pl_ratio"] = pl
                info["orders"] = orders
                info["sharpe"] = sharpe
        else:
            print(f"  {name:<43s} {'READ_ERR':>10s}")
            errors += 1

    print("-" * 100)
    print(f"\nCompleted: {completed} | Running: {running} | Errors: {errors}")

    # Save updated results
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)

    if completed > 0:
        print("\n" + "=" * 100)
        print("TOP 5 PERFORMERS (by Net Profit):")
        print("=" * 100)
        ranked = []
        for name, info in results.items():
            np_str = info.get("net_profit", "")
            if np_str and np_str != "?":
                try:
                    np_val = float(np_str.replace("%", "").replace(",", ""))
                    ranked.append((name, np_val, info))
                except:
                    pass
        ranked.sort(key=lambda x: x[1], reverse=True)
        for i, (name, val, info) in enumerate(ranked[:5]):
            print(f"  #{i+1}: {name:<43s} {val:+.1f}% | WR: {info.get('win_rate','?')} | DD: {info.get('max_dd','?')}")

    print()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "poll":
        poll_results()
    else:
        run_all()
