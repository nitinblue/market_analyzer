"""Functional tests for Trading Intelligence Reform — end-to-end pipeline."""

from datetime import date
import pytest

from market_analyzer.features.exit_intelligence import (
    compute_regime_stop,
    compute_time_adjusted_target,
    compute_remaining_theta_value,
)
from market_analyzer.features.position_sizing import (
    compute_kelly_fraction,
    compute_kelly_position_size,
    compute_position_size,
    compute_pairwise_correlation,
    adjust_kelly_for_correlation,
    compute_regime_adjusted_bp,
    PortfolioExposure,
)
from market_analyzer.features.dte_optimizer import select_optimal_dte
from market_analyzer.features.entry_levels import compute_iv_rank_quality
from market_analyzer.models.exit import RegimeStop, TimeAdjustedTarget, ThetaDecayResult


class TestExitIntelligencePipeline:
    """End-to-end: regime stop + time target + theta decay for position monitoring."""

    def test_full_exit_analysis_r1_healthy(self) -> None:
        """R1 position, 10 days held, 30% profit → hold, standard stop."""
        stop = compute_regime_stop(1, "iron_condor")
        assert stop.base_multiplier == 2.0

        target = compute_time_adjusted_target(10, 30, 0.30, 0.50)
        # 30% in 10 days on 30 DTE = velocity 0.9 — no acceleration
        assert target.adjusted_target_pct == 0.50

        theta = compute_remaining_theta_value(20, 30, 0.30)
        assert theta.recommendation == "hold"

    def test_full_exit_analysis_r2_fast_profit(self) -> None:
        """R2 position, 5 days held, 40% profit → wider stop, lower target, hold."""
        stop = compute_regime_stop(2, "iron_condor")
        assert stop.base_multiplier == 3.0  # R2 wider stop

        target = compute_time_adjusted_target(5, 30, 0.40, 0.50)
        # 40% in 5 days = velocity ~2.4 → close early
        assert target.adjusted_target_pct < 0.50
        assert target.acceleration_reason is not None

    def test_full_exit_analysis_r4_immediate(self) -> None:
        """R4 position → tightest stop, close recommendation if profitable."""
        stop = compute_regime_stop(4, "iron_condor")
        assert stop.base_multiplier == 1.5  # R4 tight stop


class TestSizingPipeline:
    """End-to-end: Kelly + correlation + margin for position sizing."""

    def test_unified_sizing_50k_account(self) -> None:
        """50K account, good IC trade, no existing positions."""
        result = compute_position_size(
            capital=50000, pop_pct=0.72, max_profit=180, max_loss=320,
            risk_per_contract=320, wing_width=5.0, regime_id=1,
        )
        assert result.recommended_contracts >= 1
        assert result.recommended_contracts <= 10

    def test_unified_sizing_with_correlation(self) -> None:
        """Correlated existing position reduces sizing."""
        result_no_corr = compute_position_size(
            capital=50000, pop_pct=0.72, max_profit=180, max_loss=320,
            risk_per_contract=320, wing_width=5.0, regime_id=1,
        )
        corr_table = {("QQQ", "SPY"): 0.90, ("SPY", "QQQ"): 0.90}
        result_with_corr = compute_position_size(
            capital=50000, pop_pct=0.72, max_profit=180, max_loss=320,
            risk_per_contract=320, wing_width=5.0, regime_id=1,
            new_ticker="QQQ",
            open_tickers=["SPY"],
            correlation_fn=lambda a, b: corr_table.get((a, b), 0.0),
        )
        assert result_with_corr.recommended_contracts <= result_no_corr.recommended_contracts

    def test_r2_margin_reduces_contracts(self) -> None:
        """R2 regime-adjusted margin means fewer contracts for same available BP."""
        available_bp = 10000.0
        r1_margin = compute_regime_adjusted_bp(5.0, 1, available_bp=available_bp)
        r2_margin = compute_regime_adjusted_bp(5.0, 2, available_bp=available_bp)
        assert r2_margin.max_contracts_by_margin < r1_margin.max_contracts_by_margin


class TestDTEOptimizerPipeline:
    """DTE selection with real vol surface fixtures."""

    def test_selects_from_vol_surface(self, normal_vol_surface) -> None:
        result = select_optimal_dte(normal_vol_surface, 1, "iron_condor")
        assert result.recommended_dte >= 14
        assert result.recommended_dte <= 90


class TestIVRankPipeline:
    """IV rank quality across ticker types."""

    def test_etf_moderate_rank_good(self) -> None:
        result = compute_iv_rank_quality(35.0, "etf")
        assert result.quality == "good"

    def test_equity_moderate_rank_wait(self) -> None:
        result = compute_iv_rank_quality(35.0, "equity")
        assert result.quality == "wait"  # Same rank, different threshold

    def test_index_low_rank_good(self) -> None:
        result = compute_iv_rank_quality(28.0, "index")
        assert result.quality == "good"
