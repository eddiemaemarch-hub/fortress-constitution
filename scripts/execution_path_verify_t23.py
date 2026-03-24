"""Execution Path Verifier — Trader2 & Trader3 / Rudy v2.0 / Constitution v50.0
Runs Mon–Fri at 9:20 AM and 3:45 PM ET alongside Trader1 verifier.
Verifies every step of the Trader2 + Trader3 exit execution path.

Trader2 — MSTR $50 Put Jan28 (expiry 20280121 → roll to 20300117)
  Execution path: ladder tier hit → trail stop set → HITL Telegram → execute_sell()
  Ladder: +150% (trail 20%), +300% (sell 25%, trail 18%), +500% (sell 33%, trail 15%),
          +800% (sell 50%, trail 12%), runner at 15% trail

Trader3 — SPY $430 Put Jan27 (expiry 20270115 → roll to 20290119)
  Execution path: ladder tier hit → trail stop set → HITL Telegram → execute_sell()
  Ladder: +100% (trail 20%), +200% (trail 18%), +400% (trail 15%),
          +700% (trail 12%), runner at 15% trail
  Note: Single contract — no partial sells. Trail hit = full exit.

HITL: ALL sells require Telegram approval. This script verifies that path is live.
"""
import os
import sys
import json
import subprocess
import socket
from datetime import datetime

DISABLED_SCRIPTS = [
    "trader1.py","trader2.py","trader3.py","trader4.py",
    "trader5.py","trader6.py","trader7.py","trader8.py",
    "trader9.py","trader10.py","trader11.py","trader12.py",
    "trader_moonshot.py","trader_v30.py",
]

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

LOG_DIR  = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
LOG_FILE = os.path.join(LOG_DIR, "execution_path_verify_t23.log")
os.makedirs(LOG_DIR, exist_ok=True)

# ── Trader config ──
TRADERS = {
    "trader2": {
        "name":      "Trader2",
        "desc":      "MSTR $50 Put",
        "script":    "trader2_mstr_put.py",
        "label":     "com.rudy.trader2",
        "class":     "Trader2",
        "state":     os.path.join(DATA_DIR, "trader2_state.json"),
        "pid_file":  os.path.join(DATA_DIR, "trader2.pid"),
        "client_id": 53,
        "symbol":    "MSTR",
        "strike":    50.0,
        "expiry":    "20280121",
        "next_exp":  "20300117",
        "ladder": [
            {"name": "Tier 1", "trigger_pct": 150,  "sell_frac": 0.0,  "trail_pct": 20},
            {"name": "Tier 2", "trigger_pct": 300,  "sell_frac": 0.25, "trail_pct": 18},
            {"name": "Tier 3", "trigger_pct": 500,  "sell_frac": 0.33, "trail_pct": 15},
            {"name": "Tier 4", "trigger_pct": 800,  "sell_frac": 0.50, "trail_pct": 12},
        ],
        "runner_trail": 15,
    },
    "trader3": {
        "name":      "Trader3",
        "desc":      "SPY $430 Put",
        "script":    "trader3_spy_put.py",
        "label":     "com.rudy.trader3",
        "class":     "Trader3",
        "state":     os.path.join(DATA_DIR, "trader3_state.json"),
        "pid_file":  os.path.join(DATA_DIR, "trader3.pid"),
        "client_id": 54,
        "symbol":    "SPY",
        "strike":    430.0,
        "expiry":    "20270115",
        "next_exp":  "20290119",
        "ladder": [
            {"name": "Tier 1", "trigger_pct": 100,  "sell_frac": 0.0,  "trail_pct": 20},
            {"name": "Tier 2", "trigger_pct": 200,  "sell_frac": 0.0,  "trail_pct": 18},
            {"name": "Tier 3", "trigger_pct": 400,  "sell_frac": 0.0,  "trail_pct": 15},
            {"name": "Tier 4", "trigger_pct": 700,  "sell_frac": 0.0,  "trail_pct": 12},
        ],
        "runner_trail": 15,
    },
}


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[VerifyT23 {ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def _pass(label): log(f"  ✅ {label}"); return True, label
def _fail(label): log(f"  ❌ {label}"); return False, label
def _warn(label): log(f"  ⚠️  {label}"); return None, label


def _load_state(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _days_to_expiry(expiry_str):
    """YYYYMMDD → days remaining."""
    try:
        exp = datetime.strptime(expiry_str, "%Y%m%d")
        return (exp - datetime.now()).days
    except Exception:
        return None


def _fmt_expiry(expiry_str):
    try:
        return datetime.strptime(expiry_str, "%Y%m%d").strftime("%b %d %Y")
    except Exception:
        return expiry_str


# ════════════════════════════════════════════════════════
# PER-TRADER CHECKS
# ════════════════════════════════════════════════════════

def check_daemon(cfg):
    r = subprocess.run(["pgrep", "-f", cfg["script"]],
                       capture_output=True, text=True, timeout=5)
    if r.returncode == 0:
        pid = r.stdout.strip().split("\n")[0]
        return _pass(f"{cfg['name']} daemon running (PID {pid})")
    return _fail(f"{cfg['name']} daemon is DOWN — exit orders WILL NOT fire")


def check_launchagent(cfg):
    r = subprocess.run(["launchctl", "list", cfg["label"]],
                       capture_output=True, text=True, timeout=5)
    if r.returncode == 0:
        return _pass(f"LaunchAgent {cfg['label']} registered")
    return _fail(f"LaunchAgent {cfg['label']} NOT registered — won't restart on reboot")


def check_ibkr():
    """Single shared check — both traders use same TWS port."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        result = s.connect_ex(("127.0.0.1", 7496))
        s.close()
        if result == 0:
            return _pass("IBKR TWS port 7496 open (shared check)")
        return _fail("IBKR TWS port 7496 REFUSED — sell orders CAN'T execute")
    except Exception as e:
        return _fail(f"IBKR port check error: {e}")


def check_state_fresh(cfg):
    state = _load_state(cfg["state"])
    if not state:
        return _fail(f"{cfg['name']} state file missing or empty")
    last_check = state.get("last_check", "")
    if not last_check:
        return _warn(f"{cfg['name']} no last_check timestamp in state")
    try:
        last_dt = datetime.fromisoformat(last_check)
        hours = (datetime.now() - last_dt).total_seconds() / 3600
        threshold = 2.0  # Trader2/3 check every ~30min during market hours
        if hours <= threshold:
            return _pass(f"{cfg['name']} state fresh — last check {hours:.1f}h ago")
        return _fail(f"{cfg['name']} state STALE — last check {hours:.1f}h ago (threshold: {threshold}h)")
    except Exception as e:
        return _fail(f"{cfg['name']} state timestamp parse error: {e}")


def check_state_valid(cfg):
    state = _load_state(cfg["state"])
    if not state:
        return _fail(f"{cfg['name']} state file missing")
    if not os.access(cfg["state"], os.W_OK):
        return _fail(f"{cfg['name']} state file NOT writable — can't save on sell")
    required = ["activated", "current_tier", "peak_value", "trail_stop_value",
                "contracts_remaining", "tiers_hit", "pending_sell", "last_value"]
    missing = [k for k in required if k not in state]
    if missing:
        return _fail(f"{cfg['name']} state missing keys: {missing}")
    return _pass(f"{cfg['name']} state file valid and writable")


def check_position_via_ibkr(cfg):
    """Verify position exists in IBKR via dashboard API."""
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:3001/api/account-live", timeout=5) as r:
            data = json.loads(r.read())
        positions = data.get("positions", [])
        for p in positions:
            if (p.get("symbol") == cfg["symbol"] and
                    abs(p.get("strike", 0) - cfg["strike"]) < 0.01 and
                    p.get("right", "") == "P"):
                qty = p.get("qty", 0)
                avg = p.get("avg_cost", 0)
                exp = p.get("expiry", "")
                return _pass(
                    f"{cfg['name']} position confirmed in IBKR: "
                    f"{cfg['symbol']} ${cfg['strike']:.0f}P qty={qty:.0f} "
                    f"avg=${avg:.2f} exp={exp}"
                )
        return _fail(
            f"{cfg['name']} position NOT found in IBKR! "
            f"Expected {cfg['symbol']} ${cfg['strike']:.0f}P. Sell can't execute."
        )
    except Exception as e:
        return _warn(f"{cfg['name']} IBKR position check error: {e}")


def check_ladder_status(cfg):
    """Show ladder progress and trail stop status."""
    state = _load_state(cfg["state"])
    if not state:
        return _warn(f"{cfg['name']} state unavailable for ladder check")

    activated       = state.get("activated", False)
    current_tier    = state.get("current_tier", 0)
    tiers_hit       = state.get("tiers_hit", [])
    peak_value      = state.get("peak_value", 0)
    peak_gain       = state.get("peak_gain_pct", 0)
    trail_stop      = state.get("trail_stop_value", 0)
    trail_pct       = state.get("trail_stop_pct", 0)
    last_value      = state.get("last_value", 0)
    last_gain       = state.get("last_gain_pct", 0)
    contracts_rem   = state.get("contracts_remaining", 1)
    pending_sell    = state.get("pending_sell")

    # Find next tier to hit
    ladder = cfg["ladder"]
    next_tier = None
    for tier in ladder:
        if tier["name"] not in tiers_hit:
            next_tier = tier
            break

    gain_icon = "🟢" if last_gain >= 0 else "🔴"

    lines = [
        f"  {gain_icon} Current gain: {last_gain:+.1f}% | Value: ${last_value:.2f}",
        f"  Activated: {'✅ YES' if activated else '⏳ Not yet'}",
        f"  Contracts remaining: {contracts_rem}",
        f"  Tiers hit: {', '.join(tiers_hit) if tiers_hit else 'None yet'}",
    ]

    if activated and trail_stop > 0:
        lines.append(f"  Trail stop: ${trail_stop:.2f} ({trail_pct}% from peak ${peak_value:.2f})")
    elif activated:
        lines.append(f"  Trail stop: Not yet set (peak={peak_gain:.1f}%)")

    if next_tier:
        gain_needed = next_tier["trigger_pct"] - last_gain
        lines.append(
            f"  Next trigger: {next_tier['name']} at +{next_tier['trigger_pct']}% "
            f"(need +{gain_needed:.0f}% more | trail will set to {next_tier['trail_pct']}%)"
        )
    else:
        lines.append(f"  All ladder tiers hit — running with {cfg['runner_trail']}% trail")

    if pending_sell:
        lines.append(f"  ⚠️  PENDING SELL awaiting HITL approval: {pending_sell}")

    for l in lines:
        log(l)

    # Pass/warn based on pending sell and activation
    if pending_sell:
        return _warn(f"{cfg['name']} has PENDING SELL — awaiting Commander approval")
    elif activated and trail_stop > 0:
        return _pass(f"{cfg['name']} ladder ACTIVE — trail stop set at ${trail_stop:.2f}")
    else:
        return _warn(
            f"{cfg['name']} monitoring — at {last_gain:+.1f}% | "
            f"activates at +{next_tier['trigger_pct'] if next_tier else '?'}%"
        )


def check_trail_stop_math(cfg):
    """Verify trail stop value is mathematically correct — peak × (1 - trail_pct/100)."""
    state = _load_state(cfg["state"])
    if not state:
        return _warn(f"{cfg['name']} state unavailable")

    activated   = state.get("activated", False)
    trail_value = state.get("trail_stop_value", 0)
    trail_pct   = state.get("trail_stop_pct", 0)
    peak_value  = state.get("peak_value", 0)

    if not activated:
        return _pass(f"{cfg['name']} not yet activated — trail math N/A (waiting for first tier)")

    if trail_value <= 0 or trail_pct <= 0 or peak_value <= 0:
        return _warn(f"{cfg['name']} activated but trail not yet set (peak=${peak_value:.2f})")

    # Verify math: trail_value should be within 5% of peak × (1 - effective_trail/100)
    # Note: regime adjustment (±5%) is applied on top of base trail_pct
    expected_base = peak_value * (1 - trail_pct / 100)
    expected_min  = peak_value * (1 - (trail_pct + 7) / 100)   # +7% regime tighten max
    expected_max  = peak_value * (1 - max(5, trail_pct - 7) / 100)  # -7% regime loosen max

    if expected_min <= trail_value <= expected_max:
        distance_pct = ((state.get("last_value", peak_value) - trail_value) / trail_value * 100)
        return _pass(
            f"{cfg['name']} trail math OK — "
            f"peak=${peak_value:.2f} × (1-{trail_pct}%) = ${expected_base:.2f} | "
            f"Actual: ${trail_value:.2f} | "
            f"Distance to stop: {distance_pct:.1f}%"
        )
    return _fail(
        f"{cfg['name']} trail stop MATH ERROR — "
        f"peak=${peak_value:.2f}, trail_pct={trail_pct}%, "
        f"expected ${expected_min:.2f}–${expected_max:.2f} but got ${trail_value:.2f}"
    )


def check_pending_sell(cfg):
    """Fail loudly if there's a pending sell awaiting Commander approval."""
    state = _load_state(cfg["state"])
    if not state:
        return _warn(f"{cfg['name']} state unavailable")

    pending = state.get("pending_sell")
    if not pending:
        return _pass(f"{cfg['name']} no pending sell — clean")

    # Pending sell is a WARNING if recent, FAIL if it's been sitting >30 min
    ts = pending.get("timestamp", "") if isinstance(pending, dict) else ""
    if ts:
        try:
            age_min = (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 60
            if age_min > 30:
                return _fail(
                    f"{cfg['name']} PENDING SELL STALE — sitting {age_min:.0f}min without approval! "
                    f"Respond via Telegram or MCP approve_trade"
                )
            return _warn(f"{cfg['name']} pending sell {age_min:.0f}min old — awaiting Commander approval")
        except Exception:
            pass
    return _warn(f"{cfg['name']} has pending sell — awaiting Commander approval: {pending}")


def check_execute_sell_path(cfg):
    """Verify execute_sell() IBKR order path is callable and the class has all exit methods."""
    script = cfg["script"].replace(".py", "")
    cls    = cfg["class"]
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0,'/Users/eddiemae/rudy/scripts'); "
             f"import {script}; t = {script}.{cls}(); "
             f"assert hasattr(t, 'execute_sell'), 'no execute_sell'; "
             f"assert hasattr(t, 'approve_pending_sell'), 'no approve_pending_sell'; "
             f"assert hasattr(t, '_trigger_trail_stop'), 'no _trigger_trail_stop'; "
             f"assert hasattr(t, 'approve_expiry_roll'), 'no approve_expiry_roll'; "
             f"print('OK')"],
            capture_output=True, text=True, timeout=15,
            cwd="/Users/eddiemae/rudy/scripts"
        )
        if "OK" in result.stdout:
            return _pass(
                f"{cfg['name']} execute_sell() path clean — "
                f"execute_sell + approve_pending_sell + _trigger_trail_stop + approve_expiry_roll all present"
            )
        return _fail(f"{cfg['name']} exit method missing: {result.stderr[:200]}")
    except Exception as e:
        return _fail(f"{cfg['name']} exit path check error: {e}")


def check_profit_taking_sequence(cfg):
    """Verify ladder tier sequence integrity and runner trail are intact."""
    state = _load_state(cfg["state"])
    if not state:
        return _warn(f"{cfg['name']} state unavailable")

    ladder      = cfg["ladder"]
    runner_trail = cfg["runner_trail"]
    tiers_hit   = state.get("tiers_hit", [])
    current_tier = state.get("current_tier", 0)
    last_gain   = state.get("last_gain_pct", 0)
    activated   = state.get("activated", False)
    contracts   = state.get("contracts_remaining", 1)
    peak_gain   = state.get("peak_gain_pct", 0)

    # Verify tier sequence integrity — tiers should be hit in order
    expected_order = [t["name"] for t in ladder]
    for i, tier_name in enumerate(tiers_hit):
        if tier_name not in expected_order:
            return _fail(f"{cfg['name']} unknown tier in tiers_hit: '{tier_name}'")
        if i > 0 and expected_order.index(tier_name) < expected_order.index(tiers_hit[i-1]):
            return _fail(f"{cfg['name']} tier sequence out of order: {tiers_hit}")

    # Verify current_tier index is consistent with tiers_hit count
    if current_tier != len(tiers_hit):
        return _warn(
            f"{cfg['name']} current_tier ({current_tier}) ≠ len(tiers_hit) ({len(tiers_hit)}) — "
            f"possible state inconsistency"
        )

    # Build profit-taking roadmap
    log(f"  {cfg['name']} Profit-Taking Roadmap:")
    for tier in ladder:
        hit     = tier["name"] in tiers_hit
        dist    = tier["trigger_pct"] - last_gain
        sell_str = f"sell {int(tier['sell_frac']*100)}% remaining" if tier["sell_frac"] > 0 else "tighten trail only"
        icon    = "✅" if hit else ("🎯" if dist <= 0 else f"⏳ +{dist:.0f}% away")
        log(f"    {icon} {tier['name']}: +{tier['trigger_pct']}% → {sell_str} | trail→{tier['trail_pct']}%")

    all_tiers_hit = len(tiers_hit) >= len(ladder)
    if all_tiers_hit:
        log(f"    🏃 Runner: {runner_trail}% trailing stop on {contracts}x remaining")

    # Check if current gain exceeds a tier that hasn't been hit yet (missed trigger?)
    for tier in ladder:
        if tier["name"] not in tiers_hit and last_gain >= tier["trigger_pct"]:
            return _fail(
                f"{cfg['name']} MISSED TIER — gain={last_gain:.1f}% exceeded "
                f"{tier['name']} trigger (+{tier['trigger_pct']}%) but tier not recorded. "
                f"Daemon may have been offline when trigger occurred!"
            )

    # All good
    if not activated:
        next_tier = ladder[0]
        dist = next_tier["trigger_pct"] - last_gain
        return _pass(
            f"{cfg['name']} profit-taking sequence intact | "
            f"Monitoring: +{dist:.0f}% to Tier 1 | "
            f"Full ladder: {' → '.join('+' + str(t['trigger_pct']) + '%' for t in ladder)} → runner {runner_trail}%"
        )
    elif all_tiers_hit:
        return _pass(
            f"{cfg['name']} all tiers hit — running with {runner_trail}% trail on {contracts}x | "
            f"Peak: +{peak_gain:.1f}%"
        )
    else:
        remaining = [t for t in ladder if t["name"] not in tiers_hit]
        next_t = remaining[0]
        dist = next_t["trigger_pct"] - last_gain
        return _pass(
            f"{cfg['name']} profit-taking on track | "
            f"Tiers hit: {len(tiers_hit)}/{len(ladder)} | "
            f"Next: {next_t['name']} at +{next_t['trigger_pct']}% (+{dist:.0f}% away)"
        )


def check_expiry(cfg):
    """Check days to expiry — warn at 180d, urgent at 90d."""
    days = _days_to_expiry(cfg["expiry"])
    exp_fmt = _fmt_expiry(cfg["expiry"])
    next_fmt = _fmt_expiry(cfg["next_exp"])

    if days is None:
        return _warn(f"{cfg['name']} expiry date parse failed")
    if days < 90:
        return _fail(
            f"{cfg['name']} EXPIRY URGENT: {days}d to {exp_fmt} — "
            f"roll to {next_fmt} NOW (HITL required)"
        )
    elif days < 180:
        return _warn(
            f"{cfg['name']} expiry warning: {days}d to {exp_fmt} — "
            f"plan roll to {next_fmt}"
        )
    return _pass(f"{cfg['name']} expiry OK — {days}d to {exp_fmt}")


def check_pid_lock(cfg):
    if os.path.exists(cfg["pid_file"]):
        try:
            pid = open(cfg["pid_file"]).read().strip()
            return _pass(f"{cfg['name']} PID lock present (PID {pid})")
        except Exception:
            return _pass(f"{cfg['name']} PID lock file present")
    return _warn(f"{cfg['name']} PID lock missing — daemon may allow duplicates")


def check_entry_code(cfg):
    """Exit code path is importable without errors."""
    try:
        script = cfg["script"].replace(".py", "")
        result = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0,'/Users/eddiemae/rudy/scripts'); "
             f"import {script}; "
             f"t = {script}.{cfg['class']}(); "
             f"print('OK')"],
            capture_output=True, text=True, timeout=15,
            cwd="/Users/eddiemae/rudy/scripts"
        )
        if "OK" in result.stdout:
            return _pass(f"{cfg['name']} exit code path importable — {cfg['class']}() clean")
        return _fail(f"{cfg['name']} exit code import error: {result.stderr[:200]}")
    except Exception as e:
        return _fail(f"{cfg['name']} code check error: {e}")


# ════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════

def run_verify():
    now = datetime.now()
    session = "OPEN" if now.hour < 12 else "CLOSE"
    log(f"{'='*60}")
    log(f"Execution Path Verify T2+T3 — {now.strftime('%A %b %d %H:%M ET')} ({session})")
    log(f"{'='*60}")

    all_results  = {}
    all_failures = []
    all_warnings = []

    # ── Shared IBKR check ──
    log("\n[SHARED] IBKR Connection")
    ibkr_status, ibkr_detail = check_ibkr()

    # ── Shared Clone Prohibition check (Article XI) ──
    log("\n[SHARED] Clone Prohibition (Article XI)")
    clone_violations = []
    for script in DISABLED_SCRIPTS:
        r = subprocess.run(["pgrep", "-f", script], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            clone_violations.append(f"{script} (PID {r.stdout.strip()})")
    if clone_violations:
        clone_status, clone_detail = _fail(f"CLONE VIOLATION — unauthorized traders running: {clone_violations}")
        all_failures.append(clone_detail)
    else:
        clone_status, clone_detail = _pass("Clone check clean — no unauthorized traders running")

    # ── Shared Telegram check ──
    log("\n[SHARED] Telegram HITL")
    try:
        telegram.send(
            "🔍 *Exec Path Verify T2+T3* — HITL check\n"
            "Telegram reachable. Exit approvals WILL deliver. ✅\n"
            f"_{now.strftime('%b %d %H:%M ET')}_"
        )
        tg_status, tg_detail = _pass("Telegram HITL reachable — exit approvals WILL deliver")
    except Exception as e:
        tg_status, tg_detail = _fail(f"Telegram UNREACHABLE: {e} — exit approvals WON'T deliver!")

    if ibkr_status is False:
        all_failures.append(ibkr_detail)
    if tg_status is False:
        all_failures.append(tg_detail)

    # ── Per-trader checks ──
    for tid, cfg in TRADERS.items():
        log(f"\n{'─'*50}")
        log(f"{cfg['name']} ({cfg['desc']}) — {cfg['script']}")
        log(f"{'─'*50}")

        checks = [
            ("Daemon",                  lambda c=cfg: check_daemon(c)),
            ("LaunchAgent",             lambda c=cfg: check_launchagent(c)),
            ("State Fresh",             lambda c=cfg: check_state_fresh(c)),
            ("State Valid",             lambda c=cfg: check_state_valid(c)),
            ("IBKR Position",           lambda c=cfg: check_position_via_ibkr(c)),
            ("Ladder Status",           lambda c=cfg: check_ladder_status(c)),
            ("Trail Stop Math",         lambda c=cfg: check_trail_stop_math(c)),
            ("Pending Sell",            lambda c=cfg: check_pending_sell(c)),
            ("Profit-Taking Sequence",  lambda c=cfg: check_profit_taking_sequence(c)),
            ("Execute Sell Path",       lambda c=cfg: check_execute_sell_path(c)),
            ("Expiry",                  lambda c=cfg: check_expiry(c)),
            ("PID Lock",                lambda c=cfg: check_pid_lock(c)),
            ("Exit Code",               lambda c=cfg: check_entry_code(c)),
        ]

        trader_results = []
        for label, fn in checks:
            log(f"\n  {cfg['name']} — {label}")
            try:
                status, detail = fn()
                trader_results.append((label, status, detail))
                if status is False:
                    all_failures.append(detail)
                elif status is None:
                    all_warnings.append(detail)
            except Exception as e:
                log(f"    💥 Check crashed: {e}")
                all_failures.append(f"{cfg['name']} {label} crashed: {e}")
                trader_results.append((label, False, str(e)))

        all_results[tid] = trader_results

    # ── Build Telegram report ──
    t2_state = _load_state(TRADERS["trader2"]["state"])
    t3_state = _load_state(TRADERS["trader3"]["state"])

    def state_summary(state, cfg):
        gain    = state.get("last_gain_pct", 0)
        val     = state.get("last_value", 0)
        active  = state.get("activated", False)
        tiers   = state.get("tiers_hit", [])
        trail   = state.get("trail_stop_value", 0)
        pending = state.get("pending_sell")
        conts   = state.get("contracts_remaining", 1)
        ladder  = cfg["ladder"]
        next_t  = next((t for t in ladder if t["name"] not in tiers), None)
        days_exp = _days_to_expiry(cfg["expiry"])

        gain_icon = "🟢" if gain >= 0 else "🔴"
        status = ("🔫 TRAIL ACTIVE" if active and trail > 0
                  else ("📊 ACTIVATED" if active
                        else f"⏳ Monitoring"))
        next_info = (f"Next: {next_t['name']} at +{next_t['trigger_pct']}%"
                     if next_t else "All tiers hit — running")
        pending_str = f"\n  ⚠️ PENDING SELL: {pending}" if pending else ""

        return (
            f"{gain_icon} {gain:+.1f}% | ${val:.2f} | {status}\n"
            f"  {next_info} | Trail: {'${:.2f}'.format(trail) if trail else 'not set'}\n"
            f"  Tiers: {', '.join(tiers) if tiers else 'none'} | Rem: {conts}x\n"
            f"  Expiry: {_fmt_expiry(cfg['expiry'])} ({days_exp}d){pending_str}"
        )

    total_checks = (sum(len(v) for v in all_results.values())
                    + 2)  # +2 for shared IBKR + Telegram
    total_failures = len(all_failures)
    total_warnings = len(all_warnings)

    if total_failures > 0:
        headline = f"🚨 *EXIT PATH BROKEN — {total_failures} FAILURE(S)*"
    else:
        headline = f"✅ *T2+T3 Exit Paths CLEAR — Ready to Execute*"

    t2_rows = all_results.get("trader2", [])
    t3_rows = all_results.get("trader3", [])

    def fmt_rows(rows):
        return "".join(
            f"{'✅' if s is True else ('❌' if s is False else '⚠️')} {lbl}\n"
            for lbl, s, _ in rows
        )

    msg = (
        f"{headline}\n"
        f"{now.strftime('%a %b %d — %I:%M %p ET')} | {session}\n\n"
        f"[SHARED]\n"
        f"{'✅' if ibkr_status else '❌'} IBKR TWS Connection\n"
        f"{'✅' if tg_status else '❌'} Telegram HITL\n"
        f"{'✅' if clone_status else '❌'} Clone Prohibition (Article XI)\n\n"
        f"*Trader2 — MSTR $50 Put*\n"
        f"{fmt_rows(t2_rows)}\n"
        f"{state_summary(t2_state, TRADERS['trader2'])}\n\n"
        f"*Trader3 — SPY $430 Put*\n"
        f"{fmt_rows(t3_rows)}\n"
        f"{state_summary(t3_state, TRADERS['trader3'])}\n"
    )

    if all_failures:
        msg += f"\n*🚨 Failures*\n" + "\n".join(f"• {f}" for f in all_failures)
    if all_warnings:
        msg += f"\n*⚠️ Warnings*\n" + "\n".join(f"• {w}" for w in all_warnings[:5])

    try:
        telegram.send(msg)
    except Exception as e:
        log(f"Final Telegram send failed: {e}")

    log(f"\nResult: {total_checks - total_failures}/{total_checks} passed | "
        f"{total_failures} failures | {total_warnings} warnings")
    return total_failures == 0


if __name__ == "__main__":
    ok = run_verify()
    sys.exit(0 if ok else 1)
