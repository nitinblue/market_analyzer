"""Tests for Tier 3 proxy/index hedging."""

import pytest

from income_desk.hedging.models import HedgeTier
from income_desk.hedging.proxy import (
    build_index_hedge,
    compute_portfolio_beta,
    recommend_proxy,
)
from income_desk.models.opportunity import LegAction, StructureType
from income_desk.registry import MarketRegistry


@pytest.fixture
def registry() -> MarketRegistry:
    return MarketRegistry()


class TestComputePortfolioBeta:
    def test_single_tech_stock(self):
        beta = compute_portfolio_beta(["AAPL"], [100000.0], "SPY", "US")
        assert beta > 1.0  # Tech is high-beta

    def test_mixed_portfolio(self):
        beta = compute_portfolio_beta(
            ["AAPL", "XLU", "TLT"],
            [100000.0, 50000.0, 50000.0],
            "SPY", "US",
        )
        # Mix of high-beta tech (1.20) + low-beta utilities (0.55) + negative-beta bonds (-0.20)
        assert 0.3 < beta < 1.5

    def test_india_finance_portfolio(self):
        beta = compute_portfolio_beta(
            ["HDFCBANK", "ICICIBANK", "SBIN"],
            [500000.0, 500000.0, 500000.0],
            "NIFTY", "INDIA",
        )
        assert beta > 1.0  # Finance is high-beta in India

    def test_empty_returns_one(self):
        assert compute_portfolio_beta([], [], "SPY", "US") == 1.0

    def test_mismatched_lengths_returns_one(self):
        assert compute_portfolio_beta(["AAPL", "MSFT"], [100000.0], "SPY", "US") == 1.0

    def test_zero_total_value_returns_one(self):
        assert compute_portfolio_beta(["AAPL"], [0.0], "SPY", "US") == 1.0

    def test_weighted_correctly(self):
        """Equal-weight portfolio of same sector = that sector's beta."""
        beta = compute_portfolio_beta(
            ["AAPL", "MSFT"],
            [100000.0, 100000.0],
            "SPY", "US",
        )
        # Both tech — both 1.20
        assert abs(beta - 1.20) < 0.01


class TestRecommendProxy:
    def test_india_consumer_nifty(self, registry: MarketRegistry):
        proxy = recommend_proxy("DMART", "INDIA", registry)
        assert proxy == "NIFTY"

    def test_us_tech_qqq(self, registry: MarketRegistry):
        proxy = recommend_proxy("AAPL", "US", registry)
        assert proxy == "QQQ"

    def test_unknown_india_ticker_defaults_nifty(self, registry: MarketRegistry):
        proxy = recommend_proxy("UNKNOWN_STOCK", "INDIA", registry)
        assert proxy == "NIFTY"

    def test_unknown_us_ticker_defaults_spy(self, registry: MarketRegistry):
        proxy = recommend_proxy("UNKNOWN_STOCK", "US", registry)
        assert proxy == "SPY"


class TestBuildIndexHedge:
    def test_india_nifty_hedge(self, registry: MarketRegistry):
        """Hedge a non-F&O India stock with NIFTY puts."""
        result = build_index_hedge(
            portfolio_value=500000.0,
            portfolio_beta=0.9,
            index="NIFTY",
            index_price=22500.0,
            regime_id=2,
            dte=30,
            market="INDIA",
            registry=registry,
        )
        assert result.tier == HedgeTier.PROXY_INDEX
        assert result.hedge_type == "index_put"
        assert result.trade_spec.ticker == "NIFTY"
        assert result.trade_spec.structure_type == StructureType.LONG_OPTION
        leg = result.trade_spec.legs[0]
        assert leg.action == LegAction.BUY_TO_OPEN
        assert leg.option_type == "put"
        # Strike should be multiple of NIFTY strike interval (50)
        assert leg.strike % 50 == 0
        assert leg.strike < 22500  # OTM
        # Should flag basis risk in commentary
        assert any("basis risk" in c.lower() for c in result.commentary)

    def test_us_spy_hedge(self, registry: MarketRegistry):
        result = build_index_hedge(
            portfolio_value=50000.0,
            portfolio_beta=1.2,
            index="SPY",
            index_price=580.0,
            regime_id=4,
            dte=14,
            market="US",
            registry=registry,
        )
        assert result.trade_spec.ticker == "SPY"
        leg = result.trade_spec.legs[0]
        # R4: 2% OTM → strike ~568
        assert leg.strike < 580
        assert leg.strike >= 550

    def test_hedge_pct_scales_lots(self, registry: MarketRegistry):
        """Half hedge should use fewer lots."""
        full = build_index_hedge(
            portfolio_value=5000000.0, portfolio_beta=1.0,
            index="NIFTY", index_price=22500.0, regime_id=2,
            dte=30, market="INDIA", hedge_pct=1.0, registry=registry,
        )
        half = build_index_hedge(
            portfolio_value=5000000.0, portfolio_beta=1.0,
            index="NIFTY", index_price=22500.0, regime_id=2,
            dte=30, market="INDIA", hedge_pct=0.5, registry=registry,
        )
        assert full.trade_spec.legs[0].quantity >= half.trade_spec.legs[0].quantity

    def test_result_fields_populated(self, registry: MarketRegistry):
        """All key fields are populated."""
        result = build_index_hedge(
            portfolio_value=500000.0,
            portfolio_beta=1.0,
            index="NIFTY",
            index_price=22500.0,
            regime_id=1,
            dte=30,
            market="INDIA",
            registry=registry,
        )
        assert result.cost_estimate is not None
        assert result.cost_pct is not None
        assert result.delta_reduction > 0
        assert result.protection_level != ""
        assert result.rationale != ""

    def test_regime_affects_otm_distance(self, registry: MarketRegistry):
        """R4 puts are closer to ATM than R1 puts."""
        r1 = build_index_hedge(
            portfolio_value=500000.0, portfolio_beta=1.0,
            index="NIFTY", index_price=22500.0, regime_id=1,
            dte=30, market="INDIA", registry=registry,
        )
        r4 = build_index_hedge(
            portfolio_value=500000.0, portfolio_beta=1.0,
            index="NIFTY", index_price=22500.0, regime_id=4,
            dte=30, market="INDIA", registry=registry,
        )
        # R1: 5% OTM, R4: 2% OTM → R4 strike is closer to spot (higher)
        assert r4.trade_spec.legs[0].strike > r1.trade_spec.legs[0].strike

    def test_unknown_index_uses_defaults(self):
        """Unknown index falls back to default lot sizes."""
        result = build_index_hedge(
            portfolio_value=100000.0,
            portfolio_beta=1.0,
            index="MIDCAP",
            index_price=10000.0,
            regime_id=2,
            dte=30,
            market="INDIA",
        )
        # Should not crash; uses fallback lot_size=25 for INDIA
        assert result.tier == HedgeTier.PROXY_INDEX
        assert result.trade_spec.legs[0].quantity >= 1
