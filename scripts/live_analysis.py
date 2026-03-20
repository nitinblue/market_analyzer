"""Live trading analysis with broker data."""
import sys
import io
import warnings

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
warnings.filterwarnings("ignore")
import logging
logging.disable(logging.WARNING)

from market_analyzer.cli._broker import connect_broker
from market_analyzer import MarketAnalyzer, DataService
from market_analyzer.opportunity.option_plays.iron_condor import assess_iron_condor
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


def main():
    md, mm, acct, wl = connect_broker(is_paper=False)
    if md is None:
        print("Broker connection failed")
        return

    ma = MarketAnalyzer(data_service=DataService(), market_data=md, market_metrics=mm)
    bal = acct.get_balance()
    CAPITAL = bal.net_liquidating_value

    # Context
    ctx = ma.context.assess()
    print("=" * 65)
    print(f"LIVE ANALYSIS WITH BROKER | ${CAPITAL:,.0f} NLV | ${bal.derivative_buying_power:,.0f} BP")
    print(f"Market: {ctx.environment_label} | Trading: {ctx.trading_allowed} | Size: {ctx.position_size_factor}")
    print("=" * 65)

    # Regime scan
    tickers = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
    print(f"\n{'Ticker':<8}{'Regime':<8}{'Conf':<8}{'Price':>10}{'IV Rank':>10}{'IV Pct':>10}")
    print("-" * 58)
    regime_data = {}
    for t in tickers:
        r = ma.regime.detect(t)
        tech = ma.technicals.snapshot(t)
        m = ma.quotes.get_metrics(t)
        regime_data[t] = (r, tech, m)
        ivr = f"{m.iv_rank:.0f}%" if m and m.iv_rank else "N/A"
        ivp = f"{m.iv_percentile:.0f}%" if m and m.iv_percentile else "N/A"
        flag = " << NO TRADE" if r.regime.value == 4 else ""
        print(f"{t:<8}R{r.regime.value:<7}{r.confidence:.0%}{'':>4}{tech.current_price:>9.2f}{ivr:>10}{ivp:>10}{flag}")

    # Analyze top R1 candidates
    candidates = [t for t in tickers if regime_data[t][0].regime.value in (1, 2)]
    print(f"\nAnalyzing {len(candidates)} candidates: {candidates}")

    deployed_risk = 0
    position_count = 0

    for ticker in candidates:
        r, tech_cached, m = regime_data[ticker]
        tech = ma.technicals.snapshot(ticker)
        vol = ma.vol_surface.surface(ticker)
        levels = ma.levels.analyze(ticker)
        iv_rank = m.iv_rank if m else None

        ic = assess_iron_condor(ticker, r, tech, vol)
        ts = ic.trade_spec
        if not ts:
            print(f"\n{ticker}: No trade spec (verdict: {ic.verdict})")
            continue

        # Real DXLink quotes
        try:
            lqs = ma.quotes.get_leg_quotes(ts.legs)
            real_credit = 0
            for leg, lq in zip(ts.legs, lqs):
                if lq and lq.bid is not None and lq.ask is not None:
                    mid = (lq.bid + lq.ask) / 2
                    if leg.action.value == "STO":
                        real_credit += mid
                    else:
                        real_credit -= mid
            real_credit = round(abs(real_credit), 2)
        except Exception:
            real_credit = (ts.wing_width_points or 5) * vol.front_iv * 0.40

        # Analysis
        pop = estimate_pop(ts, real_credit, r.regime.value, tech.atr_pct, tech.current_price)
        entry = score_entry_level(tech, levels, direction="neutral")
        iv_q = compute_iv_rank_quality(iv_rank, "etf") if iv_rank else None
        dte_rec = select_optimal_dte(vol, r.regime.value, "iron_condor")
        stop = compute_regime_stop(r.regime.value)

        # Validation
        rpt = run_daily_checks(
            ticker=ticker, trade_spec=ts, entry_credit=real_credit,
            regime_id=r.regime.value, atr_pct=tech.atr_pct,
            current_price=tech.current_price,
            avg_bid_ask_spread_pct=vol.avg_bid_ask_spread_pct,
            dte=ts.target_dte, rsi=tech.rsi.value,
            iv_rank=iv_rank, ticker_type="etf",
            days_to_earnings=None, levels=levels,
        )
        stress = run_adversarial_checks(ticker, ts, real_credit, tech.atr_pct)

        # Kelly sizing (position-aware)
        kelly_f = compute_kelly_fraction(pop.pop_pct, pop.max_profit, pop.max_loss)
        wing = ts.wing_width_points or 5.0
        risk_per = wing * ts.lot_size
        sz = compute_position_size(
            pop_pct=pop.pop_pct, max_profit=pop.max_profit,
            max_loss=pop.max_loss, capital=CAPITAL,
            risk_per_contract=risk_per, wing_width=wing,
            regime_id=r.regime.value,
            exposure=PortfolioExposure(
                open_position_count=position_count, max_positions=5,
                current_risk_pct=deployed_risk / CAPITAL if CAPITAL > 0 else 0,
                max_risk_pct=0.25,
            ),
        )

        # Audit
        gamma = check_gamma_stress(ts, real_credit, tech.atr_pct)
        vega = check_vega_shock(ts, real_credit)
        stress_ok = gamma.severity.value != "fail" and vega.severity.value != "fail"
        skew = vol.skew_by_expiry[0] if vol and vol.skew_by_expiry else None

        audit = audit_decision(
            ticker=ticker, trade_spec=ts, levels=levels, skew=skew, atr=tech.atr,
            pop_pct=pop.pop_pct, expected_value=pop.expected_value,
            entry_credit=real_credit, entry_score=entry.overall_score,
            regime_id=r.regime.value, atr_pct=tech.atr_pct,
            capital=CAPITAL, contracts=sz.recommended_contracts,
            stress_passed=stress_ok, kelly_fraction=kelly_f,
        )

        pbs = compute_pullback_levels(tech.current_price, levels, atr=tech.atr)

        # Count checks
        passes = len([c for c in rpt.checks if c.severity.value == "pass"])
        warns = len([c for c in rpt.checks if c.severity.value == "warn"])
        fails = len([c for c in rpt.checks if c.severity.value == "fail"])

        # Print
        print(f"\n{'=' * 65}")
        print(f"{ticker} IRON CONDOR | R{r.regime.value} ({r.confidence:.0%}) | ${tech.current_price:.2f}")
        print(f"{'=' * 65}")
        print(f"RSI: {tech.rsi.value:.1f} | ATR: {tech.atr_pct:.2f}% | IV: {vol.front_iv:.1%}")
        if iv_rank:
            qual = iv_q.quality.upper() if iv_q else "?"
            print(f"IV Rank: {iv_rank:.0f}% | IV Pctile: {m.iv_percentile:.0f}% | Quality: {qual}")
        if skew:
            print(f"Put skew: {skew.put_skew:.3f} | Call skew: {skew.call_skew:.3f} | Ratio: {skew.skew_ratio:.2f}")

        print(f"\nLegs: {ts.leg_codes}")
        print(f"Wing: {wing:.0f} pts | DTE: {ts.target_dte} | Optimal DTE: {dte_rec.recommended_dte}")
        print(f"BROKER CREDIT: ${real_credit:.2f}/contract (${real_credit * 100:.0f} per contract)")

        print(f"\nEntry Score: {entry.overall_score:.0%} -> {entry.action.upper()}")
        print(f"  {entry.rationale}")

        print(f"\nPOP: {pop.pop_pct:.0%} | Max Profit: ${pop.max_profit:.0f} | Max Loss: ${pop.max_loss:.0f}")
        print(f"EV: ${pop.expected_value:.0f} | Quality: {pop.trade_quality} ({pop.trade_quality_score:.2f})")

        print(f"\nVALIDATION ({len(rpt.checks)} checks): {passes}P/{warns}W/{fails}F", end="")
        print(f" -> {'READY' if rpt.is_ready else 'BLOCKED'}")
        for c in rpt.checks:
            icon = "OK" if c.severity.value == "pass" else c.severity.value.upper()
            print(f"  {icon:4s} {c.name:<22s} {c.message}")

        print(f"\nSTRESS TEST:")
        for c in stress.checks:
            print(f"  {c.severity.value.upper():4s} {c.name:<22s} {c.message}")

        print(f"\nKELLY SIZING:")
        print(f"  Full Kelly: {kelly_f:.1%} | Half Kelly: {kelly_f * 0.5:.1%}")
        print(f"  Recommended: {sz.recommended_contracts} contracts")
        print(f"  Risk: ${sz.recommended_contracts * risk_per:,.0f} ({sz.recommended_contracts * risk_per / CAPITAL * 100:.1f}% of NLV)")
        print(f"  Stop: {stop.base_multiplier}x credit (R{r.regime.value})")

        print(f"\nDECISION AUDIT: {audit.overall_score}/100 {audit.overall_grade}", end="")
        print(f" -> {'APPROVED' if audit.approved else 'REJECTED'}")
        if audit.leg_audit:
            print(f"  Legs:      {audit.leg_audit.score:.0f}/100 {audit.leg_audit.grade}")
        print(f"  Trade:     {audit.trade_audit.score:.0f}/100 {audit.trade_audit.grade}")
        print(f"  Portfolio: {audit.portfolio_audit.score:.0f}/100 {audit.portfolio_audit.grade}")
        print(f"  Risk:      {audit.risk_audit.score:.0f}/100 {audit.risk_audit.grade}")

        if pbs:
            print(f"\nPULLBACK ALERTS:")
            for pb in pbs[:3]:
                print(f"  ${pb.alert_price:.0f} ({pb.level_source}) -> +{pb.roc_improvement_pct:.1f}% ROC")

        # Track deployed
        if sz.recommended_contracts > 0 and rpt.is_ready:
            deployed_risk += sz.recommended_contracts * risk_per
            position_count += 1

    # Portfolio summary
    print(f"\n{'=' * 65}")
    print(f"PORTFOLIO SUMMARY")
    print(f"{'=' * 65}")
    print(f"Account NLV:    ${CAPITAL:,.0f}")
    print(f"Positions:      {position_count}/5")
    print(f"Deployed risk:  ${deployed_risk:,.0f} ({deployed_risk / CAPITAL * 100:.1f}% of NLV)")
    print(f"Risk remaining: ${CAPITAL * 0.25 - deployed_risk:,.0f}")
    if position_count == 0:
        print(f"\nNO TRADES TODAY — capital preserved.")
        print(f"Recommendation: Wait for broker credits to improve or regime stabilization.")


if __name__ == "__main__":
    main()
