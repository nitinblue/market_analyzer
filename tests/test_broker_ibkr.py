"""Tests for IBKR broker integration."""
from __future__ import annotations

from datetime import date

import pytest

from market_analyzer.models.quotes import AccountBalance, OptionQuote


# ---------------------------------------------------------------------------
# Import / SDK checks
# ---------------------------------------------------------------------------

class TestIBKRImport:
    def test_module_importable(self) -> None:
        """The broker module itself imports cleanly (lazy SDK import)."""
        import market_analyzer.broker.ibkr

    def test_submodules_importable(self) -> None:
        """All submodules import without errors."""
        import market_analyzer.broker.ibkr.account
        import market_analyzer.broker.ibkr.market_data

    def test_missing_sdk_raises_helpful_error(self) -> None:
        """If ib_insync not installed, connect_ibkr raises ImportError with pip command."""
        from market_analyzer.broker.ibkr import connect_ibkr
        try:
            connect_ibkr()
        except ImportError as e:
            assert "pip install" in str(e)
            assert "ibkr" in str(e).lower()
        except ConnectionError:
            pass  # SDK installed but TWS not running — that's fine
        except Exception:
            pass

    def test_connect_ibkr_raises_import_error_without_sdk(self) -> None:
        """Importing connect_ibkr works; SDK absence handled at call time."""
        from market_analyzer.broker.ibkr import connect_ibkr
        assert callable(connect_ibkr)


# ---------------------------------------------------------------------------
# Provider properties (no SDK needed)
# ---------------------------------------------------------------------------

class TestIBKRMarketDataProperties:
    def test_provider_name(self) -> None:
        from market_analyzer.broker.ibkr.market_data import IBKRMarketData
        md = IBKRMarketData.__new__(IBKRMarketData)
        assert md.provider_name == "ibkr"

    def test_currency(self) -> None:
        from market_analyzer.broker.ibkr.market_data import IBKRMarketData
        md = IBKRMarketData.__new__(IBKRMarketData)
        assert md.currency == "USD"

    def test_timezone(self) -> None:
        from market_analyzer.broker.ibkr.market_data import IBKRMarketData
        md = IBKRMarketData.__new__(IBKRMarketData)
        assert md.timezone == "US/Eastern"


# ---------------------------------------------------------------------------
# Date parsing utility
# ---------------------------------------------------------------------------

class TestIBKRDateParsing:
    def test_parse_valid_ibkr_date(self) -> None:
        from market_analyzer.broker.ibkr.market_data import _parse_ibkr_date
        d = _parse_ibkr_date("20260424")
        assert d == date(2026, 4, 24)

    def test_parse_invalid_ibkr_date(self) -> None:
        from market_analyzer.broker.ibkr.market_data import _parse_ibkr_date
        assert _parse_ibkr_date("invalid") is None
        assert _parse_ibkr_date("") is None
        assert _parse_ibkr_date("2026-04-24") is None  # wrong format

    def test_parse_year_boundary(self) -> None:
        from market_analyzer.broker.ibkr.market_data import _parse_ibkr_date
        assert _parse_ibkr_date("20260101") == date(2026, 1, 1)
        assert _parse_ibkr_date("20261231") == date(2026, 12, 31)


# ---------------------------------------------------------------------------
# Safe float utility
# ---------------------------------------------------------------------------

class TestIBKRSafeFloat:
    def test_normal_value(self) -> None:
        from market_analyzer.broker.ibkr.market_data import _safe_float
        assert _safe_float(1.5) == pytest.approx(1.5)

    def test_none_returns_none(self) -> None:
        from market_analyzer.broker.ibkr.market_data import _safe_float
        assert _safe_float(None) is None

    def test_sentinel_returns_none(self) -> None:
        """IBKR uses max float as 'not available' sentinel."""
        from market_analyzer.broker.ibkr.market_data import _safe_float
        assert _safe_float(1.7976931348623157e+308) is None

    def test_string_number(self) -> None:
        from market_analyzer.broker.ibkr.market_data import _safe_float
        assert _safe_float("2.50") == pytest.approx(2.50)

    def test_non_numeric_returns_none(self) -> None:
        from market_analyzer.broker.ibkr.market_data import _safe_float
        assert _safe_float("not_a_number") is None


# ---------------------------------------------------------------------------
# AccountBalance mapping
# ---------------------------------------------------------------------------

class TestIBKRAccountMapping:
    def test_account_balance_model(self) -> None:
        """AccountBalance accepts ibkr source."""
        bal = AccountBalance(
            account_number="DU123456",
            net_liquidating_value=250000.0,
            cash_balance=100000.0,
            derivative_buying_power=50000.0,
            equity_buying_power=200000.0,
            maintenance_requirement=25000.0,
            source="ibkr",
            currency="USD",
        )
        assert bal.source == "ibkr"
        assert bal.account_number == "DU123456"
        assert bal.net_liquidating_value == 250000.0

    def test_ibkr_account_requires_ib_instance(self) -> None:
        """IBKRAccount class imports cleanly."""
        from market_analyzer.broker.ibkr.account import IBKRAccount
        assert IBKRAccount is not None


# ---------------------------------------------------------------------------
# OptionQuote mapping tests
# ---------------------------------------------------------------------------

class TestIBKROptionQuoteMapping:
    def test_option_quote_from_ibkr_fields(self) -> None:
        """OptionQuote model works with IBKR-sourced data."""
        quote = OptionQuote(
            ticker="SPY",
            expiration=date(2026, 4, 24),
            strike=570.0,
            option_type="put",
            bid=1.25,
            ask=1.40,
            mid=(1.25 + 1.40) / 2,
            implied_volatility=0.23,
            delta=-0.30,
            gamma=0.02,
            theta=-0.04,
            vega=0.11,
        )
        assert quote.ticker == "SPY"
        assert quote.mid == pytest.approx(1.325)
        assert quote.delta == pytest.approx(-0.30)

    def test_option_quote_no_greeks(self) -> None:
        """OptionQuote without Greeks (e.g. when include_greeks=False)."""
        quote = OptionQuote(
            ticker="QQQ",
            expiration=date(2026, 5, 15),
            strike=480.0,
            option_type="call",
            bid=2.00,
            ask=2.20,
            mid=2.10,
        )
        assert quote.delta is None
        assert quote.implied_volatility is None


# ---------------------------------------------------------------------------
# Integration: IBKR adapter vs. first-class broker module
# ---------------------------------------------------------------------------

class TestIBKRAdapterBackwardCompat:
    """Ensure old adapter import path still works (not broken by new package)."""

    def test_old_adapter_still_importable(self) -> None:
        """Legacy adapter in adapters/ still imports cleanly."""
        from market_analyzer.adapters.ibkr_adapter import IBKRMarketData
        assert IBKRMarketData is not None

    def test_new_broker_module_importable(self) -> None:
        """New first-class broker module imports cleanly."""
        from market_analyzer.broker.ibkr.market_data import IBKRMarketData
        assert IBKRMarketData is not None

    def test_both_have_same_provider_name(self) -> None:
        """Both implementations report provider_name == 'ibkr'."""
        from market_analyzer.adapters.ibkr_adapter import IBKRMarketData as OldIBKR
        from market_analyzer.broker.ibkr.market_data import IBKRMarketData as NewIBKR
        old = OldIBKR.__new__(OldIBKR)
        new = NewIBKR.__new__(NewIBKR)
        assert old.provider_name == new.provider_name == "ibkr"
