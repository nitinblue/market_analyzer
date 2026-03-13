"""$30K Options Trader -- End-to-End Proof of Concept.

Demonstrates the COMPLETE trading workflow using market_analyzer APIs:

    1. Market context -- Is today safe to trade?
    2. Universe scan -- Dynamic ticker selection via broker filters
    3. Ticker analysis -- Regime + technicals for each candidate
    4. Rank opportunities -- Score trades across tickers x strategies
    5. Account filtering -- Remove trades that exceed account limits
    6. Trade analytics -- Yield, POP, breakevens for each trade
    7. Final recommendations -- High-confidence filter
    8. Position monitoring -- Exit signal check

This script uses REAL market data (via DataService + yfinance).
Run with --broker flag to use live TastyTrade quotes + universe scanning.

Usage::

    .venv_312/Scripts/python.exe challenge/trader.py
    .venv_312/Scripts/python.exe challenge/trader.py --broker
    .venv_312/Scripts/python.exe challenge/trader.py --broker --preset income
    .venv_312/Scripts/python.exe challenge/trader.py --broker --preset income --save MA-Income
    .venv_312/Scripts/python.exe challenge/trader.py --tickers GLD SPY QQQ
    .venv_312/Scripts/python.exe challenge/trader.py --broker --detail
    .venv_312/Scripts/python.exe challenge/trader.py --broker --min-pop 0.40 --min-score 0.50
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force UTF-8 output on Windows (cp1252 can't handle unicode chars)
import io
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from market_analyzer import (
    DataService,
    MarketAnalyzer,
    RegimeID,
)
from market_analyzer.cli._broker import _styled, connect_broker
from market_analyzer.models.universe import PRESETS, UniverseFilter
from market_analyzer.trade_lifecycle import (
    check_income_entry,
    compute_breakevens,
    compute_income_yield,
    estimate_pop,
    filter_trades_by_account,
    monitor_exit_conditions,
)

# -- Configuration --

ACCOUNT_SIZE = 30_000
MAX_POSITIONS = 5
MAX_RISK_PER_TRADE_PCT = 0.05  # 5% of account = $1,500
BP_RESERVE_PCT = 0.20  # Keep 20% buying power in reserve
DEFAULT_TICKERS = ["SPX", "GLD", "QQQ", "TLT", "IWM", "AAPL"]

# High-confidence gate thresholds (Step 7)
HC_MIN_POP = 0.50           # Minimum probability of profit
HC_MIN_SCORE = 0.60         # Minimum ranking composite score
HC_MIN_CREDIT_WIDTH = 0.10  # Minimum credit/width ratio for capital efficiency

# Income structures we trade with $30K
ALLOWED_STRUCTURES = {
    "iron_condor", "iron_butterfly", "credit_spread",
    "calendar", "debit_spread",
}


def _sep(title: str) -> None:
    print(f"\n{'-' * 60}")
    print(f"  {title}")
    print(f"{'-' * 60}")


def _regime_label(regime_id: int) -> str:
    names = {1: "R1 Low-Vol MR", 2: "R2 High-Vol MR", 3: "R3 Low-Vol Trend", 4: "R4 High-Vol Trend"}
    return names.get(regime_id, f"R{regime_id}")


def _gate_scorecard(
    t: dict,
    min_pop: float = HC_MIN_POP,
    min_score: float = HC_MIN_SCORE,
    min_credit_width: float = HC_MIN_CREDIT_WIDTH,
) -> list[dict]:
    """Evaluate all 5 high-confidence gates for a trade. Returns list of gate results."""
    entry_check = t["entry_check"]
    pop = t["pop"]
    income = t["income"]
    score = t["entry"].composite_score

    gates = []

    # Gate 1: Entry confirmed
    gates.append({
        "name": "Entry confirmed",
        "threshold": "regime + RSI + DTE + ATR all green",
        "actual": f"score={entry_check.score:.2f}, {sum(1 for c in entry_check.conditions if c['passed'])}/{len(entry_check.conditions)} conditions",
        "passed": entry_check.confirmed,
    })

    # Gate 2: POP >= threshold
    if pop is not None:
        gates.append({
            "name": "POP",
            "threshold": f">= {min_pop:.0%}",
            "actual": f"{pop.pop_pct:.0%}",
            "passed": pop.pop_pct >= min_pop,
        })
    else:
        gates.append({
            "name": "POP",
            "threshold": f">= {min_pop:.0%}",
            "actual": "unavailable",
            "passed": False,
        })

    # Gate 3: Positive EV
    if pop is not None:
        gates.append({
            "name": "Expected value",
            "threshold": "> $0",
            "actual": f"${pop.expected_value:.0f}",
            "passed": pop.expected_value > 0,
        })
    else:
        gates.append({
            "name": "Expected value",
            "threshold": "> $0",
            "actual": "unavailable",
            "passed": False,
        })

    # Gate 4: Ranking score
    gates.append({
        "name": "Ranking score",
        "threshold": f">= {min_score:.2f}",
        "actual": f"{score:.2f}",
        "passed": score >= min_score,
    })

    # Gate 5: Credit/width (capital efficiency)
    if income is not None:
        gates.append({
            "name": "Credit/width",
            "threshold": f">= {min_credit_width:.0%}",
            "actual": f"{income.credit_to_width_pct:.1%}",
            "passed": income.credit_to_width_pct >= min_credit_width,
        })
    else:
        # No income data = not a credit structure, gate N/A (pass by default)
        gates.append({
            "name": "Credit/width",
            "threshold": f">= {min_credit_width:.0%}",
            "actual": "n/a (not credit)",
            "passed": True,
        })

    return gates


def run(
    tickers: list[str] | None = None,
    broker: bool = False,
    paper: bool = False,
    preset: str | None = None,
    save_watchlist: str | None = None,
    detail: bool = False,
    min_pop: float | None = None,
    min_score: float | None = None,
    min_credit_width: float | None = None,
):
    """Execute the full $30K trading workflow."""

    # Resolve gate thresholds (CLI overrides or defaults)
    eff_min_pop = min_pop if min_pop is not None else HC_MIN_POP
    eff_min_score = min_score if min_score is not None else HC_MIN_SCORE
    eff_min_cw = min_credit_width if min_credit_width is not None else HC_MIN_CREDIT_WIDTH

    gate_kwargs = {"min_pop": eff_min_pop, "min_score": eff_min_score, "min_credit_width": eff_min_cw}

    print(f"{'=' * 60}")
    print(f"  $30K OPTIONS TRADER -- {date.today().isoformat()}")
    print(f"  Account: ${ACCOUNT_SIZE:,} | Max positions: {MAX_POSITIONS}")
    print(f"  Risk/trade: {MAX_RISK_PER_TRADE_PCT:.0%} (${ACCOUNT_SIZE * MAX_RISK_PER_TRADE_PCT:,.0f})")
    print(f"  BP reserve: {BP_RESERVE_PCT:.0%} (${ACCOUNT_SIZE * BP_RESERVE_PCT:,.0f})")
    print(f"{'=' * 60}")

    # -- Build MarketAnalyzer --
    ds = DataService()
    ma_kwargs: dict = {"data_service": ds}
    market_data = None
    market_metrics = None
    account_provider = None
    watchlist_provider = None

    if broker:
        try:
            market_data, market_metrics, account_provider, watchlist_provider = connect_broker(
                is_paper=paper,
            )
            ma_kwargs["market_data"] = market_data
            ma_kwargs["market_metrics"] = market_metrics
            ma_kwargs["account_provider"] = account_provider
            ma_kwargs["watchlist_provider"] = watchlist_provider
        except Exception as e:
            print(_styled(f"Broker connection failed: {e}", "yellow"))
            print("  Continuing without broker (no live quotes, no universe scan)")

    ma = MarketAnalyzer(**ma_kwargs)

    # ==============================================================
    # STEP 1: Market Context -- Is today safe to trade?
    # ==============================================================
    _sep("STEP 1: Market Context")

    try:
        ctx = ma.context.assess()
        print(f"  Environment: {ctx.environment_label}")
        print(f"  Trading:     {'ALLOWED' if ctx.trading_allowed else 'BLOCKED'}")
        if hasattr(ctx, 'day_verdict'):
            print(f"  Verdict:     {ctx.day_verdict}")

        # Black swan check
        try:
            alert = ma.black_swan.alert()
            print(f"  Black Swan:  {alert.alert_level} (score={alert.composite_score:.2f})")
            if alert.alert_level in ("critical", "high"):
                print("\n  [!!] BLACK SWAN ALERT -- NO TRADING TODAY")
                return
        except Exception as e:
            print(f"  Black Swan:  unavailable ({e})")
    except Exception as e:
        print(f"  Context assessment failed: {e}")
        print("  Proceeding with caution...")

    # ==============================================================
    # STEP 2: Universe Scan -- Dynamic ticker selection
    # ==============================================================
    if tickers:
        # Explicit tickers provided
        scan_tickers = list(tickers)
        print(f"\n  Using explicit tickers: {', '.join(scan_tickers)}")
    elif preset and ma.universe.has_broker:
        # Dynamic universe from broker filters
        _sep("STEP 2: Universe Scan")
        print(f"  Preset: {_styled(preset, 'bold')}")

        if preset in PRESETS:
            f = PRESETS[preset]
            details = []
            if f.iv_rank_min is not None or f.iv_rank_max is not None:
                details.append(f"IV rank {f.iv_rank_min or 0}-{f.iv_rank_max or 100}")
            if f.min_liquidity_rating:
                details.append(f"liquidity >= {f.min_liquidity_rating}")
            if f.beta_min is not None or f.beta_max is not None:
                details.append(f"beta {f.beta_min or 0}-{f.beta_max or 'any'}")
            details.append(f"max {f.max_symbols} symbols")
            print(f"  Filters: {', '.join(details)}")

        print(f"  Scanning broker universe...")
        result = ma.universe.scan(preset=preset, save_watchlist=save_watchlist)

        if not result.candidates:
            print(_styled("  No symbols passed filters. Try a broader preset.", "yellow"))
            return

        scan_tickers = [c.ticker for c in result.candidates]

        # Show scan results
        print(f"\n  Scanned: {result.total_scanned} | Passed: {result.total_passed}")
        print(f"  Top candidates:")
        for c in result.candidates[:15]:
            iv = f"IV={c.iv_rank:.0f}" if c.iv_rank is not None else "IV=?"
            liq = f"Liq={c.liquidity_rating:.0f}" if c.liquidity_rating is not None else ""
            beta = f"B={c.beta:.1f}" if c.beta is not None else ""
            print(f"    {c.ticker:6s} {c.asset_type:6s}  {iv:8s} {liq:6s} {beta}")

        if result.watchlist_saved:
            print(_styled(f"\n  Saved watchlist: '{result.watchlist_saved}'", "green"))
    elif broker and ma.universe.has_broker:
        # Default: income preset when broker connected but no tickers/preset given
        _sep("STEP 2: Universe Scan (default: income)")
        print(f"  Using 'income' preset (ETF, IV rank 30-80, liq 4+)...")
        result = ma.universe.scan(preset="income")

        if result.candidates:
            scan_tickers = [c.ticker for c in result.candidates]
            print(f"  Found {len(scan_tickers)} candidates")
            for c in result.candidates[:10]:
                iv = f"IV={c.iv_rank:.0f}" if c.iv_rank is not None else "IV=?"
                print(f"    {c.ticker:6s} {c.asset_type:6s}  {iv}")
        else:
            print(_styled("  No candidates from universe scan. Falling back to defaults.", "yellow"))
            scan_tickers = list(DEFAULT_TICKERS)
    else:
        # No broker, use defaults
        scan_tickers = list(DEFAULT_TICKERS)
        print(f"\n  Using default tickers: {', '.join(scan_tickers)}")
        if not broker:
            print(_styled("  Tip: Run with --broker --preset income for dynamic universe", "dim"))

    # ==============================================================
    # STEP 3: Analyze Tickers -- Regime + Technicals
    # ==============================================================
    _sep(f"STEP 3: Ticker Analysis ({len(scan_tickers)} symbols)")

    analyses = {}
    for ticker in scan_tickers:
        try:
            regime = ma.regime.detect(ticker)
            tech = ma.technicals.snapshot(ticker)
            analyses[ticker] = {"regime": regime, "technicals": tech}
            print(
                f"  {ticker:6s}  {_regime_label(regime.regime)} "
                f"({regime.confidence:.0%})  "
                f"RSI {tech.rsi.value:.0f}  "
                f"ATR {tech.atr_pct:.2f}%  "
                f"${tech.current_price:.2f}"
            )
        except Exception as e:
            print(f"  {ticker:6s}  FAILED: {e}")

    if not analyses:
        print("\n  No tickers analyzed successfully. Exiting.")
        return

    # ==============================================================
    # STEP 4: Rank Opportunities
    # ==============================================================
    _sep("STEP 4: Rank Opportunities")

    try:
        ranking_result = ma.ranking.rank(list(analyses.keys()), skip_intraday=True)
        raw_trades = ranking_result.top_trades
        print(f"  Found {len(raw_trades)} ranked trades across {len(analyses)} tickers")
        for e in raw_trades[:10]:
            sym = e.trade_spec.strategy_badge if e.trade_spec else e.strategy_type
            print(
                f"    #{e.rank:2d} {e.ticker:6s} {sym:28s} "
                f"score={e.composite_score:.2f}  {e.verdict}"
            )
    except Exception as e:
        print(f"  Ranking failed: {e}")
        return

    # ==============================================================
    # STEP 5: Filter by Account Constraints
    # ==============================================================
    _sep("STEP 5: Account Filtering")

    available_bp = ACCOUNT_SIZE * (1 - BP_RESERVE_PCT)
    max_risk = ACCOUNT_SIZE * MAX_RISK_PER_TRADE_PCT

    filtered = filter_trades_by_account(
        ranked_entries=raw_trades,
        available_buying_power=available_bp,
        allowed_structures=list(ALLOWED_STRUCTURES),
        max_risk_per_trade=max_risk,
    )

    print(f"  Passed:  {filtered.total_affordable} trades")
    print(f"  Blocked: {len(filtered.filtered_out)} trades")
    if filtered.filtered_out:
        reasons = {}
        for b in filtered.filtered_out:
            r = b.get("filter_reason", "unknown")
            reasons[r] = reasons.get(r, 0) + 1
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    - {reason}: {count}")

    if not filtered.affordable:
        print("\n  No trades pass account constraints. Exiting.")
        return

    # Map affordable tickers+strategies back to original RankedEntry objects
    affordable_keys = {(r["ticker"], r["structure_type"]) for r in filtered.affordable}
    passed_entries = [
        e for e in raw_trades
        if e.trade_spec and (e.ticker, e.trade_spec.structure_type) in affordable_keys
    ]

    # ==============================================================
    # STEP 6: Deep Analytics on Top Trades
    # ==============================================================
    _sep("STEP 6: Trade Analytics")

    actionable = []
    for entry in passed_entries[:8]:  # Top 8 candidates
        spec = entry.trade_spec
        if spec is None:
            continue

        ticker = spec.ticker
        data = analyses.get(ticker)
        if data is None:
            continue

        regime = data["regime"]
        tech = data["technicals"]
        price = tech.current_price

        print(f"\n  -- {ticker} {spec.strategy_badge} --")
        print(f"     Legs: {' | '.join(spec.leg_codes)}")

        # Estimate entry credit/debit from max_entry_price or a reasonable default
        entry_price = spec.max_entry_price
        if entry_price is None:
            # Rough estimate: wing_width * 0.15 for IC, 0.10 for CS
            wing = spec.wing_width_points or 5.0
            if spec.order_side == "credit":
                entry_price = wing * 0.15 if spec.structure_type == "iron_condor" else wing * 0.10
            else:
                entry_price = wing * 0.40

        # F5: Income Yield
        income = compute_income_yield(spec, entry_credit=entry_price)
        if income:
            print(
                f"     Yield: credit/width={income.credit_to_width_pct:.1%} "
                f"ROC={income.return_on_capital_pct:.1%} "
                f"ann={income.annualized_roc_pct:.1%}"
            )
            print(
                f"     Max profit=${income.max_profit:.0f} "
                f"Max loss=${income.max_loss:.0f}"
            )

        # F7: POP
        pop = estimate_pop(
            spec, entry_price=entry_price, regime_id=regime.regime,
            atr_pct=tech.atr_pct, current_price=price,
        )
        if pop:
            print(
                f"     POP: {pop.pop_pct:.0%} "
                f"EV=${pop.expected_value:.0f} "
                f"({pop.method})"
            )

        # F8: Breakevens
        be = compute_breakevens(spec, entry_price=entry_price)
        if be:
            be_parts = []
            if be.low:
                be_parts.append(f"low=${be.low:.2f}")
            if be.high:
                be_parts.append(f"high=${be.high:.2f}")
            print(f"     Breakevens: {', '.join(be_parts)}")

        # F10: Income Entry Check
        iv_rank = None
        iv_pct = None
        if broker and hasattr(ma, 'quotes') and ma.quotes.has_broker:
            try:
                metrics = ma.quotes.get_metrics(ticker)
                if metrics:
                    iv_rank = metrics.iv_rank
                    iv_pct = metrics.iv_percentile
            except Exception:
                pass

        dte = spec.target_dte or 30
        entry_check = check_income_entry(
            iv_rank=iv_rank, iv_percentile=iv_pct,
            dte=dte, rsi=tech.rsi.value, atr_pct=tech.atr_pct,
            regime_id=regime.regime,
        )
        status = "[OK] CONFIRMED" if entry_check.confirmed else "[X] NOT CONFIRMED"
        print(f"     Entry: {status} (score={entry_check.score:.2f})")
        if not entry_check.confirmed:
            failed = [c for c in entry_check.conditions if not c["passed"]]
            for c in failed:
                print(f"       [X] {c['name']}: {c.get('detail', '')}")

        # Exit rules
        print(f"     Exit:  {spec.exit_summary}")

        # High-confidence gate scorecard (always computed, shown with --detail)
        gates = _gate_scorecard({
            "entry_check": entry_check, "pop": pop, "income": income,
            "entry": entry, "spec": spec,
        }, **gate_kwargs)
        all_passed = all(g["passed"] for g in gates)

        if detail:
            verdict = _styled("PASS", "green") if all_passed else _styled("FAIL", "red")
            print(f"     --- Confidence Gates: {verdict} ---")
            for g in gates:
                icon = "[OK]" if g["passed"] else "[X] "
                print(f"       {icon} {g['name']:18s}  need {g['threshold']:20s}  got {g['actual']}")
        else:
            passed_count = sum(1 for g in gates if g["passed"])
            label = _styled("PASS", "green") if all_passed else _styled(f"{passed_count}/{len(gates)}", "yellow")
            print(f"     Gates: {label} (use --detail for breakdown)")

        actionable.append({
            "entry": entry,
            "spec": spec,
            "entry_price": entry_price,
            "income": income,
            "pop": pop,
            "breakevens": be,
            "entry_check": entry_check,
            "regime": regime,
            "technicals": tech,
        })

    # ==============================================================
    # STEP 7: Final Recommendations (HIGH CONFIDENCE ONLY)
    # ==============================================================
    _sep("STEP 7: Actionable Trades")

    # Show current gate thresholds
    print(f"\n  High-confidence gates:")
    print(f"    1. Entry confirmed   — regime + RSI + DTE + ATR all green")
    print(f"    2. POP               >= {eff_min_pop:.0%}")
    print(f"    3. Expected value    > $0")
    print(f"    4. Ranking score     >= {eff_min_score:.2f}")
    print(f"    5. Credit/width      >= {eff_min_cw:.0%}")

    # Apply gates using the same scorecard function
    best = []
    for t in actionable:
        gates = _gate_scorecard(t, **gate_kwargs)
        if all(g["passed"] for g in gates):
            best.append(t)

    if not best:
        print(f"\n  No trades meet all 5 gates ({len(actionable)} analyzed).\n")
        # Show per-trade gate failures
        for t in actionable:
            spec = t["spec"]
            gates = _gate_scorecard(t, **gate_kwargs)
            failed = [g for g in gates if not g["passed"]]
            reasons = [f"{g['name']} ({g['actual']})" for g in failed]
            print(f"  {spec.ticker:6s} {spec.strategy_badge:28s} FAILED: {', '.join(reasons)}")

        # Show nearest miss
        near_misses = []
        for t in actionable:
            gates = _gate_scorecard(t, **gate_kwargs)
            fail_count = sum(1 for g in gates if not g["passed"])
            near_misses.append((fail_count, t))
        near_misses.sort(key=lambda x: x[0])

        if near_misses:
            closest_fails, closest = near_misses[0]
            spec = closest["spec"]
            print(f"\n  Nearest miss: {spec.ticker} {spec.strategy_badge} ({closest_fails} gate(s) failed)")
            gates = _gate_scorecard(closest, **gate_kwargs)
            for g in gates:
                if not g["passed"]:
                    print(f"    [X] {g['name']}: need {g['threshold']}, got {g['actual']}")

        print(f"\n  Discipline = capital preservation. No forced trades.")
        return

    print(f"\n  {len(best)} trade(s) ready for execution:\n")
    for i, t in enumerate(best[:MAX_POSITIONS], 1):
        spec = t["spec"]
        pop = t["pop"]
        income = t["income"]
        regime = t["regime"]
        price = t["technicals"].current_price

        print(f"  +-- TRADE #{i}: {spec.ticker} {spec.strategy_badge}")
        print(f"  |  Price: ${price:.2f} | Regime: {_regime_label(regime.regime)} ({regime.confidence:.0%})")
        print(f"  |  Legs:")
        for code in spec.leg_codes:
            print(f"  |    {code}")

        if income:
            print(f"  |  Credit: ${t['entry_price']:.2f}/spread | Max profit: ${income.max_profit:.0f} | Max loss: ${income.max_loss:.0f}")
        if pop:
            print(f"  |  POP: {pop.pop_pct:.0%} | EV: ${pop.expected_value:.0f}")
        if t["breakevens"]:
            be = t["breakevens"]
            be_str = f"${be.low:.2f}" if be.low else "n/a"
            be_str += f" -- ${be.high:.2f}" if be.high else ""
            print(f"  |  Breakevens: {be_str}")

        print(f"  |  Exit: {spec.exit_summary}")
        contracts = spec.position_size(capital=ACCOUNT_SIZE)
        print(f"  |  Suggested contracts: {contracts}")
        print(f"  +--")

    # ==============================================================
    # STEP 8: Position Monitoring Example
    # ==============================================================
    if best:
        _sep("STEP 8: Exit Monitoring (example)")
        t = best[0]
        spec = t["spec"]
        regime = t["regime"]

        # Simulate a position at 30% profit
        sim_mid = t["entry_price"] * 0.70 if spec.order_side == "credit" else t["entry_price"] * 1.30

        result = monitor_exit_conditions(
            trade_id=f"{spec.ticker}-{spec.strategy_symbol}-001",
            ticker=spec.ticker,
            structure_type=spec.structure_type or "iron_condor",
            order_side=spec.order_side or "credit",
            entry_price=t["entry_price"],
            current_mid_price=sim_mid,
            contracts=1,
            dte_remaining=spec.target_dte or 30,
            regime_id=regime.regime,
            profit_target_pct=spec.profit_target_pct or 0.50,
            stop_loss_pct=spec.stop_loss_pct or 2.0,
            exit_dte=spec.exit_dte or 21,
        )

        print(f"\n  Simulated position: {spec.ticker} {spec.strategy_badge}")
        print(f"  Entry: ${t['entry_price']:.2f} | Current: ${sim_mid:.2f} | P&L: {result.pnl_pct:.0%} ({result.pnl_dollars:+,.0f}$)")
        print(f"  Action: {'CLOSE' if result.should_close else 'HOLD'}")
        print(f"  Commentary: {result.commentary}")
        for s in result.signals:
            flag = ">>" if s.triggered else "  "
            print(f"    {flag} {s.rule}: {s.detail}")

    print(f"\n{'=' * 60}")
    src = "TastyTrade + yfinance" if broker and market_data else "yfinance (historical only)"
    print(f"  Data source: {src}")
    if not broker:
        print(f"  [!] Run with --broker for live quotes and universe scanning")
        print(f"  [!] Run with --broker --preset income for dynamic universe")
    print(f"{'=' * 60}")


def main():
    parser = argparse.ArgumentParser(description="$30K Options Trader -- Proof of Concept")
    parser.add_argument("--tickers", nargs="+", default=None, help="Explicit tickers (skips universe scan)")
    parser.add_argument("--broker", action="store_true", help="Connect to TastyTrade for live quotes")
    parser.add_argument("--paper", action="store_true", help="Use paper trading account")
    parser.add_argument(
        "--preset",
        choices=list(PRESETS.keys()),
        default=None,
        help="Universe filter preset: income, directional, high_vol, broad",
    )
    parser.add_argument("--save", default=None, help="Save filtered universe as TastyTrade watchlist")
    parser.add_argument("--detail", action="store_true", help="Show per-trade gate scorecard in Step 6")
    parser.add_argument("--min-pop", type=float, default=None, help=f"Override min POP threshold (default {HC_MIN_POP:.0%})")
    parser.add_argument("--min-score", type=float, default=None, help=f"Override min ranking score (default {HC_MIN_SCORE})")
    parser.add_argument("--min-credit-width", type=float, default=None, help=f"Override min credit/width (default {HC_MIN_CREDIT_WIDTH:.0%})")
    args = parser.parse_args()

    run(
        tickers=args.tickers,
        broker=args.broker,
        paper=args.paper,
        preset=args.preset,
        save_watchlist=args.save,
        detail=args.detail,
        min_pop=args.min_pop,
        min_score=args.min_score,
        min_credit_width=args.min_credit_width,
    )


if __name__ == "__main__":
    main()
