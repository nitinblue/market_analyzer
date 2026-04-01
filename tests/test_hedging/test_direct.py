"""Tests for Tier 1 direct hedging — puts, collars, put spreads."""

import pytest

from income_desk.hedging.direct import (
    build_collar,
    build_protective_put,
    build_put_spread_hedge,
)
from income_desk.hedging.models import HedgeTier
from income_desk.models.opportunity import LegAction, OrderSide, StructureType
from income_desk.registry import MarketRegistry


@pytest.fixture
def registry() -> MarketRegistry:
    return MarketRegistry()


class TestProtectivePut:
    def test_reliance_r2(self, registry: MarketRegistry):
        """RELIANCE in R2 — 1 ATR OTM put."""
        result = build_protective_put(
            ticker="RELIANCE", shares=500, price=2680.0, regime_id=2,
            atr=80.0, dte=30, market="INDIA", registry=registry,
        )
        assert result.tier == HedgeTier.DIRECT
        assert result.hedge_type == "protective_put"
        assert result.trade_spec.ticker == "RELIANCE"
        assert result.trade_spec.structure_type == StructureType.LONG_OPTION
        assert len(result.trade_spec.legs) == 1
        leg = result.trade_spec.legs[0]
        assert leg.action == LegAction.BUY_TO_OPEN
        assert leg.option_type == "put"
        # Strike should be ~2600 (2680 - 80*1.0 = 2600, snapped to 20-interval)
        assert leg.strike <= 2680
        assert leg.strike >= 2500
        # Lots: 500 shares / 500 lot_size = 1
        assert leg.quantity == 1

    def test_spy_r4_near_atm(self, registry: MarketRegistry):
        """SPY in R4 — near ATM put (0.25 ATR OTM)."""
        result = build_protective_put(
            ticker="SPY", shares=100, price=580.0, regime_id=4,
            atr=8.0, dte=14, market="US", registry=registry,
        )
        leg = result.trade_spec.legs[0]
        # R4: 0.25 * 8 = 2 points OTM → strike ~578
        assert leg.strike >= 575
        assert leg.strike <= 580
        assert result.cost_pct > 2.0  # R4 is expensive

    def test_spy_r1_cheap_otm(self, registry: MarketRegistry):
        """SPY in R1 — far OTM put (1.5 ATR OTM)."""
        result = build_protective_put(
            ticker="SPY", shares=100, price=580.0, regime_id=1,
            atr=8.0, dte=30, market="US", registry=registry,
        )
        leg = result.trade_spec.legs[0]
        # R1: 1.5 * 8 = 12 points OTM → strike ~568
        assert leg.strike <= 570
        assert result.cost_pct < 1.0  # R1 is cheap

    def test_nifty_india_lot_size(self, registry: MarketRegistry):
        """NIFTY lot_size=25, strike_interval=50."""
        result = build_protective_put(
            ticker="NIFTY", shares=75, price=22500.0, regime_id=2,
            atr=200.0, dte=7, market="INDIA", registry=registry,
        )
        leg = result.trade_spec.legs[0]
        # 75 shares / 25 lot_size = 3 lots
        assert leg.quantity == 3
        # Strike interval is 50, so strike should be multiple of 50
        assert leg.strike % 50 == 0


class TestCollar:
    def test_reliance_r2_collar(self, registry: MarketRegistry):
        """RELIANCE R2 — zero-cost collar (high IV funds put with call)."""
        result = build_collar(
            ticker="RELIANCE", shares=500, price=2680.0, cost_basis=2400.0,
            regime_id=2, atr=80.0, dte=30, market="INDIA", registry=registry,
        )
        assert result.put_strike < 2680
        assert result.call_strike > 2680
        assert result.call_strike > 2400  # Above cost basis
        assert abs(result.net_cost) < 0.5  # R2 → near zero cost
        # TradeSpec has 2 legs
        assert len(result.trade_spec.legs) == 2
        put_leg = [l for l in result.trade_spec.legs if l.option_type == "put"][0]
        call_leg = [l for l in result.trade_spec.legs if l.option_type == "call"][0]
        assert put_leg.action == LegAction.BUY_TO_OPEN
        assert call_leg.action == LegAction.SELL_TO_OPEN

    def test_spy_collar_call_above_cost_basis(self, registry: MarketRegistry):
        """Call strike must be above cost basis."""
        result = build_collar(
            ticker="SPY", shares=100, price=580.0, cost_basis=575.0,
            regime_id=2, atr=8.0, dte=30, market="US", registry=registry,
        )
        assert result.call_strike > 575


class TestPutSpread:
    def test_budget_constrained_hedge(self, registry: MarketRegistry):
        """Put spread when budget is tight."""
        result = build_put_spread_hedge(
            ticker="SPY", shares=100, price=580.0, budget_pct=0.5,
            dte=30, market="US", registry=registry,
        )
        assert result.tier == HedgeTier.DIRECT
        assert result.hedge_type == "put_spread"
        assert result.trade_spec.structure_type == StructureType.DEBIT_SPREAD
        assert len(result.trade_spec.legs) == 2
        # Long put should be higher strike than short put
        long_leg = [l for l in result.trade_spec.legs if l.action == LegAction.BUY_TO_OPEN][0]
        short_leg = [l for l in result.trade_spec.legs if l.action == LegAction.SELL_TO_OPEN][0]
        assert long_leg.strike > short_leg.strike

    def test_reliance_put_spread(self, registry: MarketRegistry):
        """RELIANCE put spread with strike intervals."""
        result = build_put_spread_hedge(
            ticker="RELIANCE", shares=500, price=2680.0, budget_pct=1.0,
            dte=30, market="INDIA", registry=registry,
        )
        for leg in result.trade_spec.legs:
            # RELIANCE strike interval = 20
            assert leg.strike % 20 == 0
