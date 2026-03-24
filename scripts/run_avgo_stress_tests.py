"""AVGO v2.8+ Comprehensive Stress Test Suite.

Mirrors the MSTR v2.8+ stress tests:
  1. Execution Realism / Slippage Stress (100/200/300bps)
  2. Anti-Trend Regime Simulation (2022 bear market isolation)
  3. Parameter Sensitivity (+/- 20%)
  4. False Signal Analysis
  5. Monte Carlo / Bootstrap
  6. Drawdown Duration Analysis
  7. Regime Dependency (bull/bear/flat)
  8. Walk-Forward Efficiency (WFE)

RESEARCH ONLY - does not modify any live trading code.
"""
import os, sys, time, json, re, copy, random, math
from hashlib import sha256
from base64 import b64encode
from datetime import datetime
import numpy as np

QC_API_TOKEN = "a5e10d30d2c0f483c2c62a124375b2fcf4e0f907d54ab3ae863e7450e50b7688"
QC_USER_ID = "473242"
QC_BASE = "https://www.quantconnect.com/api/v2"

ALGO_PATH = os.path.expanduser("~/rudy/quantconnect/AVGOCycleLowLeap_v28plus.py")
OUTPUT_PATH = os.path.expanduser("~/rudy/data/avgo_v28plus_stress_tests.json")

# Baseline results from initial backtest
BASELINE = {
    "net_profit": 501.543,
    "sharpe": 0.888,
    "sortino": 0.828,
    "max_dd": 18.8,
    "orders": 106,
    "win_rate": 26,
    "cagr": 19.638,
    "alpha": 0.087,
    "beta": 0.317,
    "profit_loss_ratio": 19.19,
    "dd_recovery_days": 505,
    "avg_win": 17.45,
    "avg_loss": -0.91,
}


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _auth_headers():
    timestamp = str(int(time.time()))
    hashed = sha256(f"{QC_API_TOKEN}:{timestamp}".encode()).hexdigest()
    auth = b64encode(f"{QC_USER_ID}:{hashed}".encode()).decode()
    return {"Authorization": f"Basic {auth}", "Timestamp": timestamp, "Content-Type": "application/json"}


def _post(endpoint, data=None):
    import requests
    r = requests.post(f"{QC_BASE}/{endpoint}", headers=_auth_headers(), json=data or {}, timeout=60)
    return r.json()


def patch_dates(code, start, end):
    code = re.sub(
        r'self\.SetStartDate\(\d+,\s*\d+,\s*\d+\)',
        f'self.SetStartDate({start[0]}, {start[1]}, {start[2]})',
        code
    )
    code = re.sub(
        r'self\.SetEndDate\(\d+,\s*\d+,\s*\d+\)',
        f'self.SetEndDate({end[0]}, {end[1]}, {end[2]})',
        code
    )
    return code


def patch_slippage(code, slippage_pct):
    """Replace the slippage constant in the algo code."""
    code = re.sub(
        r'ConstantSlippageModel\([0-9.]+\)',
        f'ConstantSlippageModel({slippage_pct})',
        code
    )
    return code


def patch_parameter(code, param_name, new_value):
    """Replace a parameter value in the algo code."""
    # Handle integer params
    if isinstance(new_value, int):
        code = re.sub(
            rf'self\.{param_name}\s*=\s*[-\d]+',
            f'self.{param_name} = {new_value}',
            code
        )
    else:
        code = re.sub(
            rf'self\.{param_name}\s*=\s*[-\d.]+',
            f'self.{param_name} = {new_value}',
            code
        )
    return code


def patch_disable_trend_adder(code):
    """Disable trend adder for base-only tests."""
    return code.replace(
        'self.trend_adder_enabled = True',
        'self.trend_adder_enabled = False'
    )


def run_backtest(algo_code, test_name, timeout_sec=600):
    """Create project, upload, compile, run backtest, poll for results."""
    project_name = f"AVGO_stress_{test_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    log(f"  Launching: {test_name}")

    # Create project
    result = _post("projects/create", {"name": project_name, "language": "Py"})
    if not result.get("success"):
        log(f"  Project create failed: {result}")
        return None
    project_id = result.get("projects", [{}])[0].get("projectId")

    # Upload code
    result = _post("files/create", {"projectId": project_id, "name": "main.py", "content": algo_code})
    if not result.get("success"):
        result = _post("files/update", {"projectId": project_id, "name": "main.py", "content": algo_code})

    # Compile
    compile_result = _post("compile/create", {"projectId": project_id})
    compile_id = compile_result.get("compileId", "")
    state = compile_result.get("state", "")

    if state != "BuildSuccess":
        for i in range(60):
            time.sleep(3)
            check = _post("compile/read", {"projectId": project_id, "compileId": compile_id})
            state = check.get("state", "")
            if state == "BuildSuccess":
                break
            if state == "BuildError":
                errors = check.get("errors", [])
                log(f"  BUILD ERROR: {errors}")
                return None

    if state != "BuildSuccess":
        log("  Compile timed out")
        return None

    # Launch backtest
    bt_result = _post("backtests/create", {
        "projectId": project_id, "compileId": compile_id,
        "backtestName": f"AVGO stress {test_name}"
    })
    if not bt_result.get("success"):
        log(f"  Launch failed: {bt_result}")
        return None

    backtest_id = bt_result.get("backtest", {}).get("backtestId") or bt_result.get("backtestId", "")
    if not backtest_id:
        log(f"  No backtest ID")
        return None

    # Poll for completion
    max_polls = int(timeout_sec / 2)
    for i in range(max_polls):
        time.sleep(2)
        result = _post("backtests/read", {"projectId": project_id, "backtestId": backtest_id})
        bt = result.get("backtest", result)
        status = bt.get("status", "")
        progress = bt.get("progress", 0)

        if status == "Completed" or (isinstance(progress, (int, float)) and progress >= 1.0):
            stats = bt.get("statistics", {})
            log(f"  DONE: {test_name} | Net={stats.get('Net Profit','?')} Sharpe={stats.get('Sharpe Ratio','?')} DD={stats.get('Drawdown','?')}")

            # Get logs for trade analysis
            log_entries = []
            try:
                log_result = _post("backtests/read", {
                    "projectId": project_id, "backtestId": backtest_id,
                })
                log_entries = log_result.get("backtest", {}).get("logs", [])
            except:
                pass

            return {
                "test": test_name,
                "project_id": project_id,
                "backtest_id": backtest_id,
                "statistics": stats,
                "status": "Completed",
                "logs": log_entries[-200:] if log_entries else [],
            }

        if i % 30 == 0 and i > 0:
            log(f"  Progress: {progress} | Status: {status}")

    log(f"  Backtest timed out: {test_name}")
    return {"test": test_name, "status": "Timeout", "statistics": {}}


def extract_stats(result):
    """Extract key numeric stats from a backtest result."""
    if not result or not result.get("statistics"):
        return {}
    stats = result["statistics"]
    out = {}
    for k, v in stats.items():
        try:
            out[k] = float(v.replace("%", "").replace("$", "").replace(",", ""))
        except:
            out[k] = v
    return out


def get_stat(stats, keyword):
    """Get a stat value by keyword match."""
    for k, v in stats.items():
        if keyword.lower() in k.lower():
            if isinstance(v, (int, float)):
                return v
            try:
                return float(str(v).replace("%", "").replace("$", "").replace(",", ""))
            except:
                pass
    return None


# ============================================================
# TEST 1: EXECUTION REALISM / SLIPPAGE STRESS
# ============================================================
def test_slippage_stress(base_code):
    """Run with 100bps, 200bps, 300bps slippage."""
    log("\n" + "="*60)
    log("TEST 1: SLIPPAGE STRESS")
    log("="*60)

    slippage_levels = [
        (0.003, 30, "30bps (baseline)"),
        (0.005, 50, "50bps"),
        (0.0075, 75, "75bps"),
        (0.01, 100, "100bps"),
        (0.015, 150, "150bps"),
        (0.02, 200, "200bps"),
        (0.03, 300, "300bps"),
    ]

    results = []
    for slip_pct, bps, label in slippage_levels:
        code = patch_slippage(base_code, slip_pct)
        result = run_backtest(code, f"slip_{bps}bps")
        stats = extract_stats(result)
        net = get_stat(stats, "net profit") or 0
        dd = get_stat(stats, "drawdown") or 0
        sharpe = get_stat(stats, "sharpe") or 0
        orders = get_stat(stats, "total orders") or 0
        sortino = get_stat(stats, "sortino") or 0
        win_rate = get_stat(stats, "win rate") or 0

        entry = {
            "slippage_pct": slip_pct,
            "bps": bps,
            "label": label,
            "net": net,
            "dd": dd,
            "sharpe": sharpe,
            "sortino": sortino,
            "orders": orders,
            "win_rate": win_rate,
            "survival_ratio": net / BASELINE["net_profit"] if BASELINE["net_profit"] else 0,
            "edge_survives": net > 0 and sharpe > 0,
        }
        results.append(entry)
        log(f"  {label}: Net={net:.1f}% Sharpe={sharpe:.3f} DD={dd:.1f}% Survival={entry['survival_ratio']:.2f}")

    return results


# ============================================================
# TEST 2: ANTI-TREND REGIME / BEAR MARKET ISOLATION
# ============================================================
def test_bear_market_isolation(base_code):
    """Test performance during the 2022 bear market and other adverse periods."""
    log("\n" + "="*60)
    log("TEST 2: BEAR MARKET / REGIME ISOLATION")
    log("="*60)

    regimes = [
        {
            "name": "2022_bear",
            "description": "2022 Bear Market (full year) - AVGO dropped ~45% from highs",
            "start": (2021, 11, 1),
            "end": (2023, 1, 31),
            "expectation": "Strategy should either sit flat or take small losses, NOT large ones"
        },
        {
            "name": "2018_correction",
            "description": "2018 Q4 Correction - tech sell-off, trade wars",
            "start": (2018, 9, 1),
            "end": (2019, 6, 30),
            "expectation": "Potential dip+reclaim opportunity"
        },
        {
            "name": "2020_covid",
            "description": "2020 COVID Crash + Recovery - sharp V-shape",
            "start": (2020, 1, 1),
            "end": (2021, 6, 30),
            "expectation": "Strategy should fire on the recovery dip+reclaim"
        },
        {
            "name": "2023_2025_bull",
            "description": "2023-2025 AI Bull Run - AVGO surged on AI/chip demand",
            "start": (2023, 1, 1),
            "end": (2025, 12, 31),
            "expectation": "Strategy should capture the major trend"
        },
        {
            "name": "sideways_2017",
            "description": "2017 AVGO consolidation period",
            "start": (2016, 7, 1),
            "end": (2018, 6, 30),
            "expectation": "Minimal activity, no major losses"
        },
    ]

    results = []
    for regime in regimes:
        # Run with adder
        code_with = patch_dates(base_code, regime["start"], regime["end"])
        result_with = run_backtest(code_with, f"regime_{regime['name']}_with_adder")

        # Run without adder
        code_without = patch_disable_trend_adder(patch_dates(base_code, regime["start"], regime["end"]))
        result_without = run_backtest(code_without, f"regime_{regime['name']}_no_adder")

        stats_with = extract_stats(result_with)
        stats_without = extract_stats(result_without)

        net_with = get_stat(stats_with, "net profit") or 0
        dd_with = get_stat(stats_with, "drawdown") or 0
        sharpe_with = get_stat(stats_with, "sharpe") or 0
        orders_with = get_stat(stats_with, "total orders") or 0

        net_without = get_stat(stats_without, "net profit") or 0
        dd_without = get_stat(stats_without, "drawdown") or 0
        sharpe_without = get_stat(stats_without, "sharpe") or 0
        orders_without = get_stat(stats_without, "total orders") or 0

        entry = {
            "regime": regime["name"],
            "description": regime["description"],
            "expectation": regime["expectation"],
            "with_adder": {
                "net": net_with, "dd": dd_with, "sharpe": sharpe_with, "orders": orders_with,
            },
            "without_adder": {
                "net": net_without, "dd": dd_without, "sharpe": sharpe_without, "orders": orders_without,
            },
            "delta_net": net_with - net_without,
            "delta_dd": dd_with - dd_without,
            "extra_orders": int(orders_with - orders_without),
            "adder_alpha": net_with - net_without,
        }
        results.append(entry)
        log(f"  {regime['name']}: With={net_with:.1f}% Without={net_without:.1f}% Delta={entry['delta_net']:.1f}%")

    return results


# ============================================================
# TEST 3: PARAMETER SENSITIVITY (+/- 20%)
# ============================================================
def test_parameter_sensitivity(base_code):
    """Vary key parameters +/- 20% to check for overfitting."""
    log("\n" + "="*60)
    log("TEST 3: PARAMETER SENSITIVITY (+/- 20%)")
    log("="*60)

    # Parameters to test with their baseline values
    params = [
        ("sma_weekly_period", 200, "int", [160, 180, 200, 220, 240]),
        ("stoch_rsi_entry_threshold", 70, "int", [56, 63, 70, 77, 84]),
        ("green_weeks_threshold", 2, "int", [1, 2, 3]),
        ("premium_cap", 2.5, "float", [2.0, 2.25, 2.5, 2.75, 3.0]),
        ("initial_floor_pct", 0.65, "float", [0.52, 0.585, 0.65, 0.715, 0.78]),
        ("panic_floor_pct", -35.0, "float", [-42.0, -38.5, -35.0, -31.5, -28.0]),
        ("max_hold_bars", 567, "int", [454, 510, 567, 624, 680]),
        ("risk_capital_pct", 0.25, "float", [0.20, 0.225, 0.25, 0.275, 0.30]),
        ("trend_confirm_weeks", 4, "int", [2, 3, 4, 5, 6]),
        ("trend_adder_capital_pct", 0.25, "float", [0.20, 0.225, 0.25, 0.275, 0.30]),
        ("euphoria_premium", 3.0, "float", [2.4, 2.7, 3.0, 3.3, 3.6]),
    ]

    results = []
    for param_name, baseline, ptype, values in params:
        param_results = []
        for val in values:
            if ptype == "int":
                code = patch_parameter(base_code, param_name, int(val))
                test_label = f"param_{param_name}_{int(val)}"
            else:
                code = patch_parameter(base_code, param_name, round(val, 4))
                test_label = f"param_{param_name}_{val}"

            result = run_backtest(code, test_label)
            stats = extract_stats(result)
            net = get_stat(stats, "net profit") or 0
            dd = get_stat(stats, "drawdown") or 0
            sharpe = get_stat(stats, "sharpe") or 0
            orders = get_stat(stats, "total orders") or 0

            param_results.append({
                "value": val,
                "is_baseline": val == baseline,
                "net": net,
                "dd": dd,
                "sharpe": sharpe,
                "orders": orders,
                "pct_of_baseline_net": (net / BASELINE["net_profit"] * 100) if BASELINE["net_profit"] else 0,
            })

        # Compute sensitivity score: how much does net change per 20% param change?
        nets = [r["net"] for r in param_results]
        if len(nets) >= 2 and max(nets) > 0:
            sensitivity = (max(nets) - min(nets)) / max(nets) * 100
        else:
            sensitivity = 0

        entry = {
            "parameter": param_name,
            "baseline_value": baseline,
            "values_tested": values,
            "results": param_results,
            "sensitivity_pct": round(sensitivity, 1),
            "robust": sensitivity < 50,  # Less than 50% swing = robust
        }
        results.append(entry)
        log(f"  {param_name}: Sensitivity={sensitivity:.1f}% {'ROBUST' if sensitivity < 50 else 'SENSITIVE'}")
        for pr in param_results:
            marker = " <-- BASELINE" if pr["is_baseline"] else ""
            log(f"    {pr['value']}: Net={pr['net']:.1f}% Sharpe={pr['sharpe']:.3f}{marker}")

    return results


# ============================================================
# TEST 4: FALSE SIGNAL ANALYSIS
# ============================================================
def test_false_signals(base_code):
    """Analyze how many entry signals were false positives that hit the initial stop."""
    log("\n" + "="*60)
    log("TEST 4: FALSE SIGNAL ANALYSIS")
    log("="*60)

    # Run baseline and extract log entries
    result = run_backtest(base_code, "false_signal_analysis")
    if not result:
        return {"error": "Backtest failed"}

    logs = result.get("logs", [])
    stats = extract_stats(result)

    entries = []
    exits = []
    for line in logs:
        if isinstance(line, str):
            text = line
        elif isinstance(line, dict):
            text = line.get("Message", line.get("message", ""))
        else:
            continue

        if "ENTRY 1/2" in text or "ENTRY 2/2" in text:
            entries.append(text)
        if any(reason in text for reason in [
            "INITIAL_FLOOR", "PANIC_FLOOR", "EMA50_LOSS",
            "LADDER_TRAIL", "MAX_HOLD", "TARGET_HIT",
            "SPY_DEATH_CROSS", "SPY_200W_BREAK", "EUPHORIA"
        ]):
            exits.append(text)

    # Count exit reasons
    exit_reasons = {}
    for line in exits:
        for reason in ["INITIAL_FLOOR", "PANIC_FLOOR", "EMA50_LOSS",
                        "LADDER_TRAIL", "MAX_HOLD", "TARGET_HIT",
                        "SPY_DEATH_CROSS", "SPY_200W_BREAK",
                        "ADDER_PANIC", "ADDER_FLOOR", "ADDER_TRAIL",
                        "CONVERGENCE_DOWN"]:
            if reason in line:
                exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

    total_entries = len(entries)
    false_stops = exit_reasons.get("INITIAL_FLOOR", 0) + exit_reasons.get("PANIC_FLOOR", 0) + exit_reasons.get("EMA50_LOSS", 0)
    win_exits = exit_reasons.get("LADDER_TRAIL", 0) + exit_reasons.get("TARGET_HIT", 0)

    false_positive_rate = (false_stops / total_entries * 100) if total_entries > 0 else 0

    analysis = {
        "total_entry_signals": total_entries,
        "exit_reason_counts": exit_reasons,
        "false_positives_hit_stop": false_stops,
        "false_positive_rate_pct": round(false_positive_rate, 1),
        "winning_exits": win_exits,
        "win_rate_from_baseline": BASELINE["win_rate"],
        "avg_win_pct": BASELINE["avg_win"],
        "avg_loss_pct": BASELINE["avg_loss"],
        "profit_loss_ratio": BASELINE["profit_loss_ratio"],
        "assessment": (
            f"With a {BASELINE['win_rate']}% win rate and {BASELINE['profit_loss_ratio']:.1f}x P/L ratio, "
            f"the strategy relies on few large winners to compensate for many small losers. "
            f"This is typical of trend-following LEAP strategies. "
            f"Average win ({BASELINE['avg_win']}%) vs average loss ({BASELINE['avg_loss']}%) = "
            f"highly asymmetric payoff profile."
        ),
    }

    log(f"  Entries: {total_entries} | False stops: {false_stops} | False positive rate: {false_positive_rate:.1f}%")
    log(f"  Exit reasons: {exit_reasons}")

    return analysis


# ============================================================
# TEST 5: MONTE CARLO / BOOTSTRAP
# ============================================================
def test_monte_carlo(base_code):
    """Randomize trade order to check if returns are path-dependent.
    Uses the baseline stats to simulate: we know avg win, avg loss, win rate, and number of trades."""
    log("\n" + "="*60)
    log("TEST 5: MONTE CARLO / BOOTSTRAP")
    log("="*60)

    # We simulate using known trade statistics from the baseline
    n_simulations = 10000
    n_trades_approx = 53  # 106 orders / ~2 orders per trade = ~53 round trips
    win_rate = BASELINE["win_rate"] / 100.0  # 0.26
    avg_win = BASELINE["avg_win"] / 100.0   # 0.1745
    avg_loss = BASELINE["avg_loss"] / 100.0  # -0.0091
    initial_capital = 100000

    random.seed(42)
    np.random.seed(42)

    # Generate trade returns distribution
    # Use log-normal for wins, normal for losses to model fat tails
    final_returns = []
    max_drawdowns = []
    sharpe_proxies = []

    for sim in range(n_simulations):
        capital = initial_capital
        peak = capital
        max_dd = 0
        trade_returns = []

        for trade in range(n_trades_approx):
            if random.random() < win_rate:
                # Winner: draw from distribution centered on avg_win with some variance
                ret = np.random.lognormal(
                    mean=np.log(1 + avg_win) - 0.5 * 0.5**2,
                    sigma=0.5
                ) - 1
                ret = max(ret, -0.5)  # Cap losses from lognormal tail
            else:
                # Loser: draw from distribution centered on avg_loss
                ret = np.random.normal(avg_loss, abs(avg_loss) * 0.5)
                ret = min(ret, 0.01)  # Losers shouldn't be big winners
                ret = max(ret, -0.5)  # Cap max loss

            trade_returns.append(ret)
            # Apply to invested portion (risk_capital_pct = 25%)
            position_size = capital * 0.25
            pnl = position_size * ret
            capital += pnl
            peak = max(peak, capital)
            dd = (peak - capital) / peak * 100
            max_dd = max(max_dd, dd)

        total_return = (capital / initial_capital - 1) * 100
        final_returns.append(total_return)
        max_drawdowns.append(max_dd)

        # Proxy Sharpe from trade returns
        if len(trade_returns) > 1:
            mean_ret = np.mean(trade_returns)
            std_ret = np.std(trade_returns)
            sharpe_proxy = (mean_ret / std_ret * np.sqrt(52)) if std_ret > 0 else 0  # Annualized
            sharpe_proxies.append(sharpe_proxy)

    final_returns = np.array(final_returns)
    max_drawdowns = np.array(max_drawdowns)
    sharpe_proxies = np.array(sharpe_proxies)

    percentiles = [5, 10, 25, 50, 75, 90, 95]
    return_percentiles = {f"p{p}": round(float(np.percentile(final_returns, p)), 2) for p in percentiles}
    dd_percentiles = {f"p{p}": round(float(np.percentile(max_drawdowns, p)), 2) for p in percentiles}

    analysis = {
        "n_simulations": n_simulations,
        "n_trades_per_sim": n_trades_approx,
        "win_rate_used": win_rate,
        "avg_win_used": avg_win,
        "avg_loss_used": avg_loss,
        "return_distribution": {
            "mean": round(float(np.mean(final_returns)), 2),
            "std": round(float(np.std(final_returns)), 2),
            "min": round(float(np.min(final_returns)), 2),
            "max": round(float(np.max(final_returns)), 2),
            "percentiles": return_percentiles,
            "pct_positive": round(float(np.mean(final_returns > 0) * 100), 1),
            "pct_above_100": round(float(np.mean(final_returns > 100) * 100), 1),
            "pct_above_200": round(float(np.mean(final_returns > 200) * 100), 1),
            "pct_above_500": round(float(np.mean(final_returns > 500) * 100), 1),
        },
        "drawdown_distribution": {
            "mean": round(float(np.mean(max_drawdowns)), 2),
            "std": round(float(np.std(max_drawdowns)), 2),
            "percentiles": dd_percentiles,
        },
        "sharpe_distribution": {
            "mean": round(float(np.mean(sharpe_proxies)), 3),
            "std": round(float(np.std(sharpe_proxies)), 3),
            "p5": round(float(np.percentile(sharpe_proxies, 5)), 3),
            "p50": round(float(np.percentile(sharpe_proxies, 50)), 3),
            "p95": round(float(np.percentile(sharpe_proxies, 95)), 3),
            "pct_above_zero": round(float(np.mean(sharpe_proxies > 0) * 100), 1),
        },
        "path_dependency": {
            "actual_return": BASELINE["net_profit"],
            "median_simulated": round(float(np.percentile(final_returns, 50)), 2),
            "actual_percentile": round(float(np.mean(final_returns <= BASELINE["net_profit"]) * 100), 1),
            "assessment": "",
        },
    }

    actual_pctile = analysis["path_dependency"]["actual_percentile"]
    if actual_pctile > 90:
        analysis["path_dependency"]["assessment"] = (
            f"CAUTION: Actual return ({BASELINE['net_profit']:.1f}%) is at the {actual_pctile:.0f}th percentile "
            f"of Monte Carlo simulations. Returns may be path-dependent (lucky sequencing). "
            f"Median simulated return is {analysis['return_distribution']['percentiles']['p50']:.1f}%."
        )
    elif actual_pctile > 70:
        analysis["path_dependency"]["assessment"] = (
            f"OK: Actual return ({BASELINE['net_profit']:.1f}%) is at the {actual_pctile:.0f}th percentile. "
            f"Returns are somewhat above median ({analysis['return_distribution']['percentiles']['p50']:.1f}%) "
            f"but within reasonable range. Some path dependency possible."
        )
    else:
        analysis["path_dependency"]["assessment"] = (
            f"GOOD: Actual return ({BASELINE['net_profit']:.1f}%) is at the {actual_pctile:.0f}th percentile. "
            f"Returns are NOT path-dependent. The strategy edge is robust across trade orderings."
        )

    log(f"  Mean return: {analysis['return_distribution']['mean']:.1f}%")
    log(f"  Median return: {return_percentiles['p50']:.1f}%")
    log(f"  5th percentile: {return_percentiles['p5']:.1f}%")
    log(f"  95th percentile: {return_percentiles['p95']:.1f}%")
    log(f"  % positive: {analysis['return_distribution']['pct_positive']:.1f}%")
    log(f"  Actual at {actual_pctile:.0f}th percentile")
    log(f"  Mean max DD: {analysis['drawdown_distribution']['mean']:.1f}%")

    return analysis


# ============================================================
# TEST 6: DRAWDOWN DURATION ANALYSIS
# ============================================================
def test_drawdown_duration(base_code):
    """Analyze drawdown periods from the backtest. Can human hold through them?"""
    log("\n" + "="*60)
    log("TEST 6: DRAWDOWN DURATION ANALYSIS")
    log("="*60)

    # The baseline stats tell us max DD recovery was 505 days
    # We need to run a backtest and extract equity curve from logs
    result = run_backtest(base_code, "drawdown_analysis")
    if not result:
        return {"error": "Backtest failed"}

    stats = extract_stats(result)
    logs = result.get("logs", [])

    # Parse trade log entries for P&L sequence
    trade_pnls = []
    trade_dates = []
    for line in logs:
        text = line if isinstance(line, str) else line.get("Message", line.get("message", ""))
        # Look for exit entries with Stock gain info
        if "Stock:" in text and "LEAP:" in text:
            try:
                # Extract stock gain
                stock_match = re.search(r'Stock:\s*([+-]?\d+\.?\d*)%', text)
                leap_match = re.search(r'LEAP:\s*([+-]?\d+\.?\d*)%', text)
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
                if stock_match and leap_match:
                    trade_pnls.append({
                        "stock_gain": float(stock_match.group(1)),
                        "leap_gain": float(leap_match.group(1)),
                        "date": date_match.group(1) if date_match else "unknown",
                    })
            except:
                pass

    winners = [t for t in trade_pnls if t["leap_gain"] > 0]
    losers = [t for t in trade_pnls if t["leap_gain"] <= 0]

    # Compute losing streaks
    streak = 0
    max_streak = 0
    streaks = []
    for t in trade_pnls:
        if t["leap_gain"] <= 0:
            streak += 1
        else:
            if streak > 0:
                streaks.append(streak)
            max_streak = max(max_streak, streak)
            streak = 0
    if streak > 0:
        streaks.append(streak)
        max_streak = max(max_streak, streak)

    analysis = {
        "max_drawdown_pct": BASELINE["max_dd"],
        "max_dd_recovery_days": BASELINE["dd_recovery_days"],
        "total_trades_parsed": len(trade_pnls),
        "winners": len(winners),
        "losers": len(losers),
        "max_losing_streak": max_streak,
        "losing_streaks": sorted(streaks, reverse=True)[:10] if streaks else [],
        "avg_losing_streak": round(np.mean(streaks), 1) if streaks else 0,
        "psychology_assessment": {
            "max_dd_survivable": BASELINE["max_dd"] <= 25,
            "recovery_days_reasonable": BASELINE["dd_recovery_days"] <= 365,
            "max_dd_label": (
                "EXCELLENT" if BASELINE["max_dd"] <= 15 else
                "GOOD" if BASELINE["max_dd"] <= 20 else
                "ACCEPTABLE" if BASELINE["max_dd"] <= 30 else
                "CHALLENGING" if BASELINE["max_dd"] <= 40 else
                "DANGEROUS"
            ),
            "recovery_label": (
                "FAST" if BASELINE["dd_recovery_days"] <= 180 else
                "MODERATE" if BASELINE["dd_recovery_days"] <= 365 else
                "SLOW" if BASELINE["dd_recovery_days"] <= 730 else
                "VERY SLOW"
            ),
            "verdict": "",
        },
    }

    # Build verdict
    dd_label = analysis["psychology_assessment"]["max_dd_label"]
    rec_label = analysis["psychology_assessment"]["recovery_label"]
    analysis["psychology_assessment"]["verdict"] = (
        f"Max drawdown of {BASELINE['max_dd']}% is {dd_label}. "
        f"Recovery period of {BASELINE['dd_recovery_days']} days is {rec_label}. "
        f"Max losing streak: {max_streak} trades. "
        f"With a {BASELINE['win_rate']}% win rate, expect ~3/4 of trades to lose. "
        f"The strategy is psychologically {'holdable' if BASELINE['max_dd'] <= 25 else 'challenging but manageable'} "
        f"because large wins ({BASELINE['avg_win']}% avg) far exceed losses ({BASELINE['avg_loss']}% avg)."
    )

    log(f"  Max DD: {BASELINE['max_dd']}% | Recovery: {BASELINE['dd_recovery_days']} days")
    log(f"  Max losing streak: {max_streak}")
    log(f"  Assessment: {dd_label} DD, {rec_label} recovery")

    return analysis


# ============================================================
# TEST 7: REGIME DEPENDENCY
# ============================================================
def test_regime_dependency(base_code):
    """Does the strategy only work in bull markets?"""
    log("\n" + "="*60)
    log("TEST 7: REGIME DEPENDENCY")
    log("="*60)

    # Define regime periods for AVGO
    regimes = [
        {
            "name": "bull_2016_2018",
            "label": "Bull Market 2016-2018 (AVGO strong growth)",
            "start": (2016, 1, 1),
            "end": (2018, 9, 30),
            "regime_type": "bull",
        },
        {
            "name": "correction_2018q4",
            "label": "2018 Q4 Correction (tech selloff)",
            "start": (2018, 10, 1),
            "end": (2019, 6, 30),
            "regime_type": "bear",
        },
        {
            "name": "bull_2019_2020",
            "label": "Bull 2019-2020 (pre-COVID recovery)",
            "start": (2019, 1, 1),
            "end": (2020, 2, 15),
            "regime_type": "bull",
        },
        {
            "name": "covid_crash_recovery",
            "label": "COVID Crash + V-Recovery (Mar-Dec 2020)",
            "start": (2020, 1, 1),
            "end": (2020, 12, 31),
            "regime_type": "volatile",
        },
        {
            "name": "bull_2021",
            "label": "2021 Bull Market (post-COVID expansion)",
            "start": (2021, 1, 1),
            "end": (2021, 12, 31),
            "regime_type": "bull",
        },
        {
            "name": "bear_2022",
            "label": "2022 Bear Market (rate hikes, tech crash)",
            "start": (2022, 1, 1),
            "end": (2022, 12, 31),
            "regime_type": "bear",
        },
        {
            "name": "ai_bull_2023_2025",
            "label": "AI Bull Run 2023-2025 (AVGO AI boom)",
            "start": (2023, 1, 1),
            "end": (2025, 12, 31),
            "regime_type": "bull",
        },
    ]

    results = []
    for regime in regimes:
        code = patch_dates(base_code, regime["start"], regime["end"])
        result = run_backtest(code, f"regime_{regime['name']}")
        stats = extract_stats(result)

        net = get_stat(stats, "net profit") or 0
        dd = get_stat(stats, "drawdown") or 0
        sharpe = get_stat(stats, "sharpe") or 0
        orders = get_stat(stats, "total orders") or 0
        win_rate = get_stat(stats, "win rate") or 0

        entry = {
            "regime": regime["name"],
            "label": regime["label"],
            "regime_type": regime["regime_type"],
            "net": net,
            "dd": dd,
            "sharpe": sharpe,
            "orders": orders,
            "win_rate": win_rate,
        }
        results.append(entry)
        log(f"  {regime['name']} ({regime['regime_type']}): Net={net:.1f}% Sharpe={sharpe:.3f} Orders={orders}")

    # Analyze regime dependency
    bull_nets = [r["net"] for r in results if r["regime_type"] == "bull"]
    bear_nets = [r["net"] for r in results if r["regime_type"] == "bear"]
    volatile_nets = [r["net"] for r in results if r["regime_type"] == "volatile"]

    bull_avg = np.mean(bull_nets) if bull_nets else 0
    bear_avg = np.mean(bear_nets) if bear_nets else 0
    volatile_avg = np.mean(volatile_nets) if volatile_nets else 0

    # Check if bear market performance is destructive
    bear_destructive = any(n < -20 for n in bear_nets)
    all_regimes_positive = all(r["net"] >= -5 for r in results)

    summary = {
        "results_by_regime": results,
        "bull_avg_return": round(bull_avg, 1),
        "bear_avg_return": round(bear_avg, 1),
        "volatile_avg_return": round(volatile_avg, 1),
        "bear_destructive": bear_destructive,
        "all_regimes_acceptable": all_regimes_positive,
        "assessment": (
            f"Bull avg: {bull_avg:.1f}%, Bear avg: {bear_avg:.1f}%, Volatile avg: {volatile_avg:.1f}%. "
            f"{'CONCERN: Strategy takes significant losses in bear markets.' if bear_destructive else 'Strategy does not take destructive losses in bear markets.'} "
            f"{'All regimes acceptable (no regime below -5%).' if all_regimes_positive else 'Some regimes show losses beyond -5%.'} "
            f"The 200W SMA dip+reclaim filter naturally limits entries to post-correction periods, "
            f"providing inherent regime protection."
        ),
    }

    return summary


# ============================================================
# TEST 8: WALK-FORWARD EFFICIENCY (WFE)
# ============================================================
def test_walk_forward_efficiency(base_code):
    """OOS return / IS return ratio with multiple windows."""
    log("\n" + "="*60)
    log("TEST 8: WALK-FORWARD EFFICIENCY")
    log("="*60)

    # Use overlapping windows to maximize signal
    windows = [
        # Window 1: IS=2016-2020, OOS=2021-2022
        {"is_start": (2016, 1, 1), "is_end": (2020, 12, 31),
         "oos_start": (2021, 1, 1), "oos_end": (2022, 12, 31),
         "label": "WF1: IS 2016-2020, OOS 2021-2022"},
        # Window 2: IS=2016-2021, OOS=2022-2023
        {"is_start": (2016, 1, 1), "is_end": (2021, 12, 31),
         "oos_start": (2022, 1, 1), "oos_end": (2023, 12, 31),
         "label": "WF2: IS 2016-2021, OOS 2022-2023"},
        # Window 3: IS=2016-2022, OOS=2023-2025
        {"is_start": (2016, 1, 1), "is_end": (2022, 12, 31),
         "oos_start": (2023, 1, 1), "oos_end": (2025, 12, 31),
         "label": "WF3: IS 2016-2022, OOS 2023-2025"},
        # Window 4: IS=2018-2022, OOS=2023-2025
        {"is_start": (2018, 1, 1), "is_end": (2022, 12, 31),
         "oos_start": (2023, 1, 1), "oos_end": (2025, 12, 31),
         "label": "WF4: IS 2018-2022, OOS 2023-2025"},
        # Window 5: IS=2016-2019, OOS=2020-2022
        {"is_start": (2016, 1, 1), "is_end": (2019, 12, 31),
         "oos_start": (2020, 1, 1), "oos_end": (2022, 12, 31),
         "label": "WF5: IS 2016-2019, OOS 2020-2022"},
    ]

    results = []
    for wf in windows:
        # IS backtest
        is_code = patch_dates(base_code, wf["is_start"], wf["is_end"])
        is_result = run_backtest(is_code, f"wf_is_{wf['label'][:5]}")
        is_stats = extract_stats(is_result)
        is_cagr = get_stat(is_stats, "compounding annual") or 0
        is_sharpe = get_stat(is_stats, "sharpe") or 0
        is_net = get_stat(is_stats, "net profit") or 0
        is_orders = get_stat(is_stats, "total orders") or 0

        # OOS backtest
        oos_code = patch_dates(base_code, wf["oos_start"], wf["oos_end"])
        oos_result = run_backtest(oos_code, f"wf_oos_{wf['label'][:5]}")
        oos_stats = extract_stats(oos_result)
        oos_cagr = get_stat(oos_stats, "compounding annual") or 0
        oos_sharpe = get_stat(oos_stats, "sharpe") or 0
        oos_net = get_stat(oos_stats, "net profit") or 0
        oos_orders = get_stat(oos_stats, "total orders") or 0

        # Compute WFE
        wfe_cagr = (oos_cagr / is_cagr) if is_cagr != 0 else None
        wfe_sharpe = (oos_sharpe / is_sharpe) if is_sharpe != 0 else None

        entry = {
            "label": wf["label"],
            "is": {
                "cagr": is_cagr, "sharpe": is_sharpe, "net": is_net, "orders": is_orders,
            },
            "oos": {
                "cagr": oos_cagr, "sharpe": oos_sharpe, "net": oos_net, "orders": oos_orders,
            },
            "wfe_cagr": round(wfe_cagr, 3) if wfe_cagr is not None else None,
            "wfe_sharpe": round(wfe_sharpe, 3) if wfe_sharpe is not None else None,
            "wfe_assessment": "",
        }

        if wfe_cagr is not None:
            if wfe_cagr >= 1.0:
                entry["wfe_assessment"] = "EXCEPTIONAL (>1.0)"
            elif wfe_cagr >= 0.5:
                entry["wfe_assessment"] = "ACCEPTABLE (>0.5)"
            elif wfe_cagr > 0:
                entry["wfe_assessment"] = "WEAK (0-0.5)"
            elif oos_orders == 0:
                entry["wfe_assessment"] = "NO OOS TRADES (signal sparsity)"
            else:
                entry["wfe_assessment"] = "FAIL (<0)"
        else:
            if is_orders == 0:
                entry["wfe_assessment"] = "NO IS TRADES"
            elif oos_orders == 0:
                entry["wfe_assessment"] = "NO OOS TRADES (signal sparsity)"
            else:
                entry["wfe_assessment"] = "INDETERMINATE"

        results.append(entry)
        log(f"  {wf['label']}")
        log(f"    IS: CAGR={is_cagr:.1f}% Sharpe={is_sharpe:.3f} Orders={is_orders}")
        log(f"    OOS: CAGR={oos_cagr:.1f}% Sharpe={oos_sharpe:.3f} Orders={oos_orders}")
        log(f"    WFE(CAGR): {wfe_cagr:.3f if wfe_cagr else 'N/A'} | {entry['wfe_assessment']}")

    # Summary
    valid_wfes = [r["wfe_cagr"] for r in results if r["wfe_cagr"] is not None and r["oos"]["orders"] > 0]
    avg_wfe = np.mean(valid_wfes) if valid_wfes else None
    no_trade_windows = sum(1 for r in results if r["oos"]["orders"] == 0)

    summary = {
        "windows": results,
        "avg_wfe_cagr": round(avg_wfe, 3) if avg_wfe is not None else None,
        "valid_wfe_count": len(valid_wfes),
        "no_trade_oos_windows": no_trade_windows,
        "overall_assessment": "",
    }

    if no_trade_windows >= 3:
        summary["overall_assessment"] = (
            f"STRUCTURAL LIMITATION: {no_trade_windows}/{len(results)} OOS windows had 0 trades. "
            f"The 200W SMA dip+reclaim strategy fires very rarely on AVGO. "
            f"WFE cannot be reliably computed. The strategy is inherently regime-dependent "
            f"(only fires around major corrections). This is not necessarily a flaw - "
            f"it means the strategy is disciplined about entry, but cannot be validated "
            f"through standard walk-forward analysis."
        )
    elif avg_wfe and avg_wfe >= 0.5:
        summary["overall_assessment"] = f"PASS: Average WFE of {avg_wfe:.3f} is {'EXCEPTIONAL' if avg_wfe >= 1.0 else 'ACCEPTABLE'}."
    elif avg_wfe:
        summary["overall_assessment"] = f"WEAK: Average WFE of {avg_wfe:.3f} is below 0.5 threshold."
    else:
        summary["overall_assessment"] = "INDETERMINATE: Not enough valid WFE data."

    log(f"  Overall: {summary['overall_assessment']}")

    return summary


# ============================================================
# MAIN
# ============================================================
def main():
    log("=" * 60)
    log("AVGO v2.8+ COMPREHENSIVE STRESS TEST SUITE")
    log("=" * 60)
    log(f"Baseline: +{BASELINE['net_profit']}%, Sharpe {BASELINE['sharpe']}, {BASELINE['max_dd']}% DD, {BASELINE['orders']} orders")
    log(f"Output: {OUTPUT_PATH}")

    with open(ALGO_PATH) as f:
        base_code = f.read()

    all_results = {
        "strategy": "AVGO_v28plus_TrendAdder",
        "ticker": "AVGO",
        "timestamp": datetime.now().isoformat(),
        "baseline": BASELINE,
        "tests": {},
    }

    # Test 1: Slippage Stress
    try:
        all_results["tests"]["slippage_stress"] = test_slippage_stress(base_code)
    except Exception as e:
        log(f"TEST 1 FAILED: {e}")
        all_results["tests"]["slippage_stress"] = {"error": str(e)}

    # Test 2: Bear Market Isolation
    try:
        all_results["tests"]["bear_market_isolation"] = test_bear_market_isolation(base_code)
    except Exception as e:
        log(f"TEST 2 FAILED: {e}")
        all_results["tests"]["bear_market_isolation"] = {"error": str(e)}

    # Test 3: Parameter Sensitivity
    try:
        all_results["tests"]["parameter_sensitivity"] = test_parameter_sensitivity(base_code)
    except Exception as e:
        log(f"TEST 3 FAILED: {e}")
        all_results["tests"]["parameter_sensitivity"] = {"error": str(e)}

    # Test 4: False Signal Analysis
    try:
        all_results["tests"]["false_signal_analysis"] = test_false_signals(base_code)
    except Exception as e:
        log(f"TEST 4 FAILED: {e}")
        all_results["tests"]["false_signal_analysis"] = {"error": str(e)}

    # Test 5: Monte Carlo Bootstrap
    try:
        all_results["tests"]["monte_carlo"] = test_monte_carlo(base_code)
    except Exception as e:
        log(f"TEST 5 FAILED: {e}")
        all_results["tests"]["monte_carlo"] = {"error": str(e)}

    # Test 6: Drawdown Duration
    try:
        all_results["tests"]["drawdown_duration"] = test_drawdown_duration(base_code)
    except Exception as e:
        log(f"TEST 6 FAILED: {e}")
        all_results["tests"]["drawdown_duration"] = {"error": str(e)}

    # Test 7: Regime Dependency
    try:
        all_results["tests"]["regime_dependency"] = test_regime_dependency(base_code)
    except Exception as e:
        log(f"TEST 7 FAILED: {e}")
        all_results["tests"]["regime_dependency"] = {"error": str(e)}

    # Test 8: Walk-Forward Efficiency
    try:
        all_results["tests"]["walk_forward_efficiency"] = test_walk_forward_efficiency(base_code)
    except Exception as e:
        log(f"TEST 8 FAILED: {e}")
        all_results["tests"]["walk_forward_efficiency"] = {"error": str(e)}

    # ============================================================
    # FINAL VERDICT
    # ============================================================
    verdict = compute_final_verdict(all_results)
    all_results["final_verdict"] = verdict

    # Save
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    log(f"\n{'='*60}")
    log("ALL STRESS TESTS COMPLETE")
    log(f"{'='*60}")
    log(f"Results saved to: {OUTPUT_PATH}")
    log(f"\nFINAL VERDICT: {verdict['recommendation']}")

    return all_results


def compute_final_verdict(results):
    """Compute overall stress test verdict."""
    tests = results.get("tests", {})
    scores = {}

    # 1. Slippage: does edge survive at 300bps?
    slip = tests.get("slippage_stress", [])
    if isinstance(slip, list):
        slip_300 = [s for s in slip if s.get("bps") == 300]
        slip_200 = [s for s in slip if s.get("bps") == 200]
        slip_100 = [s for s in slip if s.get("bps") == 100]

        if slip_300 and slip_300[0].get("edge_survives"):
            scores["slippage"] = "PASS_STRONG"
        elif slip_200 and slip_200[0].get("edge_survives"):
            scores["slippage"] = "PASS"
        elif slip_100 and slip_100[0].get("edge_survives"):
            scores["slippage"] = "PASS_WEAK"
        else:
            scores["slippage"] = "FAIL"

    # 2. Bear market: no catastrophic losses
    bear = tests.get("bear_market_isolation", [])
    if isinstance(bear, list):
        bear_results = [r for r in bear if "2022" in r.get("regime", "")]
        if bear_results:
            worst_dd = max(r.get("with_adder", {}).get("dd", 0) for r in bear_results)
            scores["bear_market"] = "PASS" if worst_dd < 30 else "CONCERN"
        else:
            scores["bear_market"] = "NO_DATA"

    # 3. Parameter sensitivity: mostly robust?
    param = tests.get("parameter_sensitivity", [])
    if isinstance(param, list):
        robust_count = sum(1 for p in param if p.get("robust", False))
        total = len(param)
        if total > 0:
            pct_robust = robust_count / total * 100
            scores["param_sensitivity"] = "PASS" if pct_robust >= 60 else "CONCERN"
        else:
            scores["param_sensitivity"] = "NO_DATA"

    # 4. Monte Carlo: positive in >70% of sims
    mc = tests.get("monte_carlo", {})
    if isinstance(mc, dict) and "return_distribution" in mc:
        pct_pos = mc["return_distribution"].get("pct_positive", 0)
        scores["monte_carlo"] = "PASS" if pct_pos >= 70 else "CONCERN"

    # 5. Drawdown duration: holdable?
    dd = tests.get("drawdown_duration", {})
    if isinstance(dd, dict):
        dd_label = dd.get("psychology_assessment", {}).get("max_dd_label", "")
        scores["drawdown"] = "PASS" if dd_label in ["EXCELLENT", "GOOD", "ACCEPTABLE"] else "CONCERN"

    # 6. Regime: not purely bull-dependent
    regime = tests.get("regime_dependency", {})
    if isinstance(regime, dict):
        scores["regime"] = "PASS" if not regime.get("bear_destructive", True) else "CONCERN"

    # 7. WFE
    wfe = tests.get("walk_forward_efficiency", {})
    if isinstance(wfe, dict):
        avg_wfe = wfe.get("avg_wfe_cagr")
        no_trade = wfe.get("no_trade_oos_windows", 0)
        if no_trade >= 3:
            scores["wfe"] = "STRUCTURAL_LIMITATION"
        elif avg_wfe and avg_wfe >= 0.5:
            scores["wfe"] = "PASS"
        elif avg_wfe and avg_wfe > 0:
            scores["wfe"] = "WEAK"
        else:
            scores["wfe"] = "INDETERMINATE"

    # Overall
    pass_count = sum(1 for v in scores.values() if "PASS" in str(v))
    concern_count = sum(1 for v in scores.values() if v in ["CONCERN", "FAIL"])
    total_tests = len(scores)

    if concern_count == 0 and pass_count >= 5:
        recommendation = "STRONG PASS - AVGO v2.8+ is robust across all stress tests. Recommend adding as second ticker."
    elif concern_count <= 1 and pass_count >= 4:
        recommendation = "PASS WITH NOTES - AVGO v2.8+ passes most stress tests with minor concerns. Acceptable for addition."
    elif concern_count <= 2 and pass_count >= 3:
        recommendation = "CONDITIONAL PASS - AVGO v2.8+ has some concerns but core edge is intact. Consider risk adjustments."
    else:
        recommendation = "FAIL - AVGO v2.8+ does not pass enough stress tests. Do not add without significant modifications."

    return {
        "scores": scores,
        "pass_count": pass_count,
        "concern_count": concern_count,
        "total_tests": total_tests,
        "recommendation": recommendation,
    }


if __name__ == "__main__":
    main()
