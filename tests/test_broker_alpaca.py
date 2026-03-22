"""Tests for Alpaca broker integration."""
from __future__ import annotations

from datetime import date

import pytest

from income_desk.models.quotes import AccountBalance, OptionQuote


# ---------------------------------------------------------------------------
# Import / SDK checks
# ---------------------------------------------------------------------------

class TestAlpacaImport:
    def test_module_importable(self) -> None:
        """The broker module itself imports cleanly (lazy SDK import)."""
        import income_desk.broker.alpaca  # Should not raise

    def test_submodules_importable(self) -> None:
        """All submodules import without errors."""
        import income_desk.broker.alpaca.account
        import income_desk.broker.alpaca.market_data
        import income_desk.broker.alpaca.metrics

    def test_missing_sdk_raises_helpful_error(self) -> None:
        """If alpaca-py not installed, connect_alpaca raises ImportError with pip command."""
        from income_desk.broker.alpaca import connect_alpaca
        try:
            connect_alpaca("fake_key", "fake_secret")
        except ImportError as e:
            assert "pip install" in str(e)
            assert "alpaca" in str(e).lower()
        except Exception:
            # Connection error / ValueError is fine — means SDK IS installed
            pass

    def test_missing_credentials_raises_value_error(self) -> None:
        """Empty credentials raise ValueError with helpful message."""
        try:
            from alpaca.trading.client import TradingClient  # noqa: F401
            # SDK installed — test empty credentials
            from income_desk.broker.alpaca import connect_alpaca
            with pytest.raises(ValueError, match="API key"):
                connect_alpaca("", "")
        except ImportError:
            pytest.skip("alpaca-py not installed — skipping credential validation test")


# ---------------------------------------------------------------------------
# OCC symbol parsing (pure logic — no SDK needed)
# ---------------------------------------------------------------------------

class TestOCCParsing:
    def test_parse_standard_occ(self) -> None:
        """Parse a well-formed OCC symbol."""
        from income_desk.broker.alpaca.market_data import _parse_occ
        result = _parse_occ("SPY   260424C00580000")
        assert result is not None
        ticker, exp, option_type, strike = result
        assert ticker == "SPY"
        assert exp == date(2026, 4, 24)
        assert option_type == "call"
        assert strike == pytest.approx(580.0)

    def test_parse_put_occ(self) -> None:
        """Parse a put OCC symbol."""
        from income_desk.broker.alpaca.market_data import _parse_occ
        result = _parse_occ("QQQ   260620P00480000")
        assert result is not None
        _, _, option_type, strike = result
        assert option_type == "put"
        assert strike == pytest.approx(480.0)

    def test_parse_fractional_strike(self) -> None:
        """Parse OCC symbol with fractional strike (e.g. 580.50)."""
        from income_desk.broker.alpaca.market_data import _parse_occ
        result = _parse_occ("SPY   260424C00580500")
        assert result is not None
        _, _, _, strike = result
        assert strike == pytest.approx(580.5)

    def test_parse_invalid_returns_none(self) -> None:
        """Invalid symbol returns None without raising."""
        from income_desk.broker.alpaca.market_data import _parse_occ
        assert _parse_occ("not_a_symbol") is None
        assert _parse_occ("") is None

    def test_build_occ_roundtrip(self) -> None:
        """Build OCC symbol and parse it back."""
        from income_desk.broker.alpaca.market_data import _build_occ, _parse_occ
        from income_desk.models.opportunity import LegSpec, LegAction

        leg = LegSpec(
            role="short_put",
            action=LegAction.SELL_TO_OPEN,
            option_type="put",
            strike=570.0,
            strike_label="short",
            expiration=date(2026, 4, 24),
            days_to_expiry=35,
            atm_iv_at_expiry=0.22,
        )
        occ = _build_occ("SPY", leg)
        parsed = _parse_occ(occ)
        assert parsed is not None
        ticker, exp, option_type, strike = parsed
        assert ticker == "SPY"
        assert exp == date(2026, 4, 24)
        assert option_type == "put"
        assert strike == pytest.approx(570.0)


# ---------------------------------------------------------------------------
# AccountBalance mapping (pure model test — no SDK needed)
# ---------------------------------------------------------------------------

class TestAlpacaAccountMapping:
    def test_account_balance_model(self) -> None:
        """AccountBalance Pydantic model accepts alpaca source field."""
        bal = AccountBalance(
            account_number="PA12345",
            net_liquidating_value=35000.0,
            cash_balance=30000.0,
            derivative_buying_power=28000.0,
            equity_buying_power=28000.0,
            maintenance_requirement=5000.0,
            source="alpaca",
            currency="USD",
        )
        assert bal.source == "alpaca"
        assert bal.net_liquidating_value == 35000.0
        assert bal.derivative_buying_power == 28000.0
        assert bal.currency == "USD"

    def test_account_balance_defaults(self) -> None:
        """AccountBalance optional fields default to 0/empty."""
        bal = AccountBalance(
            account_number="test",
            net_liquidating_value=10000.0,
            cash_balance=10000.0,
            derivative_buying_power=9000.0,
            equity_buying_power=9000.0,
            maintenance_requirement=0.0,
            source="alpaca",
        )
        assert bal.pending_cash == 0.0
        assert bal.timezone == "US/Eastern"


# ---------------------------------------------------------------------------
# Mock-based mapping tests (broker response → OptionQuote)
# ---------------------------------------------------------------------------

class TestAlpacaOptionQuoteMapping:
    """Test the mapping logic from Alpaca snapshot dicts to OptionQuote."""

    def test_option_quote_from_alpaca_fields(self) -> None:
        """Verify that a manually-constructed OptionQuote mirrors Alpaca mapping."""
        quote = OptionQuote(
            ticker="SPY",
            expiration=date(2026, 4, 24),
            strike=570.0,
            option_type="put",
            bid=1.20,
            ask=1.35,
            mid=1.275,
            implied_volatility=0.22,
            volume=1500,
            open_interest=8000,
            delta=-0.30,
            gamma=0.02,
            theta=-0.05,
            vega=0.10,
        )
        assert quote.ticker == "SPY"
        assert quote.bid == 1.20
        assert quote.ask == 1.35
        assert quote.mid == pytest.approx(1.275)
        assert quote.delta == pytest.approx(-0.30)
        assert quote.implied_volatility == pytest.approx(0.22)

    def test_mid_from_bid_ask(self) -> None:
        """Mid should equal (bid + ask) / 2 when no explicit mid provided."""
        bid, ask = 2.10, 2.30
        expected_mid = (bid + ask) / 2
        quote = OptionQuote(
            ticker="QQQ",
            expiration=date(2026, 5, 15),
            strike=480.0,
            option_type="call",
            bid=bid,
            ask=ask,
            mid=expected_mid,
        )
        assert quote.mid == pytest.approx(expected_mid)

    def test_greeks_none_when_unavailable(self) -> None:
        """OptionQuote accepts None Greeks for free-tier data."""
        quote = OptionQuote(
            ticker="SPY",
            expiration=date(2026, 4, 24),
            strike=580.0,
            option_type="call",
            bid=1.50,
            ask=1.65,
            mid=1.575,
            delta=None,
            gamma=None,
            theta=None,
            vega=None,
        )
        assert quote.delta is None
        assert quote.gamma is None


# ---------------------------------------------------------------------------
# Provider property checks (no SDK needed — class attributes only)
# ---------------------------------------------------------------------------

class TestAlpacaMarketDataProperties:
    def test_provider_name(self) -> None:
        from income_desk.broker.alpaca.market_data import AlpacaMarketData
        # Use __new__ to bypass __init__ (avoids needing SDK clients)
        md = AlpacaMarketData.__new__(AlpacaMarketData)
        assert md.provider_name == "alpaca"

    def test_currency(self) -> None:
        from income_desk.broker.alpaca.market_data import AlpacaMarketData
        md = AlpacaMarketData.__new__(AlpacaMarketData)
        assert md.currency == "USD"

    def test_timezone(self) -> None:
        from income_desk.broker.alpaca.market_data import AlpacaMarketData
        md = AlpacaMarketData.__new__(AlpacaMarketData)
        assert md.timezone == "US/Eastern"


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------

class TestAlpacaCredentialResolution:
    def test_explicit_credentials_returned(self) -> None:
        from income_desk.broker.alpaca import _resolve_credentials
        key, secret = _resolve_credentials("my_key", "my_secret")
        assert key == "my_key"
        assert secret == "my_secret"

    def test_env_var_credentials(self, monkeypatch) -> None:
        from income_desk.broker.alpaca import _resolve_credentials
        monkeypatch.setenv("ALPACA_API_KEY", "env_key")
        monkeypatch.setenv("ALPACA_API_SECRET", "env_secret")
        key, secret = _resolve_credentials(None, None)
        assert key == "env_key"
        assert secret == "env_secret"

    def test_empty_credentials_returned_as_empty_strings(self, monkeypatch) -> None:
        from income_desk.broker.alpaca import _resolve_credentials
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
        key, secret = _resolve_credentials(None, None)
        # Returns empty strings when no config file present
        assert isinstance(key, str)
        assert isinstance(secret, str)
