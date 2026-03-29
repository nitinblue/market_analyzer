"""Run trader_md workflows.

Usage:
    python -m income_desk.trader_md run workflows/daily_us.workflow.md
    python -m income_desk.trader_md validate workflows/daily_us.workflow.md
    python -m income_desk.trader_md dry-run workflows/daily_us.workflow.md
    python -m income_desk.trader_md run workflows/daily_us.workflow.md --interactive
    python -m income_desk.trader_md run workflows/daily_us.workflow.md --set capital=100000
    python -m income_desk.trader_md run workflows/daily_us.workflow.md --report reports/out.md
"""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="income_desk Trader MD -- execute .workflow.md files",
    )
    parser.add_argument(
        "command",
        choices=["run", "validate", "dry-run"],
        help="Command to execute",
    )
    parser.add_argument("workflow", help="Path to .workflow.md file")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Pause between steps",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show tracebacks",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        help="Override variable: key=value (repeatable)",
    )
    parser.add_argument(
        "--report",
        help="Save execution report to markdown file",
    )
    args = parser.parse_args()

    # Parse --set overrides into a dict
    overrides: dict[str, str] = {}
    for item in args.set:
        key, _, value = item.partition("=")
        overrides[key.strip()] = value.strip()

    from income_desk.trader_md.runner import TradingRunner

    runner = TradingRunner(
        workflow_path=args.workflow,
        interactive=args.interactive,
        verbose=args.verbose,
        overrides=overrides,
    )

    if args.command == "validate":
        issues = runner.validate()
        if issues:
            print("Validation issues:")
            for issue in issues:
                print(f"  - {issue}")
            sys.exit(1)
        else:
            print("Workflow is valid.")
            sys.exit(0)

    elif args.command == "dry-run":
        print(runner.dry_run())
        sys.exit(0)

    elif args.command == "run":
        # Suppress library warnings unless verbose
        if not args.verbose:
            import logging

            logging.getLogger("income_desk").setLevel(logging.ERROR)
            logging.getLogger("fredapi").setLevel(logging.ERROR)

        report = runner.run()

        if args.report:
            runner.export_report(args.report)
            print(f"\n  Report saved to {args.report}")

        ok = sum(1 for r in report.step_results if r.status == "OK")
        total = len(report.step_results)
        sys.exit(0 if ok == total else 1)


if __name__ == "__main__":
    main()
