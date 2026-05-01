"""Auditor Agent — Rudy v2.0 / Constitution v50.0
Validates live system state against Constitution rules.
Runs daily at 4:00 PM ET (after 3:45 eval) via LaunchAgent com.rudy.auditor.

Authorized Traders (Article XI):
  Trader1 — trader_v28.py        — MSTR LEAP Entry/Exit
  Trader2 — trader2_mstr_put.py  — MSTR $50 Put Jan28
  Trader3 — trader3_spy_put.py   — SPY $430 Put Jan27

Paper trading: PERMANENTLY DISABLED (feedback_no_paper_trading.md)
"""
import json
import os
import sys
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

# ── Load env ──
_env = os.path.expanduser("~/.agent_zero_env")
if os.path.exists(_env):
    with open(_env) as _f:
        for _ln in _f:
            _ln = _ln.strip()
            if "=" in _ln and not _ln.startswith("#"):
                k, v = _ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

import telegram

LOG_DIR   = os.path.expanduser("~/rudy/logs")
DATA_DIR  = os.path.expanduser("~/rudy/data")
LOG_FILE  = os.path.join(LOG_DIR, "auditor.log")
AUDIT_FILE = os.path.join(DATA_DIR, "audit_log.json")
BREAKER_STATE_FILE = os.path.join(DATA_DIR, "breaker_state.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


# ── Authorized trader registry (Article XI) ──
AUTHORIZED_TRADERS = {
    "trader1": {
        "script":    "trader_v28.py",
        "label":     "com.rudy.trader1",
        "state":     "trader_v28_state.json",
        "desc":      "MSTR LEAP Entry/Exit",
        "client_id": 28,
        "authority": "BUY + SELL MSTR stock",
    },
    "trader2": {
        "script":    "trader2_mstr_put.py",
        "label":     "com.rudy.trader2",
        "state":     "trader2_state.json",
        "desc":      "MSTR $50 Put Jan28",
        "client_id": 12,
        "authority": "CLOSE only (with Commander approval)",
    },
    "trader3": {
        "script":    "trader3_spy_put.py",
        "label":     "com.rudy.trader3",
        "state":     "trader3_state.json",
        "desc":      "SPY $430 Put Jan27",
        "client_id": 13,
        "authority": "CLOSE only (with Commander approval)",
    },
}

# Backward-compat alias for legacy tests (test_breaker_integration,
# test_breaker_mid_execution still reference auditor.SYSTEMS). The pre-v50.0
# auditor exposed a SYSTEMS dict (Systems 1-14) — it was renamed AUTHORIZED_TRADERS
# in the v50.0 rewrite. Tests only iterate keys / len, so the alias works.
SYSTEMS = AUTHORIZED_TRADERS

# ── Constitution v50.0 limits ──
RULES = {
    "daily_loss_cap_pct":     0.02,
    "max_consecutive_losses": 5,
    "mnav_kill_ratio":        0.75,
    "max_premium_ratio":      1.3,
    "green_weeks_required":   2,
    "risk_capital_pct":       0.25,
    "deploy_pct":             0.50,
}

DISABLED_SCRIPTS = [
    "trader1.py", "trader2.py", "trader3.py", "trader4.py",
    "trader5.py", "trader6.py", "trader7.py", "trader8.py",
    "trader9.py", "trader10.py", "trader11.py", "trader12.py",
    "trader_moonshot.py", "trader_v30.py",
]


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[Auditor {ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def _load(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def load_audit_log():
    if os.path.exists(AUDIT_FILE):
        try:
            with open(AUDIT_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def log_audit(entry):
    history = load_audit_log()
    history.append(entry)
    history = history[-500:]
    with open(AUDIT_FILE, "w") as f:
        json.dump(history, f, indent=2)


# ════════════════════════════════════════════════════════════
# BREAKER STATE
# ════════════════════════════════════════════════════════════

def _load_breaker():
    return _load(BREAKER_STATE_FILE) or {"global_halt": False, "systems": {}}


def _save_breaker(state):
    state["last_updated"] = datetime.now().isoformat()
    with open(BREAKER_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def is_breaker_active(system_id=None):
    state = _load_breaker()
    if state.get("global_halt"):
        return True, f"GLOBAL HALT: {state.get('halt_reason', 'Commander ordered halt')}"
    if system_id is None:
        return False, ""
    sys_state = state.get("systems", {}).get(str(system_id), {})
    if sys_state.get("breaker_active"):
        return True, f"System {system_id} breaker: {sys_state.get('reason', 'capital below threshold')}"
    return False, ""


def set_global_halt(reason="Commander ordered halt"):
    state = _load_breaker()
    state["global_halt"] = True
    state["halt_time"] = datetime.now().isoformat()
    state["halt_reason"] = reason
    _save_breaker(state)
    try:
        telegram.send(f"🔴 *GLOBAL HALT ACTIVATED*\nReason: {reason}\nAll new entries BLOCKED.")
    except Exception:
        pass
    return state


def clear_global_halt():
    state = _load_breaker()
    state["global_halt"] = False
    state["halt_time"] = None
    state["halt_reason"] = None
    _save_breaker(state)
    try:
        telegram.send("✅ *GLOBAL HALT CLEARED* — Normal operations resumed.")
    except Exception:
        pass
    return state


def set_system_breaker(system_id, reason="Capital below survival threshold"):
    state = _load_breaker()
    state.setdefault("systems", {})[str(system_id)] = {
        "breaker_active": True,
        "reason": reason,
        "triggered_at": datetime.now().isoformat(),
    }
    _save_breaker(state)
    return state


def clear_system_breaker(system_id):
    state = _load_breaker()
    state.get("systems", {}).pop(str(system_id), None)
    _save_breaker(state)
    return state


def get_breaker_status():
    state = _load_breaker()
    return {
        "global_halt":  state.get("global_halt", False),
        "halt_reason":  state.get("halt_reason"),
        "halt_time":    state.get("halt_time"),
        "last_updated": state.get("last_updated"),
        "systems":      state.get("systems", {}),
    }


# ════════════════════════════════════════════════════════════
# AUDIT CHECKS
# ════════════════════════════════════════════════════════════

def _check_daemon(script_fragment):
    try:
        r = subprocess.run(["pgrep", "-f", script_fragment],
                           capture_output=True, text=True, timeout=5)
        return r.returncode == 0, r.stdout.strip()
    except Exception:
        return False, None


def _check_launchctl(label):
    try:
        r = subprocess.run(["launchctl", "list", label],
                           capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _eval_staleness_hours(state):
    last_eval = state.get("last_eval", "")
    if not last_eval:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(last_eval)).total_seconds() / 3600
    except Exception:
        return None


def check_clone_prohibition():
    """Article XI — verify no unauthorized trader scripts are running."""
    violations = []
    for script in DISABLED_SCRIPTS:
        running, pid = _check_daemon(script)
        if running:
            violations.append(f"CLONE VIOLATION: {script} running (PID {pid}) — NOT authorized")
    return violations


def check_trader1(violations, warnings):
    t = AUTHORIZED_TRADERS["trader1"]
    state = _load(os.path.join(DATA_DIR, t["state"]))
    daemon_ok, pid = _check_daemon(t["script"])
    lctl_ok = _check_launchctl(t["label"])

    if not daemon_ok:
        violations.append(f"🔴 Trader1 ({t['script']}) is DOWN — entry will NOT fire")
    if not lctl_ok:
        violations.append(f"🔴 Trader1 LaunchAgent ({t['label']}) NOT registered")

    hours = _eval_staleness_hours(state)
    today = datetime.now().weekday()
    if hours is not None and today < 5 and hours > 28:
        violations.append(f"🔴 Trader1 last eval was {hours:.1f}h ago — missed scheduled eval")
    elif hours is None and daemon_ok:
        warnings.append("⚠️ Trader1 state has no last_eval timestamp")

    halted, reason = is_breaker_active("trader1")
    if halted:
        warnings.append(f"⚠️ Trader1 circuit breaker ACTIVE: {reason}")

    return {
        "daemon":           daemon_ok,
        "pid":              pid,
        "launchctl":        lctl_ok,
        "last_eval_hours":  round(hours, 1) if hours is not None else None,
        "armed":            state.get("is_armed", False),
        "dipped":           state.get("dipped_below_200w", False),
        "green_weeks":      state.get("green_week_count", 0),
        "in_position":      state.get("position_qty", 0) > 0,
        "position_qty":     state.get("position_qty", 0),
    }


def check_trader2(violations, warnings):
    t = AUTHORIZED_TRADERS["trader2"]
    state = _load(os.path.join(DATA_DIR, t["state"]))
    daemon_ok, pid = _check_daemon(t["script"])
    lctl_ok = _check_launchctl(t["label"])

    if not daemon_ok:
        violations.append(f"🔴 Trader2 ({t['script']}) is DOWN")
    if not lctl_ok:
        violations.append(f"🔴 Trader2 LaunchAgent NOT registered")

    expiry = state.get("expiry_date", "")
    if expiry:
        try:
            days = (datetime.strptime(expiry[:10], "%Y-%m-%d") - datetime.now()).days
            if days < 90:
                violations.append(f"🔴 Trader2 expiry URGENT: {days}d remaining — roll NOW")
            elif days < 180:
                warnings.append(f"⚠️ Trader2 expiry WARNING: {days}d remaining — plan roll")
        except Exception:
            pass

    return {
        "daemon":          daemon_ok,
        "pid":             pid,
        "launchctl":       lctl_ok,
        "position_active": state.get("activated", False),
        "expiry":          expiry,
    }


def check_trader3(violations, warnings):
    t = AUTHORIZED_TRADERS["trader3"]
    state = _load(os.path.join(DATA_DIR, t["state"]))
    daemon_ok, pid = _check_daemon(t["script"])
    lctl_ok = _check_launchctl(t["label"])

    if not daemon_ok:
        violations.append(f"🔴 Trader3 ({t['script']}) is DOWN")
    if not lctl_ok:
        violations.append(f"🔴 Trader3 LaunchAgent NOT registered")

    expiry = state.get("expiry_date", "")
    if expiry:
        try:
            days = (datetime.strptime(expiry[:10], "%Y-%m-%d") - datetime.now()).days
            if days < 90:
                violations.append(f"🔴 Trader3 expiry URGENT: {days}d remaining — roll NOW")
            elif days < 180:
                warnings.append(f"⚠️ Trader3 expiry WARNING: {days}d remaining — plan roll")
        except Exception:
            pass

    return {
        "daemon":          daemon_ok,
        "pid":             pid,
        "launchctl":       lctl_ok,
        "position_active": state.get("activated", False),
        "expiry":          expiry,
    }


def check_daily_loss_cap():
    violations = []
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:3001/api/account-live", timeout=5) as r:
            d = json.loads(r.read())
        nlv = d.get("net_liq", 0)
        open_nlv = d.get("open_nlv", 0)
        if nlv > 0 and open_nlv > 0:
            pnl_pct = (nlv - open_nlv) / open_nlv
            if pnl_pct < -RULES["daily_loss_cap_pct"]:
                violations.append(
                    f"🔴 DAILY LOSS CAP BREACHED: {pnl_pct*100:.2f}% "
                    f"(limit: -{RULES['daily_loss_cap_pct']*100:.0f}%)"
                )
    except Exception:
        pass
    return violations


# ════════════════════════════════════════════════════════════
# MAIN DAILY AUDIT
# ════════════════════════════════════════════════════════════

def run_daily_audit():
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log(f"Running daily audit — {ts}")

    violations = []
    warnings = []

    clone_viols = check_clone_prohibition()
    violations.extend(clone_viols)

    t1 = check_trader1(violations, warnings)
    log(f"Trader1: {'✅' if t1['daemon'] else '❌'} | armed={t1['armed']} | "
        f"dipped={t1['dipped']} | green_wks={t1['green_weeks']}")

    t2 = check_trader2(violations, warnings)
    log(f"Trader2: {'✅' if t2['daemon'] else '❌'} | active={t2['position_active']}")

    t3 = check_trader3(violations, warnings)
    log(f"Trader3: {'✅' if t3['daemon'] else '❌'} | active={t3['position_active']}")

    loss_viols = check_daily_loss_cap()
    violations.extend(loss_viols)

    halted, halt_reason = is_breaker_active()

    all_clear = len(violations) == 0
    entry = {
        "timestamp": ts,
        "type": "daily_audit",
        "approved": all_clear,
        "violations": violations,
        "warnings": warnings,
        "status": "CLEAN" if all_clear else "VIOLATIONS",
        "trader1": t1,
        "trader2": t2,
        "trader3": t3,
    }
    log_audit(entry)

    v_icon  = "✅" if all_clear else "🚨"
    v_label = "ALL CLEAR" if all_clear else f"{len(violations)} VIOLATION(s)"

    msg = (
        f"{v_icon} *Auditor Daily Report — {datetime.now().strftime('%b %d')}*\n"
        f"Constitution v50.0 | *{v_label}*\n\n"
        f"*Authorized Traders*\n"
        f"{'✅' if t1['daemon'] else '❌'} Trader1 (v2.8+) — "
        f"{'Armed' if t1['armed'] else 'Dipped/Waiting' if t1['dipped'] else 'Monitoring'} | "
        f"Green wks: {t1['green_weeks']}/2 | "
        f"Last eval: {str(t1['last_eval_hours'])+'h ago' if t1['last_eval_hours'] else 'unknown'}\n"
        f"{'✅' if t2['daemon'] else '❌'} Trader2 (MSTR $50P) — "
        f"{'Active' if t2['position_active'] else 'Monitoring'}\n"
        f"{'✅' if t3['daemon'] else '❌'} Trader3 (SPY $430P) — "
        f"{'Active' if t3['position_active'] else 'Monitoring'}\n"
        f"🔒 Clone Check: {'✅ CLEAN' if not clone_viols else '🚨 '+str(len(clone_viols))+' VIOLATION(S)'}\n"
        f"⚡ Circuit Breaker: {'🔴 HALTED' if halted else '✅ CLEAR'}\n"
    )

    if violations:
        msg += "\n*🚨 Violations*\n" + "\n".join(violations)
    if warnings:
        msg += "\n*⚠️ Warnings*\n" + "\n".join(warnings)

    try:
        telegram.send(msg)
        log("Telegram sent ✅")
    except Exception as e:
        log(f"Telegram failed: {e}")

    log(f"Audit complete: {len(violations)} violations, {len(warnings)} warnings")
    return all_clear, violations, warnings


# ════════════════════════════════════════════════════════════
# DASHBOARD INTERFACE (called by app.py)
# ════════════════════════════════════════════════════════════

def get_summary():
    history = load_audit_log()
    if not history:
        return {
            "total_audits": 0, "approved": 0, "rejected": 0,
            "last_audit": None, "recent_violations": [], "status": "clean",
        }
    daily = [e for e in history if e.get("type") == "daily_audit"]
    approved = sum(1 for e in daily if e.get("approved"))
    rejected  = len(daily) - approved
    last = daily[-1] if daily else history[-1]

    recent_violations = []
    for entry in reversed((daily or history)[-20:]):
        for v in entry.get("violations", []):
            recent_violations.append({"time": entry["timestamp"], "violation": v})

    return {
        "total_audits":       len(daily),
        "approved":           approved,
        "rejected":           rejected,
        "last_audit":         last.get("timestamp"),
        "recent_violations":  recent_violations[:5],
        "status":             "clean" if not recent_violations else "violations",
    }


def check_paper_test():
    """Paper trading permanently disabled — always returns passed."""
    return {
        "passed":    True,
        "score":     "N/A",
        "timestamp": "DISABLED",
        "note":      "Paper trading permanently disabled (feedback_no_paper_trading.md)",
    }


def audit_trade(trade):
    """Audit a trade proposal against Constitution v50.0."""
    violations = []
    warnings   = []
    script = trade.get("script", "")

    authorized_scripts = [t["script"] for t in AUTHORIZED_TRADERS.values()]
    if script and script not in authorized_scripts:
        violations.append(f"UNAUTHORIZED: {script} is not an authorized trader (Article XI)")

    halted, reason = is_breaker_active()
    if halted:
        violations.append(f"BLOCKED: Global halt — {reason}")

    approved = len(violations) == 0
    log_audit({
        "timestamp": datetime.now().isoformat(),
        "type": "trade_audit",
        "trade": trade,
        "approved": approved,
        "violations": violations,
        "warnings": warnings,
    })
    return approved, violations, warnings


if __name__ == "__main__":
    all_clear, violations, warnings = run_daily_audit()
    sys.exit(0 if all_clear else 1)
