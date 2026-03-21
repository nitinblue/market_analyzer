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


# ---------------------------------------------------------------------------
# Task 9: AdjustmentOutcome + analyze_adjustment_effectiveness()
# ---------------------------------------------------------------------------


from datetime import date as dt_date  # noqa: E402
from market_analyzer.models.adjustment import AdjustmentOutcome, AdjustmentEffectiveness  # noqa: E402
from market_analyzer.features.position_sizing import analyze_adjustment_effectiveness  # noqa: E402


class TestAdjustmentEffectiveness:
    def _make_outcome(
        self, adj_type: str = "roll_away", cost: float = -50.0,
        pnl: float = 100.0, profitable: bool = True,
        regime: int = 1, status: str = "tested",
    ) -> AdjustmentOutcome:
        return AdjustmentOutcome(
            trade_id="test-1", adjustment_type=adj_type,
            adjustment_date=dt_date(2026, 3, 1), cost=cost,
            subsequent_pnl=pnl, was_profitable=profitable,
            regime_at_adjustment=regime, position_status_at_adjustment=status,
        )

    def test_empty_outcomes(self) -> None:
        result = analyze_adjustment_effectiveness([])
        assert result.total_outcomes == 0
        assert "No adjustment data" in result.recommendations[0]

    def test_single_type_win_rate(self) -> None:
        outcomes = [
            self._make_outcome(profitable=True),
            self._make_outcome(profitable=True),
            self._make_outcome(profitable=False),
        ]
        result = analyze_adjustment_effectiveness(outcomes)
        assert result.total_outcomes == 3
        assert result.by_type["roll_away"]["win_rate"] == pytest.approx(0.67, abs=0.01)
        assert result.by_type["roll_away"]["count"] == 3

    def test_multiple_types(self) -> None:
        outcomes = [
            self._make_outcome(adj_type="roll_away", profitable=True),
            self._make_outcome(adj_type="roll_away", profitable=True),
            self._make_outcome(adj_type="close_full", profitable=False),
        ]
        result = analyze_adjustment_effectiveness(outcomes)
        assert "roll_away" in result.by_type
        assert "close_full" in result.by_type

    def test_regime_grouping(self) -> None:
        outcomes = [
            self._make_outcome(regime=1, profitable=True),
            self._make_outcome(regime=2, profitable=False),
            self._make_outcome(regime=2, profitable=True),
        ]
        result = analyze_adjustment_effectiveness(outcomes)
        assert 1 in result.by_regime
        assert 2 in result.by_regime

    def test_recommendations_generated(self) -> None:
        outcomes = [
            self._make_outcome(adj_type="roll_away", profitable=True),
            self._make_outcome(adj_type="roll_away", profitable=True),
            self._make_outcome(adj_type="roll_away", profitable=True),
        ]
        result = analyze_adjustment_effectiveness(outcomes)
        assert any("ROLL_AWAY" in r for r in result.recommendations)

    def test_avoid_recommendation_low_win_rate(self) -> None:
        outcomes = [
            self._make_outcome(adj_type="roll_out", profitable=False),
            self._make_outcome(adj_type="roll_out", profitable=False),
            self._make_outcome(adj_type="roll_out", profitable=True),
        ]
        result = analyze_adjustment_effectiveness(outcomes)
        assert any("Avoid" in r and "ROLL_OUT" in r for r in result.recommendations)

    def test_avg_cost_calculation(self) -> None:
        outcomes = [
            self._make_outcome(cost=-100.0),
            self._make_outcome(cost=-50.0),
            self._make_outcome(cost=0.0),
        ]
        result = analyze_adjustment_effectiveness(outcomes)
        assert result.by_type["roll_away"]["avg_cost"] == pytest.approx(-50.0, abs=0.01)

    def test_serialization(self) -> None:
        outcomes = [self._make_outcome()]
        result = analyze_adjustment_effectiveness(outcomes)
        d = result.model_dump()
        assert "by_type" in d
        assert "recommendations" in d


# ---------------------------------------------------------------------------
# MarginAnalysis tests
# ---------------------------------------------------------------------------

from datetime import date, timedelta

from market_analyzer.features.position_sizing import MarginAnalysis, compute_margin_analysis
from market_analyzer.models.opportunity import LegAction, LegSpec, OrderSide, StructureType, TradeSpec


def _make_ic_trade_spec(
    ticker: str = "SPY",
    short_put: float = 570.0,
    short_call: float = 590.0,
    wing: float = 5.0,
    price: float = 580.0,
    dte: int = 30,
) -> TradeSpec:
    exp = date.today() + timedelta(days=dte)
    legs = [
        LegSpec(role="short_put", action=LegAction.SELL_TO_OPEN, option_type="put",
                strike=short_put, strike_label=f"STO {short_put:.0f}P",
                expiration=exp, days_to_expiry=dte, atm_iv_at_expiry=0.0),
        LegSpec(role="long_put", action=LegAction.BUY_TO_OPEN, option_type="put",
                strike=short_put - wing, strike_label=f"BTO {short_put - wing:.0f}P",
                expiration=exp, days_to_expiry=dte, atm_iv_at_expiry=0.0),
        LegSpec(role="short_call", action=LegAction.SELL_TO_OPEN, option_type="call",
                strike=short_call, strike_label=f"STO {short_call:.0f}C",
                expiration=exp, days_to_expiry=dte, atm_iv_at_expiry=0.0),
        LegSpec(role="long_call", action=LegAction.BUY_TO_OPEN, option_type="call",
                strike=short_call + wing, strike_label=f"BTO {short_call + wing:.0f}C",
                expiration=exp, days_to_expiry=dte, atm_iv_at_expiry=0.0),
    ]
    return TradeSpec(
        ticker=ticker,
        legs=legs,
        underlying_price=price,
        target_dte=dte,
        target_expiration=exp,
        wing_width_points=wing,
        structure_type=StructureType.IRON_CONDOR,
        order_side=OrderSide.CREDIT,
        spec_rationale="Test IC",
    )


def _make_equity_spec(
    ticker: str = "AAPL",
    price: float = 200.0,
    lot_size: int = 100,
) -> TradeSpec:
    exp = date.today() + timedelta(days=1)
    return TradeSpec(
        ticker=ticker,
        legs=[LegSpec(role="equity_buy", action=LegAction.BUY_TO_OPEN, option_type="equity",
                      strike=0, strike_label="Buy shares", expiration=exp, days_to_expiry=1,
                      atm_iv_at_expiry=0.0)],
        underlying_price=price,
        target_dte=1,
        target_expiration=exp,
        structure_type=StructureType.EQUITY_LONG,
        order_side=OrderSide.DEBIT,
        lot_size=lot_size,
        spec_rationale="Test equity",
    )


class TestMarginAnalysis:
    def test_defined_risk_ic_cash_equals_wing_times_lot(self):
        """5-wide IC: cash_required = 5 * 100 = $500."""
        ts = _make_ic_trade_spec(wing=5.0)
        result = compute_margin_analysis(ts, account_nlv=50000, available_bp=30000, regime_id=1)
        assert result.cash_required == pytest.approx(500.0, abs=0.01)

    def test_defined_risk_ic_margin_equals_cash(self):
        """5-wide IC: margin_required == cash_required (defined risk, no margin benefit)."""
        ts = _make_ic_trade_spec(wing=5.0)
        result = compute_margin_analysis(ts, account_nlv=50000, available_bp=30000, regime_id=1)
        assert result.margin_required == pytest.approx(result.cash_required, abs=0.01)

    def test_ic_bp_after_trade_reduces_by_bp_reduction(self):
        """bp_after_trade = available_bp - buying_power_reduction."""
        ts = _make_ic_trade_spec(wing=5.0)
        avail = 30000.0
        result = compute_margin_analysis(ts, account_nlv=50000, available_bp=avail, regime_id=1)
        assert result.bp_after_trade == pytest.approx(
            avail - result.buying_power_reduction, abs=0.01,
        )

    def test_regime_2_multiplier_is_1_3(self):
        """R2 regime: margin multiplier should be 1.3."""
        ts = _make_ic_trade_spec(wing=5.0)
        result = compute_margin_analysis(ts, account_nlv=50000, available_bp=30000, regime_id=2)
        assert result.regime_margin_multiplier == pytest.approx(1.3, abs=0.01)

    def test_regime_4_multiplier_is_1_5(self):
        """R4 regime: margin multiplier should be 1.5."""
        ts = _make_ic_trade_spec(wing=5.0)
        result = compute_margin_analysis(ts, account_nlv=50000, available_bp=30000, regime_id=4)
        assert result.regime_margin_multiplier == pytest.approx(1.5, abs=0.01)

    def test_regime_2_higher_bp_than_regime_1(self):
        """R2 BP needed > R1 BP needed."""
        ts = _make_ic_trade_spec(wing=5.0)
        r1 = compute_margin_analysis(ts, account_nlv=50000, available_bp=30000, regime_id=1)
        r2 = compute_margin_analysis(ts, account_nlv=50000, available_bp=30000, regime_id=2)
        assert r2.buying_power_reduction >= r1.buying_power_reduction

    def test_r4_higher_bp_than_r1(self):
        """R4 BP needed > R1 BP needed."""
        ts = _make_ic_trade_spec(wing=5.0)
        r1 = compute_margin_analysis(ts, account_nlv=50000, available_bp=30000, regime_id=1)
        r4 = compute_margin_analysis(ts, account_nlv=50000, available_bp=30000, regime_id=4)
        assert r4.buying_power_reduction >= r1.buying_power_reduction

    def test_equity_cash_required_is_full_cost(self):
        """100 shares at $200: cash_required = $20,000."""
        ts = _make_equity_spec(price=200.0, lot_size=100)
        result = compute_margin_analysis(ts, account_nlv=50000, available_bp=30000, regime_id=1)
        assert result.cash_required == pytest.approx(20000.0, abs=1.0)

    def test_equity_margin_benefit(self):
        """100 shares at $200: margin_required = 25% of $20,000 = $5,000."""
        ts = _make_equity_spec(price=200.0, lot_size=100)
        result = compute_margin_analysis(ts, account_nlv=50000, available_bp=30000,
                                         regime_id=1, maintenance_pct=0.25)
        assert result.margin_required == pytest.approx(5000.0, abs=1.0)

    def test_equity_margin_less_than_cash(self):
        """Equity: margin_required < cash_required."""
        ts = _make_equity_spec(price=200.0, lot_size=100)
        result = compute_margin_analysis(ts, account_nlv=50000, available_bp=30000, regime_id=1)
        assert result.margin_required < result.cash_required

    def test_margin_cushion_between_0_and_1(self):
        """margin_cushion_pct should be in [0, 1]."""
        ts = _make_ic_trade_spec(wing=5.0)
        result = compute_margin_analysis(ts, account_nlv=50000, available_bp=30000, regime_id=1)
        assert 0.0 <= result.margin_cushion_pct <= 1.0

    def test_bp_utilization_between_0_and_1(self):
        """bp_utilization_pct should be in [0, 1]."""
        ts = _make_ic_trade_spec(wing=5.0)
        result = compute_margin_analysis(ts, account_nlv=50000, available_bp=30000, regime_id=1)
        assert 0.0 <= result.bp_utilization_pct <= 1.0

    def test_ticker_in_result(self):
        """Result ticker should match trade_spec ticker."""
        ts = _make_ic_trade_spec(ticker="GLD")
        result = compute_margin_analysis(ts, account_nlv=50000, available_bp=30000, regime_id=1)
        assert result.ticker == "GLD"

    def test_summary_is_string(self):
        """Summary should be a non-empty string."""
        ts = _make_ic_trade_spec(wing=5.0)
        result = compute_margin_analysis(ts, account_nlv=50000, available_bp=30000, regime_id=1)
        assert isinstance(result.summary, str)
        assert len(result.summary) > 0

    def test_regime_adjusted_bp_field(self):
        """regime_adjusted_bp should be present and positive."""
        ts = _make_ic_trade_spec(wing=5.0)
        result = compute_margin_analysis(ts, account_nlv=50000, available_bp=30000, regime_id=2)
        assert result.regime_adjusted_bp > 0

    def test_wider_wing_higher_bp(self):
        """10-wide IC requires more BP than 5-wide."""
        ts5 = _make_ic_trade_spec(wing=5.0)
        ts10 = _make_ic_trade_spec(wing=10.0)
        r5 = compute_margin_analysis(ts5, account_nlv=50000, available_bp=30000, regime_id=1)
        r10 = compute_margin_analysis(ts10, account_nlv=50000, available_bp=30000, regime_id=1)
        assert r10.buying_power_reduction > r5.buying_power_reduction
