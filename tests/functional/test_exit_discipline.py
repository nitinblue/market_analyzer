"""Functional tests: exit discipline via monitor_exit_conditions."""
import pytest
from datetime import date, timedelta

from income_desk.trade_spec_factory import build_iron_condor
from income_desk.trade_lifecycle import monitor_exit_conditions


def _ic():
    exp = date.today() + timedelta(days=15)
    return build_iron_condor(
        ticker="SPY", underlying_price=580.0,
        short_put=570.0, long_put=565.0,
        short_call=590.0, long_call=595.0,
        expiration=exp.isoformat(),
    )


class TestExitDisciplineFunctional:
    @pytest.mark.daily
    def test_profit_target_at_50pct_fires(self) -> None:
        """Entry at $1.50 credit, current mid at $0.75 (50% of max profit) → should_close = True."""
        result = monitor_exit_conditions(
            trade_id="t1",
            ticker="SPY",
            structure_type="iron_condor",
            order_side="credit",
            entry_price=1.50,
            current_mid_price=0.75,
            contracts=1,
            dte_remaining=14,
            regime_id=1,
            entry_regime_id=1,
            profit_target_pct=0.50,
            stop_loss_pct=2.0,
            exit_dte=21,
        )
        assert result.should_close is True, f"Expected should_close=True at 50% PT. Summary: {result.summary}"

    @pytest.mark.daily
    def test_stop_loss_at_2x_credit_fires(self) -> None:
        """Entry at $1.50 credit, current mid at $3.00 (2x credit stop) → should_close = True."""
        result = monitor_exit_conditions(
            trade_id="t2",
            ticker="SPY",
            structure_type="iron_condor",
            order_side="credit",
            entry_price=1.50,
            current_mid_price=3.00,
            contracts=1,
            dte_remaining=14,
            regime_id=1,
            entry_regime_id=1,
            profit_target_pct=0.50,
            stop_loss_pct=2.0,
            exit_dte=21,
        )
        assert result.should_close is True, f"Expected should_close=True at 2x stop. Summary: {result.summary}"

    @pytest.mark.daily
    def test_dte_exit_fires_at_threshold(self) -> None:
        """DTE drops to 21 (exit_dte threshold) → should_close = True."""
        result = monitor_exit_conditions(
            trade_id="t3",
            ticker="SPY",
            structure_type="iron_condor",
            order_side="credit",
            entry_price=1.50,
            current_mid_price=1.40,  # Still profitable
            contracts=1,
            dte_remaining=21,
            regime_id=1,
            entry_regime_id=1,
            profit_target_pct=0.50,
            stop_loss_pct=2.0,
            exit_dte=21,
        )
        assert result.should_close is True, f"Expected should_close=True at exit_dte. Summary: {result.summary}"

    def test_healthy_trade_does_not_exit_early(self) -> None:
        """Healthy mid ($1.40) with plenty of DTE (25) and exit_dte=21 → should_close = False."""
        result = monitor_exit_conditions(
            trade_id="t4",
            ticker="SPY",
            structure_type="iron_condor",
            order_side="credit",
            entry_price=1.50,
            current_mid_price=1.40,
            contracts=1,
            dte_remaining=25,  # More than exit_dte threshold
            regime_id=1,
            entry_regime_id=1,
            profit_target_pct=0.50,
            stop_loss_pct=2.0,
            exit_dte=21,
        )
        assert result.should_close is False, f"Expected should_close=False for healthy trade. Summary: {result.summary}"
