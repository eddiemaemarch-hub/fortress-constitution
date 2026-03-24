"""QuantConnect — Cloud Backtesting & Algorithm Management for Rudy v2.0
Uses QC REST API for backtesting, project management, and live deployment.
"""
import os
import sys
import json
import requests
from hashlib import sha256
from time import time
from base64 import b64encode
from datetime import datetime

LOG_DIR = os.path.expanduser("~/rudy/logs")
os.makedirs(LOG_DIR, exist_ok=True)

QC_USER_ID = os.environ.get("QC_USER_ID", "")
QC_API_TOKEN = os.environ.get("QC_API_TOKEN", "")
QC_BASE = "https://www.quantconnect.com/api/v2"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[QC {ts}] {msg}")
    with open(f"{LOG_DIR}/quantconnect.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def _auth_headers():
    """Generate authenticated headers for QC API."""
    timestamp = str(int(time()))
    hashed = sha256(f"{QC_API_TOKEN}:{timestamp}".encode()).hexdigest()
    auth = b64encode(f"{QC_USER_ID}:{hashed}".encode()).decode()
    return {
        "Authorization": f"Basic {auth}",
        "Timestamp": timestamp,
        "Content-Type": "application/json",
    }


def _post(endpoint, data=None):
    """Make authenticated POST request to QC API."""
    url = f"{QC_BASE}/{endpoint}"
    try:
        r = requests.post(url, headers=_auth_headers(), json=data or {}, timeout=30)
        return r.json()
    except Exception as e:
        log(f"API error: {e}")
        return {"success": False, "error": str(e)}


def _get(endpoint, params=None):
    """Make authenticated GET request to QC API."""
    url = f"{QC_BASE}/{endpoint}"
    try:
        r = requests.get(url, headers=_auth_headers(), params=params or {}, timeout=30)
        return r.json()
    except Exception as e:
        log(f"API error: {e}")
        return {"success": False, "error": str(e)}


# === AUTHENTICATION ===

def authenticate():
    """Test API authentication."""
    result = _post("authenticate")
    if result.get("success"):
        log("Authentication successful")
    else:
        log(f"Authentication failed: {result}")
    return result


# === PROJECT MANAGEMENT ===

def list_projects():
    """List all projects."""
    result = _post("projects/read")
    if result.get("success"):
        projects = result.get("projects", [])
        log(f"Found {len(projects)} projects")
        return projects
    return []


def create_project(name, language="Py"):
    """Create a new project. Language: 'Py' or 'C#'."""
    result = _post("projects/create", {"name": name, "language": language})
    if result.get("success"):
        project_id = result.get("projects", [{}])[0].get("projectId")
        log(f"Created project: {name} (ID: {project_id})")
        return result
    log(f"Create project failed: {result}")
    return result


def add_file(project_id, filename, content):
    """Add or update a file in a project."""
    result = _post("files/create", {
        "projectId": project_id,
        "name": filename,
        "content": content,
    })
    if not result.get("success"):
        # Try update instead
        result = _post("files/update", {
            "projectId": project_id,
            "name": filename,
            "content": content,
        })
    log(f"File {'added' if result.get('success') else 'failed'}: {filename}")
    return result


# === COMPILATION ===

def compile_project(project_id):
    """Compile a project."""
    result = _post("compile/create", {"projectId": project_id})
    if result.get("success"):
        compile_id = result.get("compileId", "")
        state = result.get("state", "")
        log(f"Compile started: {compile_id} ({state})")
        return result
    log(f"Compile failed: {result}")
    return result


# === BACKTESTING ===

def create_backtest(project_id, compile_id, name="Rudy Backtest"):
    """Create and run a backtest."""
    result = _post("backtests/create", {
        "projectId": project_id,
        "compileId": compile_id,
        "backtestName": name,
    })
    if result.get("success"):
        backtest_id = result.get("backtestId", "")
        log(f"Backtest started: {name} (ID: {backtest_id})")
        return result
    log(f"Backtest failed: {result}")
    return result


def read_backtest(project_id, backtest_id):
    """Read backtest results."""
    result = _post("backtests/read", {
        "projectId": project_id,
        "backtestId": backtest_id,
    })
    return result


def list_backtests(project_id):
    """List all backtests for a project."""
    result = _post("backtests/read", {"projectId": project_id})
    return result


def format_backtest_results(result):
    """Format backtest results for display."""
    if not result.get("success"):
        return f"Backtest error: {result.get('errors', result.get('error', 'Unknown'))}"

    bt = result.get("backtest", result)
    stats = bt.get("statistics", {})

    lines = [f"**Backtest: {bt.get('name', 'Unknown')}**\n"]

    stat_labels = {
        "Total Trades": "Total Trades",
        "Win Rate": "Win Rate",
        "Net Profit": "Net Profit",
        "Sharpe Ratio": "Sharpe Ratio",
        "Drawdown": "Max Drawdown",
        "Return": "Total Return",
        "Compounding Annual Return": "Annual Return",
        "Profit-Loss Ratio": "Profit/Loss Ratio",
    }

    for key, label in stat_labels.items():
        for stat_key, stat_val in stats.items():
            if key.lower() in stat_key.lower():
                lines.append(f"{label}: {stat_val}")
                break

    if not stats:
        lines.append("Status: " + bt.get("status", "Running..."))
        progress = bt.get("progress", 0)
        if progress:
            lines.append(f"Progress: {progress}%")

    return "\n".join(lines)


# === LIVE TRADING ===

def deploy_live(project_id, compile_id, node_id, brokerage_data=None,
                version_id="-1", data_providers=None):
    """Deploy a live algorithm to IBKR via QuantConnect.

    Args:
        project_id: QC project ID
        compile_id: Compile ID from successful compilation
        node_id: Live node ID (from your QC subscription)
        brokerage_data: Dict with IBKR brokerage settings. Example:
            {
                "id": "InteractiveBrokersBrokerage",
                "user": "<IBKR_USERNAME>",
                "password": "<IBKR_PASSWORD>",
                "account": "<IBKR_ACCOUNT_ID>",  # e.g. "DUA724990" for paper
                "environment": "paper",  # "paper" or "live"
            }
        version_id: Algorithm version ("-1" = latest)
        data_providers: Dict of data provider settings (default: QuantConnect)
    """
    if brokerage_data is None:
        brokerage_data = {}
    if data_providers is None:
        data_providers = {"QuantConnectBrokerage": {"id": "QuantConnectBrokerage"}}

    payload = {
        "projectId": project_id,
        "compileId": compile_id,
        "nodeId": node_id,
        "brokerage": brokerage_data,
        "versionId": version_id,
        "dataProviders": data_providers,
    }
    result = _post("live/create", payload)
    if result.get("success"):
        log(f"Live deployment started for project {project_id}")
    else:
        log(f"Live deployment failed: {result}")
    return result


def read_live(project_id):
    """Read the status of a live algorithm."""
    result = _post("live/read", {"projectId": project_id})
    if result.get("success"):
        live = result.get("live", {})
        status = live.get("status", "Unknown")
        log(f"Live algo status: {status}")
    return result


def stop_live(project_id):
    """Stop a running live algorithm."""
    result = _post("live/update/stop", {"projectId": project_id})
    if result.get("success"):
        log(f"Live algo stopped for project {project_id}")
    else:
        log(f"Stop live failed: {result}")
    return result


def liquidate_live(project_id):
    """Liquidate all positions in a live algorithm."""
    result = _post("live/update/liquidate", {"projectId": project_id})
    if result.get("success"):
        log(f"Live algo liquidated for project {project_id}")
    else:
        log(f"Liquidate failed: {result}")
    return result


def list_live():
    """List all live algorithms."""
    result = _post("live/read", {
        "status": "Running",
        "start": 0,
        "end": 50,
    })
    if result.get("success"):
        algos = result.get("live", [])
        log(f"Found {len(algos)} live algorithms")
        return algos
    return []


def get_org_id():
    """Get the organization ID for this account."""
    result = _get("account/read")
    if result.get("success"):
        org_id = result.get("organizationId", "")
        log(f"Organization ID: {org_id}")
        return org_id
    log(f"Failed to get org ID: {result}")
    return ""


def list_nodes(org_id=None):
    """List available live nodes (required for deployment)."""
    if not org_id:
        org_id = get_org_id()
    result = _post("nodes/read", {"organizationId": org_id})
    if result.get("success"):
        live_nodes = result.get("live", [])
        log(f"Found {len(live_nodes)} live nodes")
        return result
    log(f"Node list failed: {result}")
    return {}


# === FULL WORKFLOW ===

def run_backtest(name, code, language="Py"):
    """Full workflow: create project → add code → compile → backtest."""
    log(f"Starting full backtest workflow: {name}")

    # Create project
    proj_result = create_project(name)
    if not proj_result.get("success"):
        return f"Failed to create project: {proj_result}"

    project_id = proj_result.get("projects", [{}])[0].get("projectId")

    # Add code
    filename = "main.py" if language == "Py" else "Main.cs"
    add_file(project_id, filename, code)

    # Compile
    compile_result = compile_project(project_id)
    if not compile_result.get("success"):
        errors = compile_result.get("errors", [])
        return f"Compilation failed:\n" + "\n".join(str(e) for e in errors)

    compile_id = compile_result.get("compileId", "")

    # Wait for compilation if needed
    state = compile_result.get("state", "")
    if state != "BuildSuccess":
        import time as t
        for _ in range(10):
            t.sleep(3)
            check = _post("compile/read", {"projectId": project_id, "compileId": compile_id})
            state = check.get("state", "")
            if state == "BuildSuccess":
                break
            elif state == "BuildError":
                return f"Build error:\n{check.get('errors', 'Unknown')}"

    # Run backtest
    bt_result = create_backtest(project_id, compile_id, name)
    if not bt_result.get("success"):
        return f"Backtest failed: {bt_result}"

    backtest_id = bt_result.get("backtestId", "")

    # Poll for results
    import time as t
    for _ in range(20):
        t.sleep(5)
        results = read_backtest(project_id, backtest_id)
        bt = results.get("backtest", {})
        if bt.get("completed"):
            return format_backtest_results(results)

    return f"Backtest still running. Project ID: {project_id}, Backtest ID: {backtest_id}\nCheck results later with /qc results {project_id} {backtest_id}"


# === STRATEGY TEMPLATES ===

MSTR_MOMENTUM = '''from AlgorithmImports import *

class MSTRMomentum(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2023, 1, 1)
        self.set_end_date(2025, 12, 31)
        self.set_cash(100000)

        self.mstr = self.add_equity("MSTR", Resolution.DAILY).symbol
        self.rsi = self.rsi(self.mstr, 14, MovingAverageType.WILDERS, Resolution.DAILY)
        self.sma50 = self.sma(self.mstr, 50, Resolution.DAILY)
        self.sma200 = self.sma(self.mstr, 200, Resolution.DAILY)

    def on_data(self, data):
        if not self.rsi.is_ready or not self.sma200.is_ready:
            return

        if not self.portfolio.invested:
            if self.rsi.current.value < 30 and self.sma50.current.value > self.sma200.current.value:
                self.set_holdings(self.mstr, 1.0)
                self.log(f"BUY MSTR @ {data[self.mstr].close}")
        else:
            if self.rsi.current.value > 70:
                self.liquidate()
                self.log(f"SELL MSTR @ {data[self.mstr].close}")
'''

DIAGONAL_SPREAD = '''from AlgorithmImports import *

class DiagonalSpread(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2023, 1, 1)
        self.set_end_date(2025, 12, 31)
        self.set_cash(10000)

        equity = self.add_equity("AAPL", Resolution.DAILY)
        equity.set_data_normalization_mode(DataNormalizationMode.RAW)
        self.symbol = equity.symbol

        self.add_option(self.symbol, Resolution.DAILY)

        self.rsi = self.rsi(self.symbol, 14, MovingAverageType.WILDERS, Resolution.DAILY)
        self.ema50 = self.ema(self.symbol, 50, Resolution.DAILY)
        self.ema200 = self.ema(self.symbol, 200, Resolution.DAILY)

    def on_data(self, data):
        if not self.rsi.is_ready or not self.ema200.is_ready:
            return

        if not self.portfolio.invested:
            if (self.ema50.current.value > self.ema200.current.value and
                40 <= self.rsi.current.value <= 50):
                self.set_holdings(self.symbol, 0.5)
                self.log(f"BUY {self.symbol} @ {data[self.symbol].close}")
        else:
            if self.rsi.current.value > 75 or self.portfolio.total_unrealized_profit < -250:
                self.liquidate()
                self.log(f"EXIT @ {data[self.symbol].close}")
'''


def get_template(name):
    """Get a strategy template by name."""
    templates = {
        "mstr_momentum": MSTR_MOMENTUM,
        "diagonal": DIAGONAL_SPREAD,
    }
    return templates.get(name.lower())


if __name__ == "__main__":
    if not QC_USER_ID:
        print("Set QC_USER_ID environment variable (find it at quantconnect.com/account)")
        sys.exit(1)

    result = authenticate()
    print(json.dumps(result, indent=2))

    if result.get("success"):
        projects = list_projects()
        print(f"\n{len(projects)} projects found")
        for p in projects[:5]:
            print(f"  {p.get('name')} (ID: {p.get('projectId')})")
