#!/usr/bin/env python3
"""FINAL Stress Test Battery for Rudy v2.8+ Trend Adder

The "break it one more time" suite. Tests the failure modes that haven't been
covered yet — the subtle ones that separate real edge from survivorship bias.

TESTS:
  1. ANTI-TREND REGIME — Force adder to fire on weak signals (confirm=1,2 weeks)
     to simulate "trends that fail after confirmation"
  2. EXPOSURE STACKING — Push adder capital to 35/40/50% to find the DD cliff
  3. START-DATE SENSITIVITY — Multiple start dates to detect path dependency
     and single-trade dependency
  4. PARAMETER PERTURBATION — Randomly jitter ALL params ±20% to test stability
  5. RESOLUTION SENSITIVITY — Daily vs Weekly evaluation to detect timeframe fragility
  6. ADDER ENTRY TIMING — What if adder enters 2/4/8 weeks late? (momentum decay)

Uses QC API for all tests.
"""
import os, sys, re, json, time, random, copy
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
RESULTS_FILE = os.path.join(DATA_DIR, "final_stress_v28plus.json")

# Baselines
CLEAN_NET = 126.533
CLEAN_SHARPE = 0.258
CLEAN_DD = 49.7
BASE_ONLY_NET = 55.908


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


def patch_param(code, param_name, value):
    """Generic parameter patcher."""
    # Handle negative values
    if isinstance(value, float):
        return re.sub(
            rf"self\.{param_name}\s*=\s*-?[\d.]+",
            f"self.{param_name} = {value}",
            code,
        )
    elif isinstance(value, int):
        return re.sub(
            rf"self\.{param_name}\s*=\s*-?\d+",
            f"self.{param_name} = {value}",
            code,
        )
    return code


def patch_start_date(code, year, month=1, day=1):
    return re.sub(
        r"self\.SetStartDate\(\d+,\s*\d+,\s*\d+\)",
        f"self.SetStartDate({year}, {month}, {day})",
        code,
    )


def patch_resolution(code, resolution):
    """Switch trade_resolution."""
    return re.sub(
        r'self\.trade_resolution\s*=\s*"weekly"',
        f'self.trade_resolution = "{resolution}"',
        code,
    )


def patch_adder_disabled(code):
    return re.sub(
        r"self\.trend_adder_enabled\s*=\s*True",
        "self.trend_adder_enabled = False",
        code,
    )


def extract_stats(stats):
    """Extract standard metrics from QC stats dict."""
    if not stats:
        return None
    return {
        "net": parse_stat(stats, "Net Profit"),
        "dd": parse_stat(stats, "Drawdown"),
        "sharpe": parse_stat(stats, "Sharpe Ratio"),
        "orders": int(parse_stat(stats, "Total Orders")),
        "sortino": parse_stat(stats, "Sortino Ratio"),
        "win_rate": parse_stat(stats, "Win Rate"),
    }


# ═══════════════════════════════════════════════════════════════
# TEST 1: ANTI-TREND REGIME (False Signal Stress)
# ═══════════════════════════════════════════════════════════════

def test_anti_trend(base_code):
    """Force the adder to fire on weaker signals by reducing confirm_weeks.

    This simulates: "What if golden cross triggers but trends fail after?"
    If confirm=1 or 2 weeks fires the adder and it still works, the signal
    is robust. If it bleeds, we know the 4-week confirmation is load-bearing.
    """
    log("\n" + "=" * 60)
    log("TEST 1: ANTI-TREND REGIME / FALSE SIGNAL STRESS")
    log("Reducing confirm_weeks to force adder fires on weak signals")
    log("Tests: 'What if trends fail right after confirmation?'")
    log("=" * 60)

    configs = [
        (1, "1 week (ultra-aggressive — many false fires expected)"),
        (2, "2 weeks (aggressive — some false fires)"),
        (3, "3 weeks (moderate)"),
        (4, "4 weeks (current optimal)"),
        (6, "6 weeks (conservative)"),
        (8, "8 weeks (ultra-conservative — may miss entries)"),
    ]

    results = []
    for weeks, desc in configs:
        log(f"\n  [confirm_weeks={weeks}: {desc}]...")

        patched = patch_param(base_code, "trend_confirm_weeks", weeks)
        stats = run_backtest(patched, f"ANTITREND-confirm{weeks}w")
        time.sleep(5)

        r = {"confirm_weeks": weeks, "description": desc}
        s = extract_stats(stats)
        if s:
            r.update(s)
            r["adder_alpha"] = r["net"] - BASE_ONLY_NET
            log(f"    Net={r['net']:+.1f}% | DD={r['dd']:.1f}% | Sharpe={r['sharpe']:.3f} | "
                f"Orders={r['orders']} | Adder α={r['adder_alpha']:+.1f}%")
        else:
            log(f"    FAILED")

        results.append(r)

    return results


# ═══════════════════════════════════════════════════════════════
# TEST 2: EXPOSURE STACKING / DD CLIFF FINDER
# ═══════════════════════════════════════════════════════════════

def test_exposure_stacking(base_code):
    """Push adder capital higher to find the drawdown cliff.

    If DD increases linearly with capital = healthy convex behavior.
    If DD spikes non-linearly = exposure stacking risk confirmed.
    Also tests: at what capital level does the system become unsurvivable?
    """
    log("\n" + "=" * 60)
    log("TEST 2: EXPOSURE STACKING / DD CLIFF FINDER")
    log("How much adder capital before DD becomes unsurvivable (>65%)?")
    log("=" * 60)

    # Previous sweep was 0-25%. Now extend to extreme levels.
    capitals = [0.25, 0.30, 0.35, 0.40, 0.50, 0.60, 0.75]
    results = []

    for cap in capitals:
        label = f"{int(cap*100)}% adder capital"
        log(f"\n  [{label}]...")

        patched = patch_param(base_code, "trend_adder_capital_pct", cap)
        stats = run_backtest(patched, f"EXPOSURE-{int(cap*100)}pct")
        time.sleep(5)

        r = {"capital_pct": cap, "label": label}
        s = extract_stats(stats)
        if s:
            r.update(s)
            r["efficiency"] = r["net"] / r["dd"] if r["dd"] > 0 else 0
            r["dd_per_capital"] = r["dd"] / (cap * 100)  # DD normalized by capital deployed
            log(f"    Net={r['net']:+.1f}% | DD={r['dd']:.1f}% | Sharpe={r['sharpe']:.3f} | "
                f"Eff={r['efficiency']:.2f} | DD/Cap={r['dd_per_capital']:.2f}")
        else:
            log(f"    FAILED")

        results.append(r)

    return results


# ═══════════════════════════════════════════════════════════════
# TEST 3: START-DATE SENSITIVITY (Path Dependency)
# ═══════════════════════════════════════════════════════════════

def test_start_date_sensitivity(base_code):
    """Test different start dates to detect:
    1. Single-trade dependency (one lucky entry driving all returns)
    2. Path dependency (results change dramatically with start timing)
    3. Data snooping (system only works if started at the 'right' time)

    If returns are stable across start dates = robust.
    If they swing wildly = path dependent.
    """
    log("\n" + "=" * 60)
    log("TEST 3: START-DATE SENSITIVITY")
    log("Does the system depend on catching one specific trade?")
    log("=" * 60)

    # All need enough history for 200W SMA (first 200 weeks = ~4 years warmup)
    # So start dates before 2020 just mean longer warmup, fewer signals
    start_dates = [
        (2016, 1, 1, "2016 (original — full history)"),
        (2016, 7, 1, "2016 mid-year"),
        (2017, 1, 1, "2017 (miss early data)"),
        (2017, 7, 1, "2017 mid-year"),
        (2018, 1, 1, "2018 (miss 2016-17 entirely)"),
        (2019, 1, 1, "2019 (200W SMA barely ready by 2023)"),
    ]

    results = []
    for y, m, d, desc in start_dates:
        log(f"\n  [Start: {y}-{m:02d}-{d:02d} — {desc}]...")

        patched = patch_start_date(base_code, y, m, d)
        stats = run_backtest(patched, f"START-{y}_{m:02d}")
        time.sleep(5)

        r = {"start_year": y, "start_month": m, "description": desc}
        s = extract_stats(stats)
        if s:
            r.update(s)
            log(f"    Net={r['net']:+.1f}% | DD={r['dd']:.1f}% | Sharpe={r['sharpe']:.3f} | Orders={r['orders']}")
        else:
            log(f"    FAILED")

        results.append(r)

    return results


# ═══════════════════════════════════════════════════════════════
# TEST 4: PARAMETER PERTURBATION (Stability Under Noise)
# ═══════════════════════════════════════════════════════════════

def test_parameter_perturbation(base_code):
    """Randomly perturb ALL key parameters by ±20% simultaneously.

    This is the ultimate stability test. If the system is curve-fit,
    random perturbation will destroy returns. If it's robust, returns
    should degrade gracefully (within ~30% of baseline).

    Run 5 random perturbation trials.
    """
    log("\n" + "=" * 60)
    log("TEST 4: PARAMETER PERTURBATION (±20% random jitter)")
    log("If curve-fit, random perturbation destroys returns")
    log("If robust, returns stay within ~30% of baseline")
    log("=" * 60)

    # Parameters to perturb and their baseline values
    params = {
        "trend_confirm_weeks": (4, "int"),       # 3-5 range
        "trend_convergence_pct": (15.0, "float"), # 12-18 range
        "trend_adder_capital_pct": (0.25, "float"),  # 0.20-0.30
        "risk_capital_pct": (0.25, "float"),      # 0.20-0.30
        "initial_floor_pct": (0.65, "float"),     # 0.52-0.78
        "panic_floor_pct": (-35.0, "float"),      # -42 to -28
        "green_weeks_threshold": (2, "int"),      # 1-3
        "stoch_rsi_entry_threshold": (70, "int"), # 56-84
        "premium_cap": (1.5, "float"),            # 1.2-1.8
        "max_hold_bars": (567, "int"),            # 454-680
    }

    random.seed(42)  # Reproducible
    results = []

    for trial in range(5):
        perturbations = {}
        patched = base_code

        for param, (baseline, ptype) in params.items():
            # ±20% perturbation
            factor = 1.0 + random.uniform(-0.20, 0.20)
            new_val = baseline * factor

            if ptype == "int":
                new_val = max(1, int(round(new_val)))
            else:
                new_val = round(new_val, 4)

            perturbations[param] = {"baseline": baseline, "perturbed": new_val, "factor": factor}
            patched = patch_param(patched, param, new_val)

        log(f"\n  [Trial {trial+1}/5]")
        # Log key perturbations
        for p in ["trend_confirm_weeks", "risk_capital_pct", "initial_floor_pct"]:
            v = perturbations[p]
            log(f"    {p}: {v['baseline']} → {v['perturbed']} ({v['factor']:.2f}x)")

        stats = run_backtest(patched, f"PERTURB-trial{trial+1}")
        time.sleep(5)

        r = {"trial": trial + 1, "perturbations": perturbations}
        s = extract_stats(stats)
        if s:
            r.update(s)
            r["survival_ratio"] = r["net"] / CLEAN_NET if CLEAN_NET > 0 else 0
            log(f"    Net={r['net']:+.1f}% | DD={r['dd']:.1f}% | Sharpe={r['sharpe']:.3f} | "
                f"Survival={r['survival_ratio']:.0%}")
        else:
            log(f"    FAILED")

        results.append(r)

    return results


# ═══════════════════════════════════════════════════════════════
# TEST 5: RESOLUTION SENSITIVITY
# ═══════════════════════════════════════════════════════════════

def test_resolution_sensitivity(base_code):
    """Test daily vs weekly vs monthly trade evaluation.

    If results are similar across resolutions = signal is structural.
    If daily >> weekly = you're catching noise, not trend.
    If weekly >> daily = you need the smoothing (fragile).
    """
    log("\n" + "=" * 60)
    log("TEST 5: RESOLUTION SENSITIVITY")
    log("Testing: daily vs weekly vs monthly trade evaluation")
    log("If results diverge wildly = timeframe fragility")
    log("=" * 60)

    resolutions = [
        ("daily", "Daily evaluation"),
        ("weekly", "Weekly evaluation (default)"),
        ("monthly", "Monthly evaluation"),
    ]

    results = []
    for res, desc in resolutions:
        log(f"\n  [{desc}]...")

        patched = patch_resolution(base_code, res)
        stats = run_backtest(patched, f"RES-{res}")
        time.sleep(5)

        r = {"resolution": res, "description": desc}
        s = extract_stats(stats)
        if s:
            r.update(s)
            log(f"    Net={r['net']:+.1f}% | DD={r['dd']:.1f}% | Sharpe={r['sharpe']:.3f} | Orders={r['orders']}")
        else:
            log(f"    FAILED")

        results.append(r)

    return results


# ═══════════════════════════════════════════════════════════════
# TEST 6: ADDER ENTRY TIMING DECAY
# ═══════════════════════════════════════════════════════════════

def test_adder_timing_decay(base_code):
    """What if the adder enters late? Test with higher confirm_weeks.

    This measures momentum decay — if entering 2-4 weeks later
    kills the edge, the adder is timing-dependent (fragile).
    If it degrades slowly, the trend leg is long enough to absorb delay.
    """
    log("\n" + "=" * 60)
    log("TEST 6: ADDER ENTRY TIMING DECAY")
    log("What happens if adder enters late? (higher confirm threshold)")
    log("Measures: does the trend leg outlast the delay?")
    log("=" * 60)

    delays = [
        (4, 0, "4w confirm + 0w delay (baseline)"),
        (6, 0, "6w confirm (2w later)"),
        (8, 0, "8w confirm (4w later)"),
        (10, 0, "10w confirm (6w later)"),
        (12, 0, "12w confirm (8w later)"),
        (16, 0, "16w confirm (12w later — extreme)"),
    ]

    results = []
    for confirm, delay, desc in delays:
        log(f"\n  [{desc}]...")

        patched = patch_param(base_code, "trend_confirm_weeks", confirm)
        stats = run_backtest(patched, f"TIMING-{confirm}w")
        time.sleep(5)

        r = {"confirm_weeks": confirm, "delay_weeks": confirm - 4, "description": desc}
        s = extract_stats(stats)
        if s:
            r.update(s)
            r["adder_alpha"] = r["net"] - BASE_ONLY_NET
            r["alpha_retention"] = r["adder_alpha"] / (CLEAN_NET - BASE_ONLY_NET) * 100 if (CLEAN_NET - BASE_ONLY_NET) > 0 else 0
            log(f"    Net={r['net']:+.1f}% | Sharpe={r['sharpe']:.3f} | "
                f"Adder α={r['adder_alpha']:+.1f}% | α retention={r['alpha_retention']:.0f}%")
        else:
            log(f"    FAILED")

        results.append(r)

    return results


# ═══════════════════════════════════════════════════════════════
# FINAL REPORT
# ═══════════════════════════════════════════════════════════════

def print_report(results):
    print("\n" + "=" * 80)
    print("v2.8+ FINAL STRESS TEST REPORT")
    print("=" * 80)
    print(f"Baseline: Net +{CLEAN_NET:.1f}% | Sharpe {CLEAN_SHARPE} | DD {CLEAN_DD}%")

    # Test 1: Anti-trend
    print("\n── TEST 1: ANTI-TREND / FALSE SIGNAL STRESS ──")
    print(f"{'Confirm Weeks':<12} {'Net%':>8} {'DD%':>8} {'Sharpe':>8} {'Orders':>8} {'Adder α':>10}")
    print("─" * 58)
    for r in results.get("anti_trend", []):
        if "net" in r:
            alpha = f"{r.get('adder_alpha', 0):+.1f}%" if "adder_alpha" in r else "?"
            print(f"{r['confirm_weeks']:<12} {r['net']:>7.1f}% {r['dd']:>7.1f}% {r['sharpe']:>7.3f} {r['orders']:>8} {alpha:>10}")

    # Check if 1-2 week confirm bleeds
    weak_confirms = [r for r in results.get("anti_trend", []) if r.get("confirm_weeks", 99) <= 2 and "sharpe" in r]
    if weak_confirms:
        bleeds = [r for r in weak_confirms if r["sharpe"] < 0]
        if bleeds:
            print(f"\n  ⚠️ Weak confirmation ({bleeds[0]['confirm_weeks']}w) BLEEDS — confirmation is load-bearing")
        else:
            print(f"\n  ✅ Even weak confirmations (1-2w) don't bleed — signal is inherently strong")

    # Test 2: Exposure stacking
    print("\n── TEST 2: EXPOSURE STACKING / DD CLIFF ──")
    print(f"{'Capital':<18} {'Net%':>8} {'DD%':>8} {'Sharpe':>8} {'Efficiency':>12} {'DD/Cap':>8}")
    print("─" * 65)
    dd_cliff = None
    for r in results.get("exposure_stacking", []):
        if "net" in r:
            eff = f"{r.get('efficiency', 0):.2f}"
            ddc = f"{r.get('dd_per_capital', 0):.2f}"
            print(f"{r['label']:<18} {r['net']:>7.1f}% {r['dd']:>7.1f}% {r['sharpe']:>7.3f} {eff:>12} {ddc:>8}")
            if r.get("dd", 0) > 65 and dd_cliff is None:
                dd_cliff = r["capital_pct"]

    if dd_cliff:
        print(f"\n  ⚠️ DD cliff found at {int(dd_cliff*100)}% adder capital (DD > 65%)")
    else:
        print(f"\n  ✅ No DD cliff found — system scales to {int(results.get('exposure_stacking', [{}])[-1].get('capital_pct', 0)*100)}% without breaking")

    # Test 3: Start-date sensitivity
    print("\n── TEST 3: START-DATE SENSITIVITY ──")
    print(f"{'Start Date':<25} {'Net%':>8} {'DD%':>8} {'Sharpe':>8} {'Orders':>8}")
    print("─" * 60)
    nets = []
    for r in results.get("start_date", []):
        if "net" in r:
            print(f"{r['description'][:25]:<25} {r['net']:>7.1f}% {r['dd']:>7.1f}% {r['sharpe']:>7.3f} {r['orders']:>8}")
            nets.append(r["net"])

    if len(nets) >= 2:
        spread = max(nets) - min(nets)
        cv = (max(nets) - min(nets)) / (sum(nets) / len(nets)) * 100 if sum(nets) > 0 else 999
        print(f"\n  Net range: {min(nets):.1f}% to {max(nets):.1f}% (spread: {spread:.1f}%)")
        if cv < 50:
            print(f"  ✅ Low path dependency (CV={cv:.0f}%)")
        else:
            print(f"  ⚠️ Moderate path dependency (CV={cv:.0f}%) — results vary with start date")

    # Test 4: Parameter perturbation
    print("\n── TEST 4: PARAMETER PERTURBATION (±20%) ──")
    print(f"{'Trial':<8} {'Net%':>8} {'DD%':>8} {'Sharpe':>8} {'Survival':>10}")
    print("─" * 48)
    survivals = []
    for r in results.get("perturbation", []):
        if "net" in r:
            surv = f"{r.get('survival_ratio', 0):.0%}"
            print(f"Trial {r['trial']:<3} {r['net']:>7.1f}% {r['dd']:>7.1f}% {r['sharpe']:>7.3f} {surv:>10}")
            survivals.append(r.get("survival_ratio", 0))

    if survivals:
        avg_surv = sum(survivals) / len(survivals)
        min_surv = min(survivals)
        all_positive = all(r.get("sharpe", 0) > 0 for r in results.get("perturbation", []) if "sharpe" in r)
        print(f"\n  Avg survival: {avg_surv:.0%} | Min survival: {min_surv:.0%}")
        if all_positive and avg_surv > 0.6:
            print(f"  ✅ Robust under perturbation — NOT curve-fit")
        elif all_positive:
            print(f"  ⚠️ Survives but degrades significantly under perturbation")
        else:
            print(f"  ❌ Some trials go negative — parameter sensitivity detected")

    # Test 5: Resolution sensitivity
    print("\n── TEST 5: RESOLUTION SENSITIVITY ──")
    print(f"{'Resolution':<25} {'Net%':>8} {'DD%':>8} {'Sharpe':>8} {'Orders':>8}")
    print("─" * 55)
    for r in results.get("resolution", []):
        if "net" in r:
            print(f"{r['description']:<25} {r['net']:>7.1f}% {r['dd']:>7.1f}% {r['sharpe']:>7.3f} {r['orders']:>8}")

    # Test 6: Timing decay
    print("\n── TEST 6: ADDER ENTRY TIMING DECAY ──")
    print(f"{'Delay':<30} {'Net%':>8} {'Sharpe':>8} {'Adder α':>10} {'α Retained':>12}")
    print("─" * 72)
    for r in results.get("timing_decay", []):
        if "net" in r:
            alpha = f"{r.get('adder_alpha', 0):+.1f}%"
            retention = f"{r.get('alpha_retention', 0):.0f}%"
            print(f"{r['description'][:30]:<30} {r['net']:>7.1f}% {r['sharpe']:>7.3f} {alpha:>10} {retention:>12}")

    # Half-life calculation
    timing_results = [r for r in results.get("timing_decay", []) if "adder_alpha" in r]
    if len(timing_results) >= 2:
        baseline_alpha = timing_results[0].get("adder_alpha", 0)
        for r in timing_results:
            if r.get("adder_alpha", baseline_alpha) < baseline_alpha * 0.5:
                print(f"\n  ⚠️ Alpha half-life: ~{r['delay_weeks']} weeks delay")
                break
        else:
            print(f"\n  ✅ Alpha persists even with {timing_results[-1].get('delay_weeks', 0)}-week delay — trend legs are long")

    # ══════════════════════════════════════════════════════════
    # FINAL VERDICT
    # ══════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("FINAL VERDICT — Is This System Real?")
    print("=" * 80)

    verdicts = []

    # Anti-trend
    at = results.get("anti_trend", [])
    optimal = [r for r in at if r.get("confirm_weeks") == 4]
    aggressive = [r for r in at if r.get("confirm_weeks", 99) <= 2]
    if aggressive and all(r.get("sharpe", -1) > 0 for r in aggressive if "sharpe" in r):
        verdicts.append(("Anti-trend resilience", "✅ PASSED", "Signal strong even with weak confirmation"))
    elif optimal and optimal[0].get("sharpe", 0) > 0:
        verdicts.append(("Anti-trend resilience", "⚠️ PARTIAL", "Needs 4w confirm to filter noise"))
    else:
        verdicts.append(("Anti-trend resilience", "❌ FAILED", "Signal is fragile"))

    # Exposure
    es = results.get("exposure_stacking", [])
    if es and not dd_cliff:
        verdicts.append(("Exposure scaling", "✅ PASSED", "No DD cliff found"))
    elif dd_cliff and dd_cliff >= 0.5:
        verdicts.append(("Exposure scaling", "⚠️ OK", f"DD cliff at {int(dd_cliff*100)}%"))
    else:
        verdicts.append(("Exposure scaling", "❌ CONCERN", "DD cliff too low"))

    # Path dependency
    if nets and len(nets) >= 2:
        cv = (max(nets) - min(nets)) / (sum(nets) / len(nets)) * 100 if sum(nets) > 0 else 999
        if cv < 30:
            verdicts.append(("Path independence", "✅ PASSED", f"CV={cv:.0f}%"))
        elif cv < 60:
            verdicts.append(("Path independence", "⚠️ MODERATE", f"CV={cv:.0f}%"))
        else:
            verdicts.append(("Path independence", "❌ CONCERN", f"CV={cv:.0f}%"))

    # Perturbation
    if survivals:
        if avg_surv > 0.7 and all_positive:
            verdicts.append(("Parameter stability", "✅ PASSED", f"Avg survival {avg_surv:.0%}"))
        elif avg_surv > 0.5:
            verdicts.append(("Parameter stability", "⚠️ OK", f"Avg survival {avg_surv:.0%}"))
        else:
            verdicts.append(("Parameter stability", "❌ CONCERN", f"Avg survival {avg_surv:.0%}"))

    # Timing
    timing = results.get("timing_decay", [])
    if timing and len(timing) >= 2:
        last = timing[-1]
        if last.get("alpha_retention", 0) > 30:
            verdicts.append(("Momentum duration", "✅ PASSED", f"Alpha persists at {last.get('delay_weeks',0)}w delay"))
        else:
            verdicts.append(("Momentum duration", "⚠️ DECAYS", "Alpha requires timely entry"))

    for name, status, detail in verdicts:
        print(f"  {name:<25} {status:<12} {detail}")

    passed = sum(1 for _, s, _ in verdicts if "✅" in s)
    partial = sum(1 for _, s, _ in verdicts if "⚠️" in s)
    failed = sum(1 for _, s, _ in verdicts if "❌" in s)
    print(f"\n  Score: {passed} passed, {partial} caution, {failed} failed out of {len(verdicts)} tests")

    if failed == 0 and passed >= 3:
        print("\n  🏆 SYSTEM VALIDATED — Edge is structural, not artifactual")
    elif failed == 0:
        print("\n  ✅ SYSTEM VIABLE — Edge exists but monitor caution areas")
    else:
        print("\n  ⚠️ SYSTEM NEEDS WORK — Address failed areas before deployment")

    print()


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log("v2.8+ FINAL STRESS TEST BATTERY")
    log("=" * 60)
    log("'Break it one more time' — every angle we can think of")
    log(f"Baseline: +{CLEAN_NET:.1f}% | Sharpe {CLEAN_SHARPE} | DD {CLEAN_DD}%")

    with open(ALGO_PATH) as f:
        base_code = f.read()

    all_results = {}

    # Run all 6 tests
    all_results["anti_trend"] = test_anti_trend(base_code)
    all_results["exposure_stacking"] = test_exposure_stacking(base_code)
    all_results["start_date"] = test_start_date_sensitivity(base_code)
    all_results["perturbation"] = test_parameter_perturbation(base_code)
    all_results["resolution"] = test_resolution_sensitivity(base_code)
    all_results["timing_decay"] = test_adder_timing_decay(base_code)

    # Save
    with open(RESULTS_FILE, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    log(f"\nResults saved to {RESULTS_FILE}")

    # Report
    print_report(all_results)
