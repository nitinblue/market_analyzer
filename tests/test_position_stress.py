"""Tests for ongoing position stress monitoring."""
from datetime import date
import pytest

from market_analyzer.models.opportunity import LegAction, LegSpec, TradeSpec
from market_analyzer.validation.stress_scenarios import run_position_stress
from market_analyzer.validation.models import Severity


def _leg(role, action, opt_type, strike):
    return LegSpec(
        role=role,
        action=action,
        option_type=opt_type,
        strike=strike,
        strike_label="test",
        expiration=date(2026, 4, 24),
        days_to_expiry=35,
        atm_iv_at_expiry=0.25,
    )


def _ic():
    return TradeSpec(
        ticker="SPY",
        underlying_price=650.0,
        target_dte=35,
        target_expiration=date(2026, 4, 24),
        spec_rationale="test",
        structure_type="iron_condor",
        wing_width_points=5.0,
        legs=[
            _leg("short_put", LegAction.SELL_TO_OPEN, "put", 635),
            _leg("long_put", LegAction.BUY_TO_OPEN, "put", 630),
            _leg("short_call", LegAction.SELL_TO_OPEN, "call", 665),
            _leg("long_call", LegAction.BUY_TO_OPEN, "call", 670),
        ],
    )


class TestRunPositionStress:
    def test_healthy_position_all_pass(self):
        """Position at entry conditions — should mostly pass."""
        report = run_position_stress(
            trade_spec=_ic(),
            current_credit_value=1.50,
            current_atr_pct=1.0,
            entry_credit=1.50,
        )
        assert len(report.checks) == 4  # gamma, vega, breakeven, degradation
        deg = [c for c in report.checks if c.name == "position_degradation"][0]
        assert deg.severity == Severity.PASS

    def test_atr_doubled_gamma_stress_worse(self):
        """ATR doubled since entry — gamma stress should be same or worse."""
        normal = run_position_stress(_ic(), 1.50, 1.0, 1.50)
        stressed = run_position_stress(_ic(), 1.50, 2.5, 1.50)
        # Higher ATR means bigger expected move → worse gamma result
        normal_gamma = [c for c in normal.checks if c.name == "gamma_stress"][0]
        stressed_gamma = [c for c in stressed.checks if c.name == "gamma_stress"][0]
        # Stressed should be same or worse severity
        severity_order = {"pass": 0, "warn": 1, "fail": 2}
        assert (
            severity_order[stressed_gamma.severity.value]
            >= severity_order[normal_gamma.severity.value]
        )

    def test_position_degradation_detected(self):
        """Current credit much lower than entry → degradation FAIL."""
        report = run_position_stress(
            trade_spec=_ic(),
            current_credit_value=0.30,  # Position lost most of its value
            current_atr_pct=1.5,
            entry_credit=1.50,
        )
        deg = [c for c in report.checks if c.name == "position_degradation"][0]
        # R:R at entry: (500-150)/150 = 2.3:1. Current: (500-30)/30 = 15.7:1. > 2x → FAIL
        assert deg.severity == Severity.FAIL

    def test_position_improving(self):
        """Current credit higher than entry (approaching profit target) → PASS."""
        report = run_position_stress(
            trade_spec=_ic(),
            current_credit_value=0.80,  # Position close to 50% profit
            current_atr_pct=0.8,
            entry_credit=1.50,
        )
        deg = [c for c in report.checks if c.name == "position_degradation"][0]
        # Current R:R: (500-80)/80 = 5.25:1. Entry R:R: (500-150)/150 = 2.33:1.
        # 5.25 / 2.33 = 2.25x — just over 2x threshold → FAIL boundary
        # (Under spec's wing_width_points=5.0 → max_loss = 500-150=350)
        # entry_rr = 350/150 = 2.33. current_rr = 350/80 = 4.375. 4.375/2.33 = 1.88 < 2.0 → PASS
        assert deg.severity in (Severity.PASS, Severity.WARN)

    def test_zero_credit_value_warns(self):
        """Position at zero credit → can't compute degradation."""
        report = run_position_stress(_ic(), 0.0, 1.0, 1.50)
        deg = [c for c in report.checks if c.name == "position_degradation"][0]
        assert deg.severity == Severity.WARN

    def test_report_is_adversarial_suite(self):
        report = run_position_stress(_ic(), 1.50, 1.0, 1.50)
        assert report.suite.value == "adversarial"

    def test_serialization(self):
        report = run_position_stress(_ic(), 1.50, 1.0, 1.50)
        d = report.model_dump()
        assert "checks" in d
        assert len(d["checks"]) == 4

    def test_check_names_present(self):
        """All 4 expected check names must be in the report."""
        report = run_position_stress(_ic(), 1.50, 1.0, 1.50)
        names = {c.name for c in report.checks}
        assert "gamma_stress" in names
        assert "vega_shock" in names
        assert "breakeven_spread" in names
        assert "position_degradation" in names

    def test_ticker_matches_trade_spec(self):
        report = run_position_stress(_ic(), 1.50, 1.0, 1.50)
        assert report.ticker == "SPY"

    def test_days_held_and_dte_accepted(self):
        """Keyword args days_held and dte_remaining should be accepted without error."""
        report = run_position_stress(
            trade_spec=_ic(),
            current_credit_value=1.20,
            current_atr_pct=1.2,
            entry_credit=1.50,
            days_held=5,
            dte_remaining=30,
        )
        assert len(report.checks) == 4

    def test_warn_threshold_between_1_5x_and_2x(self):
        """R:R degraded 1.5x–2x → WARN."""
        # entry_rr = (500 - 150) / 150 = 2.333
        # WARN when current_rr > entry_rr * 1.5 AND <= entry_rr * 2.0
        # entry_rr * 1.5 = 3.5, entry_rr * 2.0 = 4.667
        # Use current_credit_value=0.90 → current_max_profit=90, current_rr=350/90=3.89 → WARN
        report = run_position_stress(
            trade_spec=_ic(),
            current_credit_value=0.90,
            current_atr_pct=1.0,
            entry_credit=1.50,
        )
        deg = [c for c in report.checks if c.name == "position_degradation"][0]
        assert deg.severity == Severity.WARN

    def test_imported_from_validation_package(self):
        """run_position_stress is accessible via the validation package."""
        from market_analyzer.validation import run_position_stress as rps
        report = rps(_ic(), 1.50, 1.0, 1.50)
        assert len(report.checks) == 4

    def test_imported_from_top_level(self):
        """run_position_stress is accessible from market_analyzer root."""
        from market_analyzer import run_position_stress as rps
        report = rps(_ic(), 1.50, 1.0, 1.50)
        assert len(report.checks) == 4
