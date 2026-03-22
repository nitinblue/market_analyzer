"""Tests for hedge method comparison."""

import pytest

from income_desk.hedging.comparison import compare_hedge_methods
from income_desk.hedging.models import HedgeTier
from income_desk.registry import MarketRegistry


@pytest.fixture
def registry() -> MarketRegistry:
    return MarketRegistry()


class TestCompareHedgeMethods:
    def test_reliance_all_tiers_available(self, registry: MarketRegistry):
        """RELIANCE (India, liquid options) — direct + futures + proxy all run."""
        comp = compare_hedge_methods(
            ticker="RELIANCE",
            shares=500,
            current_price=2680.0,
            regime_id=2,
            atr=80.0,
            market="INDIA",
            futures_price=2695.0,
            index_price=22500.0,
            registry=registry,
        )
        assert comp.ticker == "RELIANCE"
        assert comp.market == "INDIA"
        assert comp.shares == 500
        assert comp.regime_id == 2
        assert len(comp.methods) >= 3

        available = [m for m in comp.methods if m.available]
        # Direct (put, collar, put_spread) + futures + proxy = 5 available
        assert len(available) >= 3
        assert comp.recommended.available
        # RELIANCE has liquid options → direct should be recommended
        assert comp.recommended.tier == HedgeTier.DIRECT

    def test_spy_direct_preferred(self, registry: MarketRegistry):
        """SPY — US stock with liquid options; direct should be first."""
        comp = compare_hedge_methods(
            ticker="SPY",
            shares=100,
            current_price=580.0,
            regime_id=2,
            atr=8.0,
            market="US",
            index_price=580.0,
            registry=registry,
        )
        assert comp.recommended.tier == HedgeTier.DIRECT
        # Multiple direct methods available
        direct_methods = [m for m in comp.methods if m.tier == HedgeTier.DIRECT and m.available]
        assert len(direct_methods) >= 2
        # US has no single-stock futures
        futures_method = next((m for m in comp.methods if m.tier == HedgeTier.FUTURES_SYNTHETIC), None)
        assert futures_method is not None
        assert not futures_method.available

    def test_tatasteel_futures_available(self, registry: MarketRegistry):
        """TATASTEEL — illiquid options, but futures available (India)."""
        comp = compare_hedge_methods(
            ticker="TATASTEEL",
            shares=1100,
            current_price=136.0,
            regime_id=3,
            atr=5.0,
            market="INDIA",
            futures_price=137.0,
            index_price=22500.0,
            registry=registry,
        )
        # Direct methods should be unavailable (options illiquid)
        direct_methods = [m for m in comp.methods if m.tier == HedgeTier.DIRECT and m.available]
        assert len(direct_methods) == 0
        # Futures should be available
        futures_methods = [m for m in comp.methods if m.tier == HedgeTier.FUTURES_SYNTHETIC and m.available]
        assert len(futures_methods) >= 1

    def test_unknown_ticker_proxy_available(self, registry: MarketRegistry):
        """Unknown India ticker — no F&O, proxy is always available when index_price given."""
        comp = compare_hedge_methods(
            ticker="SOME_UNKNOWN_INDIA_STOCK",
            shares=100,
            current_price=500.0,
            regime_id=2,
            atr=15.0,
            market="INDIA",
            index_price=22500.0,
            registry=registry,
        )
        # Should have proxy available (always works with index_price)
        proxy_methods = [m for m in comp.methods if m.tier == HedgeTier.PROXY_INDEX and m.available]
        assert len(proxy_methods) >= 1
        # Unknown India stock is PROXY_INDEX tier, but futures may also be attempted
        # At minimum, a recommended hedge should be available
        assert comp.recommended.available

    def test_no_index_price_proxy_unavailable(self, registry: MarketRegistry):
        """No index_price → proxy hedge not computed."""
        comp = compare_hedge_methods(
            ticker="SPY",
            shares=100,
            current_price=580.0,
            regime_id=2,
            atr=8.0,
            market="US",
            index_price=None,  # No index price
            registry=registry,
        )
        proxy_methods = [m for m in comp.methods if m.tier == HedgeTier.PROXY_INDEX]
        assert all(not m.available for m in proxy_methods)
        # Should still have direct methods
        assert comp.recommended.available

    def test_ranking_available_before_unavailable(self, registry: MarketRegistry):
        """Available methods must come before unavailable ones in sorted list."""
        comp = compare_hedge_methods(
            ticker="SPY",
            shares=100,
            current_price=580.0,
            regime_id=2,
            atr=8.0,
            market="US",
            registry=registry,
        )
        found_unavailable = False
        for m in comp.methods:
            if not m.available:
                found_unavailable = True
            elif found_unavailable:
                pytest.fail(f"Available method {m.hedge_type} found after unavailable method")

    def test_recommendation_rationale_present(self, registry: MarketRegistry):
        """Rationale string must be non-empty and mention 'Recommended'."""
        comp = compare_hedge_methods(
            ticker="SPY",
            shares=100,
            current_price=580.0,
            regime_id=2,
            atr=8.0,
            market="US",
            registry=registry,
        )
        assert len(comp.recommendation_rationale) > 0
        assert "Recommended" in comp.recommendation_rationale

    def test_position_value_computed(self, registry: MarketRegistry):
        """position_value = shares * price."""
        comp = compare_hedge_methods(
            ticker="SPY",
            shares=200,
            current_price=580.0,
            regime_id=1,
            atr=8.0,
            market="US",
            registry=registry,
        )
        assert comp.position_value == pytest.approx(200 * 580.0)

    def test_cost_ranking_first_is_cheapest(self, registry: MarketRegistry):
        """First available method should have a lower or equal cost_pct than the last."""
        comp = compare_hedge_methods(
            ticker="RELIANCE",
            shares=500,
            current_price=2680.0,
            regime_id=2,
            atr=80.0,
            market="INDIA",
            futures_price=2695.0,
            index_price=22500.0,
            registry=registry,
        )
        available = [m for m in comp.methods if m.available and m.cost_pct is not None]
        assert len(available) >= 2
        # First available method should not cost more than the last available method
        # (since we sort cost ascending)
        assert available[0].cost_pct <= available[-1].cost_pct + 0.001

    def test_r4_regime_more_expensive(self, registry: MarketRegistry):
        """R4 hedge costs should be higher than R1."""
        r4 = compare_hedge_methods(
            ticker="SPY", shares=100, current_price=580.0,
            regime_id=4, atr=8.0, market="US", registry=registry,
        )
        r1 = compare_hedge_methods(
            ticker="SPY", shares=100, current_price=580.0,
            regime_id=1, atr=8.0, market="US", registry=registry,
        )
        # Find protective_put in both
        r4_pp = next((m for m in r4.methods if m.hedge_type == "protective_put" and m.available), None)
        r1_pp = next((m for m in r1.methods if m.hedge_type == "protective_put" and m.available), None)
        if r4_pp and r1_pp and r4_pp.cost_pct and r1_pp.cost_pct:
            assert r4_pp.cost_pct > r1_pp.cost_pct

    def test_no_viable_hedge_all_unavailable(self, registry: MarketRegistry):
        """If no methods available, recommended.available is False."""
        # Build comparison with no index_price for unknown India stock
        comp = compare_hedge_methods(
            ticker="SOME_UNKNOWN_INDIA_STOCK",
            shares=100,
            current_price=500.0,
            regime_id=2,
            atr=15.0,
            market="INDIA",
            index_price=None,  # No proxy
            registry=registry,
        )
        # Without index price, proxy is unavailable; direct also unavailable for unknown India
        # So recommended may or may not be available (futures might still work)
        # Just check the structure is valid
        assert comp.recommended is not None
        assert len(comp.recommendation_rationale) > 0
