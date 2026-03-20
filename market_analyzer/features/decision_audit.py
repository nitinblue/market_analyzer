"""Multi-level trade decision audit framework.

Evaluates a proposed or existing trade at 4 levels:
  1. Leg level  — strike placement quality, S/R backing, skew edge
  2. Trade level — POP, EV, economics, regime fit, exit plan
  3. Portfolio level — diversification, correlation, concentration
  4. Risk level  — sizing, drawdown headroom, stress survival, Kelly alignment

Each level produces a score (0-100) and a grade (A/B+/B/C/D/F).
The overall score is a weighted average: trade 35%, risk 30%, portfolio 20%, legs 15%.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from market_analyzer.models.decision_audit import (
    DecisionReport,
    GradedCheck,
    LegAudit,
    PortfolioAudit,
    RiskAudit,
    TradeAudit,
)
from market_analyzer.models.opportunity import LegAction, TradeSpec
from market_analyzer.models.vol_surface import SkewSlice

if TYPE_CHECKING:
    from market_analyzer.models.levels import LevelsAnalysis


def _score_to_grade(score: float) -> str:
    """Convert a numeric score (0-100) to a letter grade."""
    if score >= 93:
        return "A"
    if score >= 85:
        return "B+"
    if score >= 77:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def audit_legs(
    trade_spec: TradeSpec,
    levels: "LevelsAnalysis | None",
    skew: SkewSlice | None,
    atr: float,
) -> LegAudit | None:
    """Audit each leg: strike placement quality, S/R backing, skew edge.

    For each STO leg:
      - S/R proximity: 0-30 pts (backed within 1 ATR = 30, 2 ATR = 15, no backing = 0)
      - Skew advantage: 0-25 pts (>5% IV advantage = 25, >2% = 15, none = 5)
      - ATR distance: 0-25 pts (1.0 ATR = 25, 1.5 ATR = 20, <0.5 = 5, >3 = 5)
      - Wing width adequacy: 0-20 pts (5+ wide = 20, 3-5 = 15, <3 = 5)

    For each BTO leg:
      - Wing protection scored based on wing width relative to ATR.

    Returns None if trade_spec has no legs.
    """
    if not trade_spec.legs:
        return None

    underlying = trade_spec.underlying_price or 0.0

    # Collect support/resistance levels if available
    sr_levels: list[float] = []
    if levels is not None:
        for lvl in getattr(levels, "levels", []):
            price = getattr(lvl, "price", None)
            if price is not None:
                sr_levels.append(float(price))

    # Build per-leg checks and average
    all_scores: list[float] = []
    primary_role = "mixed"
    primary_strike = 0.0

    for leg in trade_spec.legs:
        strike = float(leg.strike)
        if not primary_strike:
            primary_strike = strike
            primary_role = leg.role or ("short" if leg.action == LegAction.SELL_TO_OPEN else "long")

        if leg.action == LegAction.SELL_TO_OPEN:
            # --- S/R proximity ---
            if sr_levels and atr > 0:
                nearest_dist = min(abs(strike - lvl) for lvl in sr_levels)
                if nearest_dist <= atr:
                    sr_score = 30
                elif nearest_dist <= 2 * atr:
                    sr_score = 15
                else:
                    sr_score = 0
            else:
                sr_score = 0  # No data = no credit

            # --- Skew advantage ---
            if skew is not None and underlying > 0:
                # Skew slice has put_skew / call_skew relative to ATM IV
                option_type = getattr(leg, "option_type", None) or ""
                if "put" in str(option_type).lower():
                    skew_val = getattr(skew, "put_skew", 0.0) or 0.0
                else:
                    skew_val = getattr(skew, "call_skew", 0.0) or 0.0
                # Positive skew means we're selling elevated IV
                if skew_val >= 0.05:
                    skew_score = 25
                elif skew_val >= 0.02:
                    skew_score = 15
                else:
                    skew_score = 5
            else:
                skew_score = 5  # Unknown = minimal credit

            # --- ATR distance ---
            if atr > 0 and underlying > 0:
                dist = abs(underlying - strike)
                atr_ratio = dist / atr
                if 1.0 <= atr_ratio <= 1.5:
                    atr_score = 25
                elif 1.5 < atr_ratio <= 2.0:
                    atr_score = 20
                elif 0.5 <= atr_ratio < 1.0:
                    atr_score = 15
                elif atr_ratio > 3.0:
                    atr_score = 5
                else:
                    atr_score = 5
            else:
                atr_score = 15  # Unknown = average

            # --- Wing width adequacy ---
            wing = trade_spec.wing_width_points or 0.0
            if wing >= 5:
                wing_score = 20
            elif wing >= 3:
                wing_score = 15
            else:
                wing_score = 5

            leg_total = (sr_score + skew_score + atr_score + wing_score) / 4.0 * 100 / 25
            # Normalize: max possible = 30+25+25+20 = 100
            leg_total = sr_score + skew_score + atr_score + wing_score
            all_scores.append(min(100.0, leg_total))

        else:
            # BTO legs: scored purely on wing width protection
            wing = trade_spec.wing_width_points or 0.0
            if wing >= 5:
                protection = 90
            elif wing >= 3:
                protection = 70
            else:
                protection = 40
            all_scores.append(float(protection))

    if not all_scores:
        return None

    avg_score = sum(all_scores) / len(all_scores)
    avg_score = min(100.0, avg_score)

    # Build a summary check list for the primary leg perspective
    checks: list[GradedCheck] = []

    # Aggregate S/R check
    if sr_levels and atr > 0:
        short_strikes = [float(l.strike) for l in trade_spec.legs if l.action == LegAction.SELL_TO_OPEN]
        if short_strikes:
            best_dist = min(min(abs(s - lvl) for lvl in sr_levels) for s in short_strikes)
            if best_dist <= atr:
                sr_agg = 30
                sr_detail = f"Nearest S/R {best_dist:.1f} pts (within 1 ATR)"
            elif best_dist <= 2 * atr:
                sr_agg = 15
                sr_detail = f"Nearest S/R {best_dist:.1f} pts (1-2 ATR)"
            else:
                sr_agg = 0
                sr_detail = f"Nearest S/R {best_dist:.1f} pts (>2 ATR — no structural backing)"
        else:
            sr_agg = 0
            sr_detail = "No short strikes to evaluate"
    else:
        sr_agg = 0
        sr_detail = "No S/R data available"
    checks.append(GradedCheck(name="sr_proximity", score=float(sr_agg),
                               grade=_score_to_grade(sr_agg * 100 / 30 if sr_agg else 0),
                               detail=sr_detail))

    # Skew check
    if skew is not None:
        max_skew = max(getattr(skew, "put_skew", 0.0) or 0.0,
                       getattr(skew, "call_skew", 0.0) or 0.0)
        if max_skew >= 0.05:
            sk_score = 100
        elif max_skew >= 0.02:
            sk_score = 60
        else:
            sk_score = 20
        sk_detail = f"Max IV skew {max_skew:.1%}"
    else:
        sk_score = 20
        sk_detail = "Skew data unavailable"
    checks.append(GradedCheck(name="skew_advantage", score=float(sk_score),
                               grade=_score_to_grade(sk_score),
                               detail=sk_detail))

    # ATR distance check (aggregate over short strikes)
    short_strikes = [float(l.strike) for l in trade_spec.legs if l.action == LegAction.SELL_TO_OPEN]
    if short_strikes and atr > 0 and underlying > 0:
        avg_dist_atr = sum(abs(underlying - s) for s in short_strikes) / len(short_strikes) / atr
        if 1.0 <= avg_dist_atr <= 1.5:
            atr_s = 100
        elif 1.5 < avg_dist_atr <= 2.0:
            atr_s = 80
        elif 0.5 <= avg_dist_atr < 1.0:
            atr_s = 60
        elif avg_dist_atr > 3.0:
            atr_s = 20
        else:
            atr_s = 20
        atr_detail = f"Avg short strike {avg_dist_atr:.1f}× ATR from underlying"
    else:
        atr_s = 50
        atr_detail = "ATR distance unknown"
    checks.append(GradedCheck(name="atr_distance", score=float(atr_s),
                               grade=_score_to_grade(atr_s),
                               detail=atr_detail))

    # Wing width check
    wing = trade_spec.wing_width_points or 0.0
    if wing >= 5:
        ww_score = 100
        ww_detail = f"{wing:.0f}-pt wing — adequate protection"
    elif wing >= 3:
        ww_score = 75
        ww_detail = f"{wing:.0f}-pt wing — minimum acceptable"
    else:
        ww_score = 25
        ww_detail = f"{wing:.0f}-pt wing — too narrow, high gamma risk"
    checks.append(GradedCheck(name="wing_width", score=float(ww_score),
                               grade=_score_to_grade(ww_score),
                               detail=ww_detail))

    final_score = sum(c.score for c in checks) / len(checks)
    final_score = round(min(100.0, final_score))

    return LegAudit(
        role=primary_role,
        strike=primary_strike,
        checks=checks,
        score=float(final_score),
        grade=_score_to_grade(final_score),
    )


def audit_trade(
    trade_spec: TradeSpec,
    pop_pct: float | None,
    expected_value: float | None,
    entry_credit: float,
    entry_score: float | None,
    regime_id: int,
    atr_pct: float,
    commission_per_leg: float = 0.65,
) -> TradeAudit:
    """Audit trade structure: POP, EV, economics, regime fit, exit plan.

    Checks:
      1. Structure-regime alignment (0-20 raw → ×5 = 0-100)
      2. POP quality
      3. Expected value
      4. Commission drag
      5. Exit plan quality
      6. Entry timing
    """
    checks: list[GradedCheck] = []

    # 1. Structure-regime alignment
    alignment: dict[str, dict[int, int]] = {
        "iron_condor":   {1: 20, 2: 15, 3: 5,  4: 0},
        "iron_butterfly":{1: 18, 2: 20, 3: 5,  4: 0},
        "credit_spread": {1: 18, 2: 18, 3: 10, 4: 0},
        "calendar":      {1: 18, 2: 15, 3: 10, 4: 5},
        "diagonal":      {1: 12, 2: 10, 3: 18, 4: 5},
        "debit_spread":  {1: 5,  2: 8,  3: 18, 4: 5},
        "ratio_spread":  {1: 18, 2: 12, 3: 5,  4: 0},
        "straddle":      {1: 5,  2: 15, 3: 5,  4: 15},
        "strangle":      {1: 5,  2: 15, 3: 5,  4: 12},
    }
    st = trade_spec.structure_type or "iron_condor"
    raw_alignment = alignment.get(st, {}).get(regime_id, 10)
    alignment_score = raw_alignment * 5  # Scale to 0-100
    checks.append(GradedCheck(
        name="regime_alignment",
        score=float(alignment_score),
        grade=_score_to_grade(alignment_score),
        detail=f"{st} in R{regime_id}",
    ))

    # 2. POP quality
    if pop_pct is not None:
        pop_score = min(100.0, max(0.0, (pop_pct - 0.40) / 0.35 * 100))
    else:
        pop_score = 50.0  # Unknown = mediocre
    checks.append(GradedCheck(
        name="pop_quality",
        score=round(pop_score),
        grade=_score_to_grade(pop_score),
        detail=f"POP {pop_pct:.0%}" if pop_pct is not None else "POP unknown",
    ))

    # 3. Expected value
    if expected_value is not None and expected_value > 0:
        credit_dollars = entry_credit * 100
        ev_score: float = min(100.0, expected_value / max(credit_dollars, 1) * 200)
    elif expected_value is not None:
        ev_score = max(0.0, 50.0 + expected_value / 5.0)
    else:
        ev_score = 50.0
    checks.append(GradedCheck(
        name="expected_value",
        score=round(min(100.0, max(0.0, ev_score))),
        grade=_score_to_grade(ev_score),
        detail=f"EV ${expected_value:.0f}" if expected_value is not None else "EV unknown",
    ))

    # 4. Commission drag
    leg_count = len(trade_spec.legs)
    round_trip = commission_per_leg * leg_count * 2
    credit_dollars = entry_credit * 100
    drag_pct = round_trip / credit_dollars * 100 if credit_dollars > 0 else 100.0
    if drag_pct < 5:
        drag_score: float = 100
    elif drag_pct < 10:
        drag_score = 85
    elif drag_pct < 20:
        drag_score = 60
    elif drag_pct < 30:
        drag_score = 30
    else:
        drag_score = 0
    checks.append(GradedCheck(
        name="commission_drag",
        score=float(drag_score),
        grade=_score_to_grade(drag_score),
        detail=f"{drag_pct:.1f}% drag (${round_trip:.2f} on ${credit_dollars:.0f})",
    ))

    # 5. Exit plan quality
    has_tp = trade_spec.profit_target_pct is not None
    has_sl = trade_spec.stop_loss_pct is not None
    has_dte = trade_spec.exit_dte is not None
    exit_score = float(has_tp * 35 + has_sl * 35 + has_dte * 30)
    checks.append(GradedCheck(
        name="exit_plan",
        score=exit_score,
        grade=_score_to_grade(exit_score),
        detail=f"TP {'yes' if has_tp else 'NO'} | SL {'yes' if has_sl else 'NO'} | DTE {'yes' if has_dte else 'NO'}",
    ))

    # 6. Entry timing
    entry_timing_score = min(100.0, (entry_score or 0.5) * 100)
    checks.append(GradedCheck(
        name="entry_timing",
        score=round(entry_timing_score),
        grade=_score_to_grade(entry_timing_score),
        detail=f"Entry score {entry_score:.0%}" if entry_score is not None else "No entry score",
    ))

    avg = sum(c.score for c in checks) / len(checks)
    return TradeAudit(checks=checks, score=round(avg), grade=_score_to_grade(avg))


def audit_portfolio(
    trade_spec: TradeSpec,
    open_position_count: int = 0,
    max_positions: int = 5,
    portfolio_risk_pct: float = 0.0,
    max_risk_pct: float = 0.25,
    correlation_with_existing: float = 0.0,
    strategy_concentration_pct: float = 0.0,
    directional_score: float = 0.0,
) -> PortfolioAudit:
    """Audit portfolio fit: diversification, correlation, concentration.

    Checks:
      1. Slot availability
      2. Correlation with existing positions
      3. Risk budget remaining
      4. Strategy concentration
      5. Directional balance
    """
    checks: list[GradedCheck] = []

    # 1. Slot availability
    slots_remaining = max(0, max_positions - open_position_count)
    slot_score = min(100.0, slots_remaining / max_positions * 100 * 2)
    checks.append(GradedCheck(
        name="slot_availability",
        score=round(min(100.0, slot_score)),
        grade=_score_to_grade(slot_score),
        detail=f"{open_position_count}/{max_positions} slots used",
    ))

    # 2. Correlation
    if correlation_with_existing < 0.50:
        corr_score = 100
    elif correlation_with_existing < 0.70:
        corr_score = 70
    elif correlation_with_existing < 0.85:
        corr_score = 40
    else:
        corr_score = 10
    checks.append(GradedCheck(
        name="correlation",
        score=float(corr_score),
        grade=_score_to_grade(corr_score),
        detail=f"Max correlation {correlation_with_existing:.2f} with existing",
    ))

    # 3. Risk budget
    risk_remaining_pct = max(0.0, max_risk_pct - portfolio_risk_pct)
    risk_score = min(100.0, risk_remaining_pct / max_risk_pct * 100 * 1.5)
    checks.append(GradedCheck(
        name="risk_budget",
        score=round(min(100.0, risk_score)),
        grade=_score_to_grade(risk_score),
        detail=f"{portfolio_risk_pct*100:.1f}% deployed of {max_risk_pct*100:.0f}% max",
    ))

    # 4. Strategy concentration
    if strategy_concentration_pct < 0.40:
        conc_score = 100
    elif strategy_concentration_pct < 0.60:
        conc_score = 70
    elif strategy_concentration_pct < 0.80:
        conc_score = 40
    else:
        conc_score = 10
    checks.append(GradedCheck(
        name="strategy_concentration",
        score=float(conc_score),
        grade=_score_to_grade(conc_score),
        detail=f"{strategy_concentration_pct*100:.0f}% in {trade_spec.structure_type or 'unknown'}",
    ))

    # 5. Directional balance
    dir_score = max(0.0, 100.0 - abs(directional_score) * 100)
    checks.append(GradedCheck(
        name="directional_balance",
        score=round(dir_score),
        grade=_score_to_grade(dir_score),
        detail=f"Net directional: {directional_score:+.2f}",
    ))

    avg = sum(c.score for c in checks) / len(checks)
    return PortfolioAudit(checks=checks, score=round(avg), grade=_score_to_grade(avg))


def audit_risk(
    trade_spec: TradeSpec,
    capital: float,
    contracts: int,
    drawdown_pct: float = 0.0,
    drawdown_halt_pct: float = 0.10,
    stress_passed: bool = True,
    kelly_fraction: float = 0.0,
) -> RiskAudit:
    """Audit risk management: sizing, drawdown, stress survival, Kelly alignment.

    Checks:
      1. Position sizing (% of NLV at risk)
      2. Drawdown headroom
      3. Stress survival
      4. Kelly alignment
    """
    checks: list[GradedCheck] = []

    wing = trade_spec.wing_width_points or 5.0
    risk_dollars = contracts * wing * trade_spec.lot_size
    risk_pct = risk_dollars / capital if capital > 0 else 1.0

    # 1. Position sizing
    if risk_pct <= 0.02:
        size_score = 100
    elif risk_pct <= 0.05:
        size_score = 75
    elif risk_pct <= 0.10:
        size_score = 40
    else:
        size_score = 10
    checks.append(GradedCheck(
        name="position_size",
        score=float(size_score),
        grade=_score_to_grade(size_score),
        detail=f"{contracts} contracts, ${risk_dollars:,.0f} risk ({risk_pct*100:.1f}% of NLV)",
    ))

    # 2. Drawdown headroom
    dd_remaining = max(0.0, drawdown_halt_pct - drawdown_pct)
    dd_score = min(100.0, dd_remaining / drawdown_halt_pct * 100 * 1.5)
    checks.append(GradedCheck(
        name="drawdown_headroom",
        score=round(min(100.0, dd_score)),
        grade=_score_to_grade(dd_score),
        detail=f"{drawdown_pct*100:.1f}% drawdown ({dd_remaining*100:.1f}% to halt)",
    ))

    # 3. Stress survival
    stress_score = 100 if stress_passed else 20
    checks.append(GradedCheck(
        name="stress_survival",
        score=float(stress_score),
        grade=_score_to_grade(stress_score),
        detail="Survives adversarial stress" if stress_passed else "FAILS stress test",
    ))

    # 4. Kelly alignment
    if kelly_fraction > 0 and contracts > 0:
        kelly_score = 90  # Positive Kelly + deploying = good
    elif kelly_fraction <= 0 and contracts == 0:
        kelly_score = 80  # Negative Kelly + not deploying = correct
    elif kelly_fraction <= 0 and contracts > 0:
        kelly_score = 10  # Deploying against Kelly = BAD
    else:
        kelly_score = 70  # Positive Kelly but not deploying
    checks.append(GradedCheck(
        name="kelly_alignment",
        score=float(kelly_score),
        grade=_score_to_grade(kelly_score),
        detail=f"Kelly {kelly_fraction:.1%}, deploying {contracts} contracts",
    ))

    avg = sum(c.score for c in checks) / len(checks)
    return RiskAudit(checks=checks, score=round(avg), grade=_score_to_grade(avg))


def audit_decision(
    ticker: str,
    trade_spec: TradeSpec,
    # Leg level
    levels: "LevelsAnalysis | None" = None,
    skew: SkewSlice | None = None,
    atr: float = 5.0,
    # Trade level
    pop_pct: float | None = None,
    expected_value: float | None = None,
    entry_credit: float = 1.0,
    entry_score: float | None = None,
    regime_id: int = 1,
    atr_pct: float = 1.0,
    # Portfolio level
    open_position_count: int = 0,
    max_positions: int = 5,
    portfolio_risk_pct: float = 0.0,
    correlation_with_existing: float = 0.0,
    strategy_concentration_pct: float = 0.0,
    directional_score: float = 0.0,
    # Risk level
    capital: float = 50000,
    contracts: int = 1,
    drawdown_pct: float = 0.0,
    stress_passed: bool = True,
    kelly_fraction: float = 0.0,
) -> DecisionReport:
    """Run complete 4-level trade decision audit.

    Weights: trade 35%, risk 30%, portfolio 20%, legs 15% (when present).
    Approved when overall >= 70.
    """
    leg = audit_legs(trade_spec, levels, skew, atr)
    trade = audit_trade(
        trade_spec, pop_pct, expected_value, entry_credit,
        entry_score, regime_id, atr_pct,
    )
    portfolio = audit_portfolio(
        trade_spec, open_position_count, max_positions,
        portfolio_risk_pct, 0.25, correlation_with_existing,
        strategy_concentration_pct, directional_score,
    )
    risk = audit_risk(
        trade_spec, capital, contracts, drawdown_pct, 0.10,
        stress_passed, kelly_fraction,
    )

    # Weighted overall: trade 35%, risk 30%, portfolio 20%, legs 15%
    scores: list[float] = []
    weights: list[float] = []
    if leg is not None:
        scores.append(leg.score)
        weights.append(0.15)
    scores.extend([trade.score, portfolio.score, risk.score])
    weights.extend([0.35, 0.20, 0.30])

    total_weight = sum(weights)
    overall = sum(s * w for s, w in zip(scores, weights)) / total_weight
    overall = round(overall)
    grade = _score_to_grade(overall)
    approved = overall >= 70

    summary_parts: list[str] = []
    if leg is not None:
        summary_parts.append(f"Legs: {leg.grade}")
    summary_parts.extend([
        f"Trade: {trade.grade}",
        f"Portfolio: {portfolio.grade}",
        f"Risk: {risk.grade}",
    ])
    summary = (
        f"{overall}/100 {grade} — {'APPROVED' if approved else 'REJECTED'} | "
        + " | ".join(summary_parts)
    )

    return DecisionReport(
        ticker=ticker,
        structure_type=trade_spec.structure_type or "unknown",
        leg_audit=leg,
        trade_audit=trade,
        portfolio_audit=portfolio,
        risk_audit=risk,
        overall_score=float(overall),
        overall_grade=grade,
        approved=approved,
        summary=summary,
    )
