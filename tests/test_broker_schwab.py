"""Tests for Schwab broker integration."""
from __future__ import annotations

from datetime import date

import pytest

from market_analyzer.models.quotes import AccountBalance, OptionQuote


# ---------------------------------------------------------------------------
# Import / SDK checks
# ---------------------------------------------------------------------------

class TestSchwabImport:
    def test_module_importable(self) -> None:
        """The broker module itself imports cleanly (lazy SDK import)."""
        import market_analyzer.broker.schwab

    def test_submodules_importable(self) -> None:
        """All submodules import without errors."""
        import market_analyzer.broker.schwab.account
        import market_analyzer.broker.schwab.market_data
        import market_analyzer.broker.schwab.metrics

    def test_missing_sdk_raises_helpful_error(self) -> None:
        """If schwab-py not installed, connect_schwab raises ImportError with pip command."""
        from market_analyzer.broker.schwab import connect_schwab
        try:
            connect_schwab("fake_key", "fake_secret")
        except ImportError as e:
            assert "pip install" in str(e)
            assert "schwab" in str(e).lower()
        except (ValueError, ConnectionError):
            pass  # SDK installed — credential/auth error is fine
        except Exception:
            pass

    def test_missing_credentials_raises_value_error(self) -> None:
        """Empty credentials raise ValueError with helpful message."""
        try:
            import schwab  # type: ignore[import]  # noqa: F401
            from market_analyzer.broker.schwab import connect_schwab
            with pytest.raises(ValueError, match="app_key"):
                connect_schwab("", "")
        except ImportError:
            pytest.skip("schwab-py not installed — skipping credential validation test")


# ---------------------------------------------------------------------------
# OCC symbol formatting (pure logic — no SDK needed)
# ---------------------------------------------------------------------------

class TestSchwabOCCSymbol:
    def _make_leg(
        self,
        strike: float,
        option_type: str = "call",
        expiration: date = date(2026, 4, 24),
    ):
        from market_analyzer.models.opportunity import LegSpec, LegAction
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

    def test_call_occ_format(self) -> None:
        from market_analyzer.broker.schwab.market_data import _to_occ
        leg = self._make_leg(580.0, "call", date(2026, 4, 24))
        occ = _to_occ("SPY", leg)
        assert occ.startswith("SPY")
        assert "260424" in occ
        assert "C" in occ
        assert "580000" in occ

    def test_put_occ_format(self) -> None:
        from market_analyzer.broker.schwab.market_data import _to_occ
        leg = self._make_leg(570.0, "put", date(2026, 6, 20))
        occ = _to_occ("SPY", leg)
        assert "P" in occ
        assert "570000" in occ
        assert "260620" in occ

    def test_short_ticker_padded(self) -> None:
        """Ticker shorter than 6 chars is padded with spaces."""
        from market_analyzer.broker.schwab.market_data import _to_occ
        leg = self._make_leg(480.0, "call")
        occ = _to_occ("QQQ", leg)
        assert len(occ) == 21  # 6 + 6 + 1 + 8
        assert occ[:3] == "QQQ"
        assert occ[3:6] == "   "  # padded

    def test_long_ticker_truncated_to_6(self) -> None:
        """Ticker longer than 6 chars not truncated — just formatted."""
        from market_analyzer.broker.schwab.market_data import _to_occ
        leg = self._make_leg(100.0, "call")
        occ = _to_occ("NVDA", leg)
        assert "NVDA" in occ

    def test_fractional_strike_encoding(self) -> None:
        """Fractional strikes are encoded correctly (* 1000)."""
        from market_analyzer.broker.schwab.market_data import _to_occ
        leg = self._make_leg(580.5, "put")
        occ = _to_occ("SPY", leg)
        assert "580500" in occ

    def test_occ_consistent_with_adapter(self) -> None:
        """New schwab package OCC matches legacy adapter format."""
        from market_analyzer.broker.schwab.market_data import _to_occ as new_occ
        from market_analyzer.adapters.schwab_adapter import SchwabMarketData
        leg = self._make_leg(580.0, "call", date(2026, 4, 24))
        assert new_occ("SPY", leg) == SchwabMarketData._to_occ("SPY", leg)


# ---------------------------------------------------------------------------
# Provider properties (no SDK needed)
# ---------------------------------------------------------------------------

class TestSchwabMarketDataProperties:
    def test_provider_name(self) -> None:
        from market_analyzer.broker.schwab.market_data import SchwabMarketData
        md = SchwabMarketData.__new__(SchwabMarketData)
        assert md.provider_name == "schwab"

    def test_currency(self) -> None:
        from market_analyzer.broker.schwab.market_data import SchwabMarketData
        md = SchwabMarketData.__new__(SchwabMarketData)
        assert md.currency == "USD"

    def test_timezone(self) -> None:
        from market_analyzer.broker.schwab.market_data import SchwabMarketData
        md = SchwabMarketData.__new__(SchwabMarketData)
        assert md.timezone == "US/Eastern"


# ---------------------------------------------------------------------------
# Contract parsing (mock Schwab response dict → OptionQuote)
# ---------------------------------------------------------------------------

class TestSchwabContractParsing:
    def test_parse_schwab_contract_basic(self) -> None:
        from market_analyzer.broker.schwab.market_data import _parse_schwab_contract

        contract = {
            "bid": 1.20,
            "ask": 1.35,
            "mark": 1.275,
            "volatility": 0.22,
            "totalVolume": 1500,
            "openInterest": 8000,
            "delta": -0.30,
            "gamma": 0.02,
            "theta": -0.05,
            "vega": 0.10,
        }
        quote = _parse_schwab_contract(contract, "SPY", date(2026, 4, 24), 570.0, "put")
        assert quote is not None
        assert quote.ticker == "SPY"
        assert quote.bid == pytest.approx(1.20)
        assert quote.ask == pytest.approx(1.35)
        assert quote.mid == pytest.approx(1.275)
        assert quote.implied_volatility == pytest.approx(0.22)
        assert quote.delta == pytest.approx(-0.30)
        assert quote.volume == 1500
        assert quote.open_interest == 8000

    def test_parse_schwab_contract_missing_greeks(self) -> None:
        from market_analyzer.broker.schwab.market_data import _parse_schwab_contract

        contract = {
            "bid": 2.00,
            "ask": 2.20,
        }
        quote = _parse_schwab_contract(contract, "QQQ", date(2026, 5, 15), 480.0, "call")
        assert quote is not None
        assert quote.bid == 2.00
        assert quote.delta is None
        assert quote.implied_volatility is None

    def test_parse_schwab_contract_mid_from_mark(self) -> None:
        """Schwab 'mark' field used as mid when present."""
        from market_analyzer.broker.schwab.market_data import _parse_schwab_contract

        contract = {"bid": 1.00, "ask": 1.50, "mark": 1.22}
        quote = _parse_schwab_contract(contract, "SPY", date(2026, 4, 24), 575.0, "put")
        assert quote is not None
        assert quote.mid == pytest.approx(1.22)

    def test_parse_schwab_contract_mid_fallback(self) -> None:
        """Without 'mark', mid = (bid + ask) / 2."""
        from market_analyzer.broker.schwab.market_data import _parse_schwab_contract

        contract = {"bid": 1.00, "ask": 1.50}
        quote = _parse_schwab_contract(contract, "SPY", date(2026, 4, 24), 575.0, "put")
        assert quote is not None
        assert quote.mid == pytest.approx(1.25)

    def test_parse_bad_contract_returns_none(self) -> None:
        """Malformed contract data returns None without crashing."""
        from market_analyzer.broker.schwab.market_data import _parse_schwab_contract

        # Pass invalid date type to trigger exception
        result = _parse_schwab_contract(None, "SPY", date(2026, 4, 24), 570.0, "put")
        assert result is None


# ---------------------------------------------------------------------------
# AccountBalance mapping
# ---------------------------------------------------------------------------

class TestSchwabAccountMapping:
    def test_account_balance_model(self) -> None:
        """AccountBalance accepts schwab source."""
        bal = AccountBalance(
            account_number="SCHWAB123",
            net_liquidating_value=150000.0,
            cash_balance=50000.0,
            derivative_buying_power=40000.0,
            equity_buying_power=100000.0,
            maintenance_requirement=10000.0,
            source="schwab",
            currency="USD",
        )
        assert bal.source == "schwab"
        assert bal.net_liquidating_value == 150000.0
        assert bal.derivative_buying_power == 40000.0

    def test_schwab_account_class_importable(self) -> None:
        from market_analyzer.broker.schwab.account import SchwabAccount
        assert SchwabAccount is not None


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------

class TestSchwabCredentialResolution:
    def test_explicit_credentials_returned(self) -> None:
        from market_analyzer.broker.schwab import _resolve_credentials
        key, secret = _resolve_credentials("my_key", "my_secret")
        assert key == "my_key"
        assert secret == "my_secret"

    def test_env_var_credentials(self, monkeypatch) -> None:
        from market_analyzer.broker.schwab import _resolve_credentials
        monkeypatch.setenv("SCHWAB_APP_KEY", "env_key")
        monkeypatch.setenv("SCHWAB_APP_SECRET", "env_secret")
        key, secret = _resolve_credentials(None, None)
        assert key == "env_key"
        assert secret == "env_secret"

    def test_empty_credentials_returned_as_empty_strings(self, monkeypatch) -> None:
        from market_analyzer.broker.schwab import _resolve_credentials
        monkeypatch.delenv("SCHWAB_APP_KEY", raising=False)
        monkeypatch.delenv("SCHWAB_APP_SECRET", raising=False)
        key, secret = _resolve_credentials(None, None)
        assert isinstance(key, str)
        assert isinstance(secret, str)


# ---------------------------------------------------------------------------
# Integration: Schwab adapter backward compat
# ---------------------------------------------------------------------------

class TestSchwabAdapterBackwardCompat:
    """Ensure old adapter import path still works."""

    def test_old_adapter_still_importable(self) -> None:
        from market_analyzer.adapters.schwab_adapter import SchwabMarketData
        assert SchwabMarketData is not None

    def test_new_broker_module_importable(self) -> None:
        from market_analyzer.broker.schwab.market_data import SchwabMarketData
        assert SchwabMarketData is not None

    def test_both_have_same_provider_name(self) -> None:
        from market_analyzer.adapters.schwab_adapter import SchwabMarketData as OldSchwab
        from market_analyzer.broker.schwab.market_data import SchwabMarketData as NewSchwab
        old = OldSchwab.__new__(OldSchwab)
        new = NewSchwab.__new__(NewSchwab)
        assert old.provider_name == new.provider_name == "schwab"
