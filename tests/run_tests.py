"""Phase 2 Test Runner — runs test suites with category flags.

Usage:
    python tests/run_tests.py --all --verbose       # Everything
    python tests/run_tests.py --unit --verbose       # Ladder + sim + edge
    python tests/run_tests.py --integration          # Breaker + mid-execution
    python tests/run_tests.py --fast                 # Quick smoke test (ladder + breaker only)
    python tests/run_tests.py --sim                  # Random walk + simulated market
    python tests/run_tests.py --edge                 # Edge cases only
    python tests/run_tests.py --mid-execution        # Mid-execution kill switch only
    python tests/run_tests.py --core                 # Original ladder + breaker (backward compat)
    python tests/run_tests.py --ladder               # Original ladder only
    python tests/run_tests.py --breaker              # Original breaker only
    python tests/run_tests.py --tv                    # TradingView alert tests only
"""
import sys
import os
import argparse
import subprocess
import time

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Test suite definitions: (name, script, category)
SUITES = [
    ("Ladder Cycle",          "test_ladder_cycle.py",          ["unit", "core", "fast", "ladder"]),
    ("Breaker Integration",   "test_breaker_integration.py",   ["integration", "core", "fast", "breaker"]),
    ("Random Walk Ladder",    "test_random_walk_ladder.py",    ["unit", "sim"]),
    ("Ladder Edge Cases",     "test_ladder_edge_cases.py",     ["unit", "edge"]),
    ("Breaker Mid-Execution", "test_breaker_mid_execution.py", ["integration", "mid-execution"]),
    ("TradingView Alerts",    "test_tradingview_alerts.py",    ["unit", "tv"]),
    ("IBKR Automation",       "test_ibkr_automation.py",       ["unit", "ibkr"]),
]


def run_test(name, script, verbose=False):
    script_path = os.path.join(TESTS_DIR, script)
    if not os.path.exists(script_path):
        print(f"\n  SKIP: {script} not found")
        return -1

    env = os.environ.copy()
    if verbose:
        env["VERBOSE"] = "1"

    cmd = [sys.executable, script_path]
    if verbose:
        cmd.append("--verbose")

    start = time.time()
    result = subprocess.run(cmd, capture_output=not verbose, text=True, env=env)
    elapsed = time.time() - start

    if not verbose and result.stdout:
        lines = result.stdout.strip().split("\n")
        for line in lines:
            if any(kw in line for kw in ["RESULTS:", "PASS", "FAIL", "PASSED", "FAILURES", "SKIP"]):
                print(f"  {line.strip()}")

    return result.returncode, elapsed


def main():
    parser = argparse.ArgumentParser(description="Phase 2 Test Runner")
    parser.add_argument("--all", action="store_true", help="Run all test suites")
    parser.add_argument("--unit", action="store_true", help="Ladder + sim + edge (no IBKR)")
    parser.add_argument("--integration", action="store_true", help="Breaker + mid-execution")
    parser.add_argument("--fast", action="store_true", help="Quick smoke: ladder + breaker only")
    parser.add_argument("--sim", action="store_true", help="Random walk + simulated market")
    parser.add_argument("--edge", action="store_true", help="Edge cases only")
    parser.add_argument("--mid-execution", action="store_true", dest="mid_execution", help="Mid-execution kill switch")
    parser.add_argument("--core", action="store_true", help="Original ladder + breaker (backward compat)")
    parser.add_argument("--ladder", action="store_true", help="Original ladder tests only")
    parser.add_argument("--breaker", action="store_true", help="Original breaker tests only")
    parser.add_argument("--tv", action="store_true", help="TradingView alert tests only")
    parser.add_argument("--ibkr", action="store_true", help="IBKR automation tests only")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show full test output")
    args = parser.parse_args()

    # Build set of categories to run
    categories = set()
    if args.all:
        categories = {"unit", "integration", "core", "fast", "sim", "edge", "mid-execution", "ladder", "breaker", "tv", "ibkr"}
    else:
        if args.unit:
            categories.add("unit")
        if args.integration:
            categories.add("integration")
        if args.fast:
            categories.add("fast")
        if args.sim:
            categories.add("sim")
        if args.edge:
            categories.add("edge")
        if args.mid_execution:
            categories.add("mid-execution")
        if args.core:
            categories.add("core")
        if args.ladder:
            categories.add("ladder")
        if args.breaker:
            categories.add("breaker")
        if args.tv:
            categories.add("tv")
        if args.ibkr:
            categories.add("ibkr")

    if not categories:
        categories = {"unit", "integration", "core", "fast", "sim", "edge", "mid-execution", "ladder", "breaker", "tv", "ibkr"}

    # Select suites that match any requested category
    selected = []
    seen_scripts = set()
    for name, script, suite_cats in SUITES:
        if any(c in categories for c in suite_cats) and script not in seen_scripts:
            selected.append((name, script))
            seen_scripts.add(script)

    if not selected:
        print("No test suites matched the selected categories.")
        sys.exit(1)

    print("=" * 60)
    print("RUDY v2.0 — TEST RUNNER")
    print(f"Suites: {len(selected)} | Categories: {', '.join(sorted(categories))}")
    print("=" * 60)

    results = {}
    total_start = time.time()

    for name, script in selected:
        print(f"\n{'─' * 60}")
        print(f"RUNNING: {name}")
        print(f"{'─' * 60}")

        code, elapsed = run_test(name, script, args.verbose)
        results[name] = (code, elapsed)

    total_elapsed = time.time() - total_start

    # Summary table
    print(f"\n{'=' * 60}")
    print("TEST RUNNER SUMMARY")
    print(f"{'=' * 60}")
    print(f"  {'Suite':<30} {'Status':>10} {'Time':>8}")
    print(f"  {'─' * 30} {'─' * 10} {'─' * 8}")

    all_passed = True
    for name, (code, elapsed) in results.items():
        if code == -1:
            status = "SKIPPED"
        elif code == 0:
            status = "PASSED"
        else:
            status = "FAILED"
            all_passed = False
        print(f"  {name:<30} {status:>10} {elapsed:>7.1f}s")

    print(f"  {'─' * 30} {'─' * 10} {'─' * 8}")
    print(f"  {'TOTAL':<30} {'':>10} {total_elapsed:>7.1f}s")

    if all_passed:
        print("\nALL TEST SUITES PASSED")
    else:
        print("\nSOME TESTS FAILED — review output above")
    print(f"{'=' * 60}")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
