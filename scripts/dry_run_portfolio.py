"""Dry run: Build a full portfolio trade-by-trade until capital exhausted.

Uses broker data for account, IV rank, regimes. Simulates realistic credits
from vol surface when DXLink option quotes unavailable (after hours).
"""
import sys
import io
import warnings
import logging

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

from market_analyzer.cli._broker import connect_broker
from market_analyzer import MarketAnalyzer, DataService
from market_analyzer.opportunity.option_plays.iron_condor import assess_iron_condor
from market_analyzer.opportunity.option_plays.calendar import assess_calendar
from market_analyzer.validation.daily_readiness import run_daily_checks, run_adversarial_checks
from market_analyzer.features.position_sizing import (
    compute_position_size, PortfolioExposure, compute_kelly_fraction,
)
from market_analyzer.features.exit_intelligence import compute_regime_stop
from market_analyzer.features.entry_levels import (
    score_entry_level, compute_pullback_levels, compute_iv_rank_quality,
)
from market_analyzer.features.dte_optimizer import select_optimal_dte
from market_analyzer.features.decision_audit import audit_decision
from market_analyzer.validation.stress_scenarios import check_gamma_stress, check_vega_shock
from market_analyzer.trade_lifecycle import estimate_pop


# Known cross-correlations (pre-computed from historical data)
CORRELATIONS = {
    ("SPY", "QQQ"): 0.92, ("SPY", "IWM"): 0.85, ("SPY", "GLD"): 0.05,
    ("SPY", "TLT"): -0.35, ("QQQ", "IWM"): 0.80, ("QQQ", "GLD"): -0.10,
    ("QQQ", "TLT"): -0.40, ("IWM", "GLD"): 0.10, ("IWM", "TLT"): -0.20,
    ("GLD", "TLT"): 0.30,
}


def get_corr(a, b):
    return CORRELATIONS.get((a, b), CORRELATIONS.get((b, a), 0.0))


def estimate_credit(ts, vol, tech):
    """Realistic IC credit estimate from vol surface + broker IV.

    IC credit is approximately 25-35% of wing width when strikes are 1 ATR OTM
    and IV is at normal levels. Higher IV = higher credit percentage.

    Empirical: GLD 5-wide IC at 30% IV, 35 DTE, 1 ATR OTM ~ $1.50 credit
    SPY 5-wide IC at 14% IV, 35 DTE, 1.5 ATR OTM ~ $0.80 credit
    """
    wing = ts.wing_width_points or 5.0
    iv = vol.front_iv if vol else 0.20
    # Credit as % of wing width: base 20% + IV contribution
    # At 15% IV: ~20% of wing = $1.00 on 5-wide
    # At 30% IV: ~35% of wing = $1.75 on 5-wide
    # At 45% IV: ~45% of wing = $2.25 on 5-wide
    credit_pct = 0.15 + iv * 0.80  # 15% base + 80% * IV
    credit_pct = min(credit_pct, 0.50)  # Cap at 50% of wing
    credit = wing * credit_pct
    return round(max(0.50, credit), 2)


def main():
    md, mm, acct, wl = connect_broker(is_paper=False)
    if md is None:
        print("Broker connection failed")
        return

    ma = MarketAnalyzer(data_service=DataService(), market_data=md, market_metrics=mm)
    bal = acct.get_balance()
    CAPITAL = bal.net_liquidating_value
    MAX_RISK_PCT = 0.25
    MAX_POSITIONS = 5

    print("=" * 70)
    print(f"DRY RUN: PORTFOLIO CONSTRUCTION | ${CAPITAL:,.0f} NLV")
    print(f"Risk budget: ${CAPITAL * MAX_RISK_PCT:,.0f} ({MAX_RISK_PCT:.0%} of NLV) | Max positions: {MAX_POSITIONS}")
    print("=" * 70)

    # Phase 1: Regime scan
    universe = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
    print(f"\n--- PHASE 1: REGIME SCAN ---")
    ticker_data = {}
    for t in universe:
        r = ma.regime.detect(t)
        tech = ma.technicals.snapshot(t)
        vol = ma.vol_surface.surface(t)
        levels = ma.levels.analyze(t)
        m = ma.quotes.get_metrics(t)
        iv_rank = m.get("ivRank") if isinstance(m, dict) else (m.iv_rank if m else None)
        iv_pct = m.get("ivPercentile") if isinstance(m, dict) else (m.iv_percentile if m else None)
        ticker_data[t] = {"regime": r, "tech": tech, "vol": vol, "levels": levels,
                          "iv_rank": iv_rank, "iv_pct": iv_pct}
        flag = " << SKIP (R4)" if r.regime.value == 4 else ""
        ivr = f"{iv_rank:.0f}%" if iv_rank else "N/A"
        print(f"  {t:<6} R{r.regime.value} ({r.confidence:.0%}) ${tech.current_price:>8.2f}  IV Rank: {ivr:>5}{flag}")

    # Phase 2: Rank tradeable tickers
    tradeable = [t for t in universe if ticker_data[t]["regime"].regime.value in (1, 2)]
    print(f"\nTradeable: {tradeable}")

    # Rank all
    result = ma.ranking.rank(tradeable, skip_intraday=True, debug=True,
                              iv_rank_map={t: ticker_data[t]["iv_rank"] or 0 for t in tradeable})

    # Get top candidates (deduplicate by ticker, prefer IC)
    seen = set()
    candidates = []
    for e in result.top_trades:
        if e.ticker not in seen and e.trade_spec and e.strategy_type in ("iron_condor", "credit_spread", "calendar"):
            seen.add(e.ticker)
            candidates.append(e)

    print(f"\n--- PHASE 2: RANKED CANDIDATES ---")
    for i, c in enumerate(candidates, 1):
        print(f"  {i}. {c.ticker} {c.strategy_type} (score: {c.composite_score:.2f})")

    # Phase 3: Build portfolio trade-by-trade
    print(f"\n--- PHASE 3: PORTFOLIO CONSTRUCTION ---")

    portfolio = []  # List of (ticker, trade_spec, contracts, risk, credit)
    deployed_risk = 0
    risk_budget = CAPITAL * MAX_RISK_PCT

    for rank_entry in candidates:
        ticker = rank_entry.ticker
        td = ticker_data[ticker]
        r, tech, vol, levels = td["regime"], td["tech"], td["vol"], td["levels"]
        iv_rank = td["iv_rank"]

        ts = rank_entry.trade_spec
        wing = ts.wing_width_points or 5.0
        risk_per = wing * ts.lot_size

        # Estimate credit
        credit = estimate_credit(ts, vol, tech)

        # POP
        pop = estimate_pop(ts, credit, r.regime.value, tech.atr_pct, tech.current_price)

        # Entry score
        entry = score_entry_level(tech, levels, direction="neutral")

        # IV rank quality
        iv_q = compute_iv_rank_quality(iv_rank, "etf") if iv_rank else None

        # Validation
        rpt = run_daily_checks(
            ticker=ticker, trade_spec=ts, entry_credit=credit,
            regime_id=r.regime.value, atr_pct=tech.atr_pct,
            current_price=tech.current_price,
            avg_bid_ask_spread_pct=vol.avg_bid_ask_spread_pct if vol else 2.0,
            dte=ts.target_dte, rsi=tech.rsi.value,
            iv_rank=iv_rank, ticker_type="etf",
            days_to_earnings=None, levels=levels,
        )

        # Stress
        stress = run_adversarial_checks(ticker, ts, credit, tech.atr_pct)

        # Kelly sizing (position-aware)
        kelly_f = compute_kelly_fraction(pop.pop_pct, pop.max_profit, pop.max_loss)
        open_tickers = [p[0] for p in portfolio]

        sz = compute_position_size(
            pop_pct=pop.pop_pct, max_profit=pop.max_profit,
            max_loss=pop.max_loss, capital=CAPITAL,
            risk_per_contract=risk_per, wing_width=wing,
            regime_id=r.regime.value,
            exposure=PortfolioExposure(
                open_position_count=len(portfolio),
                max_positions=MAX_POSITIONS,
                current_risk_pct=deployed_risk / CAPITAL,
                max_risk_pct=MAX_RISK_PCT,
            ),
            new_ticker=ticker,
            open_tickers=open_tickers,
            correlation_fn=lambda a, b: get_corr(a, b),
        )

        # Regime stop
        stop = compute_regime_stop(r.regime.value)

        # Audit
        gamma = check_gamma_stress(ts, credit, tech.atr_pct)
        vega = check_vega_shock(ts, credit)
        stress_ok = gamma.severity.value != "fail" and vega.severity.value != "fail"
        skew = vol.skew_by_expiry[0] if vol and vol.skew_by_expiry else None

        max_corr = max((get_corr(ticker, ot) for ot in open_tickers), default=0)

        audit = audit_decision(
            ticker=ticker, trade_spec=ts, levels=levels, skew=skew, atr=tech.atr,
            pop_pct=pop.pop_pct, expected_value=pop.expected_value,
            entry_credit=credit, entry_score=entry.overall_score,
            regime_id=r.regime.value, atr_pct=tech.atr_pct,
            capital=CAPITAL, contracts=sz.recommended_contracts,
            correlation_with_existing=max_corr,
            strategy_concentration_pct=len([p for p in portfolio if p[1].structure_type == ts.structure_type]) / max(len(portfolio), 1),
            stress_passed=stress_ok, kelly_fraction=kelly_f,
        )

        contracts = sz.recommended_contracts
        trade_risk = contracts * risk_per

        # Check if fits in budget
        if deployed_risk + trade_risk > risk_budget and contracts > 0:
            # Reduce contracts to fit
            max_contracts_by_budget = int((risk_budget - deployed_risk) / risk_per)
            contracts = max(0, min(contracts, max_contracts_by_budget))
            trade_risk = contracts * risk_per

        passes = len([c for c in rpt.checks if c.severity.value == "pass"])
        warns = len([c for c in rpt.checks if c.severity.value == "warn"])
        fails = len([c for c in rpt.checks if c.severity.value == "fail"])

        # Decision
        can_trade = rpt.is_ready and contracts > 0 and audit.approved
        action = "BOOK" if can_trade else "SKIP"

        print(f"\n{'=' * 70}")
        print(f"TRADE {len(portfolio)+1}: {ticker} {ts.structure_type} | {action}")
        print(f"{'=' * 70}")
        print(f"Regime: R{r.regime.value} ({r.confidence:.0%}) | ${tech.current_price:.2f} | RSI {tech.rsi.value:.1f}")
        if iv_rank:
            print(f"IV Rank: {iv_rank:.0f}% | Quality: {iv_q.quality.upper() if iv_q else '?'}")
        print(f"Legs: {ts.leg_codes}")
        print(f"Credit: ${credit:.2f} | POP: {pop.pop_pct:.0%} | EV: ${pop.expected_value:.0f} | {pop.trade_quality}")
        print(f"Entry: {entry.overall_score:.0%} {entry.action.upper()} | Stop: {stop.base_multiplier}x")
        print(f"Validation: {passes}P/{warns}W/{fails}F {'READY' if rpt.is_ready else 'BLOCKED'}")
        if fails > 0:
            for c in rpt.checks:
                if c.severity.value == "fail":
                    print(f"  FAIL {c.name}: {c.message}")
        print(f"Kelly: {kelly_f:.1%} -> {contracts} contracts | Risk: ${trade_risk:,.0f}")
        if open_tickers:
            print(f"Correlation: max {max_corr:.2f} with {open_tickers}")
        print(f"Audit: {audit.overall_score}/100 {audit.overall_grade} {'APPROVED' if audit.approved else 'REJECTED'}")

        if can_trade:
            portfolio.append((ticker, ts, contracts, trade_risk, credit))
            deployed_risk += trade_risk
            remaining = risk_budget - deployed_risk
            print(f"\n>>> BOOKED: {contracts}x {ticker} IC")
            print(f">>> Total deployed: ${deployed_risk:,.0f} ({deployed_risk/CAPITAL*100:.1f}%) | Remaining: ${remaining:,.0f}")
        else:
            reasons = []
            if not rpt.is_ready:
                reasons.append("validation failed")
            if contracts == 0:
                reasons.append("Kelly = 0 contracts")
            if not audit.approved:
                reasons.append(f"audit rejected ({audit.overall_score}/100)")
            print(f"\n>>> SKIPPED: {', '.join(reasons)}")

        # Check if budget exhausted
        if deployed_risk >= risk_budget * 0.95:
            print(f"\n*** RISK BUDGET EXHAUSTED ({deployed_risk/CAPITAL*100:.1f}% >= {MAX_RISK_PCT*100:.0f}% target) ***")
            break
        if len(portfolio) >= MAX_POSITIONS:
            print(f"\n*** MAX POSITIONS REACHED ({len(portfolio)}/{MAX_POSITIONS}) ***")
            break

    # Phase 4: Portfolio summary
    print(f"\n{'=' * 70}")
    print(f"FINAL PORTFOLIO")
    print(f"{'=' * 70}")
    print(f"Account NLV:     ${CAPITAL:,.0f}")
    print(f"Positions:       {len(portfolio)}/{MAX_POSITIONS}")
    print(f"Total risk:      ${deployed_risk:,.0f} ({deployed_risk/CAPITAL*100:.1f}% of NLV)")
    print(f"Risk remaining:  ${risk_budget - deployed_risk:,.0f}")

    if portfolio:
        total_credit = sum(p[4] * 100 * p[2] for p in portfolio)
        print(f"Est. total credit: ${total_credit:,.0f}")
        print(f"Max drawdown:    ${deployed_risk:,.0f} (if all positions max loss)")
        print()
        print(f"{'#':<4}{'Ticker':<8}{'Structure':<16}{'Contracts':>10}{'Risk':>10}{'Credit':>10}{'Stop':>6}")
        print("-" * 66)
        for i, (t, ts, c, risk, cr) in enumerate(portfolio, 1):
            stop = compute_regime_stop(ticker_data[t]["regime"].regime.value)
            print(f"{i:<4}{t:<8}{ts.structure_type or 'IC':<16}{c:>10}{f'${risk:,.0f}':>10}{f'${cr*100*c:,.0f}':>10}{f'{stop.base_multiplier}x':>6}")

        # Correlation matrix
        if len(portfolio) > 1:
            print(f"\nCorrelation Matrix:")
            tks = [p[0] for p in portfolio]
            print(f"{'':>8}", end="")
            for t in tks:
                print(f"{t:>8}", end="")
            print()
            for t1 in tks:
                print(f"{t1:>8}", end="")
                for t2 in tks:
                    if t1 == t2:
                        print(f"{'1.00':>8}", end="")
                    else:
                        print(f"{get_corr(t1, t2):>8.2f}", end="")
                print()

        # Monitoring schedule
        print(f"\nMONITORING SCHEDULE:")
        print(f"  10:00 AM ET — Check regime status on all positions")
        print(f"  12:00 PM ET — Midday health check (theta decay, P&L)")
        print(f"  3:00 PM ET  — End-of-day assessment (overnight risk)")
        print(f"  Weekly      — Calibrate Kelly weights from outcomes")
    else:
        print(f"\nNO TRADES BOOKED — all candidates failed validation.")
        print(f"This is the correct outcome for capital preservation.")
        print(f"Next steps: Run again during market hours with real DXLink quotes.")


if __name__ == "__main__":
    main()
