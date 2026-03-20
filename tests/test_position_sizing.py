"""Tests for Kelly criterion position sizing."""

import pytest
from market_analyzer.features.position_sizing import (
    KellyResult,
    PortfolioExposure,
    compute_kelly_fraction,
    compute_kelly_position_size,
)


class TestKellyFraction:
    def test_high_pop_good_rr_positive_kelly(self) -> None:
        """POP 70%, R:R 1:2 (max_profit $200, max_loss $400) -> positive Kelly."""
        f = compute_kelly_fraction(pop_pct=0.70, max_profit=200, max_loss=400)
        assert f > 0
        # Kelly = (0.70 * 0.5 - 0.30) / 0.5 = (0.35 - 0.30) / 0.5 = 0.10
        assert f == pytest.approx(0.10, abs=0.01)

    def test_coin_flip_even_payout_zero_kelly(self) -> None:
        """POP 50%, even R:R -> Kelly ~= 0 (no edge)."""
        f = compute_kelly_fraction(pop_pct=0.50, max_profit=100, max_loss=100)
        assert f == pytest.approx(0.0, abs=0.01)

    def test_low_pop_negative_kelly(self) -> None:
        """POP 30%, R:R 1:3 -> Kelly negative -> returns 0 (don't trade)."""
        f = compute_kelly_fraction(pop_pct=0.30, max_profit=100, max_loss=300)
        assert f == 0.0

    def test_high_pop_income_trade(self) -> None:
        """Typical IC: POP 72%, credit $180, max_loss $320 -> positive Kelly."""
        f = compute_kelly_fraction(pop_pct=0.72, max_profit=180, max_loss=320)
        assert f > 0.05
        assert f < 0.25  # Under cap

    def test_capped_at_25_percent(self) -> None:
        """Even with extreme POP, never bet more than 25%."""
        f = compute_kelly_fraction(pop_pct=0.95, max_profit=500, max_loss=100)
        assert f <= 0.25

    def test_zero_loss_returns_zero(self) -> None:
        f = compute_kelly_fraction(pop_pct=0.70, max_profit=200, max_loss=0)
        assert f == 0.0

    def test_zero_profit_returns_zero(self) -> None:
        f = compute_kelly_fraction(pop_pct=0.70, max_profit=0, max_loss=200)
        assert f == 0.0


class TestKellyPositionSize:
    def test_basic_sizing_50k_account(self) -> None:
        """50K account, good IC trade -> reasonable contract count."""
        result = compute_kelly_position_size(
            capital=50000, pop_pct=0.72, max_profit=180, max_loss=320,
            risk_per_contract=500,  # 5-wide IC
        )
        assert isinstance(result, KellyResult)
        assert result.recommended_contracts >= 1
        assert result.recommended_contracts <= 10  # Reasonable for 50K
        assert result.full_kelly_fraction > 0

    def test_negative_ev_zero_contracts(self) -> None:
        """EV-negative trade -> 0 contracts."""
        result = compute_kelly_position_size(
            capital=50000, pop_pct=0.30, max_profit=100, max_loss=400,
            risk_per_contract=500,
        )
        assert result.recommended_contracts == 0
        assert result.full_kelly_fraction == 0.0

    def test_half_kelly_default(self) -> None:
        """Default safety_factor=0.5 gives half Kelly."""
        result = compute_kelly_position_size(
            capital=50000, pop_pct=0.72, max_profit=180, max_loss=320,
            risk_per_contract=500,
        )
        assert result.half_kelly_fraction == pytest.approx(
            result.full_kelly_fraction * 0.5, abs=0.001
        )

    def test_portfolio_full_zero_contracts(self) -> None:
        """All position slots used -> 0 contracts."""
        exposure = PortfolioExposure(
            open_position_count=5, max_positions=5,
            current_risk_pct=0.20, max_risk_pct=0.25,
        )
        result = compute_kelly_position_size(
            capital=50000, pop_pct=0.72, max_profit=180, max_loss=320,
            risk_per_contract=500, exposure=exposure,
        )
        assert result.recommended_contracts == 0

    def test_drawdown_halt_zero_contracts(self) -> None:
        """Drawdown at circuit breaker -> 0 contracts."""
        exposure = PortfolioExposure(
            drawdown_pct=0.10, drawdown_halt_pct=0.10,
        )
        result = compute_kelly_position_size(
            capital=50000, pop_pct=0.72, max_profit=180, max_loss=320,
            risk_per_contract=500, exposure=exposure,
        )
        assert result.recommended_contracts == 0
        assert "HALTED" in result.rationale

    def test_partial_drawdown_reduces_size(self) -> None:
        """5% drawdown (half of 10% halt) -> roughly half size."""
        no_dd = compute_kelly_position_size(
            capital=50000, pop_pct=0.72, max_profit=180, max_loss=320,
            risk_per_contract=500,
        )
        with_dd = compute_kelly_position_size(
            capital=50000, pop_pct=0.72, max_profit=180, max_loss=320,
            risk_per_contract=500,
            exposure=PortfolioExposure(drawdown_pct=0.05, drawdown_halt_pct=0.10),
        )
        assert with_dd.recommended_contracts <= no_dd.recommended_contracts

    def test_risk_budget_nearly_full_reduces_size(self) -> None:
        """Risk at 20% of 25% limit -> reduced sizing."""
        exposure = PortfolioExposure(
            open_position_count=3, max_positions=5,
            current_risk_pct=0.20, max_risk_pct=0.25,
        )
        result = compute_kelly_position_size(
            capital=50000, pop_pct=0.72, max_profit=180, max_loss=320,
            risk_per_contract=500, exposure=exposure,
        )
        assert result.portfolio_adjusted_fraction < result.half_kelly_fraction

    def test_never_exceeds_fixed_risk_cap(self) -> None:
        """Even with high Kelly, never exceed 2% fixed risk cap."""
        result = compute_kelly_position_size(
            capital=50000, pop_pct=0.90, max_profit=400, max_loss=100,
            risk_per_contract=500,
        )
        max_by_fixed = int(50000 * 0.02 / 500)  # 2 contracts
        assert result.recommended_contracts <= max_by_fixed

    def test_200k_ira_more_contracts(self) -> None:
        """200K account -> more contracts than 50K for same trade."""
        r_50k = compute_kelly_position_size(
            capital=50000, pop_pct=0.72, max_profit=180, max_loss=320,
            risk_per_contract=500,
        )
        r_200k = compute_kelly_position_size(
            capital=200000, pop_pct=0.72, max_profit=180, max_loss=320,
            risk_per_contract=500,
        )
        assert r_200k.recommended_contracts >= r_50k.recommended_contracts

    def test_components_present(self) -> None:
        """All components should be in output dict."""
        result = compute_kelly_position_size(
            capital=50000, pop_pct=0.72, max_profit=180, max_loss=320,
            risk_per_contract=500,
        )
        assert "full_kelly" in result.components
        assert "safety_factor" in result.components
        assert "after_safety" in result.components

    def test_serialization(self) -> None:
        """KellyResult must serialize for MCP."""
        result = compute_kelly_position_size(
            capital=50000, pop_pct=0.72, max_profit=180, max_loss=320,
            risk_per_contract=500,
        )
        d = result.model_dump()
        assert "recommended_contracts" in d
        assert "full_kelly_fraction" in d
