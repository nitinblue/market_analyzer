"""Tests for hedge strategy resolver."""

import pytest

from income_desk.hedging.models import HedgeGoal, HedgeTier
from income_desk.hedging.resolver import resolve_hedge_strategy
from income_desk.registry import MarketRegistry


@pytest.fixture
def registry() -> MarketRegistry:
    return MarketRegistry()


class TestResolverIndiaStocks:
    def test_reliance_direct(self, registry: MarketRegistry):
        """RELIANCE (medium liq) → DIRECT."""
        approach = resolve_hedge_strategy(
            ticker="RELIANCE",
            position_value=1250000,
            shares=500,
            current_price=2500,
            regime_id=2,
            market="INDIA",
            account_nlv=5000000,
            registry=registry,
        )
        assert approach.recommended_tier == HedgeTier.DIRECT
        assert approach.has_liquid_options
        assert approach.lot_size == 250
        assert "options" in approach.rationale.lower()

    def test_tatasteel_futures(self, registry: MarketRegistry):
        """TATASTEEL (low liq) → FUTURES_SYNTHETIC."""
        approach = resolve_hedge_strategy(
            ticker="TATASTEEL",
            position_value=150000,
            shares=1100,
            current_price=136,
            regime_id=3,
            market="INDIA",
            account_nlv=5000000,
            registry=registry,
        )
        assert approach.recommended_tier == HedgeTier.FUTURES_SYNTHETIC
        assert approach.basis_risk == "low"
        assert "illiquid" in approach.rationale.lower() or "futures" in approach.rationale.lower()

    def test_dmart_proxy(self, registry: MarketRegistry):
        """DMart not in F&O → PROXY_INDEX."""
        approach = resolve_hedge_strategy(
            ticker="DMART",
            position_value=500000,
            shares=125,
            current_price=4000,
            regime_id=2,
            market="INDIA",
            account_nlv=5000000,
            registry=registry,
        )
        assert approach.recommended_tier == HedgeTier.PROXY_INDEX
        assert approach.basis_risk == "high"
        assert "NIFTY" in approach.rationale

    def test_nestleind_lot_size_check(self, registry: MarketRegistry):
        """NESTLEIND lot=50, strike=100, high price ~2500 — check affordability."""
        approach = resolve_hedge_strategy(
            ticker="NESTLEIND",
            position_value=125000,
            shares=50,
            current_price=2500,
            regime_id=1,
            market="INDIA",
            account_nlv=500000,  # Small account
            registry=registry,
        )
        # Lot value = 50 x 2500 = 125000, which is 25% of 500K → over 20% threshold
        # But NESTLEIND has low options → FUTURES_SYNTHETIC anyway
        assert approach.recommended_tier in (HedgeTier.FUTURES_SYNTHETIC, HedgeTier.DIRECT)


class TestResolverUSStocks:
    def test_spy_direct(self, registry: MarketRegistry):
        """SPY (high liq) → DIRECT."""
        approach = resolve_hedge_strategy(
            ticker="SPY",
            position_value=58000,
            shares=100,
            current_price=580,
            regime_id=2,
            market="US",
            account_nlv=200000,
            registry=registry,
        )
        assert approach.recommended_tier == HedgeTier.DIRECT
        assert approach.lot_size == 100
        assert len(approach.alternatives) >= 1  # At least proxy alternative

    def test_unknown_us_stock_direct(self, registry: MarketRegistry):
        """Unknown US stock defaults to DIRECT."""
        approach = resolve_hedge_strategy(
            ticker="SOME_MICRO_CAP",
            position_value=5000,
            shares=100,
            current_price=50,
            regime_id=1,
            market="US",
            registry=registry,
        )
        assert approach.recommended_tier == HedgeTier.DIRECT


class TestResolverRegimeContext:
    def test_r1_context(self, registry: MarketRegistry):
        approach = resolve_hedge_strategy(
            ticker="SPY", position_value=58000, shares=100,
            current_price=580, regime_id=1, market="US", registry=registry,
        )
        assert "R1" in approach.rationale
        assert "optional" in approach.rationale.lower() or "cheap" in approach.rationale.lower()

    def test_r4_context(self, registry: MarketRegistry):
        approach = resolve_hedge_strategy(
            ticker="SPY", position_value=58000, shares=100,
            current_price=580, regime_id=4, market="US", registry=registry,
        )
        assert "R4" in approach.rationale
        assert "immediately" in approach.rationale.lower() or "capital" in approach.rationale.lower()

    def test_goal_is_downside(self, registry: MarketRegistry):
        approach = resolve_hedge_strategy(
            ticker="SPY", position_value=58000, shares=100,
            current_price=580, regime_id=2, market="US", registry=registry,
        )
        assert approach.goal == HedgeGoal.DOWNSIDE


class TestResolverAlternatives:
    def test_direct_has_proxy_alternative(self, registry: MarketRegistry):
        approach = resolve_hedge_strategy(
            ticker="SPY", position_value=58000, shares=100,
            current_price=580, regime_id=2, market="US", registry=registry,
        )
        alt_tiers = [a.tier for a in approach.alternatives]
        assert HedgeTier.PROXY_INDEX in alt_tiers

    def test_proxy_has_no_alternatives(self, registry: MarketRegistry):
        approach = resolve_hedge_strategy(
            ticker="DMART", position_value=500000, shares=125,
            current_price=4000, regime_id=2, market="INDIA", registry=registry,
        )
        # Proxy is last resort — no better alternatives
        assert len(approach.alternatives) == 0
