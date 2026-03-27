#!/usr/bin/env python3
"""Release readiness validation — daily go-live readiness check.

Exercises every income_desk API along the 8-stage trading workflow,
validates number invariants, and produces:
  1. HTML dashboard (self-contained, no server)
  2. JSON API replay manifest (for eTrading verification)
  3. Console summary

Usage::

    python scripts/release_readiness.py
    python scripts/release_readiness.py --no-parallel
    python scripts/release_readiness.py --output-dir reports/
    python scripts/release_readiness.py --no-india
"""

import argparse
import sys
from datetime import date
from pathlib import Path

# Ensure income_desk is importable when running as a script
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def main() -> int:
    parser = argparse.ArgumentParser(description="income_desk release readiness validation")
    parser.add_argument("--no-parallel", action="store_true", help="Run stages sequentially")
    parser.add_argument("--no-india", action="store_true", help="Skip India market tests")
    parser.add_argument("--output-dir", type=str, default=".", help="Output directory for reports")
    args = parser.parse_args()

    from income_desk.regression.release_readiness import run_release_readiness
    from income_desk.regression.readiness_report import write_html, write_manifest

    print("=" * 70)
    print("  income_desk — Release Readiness Validation")
    print("=" * 70)
    print()

    report = run_release_readiness(
        parallel=not args.no_parallel,
        include_india=not args.no_india,
    )

    # Console summary
    print(f"Version:  {report.version}")
    print(f"Markets:  {', '.join(report.markets_tested)}")
    print(f"Duration: {report.duration_ms:.0f}ms")
    print()

    for stage in report.stages:
        verdict = stage.verdict.value
        icon = {"PASS": "[OK]", "FAIL": "[FAIL]", "WARN": "[WARN]", "SKIP": "[SKIP]"}.get(verdict, "[??]")
        apis = len(stage.api_calls)
        inv = f"{stage.passed_invariants}/{stage.total_invariants}"
        print(f"  {icon} Stage {stage.stage_number}: {stage.stage:<12} | {apis} APIs | {inv} invariants | {stage.duration_ms:.0f}ms")
        if stage.error:
            print(f"       ERROR: {stage.error}")

    print()
    print("-" * 70)
    pass_rate = (
        f"{report.passed_invariants}/{report.total_invariants} "
        f"({report.passed_invariants / report.total_invariants * 100:.1f}%)"
        if report.total_invariants > 0 else "0/0"
    )
    print(f"  APIs tested:      {report.total_apis_tested}")
    print(f"  Invariants:       {pass_rate}")

    if report.gaps_found:
        print(f"\n  Gaps found ({len(report.gaps_found)}):")
        for gap in report.gaps_found[:10]:
            print(f"    - {gap}")
        if len(report.gaps_found) > 10:
            print(f"    ... and {len(report.gaps_found) - 10} more (see HTML report)")

    print()
    verdict_icon = {"GO": "GO", "CONDITIONAL-GO": "CONDITIONAL-GO", "NO-GO": "NO-GO"}.get(report.overall_verdict, "??")
    print(f"  VERDICT: {verdict_icon}")
    print("-" * 70)

    # Write reports
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    html_path = write_html(report, output_dir / f"release_readiness_{today}.html")
    manifest_path = write_manifest(report, output_dir / f"release_readiness_manifest_{today}.json")

    print(f"\n  HTML report:      {html_path}")
    print(f"  API manifest:     {manifest_path}")
    print()

    return 0 if report.overall_verdict == "GO" else 1


if __name__ == "__main__":
    sys.exit(main())
