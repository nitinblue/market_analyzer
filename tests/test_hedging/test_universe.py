"""Tests for hedging universe classification."""

import pytest

from income_desk.hedging.models import HedgeTier
from income_desk.hedging.universe import (
    classify_hedge_tier,
    get_fno_coverage,
    get_proxy_instrument,
    get_sector_beta,
)
from income_desk.registry import MarketRegistry


@pytest.fixture
def registry() -> MarketRegistry:
    return MarketRegistry()


class TestClassifyHedgeTier:
    """Test hedge tier classification for various instruments."""

    def test_reliance_india_direct(self, registry: MarketRegistry):
        """RELIANCE has medium options liquidity → DIRECT."""
        tier = classify_hedge_tier("RELIANCE", "INDIA", registry)
        assert tier == HedgeTier.DIRECT

    def test_nifty_india_direct(self, registry: MarketRegistry):
        """NIFTY has high options liquidity → DIRECT."""
        tier = classify_hedge_tier("NIFTY", "INDIA", registry)
        assert tier == HedgeTier.DIRECT

    def test_hindunilvr_india_futures(self, registry: MarketRegistry):
        """HINDUNILVR has low options liquidity → FUTURES_SYNTHETIC (India has stock futures)."""
        tier = classify_hedge_tier("HINDUNILVR", "INDIA", registry)
        assert tier == HedgeTier.FUTURES_SYNTHETIC

    def test_tatasteel_india_futures(self, registry: MarketRegistry):
        """TATASTEEL has low options liquidity → FUTURES_SYNTHETIC."""
        tier = classify_hedge_tier("TATASTEEL", "INDIA", registry)
        assert tier == HedgeTier.FUTURES_SYNTHETIC

    def test_dmart_india_proxy(self, registry: MarketRegistry):
        """DMart not in F&O registry → PROXY_INDEX."""
        tier = classify_hedge_tier("DMART", "INDIA", registry)
        assert tier == HedgeTier.PROXY_INDEX

    def test_spy_us_direct(self, registry: MarketRegistry):
        """SPY has high options liquidity → DIRECT."""
        tier = classify_hedge_tier("SPY", "US", registry)
        assert tier == HedgeTier.DIRECT

    def test_unknown_us_direct(self, registry: MarketRegistry):
        """Unknown US ticker defaults to DIRECT (most US stocks have options)."""
        tier = classify_hedge_tier("SOME_UNKNOWN", "US", registry)
        assert tier == HedgeTier.DIRECT

    def test_unknown_india_proxy(self, registry: MarketRegistry):
        """Unknown India ticker defaults to PROXY_INDEX."""
        tier = classify_hedge_tier("SOME_UNKNOWN", "INDIA", registry)
        assert tier == HedgeTier.PROXY_INDEX


class TestGetFnOCoverage:
    def test_india_mixed_portfolio(self, registry: MarketRegistry):
        """10-stock India portfolio with mixed tiers."""
        tickers = [
            "RELIANCE", "NIFTY", "BANKNIFTY",    # Direct (high/medium liq)
            "TATASTEEL", "HINDUNILVR", "LT",       # Futures (low liq)
            "DMART", "PIDILITIND",                  # Proxy (not in registry)
            "HDFCBANK", "ICICIBANK",                # Direct (medium liq)
        ]
        coverage = get_fno_coverage(tickers, "INDIA", registry)
        assert coverage.total_tickers == 10
        assert coverage.direct_hedge_count >= 5  # RELIANCE, NIFTY, BANKNIFTY, HDFCBANK, ICICIBANK
        assert coverage.futures_hedge_count >= 2  # TATASTEEL, HINDUNILVR, LT
        assert coverage.proxy_only_count >= 1  # DMART at minimum
        assert coverage.coverage_pct > 50

    def test_us_portfolio(self, registry: MarketRegistry):
        """US portfolio — almost everything is direct."""
        tickers = ["SPY", "QQQ", "AAPL", "MSFT", "GOOGL"]
        coverage = get_fno_coverage(tickers, "US", registry)
        assert coverage.direct_hedge_count == 5
        assert coverage.coverage_pct == 100.0

    def test_empty_tickers(self, registry: MarketRegistry):
        coverage = get_fno_coverage([], "US", registry)
        assert coverage.total_tickers == 0
        assert coverage.coverage_pct == 0


class TestGetSectorBeta:
    def test_india_finance_beta(self):
        beta = get_sector_beta("HDFCBANK", "NIFTY", "INDIA")
        assert beta > 1.0  # Finance is high-beta in India

    def test_india_pharma_beta(self):
        beta = get_sector_beta("SUNPHARMA", "NIFTY", "INDIA")
        assert beta < 1.0  # Pharma is defensive

    def test_us_tech_beta(self):
        beta = get_sector_beta("AAPL", "SPY", "US")
        assert beta > 1.0  # Tech is high-beta

    def test_unknown_defaults_to_one(self):
        beta = get_sector_beta("UNKNOWN_TICKER", "SPY", "US")
        assert beta == 1.0


class TestGetProxyInstrument:
    def test_india_finance_banknifty(self, registry: MarketRegistry):
        proxy = get_proxy_instrument("HDFCBANK", "INDIA", registry)
        assert proxy == "BANKNIFTY"

    def test_india_tech_nifty(self, registry: MarketRegistry):
        proxy = get_proxy_instrument("TCS", "INDIA", registry)
        assert proxy == "NIFTY"

    def test_india_unknown_nifty(self, registry: MarketRegistry):
        proxy = get_proxy_instrument("DMART", "INDIA", registry)
        assert proxy == "NIFTY"

    def test_us_tech_qqq(self, registry: MarketRegistry):
        proxy = get_proxy_instrument("AAPL", "US", registry)
        assert proxy == "QQQ"

    def test_us_finance_xlf(self, registry: MarketRegistry):
        proxy = get_proxy_instrument("JPM", "US", registry)
        assert proxy == "XLF"

    def test_us_unknown_spy(self, registry: MarketRegistry):
        proxy = get_proxy_instrument("RANDOM_STOCK", "US", registry)
        assert proxy == "SPY"
