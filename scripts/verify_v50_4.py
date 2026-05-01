#!/usr/bin/env python3
"""
v50.4 Late-Fill Fix Verification — one-shot, runs Mon 2026-05-04 10:30 ET.

Verifies:
  1) trader_v28.log has no f-string crashes / ValueErrors / new ENTRY signals since 2026-05-01 fix
  2) trader_v28_state.json reflects the $500C partial entry
  3) Live IBKR positions match state — no divergence
  4) Reports verdict via Telegram

Then unloads its own LaunchAgent.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/Users/eddiemae/rudy/scripts")
import telegram

LOG = Path("/Users/eddiemae/rudy/logs/trader_v28.log")
STATE = Path("/Users/eddiemae/rudy/data/trader_v28_state.json")
PLIST = Path.home() / "Library/LaunchAgents/com.rudy.v50-4-verify.plist"
FIX_TIME = datetime(2026, 5, 1, 16, 2, 21)  # daemon restart that loaded the fix


def check_log():
    findings = []
    if not LOG.exists():
        return ["log file missing"]
    text = LOG.read_text(errors="ignore")
    lines = [ln for ln in text.splitlines() if ln.startswith("[2026-05-")]
    after_fix = []
    for ln in lines:
        m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", ln)
        if not m:
            continue
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if ts >= FIX_TIME:
            after_fix.append(ln)
    if not after_fix:
        return ["no log entries since fix — daemon not running?"]
    crashes = [ln for ln in after_fix if "Invalid format specifier" in ln or "ValueError" in ln]
    if crashes:
        findings.append(f"{len(crashes)} crash(es) since fix: {crashes[-1][:200]}")
    new_signals = [ln for ln in after_fix if "ENTRY SIGNAL" in ln or "ENTRY APPROVAL REQUESTED" in ln]
    if new_signals:
        findings.append(f"{len(new_signals)} unexpected ENTRY signal(s) since fix — possible re-entry attempt")
    timeouts = [ln for ln in after_fix if "Timeout(PendingSubmit)" in ln or "LATE FILL" in ln]
    if timeouts:
        findings.append(f"INFO: {len(timeouts)} timeout/late-fill event(s) since fix (fix exercised)")
    return findings


def check_state():
    findings = []
    if not STATE.exists():
        return ["state file missing"]
    s = json.loads(STATE.read_text())
    if not s.get("first_entry_done"):
        findings.append(f"first_entry_done={s.get('first_entry_done')} (expected True)")
    if s.get("position_qty") != 1:
        findings.append(f"position_qty={s.get('position_qty')} (expected 1)")
    if not s.get("already_entered_this_cycle"):
        findings.append(f"already_entered_this_cycle={s.get('already_entered_this_cycle')} (expected True)")
    contracts = s.get("leap_contracts") or []
    has_500c = any(
        c.get("strike") == 500 and c.get("expiry") == "20280121" and c.get("qty") == 1
        for c in contracts
    )
    if not has_500c:
        findings.append(f"$500C 20280121 not in leap_contracts: {contracts}")
    if s.get("pending_entry"):
        findings.append(f"pending_entry not None: {s['pending_entry']}")
    return findings, s


def check_ibkr():
    try:
        from ib_insync import IB
    except ImportError:
        return ["ib_insync not installed in this Python"], None
    ib = IB()
    try:
        ib.connect("127.0.0.1", 7496, clientId=88, timeout=10)
    except Exception as e:
        return [f"IBKR connect failed: {e}"], None
    try:
        positions = ib.positions()
        target = None
        for p in positions:
            c = p.contract
            if (c.secType == "OPT" and c.symbol == "MSTR"
                    and c.lastTradeDateOrContractMonth == "20280121"
                    and c.right == "C" and float(c.strike) == 500.0):
                target = p
                break
        if not target:
            others = [
                f"{p.contract.symbol} {p.contract.lastTradeDateOrContractMonth} {p.contract.strike}{p.contract.right} ×{p.position}"
                for p in positions if p.contract.secType == "OPT"
            ]
            return [f"$500C 20280121 NOT in IBKR. Live OPT positions: {others}"], None
        if target.position != 1:
            return [f"$500C qty mismatch: IBKR={target.position}, expected 1"], target
        return [], target
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass


def main():
    log_findings = check_log()
    state_findings, state = check_state()
    ibkr_findings, ibkr_pos = check_ibkr()

    blocking = (
        [f for f in log_findings if not f.startswith("INFO:")]
        + state_findings
        + ibkr_findings
    )
    info = [f for f in log_findings if f.startswith("INFO:")]

    verdict = "✅ PASS" if not blocking else "🔴 FAIL"

    lines = [f"*v50.4 Fix Verification — {verdict}*",
             f"_Mon 2026-05-04 10:30 ET post-eval check_", ""]
    if state and ibkr_pos is not None:
        lines.append(f"📊 *Position match:* IBKR ✓ State ✓")
        lines.append(f"  $500C 20280121 ×1 @ ${state.get('leap_avg_cost', 0):.2f}")
        lines.append(f"  IBKR avgCost: ${ibkr_pos.avgCost:.2f}  qty: {int(ibkr_pos.position)}")
        lines.append(f"  entry_price (MSTR): ${state.get('entry_price', 0):.2f}")
    lines.append("")
    if blocking:
        lines.append("🚨 *Issues:*")
        for f in blocking:
            lines.append(f"  • {f}")
    else:
        lines.append("✓ Log: clean since fix (no crashes, no re-entry attempts)")
        lines.append("✓ State: $500C tracked, no pending_entry, cycle locked")
        lines.append("✓ IBKR: position reconciled with state")
    if info:
        lines.append("")
        lines.append("ℹ️ *Info:*")
        for f in info:
            lines.append(f"  • {f}")

    msg = "\n".join(lines)
    print(msg)
    try:
        telegram.send(msg)
    except Exception as e:
        print(f"[ERROR] Telegram send failed: {e}", file=sys.stderr)

    # Self-unload — one-shot LaunchAgent
    try:
        subprocess.run(["launchctl", "unload", str(PLIST)], check=False, timeout=10)
    except Exception as e:
        print(f"[WARN] self-unload failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
