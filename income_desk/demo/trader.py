"""Trader — end-to-end trading simulation runner.

Two pre-built traders:
1. US Income Trader — $100K, moderate risk, SPY/QQQ/IWM/GLD/TLT
2. India Income Trader — ₹50L (INR), moderate risk, NIFTY/BANKNIFTY

Each trader runs the full pipeline:
  Create portfolio → Allocate desks → Scan universe → Rank → Validate →
  Size → Route to desk → Book → Monitor → Exit

Usage:
    from income_desk.demo.trader import run_us_trader, run_india_trader

    # CLI:
    income-desk --sim income --trader us
    income-desk --sim india_trading --trader india

    # Python:
    report = run_us_trader()
    report = run_india_trader()
"""
from __future__ import annotations

from pydantic import BaseModel

from income_desk.adapters.simulated import (
    SimulatedMarketData,
    SimulatedMetrics,
    create_ideal_income,
    create_india_trading,
)
from income_desk.demo.portfolio import add_demo_position, create_demo_portfolio


class TraderReport(BaseModel):
    """Complete report from a trading simulation run."""

    market: str              # "US" or "India"
    capital: float
    risk_tolerance: str

    # Phase 1: Setup
    desks_created: int
    desk_summary: list[dict]

    # Phase 2: Scan & Rank
    tickers_scanned: list[str]
    regime_summary: dict[str, int]    # {ticker: regime_id}
    candidates_ranked: int

    # Phase 3: Trade Selection
    trades_evaluated: int
    trades_passed_validation: int
    trades_booked: int
    trades_blocked: list[dict]        # [{ticker, reason}]

    # Phase 4: Portfolio State
    positions: list[dict]
    total_risk_deployed: float
    risk_pct: float
    cash_remaining: float

    # Phase 5: Monitoring (simulated day 10)
    monitoring_results: list[dict]    # [{ticker, action, urgency, reason}]

    # Phase 6: Summary
    sentinel_signal: str              # GREEN/YELLOW/ORANGE/RED/BLUE
    trust_summary: str
    overall_summary: str


def run_trader(
    market: str = "US",
    capital: float = 100_000,
    risk_tolerance: str = "moderate",
    sim: SimulatedMarketData | None = None,
    max_trades: int = 5,
    ma: "MarketAnalyzer | None" = None,
) -> TraderReport:
    """Run complete trading simulation end-to-end.

    This is the DEMO runner. Shows the full income-desk pipeline
    from setup to monitoring, with real validation gates and sizing.

    Pass ``ma`` to use a pre-built MarketAnalyzer (e.g. with live
    broker data).  When *ma* is provided, *sim* is only used for
    ``iv_rank`` lookups; if *sim* is ``None`` a default is created so
    those lookups don't crash.
    """
    from income_desk import DataService, MarketAnalyzer
    from income_desk.features.crash_sentinel import assess_crash_sentinel
    from income_desk.features.data_trust import compute_trust_report
    from income_desk.features.desk_management import suggest_desk_for_trade
    from income_desk.features.exit_intelligence import (
        compute_regime_stop,
        compute_remaining_theta_value,
        compute_time_adjusted_target,
    )
    from income_desk.features.position_sizing import compute_position_size
    from income_desk.trade_lifecycle import estimate_pop
    from income_desk.validation import run_daily_checks

    # ── Phase 1: Setup ───────────────────────────────────────────────────────
    if ma is None:
        # No pre-built analyzer — fall back to simulated data
        if sim is None:
            if market == "India":
                sim = create_india_trading()
            else:
                sim = create_ideal_income()

        ma = MarketAnalyzer(
            data_service=DataService(),
            market_data=sim,
            market_metrics=SimulatedMetrics(sim),
        )
    else:
        # Pre-built MA (live broker). Still need a sim for iv_rank fallback.
        if sim is None:
            sim = create_india_trading() if market == "India" else create_ideal_income()

    port = create_demo_portfolio(capital, risk_tolerance, market)

    desks_created = len(port.desks)
    desk_summary = [
        {
            "desk_key": d.get("desk_key", ""),
            "capital": d.get("capital_allocation", 0),
            "strategy_types": d.get("strategy_types", []),
            "max_positions": d.get("max_positions", 10),
        }
        for d in port.desks
    ]

    # ── Phase 2: Scan & Rank ─────────────────────────────────────────────────
    if market == "India":
        tickers = ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK"]
    else:
        tickers = ["SPY", "QQQ", "IWM", "GLD", "TLT"]

    regimes: dict[str, int] = {}
    for t in tickers:
        try:
            r = ma.regime.detect(t)
            regimes[t] = r.regime.value
        except Exception:
            regimes[t] = 0  # Unknown — skip safely

    # Filter R4 tickers (trending with high vol — no income plays)
    tradeable = [t for t in tickers if regimes.get(t, 4) in (1, 2, 3)]

    candidates_ranked = 0
    ranking = None
    if tradeable:
        iv_rank_map = {
            t: sim._tickers.get(t, {}).get("iv_rank", 0) for t in tradeable
        }
        try:
            ranking = ma.ranking.rank(
                tradeable, skip_intraday=True, iv_rank_map=iv_rank_map
            )
            candidates_ranked = len(ranking.top_trades) if ranking else 0
        except Exception:
            ranking = None

    # ── Phase 3: Evaluate & Book ─────────────────────────────────────────────
    booked: list[dict] = []
    blocked: list[dict] = []
    trades_evaluated = 0
    trades_passed_validation = 0

    top_trades = ranking.top_trades if ranking else []

    for entry in top_trades:
        if len(booked) >= max_trades:
            break
        if entry.trade_spec is None:
            continue
        # Dedup by ticker
        if entry.ticker in [b["ticker"] for b in booked]:
            continue

        trades_evaluated += 1
        ticker = entry.ticker
        ts = entry.trade_spec

        # Get entry price: credit for option spreads, price for equity
        st = ts.structure_type or ""
        if st in ("equity_long", "equity_short"):
            # Equity trade: entry_price is the stock price, no "credit"
            credit = ts.underlying_price or sim.get_underlying_price(ticker) or 100.0
        elif ts.legs:
            try:
                lqs = sim.get_quotes(ts.legs, ticker=ticker)
                credit = 0.0
                for leg, lq in zip(ts.legs, lqs):
                    if lq is None:
                        continue
                    mid = lq.mid if lq.mid is not None else 0.0
                    action_str = getattr(leg.action, 'value', str(leg.action))
                    if action_str == "STO":
                        credit += mid
                    else:
                        credit -= mid
                credit = abs(round(credit, 2))
            except Exception:
                credit = 0.0
        else:
            credit = 0.0

        if st not in ("equity_long", "equity_short") and credit < 0.50:
            blocked.append({"ticker": ticker, "reason": f"credit too low (${credit:.2f})"})
            continue

        # Get technicals for validation
        try:
            tech = ma.technicals.snapshot(ticker)
            atr_pct = tech.atr_pct if tech and tech.atr_pct else 1.0
            rsi = tech.rsi if tech and tech.rsi else 50.0
            current_price = tech.current_price if tech and tech.current_price else sim.get_underlying_price(ticker) or 100.0
        except Exception:
            atr_pct = 1.0
            rsi = 50.0
            current_price = sim.get_underlying_price(ticker) or 100.0

        regime_id = regimes.get(ticker, 1)
        iv_rank = sim._tickers.get(ticker, {}).get("iv_rank", 50.0)

        # Run validation
        try:
            rpt = run_daily_checks(
                ticker=ticker,
                trade_spec=ts,
                entry_credit=credit,
                regime_id=regime_id,
                atr_pct=atr_pct,
                current_price=current_price,
                avg_bid_ask_spread_pct=0.05,
                dte=ts.target_dte,
                rsi=rsi,
                iv_rank=iv_rank,
                contracts=1,
            )
        except Exception:
            rpt = None

        if rpt is not None and not rpt.is_ready:
            fails = [c.name for c in rpt.checks if c.severity.value == "fail"]
            blocked.append({"ticker": ticker, "reason": f"validation: {', '.join(fails)}"})
            continue

        trades_passed_validation += 1

        # Estimate POP
        try:
            pop = estimate_pop(
                trade_spec=ts,
                entry_price=credit,
                regime_id=regime_id,
                atr_pct=atr_pct,
                current_price=current_price,
                contracts=1,
                iv_rank=iv_rank,
            )
        except Exception:
            pop = None

        pop_pct = pop.pop_pct if pop else 0.65
        ev = pop.expected_value if pop else credit * 0.3

        # Hard POP floor — no trade booked below 40% POP
        if pop and pop.pop_pct < 0.40:
            blocked.append({"ticker": ticker, "reason": f"POP too low ({pop.pop_pct:.0%})"})
            continue

        # Size the position
        lot_size = ts.lot_size or 100
        if st in ("equity_long", "equity_short"):
            # Equity sizing: risk = 1.5 ATR per lot (stop distance)
            stop_risk = 1.5 * (atr_pct / 100.0) * current_price * lot_size
            target_profit = 2.0 * (atr_pct / 100.0) * current_price * lot_size
            max_risk_per_trade = capital * 0.04  # 4% max risk per trade
            contracts = max(1, int(max_risk_per_trade / stop_risk)) if stop_risk > 0 else 1
            contracts = min(contracts, 5)  # cap
        else:
            wing_width = ts.wing_width_points or 5.0
            max_profit_per = credit * lot_size
            max_loss_per = (wing_width * lot_size) - max_profit_per
            risk_per_contract = max(max_loss_per, 1.0)

            try:
                sz = compute_position_size(
                    pop_pct=pop_pct,
                    max_profit=max_profit_per,
                    max_loss=max_loss_per,
                    capital=capital,
                    risk_per_contract=risk_per_contract,
                    regime_id=regime_id,
                    wing_width=wing_width,
                    safety_factor=0.5,
                    max_contracts=20,
                )
                contracts = sz.recommended_contracts
            except Exception:
                contracts = 1

        if contracts == 0:
            blocked.append({"ticker": ticker, "reason": "Kelly = 0 contracts"})
            continue

        # Route to desk
        desk_result = suggest_desk_for_trade(
            desks=port.desks,
            trade_dte=ts.target_dte,
            strategy_type=str(ts.structure_type or "iron_condor"),
            ticker=ticker,
        )
        desk_key = desk_result["desk_key"] if isinstance(desk_result, dict) else desk_result

        # Book
        try:
            pos = add_demo_position(
                port, ticker, desk_key, ts, credit, contracts, regime_id
            )
        except Exception as e:
            blocked.append({"ticker": ticker, "reason": f"booking error: {e}"})
            continue

        booked.append({
            "ticker": ticker,
            "structure": str(ts.structure_type or "unknown"),
            "contracts": contracts,
            "credit": credit,
            "desk": desk_key,
            "position_id": pos.position_id,
            "pop": pop_pct,
            "ev": ev,
        })

    # ── Phase 4: Portfolio State ──────────────────────────────────────────────
    total_risk = sum(p.max_loss for p in port.positions)
    risk_pct = total_risk / capital if capital > 0 else 0.0

    # ── Phase 5: Monitoring (simulate day 10) ────────────────────────────────
    monitoring: list[dict] = []
    for pos in port.positions:
        try:
            stop = compute_regime_stop(pos.entry_regime_id)
            target = compute_time_adjusted_target(10, pos.dte_at_entry, 0.30)
            theta = compute_remaining_theta_value(
                pos.dte_at_entry - 10, pos.dte_at_entry, 0.30
            )
            monitoring.append({
                "ticker": pos.ticker,
                "position_id": pos.position_id,
                "days_held": 10,
                "profit_pct": 0.30,
                "stop": f"{stop.base_multiplier}x",
                "target": f"{target.adjusted_target_pct:.0%}",
                "theta_action": theta.recommendation,
                "theta_rationale": theta.rationale,
            })
        except Exception:
            monitoring.append({
                "ticker": pos.ticker,
                "position_id": pos.position_id,
                "days_held": 10,
                "profit_pct": 0.30,
                "stop": "2.0x",
                "target": "50%",
                "theta_action": "hold",
                "theta_rationale": "monitoring unavailable",
            })

    # ── Phase 6: Summary ─────────────────────────────────────────────────────
    sentinel = assess_crash_sentinel(
        regime_results={
            t: {"regime_id": regimes.get(t, 1), "confidence": 0.9, "r4_prob": 0.05}
            for t in tickers
        },
        iv_ranks={
            t: sim._tickers.get(t, {}).get("iv_rank", 0) for t in tickers
        },
    )
    sentinel_signal = str(sentinel.signal.value).upper()

    trust = compute_trust_report(
        mode="standalone",
        has_broker=True,
        has_iv_rank=True,
        has_vol_surface=False,
        entry_credit_source="broker",
        regime_confidence=0.9,
    )
    trust_summary = (
        f"{trust.overall_level} (data={trust.data_quality.trust_score:.0%})"
        if hasattr(trust, "data_quality")
        else "RELIABLE (simulated)"
    )

    books = len(booked)
    overall_summary = (
        f"{books} trade(s) booked across {desks_created} desks. "
        f"Risk deployed: ${total_risk:,.0f} ({risk_pct:.1%}). "
        f"Market Safety: {sentinel_signal}."
    )
    if blocked:
        overall_summary += f" {len(blocked)} trade(s) blocked."

    return TraderReport(
        market=market,
        capital=capital,
        risk_tolerance=risk_tolerance,
        desks_created=desks_created,
        desk_summary=desk_summary,
        tickers_scanned=tickers,
        regime_summary={t: regimes.get(t, 0) for t in tickers},
        candidates_ranked=candidates_ranked,
        trades_evaluated=trades_evaluated,
        trades_passed_validation=trades_passed_validation,
        trades_booked=books,
        trades_blocked=blocked,
        positions=booked,
        total_risk_deployed=total_risk,
        risk_pct=risk_pct,
        cash_remaining=port.cash_balance,
        monitoring_results=monitoring,
        sentinel_signal=sentinel_signal,
        trust_summary=trust_summary,
        overall_summary=overall_summary,
    )


def run_us_trader(
    capital: float = 100_000,
    risk_tolerance: str = "moderate",
) -> TraderReport:
    """Run US income trader simulation with ideal income scenario."""
    return run_trader("US", capital, risk_tolerance, create_ideal_income())


def run_india_trader(
    capital: float = 5_000_000,
    risk_tolerance: str = "moderate",
) -> TraderReport:
    """Run India income trader simulation (50 lakh INR)."""
    return run_trader("India", capital, risk_tolerance, create_india_trading())


def print_trader_report(report: TraderReport) -> None:
    """Pretty-print the trader report to console."""
    print(f"\n{'=' * 60}")
    print(f"TRADER REPORT — {report.market} Market")
    print(f"{'=' * 60}")
    print(f"Capital: ${report.capital:,.0f} | Risk: {report.risk_tolerance}")
    print(f"Market Safety: {report.sentinel_signal}")
    print(f"Trust: {report.trust_summary}")

    print(f"\nDESKS ({report.desks_created}):")
    for d in report.desk_summary[:5]:
        print(f"  {d['desk_key']:<28} ${d['capital']:>10,.0f}")

    print(f"\nREGIMES:")
    for t, r in report.regime_summary.items():
        flag = " << SKIP" if r == 4 else ""
        label = f"R{r}" if r > 0 else "?"
        print(f"  {t:<12} {label}{flag}")

    print(f"\nTRADES: {report.trades_booked} booked, {len(report.trades_blocked)} blocked")
    for trade in report.positions:
        pop_str = f"{trade['pop']:.0%}" if isinstance(trade.get("pop"), float) else "n/a"
        print(
            f"  {trade['ticker']:<6} {str(trade['structure']):<20} "
            f"{trade['contracts']}x  ${trade['credit']:.2f}  POP {pop_str}"
            f"  -> {trade['desk']}"
        )

    if report.trades_blocked:
        print(f"\nBLOCKED:")
        for b in report.trades_blocked[:5]:
            print(f"  {b['ticker']:<6} {b['reason']}")

    print(f"\nPORTFOLIO:")
    print(f"  Risk deployed: ${report.total_risk_deployed:,.0f} ({report.risk_pct:.1%})")
    print(f"  Cash remaining: ${report.cash_remaining:,.0f}")

    if report.monitoring_results:
        print(f"\nMONITORING (Day 10 simulation):")
        for m in report.monitoring_results:
            print(
                f"  {m['ticker']:<6} {m.get('theta_action', 'hold'):<20} "
                f"target={m.get('target', '?')}  stop={m.get('stop', '?')}"
            )

    print(f"\n{'=' * 60}")
    print(f"SUMMARY: {report.overall_summary}")
    print(f"{'=' * 60}")
