#!/usr/bin/env python3
"""Execution Realism Stress Test for Rudy v2.8+ Trend Adder

Tests whether the system survives real-world execution conditions:
  1. SLIPPAGE LADDER — 0.25%, 0.5%, 0.75%, 1.0%, 1.5%, 2.0% constant slippage
  2. VOLATILITY-SCALED SLIPPAGE — Higher slippage during high-ATR periods (realistic)
  3. GAP-DOWN EXIT SIM — Entries/exits filled 1-3% worse than trigger price
  4. COMBINED WORST-CASE — Max slippage + gap fills + spread expansion

What we need to see:
  - Sharpe stays positive across all scenarios
  - Adder still improves efficiency vs base-only even under worst fills
  - Drawdown doesn't blow past 65% (institutional pain threshold)
  - WFE-equivalent ratio (stressed net / clean net) stays > 0.6

Uses QC API to run targeted backtests with modified slippage models.
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
RESULTS_FILE = os.path.join(DATA_DIR, "execution_stress_v28plus.json")

# Baseline results from previous stress test (clean 0.5% slippage)
CLEAN_NET = 126.533
CLEAN_SHARPE = 0.258
CLEAN_DD = 49.7
BASE_ONLY_NET = 55.908  # No adder


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


def patch_slippage(code, slippage_pct):
    """Replace the ConstantSlippageModel with a different slippage percentage."""
    return re.sub(
        r"ConstantSlippageModel\([\d.]+\)",
        f"ConstantSlippageModel({slippage_pct})",
        code,
    )


def patch_adder_disabled(code):
    return re.sub(
        r"self\.trend_adder_enabled\s*=\s*True",
        "self.trend_adder_enabled = False",
        code,
    )


def patch_vol_scaled_slippage(code, base_slip, vol_multiplier):
    """Replace ConstantSlippageModel with a custom volatility-scaled slippage model.

    When ATR > 1.5x its 20-day average, slippage increases by vol_multiplier.
    This simulates wider spreads and worse fills during high-volatility periods
    (exactly when the trend adder is most likely to trigger).
    """
    # Remove the existing slippage model setup
    code = re.sub(
        r"if not self\.is_live_mode:\s*\n\s*self\.SetSecurityInitializer\(lambda security: security\.SetSlippageModel\(\s*ConstantSlippageModel\([\d.]+\)\s*\)\)",
        "pass  # Slippage handled by custom model below",
        code,
    )

    # Add custom slippage model class after imports
    custom_model = f'''
class VolScaledSlippage:
    """Slippage scales with volatility — higher during momentum/gaps."""
    def __init__(self, base_pct={base_slip}, vol_mult={vol_multiplier}):
        self.base_pct = base_pct
        self.vol_mult = vol_mult

    def GetSlippageApproximation(self, asset, order):
        price = asset.Price
        if price <= 0:
            return 0
        # Use asset's volatility if available
        # Base slippage always applies; during high-vol we multiply
        # Approximate: if price moved > 3% today, consider it "high vol"
        if hasattr(asset, 'High') and hasattr(asset, 'Low') and asset.High > 0:
            intraday_range = (asset.High - asset.Low) / asset.Price
            if intraday_range > 0.03:  # >3% intraday range = high vol
                return price * self.base_pct * self.vol_mult
        return price * self.base_pct

'''
    code = code.replace(
        "from AlgorithmImports import *",
        f"from AlgorithmImports import *\n{custom_model}",
    )

    # Add the custom model initialization after SetCash
    code = code.replace(
        "pass  # Slippage handled by custom model below",
        f'self.SetSecurityInitializer(lambda security: security.SetSlippageModel(VolScaledSlippage({base_slip}, {vol_multiplier})))',
    )

    return code


def patch_gap_down_exits(code, gap_pct):
    """Simulate gap-down exits by widening stop prices.

    In real markets, when price gaps through your trailing stop,
    you get filled at the gap-open, not at the stop level.

    We simulate this by making the floor/trail checks trigger at worse prices.
    Specifically: multiply all stop distances by (1 + gap_pct).
    This means stops that trigger at -35% actually exit at -(35 + gap)%.
    """
    # Widen initial floor (makes it trigger earlier = worse exit)
    code = re.sub(
        r"self\.initial_floor_pct\s*=\s*([\d.]+)",
        lambda m: f"self.initial_floor_pct = {float(m.group(1)) - gap_pct}",
        code,
    )
    # Widen panic floor
    code = re.sub(
        r"self\.panic_floor_pct\s*=\s*(-?[\d.]+)",
        lambda m: f"self.panic_floor_pct = {float(m.group(1)) - (gap_pct * 100)}",
        code,
    )
    # Widen adder panic floor
    code = re.sub(
        r"self\.trend_adder_panic_floor\s*=\s*(-?[\d.]+)",
        lambda m: f"self.trend_adder_panic_floor = {float(m.group(1)) - (gap_pct * 100)}",
        code,
    )
    # Widen adder initial floor
    code = re.sub(
        r"self\.trend_adder_initial_floor\s*=\s*([\d.]+)",
        lambda m: f"self.trend_adder_initial_floor = {float(m.group(1)) - gap_pct}",
        code,
    )
    return code


# ═══════════════════════════════════════════════════════════════
# TEST 1: SLIPPAGE LADDER
# ═══════════════════════════════════════════════════════════════

def test_slippage_ladder(base_code):
    """Test system at increasing slippage levels."""
    log("\n" + "=" * 60)
    log("TEST 1: SLIPPAGE LADDER")
    log("How much slippage can the system absorb before edge disappears?")
    log("Current default: 0.5% (50 bps)")
    log("=" * 60)

    slippages = [0.0025, 0.005, 0.0075, 0.01, 0.015, 0.02]  # 25bps to 200bps
    results = []

    for slip in slippages:
        bps = int(slip * 10000)
        label = f"{bps}bps ({slip*100:.2f}%)"
        log(f"\n  [{label}]...")

        patched = patch_slippage(base_code, slip)
        stats = run_backtest(patched, f"SLIP-{bps}bps")
        time.sleep(5)

        r = {"slippage_pct": slip, "bps": bps, "label": label}
        if stats:
            r["net"] = parse_stat(stats, "Net Profit")
            r["dd"] = parse_stat(stats, "Drawdown")
            r["sharpe"] = parse_stat(stats, "Sharpe Ratio")
            r["orders"] = int(parse_stat(stats, "Total Orders"))
            r["sortino"] = parse_stat(stats, "Sortino Ratio")
            r["survival_ratio"] = r["net"] / CLEAN_NET if CLEAN_NET > 0 else 0
            r["still_beats_base"] = r["net"] > BASE_ONLY_NET
            log(f"    Net={r['net']:+.1f}% | DD={r['dd']:.1f}% | Sharpe={r['sharpe']:.3f} | "
                f"Survival={r['survival_ratio']:.1%} | Beats Base={'✅' if r['still_beats_base'] else '❌'}")
        else:
            log(f"    FAILED")

        results.append(r)

    return results


# ═══════════════════════════════════════════════════════════════
# TEST 2: VOLATILITY-SCALED SLIPPAGE
# ═══════════════════════════════════════════════════════════════

def test_vol_scaled_slippage(base_code):
    """Test with slippage that spikes during high-volatility periods."""
    log("\n" + "=" * 60)
    log("TEST 2: VOLATILITY-SCALED SLIPPAGE")
    log("Slippage increases during high-vol periods (when adder likely triggers)")
    log("Base = 50bps, multiplied during >3% intraday range days")
    log("=" * 60)

    configs = [
        (0.005, 1.0, "50bps flat (baseline)"),
        (0.005, 2.0, "50bps base, 2x in high-vol"),
        (0.005, 3.0, "50bps base, 3x in high-vol"),
        (0.0075, 2.0, "75bps base, 2x in high-vol"),
        (0.01, 2.0, "100bps base, 2x in high-vol"),
    ]

    results = []
    for base_slip, vol_mult, label in configs:
        log(f"\n  [{label}]...")

        patched = patch_vol_scaled_slippage(base_code, base_slip, vol_mult)
        stats = run_backtest(patched, f"VOLSLIP-{int(base_slip*10000)}bps-{vol_mult}x")
        time.sleep(5)

        r = {"base_slip": base_slip, "vol_mult": vol_mult, "label": label}
        if stats:
            r["net"] = parse_stat(stats, "Net Profit")
            r["dd"] = parse_stat(stats, "Drawdown")
            r["sharpe"] = parse_stat(stats, "Sharpe Ratio")
            r["orders"] = int(parse_stat(stats, "Total Orders"))
            r["survival_ratio"] = r["net"] / CLEAN_NET if CLEAN_NET > 0 else 0
            log(f"    Net={r['net']:+.1f}% | DD={r['dd']:.1f}% | Sharpe={r['sharpe']:.3f} | "
                f"Survival={r['survival_ratio']:.1%}")
        else:
            log(f"    FAILED")

        results.append(r)

    return results


# ═══════════════════════════════════════════════════════════════
# TEST 3: GAP-DOWN EXIT SIMULATION
# ═══════════════════════════════════════════════════════════════

def test_gap_exits(base_code):
    """Simulate gap-down exits by widening stop distances."""
    log("\n" + "=" * 60)
    log("TEST 3: GAP-DOWN EXIT SIMULATION")
    log("When price gaps through stops, you exit worse than planned.")
    log("Testing: stops trigger at 1%, 2%, 3%, 5% worse than intended")
    log("=" * 60)

    gap_sizes = [0.01, 0.02, 0.03, 0.05]
    results = []

    for gap in gap_sizes:
        label = f"{gap*100:.0f}% gap-through"
        log(f"\n  [{label}]...")

        patched = patch_gap_down_exits(base_code, gap)
        stats = run_backtest(patched, f"GAP-{int(gap*100)}pct")
        time.sleep(5)

        r = {"gap_pct": gap, "label": label}
        if stats:
            r["net"] = parse_stat(stats, "Net Profit")
            r["dd"] = parse_stat(stats, "Drawdown")
            r["sharpe"] = parse_stat(stats, "Sharpe Ratio")
            r["orders"] = int(parse_stat(stats, "Total Orders"))
            r["survival_ratio"] = r["net"] / CLEAN_NET if CLEAN_NET > 0 else 0
            log(f"    Net={r['net']:+.1f}% | DD={r['dd']:.1f}% | Sharpe={r['sharpe']:.3f} | "
                f"Survival={r['survival_ratio']:.1%}")
        else:
            log(f"    FAILED")

        results.append(r)

    return results


# ═══════════════════════════════════════════════════════════════
# TEST 4: COMBINED WORST-CASE
# ═══════════════════════════════════════════════════════════════

def test_worst_case(base_code):
    """Stack ALL execution penalties together."""
    log("\n" + "=" * 60)
    log("TEST 4: COMBINED WORST-CASE EXECUTION")
    log("Maximum realistic execution drag: high slippage + gap-through + vol scaling")
    log("=" * 60)

    scenarios = [
        ("Moderate Real", 0.0075, 0.02, "Moderate realistic: 75bps + 2% gaps"),
        ("Severe Real", 0.01, 0.03, "Severe realistic: 100bps + 3% gaps"),
        ("Apocalypse", 0.015, 0.05, "Apocalypse: 150bps + 5% gaps"),
    ]

    results = []
    for name, slip, gap, desc in scenarios:
        log(f"\n  [{desc}]...")

        patched = patch_slippage(base_code, slip)
        patched = patch_gap_down_exits(patched, gap)
        stats = run_backtest(patched, f"WORST-{name.replace(' ', '_')}")
        time.sleep(5)

        r = {"scenario": name, "slippage": slip, "gap_pct": gap, "description": desc}
        if stats:
            r["net"] = parse_stat(stats, "Net Profit")
            r["dd"] = parse_stat(stats, "Drawdown")
            r["sharpe"] = parse_stat(stats, "Sharpe Ratio")
            r["orders"] = int(parse_stat(stats, "Total Orders"))
            r["survival_ratio"] = r["net"] / CLEAN_NET if CLEAN_NET > 0 else 0
            r["still_beats_base"] = r["net"] > BASE_ONLY_NET
            log(f"    Net={r['net']:+.1f}% | DD={r['dd']:.1f}% | Sharpe={r['sharpe']:.3f} | "
                f"Survival={r['survival_ratio']:.1%} | Beats Base={'✅' if r['still_beats_base'] else '❌'}")
        else:
            log(f"    FAILED")

        results.append(r)

    # Also run base-only with moderate slippage for comparison
    log(f"\n  [Base-only at 100bps (no adder, for comparison)]...")
    patched_base = patch_adder_disabled(patch_slippage(base_code, 0.01))
    stats_base = run_backtest(patched_base, "WORST-BaseOnly-100bps")
    time.sleep(5)

    base_r = {"scenario": "Base-only 100bps", "slippage": 0.01, "gap_pct": 0, "description": "No adder, 100bps slip"}
    if stats_base:
        base_r["net"] = parse_stat(stats_base, "Net Profit")
        base_r["dd"] = parse_stat(stats_base, "Drawdown")
        base_r["sharpe"] = parse_stat(stats_base, "Sharpe Ratio")
        base_r["orders"] = int(parse_stat(stats_base, "Total Orders"))
        log(f"    Base-only: Net={base_r['net']:+.1f}% | DD={base_r['dd']:.1f}% | Sharpe={base_r['sharpe']:.3f}")
    results.append(base_r)

    return results


# ═══════════════════════════════════════════════════════════════
# FINAL REPORT
# ═══════════════════════════════════════════════════════════════

def print_report(results):
    print("\n" + "=" * 80)
    print("v2.8+ EXECUTION REALISM STRESS TEST REPORT")
    print("=" * 80)
    print(f"\nBaseline (clean): Net +{CLEAN_NET:.1f}% | Sharpe {CLEAN_SHARPE:.3f} | DD {CLEAN_DD:.1f}%")
    print(f"Base-only (no adder): Net +{BASE_ONLY_NET:.1f}%")

    # Test 1: Slippage ladder
    print("\n── TEST 1: SLIPPAGE LADDER ──")
    print(f"{'Slippage':<20} {'Net%':>8} {'DD%':>8} {'Sharpe':>8} {'Survival':>10} {'vs Base':>8}")
    print("─" * 65)
    edge_kill_bps = None
    for r in results.get("slippage_ladder", []):
        if "net" in r:
            surv = f"{r['survival_ratio']:.0%}" if "survival_ratio" in r else "?"
            beats = "✅" if r.get("still_beats_base") else "❌"
            print(f"{r['label']:<20} {r['net']:>7.1f}% {r['dd']:>7.1f}% {r['sharpe']:>7.3f} {surv:>10} {beats:>8}")
            if r.get("sharpe", 1) <= 0 and edge_kill_bps is None:
                edge_kill_bps = r["bps"]

    if edge_kill_bps:
        print(f"\n  ⚠️ Edge destroyed at {edge_kill_bps}bps slippage")
    else:
        print(f"\n  ✅ Edge survives across all slippage levels tested")

    # Test 2: Vol-scaled
    print("\n── TEST 2: VOLATILITY-SCALED SLIPPAGE ──")
    print(f"{'Config':<35} {'Net%':>8} {'DD%':>8} {'Sharpe':>8} {'Survival':>10}")
    print("─" * 72)
    for r in results.get("vol_scaled", []):
        if "net" in r:
            surv = f"{r['survival_ratio']:.0%}" if "survival_ratio" in r else "?"
            print(f"{r['label']:<35} {r['net']:>7.1f}% {r['dd']:>7.1f}% {r['sharpe']:>7.3f} {surv:>10}")

    # Test 3: Gap exits
    print("\n── TEST 3: GAP-DOWN EXIT SIMULATION ──")
    print(f"{'Gap Size':<20} {'Net%':>8} {'DD%':>8} {'Sharpe':>8} {'Survival':>10}")
    print("─" * 58)
    for r in results.get("gap_exits", []):
        if "net" in r:
            surv = f"{r['survival_ratio']:.0%}" if "survival_ratio" in r else "?"
            print(f"{r['label']:<20} {r['net']:>7.1f}% {r['dd']:>7.1f}% {r['sharpe']:>7.3f} {surv:>10}")

    # Test 4: Worst case
    print("\n── TEST 4: COMBINED WORST-CASE ──")
    print(f"{'Scenario':<30} {'Net%':>8} {'DD%':>8} {'Sharpe':>8} {'Survival':>10} {'vs Base':>8}")
    print("─" * 75)
    for r in results.get("worst_case", []):
        if "net" in r:
            surv = f"{r.get('survival_ratio', 0):.0%}" if "survival_ratio" in r else "N/A"
            beats = "✅" if r.get("still_beats_base") else ("❌" if "still_beats_base" in r else "N/A")
            print(f"{r['description'][:30]:<30} {r['net']:>7.1f}% {r['dd']:>7.1f}% {r['sharpe']:>7.3f} {surv:>10} {beats:>8}")

    # Verdict
    print("\n" + "=" * 80)
    print("EXECUTION STRESS VERDICT")
    print("=" * 80)

    slip_results = results.get("slippage_ladder", [])
    if slip_results:
        # Find max slippage where Sharpe > 0
        max_survivable = 0
        for r in slip_results:
            if "sharpe" in r and r["sharpe"] > 0:
                max_survivable = r["bps"]
        print(f"  Max survivable slippage:    {max_survivable}bps (Sharpe still positive)")

        # Check if still beats base at 100bps
        at_100 = [r for r in slip_results if r.get("bps") == 100]
        if at_100 and "still_beats_base" in at_100[0]:
            status = "✅ YES" if at_100[0]["still_beats_base"] else "❌ NO"
            print(f"  Beats base at 100bps:       {status}")

    worst = results.get("worst_case", [])
    if worst:
        moderate = [r for r in worst if r.get("scenario") == "Moderate Real"]
        if moderate and "sharpe" in moderate[0]:
            status = "✅ SURVIVES" if moderate[0]["sharpe"] > 0 else "❌ FAILS"
            print(f"  Moderate worst-case:        {status} (Sharpe {moderate[0]['sharpe']:.3f})")

        severe = [r for r in worst if r.get("scenario") == "Severe Real"]
        if severe and "sharpe" in severe[0]:
            status = "✅ SURVIVES" if severe[0]["sharpe"] > 0 else "⚠️ DEGRADED"
            print(f"  Severe worst-case:          {status} (Sharpe {severe[0]['sharpe']:.3f})")

        apoc = [r for r in worst if r.get("scenario") == "Apocalypse"]
        if apoc and "net" in apoc[0]:
            status = "✅ POSITIVE" if apoc[0]["net"] > 0 else "❌ NEGATIVE"
            print(f"  Apocalypse scenario:        {status} (Net {apoc[0]['net']:+.1f}%)")

    print()


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log("v2.8+ EXECUTION REALISM STRESS TEST")
    log("=" * 60)
    log(f"Clean baseline: +{CLEAN_NET:.1f}% | Sharpe {CLEAN_SHARPE} | DD {CLEAN_DD}%")
    log(f"Base-only (no adder): +{BASE_ONLY_NET:.1f}%")

    with open(ALGO_PATH) as f:
        base_code = f.read()

    all_results = {}

    # Run all 4 tests
    all_results["slippage_ladder"] = test_slippage_ladder(base_code)
    all_results["vol_scaled"] = test_vol_scaled_slippage(base_code)
    all_results["gap_exits"] = test_gap_exits(base_code)
    all_results["worst_case"] = test_worst_case(base_code)

    # Save
    with open(RESULTS_FILE, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    log(f"\nResults saved to {RESULTS_FILE}")

    # Report
    print_report(all_results)
