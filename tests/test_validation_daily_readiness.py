"""Tests for daily readiness and adversarial check orchestrators."""
from datetime import date, timedelta, time

import pytest

from market_analyzer.trade_spec_factory import build_iron_condor
from market_analyzer.validation.models import Severity, Suite
from market_analyzer.validation.daily_readiness import (
    run_daily_checks,
    run_adversarial_checks,
)


def _ic_spec():
    exp = date.today() + timedelta(days=30)
    return build_iron_condor(
        ticker="SPY", underlying_price=580.0,
        short_put=570.0, long_put=565.0,
        short_call=590.0, long_call=595.0,
        expiration=exp.isoformat(),
    )


class TestRunDailyChecks:
    def test_returns_validation_report(self) -> None:
        report = run_daily_checks(
            ticker="SPY",
            trade_spec=_ic_spec(),
            entry_credit=1.50,
            regime_id=1,
            atr_pct=1.0,
            current_price=580.0,
            avg_bid_ask_spread_pct=0.8,
            dte=30,
            rsi=50.0,
        )
        assert report.ticker == "SPY"
        assert report.suite == Suite.DAILY
        assert len(report.checks) >= 5

    def test_ideal_conditions_is_ready(self) -> None:
        """R1 + good IV + centered RSI + tight spread + good credit → READY."""
        report = run_daily_checks(
            ticker="SPY",
            trade_spec=_ic_spec(),
            entry_credit=3.00,   # $3.00 credit → 18% annualized ROC → PASS
            regime_id=1,
            atr_pct=1.0,
            current_price=580.0,
            avg_bid_ask_spread_pct=0.8,
            dte=30,
            rsi=50.0,
            iv_rank=45.0,
        )
        assert report.is_ready is True

    def test_poor_fill_quality_blocks_trade(self) -> None:
        """Wide spread → NOT READY."""
        report = run_daily_checks(
            ticker="SPY",
            trade_spec=_ic_spec(),
            entry_credit=1.50,
            regime_id=1,
            atr_pct=1.0,
            current_price=580.0,
            avg_bid_ask_spread_pct=5.0,   # too wide
            dte=30,
            rsi=50.0,
        )
        assert report.is_ready is False
        fail_names = [c.name for c in report.checks if c.severity == Severity.FAIL]
        assert "fill_quality" in fail_names

    def test_microscopic_credit_blocks_trade(self) -> None:
        report = run_daily_checks(
            ticker="SPY",
            trade_spec=_ic_spec(),
            entry_credit=0.15,   # too thin
            regime_id=1,
            atr_pct=1.0,
            current_price=580.0,
            avg_bid_ask_spread_pct=0.8,
            dte=30,
            rsi=50.0,
        )
        assert report.is_ready is False

    def test_report_has_exit_discipline_check(self) -> None:
        report = run_daily_checks(
            ticker="SPY",
            trade_spec=_ic_spec(),
            entry_credit=1.50,
            regime_id=1,
            atr_pct=1.0,
            current_price=580.0,
            avg_bid_ask_spread_pct=0.8,
            dte=30,
            rsi=50.0,
        )
        check_names = [c.name for c in report.checks]
        assert "exit_discipline" in check_names


class TestRunAdversarialChecks:
    def test_returns_validation_report(self) -> None:
        report = run_adversarial_checks(
            ticker="SPY",
            trade_spec=_ic_spec(),
            entry_credit=1.50,
            atr_pct=1.0,
        )
        assert report.suite == Suite.ADVERSARIAL
        assert len(report.checks) >= 3

    def test_defined_risk_ic_passes_adversarial(self) -> None:
        report = run_adversarial_checks(
            ticker="SPY",
            trade_spec=_ic_spec(),
            entry_credit=1.50,
            atr_pct=1.0,
        )
        # Defined risk IC should pass gamma and breakeven checks
        fail_names = [c.name for c in report.checks if c.severity == Severity.FAIL]
        assert "gamma_stress" not in fail_names
        assert "breakeven_spread" not in fail_names
