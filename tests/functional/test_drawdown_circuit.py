"""Functional tests: drawdown circuit breaker and portfolio risk dashboard."""
import pytest

from market_analyzer.risk import (
    check_drawdown_circuit_breaker,
    compute_risk_dashboard,
    PortfolioPosition,
    GreeksLimits,
)


class TestDrawdownCircuitBreakerFunctional:
    @pytest.mark.daily
    def test_circuit_breaker_not_triggered_at_5pct_dd(self) -> None:
        """5% drawdown < 10% threshold → is_triggered = False."""
        account_peak = 50_000.0
        current = 47_500.0  # 5% down
        result = check_drawdown_circuit_breaker(current, account_peak, circuit_breaker_pct=0.10)
        assert result.is_triggered is False
        assert result.drawdown_pct == 0.05

    @pytest.mark.daily
    def test_circuit_breaker_triggered_at_10pct_dd(self) -> None:
        """At exactly 10% drawdown → is_triggered = True."""
        account_peak = 50_000.0
        current = 45_000.0  # 10% down
        result = check_drawdown_circuit_breaker(current, account_peak, circuit_breaker_pct=0.10)
        assert result.is_triggered is True
        assert result.drawdown_pct == 0.10

    @pytest.mark.daily
    def test_circuit_breaker_triggered_at_12pct_dd(self) -> None:
        """12% drawdown > 10% threshold → is_triggered = True."""
        account_peak = 50_000.0
        current = 44_000.0  # 12% down
        result = check_drawdown_circuit_breaker(current, account_peak, circuit_breaker_pct=0.10)
        assert result.is_triggered is True
        assert result.drawdown_pct == 0.12

    @pytest.mark.daily
    def test_drawdown_pct_is_calculated_correctly(self) -> None:
        """Drawdown % = (peak - current) / peak."""
        account_peak = 100_000.0
        current = 75_000.0  # 25% down
        result = check_drawdown_circuit_breaker(current, account_peak, circuit_breaker_pct=0.30)
        assert result.drawdown_pct == 0.25
        assert result.drawdown_dollars == 25_000.0

    def test_circuit_breaker_at_zero_drawdown(self) -> None:
        """No drawdown (peak = current) → is_triggered = False."""
        account_peak = 50_000.0
        current = 50_000.0
        result = check_drawdown_circuit_breaker(current, account_peak, circuit_breaker_pct=0.10)
        assert result.is_triggered is False
        assert result.drawdown_pct == 0.0


class TestRiskDashboardFunctional:
    @pytest.mark.daily
    def test_empty_portfolio_can_open_trades(self) -> None:
        """No open positions → can_open_new_trades = True."""
        result = compute_risk_dashboard(
            positions=[],
            account_nlv=50_000.0,
            account_peak=50_000.0,
            max_positions=5,
        )
        assert result.can_open_new_trades is True
        assert result.slots_remaining == 5

    @pytest.mark.daily
    def test_portfolio_at_max_positions_cannot_open(self) -> None:
        """5 positions in 5-slot account → can_open_new_trades = False."""
        positions = [
            PortfolioPosition(
                ticker=f"T{i}",
                entry_date="2026-03-01",
                entry_price=1.00,
                current_price=1.00,
                quantity=1,
                delta=0.3,
                theta=0.01,
                vega=0.02,
                gamma=0.001,
                position_type="long_call",
                exit_price=None,
                exit_date=None,
            )
            for i in range(5)
        ]
        result = compute_risk_dashboard(
            positions=positions,
            account_nlv=50_000.0,
            account_peak=50_000.0,
            max_positions=5,
        )
        assert result.can_open_new_trades is False
        assert result.slots_remaining == 0

    @pytest.mark.daily
    def test_drawdown_triggered_prevents_new_trades(self) -> None:
        """10% drawdown triggers circuit breaker → can_open_new_trades = False."""
        result = compute_risk_dashboard(
            positions=[],
            account_nlv=45_000.0,
            account_peak=50_000.0,
            max_positions=5,
            circuit_breaker_pct=0.10,
        )
        assert result.drawdown.is_triggered is True
        assert result.can_open_new_trades is False

    @pytest.mark.daily
    def test_risk_dashboard_returns_correct_greeks_limits(self) -> None:
        """Risk dashboard should reflect passed greeks_limits or use defaults."""
        custom_limits = GreeksLimits(
            max_abs_delta=25.0,
            max_abs_theta_pct=0.3,
            max_abs_vega_pct=0.5,
            max_abs_gamma=5.0,
        )
        result = compute_risk_dashboard(
            positions=[],
            account_nlv=50_000.0,
            account_peak=50_000.0,
            max_positions=5,
            greeks_limits=custom_limits,
        )
        assert result.greeks_within_limits is True  # Empty portfolio always within limits

    def test_max_new_trade_size_pct_with_multiple_positions(self) -> None:
        """With 2 of 5 slots used, max_new_trade_size_pct should allow room."""
        positions = [
            PortfolioPosition(
                ticker="T1",
                entry_date="2026-03-01",
                entry_price=1.00,
                current_price=1.00,
                quantity=1,
                delta=0.3,
                theta=0.01,
                vega=0.02,
                gamma=0.001,
                position_type="long_call",
                exit_price=None,
                exit_date=None,
            ),
            PortfolioPosition(
                ticker="T2",
                entry_date="2026-03-01",
                entry_price=1.00,
                current_price=1.00,
                quantity=1,
                delta=0.3,
                theta=0.01,
                vega=0.02,
                gamma=0.001,
                position_type="long_call",
                exit_price=None,
                exit_date=None,
            ),
        ]
        result = compute_risk_dashboard(
            positions=positions,
            account_nlv=50_000.0,
            account_peak=50_000.0,
            max_positions=5,
        )
        assert result.can_open_new_trades is True
        assert result.slots_remaining == 3
        assert result.max_new_trade_size_pct > 0
