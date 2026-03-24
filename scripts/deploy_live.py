#!/usr/bin/env python3
"""Rudy v2.8 Dynamic Blend — Deploy MSTR Cycle-Low LEAP to QuantConnect Live via IBKR

Usage:
    # Paper trading (default):
    python3 deploy_live.py --mode paper

    # Live trading (requires double confirmation):
    python3 deploy_live.py --mode live --confirm-live

    # Check status of running algo:
    python3 deploy_live.py --status

    # Stop running algo:
    python3 deploy_live.py --stop

    # Liquidate all positions:
    python3 deploy_live.py --liquidate

Prerequisites:
    1. IBKR account connected to QC at: quantconnect.com/terminal/#organization/account
    2. QC live node available (paid subscription)
    3. IBKR TWS or Gateway running and connected
    4. Environment vars: QC_USER_ID, QC_API_TOKEN, IBKR_ACCOUNT, IBKR_USERNAME, IBKR_PASSWORD

IBKR Connection Notes:
    - Do NOT call SetBrokerageModel in live mode — it causes QC to sync IBKR order history,
      which crashes on TRAIL LIMIT orders that QC can't parse.
    - QC connects to IBKR at the infrastructure level (deploy config), not in algo code.
    - The default model still routes orders through IBKR correctly.
"""

import os
import sys
import json
import argparse
import time

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quantconnect import (
    authenticate, create_project, add_file, compile_project,
    deploy_live, read_live, stop_live, liquidate_live,
    list_nodes, list_live, get_org_id, log, _post,
)

ALGO_PATH = os.path.expanduser("~/rudy/quantconnect/MSTRCycleLowLeap_v28_dynamic.py")
STATE_FILE = os.path.expanduser("~/rudy/data/live_deployment.json")
os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)
    log(f"Deployment state saved to {STATE_FILE}")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def get_ibkr_brokerage(mode="paper"):
    """Build IBKR brokerage config for QC deployment."""
    account = os.environ.get("IBKR_ACCOUNT", "")
    username = os.environ.get("IBKR_USERNAME", "")
    password = os.environ.get("IBKR_PASSWORD", "")

    if not all([account, username, password]):
        print("\nERROR: Missing IBKR credentials. Set these environment variables:")
        print("  export IBKR_ACCOUNT=DUA724990      # Your IBKR account ID")
        print("  export IBKR_USERNAME=your_username  # IBKR login username")
        print("  export IBKR_PASSWORD=your_password  # IBKR login password")
        sys.exit(1)

    return {
        "id": "InteractiveBrokersBrokerage",
        "user": username,
        "password": password,
        "account": account,
        "environment": mode,  # "paper" or "live"
        "ib-user-name": username,
        "ib-account": account,
        "ib-password": password,
        "ib-trading-mode": mode,
        "ib-weekly-restart-utc-time": "22:00:00",
    }


def cmd_deploy(args):
    """Deploy the algo to QC live trading."""
    mode = args.mode

    if mode == "live" and not args.confirm_live:
        print("\n" + "=" * 60)
        print("  LIVE TRADING MODE — REAL MONEY AT RISK")
        print("=" * 60)
        print("\nTo deploy with real money, add --confirm-live flag:")
        print("  python3 deploy_live.py --mode live --confirm-live")
        print("\nConsider paper trading first:")
        print("  python3 deploy_live.py --mode paper")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Rudy v2.8 — Deploying to IBKR ({mode.upper()})")
    print(f"{'='*60}\n")

    # 1. Authenticate
    print("[1/6] Authenticating with QuantConnect...")
    auth = authenticate()
    if not auth.get("success"):
        print(f"  FAILED: {auth}")
        sys.exit(1)
    print("  OK")

    # 2. Check for available live nodes
    print("[2/6] Checking available live nodes...")
    org_id = get_org_id()
    nodes = list_nodes(org_id)
    live_nodes = nodes.get("live", [])
    if not live_nodes:
        print("  ERROR: No live nodes available.")
        print("  You need a QC subscription with a live trading node.")
        print("  Visit: quantconnect.com/pricing")
        sys.exit(1)

    # Find a free node
    free_node = None
    for node in live_nodes:
        if not node.get("busy", True):
            free_node = node
            break

    if not free_node:
        print("  ERROR: All live nodes are busy.")
        print("  Stop an existing algo first: python3 deploy_live.py --stop")
        sys.exit(1)

    node_id = free_node.get("id", "")
    print(f"  OK — Using node: {free_node.get('name', node_id)} ({node_id})")

    # 3. Create project with algo code
    print("[3/6] Creating QC project...")
    proj_name = f"Rudy-v2.8-MSTR-{mode.upper()}-{int(time.time())}"
    proj_result = create_project(proj_name)
    if not proj_result.get("success"):
        print(f"  FAILED: {proj_result}")
        sys.exit(1)

    project_id = proj_result.get("projects", [{}])[0].get("projectId")
    print(f"  OK — Project: {proj_name} (ID: {project_id})")

    # 4. Upload algo code
    print("[4/6] Uploading MSTRCycleLowLeap_v28_dynamic.py...")
    with open(ALGO_PATH) as f:
        code = f.read()

    add_file(project_id, "main.py", code)
    print("  OK")

    # 5. Compile
    print("[5/6] Compiling...")
    compile_result = compile_project(project_id)
    if not compile_result.get("success"):
        errors = compile_result.get("errors", [])
        print(f"  FAILED: {errors}")
        sys.exit(1)

    compile_id = compile_result.get("compileId", "")
    state = compile_result.get("state", "")

    # Wait for compilation
    if state != "BuildSuccess":
        for i in range(15):
            time.sleep(3)
            check = _post("compile/read", {
                "projectId": project_id,
                "compileId": compile_id,
            })
            state = check.get("state", "")
            if state == "BuildSuccess":
                break
            elif state == "BuildError":
                print(f"  BUILD ERROR: {check.get('errors', 'Unknown')}")
                sys.exit(1)
            print(f"  Compiling... ({state})")

    print(f"  OK — Compile ID: {compile_id}")

    # 6. Deploy live
    print(f"[6/6] Deploying to IBKR ({mode})...")
    brokerage = get_ibkr_brokerage(mode)

    result = deploy_live(
        project_id=project_id,
        compile_id=compile_id,
        node_id=node_id,
        brokerage_data=brokerage,
    )

    if result.get("success"):
        print(f"\n{'='*60}")
        print(f"  DEPLOYED SUCCESSFULLY — {mode.upper()} MODE")
        print(f"{'='*60}")
        print(f"  Project ID: {project_id}")
        print(f"  Node:       {node_id}")
        print(f"  Account:    {brokerage['account']}")
        print(f"  Mode:       {mode}")
        print(f"\n  Monitor at: quantconnect.com/terminal/{project_id}#live")
        print(f"  Stop with:  python3 deploy_live.py --stop")

        # Save state
        save_state({
            "project_id": project_id,
            "node_id": node_id,
            "mode": mode,
            "account": brokerage["account"],
            "deployed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "running",
        })
    else:
        print(f"\n  DEPLOYMENT FAILED: {result}")
        sys.exit(1)


def cmd_status(args):
    """Check status of live algo."""
    state = load_state()
    if not state.get("project_id"):
        print("No deployment found. Deploy first with: python3 deploy_live.py --mode paper")
        return

    project_id = state["project_id"]
    print(f"Checking project {project_id}...")

    result = read_live(project_id)
    if result.get("success"):
        live = result.get("live", {})
        print(f"\n  Status:     {live.get('status', 'Unknown')}")
        print(f"  Mode:       {state.get('mode', 'Unknown')}")
        print(f"  Account:    {state.get('account', 'Unknown')}")
        print(f"  Deployed:   {state.get('deployed_at', 'Unknown')}")

        # Show portfolio if available
        results = live.get("results", {})
        if results:
            stats = results.get("Statistics", {})
            for key in ["Net Profit", "Total Trades", "Win Rate", "Drawdown"]:
                for sk, sv in stats.items():
                    if key.lower() in sk.lower():
                        print(f"  {key}: {sv}")
                        break
    else:
        print(f"  Error: {result}")


def cmd_stop(args):
    """Stop running live algo."""
    state = load_state()
    if not state.get("project_id"):
        print("No deployment found.")
        return

    project_id = state["project_id"]
    print(f"Stopping project {project_id}...")

    result = stop_live(project_id)
    if result.get("success"):
        print("  Algo stopped successfully.")
        state["status"] = "stopped"
        save_state(state)
    else:
        print(f"  Error: {result}")


def cmd_liquidate(args):
    """Liquidate all positions."""
    state = load_state()
    if not state.get("project_id"):
        print("No deployment found.")
        return

    project_id = state["project_id"]

    print(f"\n  WARNING: This will liquidate ALL positions in project {project_id}")
    confirm = input("  Type 'LIQUIDATE' to confirm: ")
    if confirm != "LIQUIDATE":
        print("  Cancelled.")
        return

    result = liquidate_live(project_id)
    if result.get("success"):
        print("  All positions liquidated.")
    else:
        print(f"  Error: {result}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rudy v2.8 — QC Live Deployment to IBKR")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper",
                        help="Trading mode (default: paper)")
    parser.add_argument("--confirm-live", action="store_true",
                        help="Confirm live trading with real money")
    parser.add_argument("--status", action="store_true",
                        help="Check status of running algo")
    parser.add_argument("--stop", action="store_true",
                        help="Stop running algo")
    parser.add_argument("--liquidate", action="store_true",
                        help="Liquidate all positions")

    args = parser.parse_args()

    # Dispatch command
    if args.status:
        cmd_status(args)
    elif args.stop:
        cmd_stop(args)
    elif args.liquidate:
        cmd_liquidate(args)
    else:
        cmd_deploy(args)
