"""Tests for Tier 2 futures hedging + synthetics."""

import pytest

from income_desk.hedging.futures_hedge import (
    build_futures_hedge,
    build_synthetic_collar,
    build_synthetic_put,
    compute_hedge_ratio,
)
from income_desk.hedging.models import HedgeTier
from income_desk.models.opportunity import LegAction, StructureType
from income_desk.registry import MarketRegistry


@pytest.fixture
def registry() -> MarketRegistry:
    return MarketRegistry()


class TestComputeHedgeRatio:
    def test_exact_coverage(self):
        """1100 shares / 1100 lot = 1 lot."""
        assert compute_hedge_ratio(1100, 1100, 1.0) == 1

    def test_partial_coverage(self):
        """500 shares / 1100 lot → rounds to 0, but min 1."""
        assert compute_hedge_ratio(500, 1100, 1.0) == 1

    def test_multiple_lots(self):
        """2200 shares / 1100 lot = 2 lots."""
        assert compute_hedge_ratio(2200, 1100, 1.0) == 2

    def test_half_hedge(self):
        """1100 shares at 0.5 ratio = 1 lot (rounds from 0.5)."""
        assert compute_hedge_ratio(1100, 1100, 0.5) == 1

    def test_zero_shares(self):
        assert compute_hedge_ratio(0, 100, 1.0) == 0

    def test_zero_lot_size(self):
        assert compute_hedge_ratio(100, 0, 1.0) == 0


class TestBuildFuturesHedge:
    def test_tatasteel_short_futures(self, registry: MarketRegistry):
        """TATASTEEL — illiquid options, use short futures."""
        result = build_futures_hedge(
            ticker="TATASTEEL",
            shares=1100,
            price=136.0,
            futures_price=137.0,  # Slight contango
            futures_dte=30,
            market="INDIA",
            registry=registry,
        )
        assert result.tier == HedgeTier.FUTURES_SYNTHETIC
        assert result.hedge_type == "futures_short"
        assert result.trade_spec.structure_type == StructureType.FUTURES_SHORT
        # TATASTEEL lot_size=1100, so 1 lot covers 1100 shares
        assert result.trade_spec.legs[0].quantity == 1
        assert result.trade_spec.legs[0].action == LegAction.SELL_TO_OPEN
        # Commentary should mention basis
        assert any("basis" in c.lower() for c in result.commentary)

    def test_reliance_futures_2_lots(self, registry: MarketRegistry):
        """RELIANCE 500 shares / 250 lot = 2 lots."""
        result = build_futures_hedge(
            ticker="RELIANCE",
            shares=500,
            price=2680.0,
            futures_price=2695.0,
            futures_dte=30,
            market="INDIA",
            registry=registry,
        )
        assert result.trade_spec.legs[0].quantity == 2

    def test_no_futures_price_estimates(self, registry: MarketRegistry):
        """If futures_price is None, estimates from spot."""
        result = build_futures_hedge(
            ticker="TATASTEEL",
            shares=1100,
            price=136.0,
            futures_price=None,
            market="INDIA",
            registry=registry,
        )
        # Should not crash; uses estimated price (0.5% contango)
        assert result.trade_spec.legs[0].strike > 136.0

    def test_result_fields(self, registry: MarketRegistry):
        """All HedgeResult fields populated correctly."""
        result = build_futures_hedge(
            ticker="TATASTEEL",
            shares=1100,
            price=136.0,
            futures_price=137.0,
            futures_dte=30,
            market="INDIA",
            registry=registry,
        )
        assert result.ticker == "TATASTEEL"
        assert result.market == "INDIA"
        assert result.delta_reduction > 0
        assert result.protection_level != ""
        assert result.rationale != ""

    def test_half_hedge_ratio(self, registry: MarketRegistry):
        """0.5 hedge ratio on 2200 shares (2 lots) → 1 lot at 0.5."""
        result = build_futures_hedge(
            ticker="TATASTEEL",
            shares=2200,
            price=136.0,
            futures_price=137.0,
            futures_dte=30,
            hedge_ratio=0.5,
            market="INDIA",
            registry=registry,
        )
        assert result.trade_spec.legs[0].quantity == 1


class TestBuildSyntheticPut:
    def test_tatasteel_synthetic(self, registry: MarketRegistry):
        """Synthetic put for TATASTEEL — short futures + long call."""
        result = build_synthetic_put(
            ticker="TATASTEEL",
            shares=1100,
            price=136.0,
            futures_price=137.0,
            dte=30,
            market="INDIA",
            registry=registry,
        )
        assert result.synthetic_type == "synthetic_put"
        assert result.futures_direction == "short"
        assert result.option_type == "call"  # Synthetic put uses call
        assert len(result.trade_spec.legs) == 2
        # First leg: short futures
        futures_leg = result.trade_spec.legs[0]
        assert futures_leg.action == LegAction.SELL_TO_OPEN
        assert futures_leg.option_type == "future"
        # Second leg: long call
        call_leg = result.trade_spec.legs[1]
        assert call_leg.action == LegAction.BUY_TO_OPEN
        assert call_leg.option_type == "call"
        # Call strike should be near ATM
        assert abs(call_leg.strike - 136.0) < 10

    def test_synthetic_lot_count(self, registry: MarketRegistry):
        """Futures lots and option lots should match."""
        result = build_synthetic_put(
            ticker="RELIANCE",
            shares=500,
            price=2680.0,
            futures_price=2695.0,
            dte=30,
            market="INDIA",
            registry=registry,
        )
        assert result.futures_lots == result.option_lots

    def test_lot_size_override(self, registry: MarketRegistry):
        """Explicit lot_size override is respected."""
        result = build_synthetic_put(
            ticker="TATASTEEL",
            shares=2200,
            price=136.0,
            futures_price=137.0,
            lot_size=1100,
            dte=30,
            market="INDIA",
            registry=registry,
        )
        assert result.futures_lots == 2  # 2200 / 1100 = 2

    def test_net_cost_estimate(self, registry: MarketRegistry):
        """Net cost should be computed (not None)."""
        result = build_synthetic_put(
            ticker="TATASTEEL",
            shares=1100,
            price=136.0,
            futures_price=137.0,
            dte=30,
            market="INDIA",
            registry=registry,
        )
        assert result.net_cost_estimate is not None


class TestBuildSyntheticCollar:
    def test_synthetic_collar(self, registry: MarketRegistry):
        result = build_synthetic_collar(
            ticker="TATASTEEL",
            shares=1100,
            price=136.0,
            futures_price=137.0,
            call_strike=145.0,
            dte=30,
            market="INDIA",
            registry=registry,
        )
        assert result.synthetic_type == "synthetic_collar"
        assert result.option_strike == 145.0
        assert len(result.trade_spec.legs) == 2

    def test_collar_legs(self, registry: MarketRegistry):
        """First leg is futures short, second is long call."""
        result = build_synthetic_collar(
            ticker="TATASTEEL",
            shares=1100,
            price=136.0,
            futures_price=137.0,
            call_strike=145.0,
            dte=30,
            market="INDIA",
            registry=registry,
        )
        futures_leg = result.trade_spec.legs[0]
        call_leg = result.trade_spec.legs[1]
        assert futures_leg.action == LegAction.SELL_TO_OPEN
        assert futures_leg.option_type == "future"
        assert call_leg.action == LegAction.BUY_TO_OPEN
        assert call_leg.option_type == "call"
        assert call_leg.strike == 145.0

    def test_net_cost_none_without_broker(self, registry: MarketRegistry):
        """net_cost_estimate is None because call premium requires broker quote."""
        result = build_synthetic_collar(
            ticker="TATASTEEL",
            shares=1100,
            price=136.0,
            futures_price=137.0,
            call_strike=145.0,
            dte=30,
            market="INDIA",
            registry=registry,
        )
        assert result.net_cost_estimate is None
