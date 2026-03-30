"""Tests for data providers (contract tests + integration)."""

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from income_desk.data.exceptions import DataFetchError
from income_desk.data.providers.yfinance import YFinanceProvider, resolve_yfinance_ticker
from income_desk.models.data import DataRequest, DataType, ProviderType


@pytest.fixture
def provider() -> YFinanceProvider:
    return YFinanceProvider()


@pytest.fixture
def sample_yf_df() -> pd.DataFrame:
    """DataFrame mimicking yfinance output."""
    dates = pd.date_range("2025-01-02", periods=5, freq="B")
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "High": [101.0, 102.0, 103.0, 104.0, 105.0],
            "Low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "Close": [100.5, 101.5, 102.5, 103.5, 104.5],
            "Volume": [1000, 1100, 1200, 1300, 1400],
        },
        index=dates,
    )


class TestYFinanceFetch:
    def test_fetch_returns_ohlcv(self, provider: YFinanceProvider, sample_yf_df: pd.DataFrame) -> None:
        request = DataRequest(
            ticker="SPY",
            data_type=DataType.OHLCV,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
        )

        with patch("income_desk.data.providers.yfinance.yf.download", return_value=sample_yf_df):
            result = provider.fetch(request)

        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert isinstance(result.index, pd.DatetimeIndex)
        assert result.index.is_monotonic_increasing
        assert len(result) == 5

    def test_fetch_empty_raises(self, provider: YFinanceProvider) -> None:
        request = DataRequest(ticker="INVALID", data_type=DataType.OHLCV)

        with patch("income_desk.data.providers.yfinance.yf.download", return_value=pd.DataFrame()):
            with pytest.raises(DataFetchError, match="No data returned"):
                provider.fetch(request)

    def test_fetch_exception_raises(self, provider: YFinanceProvider) -> None:
        request = DataRequest(ticker="SPY", data_type=DataType.OHLCV)

        with patch("income_desk.data.providers.yfinance.yf.download", side_effect=Exception("network error")):
            with pytest.raises(DataFetchError, match="network error"):
                provider.fetch(request)

    def test_fetch_flattens_multiindex(self, provider: YFinanceProvider) -> None:
        """yfinance sometimes returns MultiIndex columns for single ticker."""
        dates = pd.date_range("2025-01-02", periods=3, freq="B")
        arrays = [
            ["Open", "High", "Low", "Close", "Volume"],
            ["SPY", "SPY", "SPY", "SPY", "SPY"],
        ]
        tuples = list(zip(*arrays))
        index = pd.MultiIndex.from_tuples(tuples)
        df = pd.DataFrame(
            [[100, 101, 99, 100.5, 1000],
             [101, 102, 100, 101.5, 1100],
             [102, 103, 101, 102.5, 1200]],
            index=dates,
            columns=index,
        )

        request = DataRequest(ticker="SPY", data_type=DataType.OHLCV)
        with patch("income_desk.data.providers.yfinance.yf.download", return_value=df):
            result = provider.fetch(request)

        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]


class TestYFinanceValidate:
    def test_valid_ticker(self, provider: YFinanceProvider) -> None:
        mock_ticker = MagicMock()
        mock_ticker.info = {"regularMarketPrice": 450.0}

        with patch("income_desk.data.providers.yfinance.yf.Ticker", return_value=mock_ticker):
            assert provider.validate_ticker("SPY") is True

    def test_invalid_ticker(self, provider: YFinanceProvider) -> None:
        mock_ticker = MagicMock()
        mock_ticker.info = {"regularMarketPrice": None}

        with patch("income_desk.data.providers.yfinance.yf.Ticker", return_value=mock_ticker):
            assert provider.validate_ticker("ZZZZZZZ") is False

    def test_exception_returns_false(self, provider: YFinanceProvider) -> None:
        with patch("income_desk.data.providers.yfinance.yf.Ticker", side_effect=Exception("fail")):
            assert provider.validate_ticker("SPY") is False


class TestResolveYfinanceTicker:
    """Tests for resolve_yfinance_ticker — BUG-002 fix."""

    def test_us_ticker_unchanged(self) -> None:
        assert resolve_yfinance_ticker("SPY") == "SPY"
        assert resolve_yfinance_ticker("AAPL") == "AAPL"

    def test_us_index_alias(self) -> None:
        assert resolve_yfinance_ticker("SPX") == "^GSPC"
        assert resolve_yfinance_ticker("VIX") == "^VIX"

    def test_india_index_alias(self) -> None:
        assert resolve_yfinance_ticker("NIFTY") == "^NSEI"
        assert resolve_yfinance_ticker("BANKNIFTY") == "^NSEBANK"
        assert resolve_yfinance_ticker("FINNIFTY") == "NIFTY_FIN_SERVICE.NS"

    def test_india_stock_gets_ns_suffix(self) -> None:
        """BUG-002: ICICIBANK, SBIN must resolve to .NS suffix."""
        assert resolve_yfinance_ticker("ICICIBANK") == "ICICIBANK.NS"
        assert resolve_yfinance_ticker("SBIN") == "SBIN.NS"
        assert resolve_yfinance_ticker("RELIANCE") == "RELIANCE.NS"
        assert resolve_yfinance_ticker("TCS") == "TCS.NS"
        assert resolve_yfinance_ticker("INFY") == "INFY.NS"
        assert resolve_yfinance_ticker("HDFCBANK") == "HDFCBANK.NS"

    def test_india_stock_special_yfinance_symbols(self) -> None:
        """India stocks with yfinance overrides (M_M -> M&M.NS, etc.)."""
        assert resolve_yfinance_ticker("M_M") == "M&M.NS"
        assert resolve_yfinance_ticker("BAJAJ_AUTO") == "BAJAJ-AUTO.NS"

    def test_dxlink_prefix_stripped(self) -> None:
        assert resolve_yfinance_ticker("$SPX") == "^GSPC"
        assert resolve_yfinance_ticker("$SPY") == "SPY"

    def test_already_suffixed_unchanged(self) -> None:
        """Tickers already having .NS should not be double-suffixed."""
        assert resolve_yfinance_ticker("RELIANCE.NS") == "RELIANCE.NS"

    def test_unknown_ticker_unchanged(self) -> None:
        """Unknown tickers not in registry pass through unchanged."""
        assert resolve_yfinance_ticker("XYZNOTREAL") == "XYZNOTREAL"


class TestProviderContract:
    def test_provider_type(self, provider: YFinanceProvider) -> None:
        assert provider.provider_type == ProviderType.YFINANCE

    def test_supported_data_types(self, provider: YFinanceProvider) -> None:
        assert DataType.OHLCV in provider.supported_data_types
        assert DataType.OPTIONS_CHAIN in provider.supported_data_types
