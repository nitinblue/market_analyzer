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


class TestExports:
    def test_kelly_importable_from_top_level(self) -> None:
        from market_analyzer import (
            KellyResult,
            KellyPortfolioExposure,
            compute_kelly_fraction,
            compute_kelly_position_size,
        )
        assert callable(compute_kelly_fraction)
        assert callable(compute_kelly_position_size)


# ---------------------------------------------------------------------------
# Task 4: Correlation + Margin-Regime Sizing
# ---------------------------------------------------------------------------

from market_analyzer.features.position_sizing import (  # noqa: E402
    CorrelationAdjustment,
    RegimeMarginEstimate,
    compute_pairwise_correlation,
    adjust_kelly_for_correlation,
    compute_regime_adjusted_bp,
)


class TestPairwiseCorrelation:
    def test_perfect_positive_correlation(self) -> None:
        a = [0.01 * i for i in range(60)]
        b = [0.01 * i for i in range(60)]
        corr = compute_pairwise_correlation(a, b)
        assert corr == pytest.approx(1.0, abs=0.01)

    def test_perfect_negative_correlation(self) -> None:
        a = [0.01 * i for i in range(60)]
        b = [-0.01 * i for i in range(60)]
        corr = compute_pairwise_correlation(a, b)
        assert corr == pytest.approx(-1.0, abs=0.01)

    def test_uncorrelated_near_zero(self) -> None:
        import math
        a = [math.sin(i) for i in range(60)]
        b = [math.cos(i * 7.3) for i in range(60)]
        corr = compute_pairwise_correlation(a, b)
        assert abs(corr) < 0.5  # Not exactly 0 but small

    def test_insufficient_data_returns_zero(self) -> None:
        corr = compute_pairwise_correlation([0.01, 0.02], [0.01, 0.02])
        assert corr == 0.0

    def test_lookback_limits_data(self) -> None:
        # Build a=increasing, b=increasing for first 50, then b=decreasing for last 10
        # Use lookback=10 vs lookback=50 to verify different windows give different results
        a = [float(i) for i in range(60)]
        # b: perfectly correlated for first 50, then reverses
        b = [float(i) for i in range(50)] + [float(50 - i) for i in range(10)]
        corr_50 = compute_pairwise_correlation(a, b, lookback=50)  # correlated window
        corr_10 = compute_pairwise_correlation(a, b, lookback=10)  # anti-correlated window
        # Over the correlated 50-point window, corr should be > 0
        assert corr_50 > 0
        # Over the recent 10-point window (a goes up, b goes down), corr < 0
        assert corr_10 < 0

    def test_zero_variance_returns_zero(self) -> None:
        a = [0.01] * 60
        b = [0.02 * i for i in range(60)]
        corr = compute_pairwise_correlation(a, b)
        assert corr == 0.0

    def test_bounded_minus_one_to_one(self) -> None:
        import random
        random.seed(42)
        a = [random.gauss(0, 0.02) for _ in range(60)]
        b = [random.gauss(0, 0.02) for _ in range(60)]
        corr = compute_pairwise_correlation(a, b)
        assert -1.0 <= corr <= 1.0


class TestCorrelationAdjustedKelly:
    def _base_kelly(self) -> KellyResult:
        return compute_kelly_position_size(
            capital=50000, pop_pct=0.72, max_profit=180, max_loss=320,
            risk_per_contract=500,
        )

    def test_no_existing_positions_no_penalty(self) -> None:
        kelly = self._base_kelly()
        result = adjust_kelly_for_correlation(
            kelly, "AAPL", [], lambda a, b: 0.0,
        )
        assert result.correlation_penalty == 0.0
        assert result.adjusted_kelly_fraction == result.original_kelly_fraction

    def test_high_correlation_penalty(self) -> None:
        kelly = self._base_kelly()
        result = adjust_kelly_for_correlation(
            kelly, "QQQ", ["SPY"],
            lambda a, b: 0.90,  # SPY/QQQ highly correlated
        )
        assert result.correlation_penalty > 0
        assert result.adjusted_kelly_fraction < result.original_kelly_fraction
        # penalty = 0.90 * 0.5 = 0.45
        assert result.correlation_penalty == pytest.approx(0.45, abs=0.01)

    def test_low_correlation_no_penalty(self) -> None:
        kelly = self._base_kelly()
        result = adjust_kelly_for_correlation(
            kelly, "GLD", ["SPY"],
            lambda a, b: 0.30,  # Gold/SPY low correlation
        )
        assert result.correlation_penalty == 0.0
        assert result.adjusted_kelly_fraction == result.original_kelly_fraction

    def test_multiple_positions_uses_max_corr(self) -> None:
        kelly = self._base_kelly()
        corr_map = {("IWM", "SPY"): 0.85, ("IWM", "GLD"): 0.15}
        result = adjust_kelly_for_correlation(
            kelly, "IWM", ["SPY", "GLD"],
            lambda a, b: corr_map.get((a, b), corr_map.get((b, a), 0.0)),
        )
        # max_corr = 0.85, penalty = 0.85 * 0.5 = 0.425
        assert result.correlation_penalty == pytest.approx(0.425, abs=0.01)

    def test_self_ticker_skipped(self) -> None:
        kelly = self._base_kelly()
        result = adjust_kelly_for_correlation(
            kelly, "SPY", ["SPY"],
            lambda a, b: 1.0,
        )
        assert result.correlation_penalty == 0.0  # Self is skipped

    def test_effective_position_count(self) -> None:
        kelly = self._base_kelly()
        result = adjust_kelly_for_correlation(
            kelly, "QQQ", ["SPY"],
            lambda a, b: 0.80,  # penalty = 0.40
        )
        # effective = 1 / (1 - 0.40) = 1.667
        assert result.effective_position_count == pytest.approx(1.67, abs=0.05)


class TestRegimeAdjustedBP:
    def test_r1_standard_margin(self) -> None:
        result = compute_regime_adjusted_bp(5.0, regime_id=1)
        assert result.base_bp_per_contract == 500.0
        assert result.regime_multiplier == 1.0
        assert result.adjusted_bp_per_contract == 500.0

    def test_r2_expanded_margin(self) -> None:
        result = compute_regime_adjusted_bp(5.0, regime_id=2)
        assert result.regime_multiplier == 1.3
        assert result.adjusted_bp_per_contract == 650.0

    def test_r3_slight_expansion(self) -> None:
        result = compute_regime_adjusted_bp(5.0, regime_id=3)
        assert result.regime_multiplier == 1.1
        assert result.adjusted_bp_per_contract == 550.0

    def test_r4_maximum_expansion(self) -> None:
        result = compute_regime_adjusted_bp(5.0, regime_id=4)
        assert result.regime_multiplier == 1.5
        assert result.adjusted_bp_per_contract == 750.0

    def test_max_contracts_with_bp(self) -> None:
        result = compute_regime_adjusted_bp(5.0, regime_id=1, available_bp=5000.0)
        assert result.max_contracts_by_margin == 10  # 5000 / 500

    def test_max_contracts_r2_fewer(self) -> None:
        r1 = compute_regime_adjusted_bp(5.0, regime_id=1, available_bp=5000.0)
        r2 = compute_regime_adjusted_bp(5.0, regime_id=2, available_bp=5000.0)
        assert r2.max_contracts_by_margin < r1.max_contracts_by_margin

    def test_10_wide_wings(self) -> None:
        result = compute_regime_adjusted_bp(10.0, regime_id=1)
        assert result.base_bp_per_contract == 1000.0

    def test_no_available_bp(self) -> None:
        result = compute_regime_adjusted_bp(5.0, regime_id=1)
        assert result.max_contracts_by_margin == 0  # No BP provided

    def test_unknown_regime_standard(self) -> None:
        result = compute_regime_adjusted_bp(5.0, regime_id=99)
        assert result.regime_multiplier == 1.0


# ---------------------------------------------------------------------------
# Task 5: Unified Position Sizing
# ---------------------------------------------------------------------------

from market_analyzer.features.position_sizing import compute_position_size  # noqa: E402


class TestUnifiedPositionSize:
    def test_basic_sizing_without_correlation(self) -> None:
        result = compute_position_size(
            pop_pct=0.72, max_profit=180, max_loss=320,
            capital=50000, risk_per_contract=500, regime_id=1,
        )
        assert result.recommended_contracts >= 1
        assert result.recommended_contracts <= 10

    def test_r2_reduces_via_margin(self) -> None:
        r1 = compute_position_size(
            pop_pct=0.72, max_profit=180, max_loss=320,
            capital=50000, risk_per_contract=500, regime_id=1,
        )
        r2 = compute_position_size(
            pop_pct=0.72, max_profit=180, max_loss=320,
            capital=50000, risk_per_contract=500, regime_id=2,
        )
        assert r2.recommended_contracts <= r1.recommended_contracts

    def test_correlation_reduces_size(self) -> None:
        no_corr = compute_position_size(
            pop_pct=0.72, max_profit=180, max_loss=320,
            capital=50000, risk_per_contract=500, regime_id=1,
        )
        with_corr = compute_position_size(
            pop_pct=0.72, max_profit=180, max_loss=320,
            capital=50000, risk_per_contract=500, regime_id=1,
            new_ticker="QQQ", open_tickers=["SPY"],
            correlation_fn=lambda a, b: 0.90,
        )
        assert with_corr.recommended_contracts <= no_corr.recommended_contracts

    def test_negative_ev_zero_contracts(self) -> None:
        result = compute_position_size(
            pop_pct=0.30, max_profit=100, max_loss=400,
            capital=50000, risk_per_contract=500, regime_id=1,
        )
        assert result.recommended_contracts == 0

    def test_r4_most_restrictive(self) -> None:
        r1 = compute_position_size(
            pop_pct=0.72, max_profit=180, max_loss=320,
            capital=50000, risk_per_contract=500, regime_id=1,
        )
        r4 = compute_position_size(
            pop_pct=0.72, max_profit=180, max_loss=320,
            capital=50000, risk_per_contract=500, regime_id=4,
        )
        assert r4.recommended_contracts <= r1.recommended_contracts

    def test_components_include_regime_margin(self) -> None:
        result = compute_position_size(
            pop_pct=0.72, max_profit=180, max_loss=320,
            capital=50000, risk_per_contract=500, regime_id=2,
        )
        assert "regime_margin_cap" in result.components

    def test_with_exposure_and_correlation(self) -> None:
        exposure = PortfolioExposure(
            open_position_count=2, max_positions=5,
            current_risk_pct=0.10, max_risk_pct=0.25,
        )
        result = compute_position_size(
            pop_pct=0.72, max_profit=180, max_loss=320,
            capital=50000, risk_per_contract=500, regime_id=1,
            exposure=exposure,
            new_ticker="IWM", open_tickers=["SPY", "QQQ"],
            correlation_fn=lambda a, b: 0.80,
        )
        assert result.recommended_contracts >= 0
        assert "correlation_penalty" in result.components
