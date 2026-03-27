#!/usr/bin/env python3
"""India Income Trader — End-to-end trading simulation.

Run: python scripts/Trader-IND.py
     python scripts/Trader-IND.py --capital 5000000 --risk moderate
     python scripts/Trader-IND.py --broker  # Use real Dhan/Zerodha data

Simulates the complete India income trading workflow:
  1. Create ₹50L portfolio with desk allocation (NIFTY/BANKNIFTY focus)
  2. Crash sentinel check
  3. Regime detection on India universe
  4. Rank opportunities (European exercise, expiry-day awareness)
  5. Validate through 10-check gate
  6. Kelly position sizing (lot size aware: NIFTY=25, BANKNIFTY=15)
  7. Route to desk and book
  8. Monitor positions (simulated day 10)
  9. Print full report

India-specific features:
  - European exercise (no early assignment risk)
  - Weekly expiry: NIFTY=Thu, BANKNIFTY=Wed, FINNIFTY=Tue
  - Lot sizes: NIFTY=25, BANKNIFTY=15, FINNIFTY=25, SENSEX=10
  - Strike intervals: NIFTY=50, BANKNIFTY=100
  - Trading hours: 9:15 AM - 3:30 PM IST
  - Cross-market: US close → NIFTY opening gap prediction
"""
import sys
import io
import argparse
import warnings
import logging
from pathlib import Path

# Ensure income_desk is importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)


def main():
    parser = argparse.ArgumentParser(description="India Income Trader")
    parser.add_argument("--capital", type=float, default=5_000_000,
                        help="Account size in INR (default: ₹50,00,000 / 50 lakh)")
    parser.add_argument("--risk", choices=["conservative", "moderate", "aggressive"], default="moderate")
    parser.add_argument("--broker", choices=["dhan", "zerodha"], default=None,
                        help="Connect to India broker")
    parser.add_argument("--sim", choices=["india_trading", "snapshot"], default="india_trading",
                        help="Simulation preset (default: india_trading)")
    parser.add_argument("--workflow", action="store_true",
                        help="Use workflow API (generate_daily_plan) instead of demo runner")
    args = parser.parse_args()

    # Connect data source
    sim = None  # only set when using simulated data
    if args.broker == "dhan":
        try:
            from dotenv import load_dotenv
            load_dotenv()
            from income_desk.broker.dhan import connect_dhan
            md, mm, acct, wl = connect_dhan()
            from income_desk import MarketAnalyzer, DataService
            ma = MarketAnalyzer(data_service=DataService(), market_data=md, market_metrics=mm)
            print("Data: DHAN BROKER (live India)")
        except Exception as e:
            print(f"Dhan connection failed: {e}")
            return

    elif args.broker == "zerodha":
        try:
            from dotenv import load_dotenv
            load_dotenv()
            import os
            from income_desk.broker.zerodha import connect_zerodha
            md, mm, acct, wl = connect_zerodha(
                api_key=os.environ.get("ZERODHA_API_KEY", ""),
                access_token=os.environ.get("ZERODHA_ACCESS_TOKEN", ""),
            )
            from income_desk import MarketAnalyzer, DataService
            ma = MarketAnalyzer(data_service=DataService(), market_data=md, market_metrics=mm)
            print("Data: ZERODHA BROKER (live India)")
        except Exception as e:
            print(f"Zerodha connection failed: {e}")
            return

    else:
        from income_desk.adapters.simulated import (
            create_india_trading, create_from_snapshot,
            SimulatedMetrics, SimulatedAccount,
        )
        if args.sim == "snapshot":
            sim = create_from_snapshot()
            if sim is None:
                print("No snapshot found. Run 'refresh_sim' during market hours.")
                return
        else:
            sim = create_india_trading()

        from income_desk import MarketAnalyzer, DataService
        ma = MarketAnalyzer(data_service=DataService(), market_data=sim, market_metrics=SimulatedMetrics(sim))
        print(f"Data: SIMULATED ({args.sim})")

    # Print India-specific context
    print()
    print("INDIA MARKET CONTEXT")
    print("-" * 40)
    print("Exercise: European (assignment only at expiry)")
    print("Lot sizes: NIFTY=25, BANKNIFTY=15, FINNIFTY=25")
    print("Expiry: NIFTY=Thu, BANKNIFTY=Wed, FINNIFTY=Tue")
    print("Strike intervals: NIFTY=50, BANKNIFTY=100")

    from datetime import date
    today = date.today()
    weekday = today.strftime("%A")
    expiry_today = None
    if weekday == "Tuesday":
        expiry_today = "FINNIFTY"
    elif weekday == "Wednesday":
        expiry_today = "BANKNIFTY"
    elif weekday == "Thursday":
        expiry_today = "NIFTY"
    if expiry_today:
        print(f"TODAY: {weekday} — {expiry_today} expiry day!")
    else:
        print(f"Today: {weekday} — no expiry")
    print()

    # --- Workflow mode (new) ---
    if args.workflow:
        from income_desk.workflow import (
            generate_daily_plan, DailyPlanRequest,
            snapshot_market, SnapshotRequest,
        )

        tickers = ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK"]

        # Market snapshot first
        print("Fetching market snapshot...")
        snap = snapshot_market(SnapshotRequest(tickers=tickers, market="India"), ma)
        print(f"\nMARKET SNAPSHOT ({snap.timestamp.strftime('%H:%M:%S IST')})")
        print(f"{'-'*60}")
        for t, s in snap.tickers.items():
            regime_tag = f"R{s.regime_id}" if s.regime_id else "?"
            print(f"  {t:<15} {s.price or 0:>10,.2f}  {regime_tag} ({s.regime_confidence:.0%})  "
                  f"ATR={s.atr_pct:.2f}%  RSI={s.rsi or 0:.0f}")

        # Daily plan
        print(f"\nGenerating daily plan...")
        plan = generate_daily_plan(
            DailyPlanRequest(
                tickers=tickers,
                capital=args.capital,
                market="India",
                risk_tolerance=args.risk,
                max_new_trades=5,
            ),
            ma,
        )

        print(f"\n{'='*60}")
        print(f"INDIA DAILY PLAN (Workflow API)")
        print(f"{'='*60}")
        print(f"Capital: INR {args.capital:,.0f} ({args.capital/100000:.0f} lakh)")
        print(f"Sentinel: {plan.sentinel_signal}")
        print(f"Safe to trade: {plan.is_safe_to_trade}")

        print(f"\nREGIMES:")
        for t, r in plan.regimes.items():
            flag = " << SKIP" if not r.tradeable else ""
            print(f"  {t:<15} {r.regime_label} ({r.confidence:.0%}){flag}")

        print(f"\nTRADES: {len(plan.proposed_trades)} proposed, {len(plan.blocked_trades)} blocked")
        for t in plan.proposed_trades:
            pop_str = f"{t.pop_pct:.0%}" if t.pop_pct else "n/a"
            print(f"  #{t.rank} {t.ticker:<12} {t.strategy_badge:<28} "
                  f"score={t.composite_score:.2f} POP={pop_str} "
                  f"{t.contracts}x lot={t.lot_size} "
                  f"risk=INR {t.max_risk or 0:,.0f}")

        if plan.blocked_trades:
            print(f"\nBLOCKED:")
            for b in plan.blocked_trades[:5]:
                print(f"  {b.ticker:<12} {b.reason}")

        print(f"\nRISK BUDGET:")
        print(f"  Deployed: INR {plan.risk_deployed:,.0f}")
        print(f"  Remaining: INR {plan.risk_budget_remaining:,.0f}")

        print(f"\n{'='*60}")
        print(f"SUMMARY: {plan.summary}")
        print(f"{'='*60}")

        if plan.meta.warnings:
            print(f"\nWarnings ({len(plan.meta.warnings)}):")
            for w in plan.meta.warnings[:5]:
                print(f"  {w}")

        # Save
        import json
        report_path = Path.home() / ".income_desk" / "last_india_plan.json"
        report_path.parent.mkdir(exist_ok=True)
        report_path.write_text(json.dumps(plan.model_dump(), indent=2, default=str))
        print(f"\nPlan saved: {report_path}")
        return

    # --- Legacy demo runner ---
    from income_desk.demo.trader import run_trader, print_trader_report

    sim_data = sim if not args.broker else None

    report = run_trader(
        market="India",
        capital=args.capital,
        risk_tolerance=args.risk,
        sim=sim_data,
        max_trades=5,
        ma=ma if args.broker else None,
    )

    # Customize output for INR
    print(f"\n{'='*60}")
    print(f"INDIA INCOME TRADER REPORT")
    print(f"{'='*60}")
    print(f"Capital: INR {report.capital:,.0f} ({report.capital/100000:.1f} lakh)")
    print(f"Risk tolerance: {report.risk_tolerance}")
    print(f"Sentinel: {report.sentinel_signal}")
    print(f"Trust: {report.trust_summary}")

    print(f"\nDESKS ({report.desks_created}):")
    for d in report.desk_summary:
        print(f"  {d['desk_key']:<28} INR {d['capital']:>12,.0f}")

    print(f"\nREGIMES:")
    for t, r in report.regime_summary.items():
        flag = " << SKIP" if r == 4 else ""
        print(f"  {t:<12} R{r}{flag}")

    print(f"\nTRADES: {report.trades_booked} booked, {len(report.trades_blocked)} blocked")
    for trade in report.positions:
        print(f"  {trade['ticker']:<12} {trade['structure']:<16} {trade['contracts']}x  "
              f"INR {trade['credit']*100*trade['contracts']:,.0f} credit  "
              f"POP {trade['pop']:.0%}  -> {trade['desk']}")

    if report.trades_blocked:
        print(f"\nBLOCKED:")
        for b in report.trades_blocked[:5]:
            print(f"  {b['ticker']:<12} {b['reason']}")

    print(f"\nPORTFOLIO:")
    print(f"  Risk deployed: INR {report.total_risk_deployed:,.0f} ({report.risk_pct:.1%})")
    print(f"  Cash remaining: INR {report.cash_remaining:,.0f}")

    if report.monitoring_results:
        print(f"\nMONITORING (Day 10):")
        for m in report.monitoring_results:
            print(f"  {m['ticker']:<12} {m['theta_action']:<20} target={m['target']} stop={m['stop']}")

    print(f"\n{'='*60}")
    print(f"{report.overall_summary}")
    print(f"{'='*60}")

    # Save report
    report_path = Path.home() / ".income_desk" / "last_india_trader_report.json"
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(report.model_dump_json(indent=2))
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
