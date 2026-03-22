"""Tests for portfolio-level hedge orchestrator."""

import pytest

from income_desk.hedging.models import HedgeTier
from income_desk.hedging.portfolio import analyze_portfolio_hedge
from income_desk.registry import MarketRegistry


@pytest.fixture
def registry() -> MarketRegistry:
    return MarketRegistry()


def _pos(ticker: str, value: float, shares: int, price: float, delta: float = 1.0) -> dict:
    """Helper: build a position dict."""
    return {
        "ticker": ticker,
        "shares": shares,
        "value": value,
        "current_price": price,
        "delta": delta,
    }


class TestPortfolioHedgeOrchestrator:
    def test_india_mixed_portfolio(self, registry: MarketRegistry):
        """3-stock India portfolio: RELIANCE (T1), TATASTEEL (T2), DMART (T3).

        RELIANCE has lot_size=250, so at price 2500 lot_value=625000. With a
        large account_nlv (>= 3125000), it stays DIRECT; with smaller account it
        downgrades to FUTURES. Use large NLV to get DIRECT tier.
        """
        positions = [
            _pos("RELIANCE", 625000, 250, 2500),   # Tier 1 direct (with large account)
            _pos("TATASTEEL", 149600, 1100, 136),   # Tier 2 futures
            _pos("DMART", 420000, 100, 4200),        # Tier 3 proxy (not in F&O)
        ]
        result = analyze_portfolio_hedge(
            positions=positions,
            account_nlv=10000000,  # Large NLV ensures RELIANCE stays DIRECT
            regime=2,
            target_hedge_pct=1.0,  # Hedge all positions
            max_cost_pct=3.0,
            market="INDIA",
            atr_by_ticker={"RELIANCE": 75.0, "TATASTEEL": 5.0, "DMART": 120.0},
            index_price=22500.0,
            registry=registry,
        )
        assert result.total_positions == 3
        assert result.total_position_value > 0
        assert len(result.position_hedges) == 3
        # All 3 positions should be hedged
        assert len(result.trade_specs) >= 2
        # RELIANCE should be direct (lot_value=625000 < 20% of 10M = 2M)
        reliance = next(ph for ph in result.position_hedges if ph.ticker == "RELIANCE")
        assert reliance.tier == HedgeTier.DIRECT
        # TATASTEEL should be futures (low options liquidity in India)
        tatasteel = next(ph for ph in result.position_hedges if ph.ticker == "TATASTEEL")
        assert tatasteel.tier == HedgeTier.FUTURES_SYNTHETIC

    def test_us_portfolio_all_direct(self, registry: MarketRegistry):
        """US portfolio — SPY and QQQ both get direct hedges."""
        positions = [
            _pos("SPY", 58000, 100, 580),
            _pos("QQQ", 48000, 100, 480),
        ]
        result = analyze_portfolio_hedge(
            positions=positions,
            account_nlv=200000,
            regime=2,
            market="US",
            atr_by_ticker={"SPY": 8.0, "QQQ": 5.0},
            registry=registry,
        )
        assert result.total_positions == 2
        assert result.tier_counts.get("direct", 0) >= 2
        assert len(result.trade_specs) >= 2
        # Both should have direct hedges
        for ph in result.position_hedges:
            assert ph.tier == HedgeTier.DIRECT

    def test_empty_portfolio(self, registry: MarketRegistry):
        """Empty portfolio returns zeros."""
        result = analyze_portfolio_hedge(
            positions=[],
            account_nlv=200000,
            regime=2,
            market="US",
            registry=registry,
        )
        assert result.total_positions == 0
        assert result.total_position_value == 0.0
        assert result.coverage_pct == 0.0
        assert len(result.trade_specs) == 0
        assert len(result.position_hedges) == 0

    def test_target_hedge_pct_limits_hedges(self, registry: MarketRegistry):
        """With 50% target, larger position is hedged, smaller may be skipped."""
        positions = [
            _pos("SPY", 100000, 172, 580),   # Larger — hedged first
            _pos("QQQ", 100000, 208, 480),   # Same size
        ]
        result = analyze_portfolio_hedge(
            positions=positions,
            account_nlv=200000,
            regime=2,
            target_hedge_pct=0.50,
            market="US",
            atr_by_ticker={"SPY": 8.0, "QQQ": 5.0},
            registry=registry,
        )
        assert result.target_hedge_pct == 50.0
        # Coverage should be around 50%
        assert result.coverage_pct <= 60.0  # Not more than ~60%

    def test_delta_reduction_tracked(self, registry: MarketRegistry):
        """Portfolio delta should decrease after applying hedges."""
        positions = [_pos("SPY", 58000, 100, 580, delta=0.8)]
        result = analyze_portfolio_hedge(
            positions=positions,
            account_nlv=200000,
            regime=2,
            market="US",
            atr_by_ticker={"SPY": 8.0},
            registry=registry,
        )
        # After hedging, portfolio delta should be reduced
        assert result.portfolio_delta_after < result.portfolio_delta_before

    def test_cost_budget_alert(self, registry: MarketRegistry):
        """When cost exceeds budget, alert is added."""
        positions = [
            _pos("SPY", 58000, 100, 580),
            _pos("QQQ", 48000, 100, 480),
        ]
        result = analyze_portfolio_hedge(
            positions=positions,
            account_nlv=200000,
            regime=4,  # R4 = expensive hedges
            max_cost_pct=0.1,  # Very tight budget
            market="US",
            atr_by_ticker={"SPY": 8.0, "QQQ": 5.0},
            registry=registry,
        )
        # With R4 (expensive) and 0.1% budget, we expect a cost alert
        assert any("cost" in a.lower() for a in result.alerts)

    def test_per_ticker_regime(self, registry: MarketRegistry):
        """Different regime per ticker is respected."""
        positions = [
            _pos("SPY", 58000, 100, 580),
            _pos("QQQ", 48000, 100, 480),
        ]
        result = analyze_portfolio_hedge(
            positions=positions,
            account_nlv=200000,
            regime={"SPY": 4, "QQQ": 1},  # Dict regime
            market="US",
            atr_by_ticker={"SPY": 8.0, "QQQ": 5.0},
            registry=registry,
        )
        assert result.total_positions == 2
        # SPY in R4 should have higher cost than QQQ in R1
        spy = next(ph for ph in result.position_hedges if ph.ticker == "SPY")
        qqq = next(ph for ph in result.position_hedges if ph.ticker == "QQQ")
        if spy.cost_estimate and qqq.cost_estimate:
            # Normalize by value to compare cost_pct
            spy_cost_pct = spy.cost_estimate / spy.position_value
            qqq_cost_pct = qqq.cost_estimate / qqq.position_value
            assert spy_cost_pct > qqq_cost_pct

    def test_position_value_computed_from_price(self, registry: MarketRegistry):
        """Shares inferred from value/price when shares=0."""
        positions = [{"ticker": "SPY", "shares": 0, "value": 58000.0, "current_price": 580.0}]
        result = analyze_portfolio_hedge(
            positions=positions,
            account_nlv=200000,
            regime=2,
            market="US",
            atr_by_ticker={"SPY": 8.0},
            registry=registry,
        )
        # Should still build a hedge even with shares=0
        assert len(result.position_hedges) == 1

    def test_no_price_skips_position(self, registry: MarketRegistry):
        """Position with price=0 is skipped with rationale."""
        positions = [
            _pos("SPY", 58000, 100, 580),
            {"ticker": "UNKNOWN", "shares": 100, "value": 10000, "current_price": 0},
        ]
        result = analyze_portfolio_hedge(
            positions=positions,
            account_nlv=200000,
            regime=2,
            market="US",
            atr_by_ticker={"SPY": 8.0},
            registry=registry,
        )
        assert result.total_positions == 2
        # UNKNOWN position should be skipped
        unknown = next(ph for ph in result.position_hedges if ph.ticker == "UNKNOWN")
        assert unknown.tier == HedgeTier.NONE
        assert unknown.trade_spec is None

    def test_proxy_needs_index_price(self, registry: MarketRegistry):
        """DMART (proxy-only India stock) requires index_price for hedge."""
        positions = [_pos("DMART", 420000, 100, 4200)]
        result_no_index = analyze_portfolio_hedge(
            positions=positions,
            account_nlv=2000000,
            regime=2,
            market="INDIA",
            index_price=None,  # No index price
            registry=registry,
        )
        result_with_index = analyze_portfolio_hedge(
            positions=positions,
            account_nlv=2000000,
            regime=2,
            market="INDIA",
            index_price=22500.0,
            registry=registry,
        )
        # Without index, proxy hedge can't be built
        assert len(result_no_index.trade_specs) == 0
        # With index, proxy hedge is built
        assert len(result_with_index.trade_specs) == 1

    def test_summary_string_format(self, registry: MarketRegistry):
        """Summary string contains key metrics."""
        positions = [_pos("SPY", 58000, 100, 580)]
        result = analyze_portfolio_hedge(
            positions=positions,
            account_nlv=200000,
            regime=2,
            market="US",
            atr_by_ticker={"SPY": 8.0},
            registry=registry,
        )
        assert "hedge" in result.summary.lower()
        assert "coverage" in result.summary.lower() or "%" in result.summary

    def test_tier_breakdown_tracked(self, registry: MarketRegistry):
        """Tier counts and values are tracked correctly."""
        positions = [
            _pos("SPY", 58000, 100, 580),   # Direct
            _pos("QQQ", 48000, 100, 480),   # Direct
        ]
        result = analyze_portfolio_hedge(
            positions=positions,
            account_nlv=200000,
            regime=2,
            market="US",
            atr_by_ticker={"SPY": 8.0, "QQQ": 5.0},
            registry=registry,
        )
        assert result.tier_counts["direct"] == 2
        assert result.tier_values["direct"] > 0
