"""Tests for data adapters (CSV, dict quotes, IBKR/Schwab skeletons)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from datetime import date
from pathlib import Path

from income_desk.adapters.csv_provider import CSVProvider
from income_desk.adapters.dict_quotes import DictQuoteProvider, DictMetricsProvider
from income_desk.models.data import DataRequest, DataType
from income_desk.models.opportunity import LegSpec, LegAction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_leg(
    strike: float,
    option_type: str = "put",
    expiration: date = date(2026, 4, 24),
) -> LegSpec:
    return LegSpec(
        role="test",
        action=LegAction.SELL_TO_OPEN,
        option_type=option_type,
        strike=strike,
        strike_label="test",
        expiration=expiration,
        days_to_expiry=35,
        atm_iv_at_expiry=0.22,
    )


# ---------------------------------------------------------------------------
# CSVProvider
# ---------------------------------------------------------------------------

class TestCSVProvider:
    def test_reads_csv_ohlcv(self, tmp_path: Path) -> None:
        csv_content = (
            "Date,Open,High,Low,Close,Volume\n"
            "2024-01-02,472.65,473.50,471.00,472.00,50000000\n"
            "2024-01-03,473.00,475.00,472.50,474.50,45000000\n"
        )
        (tmp_path / "SPY.csv").write_text(csv_content)

        provider = CSVProvider(tmp_path)
        assert provider.validate_ticker("SPY") is True
        assert provider.validate_ticker("FAKE") is False

        req = DataRequest(ticker="SPY", data_type=DataType.OHLCV)
        df = provider.fetch(req)
        assert len(df) == 2
        assert "Close" in df.columns

    def test_missing_ticker_raises(self, tmp_path: Path) -> None:
        from income_desk.data.exceptions import DataFetchError

        provider = CSVProvider(tmp_path)
        with pytest.raises(DataFetchError):
            provider.fetch(DataRequest(ticker="FAKE", data_type=DataType.OHLCV))

    def test_normalizes_standard_column_names(self, tmp_path: Path) -> None:
        """Standard OHLCV column names accepted verbatim."""
        csv_content = (
            "date,Open,High,Low,Close,Volume\n"
            "2024-01-02,100,105,99,103,1000\n"
        )
        (tmp_path / "STD.csv").write_text(csv_content)
        provider = CSVProvider(tmp_path)
        df = provider.fetch(DataRequest(ticker="STD", data_type=DataType.OHLCV))
        assert "Open" in df.columns
        assert "Close" in df.columns

    def test_normalizes_abbreviated_column_names(self, tmp_path: Path) -> None:
        """Abbreviated column names (o/h/l/c/vol) are expanded correctly."""
        csv_content = (
            "date,o,h,l,c,vol\n"
            "2024-01-02,100,105,99,103,1000\n"
        )
        (tmp_path / "TEST.csv").write_text(csv_content)
        provider = CSVProvider(tmp_path)
        df = provider.fetch(DataRequest(ticker="TEST", data_type=DataType.OHLCV))
        assert "Open" in df.columns
        assert "Close" in df.columns
        assert "Volume" in df.columns

    def test_date_range_filtering(self, tmp_path: Path) -> None:
        csv_content = (
            "Date,Open,High,Low,Close,Volume\n"
            "2024-01-02,100,105,99,103,1000\n"
            "2024-01-03,103,108,102,107,1200\n"
            "2024-01-04,107,110,106,109,900\n"
        )
        (tmp_path / "RTEST.csv").write_text(csv_content)
        provider = CSVProvider(tmp_path)
        req = DataRequest(
            ticker="RTEST",
            data_type=DataType.OHLCV,
            start_date=date(2024, 1, 3),
            end_date=date(2024, 1, 3),
        )
        df = provider.fetch(req)
        assert len(df) == 1

    def test_provider_type(self, tmp_path: Path) -> None:
        from income_desk.models.data import ProviderType

        provider = CSVProvider(tmp_path)
        assert provider.provider_type == ProviderType.CSV

    def test_supported_data_types(self, tmp_path: Path) -> None:
        provider = CSVProvider(tmp_path)
        assert DataType.OHLCV in provider.supported_data_types


# ---------------------------------------------------------------------------
# DictQuoteProvider
# ---------------------------------------------------------------------------

class TestDictQuoteProvider:
    _sample_quotes: dict = {
        ("SPY", 570.0, "put",  "2026-04-24"): {"bid": 1.20, "ask": 1.35, "iv": 0.22},
        ("SPY", 590.0, "call", "2026-04-24"): {"bid": 1.10, "ask": 1.25, "iv": 0.20},
        ("QQQ", 480.0, "put",  "2026-04-24"): {"bid": 2.00, "ask": 2.20, "iv": 0.25},
    }

    def test_provider_name(self) -> None:
        provider = DictQuoteProvider({})
        assert provider.provider_name == "dict"

    def test_underlying_price_found(self) -> None:
        provider = DictQuoteProvider({}, underlying_prices={"SPY": 580.0})
        assert provider.get_underlying_price("SPY") == 580.0

    def test_underlying_price_missing(self) -> None:
        provider = DictQuoteProvider({})
        assert provider.get_underlying_price("FAKE") is None

    def test_chain_returns_correct_ticker(self) -> None:
        provider = DictQuoteProvider(self._sample_quotes)
        chain = provider.get_option_chain("SPY")
        assert len(chain) == 2
        assert all(q.ticker == "SPY" for q in chain)

    def test_chain_filters_by_expiration(self) -> None:
        provider = DictQuoteProvider(self._sample_quotes)
        chain = provider.get_option_chain("SPY", expiration=date(2026, 4, 24))
        assert len(chain) == 2

        empty = provider.get_option_chain("SPY", expiration=date(2026, 5, 1))
        assert len(empty) == 0

    def test_chain_filters_by_ticker(self) -> None:
        provider = DictQuoteProvider(self._sample_quotes)
        chain = provider.get_option_chain("QQQ")
        assert len(chain) == 1
        assert chain[0].ticker == "QQQ"

    def test_get_quotes_returns_matching_leg(self) -> None:
        provider = DictQuoteProvider(self._sample_quotes)
        legs = [_make_leg(570.0, "put", date(2026, 4, 24))]
        result = provider.get_quotes(legs)
        assert len(result) == 1
        q = result[0]
        assert q is not None
        assert q.bid == 1.20
        assert q.ask == 1.35
        assert q.mid == pytest.approx(1.275)
        assert q.implied_volatility == pytest.approx(0.22)

    def test_get_quotes_returns_none_for_no_match(self) -> None:
        provider = DictQuoteProvider(self._sample_quotes)
        legs = [_make_leg(999.0, "put", date(2026, 4, 24))]  # strike not in dict
        result = provider.get_quotes(legs)
        assert len(result) == 1
        assert result[0] is None

    def test_get_quotes_mid_computed(self) -> None:
        quotes = {("SPY", 570.0, "put", "2026-04-24"): {"bid": 1.00, "ask": 1.50}}
        provider = DictQuoteProvider(quotes)
        legs = [_make_leg(570.0, "put", date(2026, 4, 24))]
        result = provider.get_quotes(legs)
        assert result[0].mid == pytest.approx(1.25)

    def test_get_greeks(self) -> None:
        quotes = {
            ("SPY", 570.0, "put", "2026-04-24"): {
                "bid": 1.20, "ask": 1.35,
                "delta": -0.30, "gamma": 0.02, "theta": -0.05, "vega": 0.10,
            }
        }
        provider = DictQuoteProvider(quotes)
        legs = [_make_leg(570.0, "put")]
        greeks = provider.get_greeks(legs)
        assert "570.0p" in greeks or "570p" in greeks or any("570" in k for k in greeks)

    def test_empty_dict_returns_empty_chain(self) -> None:
        provider = DictQuoteProvider({})
        assert provider.get_option_chain("SPY") == []


# ---------------------------------------------------------------------------
# DictMetricsProvider
# ---------------------------------------------------------------------------

class TestDictMetricsProvider:
    def test_returns_metrics_for_known_ticker(self) -> None:
        metrics = {
            "SPY": {"iv_rank": 43.0, "iv_percentile": 91.0},
        }
        provider = DictMetricsProvider(metrics)
        result = provider.get_metrics(["SPY"])
        assert "SPY" in result
        assert result["SPY"].iv_rank == 43.0
        assert result["SPY"].iv_percentile == 91.0

    def test_omits_unknown_tickers(self) -> None:
        provider = DictMetricsProvider({})
        result = provider.get_metrics(["SPY", "QQQ"])
        assert len(result) == 0

    def test_partial_metrics_fields(self) -> None:
        metrics = {"GLD": {"iv_rank": 28.0}}  # only iv_rank
        provider = DictMetricsProvider(metrics)
        result = provider.get_metrics(["GLD"])
        assert result["GLD"].iv_rank == 28.0
        assert result["GLD"].iv_percentile is None


# ---------------------------------------------------------------------------
# Skeleton adapters — verify importable and raise NotImplementedError
# ---------------------------------------------------------------------------

class TestIBKRAdapterSkeleton:
    def test_importable(self) -> None:
        from income_desk.adapters.ibkr_adapter import IBKRMarketData  # noqa: F401

    def test_provider_name(self) -> None:
        from income_desk.adapters.ibkr_adapter import IBKRMarketData

        md = IBKRMarketData.__new__(IBKRMarketData)
        assert md.provider_name == "ibkr"

    def test_get_option_chain_raises_not_implemented(self) -> None:
        from income_desk.adapters.ibkr_adapter import IBKRMarketData

        md = IBKRMarketData.__new__(IBKRMarketData)
        md._ib = object()  # bypass connect
        with pytest.raises((NotImplementedError, ImportError, ConnectionError)):
            md.get_option_chain("SPY")

    def test_get_quotes_raises_not_implemented(self) -> None:
        from income_desk.adapters.ibkr_adapter import IBKRMarketData

        md = IBKRMarketData.__new__(IBKRMarketData)
        md._ib = object()
        with pytest.raises((NotImplementedError, ImportError, ConnectionError)):
            md.get_quotes([], ticker="SPY")


class TestSchwabAdapterSkeleton:
    def test_importable(self) -> None:
        from income_desk.adapters.schwab_adapter import SchwabMarketData  # noqa: F401

    def test_provider_name(self) -> None:
        from income_desk.adapters.schwab_adapter import SchwabMarketData

        md = SchwabMarketData.__new__(SchwabMarketData)
        assert md.provider_name == "schwab"

    def test_get_option_chain_raises_not_implemented(self) -> None:
        from income_desk.adapters.schwab_adapter import SchwabMarketData

        md = SchwabMarketData.__new__(SchwabMarketData)
        md._client = object()  # bypass connect
        with pytest.raises((NotImplementedError, ImportError, ConnectionError)):
            md.get_option_chain("SPY")

    def test_occ_symbol_format(self) -> None:
        from income_desk.adapters.schwab_adapter import SchwabMarketData

        leg = _make_leg(580.0, "call", date(2026, 4, 24))
        occ = SchwabMarketData._to_occ("SPY", leg)
        # SPY padded to 6 chars + YYMMDD + C/P + 8-digit strike*1000
        assert occ.startswith("SPY")
        assert "260424" in occ
        assert "C" in occ
        assert "580000" in occ


# ---------------------------------------------------------------------------
# Integration: CSV + DataService + MarketAnalyzer → regime detection
# ---------------------------------------------------------------------------

class TestIntegrationWithMA:
    def test_csv_provider_with_market_analyzer(self, tmp_path: Path) -> None:
        """Full integration: CSV -> DataService -> MarketAnalyzer -> regime."""
        dates = pd.bdate_range("2024-01-02", periods=200)
        rng = np.random.default_rng(42)
        prices = 100 + np.cumsum(rng.standard_normal(200) * 0.5)
        df = pd.DataFrame(
            {
                "Open":   prices,
                "High":   prices + 1,
                "Low":    prices - 1,
                "Close":  prices + rng.standard_normal(200) * 0.3,
                "Volume": rng.integers(1_000_000, 5_000_000, 200),
            },
            index=dates,
        )
        df.to_csv(tmp_path / "CSVTEST.csv")

        from income_desk import MarketAnalyzer, DataService
        from income_desk.adapters.csv_provider import CSVProvider

        ds = DataService()
        ds._registry.register_priority(CSVProvider(tmp_path))
        ma = MarketAnalyzer(data_service=ds)

        regime = ma.regime.detect("CSVTEST")
        assert regime.regime.value in (1, 2, 3, 4)
        assert regime.confidence > 0

    def test_dict_quotes_provider_wired_into_ma(self) -> None:
        """DictQuoteProvider wires into MarketAnalyzer.quotes correctly."""
        from income_desk import MarketAnalyzer, DataService
        from income_desk.adapters.dict_quotes import DictQuoteProvider

        quotes = {
            ("SPY", 570.0, "put", "2026-04-24"): {"bid": 1.20, "ask": 1.35, "iv": 0.22},
        }
        provider = DictQuoteProvider(quotes, underlying_prices={"SPY": 580.0})
        ma = MarketAnalyzer(data_service=DataService(), market_data=provider)

        assert ma.quotes.has_broker is True
        assert ma.quotes.source == "dict"

    def test_dict_metrics_provider_wired_into_ma(self) -> None:
        """DictMetricsProvider wires into MarketAnalyzer.quotes metrics."""
        from income_desk import MarketAnalyzer, DataService
        from income_desk.adapters.dict_quotes import DictMetricsProvider

        metrics = {"SPY": {"iv_rank": 43.0, "iv_percentile": 91.0}}
        provider = DictMetricsProvider(metrics)
        ma = MarketAnalyzer(data_service=DataService(), market_metrics=provider)

        result = ma.quotes.get_metrics("SPY")
        assert result is not None
        assert result.iv_rank == 43.0
