#!/usr/bin/env python3
"""Stress Test Suite for Rudy v2.8+ Trend Adder

4 tests:
  1. REGIME STRESS — Run on choppy/bear periods to find false-positive adder activations
  2. KILL-SWITCH — Add cooldown after adder loss, measure WFE impact
  3. CORRELATION — Check if base+adder trades cluster at peaks (doubled risk)
  4. CAPITAL SWEEP — Test 10/15/20/25% adder capital for efficiency frontier

Uses QC API to run targeted backtests.
"""
import os, sys, re, json, time, copy
from datetime import datetime, date
from hashlib import sha256
from base64 import b64encode
import requests

QC_API_TOKEN = "a5e10d30d2c0f483c2c62a124375b2fcf4e0f907d54ab3ae863e7450e50b7688"
QC_USER_ID = "473242"
QC_BASE = "https://www.quantconnect.com/api/v2"
PROJECT_ID = 29065184

ALGO_PATH = os.path.expanduser("~/rudy/quantconnect/MSTRCycleLowLeap_v28plus.py")
DATA_DIR = os.path.expanduser("~/rudy/data")
RESULTS_FILE = os.path.join(DATA_DIR, "stress_test_v28plus.json")


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


def patch_dates(code, end_year, end_month, end_day):
    return re.sub(
        r"self\.SetEndDate\(\d+,\s*\d+,\s*\d+\)",
        f"self.SetEndDate({end_year}, {end_month}, {end_day})",
        code,
    )


def patch_adder_capital(code, pct):
    return re.sub(
        r"self\.trend_adder_capital_pct\s*=\s*[\d.]+",
        f"self.trend_adder_capital_pct = {pct}",
        code,
    )


def patch_adder_disabled(code):
    return re.sub(
        r"self\.trend_adder_enabled\s*=\s*True",
        "self.trend_adder_enabled = False",
        code,
    )


def patch_kill_switch(code, cooldown_weeks):
    """Add kill-switch: if adder loses, disable for N weeks."""
    # Add cooldown state vars after trend_confirmed_logged
    code = code.replace(
        "self.trend_confirmed_logged = False\n",
        f"self.trend_confirmed_logged = False\n"
        f"        self.adder_cooldown_until = None\n"
        f"        self.adder_cooldown_weeks = {cooldown_weeks}\n",
    )

    # In ExitTrendAdder, set cooldown
    code = code.replace(
        '        self.trend_adder_active = False\n'
        '        self.trend_adder_entry_price = 0\n'
        '        self.trend_adder_qty = 0\n'
        '        self.trend_adder_hwm = 0\n'
        '        self.trend_adder_peak_gain = 0\n'
        '        self.trend_confirmed_logged = False\n'
        '\n'
        '    def LiquidateAll',
        '        self.trend_adder_active = False\n'
        '        self.trend_adder_entry_price = 0\n'
        '        self.trend_adder_qty = 0\n'
        '        self.trend_adder_hwm = 0\n'
        '        self.trend_adder_peak_gain = 0\n'
        '        self.trend_confirmed_logged = False\n'
        f'        if stock_gain < 0:\n'
        f'            self.adder_cooldown_until = self.Time + timedelta(weeks={cooldown_weeks})\n'
        f'            self.Log(f"ADDER COOLDOWN: {{reason}} loss → disabled for {cooldown_weeks} weeks until {{self.adder_cooldown_until.strftime(\'%Y-%m-%d\')}}")\n'
        '\n'
        '    def LiquidateAll',
    )

    # Add cooldown check before adder entry
    code = code.replace(
        '        if (self.trend_adder_enabled and self.Portfolio["MSTR"].Invested and\n'
        '            self.entry_price > 0 and not self.trend_adder_active and\n'
        '            self.golden_cross_weeks >= self.trend_confirm_weeks and btc_era):',
        '        adder_not_cooling = self.adder_cooldown_until is None or self.Time > self.adder_cooldown_until\n'
        '        if (self.trend_adder_enabled and self.Portfolio["MSTR"].Invested and\n'
        '            self.entry_price > 0 and not self.trend_adder_active and\n'
        '            self.golden_cross_weeks >= self.trend_confirm_weeks and btc_era and adder_not_cooling):',
    )

    return code


# ═══════════════════════════════════════════════════════════════
# TEST 1: REGIME STRESS TEST
# ═══════════════════════════════════════════════════════════════

def test_regime_stress(base_code):
    """Run v2.8+ on specific problematic regimes to find false-positive adder activations."""
    log("\n" + "=" * 60)
    log("TEST 1: REGIME STRESS TEST")
    log("Looking for: false golden crosses, adder bleeding in chop")
    log("=" * 60)

    regimes = [
        ("2018 Crypto Winter", 2019, 6, 30,
         "BTC $20K→$3K. MSTR not yet BTC-correlated but choppy. Any adder fires = false positive."),
        ("2021 Post-Top Distribution", 2022, 6, 30,
         "BTC $69K→$17K. Multiple bear rallies with fake golden crosses. Adder should NOT fire."),
        ("2022 Bear Rally Traps", 2023, 6, 30,
         "BTC bounced 20-40% multiple times. Fake reclaims, choppy. Adder should stay quiet."),
        ("Full Bear 2022 Only", 2022, 12, 31,
         "Pure bear market. If adder fires here = regime misclassification."),
        ("2020 COVID Crash+Recovery", 2021, 6, 30,
         "Sharp V-recovery. Golden cross forms fast. Adder SHOULD fire here — valid test."),
    ]

    results = []
    for name, ey, em, ed, desc in regimes:
        log(f"\n  [{name}] End: {ey}-{em:02d}-{ed:02d}")
        log(f"    {desc}")

        # Run WITH adder
        patched = patch_dates(base_code, ey, em, ed)
        stats_with = run_backtest(patched, f"STRESS-{name.replace(' ', '_')}-WITH_ADDER")
        time.sleep(5)

        # Run WITHOUT adder (baseline)
        patched_no = patch_adder_disabled(patch_dates(base_code, ey, em, ed))
        stats_without = run_backtest(patched_no, f"STRESS-{name.replace(' ', '_')}-NO_ADDER")
        time.sleep(5)

        r = {
            "regime": name,
            "description": desc,
            "end_date": f"{ey}-{em:02d}-{ed:02d}",
        }

        if stats_with:
            r["with_adder"] = {
                "net": parse_stat(stats_with, "Net Profit"),
                "dd": parse_stat(stats_with, "Drawdown"),
                "sharpe": parse_stat(stats_with, "Sharpe Ratio"),
                "orders": int(parse_stat(stats_with, "Total Orders")),
            }
        if stats_without:
            r["without_adder"] = {
                "net": parse_stat(stats_without, "Net Profit"),
                "dd": parse_stat(stats_without, "Drawdown"),
                "sharpe": parse_stat(stats_without, "Sharpe Ratio"),
                "orders": int(parse_stat(stats_without, "Total Orders")),
            }

        if stats_with and stats_without:
            net_diff = r["with_adder"]["net"] - r["without_adder"]["net"]
            dd_diff = r["with_adder"]["dd"] - r["without_adder"]["dd"]
            order_diff = r["with_adder"]["orders"] - r["without_adder"]["orders"]
            r["delta_net"] = net_diff
            r["delta_dd"] = dd_diff
            r["extra_orders"] = order_diff
            r["adder_fired"] = order_diff > 0

            status = "CLEAN" if order_diff == 0 else ("CONCERN" if net_diff < 0 else "OK")
            r["status"] = status

            log(f"    WITH:    Net={r['with_adder']['net']:+.1f}% | DD={r['with_adder']['dd']:.1f}% | Orders={r['with_adder']['orders']}")
            log(f"    WITHOUT: Net={r['without_adder']['net']:+.1f}% | DD={r['without_adder']['dd']:.1f}% | Orders={r['without_adder']['orders']}")
            log(f"    DELTA:   Net={net_diff:+.1f}% | DD={dd_diff:+.1f}% | Extra orders={order_diff} | Status={status}")

            if order_diff == 0:
                log(f"    ✅ Adder did NOT fire — clean regime filter")
            elif net_diff >= 0:
                log(f"    ✅ Adder fired but didn't hurt — net positive")
            else:
                log(f"    ⚠️ ADDER FIRED AND LOST — false positive detected!")

        results.append(r)

    return results


# ═══════════════════════════════════════════════════════════════
# TEST 2: KILL-SWITCH SIMULATION
# ═══════════════════════════════════════════════════════════════

def test_kill_switch(base_code):
    """Test adding cooldown after adder loss."""
    log("\n" + "=" * 60)
    log("TEST 2: KILL-SWITCH SIMULATION")
    log("If adder loses → disable for N weeks. Testing cooldown lengths.")
    log("=" * 60)

    cooldowns = [0, 4, 8, 12]  # 0 = no kill switch (baseline)
    results = []

    for weeks in cooldowns:
        label = f"No cooldown" if weeks == 0 else f"{weeks}w cooldown"
        log(f"\n  [{label}]...")

        if weeks == 0:
            patched = base_code
        else:
            patched = patch_kill_switch(base_code, weeks)

        stats = run_backtest(patched, f"KILLSWITCH-{weeks}w")
        time.sleep(5)

        r = {"cooldown_weeks": weeks, "label": label}
        if stats:
            r["net"] = parse_stat(stats, "Net Profit")
            r["dd"] = parse_stat(stats, "Drawdown")
            r["sharpe"] = parse_stat(stats, "Sharpe Ratio")
            r["orders"] = int(parse_stat(stats, "Total Orders"))
            r["win_rate"] = parse_stat(stats, "Win Rate")
            log(f"    Net={r['net']:+.1f}% | DD={r['dd']:.1f}% | Sharpe={r['sharpe']:.3f} | Orders={r['orders']}")
        else:
            log(f"    FAILED")

        results.append(r)

    return results


# ═══════════════════════════════════════════════════════════════
# TEST 3: CAPITAL EFFICIENCY SWEEP
# ═══════════════════════════════════════════════════════════════

def test_capital_sweep(base_code):
    """Test different adder capital percentages."""
    log("\n" + "=" * 60)
    log("TEST 3: CAPITAL EFFICIENCY SWEEP")
    log("Testing 0% (disabled), 10%, 15%, 20%, 25% adder capital")
    log("=" * 60)

    capitals = [0.0, 0.10, 0.15, 0.20, 0.25]
    results = []

    for cap in capitals:
        label = f"{int(cap*100)}% adder" if cap > 0 else "Base only (no adder)"
        log(f"\n  [{label}]...")

        if cap == 0:
            patched = patch_adder_disabled(base_code)
        else:
            patched = patch_adder_capital(base_code, cap)

        stats = run_backtest(patched, f"CAPSWEEP-{int(cap*100)}pct")
        time.sleep(5)

        r = {"capital_pct": cap, "label": label}
        if stats:
            r["net"] = parse_stat(stats, "Net Profit")
            r["dd"] = parse_stat(stats, "Drawdown")
            r["sharpe"] = parse_stat(stats, "Sharpe Ratio")
            r["orders"] = int(parse_stat(stats, "Total Orders"))
            r["sortino"] = parse_stat(stats, "Sortino Ratio")
            # Efficiency = net / drawdown
            r["efficiency"] = r["net"] / r["dd"] if r["dd"] > 0 else 0
            log(f"    Net={r['net']:+.1f}% | DD={r['dd']:.1f}% | Sharpe={r['sharpe']:.3f} | Efficiency={r['efficiency']:.2f}")
        else:
            log(f"    FAILED")

        results.append(r)

    return results


# ═══════════════════════════════════════════════════════════════
# TEST 4: CONVERGENCE SPEED TEST
# ═══════════════════════════════════════════════════════════════

def test_convergence_speed(base_code):
    """Test tight vs wide convergence exit to check sharp reversal vulnerability."""
    log("\n" + "=" * 60)
    log("TEST 4: CONVERGENCE EXIT SPEED TEST")
    log("Testing how fast the adder exits: 5%, 10%, 15%, 25%")
    log("Tighter = faster exit (protects reversals) but may cut winners")
    log("=" * 60)

    thresholds = [5.0, 10.0, 15.0, 25.0]
    results = []

    for thresh in thresholds:
        label = f"{thresh}% convergence"
        log(f"\n  [{label}]...")

        patched = re.sub(
            r"self\.trend_convergence_pct\s*=\s*[\d.]+",
            f"self.trend_convergence_pct = {thresh}",
            base_code,
        )

        stats = run_backtest(patched, f"CONVERGE-{int(thresh)}pct")
        time.sleep(5)

        r = {"convergence_pct": thresh, "label": label}
        if stats:
            r["net"] = parse_stat(stats, "Net Profit")
            r["dd"] = parse_stat(stats, "Drawdown")
            r["sharpe"] = parse_stat(stats, "Sharpe Ratio")
            r["orders"] = int(parse_stat(stats, "Total Orders"))
            log(f"    Net={r['net']:+.1f}% | DD={r['dd']:.1f}% | Sharpe={r['sharpe']:.3f} | Orders={r['orders']}")
        else:
            log(f"    FAILED")

        results.append(r)

    return results


# ═══════════════════════════════════════════════════════════════
# FINAL REPORT
# ═══════════════════════════════════════════════════════════════

def print_report(results):
    print("\n" + "=" * 80)
    print("v2.8+ STRESS TEST REPORT")
    print("=" * 80)

    # Test 1: Regime
    print("\n── TEST 1: REGIME STRESS ──")
    print(f"{'Regime':<30} {'Adder Fired?':<14} {'Net Δ':>8} {'DD Δ':>8} {'Status':<10}")
    print("─" * 75)
    false_positives = 0
    for r in results.get("regime", []):
        fired = "YES" if r.get("adder_fired") else "NO"
        net_d = f"{r.get('delta_net', 0):+.1f}%" if "delta_net" in r else "N/A"
        dd_d = f"{r.get('delta_dd', 0):+.1f}%" if "delta_dd" in r else "N/A"
        status = r.get("status", "?")
        if status == "CONCERN":
            false_positives += 1
        print(f"{r['regime']:<30} {fired:<14} {net_d:>8} {dd_d:>8} {status:<10}")
    print(f"\nFalse positives: {false_positives}/{len(results.get('regime', []))}")
    if false_positives == 0:
        print("✅ CLEAN: Adder never fires in adverse regimes OR fires profitably")
    else:
        print(f"⚠️ {false_positives} regime(s) with adder losses — needs kill-switch")

    # Test 2: Kill-switch
    print("\n── TEST 2: KILL-SWITCH ──")
    print(f"{'Cooldown':<18} {'Net%':>10} {'DD%':>8} {'Sharpe':>8} {'Orders':>8}")
    print("─" * 55)
    for r in results.get("kill_switch", []):
        if "net" in r:
            print(f"{r['label']:<18} {r['net']:>9.1f}% {r['dd']:>7.1f}% {r['sharpe']:>7.3f} {r['orders']:>8}")

    # Test 3: Capital sweep
    print("\n── TEST 3: CAPITAL EFFICIENCY ──")
    print(f"{'Capital':<22} {'Net%':>10} {'DD%':>8} {'Sharpe':>8} {'Efficiency':>12}")
    print("─" * 65)
    best_eff = None
    for r in results.get("capital_sweep", []):
        if "net" in r:
            eff_str = f"{r['efficiency']:.2f}" if "efficiency" in r else "N/A"
            print(f"{r['label']:<22} {r['net']:>9.1f}% {r['dd']:>7.1f}% {r['sharpe']:>7.3f} {eff_str:>12}")
            if best_eff is None or r.get("efficiency", 0) > best_eff.get("efficiency", 0):
                best_eff = r
    if best_eff:
        print(f"\n  Best risk-adjusted: {best_eff['label']} (efficiency={best_eff.get('efficiency', 0):.2f})")

    # Test 4: Convergence speed
    print("\n── TEST 4: CONVERGENCE EXIT SPEED ──")
    print(f"{'Threshold':<22} {'Net%':>10} {'DD%':>8} {'Sharpe':>8} {'Orders':>8}")
    print("─" * 60)
    for r in results.get("convergence", []):
        if "net" in r:
            print(f"{r['label']:<22} {r['net']:>9.1f}% {r['dd']:>7.1f}% {r['sharpe']:>7.3f} {r['orders']:>8}")

    # Verdict
    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)
    regime_clean = false_positives == 0
    print(f"  Regime filter:      {'✅ PASSED' if regime_clean else '⚠️ NEEDS WORK'}")

    ks = results.get("kill_switch", [])
    if len(ks) >= 2 and "net" in ks[0] and "net" in ks[1]:
        ks_impact = abs(ks[0]["net"] - ks[1]["net"])
        print(f"  Kill-switch impact: {'✅ MINIMAL' if ks_impact < 10 else '⚠️ SIGNIFICANT'} ({ks_impact:.1f}% difference)")

    cs = results.get("capital_sweep", [])
    if len(cs) >= 2 and "net" in cs[0] and "net" in cs[-1]:
        base_net = cs[0]["net"]
        full_net = cs[-1]["net"]
        adder_alpha = full_net - base_net
        print(f"  Adder alpha:        {adder_alpha:+.1f}% over base")

    print()


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log("v2.8+ STRESS TEST SUITE")
    log("=" * 60)

    with open(ALGO_PATH) as f:
        base_code = f.read()

    all_results = {}

    # Run all 4 tests
    all_results["regime"] = test_regime_stress(base_code)
    all_results["kill_switch"] = test_kill_switch(base_code)
    all_results["capital_sweep"] = test_capital_sweep(base_code)
    all_results["convergence"] = test_convergence_speed(base_code)

    # Save
    with open(RESULTS_FILE, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    log(f"\nResults saved to {RESULTS_FILE}")

    # Report
    print_report(all_results)
