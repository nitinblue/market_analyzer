"""Systematic Stock Trader — US + India Markets.

End-to-end equity investment workflow using market_analyzer fundamental
+ technical analysis. Demonstrates the complete flow for stock selection,
entry planning, position monitoring, and exit management.

Switch between US and India with --market flag.

Usage::

    .venv_312/Scripts/python.exe challenge/trader_stocks.py --market US
    .venv_312/Scripts/python.exe challenge/trader_stocks.py --market India
    .venv_312/Scripts/python.exe challenge/trader_stocks.py --market India --strategy value
    .venv_312/Scripts/python.exe challenge/trader_stocks.py --market US --strategy dividend --top 5
    .venv_312/Scripts/python.exe challenge/trader_stocks.py --tickers RELIANCE TCS INFY
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, time as dt_time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import io
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from market_analyzer import (
    DataService,
    MarketAnalyzer,
    MarketRegistry,
)
from market_analyzer.equity_research import (
    InvestmentHorizon,
    InvestmentStrategy,
    analyze_stock,
    fetch_fundamental_profile,
    screen_stocks,
)

# -- Configuration --

ACCOUNT_US = 50_000      # USD
ACCOUNT_INDIA = 500_000  # INR
MAX_POSITIONS = 10       # More positions for stock portfolio
RISK_PER_TRADE_PCT = 0.03  # 3% risk per trade (tighter for stocks)


def _sep(title: str) -> None:
    print(f"\n{'-' * 70}")
    print(f"  {title}")
    print(f"{'-' * 70}")


def _rating_color(rating: str) -> str:
    colors = {
        "strong_buy": "\033[92m",   # Green
        "buy": "\033[92m",
        "hold": "\033[93m",         # Yellow
        "sell": "\033[91m",         # Red
        "strong_sell": "\033[91m",
    }
    reset = "\033[0m"
    return f"{colors.get(rating, '')}{rating.upper()}{reset}"


def run(
    market: str = "US",
    strategy: str | None = None,
    horizon: str = "long",
    tickers: list[str] | None = None,
    top_n: int = 10,
    detail: bool = False,
):
    """Execute stock selection workflow."""

    registry = MarketRegistry()
    ds = DataService()
    ma = MarketAnalyzer(data_service=ds)

    # Resolve parameters
    inv_horizon = InvestmentHorizon.LONG_TERM if horizon == "long" else InvestmentHorizon.MEDIUM_TERM
    inv_strategy = InvestmentStrategy(strategy) if strategy else None
    account_size = ACCOUNT_US if market.upper() == "US" else ACCOUNT_INDIA
    currency = "USD" if market.upper() == "US" else "INR"

    print(f"{'=' * 70}")
    print(f"  SYSTEMATIC STOCK TRADER — {date.today().isoformat()}")
    print(f"  Market: {market.upper()} | Strategy: {strategy or 'blend'} | Horizon: {horizon}")
    print(f"  Account: {currency} {account_size:,.0f} | Max positions: {MAX_POSITIONS}")
    print(f"{'=' * 70}")

    # ==============================================================
    # STEP 1: Market Context
    # ==============================================================
    _sep("STEP 1: Market Context")

    try:
        ctx = ma.context.assess()
        print(f"  Environment: {ctx.environment_label}")
        print(f"  Trading:     {'ALLOWED' if ctx.trading_allowed else 'BLOCKED'}")
        print(f"  Size factor: {ctx.position_size_factor}")

        alert = ma.black_swan.alert()
        print(f"  Black Swan:  {alert.alert_level} (score={alert.composite_score:.2f})")

        if alert.alert_level == "critical":
            print("\n  [!!] BLACK SWAN — NO NEW POSITIONS")
            return
    except Exception as e:
        print(f"  Context: {e}")

    # Macro research for sector guidance
    try:
        from market_analyzer.macro_research import RESEARCH_ASSETS, generate_research_report

        research_data = {}
        for ticker in list(RESEARCH_ASSETS.keys())[:10]:  # Top 10 for speed
            try:
                research_data[ticker] = ds.get_ohlcv(ticker)
            except Exception:
                pass

        if research_data:
            report = generate_research_report(research_data, "daily")
            print(f"  Macro regime: {report.regime.regime.value.upper()} ({report.regime.confidence:.0%})")
            print(f"  Sentiment:    {report.sentiment.overall_sentiment} ({report.sentiment.sentiment_score:+.2f})")
            if report.regime.favor_sectors:
                print(f"  Favor:        {', '.join(report.regime.favor_sectors)}")
            if report.regime.avoid_sectors:
                print(f"  Avoid:        {', '.join(report.regime.avoid_sectors)}")
    except Exception as e:
        print(f"  Macro research: {e}")

    # ==============================================================
    # STEP 2: Build Universe
    # ==============================================================
    _sep("STEP 2: Universe Selection")

    if tickers:
        scan_tickers = [t.upper() for t in tickers]
        print(f"  Explicit: {', '.join(scan_tickers)}")
    else:
        # Use registry presets based on market
        if market.upper() == "INDIA":
            scan_tickers = registry.get_universe(preset="nifty50")
            print(f"  Preset: nifty50 ({len(scan_tickers)} stocks)")
        else:
            scan_tickers = registry.get_universe(preset="us_mega")
            print(f"  Preset: us_mega ({len(scan_tickers)} stocks)")

    # ==============================================================
    # STEP 3: Fetch Data
    # ==============================================================
    _sep(f"STEP 3: Fetching Data ({len(scan_tickers)} stocks)")

    ohlcv_data: dict = {}
    failed: list[str] = []
    for ticker in scan_tickers:
        try:
            ohlcv_data[ticker] = ds.get_ohlcv(ticker)
        except Exception:
            failed.append(ticker)

    print(f"  Fetched: {len(ohlcv_data)} | Failed: {len(failed)}")
    if failed and detail:
        print(f"  Failed tickers: {', '.join(failed[:10])}")

    # ==============================================================
    # STEP 4: Screen & Score
    # ==============================================================
    _sep("STEP 4: Screen & Score")

    result = screen_stocks(
        tickers=list(ohlcv_data.keys()),
        ohlcv_data=ohlcv_data,
        strategy=inv_strategy,
        horizon=inv_horizon,
        market=market.upper(),
        top_n=top_n,
        min_score=50.0,
    )

    print(f"  {result.summary}")
    print()

    if not result.top_picks:
        print("  No stocks pass the minimum score threshold.")
        print("  Try: --strategy value (more lenient) or --market India --strategy dividend")
        return

    # ==============================================================
    # STEP 5: Top Picks — Detailed View
    # ==============================================================
    _sep(f"STEP 5: Top {len(result.top_picks)} Picks")

    for i, rec in enumerate(result.top_picks, 1):
        f = rec.fundamental

        print(f"\n  {'='*3} #{i}: {rec.ticker} — {rec.name} {'='*3}")
        print(f"  Rating: {_rating_color(rec.rating.value)} | Score: {rec.composite_score:.0f}/100 | Strategy: {rec.primary_strategy.value}")
        print(f"  Sector: {rec.sector} | Market cap: {f.market_cap_category}")

        # Fundamentals snapshot
        pe_str = f"P/E {f.pe_trailing:.1f}" if f.pe_trailing else "P/E n/a"
        pb_str = f"P/B {f.pb_ratio:.1f}" if f.pb_ratio else "P/B n/a"
        roe_str = f"ROE {f.roe:.0f}%" if f.roe else "ROE n/a"
        div_str = f"Div {f.dividend_yield:.1f}%" if f.dividend_yield else "Div n/a"
        rev_str = f"Rev growth {f.revenue_growth_yoy:+.0f}%" if f.revenue_growth_yoy is not None else ""
        print(f"  Fundamentals: {pe_str} | {pb_str} | {roe_str} | {div_str}")
        if rev_str:
            print(f"                {rev_str}")
        if f.debt_to_equity is not None:
            print(f"                Debt/Equity: {f.debt_to_equity:.0f} | Margin: {f.profit_margin or 0:.0f}%")
        if f.from_52w_high_pct is not None:
            print(f"                52wk position: {f.from_52w_high_pct:+.0f}% from high")

        # Entry plan
        if rec.entry_price:
            print(f"  Entry Plan:")
            print(f"    Entry:  {currency} {rec.entry_price:,.2f}")
            if rec.stop_loss:
                risk_pct = abs(rec.entry_price - rec.stop_loss) / rec.entry_price * 100
                print(f"    Stop:   {currency} {rec.stop_loss:,.2f} ({risk_pct:.1f}% risk)")
            if rec.target_price:
                reward_pct = (rec.target_price - rec.entry_price) / rec.entry_price * 100
                print(f"    Target: {currency} {rec.target_price:,.2f} ({reward_pct:+.1f}% reward)")
            if rec.risk_reward:
                print(f"    R:R:    {rec.risk_reward:.1f}:1")

            # Position sizing
            if rec.stop_loss:
                risk_per_share = abs(rec.entry_price - rec.stop_loss)
                max_risk = account_size * RISK_PER_TRADE_PCT
                shares = int(max_risk / risk_per_share) if risk_per_share > 0 else 0

                # India: round to lot size
                try:
                    inst = registry.get_instrument(rec.ticker)
                    if inst.market == "INDIA":
                        lot = inst.lot_size
                        shares = (shares // lot) * lot
                        print(f"    Size:   {shares} shares ({shares // lot} lots × {lot}) | Risk: {currency} {shares * risk_per_share:,.0f}")
                    else:
                        print(f"    Size:   {shares} shares | Risk: {currency} {shares * risk_per_share:,.0f}")
                except KeyError:
                    print(f"    Size:   {shares} shares | Risk: {currency} {shares * risk_per_share:,.0f}")

        # Thesis
        print(f"  Thesis: {rec.thesis}")

        # Strategy scores (if detail)
        if detail:
            print(f"  Strategy Scores:")
            for s in rec.strategy_scores:
                bar = "█" * int(s.score / 5) + "░" * (20 - int(s.score / 5))
                print(f"    {s.strategy.value:20s} {s.score:5.0f} {bar} {s.rating.value}")
                if s.strengths:
                    for st in s.strengths[:2]:
                        print(f"      + {st}")
                if s.risks:
                    for r in s.risks[:2]:
                        print(f"      - {r}")

    # ==============================================================
    # STEP 6: Sector Allocation
    # ==============================================================
    if result.sector_allocation:
        _sep("STEP 6: Sector Allocation")
        total = sum(result.sector_allocation.values())
        for sector, count in sorted(result.sector_allocation.items(), key=lambda x: -x[1]):
            pct = count / total * 100
            bar = "█" * int(pct / 2)
            print(f"  {sector:20s} {count:2d} picks ({pct:4.0f}%) {bar}")

    # ==============================================================
    # STEP 7: Portfolio Construction Guidance
    # ==============================================================
    _sep("STEP 7: Portfolio Construction")

    print(f"\n  Account: {currency} {account_size:,.0f}")
    print(f"  Risk per trade: {RISK_PER_TRADE_PCT:.0%} = {currency} {account_size * RISK_PER_TRADE_PCT:,.0f}")
    print(f"  Max positions: {MAX_POSITIONS}")

    if result.top_picks:
        # Equal weight allocation
        per_position = account_size / min(len(result.top_picks), MAX_POSITIONS)
        print(f"  Equal weight: {currency} {per_position:,.0f} per position")
        print()
        print(f"  Suggested portfolio:")
        total_alloc = 0
        for i, rec in enumerate(result.top_picks[:MAX_POSITIONS], 1):
            if rec.entry_price and rec.entry_price > 0:
                shares = int(per_position / rec.entry_price)
                alloc = shares * rec.entry_price
                total_alloc += alloc
                print(f"    {i:2d}. {rec.ticker:12s} {shares:5d} shares × {currency} {rec.entry_price:>10,.2f} = {currency} {alloc:>12,.0f}  [{rec.rating.value}]")
        print(f"    {'':2s}  {'Total':12s} {'':5s}         {'':>10s}   {currency} {total_alloc:>12,.0f}")
        print(f"    {'':2s}  {'Cash':12s} {'':5s}         {'':>10s}   {currency} {account_size - total_alloc:>12,.0f}")

    # ==============================================================
    # STEP 8: Exit Rules
    # ==============================================================
    _sep("STEP 8: Exit Rules")

    print(f"""
  Exit rules for stock positions:

  PROFIT TAKING:
    - Long-term: take 50% at target price, trail stop on remainder
    - Medium-term: take 100% at target price
    - Trailing stop: move stop to breakeven after +1 ATR, then trail by 2 ATR

  STOP LOSS:
    - Initial stop: 2 ATR below entry (set at purchase)
    - NEVER move stop down — only up
    - If stop hit: sell immediately, no questions

  REGIME CHANGE:
    - If macro regime shifts to DEFLATIONARY: close all equity positions
    - If regime shifts to RISK_OFF: reduce to 50% of target allocation
    - If regime shifts to STAGFLATION: rotate to energy/commodity/healthcare

  TIME-BASED:
    - Long-term: review at 6 months — if thesis broken, exit
    - Medium-term: review at 4 weeks — if no progress, exit
    - Earnings: review before every earnings report

  FUNDAMENTAL DETERIORATION:
    - Revenue growth turns negative → sell
    - Dividend cut → sell immediately (dividend strategy)
    - Debt/equity doubles → sell (value strategy)
    - ROE drops below 8% → sell (quality strategy)
""")

    # ==============================================================
    # Summary
    # ==============================================================
    print(f"{'=' * 70}")
    print(f"  {market.upper()} Stock Selection Complete")
    print(f"  {len(result.top_picks)} picks | Strategy: {strategy or 'blend'} | Horizon: {horizon}")
    print(f"  Data: yfinance (historical + fundamentals)")
    print(f"{'=' * 70}")


def main():
    parser = argparse.ArgumentParser(description="Systematic Stock Trader")
    parser.add_argument("--market", default="US", choices=["US", "India", "us", "india"])
    parser.add_argument("--strategy", default=None,
                        choices=["value", "growth", "dividend", "quality_momentum", "turnaround", "blend"])
    parser.add_argument("--horizon", default="long", choices=["long", "medium"])
    parser.add_argument("--tickers", nargs="+", default=None)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--detail", action="store_true")
    args = parser.parse_args()

    run(
        market=args.market.upper(),
        strategy=args.strategy,
        horizon=args.horizon,
        tickers=args.tickers,
        top_n=args.top,
        detail=args.detail,
    )


if __name__ == "__main__":
    main()
