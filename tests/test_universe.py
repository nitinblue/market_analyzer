"""Tests for universe filtering and scanning."""

from unittest.mock import MagicMock

from market_analyzer.models.universe import (
    PRESETS,
    AssetType,
    SortField,
    UniverseCandidate,
    UniverseFilter,
    UniverseScanResult,
)
from market_analyzer.service.universe import UniverseService


class TestUniverseFilter:
    def test_default_filter(self):
        f = UniverseFilter()
        assert f.asset_types == [AssetType.ETF]
        assert f.min_price == 5.0
        assert f.max_price == 500.0
        assert f.min_liquidity_rating == 3
        assert f.max_symbols == 50
        assert f.sort_by == SortField.IV_RANK

    def test_presets_exist(self):
        assert "income" in PRESETS
        assert "directional" in PRESETS
        assert "high_vol" in PRESETS
        assert "broad" in PRESETS

    def test_income_preset(self):
        f = PRESETS["income"]
        assert f.iv_rank_min == 30.0
        assert f.iv_rank_max == 80.0
        assert f.min_liquidity_rating == 4
        assert f.exclude_earnings_within_days == 7

    def test_custom_filter(self):
        f = UniverseFilter(
            asset_types=[AssetType.ETF, AssetType.EQUITY],
            iv_rank_min=50.0,
            beta_max=1.5,
            max_symbols=25,
        )
        assert len(f.asset_types) == 2
        assert f.iv_rank_min == 50.0
        assert f.max_symbols == 25


class TestUniverseScanResult:
    def test_empty_result(self):
        r = UniverseScanResult(
            filter_used="income",
            total_scanned=0,
            total_passed=0,
            candidates=[],
        )
        assert r.total_passed == 0
        assert r.watchlist_saved is None

    def test_with_candidates(self):
        r = UniverseScanResult(
            filter_used="custom",
            total_scanned=500,
            total_passed=30,
            candidates=[
                UniverseCandidate(
                    ticker="SPY",
                    asset_type="ETF",
                    iv_rank=45.0,
                    liquidity_rating=5.0,
                    beta=1.0,
                ),
            ],
            watchlist_saved="MA-Income",
        )
        assert r.total_passed == 30
        assert r.candidates[0].ticker == "SPY"
        assert r.watchlist_saved == "MA-Income"


class TestUniverseService:
    def test_no_broker_returns_empty(self):
        svc = UniverseService()
        assert not svc.has_broker
        result = svc.scan(preset="income")
        assert result.total_passed == 0

    def test_scan_with_mocked_broker(self):
        mock_wl = MagicMock()
        mock_wl.get_all_equities.return_value = [
            {"symbol": "SPY", "is_etf": True, "is_index": False, "is_illiquid": False},
            {"symbol": "GLD", "is_etf": True, "is_index": False, "is_illiquid": False},
            {"symbol": "ILLIQ", "is_etf": True, "is_index": False, "is_illiquid": True},
        ]

        from market_analyzer.models.quotes import MarketMetrics

        mock_metrics = MagicMock()
        mock_metrics.get_metrics.return_value = {
            "SPY": MarketMetrics(
                ticker="SPY", iv_rank=50.0, liquidity_rating=5.0,
                beta=1.0, iv_30_day=0.20, hv_30_day=0.15,
            ),
            "GLD": MarketMetrics(
                ticker="GLD", iv_rank=35.0, liquidity_rating=4.0,
                beta=0.1, iv_30_day=0.18, hv_30_day=0.16,
            ),
        }

        svc = UniverseService(
            watchlist_provider=mock_wl,
            metrics_provider=mock_metrics,
        )
        assert svc.has_broker

        result = svc.scan(preset="income")
        # Both SPY and GLD should pass income preset (IV rank 30-80, liq 4+)
        tickers = [c.ticker for c in result.candidates]
        assert "SPY" in tickers
        assert "GLD" in tickers
        assert "ILLIQ" not in tickers  # Illiquid filtered out

    def test_iv_rank_filter(self):
        mock_wl = MagicMock()
        mock_wl.get_all_equities.return_value = [
            {"symbol": "HIGH", "is_etf": True, "is_index": False, "is_illiquid": False},
            {"symbol": "LOW", "is_etf": True, "is_index": False, "is_illiquid": False},
        ]

        from market_analyzer.models.quotes import MarketMetrics

        mock_metrics = MagicMock()
        mock_metrics.get_metrics.return_value = {
            "HIGH": MarketMetrics(ticker="HIGH", iv_rank=90.0, liquidity_rating=5.0),
            "LOW": MarketMetrics(ticker="LOW", iv_rank=10.0, liquidity_rating=5.0),
        }

        svc = UniverseService(mock_wl, mock_metrics)
        filt = UniverseFilter(iv_rank_min=50.0, min_liquidity_rating=1)
        result = svc.scan(filter_config=filt)

        tickers = [c.ticker for c in result.candidates]
        assert "HIGH" in tickers
        assert "LOW" not in tickers

    def test_include_tickers_bypass_filters(self):
        mock_wl = MagicMock()
        mock_wl.get_all_equities.return_value = []

        mock_metrics = MagicMock()
        mock_metrics.get_metrics.return_value = {}

        svc = UniverseService(mock_wl, mock_metrics)
        filt = UniverseFilter(include_tickers=["FORCED"])
        result = svc.scan(filter_config=filt)

        assert any(c.ticker == "FORCED" for c in result.candidates)
        assert "FORCED" in result.include_forced

    def test_save_watchlist(self):
        mock_wl = MagicMock()
        mock_wl.get_all_equities.return_value = [
            {"symbol": "SPY", "is_etf": True, "is_index": False, "is_illiquid": False},
        ]
        mock_wl.create_watchlist.return_value = True

        from market_analyzer.models.quotes import MarketMetrics

        mock_metrics = MagicMock()
        mock_metrics.get_metrics.return_value = {
            "SPY": MarketMetrics(ticker="SPY", iv_rank=50.0, liquidity_rating=5.0),
        }

        svc = UniverseService(mock_wl, mock_metrics)
        result = svc.scan(save_watchlist="MA-Test")

        mock_wl.create_watchlist.assert_called_once_with("MA-Test", ["SPY"])
        assert result.watchlist_saved == "MA-Test"

    def test_sort_by_iv_rank(self):
        mock_wl = MagicMock()
        mock_wl.get_all_equities.return_value = [
            {"symbol": "A", "is_etf": True, "is_index": False, "is_illiquid": False},
            {"symbol": "B", "is_etf": True, "is_index": False, "is_illiquid": False},
            {"symbol": "C", "is_etf": True, "is_index": False, "is_illiquid": False},
        ]

        from market_analyzer.models.quotes import MarketMetrics

        mock_metrics = MagicMock()
        mock_metrics.get_metrics.return_value = {
            "A": MarketMetrics(ticker="A", iv_rank=30.0, liquidity_rating=5.0),
            "B": MarketMetrics(ticker="B", iv_rank=80.0, liquidity_rating=5.0),
            "C": MarketMetrics(ticker="C", iv_rank=50.0, liquidity_rating=5.0),
        }

        svc = UniverseService(mock_wl, mock_metrics)
        filt = UniverseFilter(sort_by=SortField.IV_RANK, sort_descending=True, min_liquidity_rating=1)
        result = svc.scan(filter_config=filt)

        # Sorted by IV rank descending: B(80) > C(50) > A(30)
        assert result.candidates[0].ticker == "B"
        assert result.candidates[1].ticker == "C"
        assert result.candidates[2].ticker == "A"


class TestWatchlistProviderABC:
    def test_create_watchlist_default(self):
        from market_analyzer.broker.base import WatchlistProvider
        # Default implementation returns False
        class DummyWL(WatchlistProvider):
            def get_watchlist(self, name): return []
            def list_watchlists(self): return []

        wl = DummyWL()
        assert wl.create_watchlist("test", ["SPY"]) is False
        assert wl.get_all_equities() == []
