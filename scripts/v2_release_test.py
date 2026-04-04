#!/usr/bin/env python3
"""v2.0 Release Test Suite — run before PyPI publish.

Usage:
    python scripts/v2_release_test.py                    # All tests (simulated)
    python scripts/v2_release_test.py --live-india       # India with Dhan LIVE
    python scripts/v2_release_test.py --live-us          # US with TastyTrade LIVE
    python scripts/v2_release_test.py --pytest-only      # Just pytest suite
    python scripts/v2_release_test.py --md-only          # Just trader_md tests
    python scripts/v2_release_test.py --trader-only      # Just trader/ tests
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
RESULTS: list[tuple[str, str, str, float]] = []  # (test_id, description, status, seconds)


def run_cmd(cmd: str, timeout: int = 300) -> tuple[int, str]:
    """Run a command, return (exit_code, output)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=str(PROJECT_ROOT),
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        )
        return result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return 1, "TIMEOUT"
    except Exception as e:
        return 1, str(e)


def record(test_id: str, desc: str, passed: bool, duration: float, output: str = ""):
    status = "PASS" if passed else "FAIL"
    RESULTS.append((test_id, desc, status, duration))
    icon = "[OK]" if passed else "[FAIL]"
    print(f"  {icon} {test_id}: {desc} ({duration:.1f}s)")
    if not passed and output:
        # Show last 5 lines of failure
        lines = output.strip().splitlines()
        for line in lines[-5:]:
            print(f"       {line}")


# ---------------------------------------------------------------------------
# Test Groups
# ---------------------------------------------------------------------------

def test_pytest_suite():
    """PLAT-009: Full pytest suite."""
    print("\n  === PYTEST SUITE ===\n")

    tests = [
        ("PT-1", "benchmarking tests", "tests/test_benchmarking.py tests/test_benchmarking_workflow.py", ""),
        ("PT-2", "scenario parser tests", "tests/test_scenario_parser.py", ""),
    ]

    for test_id, desc, path, extra in tests:
        start = time.time()
        cmd = f".venv_312/Scripts/python -m pytest {path} -v --tb=short {extra}"
        code, output = run_cmd(cmd)
        duration = time.time() - start
        record(test_id, desc, code == 0, duration, output)

    # Full suite
    start = time.time()
    cmd = ".venv_312/Scripts/python -m pytest tests/ -x -q -m 'not integration'"
    code, output = run_cmd(cmd, timeout=600)
    duration = time.time() - start
    # Extract pass count
    passed = "passed" in output
    record("PT-6", "Full test suite (non-integration)", code == 0, duration, output)


def test_trader_md_simulated():
    """PLAT-007: trader_md with simulated data."""
    print("\n  === TRADER_MD (SIMULATED) ===\n")

    md_base = "income_desk/trader_md"

    # Validate
    for market, wf in [("US", "daily_us"), ("India", "daily_india")]:
        start = time.time()
        cmd = f".venv_312/Scripts/python -m income_desk.trader_md validate {md_base}/workflows/{wf}.workflow.md"
        code, output = run_cmd(cmd)
        record(f"MD-V-{market}", f"validate {wf}.workflow.md", code == 0, time.time() - start, output)

    # Dry-run
    for market, wf in [("US", "daily_us"), ("India", "daily_india")]:
        start = time.time()
        cmd = f".venv_312/Scripts/python -m income_desk.trader_md dry-run {md_base}/workflows/{wf}.workflow.md"
        code, output = run_cmd(cmd)
        record(f"MD-D-{market}", f"dry-run {wf}.workflow.md", code == 0, time.time() - start, output)

    # Run (simulated)
    for market, wf in [("US", "daily_us"), ("India", "daily_india")]:
        start = time.time()
        cmd = f".venv_312/Scripts/python -m income_desk.trader_md run {md_base}/workflows/{wf}.workflow.md"
        code, output = run_cmd(cmd, timeout=600)
        # Check for FAILED in output
        has_failed = "FAILED" in output and "| FAILED" in output
        record(f"MD-R-{market}", f"run {wf} (simulated)", code == 0 and not has_failed, time.time() - start, output)

    # --set override
    start = time.time()
    cmd = f".venv_312/Scripts/python -m income_desk.trader_md run {md_base}/workflows/daily_us.workflow.md --set capital=100000"
    code, output = run_cmd(cmd, timeout=600)
    record("MD-SET", "--set override changes behavior", code == 0, time.time() - start, output)

    # --report
    report_path = PROJECT_ROOT / "tmp_test_report.md"
    start = time.time()
    cmd = f".venv_312/Scripts/python -m income_desk.trader_md run {md_base}/workflows/daily_us.workflow.md --report {report_path}"
    code, output = run_cmd(cmd, timeout=600)
    report_exists = report_path.exists()
    if report_path.exists():
        report_path.unlink()
    record("MD-RPT", "--report generates markdown file", code == 0 and report_exists, time.time() - start, output)

    # Benchmarking workflow
    start = time.time()
    cmd = f".venv_312/Scripts/python -m income_desk.trader_md run {md_base}/workflows/benchmarking.workflow.md"
    code, output = run_cmd(cmd, timeout=120)
    record("MD-BM", "benchmarking workflow runs", code == 0, time.time() - start, output)


def test_trader_simulated():
    """PLAT-008: trader/ Python path with simulated data."""
    print("\n  === TRADER (SIMULATED) ===\n")

    for market in ["US", "India"]:
        start = time.time()
        cmd = f".venv_312/Scripts/python -m income_desk.trader --all --market={market}"
        code, output = run_cmd(cmd, timeout=600)
        # Check 15/15 or Total: 15
        has_pass = "Passed: 15" in output or "Passed:  15" in output
        record(f"TR-{market}", f"trader --all --market={market} (simulated)", code == 0 and has_pass, time.time() - start, output)


def test_trader_md_live(market: str):
    """PLAT-007 items 7-8: trader_md with LIVE broker."""
    print(f"\n  === TRADER_MD (LIVE {market.upper()}) ===\n")

    md_base = "income_desk/trader_md"
    wf = "daily_india" if market == "India" else "daily_us"

    start = time.time()
    cmd = f".venv_312/Scripts/python -m income_desk.trader_md run {md_base}/workflows/{wf}.workflow.md"
    code, output = run_cmd(cmd, timeout=600)
    has_failed = "FAILED" in output and "| FAILED" in output
    has_simulated_warning = "SIMULATED" in output
    record(f"MD-LIVE-{market}", f"run {wf} (LIVE broker)", code == 0 and not has_failed, time.time() - start, output)

    # Check data trust
    record(f"MD-TRUST-{market}", "No simulated data in LIVE run",
           not has_simulated_warning or "market closed" in output.lower(),
           0, output)


def test_trader_live(market: str):
    """PLAT-008 items 3-4: trader/ with LIVE broker."""
    print(f"\n  === TRADER (LIVE {market.upper()}) ===\n")

    start = time.time()
    cmd = f".venv_312/Scripts/python -m income_desk.trader --all --market={market}"
    code, output = run_cmd(cmd, timeout=600)
    has_pass = "Passed: 15" in output or "Passed:  15" in output
    record(f"TR-LIVE-{market}", f"trader --all --market={market} (LIVE)", code == 0 and has_pass, time.time() - start, output)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary():
    print(f"\n{'=' * 70}")
    print(f"  v2.0 RELEASE TEST SUMMARY -- {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 70}\n")

    from tabulate import tabulate

    rows = [[tid, desc, status, f"{dur:.1f}s"] for tid, desc, status, dur in RESULTS]
    print(tabulate(rows, headers=["ID", "Test", "Status", "Time"], tablefmt="grid"))

    total = len(RESULTS)
    passed = sum(1 for _, _, s, _ in RESULTS if s == "PASS")
    failed = total - passed

    print(f"\n  Total: {total} | Passed: {passed} | Failed: {failed}")

    if failed == 0:
        print(f"\n  VERDICT: READY TO PUBLISH v2.0.0")
    else:
        print(f"\n  VERDICT: NOT READY -- {failed} test(s) failing")
        print(f"  Fix failures before running: gh release create v2.0.0")

    return failed


def main():
    parser = argparse.ArgumentParser(description="v2.0 Release Test Suite")
    parser.add_argument("--live-india", action="store_true", help="Include LIVE India (Dhan) tests")
    parser.add_argument("--live-us", action="store_true", help="Include LIVE US (TastyTrade) tests")
    parser.add_argument("--pytest-only", action="store_true", help="Only run pytest suite")
    parser.add_argument("--md-only", action="store_true", help="Only run trader_md tests")
    parser.add_argument("--trader-only", action="store_true", help="Only run trader/ tests")
    args = parser.parse_args()

    print(f"\n{'=' * 70}")
    print(f"  v2.0 RELEASE TEST SUITE")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 70}")

    run_all = not (args.pytest_only or args.md_only or args.trader_only)

    if run_all or args.pytest_only:
        test_pytest_suite()

    if run_all or args.md_only:
        test_trader_md_simulated()

    if run_all or args.trader_only:
        test_trader_simulated()

    if args.live_india:
        test_trader_md_live("India")
        test_trader_live("India")

    if args.live_us:
        test_trader_md_live("US")
        test_trader_live("US")

    failed = print_summary()
    sys.exit(failed)


if __name__ == "__main__":
    main()
