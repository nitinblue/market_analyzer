#!/usr/bin/env python3
"""Daily live testing — run harness + pricing regression, save results.

Designed to run every trading day against live broker data.
Compares results with previous runs to track convergence.

Usage:
    python scripts/daily_test.py --market India    # During India hours (09:15-15:30 IST)
    python scripts/daily_test.py --market US        # During US hours (09:30-16:00 ET)
    python scripts/daily_test.py --market India --offline  # Use saved snapshot
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

RESULTS_DIR = Path(__file__).parent.parent / "docs" / "live_test_runs"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def run_harness(market: str) -> tuple[str, bool]:
    """Run the workflow harness and capture output."""
    print(f"\n{'=' * 60}")
    print(f"  STEP 1: WORKFLOW HARNESS — {market}")
    print(f"{'=' * 60}\n")

    result = subprocess.run(
        [sys.executable, "-m", "income_desk.trader.trader", "--all", f"--market={market}"],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=Path(__file__).parent.parent,
    )

    output = result.stdout + result.stderr

    # Count issues
    error_count = output.lower().count("error")
    fail_count = output.count("FAIL")

    # Extract summary
    summary_lines = [l for l in output.split("\n") if "Total:" in l and "Passed:" in l]
    summary = summary_lines[-1].strip() if summary_lines else "No summary found"

    print(f"  Harness: {summary}")
    if error_count > 0:
        print(f"  Errors in output: {error_count}")

    return output, fail_count == 0


def run_pricing_regression(market: str, rebuild: bool = False) -> tuple[str, int, int]:
    """Run pricing regression and return (output, passed, total)."""
    print(f"\n{'=' * 60}")
    print(f"  STEP 2: PRICING REGRESSION — {market}")
    print(f"{'=' * 60}\n")

    cmd = [sys.executable, "-m", "scripts.pricing_regression", f"--market={market}"]
    if rebuild:
        cmd.append("--rebuild")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
        cwd=Path(__file__).parent.parent,
    )

    output = result.stdout + result.stderr

    # Extract pass/fail counts
    passed = output.count("[PASS]")
    failed = output.count("[FAIL]")
    total = passed + failed

    print(f"  Pricing: {passed}/{total} PASS ({100*passed/total:.0f}%)" if total > 0 else "  Pricing: no trades")

    return output, passed, total


def compare_with_previous(market: str, today_results: dict) -> str:
    """Compare today's results with the most recent previous run."""
    pattern = f"*_{market.lower()}_daily_results.json"
    previous_files = sorted(RESULTS_DIR.glob(pattern))

    if len(previous_files) < 2:
        return "  (No previous run to compare with)"

    prev_file = previous_files[-2]  # Second to last (last is today's)
    try:
        with open(prev_file) as f:
            prev = json.load(f)
    except Exception:
        return f"  (Could not read {prev_file.name})"

    lines = [f"  Comparing with {prev_file.name}:"]

    # Harness comparison
    prev_harness = prev.get("harness_pass", False)
    today_harness = today_results.get("harness_pass", False)
    if today_harness and not prev_harness:
        lines.append("    Harness: IMPROVED (was failing, now passing)")
    elif not today_harness and prev_harness:
        lines.append("    Harness: REGRESSED (was passing, now failing)")
    else:
        lines.append(f"    Harness: {'PASS' if today_harness else 'FAIL'} (unchanged)")

    # Pricing comparison
    prev_passed = prev.get("pricing_passed", 0)
    today_passed = today_results.get("pricing_passed", 0)
    prev_total = prev.get("pricing_total", 0)
    today_total = today_results.get("pricing_total", 0)
    delta = today_passed - prev_passed
    if delta > 0:
        lines.append(f"    Pricing: {today_passed}/{today_total} (+{delta} trades)")
    elif delta < 0:
        lines.append(f"    Pricing: {today_passed}/{today_total} ({delta} trades) REGRESSED")
    else:
        lines.append(f"    Pricing: {today_passed}/{today_total} (unchanged)")

    return "\n".join(lines)


def save_results(market: str, harness_output: str, harness_pass: bool,
                 pricing_output: str, pricing_passed: int, pricing_total: int) -> Path:
    """Save daily results to JSON and text files."""
    today = date.today().isoformat()

    # JSON summary
    results = {
        "date": today,
        "market": market,
        "harness_pass": harness_pass,
        "pricing_passed": pricing_passed,
        "pricing_total": pricing_total,
        "pricing_pct": round(100 * pricing_passed / pricing_total, 1) if pricing_total > 0 else 0,
        "timestamp": datetime.now().isoformat(),
    }

    json_file = RESULTS_DIR / f"{today}_{market.lower()}_daily_results.json"
    with open(json_file, "w") as f:
        json.dump(results, f, indent=2)

    # Full output
    txt_file = RESULTS_DIR / f"{today}_{market.lower()}_daily_full.txt"
    with open(txt_file, "w") as f:
        f.write(f"=== HARNESS OUTPUT ===\n\n")
        f.write(harness_output)
        f.write(f"\n\n=== PRICING REGRESSION OUTPUT ===\n\n")
        f.write(pricing_output)

    return json_file


def main():
    parser = argparse.ArgumentParser(description="Daily live testing")
    parser.add_argument("--market", choices=["India", "US"], required=True)
    parser.add_argument("--rebuild", action="store_true", help="Rebuild pricing portfolio")
    parser.add_argument("--offline", action="store_true", help="Skip live tests, use saved data")
    args = parser.parse_args()

    market = args.market
    today = date.today().isoformat()

    print(f"\n  Daily Test — {market} Market — {today}")
    print(f"  {'=' * 50}")

    if args.offline:
        print("  Running in OFFLINE mode (saved snapshot data)")

    # Step 1: Harness
    harness_output, harness_pass = run_harness(market)

    # Step 2: Pricing regression
    pricing_output, pricing_passed, pricing_total = run_pricing_regression(
        market, rebuild=args.rebuild,
    )

    # Save results
    json_file = save_results(
        market, harness_output, harness_pass,
        pricing_output, pricing_passed, pricing_total,
    )

    # Compare with previous
    results = {
        "harness_pass": harness_pass,
        "pricing_passed": pricing_passed,
        "pricing_total": pricing_total,
    }
    comparison = compare_with_previous(market, results)

    # Final report
    print(f"\n{'=' * 60}")
    print(f"  DAILY TEST SUMMARY — {market} — {today}")
    print(f"{'=' * 60}")
    print(f"  Harness:  {'PASS' if harness_pass else 'FAIL'}")
    print(f"  Pricing:  {pricing_passed}/{pricing_total} trades validated")
    print(comparison)
    print(f"\n  Results saved to: {json_file.name}")
    print(f"  Full output: {json_file.stem.replace('_results', '_full')}.txt")

    # Exit code
    if not harness_pass or pricing_passed < pricing_total:
        sys.exit(1)


if __name__ == "__main__":
    main()
