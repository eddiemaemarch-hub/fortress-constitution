"""Deployer — Rudy v2.0
Manages deployment state for each trading system.
Controls whether a system trades on paper (7496) or live (7496).
Constitution v43.0: Must pass 6-month paper test before going live.
"""
import os
import json
from datetime import datetime

DATA_DIR = os.path.expanduser("~/rudy/data")
DEPLOY_FILE = os.path.join(DATA_DIR, "deployment.json")
PAPER_PORT = 7496
LIVE_PORT = 7496

SYSTEMS = {
    "1": "MSTR Lottery",
    "2": "Conservative Diagonal",
    "3": "Energy Momentum",
    "4": "Short Squeeze",
    "5": "Breakout Momentum",
    "6": "Metals Momentum",
    "7": "SpaceX IPO",
    "8": "10X Moonshot",
    "9": "SCHD Income PMCC",
    "10": "SPY PMCC",
    "11": "QQQ Growth Collar",
    "12": "TQQQ Momentum",
}


def load_deployment():
    if os.path.exists(DEPLOY_FILE):
        with open(DEPLOY_FILE) as f:
            return json.load(f)
    # Default: everything on paper
    deploy = {}
    for sid, name in SYSTEMS.items():
        deploy[sid] = {
            "name": name,
            "mode": "paper",
            "port": PAPER_PORT,
            "deployed_at": None,
            "approved_by": None,
        }
    save_deployment(deploy)
    return deploy


def save_deployment(deploy):
    with open(DEPLOY_FILE, "w") as f:
        json.dump(deploy, f, indent=2)


def get_port(system_id):
    """Get the IBKR port for a given system. Used by trader scripts."""
    deploy = load_deployment()
    sid = str(system_id)
    if sid in deploy:
        return deploy[sid].get("port", PAPER_PORT)
    return PAPER_PORT


def get_mode(system_id):
    """Get mode (paper/live) for a system."""
    deploy = load_deployment()
    sid = str(system_id)
    if sid in deploy:
        return deploy[sid].get("mode", "paper")
    return "paper"


def check_deploy_ready(system_id):
    """Check if a system is eligible for live deployment.
    Returns (ready, reasons).
    """
    sid = str(system_id)
    reasons = []

    # Check 1: Paper test must be passed
    paper_results_file = os.path.join(DATA_DIR, "paper_test_results.json")
    if os.path.exists(paper_results_file):
        with open(paper_results_file) as f:
            results = json.load(f)
        if not results.get("all_passed"):
            reasons.append("Paper execution test not passed")
    else:
        reasons.append("No paper test results found")

    # Check 2: Must have at least 30 trading days of data
    paper_track_file = os.path.join(DATA_DIR, "paper_track.json")
    if os.path.exists(paper_track_file):
        with open(paper_track_file) as f:
            track = json.load(f)
        trading_days = len(track.get("days", {}))
        if trading_days < 30:
            reasons.append(f"Only {trading_days} trading days (need 30 minimum)")
    else:
        reasons.append("No paper trading history")

    # Check 3: System must have position history
    pos_file = os.path.join(DATA_DIR, f"trader{sid}_positions.json")
    if not os.path.exists(pos_file):
        reasons.append(f"System {sid} has no position history")

    # Check 4: Overall paper account must be profitable or near breakeven
    if os.path.exists(paper_track_file):
        with open(paper_track_file) as f:
            track = json.load(f)
        days = track.get("days", {})
        if days:
            dates = sorted(days.keys())
            latest = days[dates[-1]]
            total_pct = latest.get("total_pct", 0)
            if total_pct < -10:
                reasons.append(f"Paper account down {total_pct:.1f}% (max -10% for deployment)")

    ready = len(reasons) == 0
    return ready, reasons


def deploy_live(system_id, commander_approval=True):
    """Switch a system from paper to live trading.
    Returns (success, message).
    """
    sid = str(system_id)
    deploy = load_deployment()

    if sid not in deploy:
        return False, f"Unknown system {sid}"

    if deploy[sid]["mode"] == "live":
        return False, f"System {sid} already live"

    if not commander_approval:
        return False, "Commander approval required"

    # Run safety checks
    ready, reasons = check_deploy_ready(sid)
    if not ready:
        return False, "Not ready: " + "; ".join(reasons)

    # Deploy
    deploy[sid]["mode"] = "live"
    deploy[sid]["port"] = LIVE_PORT
    deploy[sid]["deployed_at"] = datetime.now().isoformat()
    deploy[sid]["approved_by"] = "Commander"
    save_deployment(deploy)

    return True, f"System {sid} ({deploy[sid]['name']}) deployed LIVE on port {LIVE_PORT}"


def deploy_paper(system_id):
    """Switch a system back to paper trading."""
    sid = str(system_id)
    deploy = load_deployment()

    if sid not in deploy:
        return False, f"Unknown system {sid}"

    deploy[sid]["mode"] = "paper"
    deploy[sid]["port"] = PAPER_PORT
    deploy[sid]["deployed_at"] = None
    deploy[sid]["approved_by"] = None
    save_deployment(deploy)

    return True, f"System {sid} ({deploy[sid]['name']}) switched back to PAPER"


def get_status():
    """Get deployment status for all systems."""
    deploy = load_deployment()
    status = {}
    for sid, info in deploy.items():
        ready, reasons = check_deploy_ready(sid)
        status[sid] = {
            "name": info["name"],
            "mode": info["mode"],
            "port": info["port"],
            "deployed_at": info.get("deployed_at"),
            "ready_for_live": ready,
            "blockers": reasons if not ready else [],
        }
    return status
