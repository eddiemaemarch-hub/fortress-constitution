"""Execution Path Verifier — Rudy v2.0 / Constitution v50.0
Runs Mon–Fri at 9:20 AM and 3:45 PM ET.
Verifies every step of the Trader1 entry + exit + expiry-roll execution path.
Sends Telegram report. Screams loudly if ANYTHING is broken.

19-check execution path:
  1.  Trader1 daemon alive
  2.  LaunchAgent registered (survives reboot)
  3.  IBKR TWS connected (port 7496)
  4.  Last eval fresh (< 26h on weekdays)
  5.  State file valid + writable
  6.  Filter status — where are we vs. signal?
  7.  HITL Telegram reachable (approval request will deliver)
  8.  No clone traders running (Article XI)
  9.  PID lock file protecting daemon
 10.  Entry/exit code path importable (no syntax/import errors)
 11.  IBKR position matches state
 12.  Trail stop / HWM floor integrity (entry×0.65 initial floor)
 13.  Pending sell / approval check
 14.  Profit-taking roadmap (10x/20x/50x/100x tiers, trend adder, euphoria)
 15.  Execute sell path (all exit methods callable + no recent failures)
 16.  LEAP expiry countdown (warn 180d / urgent 90d)
 17.  Entry sizing (NLV×25%×50% cash available)
 18.  Strike recommendation current and valid
 19.  LEAP Expiry Roll Protocol implemented + no stuck pending roll
"""
import os
import sys
import json
import subprocess
import socket
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

EXPIRY_ROLL_URGENT_DAYS = 90   # mirrors trader_v28.py constant

LOG_DIR  = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
LOG_FILE = os.path.join(LOG_DIR, "execution_path_verify.log")
os.makedirs(LOG_DIR, exist_ok=True)

STATE_FILE  = os.path.join(DATA_DIR, "trader_v28_state.json")
PID_FILE    = os.path.join(DATA_DIR, "trader_v28.lock")
SCRIPTS_DIR = os.path.expanduser("~/rudy/scripts")

DISABLED_SCRIPTS = [
    "trader1.py","trader2.py","trader3.py","trader4.py",
    "trader5.py","trader6.py","trader7.py","trader8.py",
    "trader9.py","trader10.py","trader11.py","trader12.py",
    "trader_moonshot.py","trader_v30.py",
]


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[Verify {ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def _pass(label):
    log(f"  ✅ {label}")
    return True, label


def _fail(label):
    log(f"  ❌ {label}")
    return False, label


def _warn(label):
    log(f"  ⚠️  {label}")
    return None, label


# ════════════════════════════════════════════════════════
# CHECKS
# ════════════════════════════════════════════════════════

def check_1_daemon():
    """Trader1 process is running."""
    r = subprocess.run(["pgrep", "-f", "trader_v28.py"],
                       capture_output=True, text=True, timeout=5)
    if r.returncode == 0:
        pid = r.stdout.strip().split("\n")[0]
        return _pass(f"Trader1 daemon running (PID {pid})")
    return _fail("Trader1 daemon is DOWN — entry WILL NOT fire")


def check_2_launchagent():
    """LaunchAgent registered — daemon restarts on reboot."""
    r = subprocess.run(["launchctl", "list", "com.rudy.trader1"],
                       capture_output=True, text=True, timeout=5)
    if r.returncode == 0:
        return _pass("LaunchAgent com.rudy.trader1 registered")
    return _fail("LaunchAgent NOT registered — daemon won't restart after reboot")


def check_3_ibkr():
    """IBKR TWS port 7496 is open and accepting connections."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        result = s.connect_ex(("127.0.0.1", 7496))
        s.close()
        if result == 0:
            return _pass("IBKR TWS port 7496 open and connectable")
        return _fail("IBKR TWS port 7496 REFUSED — TWS not running or not accepting API")
    except Exception as e:
        return _fail(f"IBKR port check error: {e}")


def check_4_eval_freshness():
    """Last evaluation ran within the expected window."""
    if not os.path.exists(STATE_FILE):
        return _fail("State file missing — trader_v28_state.json not found")
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        last_eval = state.get("last_eval", "")
        if not last_eval:
            return _fail("last_eval timestamp missing from state")
        last_dt = datetime.fromisoformat(last_eval)
        hours_ago = (datetime.now() - last_dt).total_seconds() / 3600
        weekday = datetime.now().weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
        if weekday >= 5:  # Weekend — 72h window
            threshold = 72
        else:
            threshold = 26  # Weekday — must have run within ~26h
        if hours_ago <= threshold:
            return _pass(f"Last eval: {hours_ago:.1f}h ago — FRESH")
        return _fail(f"Last eval: {hours_ago:.1f}h ago — STALE (threshold: {threshold}h) — daemon may be stuck")
    except Exception as e:
        return _fail(f"State file unreadable: {e}")


def check_5_state_writable():
    """State file is readable and writable."""
    if not os.path.exists(STATE_FILE):
        return _fail("State file missing")
    if not os.access(STATE_FILE, os.W_OK):
        return _fail("State file NOT writable — daemon can't save state on entry")
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        required = ["is_armed", "dipped_below_200w", "green_week_count",
                    "position_qty", "last_eval"]
        missing = [k for k in required if k not in state]
        if missing:
            return _fail(f"State missing keys: {missing}")
        return _pass("State file valid and writable")
    except Exception as e:
        return _fail(f"State file parse error: {e}")


def check_6_filters():
    """Filter status — how close are we to signal?"""
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)

        armed        = state.get("is_armed", False)
        dipped       = state.get("dipped_below_200w", False)
        green_weeks  = state.get("green_week_count", 0)
        in_position  = state.get("position_qty", 0) > 0
        mstr_price   = state.get("last_mstr_price", 0)
        btc_price    = state.get("last_btc_price", 0)
        premium      = state.get("last_premium", 0)
        stoch_rsi    = state.get("last_stoch_rsi", 0)
        regime       = state.get("last_regime", "UNKNOWN")
        regime_conf  = state.get("last_regime_confidence", 0)

        lines = [
            f"MSTR=${mstr_price:.2f} | BTC=${btc_price:,.0f} | Premium={premium:.2f}x",
            f"Dipped below 200W: {'✅' if dipped else '❌'}",
            f"Green weeks: {green_weeks}/2 {'✅' if green_weeks >= 2 else '❌ Need '+str(2-green_weeks)+' more Friday close(s) above 200W'}",
            f"Armed: {'🔫 YES — ENTRY IMMINENT' if armed else '⏳ NOT YET'}",
            f"StochRSI: {stoch_rsi:.0f} {'✅' if stoch_rsi < 70 else '❌ Overbought'}",
            f"In position: {'YES — skip entry' if in_position else '✅ No position, clear to enter'}",
            f"Regime: {regime} ({regime_conf*100:.0f}%)",
        ]
        summary = " | ".join(lines[:3])
        log(f"  📊 {summary}")

        # Return PASS only if armed, WARN if close, INFO if far
        if armed:
            return _pass(f"ARMED 🔫 — all entry filters ready to fire | StochRSI={stoch_rsi:.0f}")
        elif dipped and green_weeks >= 1:
            return _warn(f"1 of 2 green weeks complete — ONE MORE Friday close above 200W fires the gun")
        elif dipped and green_weeks == 0:
            return _warn(f"Dipped ✅ | Waiting for first green Friday close above MSTR 200W SMA")
        else:
            return _warn(f"Waiting for BTC/MSTR dip below 200W SMA")

    except Exception as e:
        return _fail(f"Filter check error: {e}")


def check_7_telegram():
    """Telegram HITL path is reachable — this is how the trade approval is sent."""
    try:
        telegram.send(
            "🔍 *Execution Path Verify* — HITL check\n"
            "Telegram is reachable. Trade approval will deliver. ✅\n"
            f"_{datetime.now().strftime('%b %d %H:%M ET')}_"
        )
        return _pass("Telegram HITL reachable — approval request WILL deliver")
    except Exception as e:
        return _fail(f"Telegram UNREACHABLE: {e} — trade approval WON'T deliver!")


def check_8_clone_prohibition():
    """No unauthorized trader scripts running (Article XI)."""
    running = []
    for script in DISABLED_SCRIPTS:
        r = subprocess.run(["pgrep", "-f", script],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            running.append(f"{script} (PID {r.stdout.strip()})")
    if running:
        return _fail(f"CLONE VIOLATION — unauthorized traders running: {running}")
    return _pass("Clone check clean — no unauthorized traders running")


def check_9_pid_lock():
    """PID lock file exists — prevents duplicate daemons."""
    if os.path.exists(PID_FILE):
        try:
            pid = open(PID_FILE).read().strip()
            return _pass(f"PID lock file present (PID {pid})")
        except Exception:
            return _pass("PID lock file present")
    return _warn("PID lock file missing — daemon may allow duplicates")


def check_10_entry_code():
    """Entry code path is importable without errors."""
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0,'/Users/eddiemae/rudy/scripts'); "
             "import trader_v28; "
             "t = trader_v28.RudyV28(); "
             "print('OK')"],
            capture_output=True, text=True, timeout=15,
            cwd=SCRIPTS_DIR
        )
        if "OK" in result.stdout:
            return _pass("Entry/exit code path importable — RudyV28() instantiates cleanly")
        return _fail(f"Entry code import error: {result.stderr[:200]}")
    except Exception as e:
        return _fail(f"Entry code check failed: {e}")


def check_11_ibkr_position():
    """Verify IBKR position matches state — when in position, LEAP must exist; when not, confirm clean."""
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        in_position = state.get("position_qty", 0) > 0
        entry_price = state.get("entry_price", 0)
        strike_rec  = state.get("last_strike_recommendation", {})
    except Exception as e:
        return _fail(f"State read error for position check: {e}")

    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:3001/api/account-live", timeout=5) as r:
            data = json.loads(r.read())
        positions = data.get("positions", [])
        mstr_opts  = [p for p in positions if p.get("symbol") == "MSTR"
                      and p.get("secType") == "OPT" and p.get("right") == "C"]
        mstr_stock = [p for p in positions if p.get("symbol") == "MSTR"
                      and p.get("secType") == "STK"]
    except Exception as e:
        return _warn(f"IBKR position check error (dashboard unreachable): {e}")

    if in_position:
        # Should have a MSTR option or stock position
        if mstr_opts:
            p = mstr_opts[0]
            exp = p.get("expiry", "?")
            strike = p.get("strike", 0)
            qty = p.get("qty", 0)
            avg = p.get("avg_cost", 0)
            days = None
            try:
                days = (datetime.strptime(exp, "%Y%m%d") - datetime.now()).days
            except Exception:
                pass
            return _pass(
                f"MSTR LEAP position confirmed: ${strike:.0f}C qty={qty:.0f} "
                f"avg=${avg:.2f} exp={exp}"
                + (f" ({days}d)" if days else "")
            )
        elif mstr_stock:
            p = mstr_stock[0]
            return _pass(f"MSTR stock position confirmed: qty={p.get('qty',0):.0f} avg=${p.get('avg_cost',0):.2f}")
        else:
            return _fail(
                "State says IN POSITION but NO MSTR position found in IBKR — "
                "state/IBKR mismatch! Entry may have failed silently."
            )
    else:
        # Not in position — confirm no accidental MSTR long
        if mstr_opts or mstr_stock:
            positions_str = ", ".join(
                f"{p.get('symbol')} {p.get('right','')}{p.get('strike','')} qty={p.get('qty',0)}"
                for p in (mstr_opts + mstr_stock)
            )
            return _warn(
                f"State says NOT in position but MSTR position(s) detected in IBKR: {positions_str} — verify"
            )
        band = strike_rec.get("band", "?")
        spec = strike_rec.get("spec_strikes", [])
        return _pass(
            f"No position — clean. Ready to enter. "
            f"Recommended strikes ({band}): {spec}"
        )


def check_17_entry_sizing():
    """Verify entry sizing math — NLV × 25% risk capital × 50% deploy = buy amount."""
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        in_position = state.get("position_qty", 0) > 0
        if in_position:
            qty       = state.get("position_qty", 0)
            entry_px  = state.get("entry_price", 0)
            return _pass(f"Already in position — qty={qty:.0f} shares @ ${entry_px:.2f} avg")
    except Exception as e:
        return _fail(f"State read error for sizing check: {e}")

    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:3001/api/account-live", timeout=5) as r:
            data = json.loads(r.read())
        nlv  = data.get("net_liq", 0)
        cash = data.get("cash", 0)
    except Exception as e:
        return _warn(f"Could not fetch NLV for sizing check: {e}")

    if nlv <= 0:
        return _fail("NLV is zero or unavailable — cannot size entry")

    # Constitution v50.0: 25% risk capital × 50% deploy on first entry
    risk_capital = nlv * 0.25
    deploy_1st   = risk_capital * 0.50
    mstr_price   = state.get("last_mstr_price", 0) if 'state' in dir() else 0
    qty_estimate = int(deploy_1st / mstr_price) if mstr_price > 0 else 0

    if cash < deploy_1st:
        return _fail(
            f"INSUFFICIENT CASH for entry: need ~${deploy_1st:.0f} "
            f"(NLV ${nlv:.0f} × 25% × 50%) but cash=${cash:.0f}"
        )
    return _pass(
        f"Entry sizing OK — NLV=${nlv:.0f} | Risk cap=${risk_capital:.0f} | "
        f"1st deploy=${deploy_1st:.0f} | Cash available=${cash:.0f} | "
        f"~{qty_estimate} shares @ ${mstr_price:.2f}"
    )


def check_18_strike_recommendation():
    """Strike recommendation is current and valid."""
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        rec = state.get("last_strike_recommendation", {})
        if not rec:
            return _warn("No strike recommendation in state yet — will generate on first eval after arming")

        band         = rec.get("band", "?")
        spec_strikes = rec.get("spec_strikes", [])
        safe_strikes = rec.get("safety_strikes", [])
        spec_weight  = rec.get("spec_weight", 0)
        safe_weight  = rec.get("safety_weight", 0)
        ts           = rec.get("timestamp", "")

        if not spec_strikes and not safe_strikes:
            return _fail("Strike recommendation is empty — no strikes defined")

        # Check freshness — should be updated within 48h
        if ts:
            try:
                rec_dt = datetime.fromisoformat(ts)
                hours = (datetime.now() - rec_dt).total_seconds() / 3600
                if hours > 48:
                    return _warn(f"Strike recommendation stale: {hours:.0f}h old — will refresh on next eval")
                freshness = f"{hours:.0f}h ago"
            except Exception:
                freshness = "unknown age"
        else:
            freshness = "no timestamp"

        # Validate weights sum to ~1.0
        weight_sum = spec_weight + safe_weight
        if abs(weight_sum - 1.0) > 0.05:
            return _warn(f"Strike weights don't sum to 1.0: spec={spec_weight} + safe={safe_weight} = {weight_sum:.2f}")

        return _pass(
            f"Strike rec OK ({freshness}) — Band: {band} | "
            f"Spec: {spec_strikes} ({spec_weight*100:.0f}%) | "
            f"Safety: {safe_strikes} ({safe_weight*100:.0f}%)"
        )
    except Exception as e:
        return _fail(f"Strike recommendation check error: {e}")



def check_12_trail_stop_math():
    """T1 trail equivalent — HWM floor integrity when in position."""
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        in_position  = state.get("position_qty", 0) > 0
        entry_price  = state.get("entry_price", 0)
        hwm          = state.get("position_hwm", 0)
        peak_gain    = state.get("peak_gain_pct", 0)
        mstr_price   = state.get("last_mstr_price", 0)
    except Exception as e:
        return _fail(f"State read error for trail check: {e}")

    if not in_position:
        return _pass("Not in position — trail/floor check N/A (will activate on entry)")

    if entry_price <= 0:
        return _fail("In position but entry_price=0 — floor cannot be calculated")

    # Initial floor: entry × 0.65 (35% max loss)
    initial_floor   = entry_price * 0.65
    # Panic floor: -35% from entry
    panic_floor     = entry_price * 0.65

    if hwm < entry_price:
        return _fail(
            f"HWM ${hwm:.2f} is BELOW entry ${entry_price:.2f} — "
            f"position HWM tracking corrupted"
        )

    # Drawdown from HWM
    drawdown_from_hwm = ((mstr_price - hwm) / hwm * 100) if hwm > 0 else 0

    log(f"  T1 Trail — entry=${entry_price:.2f} | HWM=${hwm:.2f} | "
        f"floor=${initial_floor:.2f} | current=${mstr_price:.2f} | "
        f"drawdown from HWM={drawdown_from_hwm:+.1f}%")

    if mstr_price < initial_floor:
        return _fail(
            f"MSTR ${mstr_price:.2f} is BELOW initial floor ${initial_floor:.2f} "
            f"(entry ${entry_price:.2f} × 0.65) — exit should have triggered!"
        )
    return _pass(
        f"Floor intact — entry=${entry_price:.2f} | floor=${initial_floor:.2f} | "
        f"HWM=${hwm:.2f} | current=${mstr_price:.2f} | "
        f"drawdown from HWM={drawdown_from_hwm:+.1f}% | peak gain={peak_gain:.1f}%"
    )


def check_13_pending_sell():
    """Check for any pending approval sitting unanswered in T1 state."""
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except Exception as e:
        return _fail(f"State read error for pending check: {e}")

    issues = []

    # Pending strike roll (waiting for Commander approval)
    roll = state.get("pending_strike_roll")
    if roll:
        ts = roll.get("timestamp", "")
        age_str = ""
        if ts:
            try:
                age_min = (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 60
                age_str = f"{age_min:.0f}min ago"
                if age_min > 60:
                    issues.append(
                        f"PENDING STRIKE ROLL unanswered for {age_min:.0f}min — "
                        f"use MCP approve_strike_roll or reject"
                    )
            except Exception:
                pass
        if not issues:
            return _warn(f"Pending strike roll ({age_str}) — awaiting Commander approval")

    # Expiry roll pending — WARN not FAIL (this is the normal HITL waiting state)
    pending_roll = state.get("pending_expiry_roll")
    if pending_roll:
        ts = pending_roll.get("timestamp", "")
        days_left = pending_roll.get("days_left", "?")
        strike    = pending_roll.get("strike", 0)
        old_exp   = pending_roll.get("old_expiry", "?")
        urgency   = pending_roll.get("urgency", "")
        age_str   = ""
        if ts:
            try:
                age_min = (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 60
                age_str = f" ({age_min:.0f}min ago)"
            except Exception:
                pass
        roll_msg = (f"Pending expiry roll{age_str}: "
                    f"${strike:.0f}C {old_exp} | {days_left}d left | {urgency}")
        if isinstance(days_left, int) and days_left < 90:
            issues.append(f"URGENT EXPIRY ROLL UNANSWERED{age_str} — {days_left}d left!")
        else:
            # Surface as warn, not fail — Commander needs to respond
            if not issues:
                return _warn(roll_msg)

    if issues:
        return _fail(" | ".join(issues))
    return _pass("No pending approvals — state clean")


def check_14_profit_taking_roadmap():
    """T1 profit-taking roadmap — pt_hits progress, trend adder, euphoria sell."""
    PROFIT_TIERS = [
        (1000,  0.10, "10x"),
        (2000,  0.10, "20x"),
        (5000,  0.10, "50x"),
        (10000, 0.10, "100x"),
    ]
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        in_position     = state.get("position_qty", 0) > 0
        pt_hits         = state.get("pt_hits", [False] * 4)
        entry_price     = state.get("entry_price", 0)
        mstr_price      = state.get("last_mstr_price", 0)
        second_done     = state.get("second_entry_done", False)
        euphoria_done   = state.get("euphoria_sell_done", False)
        peak_gain       = state.get("peak_gain_pct", 0)
        adder_entry     = state.get("trend_adder_entry_price", 0)
    except Exception as e:
        return _fail(f"State read error for roadmap: {e}")

    if not in_position:
        return _pass(
            "Not in position — profit-taking roadmap N/A | "
            "Roadmap: 10x→sell10% → 20x→sell10% → 50x→sell10% → 100x→sell10% | "
            "Trend adder at 50W EMA golden cross | Euphoria sell at premium >3.5x"
        )

    # Gain from entry
    gain_pct = ((mstr_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

    log(f"  T1 Profit-Taking Roadmap (in position @ ${entry_price:.2f}, "
        f"current ${mstr_price:.2f}, gain={gain_pct:+.1f}%):")

    missed = []
    for i, (threshold, sell_pct, label) in enumerate(PROFIT_TIERS):
        hit  = pt_hits[i] if i < len(pt_hits) else False
        icon = "✅" if hit else "⏳"
        gain_needed = threshold - gain_pct
        dist_str = f"(+{gain_needed:.0f}% needed)" if not hit else "(hit)"
        log(f"    {icon} PT{i+1} {label}: +{threshold:.0f}% → sell {int(sell_pct*100)}% {dist_str}")

        # Missed tier check — gain exceeded threshold but not recorded
        if gain_pct >= threshold and not hit:
            missed.append(f"PT{i+1} ({label}) missed — gain {gain_pct:.0f}% exceeded +{threshold}%!")

    log(f"    {'✅' if second_done else '⏳'} Trend Adder: "
        f"{'done @ ${:.2f}'.format(adder_entry) if second_done else 'waiting for golden cross'}")
    log(f"    {'✅' if euphoria_done else '⏳'} Euphoria Sell: "
        f"{'done' if euphoria_done else 'triggers at premium >3.5x mNAV'}")

    if missed:
        return _fail(f"MISSED PROFIT TARGETS: {'; '.join(missed)}")

    pts_hit = sum(1 for h in pt_hits if h)
    return _pass(
        f"Profit-taking on track — {pts_hit}/4 PTs hit | "
        f"Trend adder: {'done' if second_done else 'pending'} | "
        f"Euphoria: {'done' if euphoria_done else 'pending'} | "
        f"Peak gain: {peak_gain:.1f}%"
    )


def check_15_execute_sell_path():
    """T1 execute sell path — verify all exit methods callable and no sell failures in recent log."""
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0,'/Users/eddiemae/rudy/scripts'); "
             "import trader_v28; t = trader_v28.RudyV28(); "
             "assert hasattr(t, '_execute_exit'), 'missing _execute_exit'; "
             "assert hasattr(t, '_execute_partial_sell'), 'missing _execute_partial_sell'; "
             "assert hasattr(t, '_execute_trend_adder'), 'missing _execute_trend_adder'; "
             "assert hasattr(t, '_exit_trend_adder'), 'missing _exit_trend_adder'; "
             "assert hasattr(t, 'manage_trend_adder'), 'missing manage_trend_adder'; "
             "assert hasattr(t, 'reconcile_position'), 'missing reconcile_position'; "
             "assert hasattr(t, 'cleanup_stale_orders'), 'missing cleanup_stale_orders'; "
             "print('OK')"],
            capture_output=True, text=True, timeout=15,
            cwd=SCRIPTS_DIR
        )
        if "OK" not in result.stdout:
            return _fail(f"Execute sell methods missing: {result.stderr.strip()[:200]}")
    except Exception as e:
        return _fail(f"Execute sell path check error: {e}")

    # Check recent log for EXIT FAILED messages
    log_file = os.path.expanduser("~/rudy/logs/trader_v28.log")
    exit_failures = []
    if os.path.exists(log_file):
        try:
            lines = open(log_file).readlines()[-200:]  # Last 200 lines
            for line in lines:
                if "EXIT FAILED" in line or "ENTRY FAILED" in line or "SELL FAILED" in line:
                    exit_failures.append(line.strip()[-100:])
        except Exception:
            pass

    if exit_failures:
        return _warn(
            f"Execute sell path clean BUT recent failures in log: "
            f"{exit_failures[-1]}"
        )
    return _pass(
        "_execute_exit + _execute_partial_sell + _execute_trend_adder + "
        "_exit_trend_adder + reconcile_position + cleanup_stale_orders all callable | "
        "No recent EXIT/SELL failures in log"
    )


def check_16_expiry():
    """Check LEAP expiry when in position — warn at 180d, urgent at 90d."""
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        in_position = state.get("position_qty", 0) > 0
    except Exception as e:
        return _fail(f"State read error for expiry check: {e}")

    if not in_position:
        # Not in position yet — show recommended expiry from strike recommendation
        rec = state.get("last_strike_recommendation", {})
        band = rec.get("band", "?")
        spec = rec.get("spec_strikes", [])
        return _pass(f"No active position — expiry check N/A. Strike band: {band} | Rec strikes: {spec}")

    # In position — check IBKR for expiry
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:3001/api/account-live", timeout=5) as r:
            data = json.loads(r.read())
        positions = data.get("positions", [])
        mstr_opts = [p for p in positions if p.get("symbol") == "MSTR"
                     and p.get("secType") == "OPT"]
        if not mstr_opts:
            return _warn("In position but no MSTR option found in IBKR for expiry check")

        p = mstr_opts[0]
        exp_str = p.get("expiry", "")
        if not exp_str:
            return _warn("MSTR option has no expiry date in IBKR data")

        try:
            exp_dt = datetime.strptime(exp_str, "%Y%m%d")
            days = (exp_dt - datetime.now()).days
            exp_fmt = exp_dt.strftime("%b %d %Y")
        except Exception:
            return _warn(f"Could not parse expiry date: {exp_str}")

        if days < 90:
            return _fail(
                f"LEAP EXPIRY URGENT: {days}d to {exp_fmt} — "
                "roll required NOW (HITL approve_expiry_roll)"
            )
        elif days < 180:
            return _warn(f"LEAP expiry WARNING: {days}d to {exp_fmt} — plan roll")
        return _pass(f"LEAP expiry OK — {days}d to {exp_fmt}")

    except Exception as e:
        return _warn(f"Expiry check error: {e}")


def check_19_expiry_roll_protocol():
    """LEAP Expiry Roll Protocol — live IBKR countdown + protocol integrity.

    Every 9:20 AM and 3:45 PM this check:
    1. Scans IBKR for live MSTR CALL positions and shows exact days to expiry
    2. Verifies _check_expiry_extension / approve_expiry_roll / reject_expiry_roll callable
    3. FAILs if a pending roll is unanswered inside the urgent window (<90d)
    4. WARNs if pending roll is awaiting approval (>90d, no immediate danger)
    5. Shows 180d/90d alert flag status so Commander knows where Rudy is in the cycle
    """
    # ── Part A: Live IBKR scan for MSTR CALL positions ──
    ibkr_leap_line = "No MSTR CALL position detected in IBKR"
    ibkr_days      = None
    ibkr_exp_fmt   = None
    ibkr_strike    = None
    ibkr_qty       = None

    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:3001/api/account-live", timeout=5) as r:
            data = json.loads(r.read())
        positions = data.get("positions", [])
        mstr_calls = [
            p for p in positions
            if p.get("symbol") == "MSTR"
            and p.get("secType") == "OPT"
            and p.get("right") == "C"
        ]

        if mstr_calls:
            # Sort by nearest expiry
            mstr_calls.sort(key=lambda p: p.get("expiry", "99999999"))
            p = mstr_calls[0]
            exp_str    = p.get("expiry", "")
            ibkr_strike = p.get("strike", 0)
            ibkr_qty    = p.get("qty", 0)
            avg_cost    = p.get("avg_cost", 0)

            if exp_str:
                try:
                    exp_dt      = datetime.strptime(exp_str, "%Y%m%d")
                    ibkr_days   = (exp_dt - datetime.now()).days
                    ibkr_exp_fmt = exp_dt.strftime("%b %d %Y")
                except Exception:
                    pass

            if ibkr_days is not None:
                if ibkr_days < 90:
                    status_icon = "🚨"
                    status_tag  = "URGENT — roll required NOW"
                elif ibkr_days < 180:
                    status_icon = "⚠️"
                    status_tag  = "WARNING — plan the roll"
                else:
                    status_icon = "✅"
                    status_tag  = "OK"

                ibkr_leap_line = (
                    f"{status_icon} LEAP: ${ibkr_strike:.0f}C ×{ibkr_qty:.0f} "
                    f"exp {ibkr_exp_fmt} ({ibkr_days}d) avg=${avg_cost:.2f} — {status_tag}"
                )
                log(f"  📅 {ibkr_leap_line}")
            else:
                ibkr_leap_line = (
                    f"MSTR ${ibkr_strike:.0f}C ×{ibkr_qty:.0f} detected "
                    f"but expiry date unreadable"
                )
    except Exception as e:
        ibkr_leap_line = f"IBKR scan unavailable: {e}"

    # ── Part B: Verify protocol methods callable ──
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0,'/Users/eddiemae/rudy/scripts'); "
             "import trader_v28; t = trader_v28.RudyV28(); "
             "assert hasattr(t, '_check_expiry_extension'), 'missing _check_expiry_extension'; "
             "assert hasattr(t, 'approve_expiry_roll'), 'missing approve_expiry_roll'; "
             "assert hasattr(t, 'reject_expiry_roll'), 'missing reject_expiry_roll'; "
             "print('OK')"],
            capture_output=True, text=True, timeout=15,
            cwd=SCRIPTS_DIR
        )
        if "OK" not in result.stdout:
            return _fail(
                f"EXPIRY ROLL PROTOCOL MISSING from RudyV28 — "
                f"cannot auto-execute roll: {result.stderr.strip()[:200]}"
            )
    except Exception as e:
        return _fail(f"Expiry roll protocol method check error: {e}")

    # ── Part C: State — pending roll + alert flags ──
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except Exception as e:
        return _fail(f"State read error for expiry roll check: {e}")

    pending     = state.get("pending_expiry_roll")
    alerted_180 = state.get("expiry_roll_alerted_180d", False)
    alerted_90  = state.get("expiry_roll_alerted_90d",  False)

    if pending:
        ts        = pending.get("timestamp", "")
        urgency   = pending.get("urgency", "⚠️")
        days_left = pending.get("days_left", "?")
        strike    = pending.get("strike", 0)
        old_exp   = pending.get("old_expiry", "?")
        new_exp   = pending.get("new_expiry", "?")
        age_str   = ""
        if ts:
            try:
                age_min = (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 60
                age_str = f" (proposed {age_min:.0f}min ago)"
            except Exception:
                pass

        if isinstance(days_left, int) and days_left < EXPIRY_ROLL_URGENT_DAYS:
            return _fail(
                f"{urgency} URGENT ROLL UNANSWERED{age_str} | "
                f"${strike:.0f}C {old_exp} → {new_exp} | {days_left}d LEFT — "
                f"USE MCP approve_expiry_roll NOW | {ibkr_leap_line}"
            )
        return _warn(
            f"Pending roll awaiting approval{age_str}: "
            f"${strike:.0f}C {old_exp} → {new_exp} | {days_left}d | "
            f"{ibkr_leap_line}"
        )

    # ── No pending roll — show full status ──
    alert_status = (
        f"180d alert: {'fired ✅' if alerted_180 else 'armed'} | "
        f"90d alert: {'fired ✅' if alerted_90 else 'armed'}"
    )

    # If IBKR shows a LEAP in the danger zone but no pending roll — warn
    if ibkr_days is not None and ibkr_days < 180 and not pending:
        if ibkr_days < 90:
            return _fail(
                f"LEAP <90d and NO pending roll in state! "
                f"{ibkr_leap_line} | "
                f"Rudy should have fired — check daemon eval log"
            )
        return _warn(
            f"{ibkr_leap_line} | {alert_status} | "
            f"Roll proposal pending next eval cycle"
        )

    return _pass(
        f"Expiry roll protocol LIVE ✅ | {ibkr_leap_line} | "
        f"{alert_status} | No pending roll"
    )


# ════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════

def run_verify():
    now = datetime.now()
    session = "OPEN" if now.hour < 12 else "CLOSE"
    log(f"{'='*60}")
    log(f"Execution Path Verify — {now.strftime('%A %b %d %H:%M ET')} ({session})")
    log(f"{'='*60}")

    checks = [
        ("1. Trader1 Daemon",       check_1_daemon),
        ("2. LaunchAgent",          check_2_launchagent),
        ("3. IBKR Connection",      check_3_ibkr),
        ("4. Eval Freshness",       check_4_eval_freshness),
        ("5. State File",           check_5_state_writable),
        ("6. Filter Status",        check_6_filters),
        ("7. Telegram HITL",        check_7_telegram),
        ("8. Clone Prohibition",    check_8_clone_prohibition),
        ("9. PID Lock",             check_9_pid_lock),
        ("10. Entry/Exit Code",          check_10_entry_code),
        ("11. IBKR Position",            check_11_ibkr_position),
        ("12. Trail Stop / Floor",       check_12_trail_stop_math),
        ("13. Pending Sell / Approval",  check_13_pending_sell),
        ("14. Profit-Taking Roadmap",    check_14_profit_taking_roadmap),
        ("15. Execute Sell Path",        check_15_execute_sell_path),
        ("16. LEAP Expiry",              check_16_expiry),
        ("17. Entry Sizing",             check_17_entry_sizing),
        ("18. Strike Recommendation",    check_18_strike_recommendation),
        ("19. Expiry Roll Protocol",     check_19_expiry_roll_protocol),
    ]

    results = []
    failures = []
    warnings = []

    for label, fn in checks:
        log(f"\n{label}")
        try:
            status, detail = fn()
            results.append((label, status, detail))
            if status is False:
                failures.append(detail)
            elif status is None:
                warnings.append(detail)
        except Exception as e:
            log(f"  💥 Check crashed: {e}")
            failures.append(f"{label} check crashed: {e}")
            results.append((label, False, str(e)))

    # ── Build Telegram report ──
    passed   = sum(1 for _, s, _ in results if s is True)
    failed   = len(failures)
    warned   = len(warnings)
    total    = len(results)

    # Get filter detail for headline
    try:
        with open(STATE_FILE) as f:
            st = json.load(f)
        armed       = st.get("is_armed", False)
        green_weeks = st.get("green_week_count", 0)
        dipped      = st.get("dipped_below_200w", False)
        mstr        = st.get("last_mstr_price", 0)
        btc         = st.get("last_btc_price", 0)
        stoch       = st.get("last_stoch_rsi", 0)
        regime      = st.get("last_regime", "?")
        regime_conf = st.get("last_regime_confidence", 0)
        premium     = st.get("last_premium", 0)
        last_eval   = st.get("last_eval", "?")[:16].replace("T", " ")
    except Exception:
        armed = False; green_weeks = 0; dipped = False
        mstr = btc = stoch = premium = 0; regime = "?"; regime_conf = 0
        last_eval = "?"

    if failed > 0:
        headline = f"🚨 *EXECUTION PATH BROKEN — {failed} FAILURE(S)*"
    elif armed:
        headline = f"🔫 *ARMED — ENTRY IMMINENT*"
    else:
        headline = f"✅ *Execution Path CLEAR — Waiting for Signal*"

    weeks_needed = max(0, 2 - green_weeks)
    if armed:
        signal_line = "🔫 ARMED — all filters green — waiting for daily eval trigger"
    elif dipped:
        signal_line = (
            f"⏳ {green_weeks}/2 green weeks | "
            f"Need {weeks_needed} more Friday close(s) above MSTR 200W SMA"
        )
    else:
        signal_line = "Waiting for MSTR/BTC dip below 200W SMA"

    msg = (
        f"{headline}\n"
        f"{now.strftime('%a %b %d — %I:%M %p ET')} | {session} check\n\n"
        f"*Entry Pipeline ({passed}/{total} checks passed)*\n"
        + "".join(
            f"{'✅' if s is True else ('❌' if s is False else '⚠️')} {lbl.split('. ',1)[-1]}\n"
            for lbl, s, _ in results
        )
        + f"\n*Signal Status*\n"
        f"{signal_line}\n"
        f"MSTR: ${mstr:.2f} | BTC: ${btc:,.0f}\n"
        f"Premium: {premium:.2f}x mNAV | StochRSI: {stoch:.0f}\n"
        f"Regime: {regime} ({regime_conf*100:.0f}%) | Last eval: {last_eval}\n"
    )

    if failures:
        msg += f"\n*🚨 Failures*\n" + "\n".join(f"• {f}" for f in failures)
    if warnings:
        msg += f"\n*⚠️ Warnings*\n" + "\n".join(f"• {w}" for w in warnings)

    # Telegram already sent via check_7 if reachable — this sends the full report
    try:
        telegram.send(msg)
    except Exception as e:
        log(f"Final Telegram send failed: {e}")

    log(f"\nResult: {passed}/{total} passed | {failed} failures | {warned} warnings")
    return failed == 0


if __name__ == "__main__":
    ok = run_verify()
    sys.exit(0 if ok else 1)
