"""Systematic Options Trader -- End-to-End Reference Flow.

Demonstrates the COMPLETE trading workflow using ALL market_analyzer APIs.
This is the reference implementation for eTrading integration.

Flow:
    1. Market context -- Is today safe to trade?
    2. Universe scan -- Dynamic ticker selection
    3. Full analysis -- Regime + technicals + levels + fundamentals
    4. Rank opportunities -- Score trades (with IV rank + debug commentary)
    5. Account filtering -- BP, structure, risk limits
    6. Execution quality -- Bid-ask spread, OI, volume gate
    7. Trade analytics -- Yield, POP (with IV), breakevens, entry check
    8. Final recommendations -- High-confidence gate scorecard
    9. Position monitoring -- Exit signals + overnight risk + health check

Usage::

    .venv_312/Scripts/python.exe challenge/trader.py
    .venv_312/Scripts/python.exe challenge/trader.py --broker
    .venv_312/Scripts/python.exe challenge/trader.py --broker --preset income
    .venv_312/Scripts/python.exe challenge/trader.py --tickers GLD SPY QQQ
    .venv_312/Scripts/python.exe challenge/trader.py --broker --detail --debug
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
    validate_execution_quality,
)
from market_analyzer.cli._broker import _styled, connect_broker
from market_analyzer.models.universe import PRESETS
from market_analyzer.trade_lifecycle import (
    assess_overnight_risk,
    check_income_entry,
    check_trade_health,
    compute_breakevens,
    compute_income_yield,
    estimate_pop,
    filter_trades_by_account,
    monitor_exit_conditions,
)

# -- Configuration --

ACCOUNT_SIZE = 30_000
MAX_POSITIONS = 5
MAX_RISK_PER_TRADE_PCT = 0.05
BP_RESERVE_PCT = 0.20
DEFAULT_TICKERS = ["SPX", "GLD", "QQQ", "TLT", "IWM", "AAPL"]

HC_MIN_POP = 0.50
HC_MIN_SCORE = 0.60
HC_MIN_CREDIT_WIDTH = 0.10

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


def _gate_scorecard(t: dict, min_pop: float, min_score: float, min_credit_width: float) -> list[dict]:
    """Evaluate high-confidence gates for a trade."""
    entry_check = t["entry_check"]
    pop = t["pop"]
    income = t["income"]
    score = t["entry"].composite_score

    gates = [
        {"name": "Entry confirmed", "threshold": "all conditions green",
         "actual": f"score={entry_check.score:.2f}",
         "passed": entry_check.confirmed},
        {"name": "POP", "threshold": f">= {min_pop:.0%}",
         "actual": f"{pop.pop_pct:.0%}" if pop else "unavailable",
         "passed": pop is not None and pop.pop_pct >= min_pop},
        {"name": "Expected value", "threshold": "> $0",
         "actual": f"${pop.expected_value:.0f}" if pop else "unavailable",
         "passed": pop is not None and pop.expected_value > 0},
        {"name": "Ranking score", "threshold": f">= {min_score:.2f}",
         "actual": f"{score:.2f}",
         "passed": score >= min_score},
    ]

    if income is not None:
        gates.append({"name": "Credit/width", "threshold": f">= {min_credit_width:.0%}",
                       "actual": f"{income.credit_to_width_pct:.1%}",
                       "passed": income.credit_to_width_pct >= min_credit_width})
    else:
        gates.append({"name": "Credit/width", "threshold": f">= {min_credit_width:.0%}",
                       "actual": "n/a", "passed": True})

    return gates


def run(
    tickers: list[str] | None = None,
    broker: bool = False,
    paper: bool = False,
    preset: str | None = None,
    save_watchlist: str | None = None,
    detail: bool = False,
    debug: bool = False,
    min_pop: float | None = None,
    min_score: float | None = None,
    min_credit_width: float | None = None,
):
    """Execute the full systematic trading workflow."""

    eff_min_pop = min_pop if min_pop is not None else HC_MIN_POP
    eff_min_score = min_score if min_score is not None else HC_MIN_SCORE
    eff_min_cw = min_credit_width if min_credit_width is not None else HC_MIN_CREDIT_WIDTH
    gate_kwargs = {"min_pop": eff_min_pop, "min_score": eff_min_score, "min_credit_width": eff_min_cw}

    print(f"{'=' * 60}")
    print(f"  SYSTEMATIC OPTIONS TRADER -- {date.today().isoformat()}")
    print(f"  Account: ${ACCOUNT_SIZE:,} | Max positions: {MAX_POSITIONS}")
    print(f"  Risk/trade: {MAX_RISK_PER_TRADE_PCT:.0%} (${ACCOUNT_SIZE * MAX_RISK_PER_TRADE_PCT:,.0f})")
    print(f"{'=' * 60}")

    # -- Build MarketAnalyzer --
    ds = DataService()
    ma_kwargs: dict = {"data_service": ds}
    market_data = market_metrics = account_provider = watchlist_provider = None

    if broker:
        try:
            market_data, market_metrics, account_provider, watchlist_provider = connect_broker(is_paper=paper)
            ma_kwargs.update(market_data=market_data, market_metrics=market_metrics,
                             account_provider=account_provider, watchlist_provider=watchlist_provider)
        except Exception as e:
            print(_styled(f"Broker connection failed: {e}", "yellow"))

    ma = MarketAnalyzer(**ma_kwargs)

    # ==============================================================
    # STEP 1: Market Context + Macro Events
    # ==============================================================
    _sep("STEP 1: Market Context")

    macro_events_today = False
    has_earnings_map: dict[str, bool] = {}

    try:
        ctx = ma.context.assess(debug=debug)
        print(f"  Environment: {ctx.environment_label}")
        print(f"  Trading:     {'ALLOWED' if ctx.trading_allowed else 'BLOCKED'}")
        print(f"  Size factor: {ctx.position_size_factor}")

        if debug and ctx.commentary:
            for line in ctx.commentary:
                print(f"    [debug] {line}")

        alert = ma.black_swan.alert()
        print(f"  Black Swan:  {alert.alert_level} (score={alert.composite_score:.2f})")
        if alert.alert_level in ("critical", "high"):
            print("\n  [!!] BLACK SWAN ALERT -- NO TRADING TODAY")
            return

        # Check macro calendar
        try:
            macro = ma.macro.calendar()
            today_events = [e for e in macro.events if e.date == date.today()]
            if today_events:
                macro_events_today = True
                print(f"  Macro today: {', '.join(e.name for e in today_events)}")
            upcoming = [e for e in macro.events if e.date > date.today()][:3]
            if upcoming:
                print(f"  Upcoming:    {', '.join(f'{e.name} ({e.date})' for e in upcoming)}")
        except Exception:
            pass

    except Exception as e:
        print(f"  Context failed: {e} — proceeding with caution")

    # ==============================================================
    # STEP 2: Universe Scan
    # ==============================================================
    if tickers:
        scan_tickers = list(tickers)
        print(f"\n  Tickers: {', '.join(scan_tickers)}")
    elif preset and hasattr(ma, 'universe') and ma.universe.has_broker:
        _sep("STEP 2: Universe Scan")
        result = ma.universe.scan(preset=preset, save_watchlist=save_watchlist)
        scan_tickers = [c.ticker for c in result.candidates] if result.candidates else list(DEFAULT_TICKERS)
        print(f"  Scanned: {result.total_scanned} | Passed: {result.total_passed}")
        for c in result.candidates[:10]:
            iv = f"IV={c.iv_rank:.0f}" if c.iv_rank is not None else "IV=?"
            print(f"    {c.ticker:6s} {iv}")
    else:
        scan_tickers = list(DEFAULT_TICKERS)
        print(f"\n  Default tickers: {', '.join(scan_tickers)}")

    # ==============================================================
    # STEP 3: Full Analysis -- Regime + Technicals + Levels + Fundamentals
    # ==============================================================
    _sep(f"STEP 3: Analysis ({len(scan_tickers)} tickers)")

    analyses: dict[str, dict] = {}
    for ticker in scan_tickers:
        try:
            regime = ma.regime.detect(ticker, debug=debug)
            tech = ma.technicals.snapshot(ticker, debug=debug)

            # Levels for strike alignment
            levels = None
            try:
                levels = ma.levels.analyze(ticker)
            except Exception:
                pass

            # Fundamentals for earnings proximity
            fundamentals = None
            has_earnings = False
            try:
                fundamentals = ma.fundamentals.get(ticker)
                if fundamentals and fundamentals.next_earnings_date:
                    days_to_earn = (fundamentals.next_earnings_date - date.today()).days
                    has_earnings = 0 < days_to_earn <= 14
                    has_earnings_map[ticker] = has_earnings
            except Exception:
                pass

            # IV rank from broker
            iv_rank = None
            if broker and hasattr(ma, 'quotes') and ma.quotes.has_broker:
                try:
                    metrics = ma.quotes.get_metrics(ticker)
                    iv_rank = metrics.iv_rank if metrics else None
                except Exception:
                    pass

            analyses[ticker] = {
                "regime": regime, "technicals": tech, "levels": levels,
                "fundamentals": fundamentals, "iv_rank": iv_rank,
            }

            # Display
            staleness = ""
            if regime.model_age_days and regime.model_age_days > 30:
                staleness = f" [stale {regime.model_age_days}d]"
            stability = ""
            if regime.regime_stability and regime.regime_stability > 4:
                stability = f" [unstable]"
            iv_str = f"  IV={iv_rank:.0f}" if iv_rank is not None else ""
            earn_str = " [EARNINGS]" if has_earnings else ""

            print(
                f"  {ticker:6s}  {_regime_label(regime.regime)} ({regime.confidence:.0%})"
                f"  RSI {tech.rsi.value:.0f}  ATR {tech.atr_pct:.2f}%"
                f"  ${tech.current_price:.2f}{iv_str}{staleness}{stability}{earn_str}"
            )

            # New TA indicators
            if detail and tech.adx:
                print(f"          ADX {tech.adx.adx:.0f} ({'trending' if tech.adx.is_trending else 'ranging'})"
                      f"  +DI={tech.adx.plus_di:.0f} -DI={tech.adx.minus_di:.0f}")
            if detail and tech.fibonacci:
                fib = tech.fibonacci
                print(f"          Fib: {fib.direction} swing ${fib.swing_low:.0f}-${fib.swing_high:.0f}"
                      f"  50%=${fib.level_500:.2f}  price at {fib.current_price_level}")
            if detail and tech.keltner and tech.keltner.squeeze:
                print(f"          ** KELTNER SQUEEZE detected ** (volatility compression)")

            # Debug commentary
            if debug and regime.commentary:
                for line in regime.commentary[:3]:
                    print(f"    [debug] {line}")
            # Data gaps
            if regime.data_gaps:
                for gap in regime.data_gaps:
                    print(f"    [gap] {gap.field}: {gap.reason} ({gap.impact})")

        except Exception as e:
            print(f"  {ticker:6s}  FAILED: {e}")

    if not analyses:
        print("\n  No tickers analyzed. Exiting.")
        return

    # ==============================================================
    # STEP 4: Rank Opportunities (with IV rank + debug)
    # ==============================================================
    _sep("STEP 4: Rank Opportunities")

    try:
        ranking_result = ma.ranking.rank(list(analyses.keys()), skip_intraday=True, debug=debug)
        raw_trades = ranking_result.top_trades
        print(f"  {len(raw_trades)} ranked trades across {len(analyses)} tickers")
        for e in raw_trades[:10]:
            sym = e.trade_spec.strategy_badge if e.trade_spec else e.strategy_type
            gaps_str = f" [{len(e.data_gaps)} gaps]" if e.data_gaps else ""
            print(f"    #{e.rank:2d} {e.ticker:6s} {sym:28s} score={e.composite_score:.2f}  {e.verdict}{gaps_str}")

            if debug and e.commentary:
                for line in e.commentary[:2]:
                    print(f"         [debug] {line}")
    except Exception as e:
        print(f"  Ranking failed: {e}")
        return

    # ==============================================================
    # STEP 5: Account Filtering
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

    print(f"  Passed: {filtered.total_affordable} | Blocked: {len(filtered.filtered_out)}")

    if not filtered.affordable:
        print("\n  No trades pass account constraints. Exiting.")
        return

    affordable_keys = {(r["ticker"], r["structure_type"]) for r in filtered.affordable}
    passed_entries = [
        e for e in raw_trades
        if e.trade_spec and (e.ticker, e.trade_spec.structure_type) in affordable_keys
    ]

    # ==============================================================
    # STEP 6: Execution Quality Gate (NEW)
    # ==============================================================
    _sep("STEP 6: Execution Quality")

    quality_passed = []
    for entry in passed_entries[:10]:
        spec = entry.trade_spec
        if spec is None:
            continue

        # Get quotes for legs (requires broker)
        if broker and hasattr(ma, 'quotes') and ma.quotes.has_broker:
            try:
                leg_quotes = ma.quotes.get_leg_quotes(spec.legs, spec.ticker)
                quality = validate_execution_quality(spec, leg_quotes)

                if quality.tradeable:
                    quality_passed.append(entry)
                    print(f"  {spec.ticker:6s} {spec.strategy_symbol:4s}  GO (spread cost {quality.total_spread_cost_pct:.1f}%)")
                else:
                    print(f"  {spec.ticker:6s} {spec.strategy_symbol:4s}  {quality.overall_verdict.upper()}: {quality.summary}")
            except Exception:
                quality_passed.append(entry)  # No quotes = skip gate, don't block
                print(f"  {spec.ticker:6s} {spec.strategy_symbol:4s}  SKIP (no quotes)")
        else:
            quality_passed.append(entry)  # No broker = skip gate
            print(f"  {spec.ticker:6s} {spec.strategy_symbol:4s}  SKIP (no broker)")

    if not quality_passed:
        print("\n  No trades pass execution quality. Exiting.")
        return

    # ==============================================================
    # STEP 7: Trade Analytics
    # ==============================================================
    _sep("STEP 7: Trade Analytics")

    actionable = []
    for entry in quality_passed[:8]:
        spec = entry.trade_spec
        if spec is None:
            continue

        ticker = spec.ticker
        data = analyses.get(ticker)
        if data is None:
            continue

        regime = data["regime"]
        tech = data["technicals"]
        iv_rank = data.get("iv_rank")
        price = tech.current_price

        print(f"\n  -- {ticker} {spec.strategy_badge} --")
        print(f"     Legs: {' | '.join(spec.leg_codes)}")

        # Entry window
        if spec.entry_window_start:
            print(f"     Entry window: {spec.entry_window_start.strftime('%H:%M')} - "
                  f"{spec.entry_window_end.strftime('%H:%M') if spec.entry_window_end else 'close'}")

        # Entry price
        entry_price = spec.max_entry_price
        if entry_price is None:
            wing = spec.wing_width_points or 5.0
            entry_price = wing * 0.15 if spec.order_side == "credit" else wing * 0.40

        # Income yield
        income = compute_income_yield(spec, entry_credit=entry_price)
        if income:
            print(f"     Yield: credit/width={income.credit_to_width_pct:.1%} ROC={income.return_on_capital_pct:.1%} ann={income.annualized_roc_pct:.1%}")

        # POP (with IV rank)
        pop = estimate_pop(spec, entry_price=entry_price, regime_id=regime.regime,
                           atr_pct=tech.atr_pct, current_price=price, iv_rank=iv_rank)
        if pop:
            iv_note = f" [IV-adjusted]" if iv_rank is not None else " [ATR-only]"
            print(f"     POP: {pop.pop_pct:.0%} EV=${pop.expected_value:.0f}{iv_note}")
            if pop.data_gaps:
                for gap in pop.data_gaps:
                    print(f"       [gap] {gap.reason}")

        # Breakevens
        be = compute_breakevens(spec, entry_price=entry_price)
        if be:
            parts = []
            if be.low:
                parts.append(f"low=${be.low:.2f}")
            if be.high:
                parts.append(f"high=${be.high:.2f}")
            print(f"     Breakevens: {', '.join(parts)}")

        # Income entry check (with REAL earnings + macro flags)
        has_earnings = has_earnings_map.get(ticker, False)
        entry_check = check_income_entry(
            iv_rank=iv_rank, iv_percentile=None,
            dte=spec.target_dte or 30, rsi=tech.rsi.value, atr_pct=tech.atr_pct,
            regime_id=regime.regime,
            has_earnings_within_dte=has_earnings,
            has_macro_event_today=macro_events_today,
        )
        status = "[OK] CONFIRMED" if entry_check.confirmed else "[X] NOT CONFIRMED"
        print(f"     Entry: {status} (score={entry_check.score:.2f})")

        # Exit rules
        print(f"     Exit:  {spec.exit_summary}")

        # Gate scorecard
        gates = _gate_scorecard({"entry_check": entry_check, "pop": pop, "income": income,
                                  "entry": entry, "spec": spec}, **gate_kwargs)
        all_passed = all(g["passed"] for g in gates)

        if detail:
            verdict_str = _styled("PASS", "green") if all_passed else _styled("FAIL", "red")
            print(f"     --- Gates: {verdict_str} ---")
            for g in gates:
                icon = "[OK]" if g["passed"] else "[X] "
                print(f"       {icon} {g['name']:18s}  need {g['threshold']:20s}  got {g['actual']}")
        else:
            passed_count = sum(1 for g in gates if g["passed"])
            label = _styled("PASS", "green") if all_passed else _styled(f"{passed_count}/{len(gates)}", "yellow")
            print(f"     Gates: {label}")

        actionable.append({
            "entry": entry, "spec": spec, "entry_price": entry_price,
            "income": income, "pop": pop, "breakevens": be,
            "entry_check": entry_check, "regime": regime, "technicals": tech,
        })

    # ==============================================================
    # STEP 8: Final Recommendations
    # ==============================================================
    _sep("STEP 8: Actionable Trades")

    best = [t for t in actionable
            if all(g["passed"] for g in _gate_scorecard(t, **gate_kwargs))]

    if not best:
        print(f"\n  No trades meet all gates ({len(actionable)} analyzed).")
        for t in actionable:
            gates = _gate_scorecard(t, **gate_kwargs)
            failed = [g for g in gates if not g["passed"]]
            reasons = [f"{g['name']} ({g['actual']})" for g in failed]
            print(f"  {t['spec'].ticker:6s} {t['spec'].strategy_badge:28s} FAILED: {', '.join(reasons)}")
        print(f"\n  Discipline = capital preservation. No forced trades.")
        return

    print(f"\n  {len(best)} trade(s) ready:\n")
    for i, t in enumerate(best[:MAX_POSITIONS], 1):
        spec = t["spec"]
        pop = t["pop"]
        income = t["income"]
        regime = t["regime"]
        price = t["technicals"].current_price

        print(f"  +-- TRADE #{i}: {spec.ticker} {spec.strategy_badge}")
        print(f"  |  Price: ${price:.2f} | Regime: {_regime_label(regime.regime)} ({regime.confidence:.0%})")
        for code in spec.leg_codes:
            print(f"  |    {code}")
        if income:
            print(f"  |  Credit: ${t['entry_price']:.2f} | Max P: ${income.max_profit:.0f} | Max L: ${income.max_loss:.0f}")
        if pop:
            print(f"  |  POP: {pop.pop_pct:.0%} | EV: ${pop.expected_value:.0f}")
        print(f"  |  Exit: {spec.exit_summary}")
        contracts = spec.position_size(capital=ACCOUNT_SIZE)
        print(f"  |  Contracts: {contracts}")
        if spec.entry_window_start:
            print(f"  |  Entry window: {spec.entry_window_start.strftime('%H:%M')}-{spec.entry_window_end.strftime('%H:%M') if spec.entry_window_end else 'close'}")
        print(f"  +--")

    # ==============================================================
    # STEP 9: Position Monitoring (Simulated)
    # ==============================================================
    if best:
        _sep("STEP 9: Position Monitoring")
        t = best[0]
        spec = t["spec"]
        regime = t["regime"]
        tech = t["technicals"]

        sim_mid = t["entry_price"] * 0.70 if spec.order_side == "credit" else t["entry_price"] * 1.30

        # Full health check (includes exit monitoring + adjustment + overnight risk)
        health = check_trade_health(
            trade_id=f"{spec.ticker}-{spec.strategy_symbol}-001",
            trade_spec=spec,
            entry_price=t["entry_price"],
            contracts=1,
            current_mid_price=sim_mid,
            dte_remaining=spec.target_dte or 30,
            regime=regime,
            technicals=tech,
            entry_regime_id=int(regime.regime),
            time_of_day=dt_time(15, 30),  # Simulate EOD check
        )

        print(f"\n  Simulated: {spec.ticker} {spec.strategy_badge}")
        print(f"  Status: {health.status.upper()} | Action: {health.overall_action}")
        print(f"  P&L: {health.exit_result.pnl_pct:.0%} ({health.exit_result.pnl_dollars:+,.0f}$)")
        print(f"  Commentary: {health.commentary}")

        # Overnight risk
        if health.overnight_risk:
            risk = health.overnight_risk
            color = "red" if risk.risk_level in ("high", "close_before_close") else "yellow" if risk.risk_level == "medium" else "green"
            print(f"  Overnight: {_styled(risk.risk_level.upper(), color)}")
            for r in risk.reasons:
                print(f"    - {r}")

        # Exit signals
        for s in health.exit_result.signals:
            flag = ">>" if s.triggered else "  "
            print(f"    {flag} {s.rule}: {s.detail[:80]}")

    # ==============================================================
    # Summary
    # ==============================================================
    print(f"\n{'=' * 60}")
    src = "TastyTrade + yfinance" if broker and market_data else "yfinance (historical only)"
    print(f"  Data: {src}")
    if not broker:
        print(f"  [!] --broker for live quotes, execution quality, IV rank")
    print(f"{'=' * 60}")


def main():
    parser = argparse.ArgumentParser(description="Systematic Options Trader")
    parser.add_argument("--tickers", nargs="+", default=None)
    parser.add_argument("--broker", action="store_true")
    parser.add_argument("--paper", action="store_true")
    parser.add_argument("--preset", choices=list(PRESETS.keys()), default=None)
    parser.add_argument("--save", default=None)
    parser.add_argument("--detail", action="store_true")
    parser.add_argument("--debug", action="store_true", help="Show calculation commentary")
    parser.add_argument("--min-pop", type=float, default=None)
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument("--min-credit-width", type=float, default=None)
    args = parser.parse_args()

    run(
        tickers=args.tickers, broker=args.broker, paper=args.paper,
        preset=args.preset, save_watchlist=args.save,
        detail=args.detail, debug=args.debug,
        min_pop=args.min_pop, min_score=args.min_score,
        min_credit_width=args.min_credit_width,
    )


if __name__ == "__main__":
    main()
