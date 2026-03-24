#!/usr/bin/env python3
"""Walk-Forward Analysis for Rudy v3.0 Trend Convergence — MSTR LEAP Strategy.

Splits history into anchored windows (always starting 2016-01-01 for 200W SMA warmup).
For each window: optimizes a 36-combo parameter grid on in-sample data, then tests
the best params on the next unseen 6-month out-of-sample period.

v3.0-SPECIFIC PARAMETERS (in addition to v2.8 premium/LEAP/trail):
  - convergence_threshold: Distance % between 50W EMA and 200W SMA to trigger
  - slope_lookback: Weeks to measure slope of both lines
  - green_candles_required: Consecutive green candles after convergence before entry

Outputs: Walk-Forward Efficiency (WFE), parameter stability, stitched OOS equity curve.

Usage:
    python3 walk_forward_v30.py              # Run full walk-forward
    python3 walk_forward_v30.py --resume     # Resume from checkpoint
    python3 walk_forward_v30.py --report     # Analyze existing results only
"""
import os, sys, re, json, time, argparse, copy
from datetime import datetime, date, timedelta
from hashlib import sha256
from base64 import b64encode
import requests

# ═══════════════════════════════════════════════════════════════
# QC API CONFIG
# ═══════════════════════════════════════════════════════════════
QC_API_TOKEN = "a5e10d30d2c0f483c2c62a124375b2fcf4e0f907d54ab3ae863e7450e50b7688"
QC_USER_ID = "473242"
QC_BASE = "https://www.quantconnect.com/api/v2"
PROJECT_ID = 29065184  # Reuse weekly project

ALGO_PATH = os.path.expanduser("~/rudy/quantconnect/MSTRTrendConvergence_v30.py")
DATA_DIR = os.path.expanduser("~/rudy/data")
CHECKPOINT_FILE = os.path.join(DATA_DIR, "wf_v30_checkpoint.json")
RESULTS_FILE = os.path.join(DATA_DIR, "wf_v30_results.json")
os.makedirs(DATA_DIR, exist_ok=True)


def _auth_headers():
    timestamp = str(int(time.time()))
    hashed = sha256(f"{QC_API_TOKEN}:{timestamp}".encode()).hexdigest()
    auth = b64encode(f"{QC_USER_ID}:{hashed}".encode()).decode()
    return {"Authorization": f"Basic {auth}", "Timestamp": timestamp, "Content-Type": "application/json"}


def _post(endpoint, data=None):
    for attempt in range(3):
        try:
            r = requests.post(f"{QC_BASE}/{endpoint}", headers=_auth_headers(), json=data or {}, timeout=60)
            if r.status_code == 429:
                wait = 10 * (2 ** attempt)
                log(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            return r.json()
        except Exception as e:
            if attempt < 2:
                log(f"  API error: {e}, retrying in 10s...")
                time.sleep(10)
            else:
                raise
    return {"success": False, "errors": ["Rate limit exhausted"]}


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


# ═══════════════════════════════════════════════════════════════
# PARAMETER GRID — v3.0 Convergence-Specific
# ═══════════════════════════════════════════════════════════════
# 3 convergence configs × 2 slope lookbacks × 2 green candle counts × 3 trail configs = 36 combos
#
# v3.0 KEY INSIGHT: The convergence-down exit IS the primary exit.
# Trailing stops are safety nets only. Golden cross (EMA50 > SMA200) required for entry.
# LEAP/premium fixed at v2.8 optimal (tight_conservative_tight).

CONVERGENCE_CONFIGS = {
    "tight":   {"convergence_threshold": 15.0, "divergence_threshold": 25.0},
    "medium":  {"convergence_threshold": 30.0, "divergence_threshold": 50.0},
    "wide":    {"convergence_threshold": 50.0, "divergence_threshold": 70.0},
}

SLOPE_LOOKBACKS = {
    "short": 3,   # 3 weeks
    "medium": 4,  # 4 weeks (default)
}

GREEN_CANDLES = {
    "quick": 1,   # 1 green candle
    "standard": 2,  # 2 green candles (default)
}

# v3.0: Much wider trails — convergence-down is the real exit, trails are crash safety
TRAIL_WIDTHS = {
    "minimal": [(5000, 35.0)],                                      # Nearly disabled
    "safety":  [(10000, 25.0), (5000, 35.0)],                       # Only extreme gains
    "moderate":[(10000, 20.0), (5000, 30.0), (2000, 40.0)],         # Moderate protection
}

# Fixed at walk-forward optimal from v2.8
FIXED_PREMIUM_BANDS = {"low_cap": 0.7, "fair_cap": 1.0, "elevated_cap": 1.3}
FIXED_LEAP_MULTS = {"low": 7.2, "fair": 6.5, "elevated": 4.8, "euphoric": 3.3}


def build_param_grid():
    """Generate all 36 parameter combinations (3×2×2×3)."""
    grid = []
    for cc_name, cc in CONVERGENCE_CONFIGS.items():
        for sl_name, sl in SLOPE_LOOKBACKS.items():
            for gc_name, gc in GREEN_CANDLES.items():
                for tw_name, tw in TRAIL_WIDTHS.items():
                    grid.append({
                        "name": f"{cc_name}_{sl_name}_{gc_name}_{tw_name}",
                        "convergence_threshold": cc["convergence_threshold"],
                        "divergence_threshold": cc["divergence_threshold"],
                        "slope_lookback": sl,
                        "green_candles_required": gc,
                        "trail_widths": tw_name,
                        "ladder_tiers": tw,
                        # Fixed v2.8 optimal
                        "low_cap": FIXED_PREMIUM_BANDS["low_cap"],
                        "fair_cap": FIXED_PREMIUM_BANDS["fair_cap"],
                        "elevated_cap": FIXED_PREMIUM_BANDS["elevated_cap"],
                        "low_mult": FIXED_LEAP_MULTS["low"],
                        "fair_mult": FIXED_LEAP_MULTS["fair"],
                        "elevated_mult": FIXED_LEAP_MULTS["elevated"],
                        "euphoric_mult": FIXED_LEAP_MULTS["euphoric"],
                    })
    return grid


# ═══════════════════════════════════════════════════════════════
# WALK-FORWARD WINDOWS (Anchored)
# ═══════════════════════════════════════════════════════════════

def generate_windows():
    """Generate anchored walk-forward windows.
    All start 2016-01-01 (200W SMA warmup). OOS windows are 6 months each."""
    windows = []
    is_start = date(2016, 1, 1)

    # OOS periods: 6-month blocks from Jan 2022 through Jun 2025
    oos_starts = [
        date(2022, 1, 1), date(2022, 7, 1), date(2023, 1, 1), date(2023, 7, 1),
        date(2024, 1, 1), date(2024, 7, 1), date(2025, 1, 1),
    ]

    for oos_start in oos_starts:
        is_end = oos_start - timedelta(days=1)
        if oos_start.month <= 6:
            oos_end = date(oos_start.year, 6, 30)
        else:
            oos_end = date(oos_start.year, 12, 31)

        windows.append({
            "is_start": is_start,
            "is_end": is_end,
            "oos_start": oos_start,
            "oos_end": oos_end,
            "label": f"OOS {oos_start.strftime('%b%y')}-{oos_end.strftime('%b%y')}",
        })

    return windows


# ═══════════════════════════════════════════════════════════════
# ALGO PATCHING — v3.0 Convergence Parameters
# ═══════════════════════════════════════════════════════════════

def patch_algo(code, params, end_date):
    """Patch the v3.0 algo source with specific parameters and end date."""
    patched = code

    # 1. Patch end date
    patched = re.sub(
        r"self\.SetEndDate\(\d+,\s*\d+,\s*\d+\)",
        f"self.SetEndDate({end_date.year}, {end_date.month}, {end_date.day})",
        patched,
    )

    # 2. Patch convergence parameters
    patched = re.sub(
        r"self\.convergence_threshold\s*=\s*[\d.]+",
        f"self.convergence_threshold = {params['convergence_threshold']}",
        patched,
    )
    patched = re.sub(
        r"self\.divergence_threshold\s*=\s*[\d.]+",
        f"self.divergence_threshold = {params['divergence_threshold']}",
        patched,
    )
    patched = re.sub(
        r"self\.slope_lookback\s*=\s*\d+",
        f"self.slope_lookback = {params['slope_lookback']}",
        patched,
    )
    patched = re.sub(
        r"self\.green_candles_required\s*=\s*\d+",
        f"self.green_candles_required = {params['green_candles_required']}",
        patched,
    )

    # 3. Patch GetDynamicLeapMultiplier method body
    old_method = re.search(
        r"(    def GetDynamicLeapMultiplier\(self, premium\):.*?)(?=\n    def )",
        patched, re.DOTALL
    )
    if old_method:
        new_method = f'''    def GetDynamicLeapMultiplier(self, premium):
        """Walk-forward parameterized LEAP blend."""
        if premium < {params["low_cap"]}:
            return {params["low_mult"]}
        elif premium < {params["fair_cap"]}:
            return {params["fair_mult"]}
        elif premium <= {params["elevated_cap"]}:
            return {params["elevated_mult"]}
        else:
            return {params["euphoric_mult"]}
'''
        patched = patched[:old_method.start()] + new_method + patched[old_method.end():]

    # 4. Patch ladder_tiers
    ladder_str = "self.ladder_tiers = [\n"
    for gain, trail in params["ladder_tiers"]:
        ladder_str += f"            ({gain}, {trail}),\n"
    ladder_str += "        ]"

    patched = re.sub(
        r"self\.ladder_tiers\s*=\s*\[.*?\]",
        ladder_str,
        patched,
        flags=re.DOTALL,
    )

    # 5. Patch premium_cap (wider for convergence strategy)
    patched = re.sub(
        r"self\.premium_cap\s*=\s*[\d.]+",
        f"self.premium_cap = 2.0",
        patched,
    )

    # 6. Patch StochRSI threshold (relaxed for convergence)
    patched = re.sub(
        r"self\.stoch_rsi_entry_threshold\s*=\s*\d+",
        f"self.stoch_rsi_entry_threshold = 80",
        patched,
    )

    return patched


# ═══════════════════════════════════════════════════════════════
# QC BACKTEST RUNNER
# ═══════════════════════════════════════════════════════════════

def run_backtest(project_id, code, name):
    """Upload code, compile, run backtest, poll for results. Returns stats dict or None."""
    # Upload
    result = _post("files/update", {"projectId": project_id, "name": "main.py", "content": code})
    if not result.get("success"):
        result = _post("files/create", {"projectId": project_id, "name": "main.py", "content": code})
    if not result.get("success"):
        log(f"Upload failed: {result}", "ERROR")
        return None

    # Compile
    compile_result = _post("compile/create", {"projectId": project_id})
    compile_id = compile_result.get("compileId", "")
    state = compile_result.get("state", "")

    if state != "BuildSuccess":
        for i in range(40):
            time.sleep(3)
            check = _post("compile/read", {"projectId": project_id, "compileId": compile_id})
            state = check.get("state", "")
            if state == "BuildSuccess":
                break
            if state == "BuildError":
                log(f"  BUILD ERROR: {check.get('errors', [])}", "ERROR")
                return None

    if state != "BuildSuccess":
        log("Compile timed out", "ERROR")
        return None

    # Launch backtest
    bt_result = _post("backtests/create", {
        "projectId": project_id, "compileId": compile_id, "backtestName": name
    })
    if not bt_result.get("success"):
        log(f"Launch failed: {bt_result}", "ERROR")
        return None

    backtest_id = bt_result.get("backtest", {}).get("backtestId") or bt_result.get("backtestId", "")
    if not backtest_id:
        log(f"No backtest ID returned", "ERROR")
        return None

    # Poll for completion (up to 8 minutes)
    for i in range(240):
        time.sleep(2)
        result = _post("backtests/read", {"projectId": project_id, "backtestId": backtest_id})
        bt = result.get("backtest", result)
        status = bt.get("status", "")
        progress = bt.get("progress", 0)

        if status == "Completed" or (isinstance(progress, (int, float)) and progress >= 1.0):
            stats = bt.get("statistics", {})
            if not stats:
                time.sleep(2)
                result = _post("backtests/read", {"projectId": project_id, "backtestId": backtest_id})
                bt = result.get("backtest", result)
                stats = bt.get("statistics", {})
            return stats

        if i % 15 == 0 and i > 0:
            log(f"  Progress: {progress} | Status: {status}")

    log("Backtest timed out (8 min)", "ERROR")
    return None


# ═══════════════════════════════════════════════════════════════
# SCORING
# ═══════════════════════════════════════════════════════════════

def parse_stat(stats, key, default=0.0):
    """Parse a QC statistic value (handles %, $, commas)."""
    val = stats.get(key, str(default))
    if isinstance(val, (int, float)):
        return float(val)
    val = val.replace("%", "").replace("$", "").replace(",", "").strip()
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def score_backtest(stats):
    """Composite score: 0.4×Sharpe + 0.3×(Return/100) + 0.3×(1-DD/100).
    Penalizes strategies with fewer than 2 trades."""
    if not stats:
        return -999

    sharpe = parse_stat(stats, "Sharpe Ratio")
    net = parse_stat(stats, "Net Profit")
    dd = parse_stat(stats, "Drawdown")
    wr = parse_stat(stats, "Win Rate")
    trades = int(parse_stat(stats, "Total Orders"))

    if trades < 2:
        return -999

    score = 0.4 * sharpe + 0.3 * (net / 100.0) + 0.3 * (1.0 - dd / 100.0)
    return round(score, 4)


# ═══════════════════════════════════════════════════════════════
# CHECKPOINTING
# ═══════════════════════════════════════════════════════════════

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {"windows": {}}


def save_checkpoint(data):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════
# MAIN WALK-FORWARD ENGINE
# ═══════════════════════════════════════════════════════════════

def run_walk_forward(resume=False):
    """Execute full anchored walk-forward analysis for v3.0."""
    log("RUDY v3.0 TREND CONVERGENCE — WALK-FORWARD ANALYSIS")
    log("=" * 60)

    # Load algo source
    with open(ALGO_PATH) as f:
        base_code = f.read()

    grid = build_param_grid()
    windows = generate_windows()
    checkpoint = load_checkpoint() if resume else {"windows": {}}

    total_bt = len(windows) * len(grid) + len(windows)
    log(f"Windows: {len(windows)} | Param combos: {len(grid)} | Total backtests: {total_bt}")
    log(f"Grid dimensions: {len(CONVERGENCE_CONFIGS)} convergence × {len(SLOPE_LOOKBACKS)} slope × "
        f"{len(GREEN_CANDLES)} candles × {len(TRAIL_WIDTHS)} trail = {len(grid)}")
    log("")

    for wi, window in enumerate(windows):
        wkey = f"run_{wi+1}"
        log(f"\n{'='*60}")
        log(f"WINDOW {wi+1}/{len(windows)}: {window['label']}")
        log(f"  IS: {window['is_start']} to {window['is_end']}")
        log(f"  OOS: {window['oos_start']} to {window['oos_end']}")
        log(f"{'='*60}")

        if wkey not in checkpoint["windows"]:
            checkpoint["windows"][wkey] = {
                "window": {k: str(v) for k, v in window.items()},
                "is_results": {},
                "best_params": None,
                "best_is_score": None,
                "best_is_stats": None,
                "oos_stats": None,
            }

        wdata = checkpoint["windows"][wkey]

        # ── IN-SAMPLE OPTIMIZATION ──
        log(f"\n  ── IN-SAMPLE: Testing {len(grid)} parameter combos ──")
        for gi, params in enumerate(grid):
            pname = params["name"]

            # Skip if already done
            if pname in wdata["is_results"]:
                log(f"  [{gi+1}/{len(grid)}] {pname}: CACHED (score={wdata['is_results'][pname].get('score', '?')})")
                continue

            log(f"  [{gi+1}/{len(grid)}] {pname} "
                f"[conv={params['convergence_threshold']}% slope={params['slope_lookback']}w "
                f"green={params['green_candles_required']} trail={params['trail_widths']}]...")

            # Patch algo for IS window
            patched = patch_algo(base_code, params, window["is_end"])
            bt_name = f"WF30-IS-{wkey}-{pname}"

            stats = run_backtest(PROJECT_ID, patched, bt_name)
            sc = score_backtest(stats)

            wdata["is_results"][pname] = {
                "stats": stats,
                "score": sc,
                "net": parse_stat(stats, "Net Profit") if stats else None,
                "sharpe": parse_stat(stats, "Sharpe Ratio") if stats else None,
                "dd": parse_stat(stats, "Drawdown") if stats else None,
                "trades": int(parse_stat(stats, "Total Orders")) if stats else 0,
            }

            net_str = f"{parse_stat(stats, 'Net Profit'):.1f}%" if stats else "FAIL"
            log(f"    → Score={sc} | Net={net_str}")

            save_checkpoint(checkpoint)
            time.sleep(5)  # Rate limiting

        # ── SELECT BEST IS PARAMS ──
        best_name = None
        best_score = -999
        for pname, result in wdata["is_results"].items():
            if result["score"] > best_score:
                best_score = result["score"]
                best_name = pname

        if best_name is None or best_score <= -999:
            log(f"  No valid IS results for window {wi+1}, skipping OOS", "WARN")
            continue

        best_params = None
        for p in grid:
            if p["name"] == best_name:
                best_params = p
                break

        wdata["best_params"] = best_name
        wdata["best_is_score"] = best_score
        wdata["best_is_stats"] = wdata["is_results"][best_name]

        log(f"\n  BEST IS: {best_name} (score={best_score})")
        log(f"    Net={wdata['is_results'][best_name]['net']:.1f}% | "
            f"Sharpe={wdata['is_results'][best_name]['sharpe']:.3f} | "
            f"DD={wdata['is_results'][best_name]['dd']:.1f}%")

        # ── OUT-OF-SAMPLE TEST ──
        if wdata["oos_stats"] is not None:
            log(f"  OOS: CACHED")
        else:
            log(f"\n  ── OUT-OF-SAMPLE: {window['oos_start']} to {window['oos_end']} ──")
            patched = patch_algo(base_code, best_params, window["oos_end"])
            bt_name = f"WF30-OOS-{wkey}-{best_name}"

            oos_stats = run_backtest(PROJECT_ID, patched, bt_name)
            oos_sc = score_backtest(oos_stats)

            wdata["oos_stats"] = {
                "stats": oos_stats,
                "score": oos_sc,
                "net": parse_stat(oos_stats, "Net Profit") if oos_stats else None,
                "sharpe": parse_stat(oos_stats, "Sharpe Ratio") if oos_stats else None,
                "dd": parse_stat(oos_stats, "Drawdown") if oos_stats else None,
                "trades": int(parse_stat(oos_stats, "Total Orders")) if oos_stats else 0,
                "params_used": best_name,
            }

            if oos_stats:
                log(f"    → OOS Net={parse_stat(oos_stats, 'Net Profit'):.1f}% | Score={oos_sc}")
            else:
                log(f"    → OOS FAILED")

        save_checkpoint(checkpoint)

    # ── FINAL REPORT ──
    log(f"\n\n{'='*60}")
    log("v3.0 WALK-FORWARD ANALYSIS COMPLETE")
    log(f"{'='*60}")
    print_report(checkpoint)

    # Save final results
    with open(RESULTS_FILE, "w") as f:
        json.dump(checkpoint, f, indent=2, default=str)
    log(f"\nResults saved to {RESULTS_FILE}")


# ═══════════════════════════════════════════════════════════════
# REPORTING
# ═══════════════════════════════════════════════════════════════

def print_report(data):
    """Print walk-forward summary table, WFE, and parameter stability."""
    windows = data.get("windows", {})
    if not windows:
        log("No results to report.")
        return

    # Summary table
    print(f"\n{'─'*100}")
    print(f"{'Window':<12} {'Best Params':<35} {'IS Net%':>8} {'IS Sharpe':>10} {'OOS Net%':>9} {'OOS Sharpe':>11}")
    print(f"{'─'*100}")

    is_returns = []
    oos_returns = []
    param_wins = {
        "convergence": {},
        "slope_lookback": {},
        "green_candles": {},
        "trail_widths": {},
    }

    for wkey in sorted(windows.keys()):
        w = windows[wkey]
        label = w.get("window", {}).get("label", wkey)
        best = w.get("best_params", "N/A")
        is_stats = w.get("best_is_stats", {})
        oos = w.get("oos_stats", {})

        is_net = is_stats.get("net", 0) if is_stats else 0
        is_sharpe = is_stats.get("sharpe", 0) if is_stats else 0
        oos_net = oos.get("net", 0) if oos else 0
        oos_sharpe = oos.get("sharpe", 0) if oos else 0

        is_returns.append(is_net or 0)
        oos_returns.append(oos_net or 0)

        # Track parameter axis wins (name format: convergence_slope_candles_trail)
        if best and best != "N/A":
            parts = best.split("_")
            if len(parts) >= 4:
                conv = parts[0]       # tight/medium/wide
                slope = parts[1]      # short/medium
                candles = parts[2]    # quick/standard
                trail = parts[3]      # tight/default/wide
                param_wins["convergence"][conv] = param_wins["convergence"].get(conv, 0) + 1
                param_wins["slope_lookback"][slope] = param_wins["slope_lookback"].get(slope, 0) + 1
                param_wins["green_candles"][candles] = param_wins["green_candles"].get(candles, 0) + 1
                param_wins["trail_widths"][trail] = param_wins["trail_widths"].get(trail, 0) + 1

        print(f"{label:<12} {str(best):<35} {is_net:>7.1f}% {is_sharpe:>9.3f} {oos_net:>8.1f}% {oos_sharpe:>10.3f}")

    print(f"{'─'*100}")

    # Walk-Forward Efficiency
    avg_is = sum(is_returns) / len(is_returns) if is_returns else 0
    avg_oos = sum(oos_returns) / len(oos_returns) if oos_returns else 0
    wfe = (avg_oos / avg_is) if avg_is != 0 else 0

    print(f"\n  Avg IS Return:  {avg_is:>7.1f}%")
    print(f"  Avg OOS Return: {avg_oos:>7.1f}%")
    print(f"  Walk-Forward Efficiency (WFE): {wfe:.2f}")

    if wfe > 0.5:
        print(f"  → ROBUST: WFE > 0.5 indicates strategy parameters are stable")
    elif wfe > 0.3:
        print(f"  → MODERATE: WFE 0.3-0.5, some overfitting but still viable")
    else:
        print(f"  → WEAK: WFE < 0.3, parameters may be overfit")

    # Stitched OOS equity
    cumulative = 100.0
    print(f"\n  Stitched OOS Equity Curve (starting $100):")
    for i, (wkey, oos_ret) in enumerate(zip(sorted(windows.keys()), oos_returns)):
        label = windows[wkey].get("window", {}).get("label", wkey)
        cumulative *= (1 + (oos_ret or 0) / 100.0)
        bar = "█" * max(1, int(cumulative / 10))
        print(f"    {label:<20} {bar} ${cumulative:>8.2f} ({oos_ret:>+6.1f}%)")

    total_oos_return = (cumulative / 100.0 - 1) * 100
    print(f"\n  Total Stitched OOS Return: {total_oos_return:>+.1f}%")

    # Parameter stability — v3.0 specific axes
    print(f"\n  Parameter Stability (wins per axis value):")
    axis_labels = {
        "convergence": "Convergence Threshold",
        "slope_lookback": "Slope Lookback",
        "green_candles": "Green Candles Required",
        "trail_widths": "Trail Width",
    }
    for axis, counts in param_wins.items():
        label = axis_labels.get(axis, axis)
        print(f"    {label}: {dict(sorted(counts.items(), key=lambda x: -x[1]))}")

    # Check if one combo dominates
    all_bests = [windows[w].get("best_params", "") for w in sorted(windows.keys())]
    most_common = max(set(all_bests), key=all_bests.count) if all_bests else "N/A"
    dominance = all_bests.count(most_common)
    print(f"\n  Most common winner: {most_common} ({dominance}/{len(all_bests)} windows)")
    if dominance >= 4:
        print(f"  → STABLE: Same params win majority of windows")
    elif dominance >= 3:
        print(f"  → MODERATELY STABLE: Params cluster around a few combos")
    else:
        print(f"  → UNSTABLE: Optimal params shift between windows — possible overfitting")

    # v3.0 vs v2.8 comparison note
    print(f"\n  ── COMPARE vs v2.8 ──")
    print(f"  v2.8 WFE: 1.20 | v2.8 Stitched OOS: +692.2%")
    print(f"  v3.0 WFE: {wfe:.2f} | v3.0 Stitched OOS: {total_oos_return:>+.1f}%")
    if wfe > 1.20:
        print(f"  → v3.0 OUTPERFORMS v2.8 on WFE")
    elif wfe > 0.5:
        print(f"  → v3.0 is viable but v2.8 has higher WFE")
    else:
        print(f"  → v3.0 underperforms v2.8 — convergence may need refinement")


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rudy v3.0 Trend Convergence Walk-Forward Analysis")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--report", action="store_true", help="Print report from existing results")
    args = parser.parse_args()

    if args.report:
        if os.path.exists(RESULTS_FILE):
            with open(RESULTS_FILE) as f:
                data = json.load(f)
            print_report(data)
        elif os.path.exists(CHECKPOINT_FILE):
            data = load_checkpoint()
            print_report(data)
        else:
            log("No results found. Run walk-forward first.")
    else:
        run_walk_forward(resume=args.resume)
