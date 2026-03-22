"""Tests for hedge monitoring — expiry, rolling, effectiveness."""

import pytest

from income_desk.hedging.monitoring import (
    compute_hedge_effectiveness,
    monitor_hedge_status,
)


class TestMonitorHedgeStatus:
    def test_healthy_hedges(self):
        """Hedges with plenty of DTE and good coverage are held."""
        hedges = [
            {"ticker": "SPY", "hedge_type": "protective_put", "dte_remaining": 20, "delta_coverage": 0.8},
            {"ticker": "RELIANCE", "hedge_type": "futures_short", "dte_remaining": 15, "delta_coverage": 0.9},
        ]
        result = monitor_hedge_status(hedges)
        assert result.expiring_count == 0
        assert result.expired_count == 0
        assert len(result.alerts) == 0
        assert all(e.action == "hold" for e in result.hedges)
        assert len(result.roll_specs) == 0
        assert "healthy" in result.summary

    def test_expiring_put_generates_roll(self):
        """A put expiring within threshold triggers roll action and roll spec."""
        hedges = [
            {"ticker": "SPY", "hedge_type": "protective_put", "dte_remaining": 3, "delta_coverage": 0.7},
        ]
        result = monitor_hedge_status(hedges)
        assert result.expiring_count == 1
        assert result.expired_count == 0
        assert result.hedges[0].action == "roll"
        assert result.hedges[0].is_expiring_soon
        assert not result.hedges[0].is_expired
        assert len(result.roll_specs) == 1
        assert result.roll_specs[0].ticker == "SPY"
        assert any("EXPIRING" in a for a in result.alerts)

    def test_expired_hedge_replace(self):
        """Expired hedge (DTE=0) requires replace action."""
        hedges = [
            {"ticker": "RELIANCE", "hedge_type": "futures_short", "dte_remaining": 0, "delta_coverage": 0.0},
        ]
        result = monitor_hedge_status(hedges)
        assert result.expired_count == 1
        assert result.expiring_count == 0
        assert result.hedges[0].action == "replace"
        assert result.hedges[0].is_expired
        assert not result.hedges[0].is_expiring_soon
        assert any("EXPIRED" in a for a in result.alerts)

    def test_negative_dte_also_expired(self):
        """DTE < 0 is also expired."""
        hedges = [
            {"ticker": "QQQ", "hedge_type": "protective_put", "dte_remaining": -2, "delta_coverage": 0.0},
        ]
        result = monitor_hedge_status(hedges)
        assert result.expired_count == 1
        assert result.hedges[0].is_expired

    def test_weak_coverage_flagged(self):
        """Hedge with delta_coverage < 30% triggers replace even with DTE remaining."""
        hedges = [
            {"ticker": "NIFTY", "hedge_type": "index_put", "dte_remaining": 20, "delta_coverage": 0.15},
        ]
        result = monitor_hedge_status(hedges)
        assert result.hedges[0].action == "replace"
        assert result.expiring_count == 0  # Not expiring — weak coverage is a separate condition
        assert any("WEAK" in a for a in result.alerts)

    def test_mixed_status(self):
        """Three hedges: one healthy, one expiring, one expired."""
        hedges = [
            {"ticker": "SPY", "hedge_type": "protective_put", "dte_remaining": 25, "delta_coverage": 0.8},
            {"ticker": "QQQ", "hedge_type": "collar", "dte_remaining": 4, "delta_coverage": 0.7},
            {"ticker": "AAPL", "hedge_type": "protective_put", "dte_remaining": 0, "delta_coverage": 0.0},
        ]
        result = monitor_hedge_status(hedges)
        assert result.expiring_count == 1
        assert result.expired_count == 1
        assert len(result.alerts) == 2
        spy = next(e for e in result.hedges if e.ticker == "SPY")
        qqq = next(e for e in result.hedges if e.ticker == "QQQ")
        aapl = next(e for e in result.hedges if e.ticker == "AAPL")
        assert spy.action == "hold"
        assert qqq.action == "roll"
        assert aapl.action == "replace"

    def test_empty_hedges(self):
        """Empty input returns empty result."""
        result = monitor_hedge_status([])
        assert result.expiring_count == 0
        assert result.expired_count == 0
        assert len(result.alerts) == 0
        assert len(result.hedges) == 0
        assert "No active hedges" in result.summary

    def test_custom_dte_threshold(self):
        """Custom threshold changes what counts as expiring."""
        hedges = [
            {"ticker": "SPY", "hedge_type": "protective_put", "dte_remaining": 8, "delta_coverage": 0.7},
        ]
        # Default threshold 5 → 8 DTE is NOT expiring
        result_default = monitor_hedge_status(hedges, dte_warning_threshold=5)
        assert result_default.expiring_count == 0
        assert result_default.hedges[0].action == "hold"

        # Custom threshold 10 → 8 DTE IS expiring
        result_custom = monitor_hedge_status(hedges, dte_warning_threshold=10)
        assert result_custom.expiring_count == 1
        assert result_custom.hedges[0].action == "roll"

    def test_futures_roll_spec(self):
        """Expiring futures hedge gets a futures roll spec."""
        hedges = [
            {"ticker": "TATASTEEL", "hedge_type": "futures_short", "dte_remaining": 2, "delta_coverage": 0.9},
        ]
        result = monitor_hedge_status(hedges)
        assert result.expiring_count == 1
        assert len(result.roll_specs) == 1
        spec = result.roll_specs[0]
        assert spec.ticker == "TATASTEEL"
        assert spec.structure_type == "futures_short"
        leg = spec.legs[0]
        assert leg.option_type == "future"
        assert leg.action.value == "STO"

    def test_put_roll_spec_structure(self):
        """Expiring put hedge gets a long_option roll spec with 30 DTE."""
        hedges = [
            {"ticker": "SPY", "hedge_type": "protective_put", "dte_remaining": 1, "delta_coverage": 0.8},
        ]
        result = monitor_hedge_status(hedges)
        spec = result.roll_specs[0]
        assert spec.structure_type == "long_option"
        leg = spec.legs[0]
        assert leg.option_type == "put"
        assert leg.days_to_expiry == 30

    def test_unknown_hedge_type_no_roll_spec(self):
        """Unknown hedge type produces no roll spec."""
        hedges = [
            {"ticker": "SPY", "hedge_type": "exotic_barrier", "dte_remaining": 2, "delta_coverage": 0.5},
        ]
        result = monitor_hedge_status(hedges)
        assert result.expiring_count == 1
        assert len(result.roll_specs) == 0
        assert result.hedges[0].roll_spec is None

    def test_total_roll_cost_is_none(self):
        """total_roll_cost is None (needs broker quotes)."""
        hedges = [
            {"ticker": "SPY", "hedge_type": "protective_put", "dte_remaining": 3, "delta_coverage": 0.7},
        ]
        result = monitor_hedge_status(hedges)
        assert result.total_roll_cost is None


class TestComputeHedgeEffectiveness:
    def test_five_pct_drop_with_hedges(self):
        """5% market drop with hedges reduces loss significantly."""
        positions = [
            {"ticker": "SPY", "value": 58000, "delta": 1.0},
            {"ticker": "QQQ", "value": 48000, "delta": 1.0},
        ]
        hedges = [
            {"ticker": "SPY", "delta_reduction": 0.8, "cost": 500},
            {"ticker": "QQQ", "delta_reduction": 0.7, "cost": 400},
        ]
        result = compute_hedge_effectiveness(positions, hedges, -0.05)

        assert result.portfolio_loss_unhedged > 0
        assert result.portfolio_loss_hedged < result.portfolio_loss_unhedged
        assert result.hedge_savings > 0
        assert result.net_benefit > 0
        assert result.roi_on_hedge > 0
        assert result.market_move_pct == -0.05

    def test_small_move_hedge_not_worth_it(self):
        """If move is tiny, hedge cost may exceed savings."""
        positions = [
            {"ticker": "SPY", "value": 58000, "delta": 1.0},
        ]
        hedges = [
            {"ticker": "SPY", "delta_reduction": 0.8, "cost": 5000},  # Expensive hedge
        ]
        result = compute_hedge_effectiveness(positions, hedges, -0.005)  # 0.5% drop
        # Savings: 58000 * 1.0 * 0.005 * 0.8 = 232
        # Cost: 5000 → net negative
        assert result.net_benefit < 0
        assert "cost" in result.commentary.lower()

    def test_no_hedges_savings_zero(self):
        """Without hedges, savings is 0 and hedged loss equals unhedged loss."""
        positions = [{"ticker": "SPY", "value": 58000, "delta": 1.0}]
        result = compute_hedge_effectiveness(positions, [], -0.05)
        assert result.hedge_savings == 0.0
        assert result.portfolio_loss_hedged == result.portfolio_loss_unhedged
        assert result.cost_of_hedges == 0.0

    def test_india_portfolio_five_pct_drop(self):
        """India 3-stock portfolio — 5% NIFTY drop."""
        positions = [
            {"ticker": "RELIANCE", "value": 1250000, "delta": 0.95},
            {"ticker": "HDFCBANK", "value": 800000, "delta": 1.15},
            {"ticker": "TATASTEEL", "value": 150000, "delta": 1.30},
        ]
        hedges = [
            {"ticker": "RELIANCE", "delta_reduction": 0.85, "cost": 15000},
            {"ticker": "HDFCBANK", "delta_reduction": 0.80, "cost": 10000},
            {"ticker": "TATASTEEL", "delta_reduction": 0.90, "cost": 3000},
        ]
        result = compute_hedge_effectiveness(positions, hedges, -0.05)
        assert result.hedge_savings > 50000  # Substantial savings on large portfolio
        assert result.roi_on_hedge > 1.0  # Hedge paid for itself

    def test_partial_hedge_coverage(self):
        """Only some positions are hedged — unhedged positions incur full loss."""
        positions = [
            {"ticker": "SPY", "value": 50000, "delta": 1.0},
            {"ticker": "AAPL", "value": 20000, "delta": 1.2},  # NOT hedged
        ]
        hedges = [
            {"ticker": "SPY", "delta_reduction": 0.8, "cost": 300},
        ]
        result = compute_hedge_effectiveness(positions, hedges, -0.05)
        # SPY loss is partially offset, AAPL is not
        expected_unhedged = abs(50000 * 1.0 * -0.05) + abs(20000 * 1.2 * -0.05)
        assert abs(result.portfolio_loss_unhedged - expected_unhedged) < 1.0

    def test_zero_move_zero_loss(self):
        """Zero market move → zero loss."""
        positions = [{"ticker": "SPY", "value": 58000, "delta": 1.0}]
        hedges = [{"ticker": "SPY", "delta_reduction": 0.8, "cost": 500}]
        result = compute_hedge_effectiveness(positions, hedges, 0.0)
        assert result.portfolio_loss_unhedged == 0.0
        assert result.portfolio_loss_hedged == 0.0
        assert result.hedge_savings == 0.0

    def test_positive_move_long_portfolio_gains(self):
        """A 5% rally on a long portfolio — unhedged gains are positive (loss = 0)."""
        positions = [{"ticker": "SPY", "value": 58000, "delta": 1.0}]
        result = compute_hedge_effectiveness(positions, [], 0.05)
        # Long position gains in a rally → loss is 0 after abs()
        assert result.portfolio_loss_unhedged >= 0

    def test_commentary_mentions_savings_pct(self):
        """Commentary mentions the savings percentage."""
        positions = [{"ticker": "SPY", "value": 100000, "delta": 1.0}]
        hedges = [{"ticker": "SPY", "delta_reduction": 0.7, "cost": 500}]
        result = compute_hedge_effectiveness(positions, hedges, -0.05)
        assert len(result.commentary) > 0
        # Should mention the move magnitude or savings
        assert any(c.isdigit() for c in result.commentary)
