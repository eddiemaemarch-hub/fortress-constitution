"""Execution Path Audit — Rudy v2.0 / trader_v28.py
Runs twice daily (9:00 AM + 3:00 PM ET, Mon-Fri) from LaunchAgent.
Audits every component from signal detection to IBKR order submission.
Sends full Telegram report. Constitution v50.0.
"""
import os
import sys
import json
import subprocess
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

# ── Load env ──
_env = os.path.expanduser("~/.agent_zero_env")
if os.path.exists(_env):
    for _ln in open(_env):
        _ln = _ln.strip()
        if "=" in _ln and not _ln.startswith("#"):
            k, v = _ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import telegram

DATA_DIR  = os.path.expanduser("~/rudy/data")
LOG_DIR   = os.path.expanduser("~/rudy/logs")
LOG_FILE  = os.path.join(LOG_DIR, "execution_audit.log")
os.makedirs(LOG_DIR, exist_ok=True)

TRADER_V28_STATE  = os.path.join(DATA_DIR, "trader_v28_state.json")
BREAKER_STATE     = os.path.join(DATA_DIR, "breaker_state.json")
REGIME_STATE      = os.path.join(DATA_DIR, "regime_state.json")
SENTINEL_STATE    = os.path.join(DATA_DIR, "btc_sentinel_state.json")


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def _load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


# ════════════════════════════════════════════════════════════
# CHECK 1 — Daemon alive (process running)
# ════════════════════════════════════════════════════════════
def check_daemon():
    try:
        r = subprocess.run(["pgrep", "-f", "trader_v28.py"],
                           capture_output=True, text=True, timeout=5)
        running = r.returncode == 0
        pid = r.stdout.strip() if running else None
        return running, pid
    except Exception as e:
        return False, None


# ════════════════════════════════════════════════════════════
# CHECK 2 — Last eval staleness
# ════════════════════════════════════════════════════════════
def check_eval_staleness(state):
    last_eval = state.get("last_eval", "")
    if not last_eval:
        return None, "NEVER EVALUATED"
    try:
        last_dt = datetime.fromisoformat(last_eval)
        hours_ago = (datetime.now() - last_dt).total_seconds() / 3600
        return hours_ago, last_eval[:16].replace("T", " ")
    except Exception:
        return None, "PARSE ERROR"


# ════════════════════════════════════════════════════════════
# CHECK 3 — IBKR connection (lightweight ping via ib_insync)
# ════════════════════════════════════════════════════════════
def check_ibkr():
    try:
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
        import asyncio

        def _connect():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            from ib_insync import IB
            ib = IB()
            ib.connect("127.0.0.1", 7496, clientId=91, timeout=8, readonly=True)
            accounts = ib.managedAccounts()
            ib.disconnect()
            return accounts

        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_connect)
            try:
                accts = fut.result(timeout=15)
                return True, accts[0] if accts else "UNKNOWN"
            except FutureTimeout:
                return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)[:60]


# ════════════════════════════════════════════════════════════
# CHECK 4 — Filter status from state
# ════════════════════════════════════════════════════════════
def check_filters(state):
    filters = state.get("filters") or {}
    armed       = state.get("is_armed", False)
    stoch_rsi   = state.get("last_stoch_rsi", filters.get("stoch_rsi"))
    green_weeks = state.get("green_week_count", 0)
    dipped      = state.get("dipped_below_200w", False)
    in_position = state.get("position_qty", 0) > 0

    # premium: last_premium in state, fallback premium_history last entry
    premium = state.get("last_premium") or None
    if not premium:
        hist = state.get("premium_history", [])
        premium = hist[-1] if hist else None

    # BTC above 200W: derive from sentinel state (most reliable source)
    sentinel = _load(SENTINEL_STATE)
    btc_above_200w = sentinel.get("btc_was_above_200w")
    if btc_above_200w is None:
        btc_above_200w = filters.get("btc_above_200w")

    return {
        "armed": armed,
        "btc_above_200w": btc_above_200w,
        "stoch_rsi": stoch_rsi,
        "premium": premium,
        "green_weeks": green_weeks,
        "dipped": dipped,
        "in_position": in_position,
    }


# ════════════════════════════════════════════════════════════
# CHECK 5 — Capital adequacy (NLV from state)
# ════════════════════════════════════════════════════════════
def check_capital(state):
    # Primary: dashboard /api/account-live (IBKR background feed in memory)
    import urllib.request
    nlv = 0.0
    source = "unknown"
    try:
        with urllib.request.urlopen("http://localhost:3001/api/account-live", timeout=5) as resp:
            d = json.loads(resp.read())
            v = d.get("net_liq") or d.get("netliq")
            if v and float(v) > 0:
                nlv = float(v)
                source = "dashboard-api"
    except Exception:
        pass
    if not nlv:
        nlv = state.get("nlv_at_last_eval", 0.0)
        source = "state"
    risk_cap  = nlv * 0.25
    deploy    = risk_cap * 0.50
    mstr_est  = state.get("last_mstr_price", 150.0) or 150.0
    qty_est   = int(deploy / mstr_est) if mstr_est > 0 else 0
    return {
        "nlv": nlv,
        "risk_capital": risk_cap,
        "deploy": deploy,
        "qty_estimate": qty_est,
        "mstr_price": mstr_est,
        "source": source,
    }


# ════════════════════════════════════════════════════════════
# CHECK 6 — Circuit breaker status
# ════════════════════════════════════════════════════════════
def check_breaker():
    b = _load(BREAKER_STATE)
    return b.get("global_halt", False), b.get("halt_reason", None)


# ════════════════════════════════════════════════════════════
# CHECK 7 — Critical file freshness
# ════════════════════════════════════════════════════════════
def check_files():
    files = {
        "trader_v28_state.json": TRADER_V28_STATE,
        "breaker_state.json":    BREAKER_STATE,
        "regime_state.json":     REGIME_STATE,
        "btc_sentinel.json":     SENTINEL_STATE,
    }
    results = {}
    for name, path in files.items():
        if not os.path.exists(path):
            results[name] = "MISSING"
        else:
            age_min = (time.time() - os.path.getmtime(path)) / 60
            results[name] = f"{age_min:.0f}m ago"
    return results


# ════════════════════════════════════════════════════════════
# CHECK 8 — Schedule integrity (is 15:45 still registered?)
# ════════════════════════════════════════════════════════════
def check_schedule_registered():
    """Check launchctl to confirm trader1 LaunchAgent is loaded."""
    try:
        r = subprocess.run(["launchctl", "list", "com.rudy.trader1"],
                           capture_output=True, text=True, timeout=5)
        return r.returncode == 0, r.stdout.strip()[:80]
    except Exception as e:
        return False, str(e)


# ════════════════════════════════════════════════════════════
# MAIN — run all checks, build Telegram report
# ════════════════════════════════════════════════════════════
def run_audit():
    now = datetime.now()
    is_weekday = now.weekday() < 5  # Mon=0 … Fri=4
    hour = now.hour

    log("=" * 60)
    log(f"EXECUTION PATH AUDIT — {now.strftime('%Y-%m-%d %H:%M')}")
    log("=" * 60)

    state = _load(TRADER_V28_STATE)
    issues = []
    warnings = []

    # ── 1. Daemon ──
    daemon_ok, pid = check_daemon()
    log(f"[1] Daemon: {'RUNNING (PID '+str(pid)+')' if daemon_ok else 'DOWN'}")
    if not daemon_ok:
        issues.append("🔴 trader_v28.py is NOT running")

    # ── 2. Eval staleness ──
    hours_ago, eval_ts = check_eval_staleness(state)
    log(f"[2] Last eval: {eval_ts} ({f'{hours_ago:.1f}h ago' if hours_ago is not None else 'unknown'})")
    if hours_ago is not None:
        # > 28h on a weekday = problem (normal max gap is Fri 15:45 → Mon 15:45 = 72h)
        if is_weekday and hours_ago > 28:
            issues.append(f"🔴 Last eval was {hours_ago:.1f}h ago — missed scheduled eval")
        elif hours_ago > 80:
            issues.append(f"🔴 Last eval was {hours_ago:.1f}h ago — stale over weekend")
    elif is_weekday:
        issues.append("🔴 Cannot determine last eval time")

    # ── 3. IBKR connection ──
    log("[3] Checking IBKR connection (clientId=91, readonly)...")
    ibkr_ok, ibkr_detail = check_ibkr()
    log(f"    IBKR: {'✅ '+str(ibkr_detail) if ibkr_ok else '❌ '+str(ibkr_detail)}")
    if not ibkr_ok:
        issues.append(f"🔴 IBKR TWS unreachable: {ibkr_detail}")

    # ── 4. Filters ──
    f = check_filters(state)
    log(f"[4] Filters: Armed={f['armed']} | BTC200W={f['btc_above_200w']} | "
        f"StRSI={f['stoch_rsi']} | Prem={f['premium']} | "
        f"GreenWks={f['green_weeks']}/2 | Dipped={f['dipped']}")

    # ── 5. Capital ──
    cap = check_capital(state)
    log(f"[5] Capital: NLV=${cap['nlv']:,.0f} | Deploy=${cap['deploy']:,.0f} | "
        f"~{cap['qty_estimate']} shares @ ${cap['mstr_price']:.2f} (source: {cap['source']})")
    if cap["qty_estimate"] <= 0 and is_weekday:
        issues.append(f"🔴 CAPITAL CRITICAL: qty_estimate=0 — entry would abort silently")
    elif cap["qty_estimate"] < 5 and is_weekday:
        warnings.append(f"⚠️ Low capital: only ~{cap['qty_estimate']} shares could be purchased")

    # ── 6. Circuit breaker ──
    halted, halt_reason = check_breaker()
    log(f"[6] Circuit breaker: {'HALTED — '+str(halt_reason) if halted else 'CLEAR'}")
    if halted:
        issues.append(f"🔴 CIRCUIT BREAKER ACTIVE: {halt_reason}")

    # ── 7. File freshness ──
    files = check_files()
    for fname, age in files.items():
        log(f"[7] {fname}: {age}")
        if age == "MISSING":
            issues.append(f"🔴 MISSING file: {fname}")

    # ── 8. LaunchAgent ──
    sched_ok, sched_detail = check_schedule_registered()
    log(f"[8] LaunchAgent: {'✅ registered' if sched_ok else '❌ NOT registered'}")
    if not sched_ok:
        issues.append("🔴 com.rudy.trader1 LaunchAgent NOT loaded — 15:45 eval will not fire")

    # ── Build Telegram report ──
    all_clear = len(issues) == 0

    status_icon = "✅" if all_clear else "🚨"
    status_line = "ALL SYSTEMS GO" if all_clear else f"{len(issues)} ISSUE(s) DETECTED"

    slot = "09:00 AM" if hour < 12 else "03:00 PM"
    header = (
        f"{status_icon} *Execution Path Audit — {slot}*\n"
        f"{now.strftime('%A %b %d, %Y')}\n"
        f"Status: *{status_line}*\n"
    )

    # Trader status block
    phase = "DIPPED — WAITING RECLAIM" if f["dipped"] and not f["armed"] else \
            "ARMED — WAITING ENTRY" if f["armed"] else \
            "IN POSITION" if f["in_position"] else "MONITORING"

    status_block = (
        f"\n*Trader1 State*\n"
        f"• Phase: {phase}\n"
        f"• Daemon: {'✅ PID ' + str(pid) if daemon_ok else '❌ DOWN'}\n"
        f"• IBKR: {'✅ ' + str(ibkr_detail) if ibkr_ok else '❌ ' + str(ibkr_detail)}\n"
        f"• Last Eval: {eval_ts} ({f'{hours_ago:.1f}h ago' if hours_ago else 'unknown'})\n"
        f"• Next Eval: 15:45 ET (scheduled)\n"
    )

    filter_block = (
        f"\n*Filter Checklist*\n"
        f"{'✅' if f['dipped'] else '⬜'} Dipped below 200W SMA\n"
        f"{'✅' if f['green_weeks'] >= 2 else '⬜'} Green weeks: {f['green_weeks']}/2\n"
        f"{'✅' if f['armed'] else '⬜'} Armed\n"
        f"{'✅' if f['btc_above_200w'] else '⬜'} BTC above 200W\n"
        f"{'✅' if (f['stoch_rsi'] is not None and f['stoch_rsi'] < 70) else '⬜'} StochRSI < 70 "
        f"(now: {f['stoch_rsi']})\n"
        f"{'✅' if (f['premium'] is not None and f['premium'] <= 1.3) else '⬜'} Premium ≤ 1.3x "
        f"(now: {round(f['premium'], 2) if f['premium'] else '—'})\n"
        f"{'⬜' if not f['in_position'] else '🎯'} In position: "
        f"{'YES' if f['in_position'] else 'No'}\n"
    )

    capital_block = (
        f"\n*Capital Readiness*\n"
        f"• NLV: ${cap['nlv']:,.0f}\n"
        f"• Risk (25%): ${cap['risk_capital']:,.0f}\n"
        f"• Deploy (50%): ${cap['deploy']:,.0f}\n"
        f"• Est. shares: ~{cap['qty_estimate']} @ ${cap['mstr_price']:.2f}\n"
        f"• {'✅ Ready' if cap['qty_estimate'] > 0 else '🚨 ZERO SHARES — entry would abort'}\n"
    )

    issue_block = ""
    if issues:
        issue_block = "\n*🚨 ISSUES — Action Required*\n" + "\n".join(issues) + "\n"
    if warnings:
        issue_block += "\n*⚠️ Warnings*\n" + "\n".join(warnings) + "\n"

    breaker_block = f"\n*Circuit Breaker*: {'🔴 HALTED — ' + str(halt_reason) if halted else '✅ CLEAR'}\n"

    message = header + status_block + filter_block + capital_block + breaker_block + issue_block

    log(f"Sending Telegram audit report ({len(issues)} issues, {len(warnings)} warnings)")
    try:
        telegram.send(message)
        log("Telegram sent ✅")
    except Exception as e:
        log(f"Telegram send failed: {e}")

    log("=" * 60)
    return all_clear, issues


if __name__ == "__main__":
    all_clear, issues = run_audit()
    sys.exit(0 if all_clear else 1)
