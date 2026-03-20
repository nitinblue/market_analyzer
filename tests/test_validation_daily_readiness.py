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


# ---------------------------------------------------------------------------
# Task 8: Check #10 — IV rank quality in daily validation
# ---------------------------------------------------------------------------


class TestIVRankQualityCheck:
    """Tests for check #10: iv_rank_quality."""

    def _run_with_iv_rank(self, iv_rank, ticker_type="etf"):
        """Run daily checks with IV rank and return the iv_rank_quality check."""
        from market_analyzer.models.opportunity import LegAction, LegSpec, TradeSpec
        legs = [
            LegSpec(role="short_put", action=LegAction.SELL_TO_OPEN, option_type="put",
                    strike=570.0, strike_label="test", expiration=date(2026, 4, 17),
                    days_to_expiry=30, atm_iv_at_expiry=0.22),
            LegSpec(role="long_put", action=LegAction.BUY_TO_OPEN, option_type="put",
                    strike=565.0, strike_label="test", expiration=date(2026, 4, 17),
                    days_to_expiry=30, atm_iv_at_expiry=0.22),
            LegSpec(role="short_call", action=LegAction.SELL_TO_OPEN, option_type="call",
                    strike=590.0, strike_label="test", expiration=date(2026, 4, 17),
                    days_to_expiry=30, atm_iv_at_expiry=0.22),
            LegSpec(role="long_call", action=LegAction.BUY_TO_OPEN, option_type="call",
                    strike=595.0, strike_label="test", expiration=date(2026, 4, 17),
                    days_to_expiry=30, atm_iv_at_expiry=0.22),
        ]
        trade_spec = TradeSpec(
            ticker="SPY", legs=legs, underlying_price=580.0,
            target_dte=30, target_expiration=date(2026, 4, 17),
            spec_rationale="test",
            structure_type="iron_condor", order_side="credit",
            profit_target_pct=0.50, stop_loss_pct=2.0, exit_dte=21,
        )
        report = run_daily_checks(
            ticker="SPY",
            trade_spec=trade_spec,
            entry_credit=1.50,
            regime_id=1,
            atr_pct=1.0,
            current_price=580.0,
            avg_bid_ask_spread_pct=0.5,
            dte=30,
            rsi=50.0,
            iv_rank=iv_rank,
            ticker_type=ticker_type,
        )
        iv_checks = [c for c in report.checks if c.name == "iv_rank_quality"]
        return iv_checks[0] if iv_checks else None

    def test_good_iv_rank_passes(self) -> None:
        check = self._run_with_iv_rank(35.0, "etf")
        assert check is not None
        assert check.severity == Severity.PASS

    def test_marginal_iv_rank_warns(self) -> None:
        check = self._run_with_iv_rank(25.0, "etf")
        assert check is not None
        assert check.severity == Severity.WARN

    def test_low_iv_rank_fails(self) -> None:
        check = self._run_with_iv_rank(15.0, "etf")
        assert check is not None
        assert check.severity == Severity.FAIL

    def test_no_iv_rank_warns(self) -> None:
        check = self._run_with_iv_rank(None, "etf")
        assert check is not None
        assert check.severity == Severity.WARN

    def test_equity_higher_threshold(self) -> None:
        # 35 is "good" for ETF but "wait" for equity
        check_etf = self._run_with_iv_rank(35.0, "etf")
        check_eq = self._run_with_iv_rank(35.0, "equity")
        assert check_etf.severity == Severity.PASS
        assert check_eq.severity == Severity.WARN

    def test_10_checks_total(self) -> None:
        """Daily suite now has 10 checks."""
        from market_analyzer.models.opportunity import LegAction, LegSpec, TradeSpec
        legs = [
            LegSpec(role="short_put", action=LegAction.SELL_TO_OPEN, option_type="put",
                    strike=570.0, strike_label="test", expiration=date(2026, 4, 17),
                    days_to_expiry=30, atm_iv_at_expiry=0.22),
            LegSpec(role="long_put", action=LegAction.BUY_TO_OPEN, option_type="put",
                    strike=565.0, strike_label="test", expiration=date(2026, 4, 17),
                    days_to_expiry=30, atm_iv_at_expiry=0.22),
            LegSpec(role="short_call", action=LegAction.SELL_TO_OPEN, option_type="call",
                    strike=590.0, strike_label="test", expiration=date(2026, 4, 17),
                    days_to_expiry=30, atm_iv_at_expiry=0.22),
            LegSpec(role="long_call", action=LegAction.BUY_TO_OPEN, option_type="call",
                    strike=595.0, strike_label="test", expiration=date(2026, 4, 17),
                    days_to_expiry=30, atm_iv_at_expiry=0.22),
        ]
        trade_spec = TradeSpec(
            ticker="SPY", legs=legs, underlying_price=580.0,
            target_dte=30, target_expiration=date(2026, 4, 17),
            spec_rationale="test",
            structure_type="iron_condor", order_side="credit",
            profit_target_pct=0.50, stop_loss_pct=2.0, exit_dte=21,
        )
        report = run_daily_checks(
            ticker="SPY",
            trade_spec=trade_spec,
            entry_credit=1.50, regime_id=1, atr_pct=1.0,
            current_price=580.0, avg_bid_ask_spread_pct=0.5,
            dte=30, rsi=50.0, iv_rank=35.0,
        )
        assert len(report.checks) == 10
