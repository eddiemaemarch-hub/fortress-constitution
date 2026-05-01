#!/usr/bin/env python3
"""
OOS Re-Validation — Rudy v2.8+ Quarterly Parameter Health Check

Adds the latest completed quarter as a new anchored OOS window, runs the full
27-parameter grid on all prior IS data, then checks whether the live parameters
(standard_medium_safety) still rank #1. Sends a Telegram verdict and saves results.

This script NEVER modifies live parameters. It reports findings only.
Commander approves any changes via the manual walk-forward update process.

Usage:
    python3 oos_revalidation.py                       # Auto-detect latest quarter
    python3 oos_revalidation.py --quarter Q4 --year 2025  # Specific quarter
    python3 oos_revalidation.py --report              # Print last saved report
    python3 oos_revalidation.py --dry-run             # Show plan, no backtests

Output:
    ~/rudy/data/oos_revalidation_YYYY_QN.json
    ~/rudy/logs/oos_revalidation.log
    Telegram summary (PASS / WARN / DRIFT ALERT)
"""

import os
import sys
import re
import json
import time
import argparse
from datetime import datetime, date, timedelta
from hashlib import sha256
from base64 import b64encode
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import telegram

# ── Load env ──
_env_file = os.path.expanduser("~/.agent_zero_env")
if os.path.exists(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if "=" in _line and not _line.startswith("#"):
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip())

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════
# v50.4 (2026-05-01): token now read from env (set QC_API_TOKEN in
# ~/.agent_zero_env). The hardcoded literal that lived here is in git
# history — ROTATE the QuantConnect token to fully invalidate it.
QC_API_TOKEN = os.environ.get("QC_API_TOKEN", "")
QC_USER_ID = os.environ.get("QC_USER_ID", "473242")
QC_BASE = "https://www.quantconnect.com/api/v2"
PROJECT_ID = 29065184

ALGO_PATH = os.path.expanduser("~/rudy/quantconnect/MSTRCycleLowLeap_v28plus.py")
DATA_DIR = os.path.expanduser("~/rudy/data")
LOG_FILE = os.path.expanduser("~/rudy/logs/oos_revalidation.log")
WF_RESULTS_FILE = os.path.join(DATA_DIR, "wf_v28plus_results.json")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# ── Live parameters — never auto-update these ──
CURRENT_LIVE_PARAMS = "standard_medium_safety"
IS_START = date(2016, 1, 1)  # Fixed anchored IS start

# ── Drift thresholds ──
DRIFT_WARN_THRESHOLD = 0.90    # Live params score < 90% of winner → WARN
DRIFT_ALERT_THRESHOLD = 0.75   # Live params score < 75% of winner → DRIFT ALERT
MIN_WFE_RATIO = 0.50           # OOS/IS score ratio must exceed this

# ═══════════════════════════════════════════════════════════════
# PARAMETER GRID (mirrors walk_forward_v28plus.py exactly)
# ═══════════════════════════════════════════════════════════════
BASE_PARAMS = {
    "low_cap": 0.7, "fair_cap": 1.0, "elevated_cap": 1.3,
    "low_mult": 7.2, "fair_mult": 6.5, "elevated_mult": 4.8, "euphoric_mult": 3.3,
    "ladder_tiers": [(10000, 12.0), (5000, 20.0), (2000, 25.0), (1000, 30.0), (500, 35.0)],
}

CONFIRM_WEEKS = {"quick": 3, "standard": 4, "patient": 6}
CONVERGENCE_PCT = {"tight": 10.0, "medium": 15.0, "wide": 25.0}
ADDER_TRAILS = {
    "minimal":  [(10000, 20.0), (5000, 30.0)],
    "safety":   [(10000, 25.0), (5000, 35.0)],
    "moderate": [(10000, 20.0), (5000, 30.0), (2000, 40.0)],
}


def build_param_grid():
    """Generate all 27 trend adder parameter combinations."""
    grid = []
    for cw_name, cw in CONFIRM_WEEKS.items():
        for cp_name, cp in CONVERGENCE_PCT.items():
            for at_name, at in ADDER_TRAILS.items():
                grid.append({
                    "name": f"{cw_name}_{cp_name}_{at_name}",
                    "confirm_weeks": cw,
                    "convergence_pct": cp,
                    "adder_trails": at,
                    **BASE_PARAMS,
                })
    return grid


# ═══════════════════════════════════════════════════════════════
# QUARTER LOGIC
# ═══════════════════════════════════════════════════════════════

QUARTER_RANGES = {
    1: (date(2000, 1, 1).replace, date(2000, 3, 31).replace),   # Q1: Jan-Mar
    2: (date(2000, 4, 1).replace, date(2000, 6, 30).replace),   # Q2: Apr-Jun
    3: (date(2000, 7, 1).replace, date(2000, 9, 30).replace),   # Q3: Jul-Sep
    4: (date(2000, 10, 1).replace, date(2000, 12, 31).replace), # Q4: Oct-Dec
}


def last_completed_quarter():
    """Return (oos_start, oos_end, quarter_label) for the last fully completed quarter."""
    today = date.today()
    q = (today.month - 1) // 3 + 1  # Current quarter
    year = today.year

    # Step back one quarter
    if q == 1:
        q, year = 4, year - 1
    else:
        q -= 1

    starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
    ends = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}

    oos_start = date(year, starts[q][0], starts[q][1])
    oos_end = date(year, ends[q][0], ends[q][1])
    label = f"Q{q} {year}"

    return oos_start, oos_end, label


def parse_quarter_arg(q_str, year):
    """Parse --quarter Q3 --year 2025 into dates."""
    q = int(q_str.replace("Q", "").replace("q", ""))
    if q not in range(1, 5):
        raise ValueError(f"Quarter must be Q1-Q4, got '{q_str}'")
    starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
    ends = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    oos_start = date(year, starts[q][0], starts[q][1])
    oos_end = date(year, ends[q][0], ends[q][1])
    return oos_start, oos_end, f"Q{q} {year}"


def result_file_path(oos_start, label):
    """Standardized output file path for a given quarter."""
    safe = label.replace(" ", "_")
    return os.path.join(DATA_DIR, f"oos_revalidation_{safe}.json")


# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ═══════════════════════════════════════════════════════════════
# QC API (mirrors walk_forward_v28plus.py)
# ═══════════════════════════════════════════════════════════════

def _auth_headers():
    timestamp = str(int(time.time()))
    hashed = sha256(f"{QC_API_TOKEN}:{timestamp}".encode()).hexdigest()
    auth = b64encode(f"{QC_USER_ID}:{hashed}".encode()).decode()
    return {"Authorization": f"Basic {auth}", "Timestamp": timestamp, "Content-Type": "application/json"}


def _post(endpoint, data=None):
    for attempt in range(3):
        try:
            r = requests.post(f"{QC_BASE}/{endpoint}", headers=_auth_headers(),
                              json=data or {}, timeout=60)
            if r.status_code == 429:
                wait = 10 * (2 ** attempt)
                log(f"Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            return r.json()
        except Exception as e:
            if attempt < 2:
                log(f"API error: {e}, retrying in 10s...", "WARN")
                time.sleep(10)
            else:
                raise
    return {"success": False, "errors": ["Rate limit exhausted"]}


def patch_algo(code, params, end_date):
    """Patch the v2.8+ algo with parameters and end date (copied from walk_forward_v28plus.py)."""
    patched = code
    patched = re.sub(
        r"self\.SetEndDate\(\d+,\s*\d+,\s*\d+\)",
        f"self.SetEndDate({end_date.year}, {end_date.month}, {end_date.day})",
        patched,
    )
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
    ladder_str = "self.ladder_tiers = [\n"
    for gain, trail in params["ladder_tiers"]:
        ladder_str += f"            ({gain}, {trail}),\n"
    ladder_str += "        ]"
    patched = re.sub(r"self\.ladder_tiers\s*=\s*\[.*?\]", ladder_str, patched, count=1, flags=re.DOTALL)
    patched = re.sub(r"self\.premium_cap\s*=\s*[\d.]+", f"self.premium_cap = {params['elevated_cap']}", patched)
    patched = re.sub(r"self\.trend_confirm_weeks\s*=\s*\d+", f"self.trend_confirm_weeks = {params['confirm_weeks']}", patched)
    patched = re.sub(r"self\.trend_convergence_pct\s*=\s*[\d.]+", f"self.trend_convergence_pct = {params['convergence_pct']}", patched)
    adder_ladder_str = "self.trend_adder_ladder = [\n"
    for gain, trail in params["adder_trails"]:
        adder_ladder_str += f"            ({gain}, {trail}),\n"
    adder_ladder_str += "        ]"
    patched = re.sub(r"self\.trend_adder_ladder\s*=\s*\[.*?\]", adder_ladder_str, patched, count=1, flags=re.DOTALL)
    return patched


def run_backtest(code, name):
    """Upload, compile, run, and return stats dict (or None on failure)."""
    result = _post("files/update", {"projectId": PROJECT_ID, "name": "main.py", "content": code})
    if not result.get("success"):
        result = _post("files/create", {"projectId": PROJECT_ID, "name": "main.py", "content": code})
    if not result.get("success"):
        log(f"Upload failed: {result}", "ERROR")
        return None

    compile_result = _post("compile/create", {"projectId": PROJECT_ID})
    compile_id = compile_result.get("compileId", "")
    state = compile_result.get("state", "")

    if state != "BuildSuccess":
        for _ in range(40):
            time.sleep(3)
            check = _post("compile/read", {"projectId": PROJECT_ID, "compileId": compile_id})
            state = check.get("state", "")
            if state == "BuildSuccess":
                break
            if state == "BuildError":
                log(f"BUILD ERROR: {check.get('errors', [])}", "ERROR")
                return None
    if state != "BuildSuccess":
        log("Compile timed out", "ERROR")
        return None

    bt_result = _post("backtests/create", {
        "projectId": PROJECT_ID, "compileId": compile_id, "backtestName": name
    })
    if not bt_result.get("success"):
        log(f"Launch failed: {bt_result}", "ERROR")
        return None

    backtest_id = bt_result.get("backtest", {}).get("backtestId") or bt_result.get("backtestId", "")
    if not backtest_id:
        log("No backtest ID returned", "ERROR")
        return None

    for i in range(240):
        time.sleep(2)
        result = _post("backtests/read", {"projectId": PROJECT_ID, "backtestId": backtest_id})
        bt = result.get("backtest", result)
        status = bt.get("status", "")
        progress = bt.get("progress", 0)
        if status == "Completed" or (isinstance(progress, (int, float)) and progress >= 1.0):
            stats = bt.get("statistics", {})
            if not stats:
                time.sleep(2)
                result = _post("backtests/read", {"projectId": PROJECT_ID, "backtestId": backtest_id})
                stats = result.get("backtest", result).get("statistics", {})
            return stats
        if i % 15 == 0 and i > 0:
            log(f"  Progress: {progress} | Status: {status}")

    log("Backtest timed out (8 min)", "ERROR")
    return None


# ═══════════════════════════════════════════════════════════════
# SCORING (identical formula to walk_forward_v28plus.py)
# ═══════════════════════════════════════════════════════════════

def parse_stat(stats, key, default=0.0):
    if not stats:
        return default
    val = stats.get(key, str(default))
    if isinstance(val, (int, float)):
        return float(val)
    val = val.replace("%", "").replace("$", "").replace(",", "").strip()
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def score_backtest(stats):
    """Composite score: 0.4×Sharpe + 0.3×(Return/100) + 0.3×(1−DD/100)."""
    if not stats:
        return -999.0
    sharpe = parse_stat(stats, "Sharpe Ratio")
    net = parse_stat(stats, "Net Profit")
    dd = parse_stat(stats, "Drawdown")
    trades = int(parse_stat(stats, "Total Orders"))
    if trades < 2:
        return -999.0
    return round(0.4 * sharpe + 0.3 * (net / 100.0) + 0.3 * (1.0 - dd / 100.0), 4)


# ═══════════════════════════════════════════════════════════════
# REGIME CONTEXT
# ═══════════════════════════════════════════════════════════════

def get_regime_for_quarter(oos_start, oos_end):
    """Return System 13 regime label(s) that were active during the OOS quarter."""
    regime_map = [
        (date(2015, 1, 1),  date(2015, 10, 15), "ACCUMULATION"),
        (date(2015, 10, 16), date(2017, 6, 10), "MARKUP"),
        (date(2017, 6, 11), date(2017, 12, 31), "DISTRIBUTION"),
        (date(2018, 1, 1),  date(2018, 12, 31), "MARKDOWN"),
        (date(2019, 1, 1),  date(2020, 3, 15),  "ACCUMULATION"),
        (date(2020, 3, 16), date(2021, 4, 14),  "MARKUP"),
        (date(2021, 4, 15), date(2021, 11, 10), "DISTRIBUTION"),
        (date(2021, 11, 11),date(2022, 11, 20), "MARKDOWN"),
        (date(2022, 11, 21),date(2024, 1, 10),  "ACCUMULATION"),
        (date(2024, 1, 11), date(2025, 10, 15), "MARKUP"),
        (date(2025, 10, 16),date(2027, 12, 31), "DISTRIBUTION"),
    ]
    # Try live regime state first
    try:
        with open(os.path.join(DATA_DIR, "regime_state.json")) as f:
            rs = json.load(f)
        if rs.get("regime"):
            return rs["regime"]
    except Exception:
        pass

    # Fall back to historical map
    regimes = set()
    for r_start, r_end, regime in regime_map:
        if oos_start <= r_end and oos_end >= r_start:
            regimes.add(regime)
    return "/".join(sorted(regimes)) if regimes else "UNKNOWN"


# ═══════════════════════════════════════════════════════════════
# HISTORICAL CONTEXT
# ═══════════════════════════════════════════════════════════════

def load_historical_wf():
    """Load existing walk-forward results for comparison context."""
    if not os.path.exists(WF_RESULTS_FILE):
        return None
    try:
        with open(WF_RESULTS_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def get_historical_win_rate(results_data):
    """How often did standard_medium_safety win in original WF runs?"""
    if not results_data:
        return None, 0, 0
    windows = results_data.get("windows", {})
    total = len(windows)
    wins = sum(1 for w in windows.values() if w.get("best_params") == CURRENT_LIVE_PARAMS)
    return wins / total if total > 0 else 0.0, wins, total


# ═══════════════════════════════════════════════════════════════
# QUARTERLY HISTORY (rolling averages, winner stability, streaks)
# ═══════════════════════════════════════════════════════════════

DRIFT_HISTORY_FILE = os.path.join(DATA_DIR, "oos_revalidation_history.json")


def load_all_quarterly_results():
    """Load all past oos_revalidation_*.json files, sorted chronologically."""
    import glob as _glob
    files = sorted(_glob.glob(os.path.join(DATA_DIR, "oos_revalidation_Q*.json")))
    results = []
    for fp in files:
        try:
            with open(fp) as f:
                results.append(json.load(f))
        except Exception:
            continue
    return results


def load_drift_history():
    """Load the persistent drift history tracker."""
    if os.path.exists(DRIFT_HISTORY_FILE):
        try:
            with open(DRIFT_HISTORY_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"quarters": [], "consecutive_drift_alerts": 0, "consecutive_warns": 0}


def save_drift_history(history):
    """Save the persistent drift history tracker."""
    with open(DRIFT_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2, default=str)


def compute_rolling_oos(past_results, current_oos_score, n=4):
    """Compute rolling N-quarter OOS average including current quarter."""
    scores = []
    for r in past_results:
        oos = r.get("oos_result", {})
        sc = oos.get("score")
        if sc is not None and sc > -900:
            scores.append(sc)
    scores.append(current_oos_score)
    recent = scores[-n:]
    if not recent:
        return None, 0
    return round(sum(recent) / len(recent), 4), len(recent)


def assess_winner_stability(past_results, current_winner):
    """Track grid winner across quarters. Flag instability."""
    winners = []
    for r in past_results:
        s = r.get("summary", {})
        w = s.get("winner")
        if w:
            winners.append({"quarter": r.get("label", "?"), "winner": w})
    winners.append({"quarter": "current", "winner": current_winner})

    if len(winners) < 2:
        return {"stable": True, "history": winners, "changes": 0, "message": "Insufficient history"}

    # Count how many times winner changed
    changes = sum(1 for i in range(1, len(winners)) if winners[i]["winner"] != winners[i-1]["winner"])
    unique_winners = len(set(w["winner"] for w in winners))
    total = len(winners)

    # Flag if winner changed in >50% of transitions or >2 unique winners in last 4
    recent = winners[-4:]
    recent_unique = len(set(w["winner"] for w in recent))

    stable = recent_unique <= 2 and changes <= len(winners) // 2
    if not stable:
        msg = (f"UNSTABLE: {recent_unique} different winners in last {len(recent)} quarters "
               f"({changes} changes total). Grid may be fitting noise.")
    else:
        msg = f"Stable: {unique_winners} unique winner(s) across {total} quarter(s), {changes} change(s)"

    return {
        "stable": stable,
        "history": winners,
        "changes": changes,
        "unique_winners": unique_winners,
        "recent_unique": recent_unique,
        "message": msg,
    }


def update_drift_streak(history, verdict, label):
    """Update consecutive drift/warn counters. Return escalation level."""
    entry = {"quarter": label, "verdict": verdict, "timestamp": datetime.now().isoformat()}
    history["quarters"].append(entry)

    if verdict == "DRIFT_ALERT":
        history["consecutive_drift_alerts"] += 1
        history["consecutive_warns"] = 0
    elif verdict == "WARN":
        history["consecutive_warns"] += 1
        # Don't reset drift counter on WARN — only on PASS
    else:  # PASS
        history["consecutive_drift_alerts"] = 0
        history["consecutive_warns"] = 0

    streak = history["consecutive_drift_alerts"]
    if streak >= 3:
        escalation = "CRITICAL"
        escalation_msg = (
            f"🔴 3+ CONSECUTIVE DRIFT ALERTS ({streak} quarters)\n"
            f"MANDATORY: Re-optimize parameters OR pause strategy.\n"
            f"Commander must decide: full walk-forward update or strategy halt."
        )
    elif streak >= 2:
        escalation = "MANDATORY_REVIEW"
        escalation_msg = (
            f"🟠 2 CONSECUTIVE DRIFT ALERTS\n"
            f"MANDATORY REVIEW: Run full walk-forward analysis.\n"
            f"Prepare parameter update proposal for Commander approval."
        )
    elif streak >= 1:
        escalation = "ALERT"
        escalation_msg = f"🟡 First drift alert. Monitor next quarter closely."
    else:
        escalation = "NONE"
        escalation_msg = ""

    return escalation, escalation_msg, streak


# ═══════════════════════════════════════════════════════════════
# DRIFT VERDICT
# ═══════════════════════════════════════════════════════════════

def assess_drift(is_results, oos_result, label, regime="UNKNOWN"):
    """
    Determine PASS / WARN / DRIFT ALERT based on:
    1. Live param IS rank (must be #1 or close)
    2. Live param OOS score vs IS score (WFE ratio)
    3. Whether a different param set dominates
    4. Rolling 4-quarter OOS average (smooths single-quarter anomalies)
    5. Grid winner stability (detects noise-fitting)
    6. Consecutive drift alert escalation
    7. Regime context (distinguishes decay from temporary conditions)
    """
    if not is_results:
        return "ERROR", "No IS results to analyze.", {}

    # Sort IS results by score
    ranked = sorted(is_results.items(), key=lambda x: x[1]["score"], reverse=True)
    if not ranked:
        return "ERROR", "All backtests failed.", {}

    winner_name, winner_data = ranked[0]
    winner_score = winner_data["score"]

    live_data = is_results.get(CURRENT_LIVE_PARAMS)
    live_score = live_data["score"] if live_data else -999.0
    live_rank = next((i + 1 for i, (n, _) in enumerate(ranked) if n == CURRENT_LIVE_PARAMS), 999)

    # WFE ratio
    oos_score = oos_result.get("score", -999.0) if oos_result else -999.0
    is_score_of_live = live_score
    wfe = (oos_score / is_score_of_live) if is_score_of_live > 0 else 0.0

    # Relative rank score
    relative_score = (live_score / winner_score) if winner_score > 0 else 0.0

    # ── Rolling 4-quarter OOS average ──
    past_results = load_all_quarterly_results()
    rolling_avg, rolling_count = compute_rolling_oos(past_results, oos_score, n=4)

    # ── Winner stability ──
    stability = assess_winner_stability(past_results, winner_name)

    # ── Regime-aware context ──
    # MARKDOWN/DISTRIBUTION regimes may naturally produce lower scores
    # without indicating strategy decay
    adverse_regimes = {"MARKDOWN", "DISTRIBUTION"}
    regime_tags = set(regime.split("/")) if regime else set()
    in_adverse_regime = bool(regime_tags & adverse_regimes)

    verdict_lines = [
        f"Live params ({CURRENT_LIVE_PARAMS}) IS rank: #{live_rank}/27",
        f"Live IS score: {live_score:.4f} | Winner IS score: {winner_score:.4f}",
        f"Relative score: {relative_score:.1%} of winner",
        f"OOS score: {oos_score:.4f} | WFE ratio: {wfe:.2f}",
    ]

    if rolling_avg is not None:
        verdict_lines.append(f"Rolling {rolling_count}Q OOS avg: {rolling_avg:.4f}")

    verdict_lines.append(f"Winner stability: {stability['message']}")

    if in_adverse_regime:
        verdict_lines.append(f"⚙️ Regime context: {regime} (adverse — underperformance may be regime-driven)")

    # ── Determine base verdict ──
    if winner_name != CURRENT_LIVE_PARAMS and relative_score < DRIFT_ALERT_THRESHOLD:
        verdict = "DRIFT_ALERT"
        verdict_lines.append(f"⚠️ DRIFT: Winner is '{winner_name}' — live params at {relative_score:.0%} of winner")
    elif winner_name != CURRENT_LIVE_PARAMS and relative_score < DRIFT_WARN_THRESHOLD:
        verdict = "WARN"
        verdict_lines.append(f"⚡ WARN: Winner is '{winner_name}' — live params at {relative_score:.0%} of winner")
    elif wfe < MIN_WFE_RATIO:
        verdict = "WARN"
        verdict_lines.append(f"⚡ WARN: WFE ratio {wfe:.2f} below {MIN_WFE_RATIO:.2f} threshold")
    else:
        verdict = "PASS"
        verdict_lines.append(f"✅ PASS: Live params remain optimal (rank #{live_rank}, {relative_score:.0%} of winner)")

    # ── Regime softening: downgrade DRIFT_ALERT → WARN in adverse regimes ──
    regime_softened = False
    if verdict == "DRIFT_ALERT" and in_adverse_regime:
        # Only soften if rolling average is still healthy (above 0)
        if rolling_avg is not None and rolling_avg > 0:
            verdict = "WARN"
            regime_softened = True
            verdict_lines.append(
                f"📉 Regime override: DRIFT→WARN (adverse regime '{regime}' + rolling avg {rolling_avg:.4f} still positive)"
            )

    # ── Winner instability warning ──
    if not stability["stable"]:
        if verdict == "PASS":
            verdict = "WARN"
        verdict_lines.append(f"🔀 Winner instability: grid search may be fitting noise — consider fixing params")

    # ── Consecutive drift streak escalation ──
    drift_history = load_drift_history()
    escalation, escalation_msg, streak = update_drift_streak(drift_history, verdict, label)
    save_drift_history(drift_history)

    if escalation_msg:
        verdict_lines.append(escalation_msg)

    return verdict, "\n".join(verdict_lines), {
        "winner": winner_name,
        "winner_score": winner_score,
        "live_rank": live_rank,
        "live_is_score": live_score,
        "relative_score": relative_score,
        "oos_score": oos_score,
        "wfe_ratio": wfe,
        "top5": [(n, round(d["score"], 4)) for n, d in ranked[:5]],
        "rolling_4q_avg": rolling_avg,
        "rolling_4q_count": rolling_count,
        "winner_stability": stability,
        "regime": regime,
        "regime_softened": regime_softened,
        "in_adverse_regime": in_adverse_regime,
        "drift_streak": streak,
        "escalation": escalation,
    }


# ═══════════════════════════════════════════════════════════════
# TELEGRAM REPORT
# ═══════════════════════════════════════════════════════════════

def build_telegram_msg(label, oos_start, oos_end, verdict, drift_detail, summary, regime):
    """Format the Telegram message for the quarterly re-validation report."""

    verdict_emoji = {"PASS": "✅", "WARN": "⚠️", "DRIFT_ALERT": "🚨", "ERROR": "❌"}.get(verdict, "❓")

    live_rank = summary.get("live_rank", "?")
    live_score = summary.get("live_is_score", 0)
    winner = summary.get("winner", "?")
    winner_score = summary.get("winner_score", 0)
    relative = summary.get("relative_score", 0)
    wfe = summary.get("wfe_ratio", 0)
    oos_score = summary.get("oos_score", 0)

    oos_stats = summary.get("oos_stats", {})
    oos_net = oos_stats.get("net", 0)
    oos_sharpe = oos_stats.get("sharpe", 0)
    oos_dd = oos_stats.get("dd", 0)

    top5 = summary.get("top5", [])
    top5_lines = "\n".join(
        f"  {'🥇' if i == 0 else f'{i+1}.'} {n}: {s:.4f}"
        + (" ← LIVE" if n == CURRENT_LIVE_PARAMS else "")
        for i, (n, s) in enumerate(top5)
    )

    hist_rate = summary.get("historical_win_rate", None)
    hist_line = f"\nHistorical win rate: {hist_rate:.0%} of prior 7 WF windows" if hist_rate is not None else ""

    # Rolling 4Q OOS average
    rolling_avg = summary.get("rolling_4q_avg")
    rolling_count = summary.get("rolling_4q_count", 0)
    rolling_line = f"\nRolling {rolling_count}Q OOS avg: {rolling_avg:.4f}" if rolling_avg is not None else ""

    # Winner stability
    stability = summary.get("winner_stability", {})
    stability_line = f"\nWinner stability: {stability.get('message', 'N/A')}"

    # Regime context
    regime_softened = summary.get("regime_softened", False)
    regime_line = ""
    if summary.get("in_adverse_regime"):
        regime_line = f"\n📉 Adverse regime ({regime}) — underperformance may be regime-driven"
        if regime_softened:
            regime_line += " [verdict softened]"

    # Drift streak escalation
    streak = summary.get("drift_streak", 0)
    escalation = summary.get("escalation", "NONE")
    escalation_line = ""
    if escalation == "CRITICAL":
        escalation_line = (
            f"\n🔴 *{streak} CONSECUTIVE DRIFT ALERTS*\n"
            f"MANDATORY: Re-optimize parameters OR pause strategy."
        )
    elif escalation == "MANDATORY_REVIEW":
        escalation_line = (
            f"\n🟠 *{streak} CONSECUTIVE DRIFT ALERTS*\n"
            f"MANDATORY: Run full walk-forward analysis."
        )
    elif escalation == "ALERT" and streak > 0:
        escalation_line = f"\n🟡 First drift alert — monitor next quarter closely."

    action_line = ""
    if verdict == "DRIFT_ALERT":
        action_line = (
            f"\n🔑 *ACTION REQUIRED*\n"
            f"Run full walk-forward: `python3 walk_forward_v28plus.py`\n"
            f"Review results before updating live params manually."
        )
    elif verdict == "WARN":
        action_line = "\n💡 Monitor next quarter — no immediate action needed."

    msg = (
        f"📊 *RUDY v2.8+ QUARTERLY RE-VALIDATION*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{verdict_emoji} *Verdict: {verdict}*\n"
        f"Quarter: {label} ({oos_start} → {oos_end})\n"
        f"Regime during OOS: {regime}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📐 *IS Optimization (2016 → {oos_start})*\n"
        f"27 param combos tested\n"
        f"Live params rank: #{live_rank}/27 (score: {live_score:.4f})\n"
        f"Winner: {winner} (score: {winner_score:.4f})\n"
        f"Live at {relative:.0%} of winner\n"
        f"\n🏆 *Top 5 IS Rankings*\n"
        f"{top5_lines}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📈 *OOS Result ({label})*\n"
        f"Net: {oos_net:+.1f}% | Sharpe: {oos_sharpe:.3f} | DD: {oos_dd:.1f}%\n"
        f"OOS score: {oos_score:.4f} | WFE ratio: {wfe:.2f}\n"
        f"{rolling_line}"
        f"{hist_line}"
        f"━━━━━━━━━━━━━━━━\n"
        f"🔍 *Health Diagnostics*"
        f"{stability_line}"
        f"{regime_line}"
        f"{escalation_line}"
        f"{action_line}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Next re-validation: Start of Q{get_next_quarter_label()}"
    )
    return msg


def get_next_quarter_label():
    today = date.today()
    q = (today.month - 1) // 3 + 1
    year = today.year
    if q == 4:
        return f"1 {year + 1}"
    return f"{q + 1} {year}"


# ═══════════════════════════════════════════════════════════════
# MAIN VALIDATION FLOW
# ═══════════════════════════════════════════════════════════════

def run_revalidation(oos_start, oos_end, label, dry_run=False):
    """Execute the full quarterly re-validation for the given OOS window."""
    log(f"{'='*60}")
    log(f"RUDY v2.8+ QUARTERLY RE-VALIDATION")
    log(f"OOS Window: {label} ({oos_start} → {oos_end})")
    log(f"IS Window:  {IS_START} → {oos_start - timedelta(days=1)}")
    log(f"{'='*60}")

    is_end = oos_start - timedelta(days=1)
    out_file = result_file_path(oos_start, label)

    # Check for existing results
    if os.path.exists(out_file):
        log(f"Results already exist: {out_file}")
        log("Loading cached results...")
        with open(out_file) as f:
            return json.load(f)

    regime = get_regime_for_quarter(oos_start, oos_end)
    log(f"System 13 regime during OOS: {regime}")

    hist_data = load_historical_wf()
    hist_rate, hist_wins, hist_total = get_historical_win_rate(hist_data)
    log(f"Historical '{CURRENT_LIVE_PARAMS}' win rate: {hist_wins}/{hist_total} WF windows")

    grid = build_param_grid()
    log(f"Parameter grid: {len(grid)} combinations")

    if dry_run:
        log("DRY RUN — no backtests will be executed.")
        log(f"Would test IS period: {IS_START} → {is_end}")
        log(f"Would test OOS period: {oos_start} → {oos_end}")
        log(f"Would run {len(grid)} IS backtests + 1 OOS backtest = {len(grid) + 1} total")
        return None

    with open(ALGO_PATH) as f:
        base_code = f.read()

    # ── IN-SAMPLE GRID SEARCH ──
    log(f"\n── IN-SAMPLE: Testing {len(grid)} param combos on {IS_START} → {is_end} ──")
    is_results = {}
    try:
        telegram.send(
            f"🔬 *OOS Re-Validation started*\n"
            f"Quarter: {label}\n"
            f"Running {len(grid)} IS backtests + 1 OOS...\n"
            f"_This will take ~45–60 minutes._"
        )
    except Exception as e:
        log(f"Telegram send failed: {e}", "ERROR")

    for gi, params in enumerate(grid):
        pname = params["name"]
        log(f"  [{gi+1:2d}/{len(grid)}] {pname} ...")
        patched = patch_algo(base_code, params, is_end)
        bt_name = f"REVAL-IS-{label.replace(' ', '')}-{pname}"
        stats = run_backtest(patched, bt_name)
        sc = score_backtest(stats)
        is_results[pname] = {
            "score": sc,
            "net": parse_stat(stats, "Net Profit") if stats else None,
            "sharpe": parse_stat(stats, "Sharpe Ratio") if stats else None,
            "dd": parse_stat(stats, "Drawdown") if stats else None,
            "trades": int(parse_stat(stats, "Total Orders")) if stats else 0,
        }
        net_str = f"{parse_stat(stats, 'Net Profit'):.1f}%" if stats else "FAIL"
        log(f"    → Score={sc:.4f} | Net={net_str}")
        time.sleep(5)

    # Find best IS params
    ranked = sorted(is_results.items(), key=lambda x: x[1]["score"], reverse=True)
    best_name, best_data = ranked[0]
    log(f"\n  BEST IS: {best_name} (score={best_data['score']:.4f})")

    # ── OUT-OF-SAMPLE using BEST IS params ──
    log(f"\n── OUT-OF-SAMPLE: {oos_start} → {oos_end} with params '{best_name}' ──")
    best_params = next(p for p in grid if p["name"] == best_name)
    patched = patch_algo(base_code, best_params, oos_end)
    bt_name = f"REVAL-OOS-{label.replace(' ', '')}-{best_name}"
    oos_stats = run_backtest(patched, bt_name)
    oos_sc = score_backtest(oos_stats)

    oos_result = {
        "score": oos_sc,
        "net": parse_stat(oos_stats, "Net Profit") if oos_stats else None,
        "sharpe": parse_stat(oos_stats, "Sharpe Ratio") if oos_stats else None,
        "dd": parse_stat(oos_stats, "Drawdown") if oos_stats else None,
        "trades": int(parse_stat(oos_stats, "Total Orders")) if oos_stats else 0,
        "params_used": best_name,
    }
    log(f"  OOS score={oos_sc:.4f} | Net={oos_result['net']:.1f}%")

    # ── DRIFT ASSESSMENT (with regime context, rolling avg, stability, streaks) ──
    verdict, drift_detail, summary = assess_drift(is_results, oos_result, label, regime=regime)
    summary["historical_win_rate"] = hist_rate
    summary["oos_stats"] = oos_result
    log(f"\n  VERDICT: {verdict}")
    log(drift_detail)

    if summary.get("escalation") and summary["escalation"] != "NONE":
        log(f"  ESCALATION: {summary['escalation']} (streak: {summary.get('drift_streak', 0)})")

    # ── SAVE RESULTS ──
    output = {
        "label": label,
        "oos_start": str(oos_start),
        "oos_end": str(oos_end),
        "is_start": str(IS_START),
        "is_end": str(is_end),
        "regime": regime,
        "run_timestamp": datetime.now().isoformat(),
        "live_params": CURRENT_LIVE_PARAMS,
        "verdict": verdict,
        "summary": summary,
        "is_results": is_results,
        "oos_result": oos_result,
        "historical_win_rate": hist_rate,
        "historical_wins": hist_wins,
        "historical_total": hist_total,
        "rolling_4q_avg": summary.get("rolling_4q_avg"),
        "winner_stability": summary.get("winner_stability"),
        "drift_streak": summary.get("drift_streak"),
        "escalation": summary.get("escalation"),
        "regime_softened": summary.get("regime_softened"),
    }
    with open(out_file, "w") as f:
        json.dump(output, f, indent=2, default=str)
    log(f"\nResults saved: {out_file}")

    # ── SEND TELEGRAM ──
    msg = build_telegram_msg(label, oos_start, oos_end, verdict, drift_detail, summary, regime)
    try:
        telegram.send(msg)
        log("Telegram report sent.")
    except Exception as e:
        log(f"Telegram report failed: {e}", "ERROR")

    return output


# ═══════════════════════════════════════════════════════════════
# REPORT MODE (print last saved results)
# ═══════════════════════════════════════════════════════════════

def print_last_report():
    """Find and print the most recent re-validation result."""
    import glob
    files = sorted(glob.glob(os.path.join(DATA_DIR, "oos_revalidation_*.json")), reverse=True)
    if not files:
        log("No re-validation results found.", "WARN")
        return
    with open(files[0]) as f:
        data = json.load(f)

    print(f"\n{'='*60}")
    print(f"Re-Validation Report: {data.get('label', '?')}")
    print(f"Run at: {data.get('run_timestamp', '?')[:19]}")
    print(f"Regime: {data.get('regime', '?')}")
    print(f"{'='*60}")
    print(f"Verdict: {data.get('verdict', '?')}")
    summary = data.get("summary", {})
    print(f"Live params rank: #{summary.get('live_rank', '?')}/27")
    print(f"Relative score: {summary.get('relative_score', 0):.1%} of winner")
    print(f"WFE ratio: {summary.get('wfe_ratio', 0):.2f}")
    print(f"\nTop 5 IS Rankings:")
    for i, (n, s) in enumerate(summary.get("top5", [])):
        marker = " ← LIVE" if n == CURRENT_LIVE_PARAMS else ""
        print(f"  {i+1}. {n}: {s:.4f}{marker}")
    oos = data.get("oos_result", {})
    print(f"\nOOS Result: Net={oos.get('net', 0):+.1f}% | Sharpe={oos.get('sharpe', 0):.3f} | DD={oos.get('dd', 0):.1f}%")

    # Health diagnostics
    print(f"\n{'─'*40}")
    print(f"Health Diagnostics:")
    rolling = data.get("rolling_4q_avg") or summary.get("rolling_4q_avg")
    if rolling is not None:
        count = summary.get("rolling_4q_count", "?")
        print(f"  Rolling {count}Q OOS avg: {rolling:.4f}")

    ws = data.get("winner_stability") or summary.get("winner_stability", {})
    if ws:
        print(f"  Winner stability: {ws.get('message', 'N/A')}")

    streak = data.get("drift_streak", summary.get("drift_streak", 0))
    escalation = data.get("escalation", summary.get("escalation", "NONE"))
    print(f"  Drift streak: {streak} consecutive | Escalation: {escalation}")

    if data.get("regime_softened") or summary.get("regime_softened"):
        print(f"  Regime softening: ACTIVE (adverse regime dampened verdict)")

    print(f"{'='*60}")


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Rudy v2.8+ Quarterly OOS Re-Validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--quarter", type=str, default=None,
                        help="Quarter to validate, e.g. Q4 (default: auto-detect last completed)")
    parser.add_argument("--year", type=int, default=None,
                        help="Year for --quarter (default: auto-detect)")
    parser.add_argument("--report", action="store_true",
                        help="Print last saved re-validation report and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would run without executing backtests")
    args = parser.parse_args()

    if args.report:
        print_last_report()
        sys.exit(0)

    if args.quarter:
        year = args.year or date.today().year
        oos_start, oos_end, label = parse_quarter_arg(args.quarter, year)
    else:
        oos_start, oos_end, label = last_completed_quarter()

    log(f"Target: {label} ({oos_start} → {oos_end})")

    if oos_end >= date.today():
        log(f"ERROR: Quarter {label} has not yet completed (ends {oos_end}).", "ERROR")
        log("Use --quarter to specify a completed quarter, or wait until the quarter ends.", "ERROR")
        sys.exit(1)

    run_revalidation(oos_start, oos_end, label, dry_run=args.dry_run)
