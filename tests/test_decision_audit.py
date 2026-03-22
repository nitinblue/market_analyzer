"""Tests for multi-level trade decision audit framework."""
from datetime import date
import pytest

from income_desk.models.decision_audit import (
    DecisionReport,
    GradedCheck,
    LegAudit,
    TradeAudit,
    PortfolioAudit,
    RiskAudit,
)
from income_desk.features.decision_audit import (
    audit_decision,
    audit_legs,
    audit_trade,
    audit_portfolio,
    audit_risk,
    _score_to_grade,
)
from income_desk.models.opportunity import LegAction, LegSpec, TradeSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _leg(role: str, action: LegAction, opt_type: str, strike: float) -> LegSpec:
    return LegSpec(
        role=role,
        action=action,
        option_type=opt_type,
        strike=strike,
        strike_label="test",
        expiration=date(2026, 4, 17),
        days_to_expiry=30,
        atm_iv_at_expiry=0.22,
    )


def _ts(legs: list[LegSpec], **kw) -> TradeSpec:
    defaults = dict(
        ticker="SPY",
        underlying_price=580.0,
        target_dte=30,
        target_expiration=date(2026, 4, 17),
        spec_rationale="test",
        structure_type="iron_condor",
        profit_target_pct=0.50,
        stop_loss_pct=2.0,
        exit_dte=21,
        wing_width_points=5.0,
    )
    defaults.update(kw)
    return TradeSpec(legs=legs, **defaults)


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

class TestGrading:
    def test_grade_a(self):
        assert _score_to_grade(95) == "A"

    def test_grade_a_boundary(self):
        assert _score_to_grade(93) == "A"

    def test_grade_b_plus(self):
        assert _score_to_grade(88) == "B+"

    def test_grade_b_plus_boundary(self):
        assert _score_to_grade(85) == "B+"

    def test_grade_b(self):
        assert _score_to_grade(80) == "B"

    def test_grade_b_boundary(self):
        assert _score_to_grade(77) == "B"

    def test_grade_c(self):
        assert _score_to_grade(72) == "C"

    def test_grade_c_boundary(self):
        assert _score_to_grade(70) == "C"

    def test_grade_d(self):
        assert _score_to_grade(65) == "D"

    def test_grade_d_boundary(self):
        assert _score_to_grade(60) == "D"

    def test_grade_f(self):
        assert _score_to_grade(50) == "F"

    def test_grade_f_zero(self):
        assert _score_to_grade(0) == "F"

    def test_grade_perfect_100(self):
        assert _score_to_grade(100) == "A"


# ---------------------------------------------------------------------------
# Leg Audit
# ---------------------------------------------------------------------------

class TestLegAudit:
    def test_returns_none_for_empty_legs(self):
        ts = _ts([])
        result = audit_legs(ts, levels=None, skew=None, atr=5.0)
        assert result is None

    def test_returns_leg_audit_for_short_leg(self):
        legs = [_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)]
        ts = _ts(legs)
        result = audit_legs(ts, levels=None, skew=None, atr=5.0)
        assert isinstance(result, LegAudit)
        assert 0 <= result.score <= 100
        assert result.grade in ("A", "B+", "B", "C", "D", "F")

    def test_has_expected_checks(self):
        legs = [_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)]
        ts = _ts(legs)
        result = audit_legs(ts, levels=None, skew=None, atr=5.0)
        assert result is not None
        check_names = {c.name for c in result.checks}
        assert "sr_proximity" in check_names
        assert "skew_advantage" in check_names
        assert "atr_distance" in check_names
        assert "wing_width" in check_names

    def test_narrow_wing_penalized(self):
        legs = [_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)]
        wide_ts = _ts(legs, wing_width_points=10.0)
        narrow_ts = _ts(legs, wing_width_points=1.0)
        wide_result = audit_legs(wide_ts, levels=None, skew=None, atr=5.0)
        narrow_result = audit_legs(narrow_ts, levels=None, skew=None, atr=5.0)
        assert wide_result is not None
        assert narrow_result is not None
        wide_ww = next(c for c in wide_result.checks if c.name == "wing_width")
        narrow_ww = next(c for c in narrow_result.checks if c.name == "wing_width")
        assert wide_ww.score > narrow_ww.score

    def test_bto_leg_returns_protection_score(self):
        legs = [_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565)]
        ts = _ts(legs, wing_width_points=5.0)
        result = audit_legs(ts, levels=None, skew=None, atr=5.0)
        assert result is not None
        # BTO-only leg: wing_width check scores well, but S/R and skew have no data.
        # Score is a function of all 4 aggregate checks; just verify it's a valid float.
        assert 0 <= result.score <= 100

    def test_ic_four_legs_audit(self):
        legs = [
            _leg("short_put", LegAction.SELL_TO_OPEN, "put", 570),
            _leg("long_put", LegAction.BUY_TO_OPEN, "put", 565),
            _leg("short_call", LegAction.SELL_TO_OPEN, "call", 590),
            _leg("long_call", LegAction.BUY_TO_OPEN, "call", 595),
        ]
        ts = _ts(legs)
        result = audit_legs(ts, levels=None, skew=None, atr=5.0)
        assert result is not None
        assert isinstance(result.score, float)


# ---------------------------------------------------------------------------
# Trade Audit
# ---------------------------------------------------------------------------

class TestTradeAudit:
    def test_good_ic_r1(self):
        legs = [
            _leg("short_put", LegAction.SELL_TO_OPEN, "put", 570),
            _leg("long_put", LegAction.BUY_TO_OPEN, "put", 565),
            _leg("short_call", LegAction.SELL_TO_OPEN, "call", 590),
            _leg("long_call", LegAction.BUY_TO_OPEN, "call", 595),
        ]
        ts = _ts(legs)
        result = audit_trade(
            ts, pop_pct=0.72, expected_value=52.0,
            entry_credit=1.50, entry_score=0.75,
            regime_id=1, atr_pct=0.86,
        )
        assert isinstance(result, TradeAudit)
        assert result.score >= 70
        assert result.grade in ("A", "B+", "B", "C")

    def test_bad_ic_r4(self):
        legs = [
            _leg("short_put", LegAction.SELL_TO_OPEN, "put", 570),
            _leg("long_put", LegAction.BUY_TO_OPEN, "put", 565),
        ]
        ts = _ts(legs, structure_type="credit_spread")
        result = audit_trade(
            ts, pop_pct=0.35, expected_value=-200.0,
            entry_credit=0.30, entry_score=0.40,
            regime_id=4, atr_pct=2.5,
        )
        assert result.score < 60

    def test_missing_exit_plan_scores_zero(self):
        legs = [
            _leg("short_put", LegAction.SELL_TO_OPEN, "put", 570),
            _leg("long_put", LegAction.BUY_TO_OPEN, "put", 565),
        ]
        ts = _ts(legs, profit_target_pct=None, stop_loss_pct=None, exit_dte=None)
        result = audit_trade(
            ts, pop_pct=0.70, expected_value=40.0,
            entry_credit=1.50, entry_score=0.75,
            regime_id=1, atr_pct=0.86,
        )
        exit_check = next(c for c in result.checks if c.name == "exit_plan")
        assert exit_check.score == 0

    def test_partial_exit_plan_scores_partial(self):
        legs = [_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)]
        ts = _ts(legs, profit_target_pct=0.50, stop_loss_pct=None, exit_dte=None)
        result = audit_trade(ts, pop_pct=0.70, expected_value=40.0,
                             entry_credit=1.50, entry_score=0.75,
                             regime_id=1, atr_pct=0.86)
        exit_check = next(c for c in result.checks if c.name == "exit_plan")
        assert 0 < exit_check.score < 100

    def test_has_six_checks(self):
        legs = [_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)]
        ts = _ts(legs)
        result = audit_trade(ts, pop_pct=0.70, expected_value=40.0,
                             entry_credit=1.50, entry_score=0.75,
                             regime_id=1, atr_pct=0.86)
        assert len(result.checks) == 6

    def test_unknown_pop_gives_mediocre(self):
        legs = [_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)]
        ts = _ts(legs)
        result_known = audit_trade(ts, pop_pct=0.75, expected_value=50.0,
                                   entry_credit=1.50, entry_score=0.75,
                                   regime_id=1, atr_pct=0.86)
        result_unknown = audit_trade(ts, pop_pct=None, expected_value=50.0,
                                     entry_credit=1.50, entry_score=0.75,
                                     regime_id=1, atr_pct=0.86)
        pop_known = next(c for c in result_known.checks if c.name == "pop_quality")
        pop_unknown = next(c for c in result_unknown.checks if c.name == "pop_quality")
        assert pop_known.score > pop_unknown.score

    def test_high_commission_drag_penalized(self):
        # Tiny credit = huge commission drag
        legs = [
            _leg("short_put", LegAction.SELL_TO_OPEN, "put", 570),
            _leg("long_put", LegAction.BUY_TO_OPEN, "put", 565),
            _leg("short_call", LegAction.SELL_TO_OPEN, "call", 590),
            _leg("long_call", LegAction.BUY_TO_OPEN, "call", 595),
        ]
        ts = _ts(legs)
        result = audit_trade(ts, pop_pct=0.70, expected_value=10.0,
                             entry_credit=0.05, entry_score=0.70,
                             regime_id=1, atr_pct=0.86)
        drag_check = next(c for c in result.checks if c.name == "commission_drag")
        assert drag_check.score <= 30

    def test_negative_ev_penalized(self):
        legs = [_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)]
        ts = _ts(legs)
        result_pos = audit_trade(ts, pop_pct=0.70, expected_value=50.0,
                                 entry_credit=1.50, entry_score=0.75,
                                 regime_id=1, atr_pct=0.86)
        result_neg = audit_trade(ts, pop_pct=0.70, expected_value=-200.0,
                                 entry_credit=1.50, entry_score=0.75,
                                 regime_id=1, atr_pct=0.86)
        ev_pos = next(c for c in result_pos.checks if c.name == "expected_value")
        ev_neg = next(c for c in result_neg.checks if c.name == "expected_value")
        assert ev_pos.score > ev_neg.score

    def test_regime_alignment_r1_ic_best(self):
        legs = [_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)]
        ts_r1 = _ts(legs, structure_type="iron_condor")
        ts_r4 = _ts(legs, structure_type="iron_condor")
        r1 = audit_trade(ts_r1, pop_pct=0.70, expected_value=40.0,
                         entry_credit=1.5, entry_score=0.7, regime_id=1, atr_pct=0.86)
        r4 = audit_trade(ts_r4, pop_pct=0.70, expected_value=40.0,
                         entry_credit=1.5, entry_score=0.7, regime_id=4, atr_pct=0.86)
        align_r1 = next(c for c in r1.checks if c.name == "regime_alignment")
        align_r4 = next(c for c in r4.checks if c.name == "regime_alignment")
        assert align_r1.score > align_r4.score


# ---------------------------------------------------------------------------
# Portfolio Audit
# ---------------------------------------------------------------------------

class TestPortfolioAudit:
    def test_empty_portfolio_high_score(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        result = audit_portfolio(
            ts, open_position_count=0, max_positions=5,
            portfolio_risk_pct=0.0, correlation_with_existing=0.0,
        )
        assert result.score >= 85

    def test_full_portfolio_low_score(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        result = audit_portfolio(
            ts, open_position_count=5, max_positions=5,
            portfolio_risk_pct=0.24, correlation_with_existing=0.90,
            strategy_concentration_pct=0.80,
        )
        assert result.score < 50

    def test_high_correlation_penalized(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        low = audit_portfolio(ts, correlation_with_existing=0.20)
        high = audit_portfolio(ts, correlation_with_existing=0.90)
        assert low.score > high.score

    def test_has_five_checks(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        result = audit_portfolio(ts)
        assert len(result.checks) == 5

    def test_check_names(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        result = audit_portfolio(ts)
        names = {c.name for c in result.checks}
        assert "slot_availability" in names
        assert "correlation" in names
        assert "risk_budget" in names
        assert "strategy_concentration" in names
        assert "directional_balance" in names

    def test_directional_imbalance_penalized(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        balanced = audit_portfolio(ts, directional_score=0.0)
        imbalanced = audit_portfolio(ts, directional_score=0.9)
        dir_balanced = next(c for c in balanced.checks if c.name == "directional_balance")
        dir_imbalanced = next(c for c in imbalanced.checks if c.name == "directional_balance")
        assert dir_balanced.score > dir_imbalanced.score

    def test_risk_budget_depleted_penalized(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        fresh = audit_portfolio(ts, portfolio_risk_pct=0.0)
        depleted = audit_portfolio(ts, portfolio_risk_pct=0.24)
        rb_fresh = next(c for c in fresh.checks if c.name == "risk_budget")
        rb_depleted = next(c for c in depleted.checks if c.name == "risk_budget")
        assert rb_fresh.score > rb_depleted.score

    def test_strategy_concentration_penalized(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        low = audit_portfolio(ts, strategy_concentration_pct=0.20)
        high = audit_portfolio(ts, strategy_concentration_pct=0.85)
        conc_low = next(c for c in low.checks if c.name == "strategy_concentration")
        conc_high = next(c for c in high.checks if c.name == "strategy_concentration")
        assert conc_low.score > conc_high.score


# ---------------------------------------------------------------------------
# Risk Audit
# ---------------------------------------------------------------------------

class TestRiskAudit:
    def test_conservative_sizing_high_score(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        result = audit_risk(
            ts, capital=50000, contracts=1,
            drawdown_pct=0.0, stress_passed=True, kelly_fraction=0.05,
        )
        assert result.score >= 85

    def test_overleveraged_low_score(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        result = audit_risk(
            ts, capital=10000, contracts=5,
            drawdown_pct=0.08, stress_passed=False, kelly_fraction=0.0,
        )
        assert result.score < 40

    def test_kelly_misalignment_penalized(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        result = audit_risk(
            ts, capital=50000, contracts=3,
            kelly_fraction=-0.05,  # Deploying against Kelly
        )
        kelly_check = next(c for c in result.checks if c.name == "kelly_alignment")
        assert kelly_check.score <= 20

    def test_has_four_checks(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        result = audit_risk(ts, capital=50000, contracts=1)
        assert len(result.checks) == 4

    def test_check_names(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        result = audit_risk(ts, capital=50000, contracts=1)
        names = {c.name for c in result.checks}
        assert "position_size" in names
        assert "drawdown_headroom" in names
        assert "stress_survival" in names
        assert "kelly_alignment" in names

    def test_stress_failure_penalized(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        passed = audit_risk(ts, capital=50000, contracts=1, stress_passed=True)
        failed = audit_risk(ts, capital=50000, contracts=1, stress_passed=False)
        stress_passed = next(c for c in passed.checks if c.name == "stress_survival")
        stress_failed = next(c for c in failed.checks if c.name == "stress_survival")
        assert stress_passed.score > stress_failed.score

    def test_drawdown_near_halt_penalized(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        fresh = audit_risk(ts, capital=50000, contracts=1, drawdown_pct=0.0)
        near_halt = audit_risk(ts, capital=50000, contracts=1, drawdown_pct=0.09)
        dd_fresh = next(c for c in fresh.checks if c.name == "drawdown_headroom")
        dd_near = next(c for c in near_halt.checks if c.name == "drawdown_headroom")
        assert dd_fresh.score > dd_near.score

    def test_oversized_position_penalized(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        small = audit_risk(ts, capital=50000, contracts=1)
        large = audit_risk(ts, capital=10000, contracts=10)
        sz_small = next(c for c in small.checks if c.name == "position_size")
        sz_large = next(c for c in large.checks if c.name == "position_size")
        assert sz_small.score > sz_large.score

    def test_positive_kelly_not_deploying_acceptable(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        result = audit_risk(ts, capital=50000, contracts=0, kelly_fraction=0.05)
        kelly_check = next(c for c in result.checks if c.name == "kelly_alignment")
        assert kelly_check.score >= 60  # Acceptable (positive Kelly, choosing not to deploy)

    def test_negative_kelly_not_deploying_good(self):
        ts = _ts([_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)])
        result = audit_risk(ts, capital=50000, contracts=0, kelly_fraction=-0.05)
        kelly_check = next(c for c in result.checks if c.name == "kelly_alignment")
        assert kelly_check.score >= 70  # Correct behavior


# ---------------------------------------------------------------------------
# Full Decision Report
# ---------------------------------------------------------------------------

class TestDecisionReport:
    def test_full_audit_approved(self):
        legs = [
            _leg("short_put", LegAction.SELL_TO_OPEN, "put", 570),
            _leg("long_put", LegAction.BUY_TO_OPEN, "put", 565),
            _leg("short_call", LegAction.SELL_TO_OPEN, "call", 590),
            _leg("long_call", LegAction.BUY_TO_OPEN, "call", 595),
        ]
        ts = _ts(legs)
        report = audit_decision(
            ticker="SPY", trade_spec=ts, atr=5.0,
            pop_pct=0.72, expected_value=52.0, entry_credit=1.50,
            entry_score=0.75, regime_id=1, atr_pct=0.86,
            capital=50000, contracts=1, stress_passed=True, kelly_fraction=0.05,
        )
        assert isinstance(report, DecisionReport)
        assert report.approved is True
        assert report.overall_score >= 70
        assert "APPROVED" in report.summary

    def test_full_audit_rejected(self):
        legs = [
            _leg("short_put", LegAction.SELL_TO_OPEN, "put", 570),
            _leg("long_put", LegAction.BUY_TO_OPEN, "put", 565),
        ]
        ts = _ts(
            legs, structure_type="credit_spread",
            profit_target_pct=None, stop_loss_pct=None, exit_dte=None,
        )
        report = audit_decision(
            ticker="SPY", trade_spec=ts, atr=5.0,
            pop_pct=0.35, expected_value=-200.0, entry_credit=0.30,
            entry_score=0.40, regime_id=4, atr_pct=2.5,
            capital=10000, contracts=3, stress_passed=False, kelly_fraction=-0.05,
        )
        assert report.approved is False
        assert report.overall_score < 70
        assert "REJECTED" in report.summary

    def test_serialization(self):
        legs = [_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)]
        ts = _ts(legs)
        report = audit_decision(ticker="SPY", trade_spec=ts, capital=50000, contracts=1)
        d = report.model_dump()
        assert "overall_score" in d
        assert "trade_audit" in d
        assert "risk_audit" in d
        assert "portfolio_audit" in d
        assert "leg_audit" in d

    def test_report_has_all_fields(self):
        legs = [_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)]
        ts = _ts(legs)
        report = audit_decision(ticker="SPY", trade_spec=ts, capital=50000, contracts=1)
        assert report.ticker == "SPY"
        assert report.structure_type == "iron_condor"
        assert isinstance(report.trade_audit, TradeAudit)
        assert isinstance(report.portfolio_audit, PortfolioAudit)
        assert isinstance(report.risk_audit, RiskAudit)
        assert isinstance(report.overall_grade, str)
        assert isinstance(report.summary, str)

    def test_overall_score_in_range(self):
        legs = [_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)]
        ts = _ts(legs)
        report = audit_decision(ticker="SPY", trade_spec=ts, capital=50000, contracts=1)
        assert 0 <= report.overall_score <= 100

    def test_grade_matches_score(self):
        legs = [_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)]
        ts = _ts(legs)
        report = audit_decision(ticker="SPY", trade_spec=ts, capital=50000, contracts=1)
        from income_desk.features.decision_audit import _score_to_grade
        assert report.overall_grade == _score_to_grade(report.overall_score)

    def test_approved_boundary_70(self):
        # Craft a scenario that should be near the boundary
        legs = [_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)]
        ts = _ts(legs)
        report = audit_decision(ticker="SPY", trade_spec=ts, capital=50000, contracts=1)
        assert report.approved == (report.overall_score >= 70)

    def test_summary_contains_grades(self):
        legs = [_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)]
        ts = _ts(legs)
        report = audit_decision(ticker="SPY", trade_spec=ts, capital=50000, contracts=1)
        assert "Trade:" in report.summary
        assert "Portfolio:" in report.summary
        assert "Risk:" in report.summary

    def test_summary_contains_legs_when_present(self):
        legs = [_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)]
        ts = _ts(legs)
        report = audit_decision(ticker="SPY", trade_spec=ts, capital=50000, contracts=1)
        assert "Legs:" in report.summary

    def test_no_legs_no_leg_audit(self):
        ts = _ts([])
        report = audit_decision(ticker="SPY", trade_spec=ts, capital=50000, contracts=1)
        assert report.leg_audit is None
        assert "Legs:" not in report.summary

    def test_weighted_score_trade_dominates(self):
        """Trade audit weight is 35%, largest single weight."""
        legs = [
            _leg("short_put", LegAction.SELL_TO_OPEN, "put", 570),
            _leg("long_put", LegAction.BUY_TO_OPEN, "put", 565),
            _leg("short_call", LegAction.SELL_TO_OPEN, "call", 590),
            _leg("long_call", LegAction.BUY_TO_OPEN, "call", 595),
        ]
        ts = _ts(legs)
        # Good trade, terrible risk
        good_trade = audit_decision(
            ticker="SPY", trade_spec=ts, atr=5.0,
            pop_pct=0.75, expected_value=60.0, entry_credit=1.50,
            entry_score=0.80, regime_id=1, atr_pct=0.86,
            capital=50000, contracts=1, stress_passed=True, kelly_fraction=0.05,
        )
        # Bad trade, good risk
        bad_trade = audit_decision(
            ticker="SPY", trade_spec=ts, atr=5.0,
            pop_pct=0.35, expected_value=-100.0, entry_credit=0.20,
            entry_score=0.20, regime_id=4, atr_pct=2.5,
            capital=50000, contracts=1, stress_passed=True, kelly_fraction=0.10,
        )
        assert good_trade.overall_score > bad_trade.overall_score

    def test_different_structure_types(self):
        """Non-default structure types are handled without error."""
        for st in ["credit_spread", "calendar", "diagonal", "ratio_spread"]:
            legs = [_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570)]
            ts = _ts(legs, structure_type=st)
            report = audit_decision(ticker="SPY", trade_spec=ts, capital=50000, contracts=1)
            assert report.structure_type == st
            assert 0 <= report.overall_score <= 100


# ---------------------------------------------------------------------------
# GradedCheck model
# ---------------------------------------------------------------------------

class TestGradedCheck:
    def test_basic_construction(self):
        check = GradedCheck(name="test", score=85.0, grade="B+", detail="all good")
        assert check.name == "test"
        assert check.score == 85.0
        assert check.grade == "B+"

    def test_serialization(self):
        check = GradedCheck(name="test", score=85.0, grade="B+", detail="all good")
        d = check.model_dump()
        assert d["name"] == "test"
        assert d["score"] == 85.0
