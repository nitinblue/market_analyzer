#!/usr/bin/env python3
"""US Income Trader — End-to-end trading simulation.

Run: python scripts/Trader-US.py
     python scripts/Trader-US.py --capital 50000 --risk conservative
     python scripts/Trader-US.py --broker  # Use real broker data

Simulates the complete income trading workflow:
  1. Create $100K portfolio with desk allocation
  2. Crash sentinel check
  3. Regime detection on US universe
  4. Rank opportunities
  5. Validate through 10-check gate
  6. Kelly position sizing
  7. Route to desk and book
  8. Monitor positions (simulated day 10)
  9. Print full report
"""
import sys
import io
import argparse
import warnings
import logging

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)


def main():
    parser = argparse.ArgumentParser(description="US Income Trader")
    parser.add_argument("--capital", type=float, default=100_000, help="Account size (default: $100,000)")
    parser.add_argument("--risk", choices=["conservative", "moderate", "aggressive"], default="moderate")
    parser.add_argument("--broker", action="store_true", help="Use real broker data (requires --setup)")
    parser.add_argument("--sim", choices=["income", "recovery", "calm", "volatile", "crash", "snapshot"],
                        default="income", help="Simulation preset (default: income)")
    args = parser.parse_args()

    # Connect data source
    if args.broker:
        from market_analyzer.cli._broker import connect_broker
        md, mm, acct, wl = connect_broker(is_paper=False)
        if md is None:
            print("Broker connection failed. Run: income-desk --setup")
            return
        from market_analyzer import MarketAnalyzer, DataService
        ma = MarketAnalyzer(data_service=DataService(), market_data=md, market_metrics=mm)
        print("Data: BROKER (live)")
    else:
        from market_analyzer.adapters.simulated import (
            create_ideal_income, create_post_crash_recovery, create_calm_market,
            create_volatile_market, create_crash_scenario, create_from_snapshot,
            SimulatedMetrics, SimulatedAccount,
        )
        factories = {
            "income": create_ideal_income,
            "recovery": create_post_crash_recovery,
            "calm": create_calm_market,
            "volatile": create_volatile_market,
            "crash": create_crash_scenario,
            "snapshot": create_from_snapshot,
        }
        sim = factories[args.sim]()
        if sim is None:
            print("No snapshot found. Run 'refresh_sim' during market hours.")
            return
        from market_analyzer import MarketAnalyzer, DataService
        ma = MarketAnalyzer(data_service=DataService(), market_data=sim, market_metrics=SimulatedMetrics(sim))
        print(f"Data: SIMULATED ({args.sim})")

    # Run trader
    from market_analyzer.demo.trader import run_trader, print_trader_report

    if args.broker:
        sim_data = None
    else:
        sim_data = sim

    report = run_trader(
        market="US",
        capital=args.capital,
        risk_tolerance=args.risk,
        sim=sim_data,
        max_trades=5,
    )

    print_trader_report(report)

    # Save report
    from pathlib import Path
    report_path = Path.home() / ".market_analyzer" / "last_us_trader_report.json"
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(report.model_dump_json(indent=2))
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
