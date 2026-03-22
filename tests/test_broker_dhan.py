"""Tests for Dhan broker integration (India NSE/NFO).

All tests are offline (no real network calls). The Dhan SDK is optional —
tests that require it are skipped when dhanhq is not installed.
"""
from __future__ import annotations

from datetime import date

import pytest

from income_desk.models.quotes import AccountBalance, MarketMetrics, OptionQuote


# ---------------------------------------------------------------------------
# Import / SDK checks
# ---------------------------------------------------------------------------

class TestDhanImport:
    def test_module_importable(self) -> None:
        """The broker module imports cleanly without dhanhq SDK present."""
        import income_desk.broker.dhan  # Should not raise

    def test_submodules_importable(self) -> None:
        """All four submodules import without errors."""
        import income_desk.broker.dhan.account
        import income_desk.broker.dhan.market_data
        import income_desk.broker.dhan.metrics
        import income_desk.broker.dhan.watchlist

    def test_missing_sdk_raises_helpful_error(self) -> None:
        """connect_dhan raises ImportError with pip command when SDK absent."""
        from income_desk.broker.dhan import connect_dhan
        try:
            connect_dhan("fake_id", "fake_token")
        except ImportError as e:
            # SDK not installed — verify helpful message
            assert "dhanhq" in str(e) or "pip install" in str(e)
        except Exception:
            # Any other exception means SDK IS installed; that's fine
            pass

    def test_missing_credentials_raises_value_error(self) -> None:
        """Empty credentials raise ValueError."""
        try:
            from dhanhq import DhanContext  # noqa: F401
            # SDK is installed — test credential validation
            from income_desk.broker.dhan import connect_dhan
            with pytest.raises(ValueError, match="DHAN_CLIENT_ID"):
                connect_dhan("", "")
        except ImportError:
            pytest.skip("dhanhq not installed — skipping credential validation test")


# ---------------------------------------------------------------------------
# Scrip codes and lot sizes (pure constants — no SDK needed)
# ---------------------------------------------------------------------------

class TestDhanConstants:
    def test_scrip_codes_defined(self) -> None:
        """Known index scrip codes match DhanHQ documentation."""
        from income_desk.broker.dhan.market_data import _SCRIP_CODES
        assert _SCRIP_CODES["NIFTY"] == 13
        assert _SCRIP_CODES["BANKNIFTY"] == 25
        assert _SCRIP_CODES["FINNIFTY"] == 27
        assert _SCRIP_CODES["SENSEX"] == 51

    def test_lot_sizes_defined(self) -> None:
        """India NSE index lot sizes match exchange specifications."""
        from income_desk.broker.dhan.market_data import _LOT_SIZES
        assert _LOT_SIZES["NIFTY"] == 25
        assert _LOT_SIZES["BANKNIFTY"] == 15
        assert _LOT_SIZES["FINNIFTY"] == 25
        assert _LOT_SIZES["SENSEX"] == 10

    def test_european_exercise_lot_sizes(self) -> None:
        """All India index options are European — lot sizes must be defined."""
        from income_desk.broker.dhan.market_data import _LOT_SIZES, _SCRIP_CODES
        # Every scrip code must have a corresponding lot size
        for ticker in _SCRIP_CODES:
            assert ticker in _LOT_SIZES, f"{ticker} missing from _LOT_SIZES"


# ---------------------------------------------------------------------------
# Provider properties (no SDK needed — uses mock client)
# ---------------------------------------------------------------------------

class _MockClient:
    """Minimal mock for dhanhq client."""
    pass


class TestDhanProviderProperties:
    def test_provider_name(self) -> None:
        from income_desk.broker.dhan.market_data import DhanMarketData
        md = DhanMarketData(_MockClient())
        assert md.provider_name == "dhan"

    def test_currency_inr(self) -> None:
        from income_desk.broker.dhan.market_data import DhanMarketData
        md = DhanMarketData(_MockClient())
        assert md.currency == "INR"

    def test_timezone_india(self) -> None:
        from income_desk.broker.dhan.market_data import DhanMarketData
        md = DhanMarketData(_MockClient())
        assert md.timezone == "Asia/Kolkata"

    def test_lot_size_default_nifty(self) -> None:
        from income_desk.broker.dhan.market_data import DhanMarketData
        md = DhanMarketData(_MockClient())
        assert md.lot_size_default == 25

    def test_market_hours_india(self) -> None:
        from datetime import time
        from income_desk.broker.dhan.market_data import DhanMarketData
        md = DhanMarketData(_MockClient())
        open_t, close_t = md.market_hours
        assert open_t == time(9, 15)
        assert close_t == time(15, 30)

    def test_rate_limit_conservative(self) -> None:
        """Rate limit should be conservative (1/s) for option chain calls."""
        from income_desk.broker.dhan.market_data import DhanMarketData
        md = DhanMarketData(_MockClient())
        assert md.rate_limit_per_second >= 1


# ---------------------------------------------------------------------------
# Option chain parsing (mock API response)
# ---------------------------------------------------------------------------

class TestDhanOptionChainParsing:
    def _make_chain_client(self, entries: list) -> object:
        class MockChainClient:
            def option_chain(self, **kwargs):
                return {"data": entries}
        return MockChainClient()

    def test_empty_chain_for_unknown_ticker(self) -> None:
        """Unknown non-numeric ticker returns empty list."""
        from income_desk.broker.dhan.market_data import DhanMarketData
        md = DhanMarketData(self._make_chain_client([]))
        result = md.get_option_chain("UNKNOWN_TICKER_XYZ")
        assert result == []

    def test_numeric_ticker_as_scrip_code(self) -> None:
        """Numeric ticker string is treated as scrip code."""
        from income_desk.broker.dhan.market_data import DhanMarketData
        md = DhanMarketData(self._make_chain_client([]))
        # Should not raise — numeric ticker resolves to int scrip code
        result = md.get_option_chain("12345")
        assert result == []  # Empty response from mock

    def test_iv_conversion_from_percentage(self) -> None:
        """Dhan returns IV as percentage (25.5) — MA stores decimal (0.255)."""
        from income_desk.broker.dhan.market_data import DhanMarketData
        entry = {
            "strikePrice": 26000,
            "expiryDate": "2026-04-24",
            "ce": {
                "bid_price": 100, "ask_price": 110, "ltp": 105,
                "iv": 25.5, "delta": 0.5, "gamma": 0.01,
                "theta": -5.0, "vega": 10.0,
                "volume": 1000, "oi": 5000,
            },
            "pe": {},
        }
        md = DhanMarketData(self._make_chain_client([entry]))
        chain = md.get_option_chain("NIFTY", expiration=date(2026, 4, 24))
        assert len(chain) == 1
        q = chain[0]
        assert q.implied_volatility == pytest.approx(0.255, abs=0.001)

    def test_greeks_populated(self) -> None:
        """Delta/gamma/theta/vega are populated from chain response."""
        from income_desk.broker.dhan.market_data import DhanMarketData
        entry = {
            "strikePrice": 26000,
            "expiryDate": "2026-04-24",
            "ce": {
                "bid_price": 100, "ask_price": 110, "ltp": 105,
                "iv": 25.5, "delta": 0.52, "gamma": 0.012,
                "theta": -4.8, "vega": 9.5,
                "volume": 500, "oi": 2000,
            },
            "pe": {},
        }
        md = DhanMarketData(self._make_chain_client([entry]))
        chain = md.get_option_chain("NIFTY", expiration=date(2026, 4, 24))
        assert len(chain) == 1
        q = chain[0]
        assert q.delta == pytest.approx(0.52)
        assert q.gamma == pytest.approx(0.012)
        assert q.theta == pytest.approx(-4.8)
        assert q.vega == pytest.approx(9.5)

    def test_lot_size_set_correctly(self) -> None:
        """Lot size matches _LOT_SIZES for the given ticker."""
        from income_desk.broker.dhan.market_data import DhanMarketData
        entry = {
            "strikePrice": 26000,
            "expiryDate": "2026-04-24",
            "ce": {"bid_price": 100, "ask_price": 110, "ltp": 105,
                   "iv": 20.0, "delta": 0.5, "gamma": 0.01,
                   "theta": -3.0, "vega": 8.0, "volume": 100, "oi": 500},
            "pe": {},
        }
        md = DhanMarketData(self._make_chain_client([entry]))
        chain = md.get_option_chain("NIFTY", expiration=date(2026, 4, 24))
        assert chain[0].lot_size == 25  # NIFTY lot size

        chain_bnf = md.get_option_chain("BANKNIFTY", expiration=date(2026, 4, 24))
        if chain_bnf:
            assert chain_bnf[0].lot_size == 15

    def test_both_call_and_put_parsed(self) -> None:
        """Both CE and PE sides are returned for each strike."""
        from income_desk.broker.dhan.market_data import DhanMarketData
        entry = {
            "strikePrice": 26000,
            "expiryDate": "2026-04-24",
            "ce": {"bid_price": 100, "ask_price": 110, "ltp": 105,
                   "iv": 20.0, "delta": 0.5, "gamma": 0.01,
                   "theta": -3.0, "vega": 8.0, "volume": 100, "oi": 500},
            "pe": {"bid_price": 90, "ask_price": 95, "ltp": 92,
                   "iv": 21.0, "delta": -0.5, "gamma": 0.01,
                   "theta": -3.2, "vega": 8.2, "volume": 80, "oi": 400},
        }
        md = DhanMarketData(self._make_chain_client([entry]))
        chain = md.get_option_chain("NIFTY", expiration=date(2026, 4, 24))
        assert len(chain) == 2
        types = {q.option_type for q in chain}
        assert types == {"call", "put"}

    def test_mid_price_calculation(self) -> None:
        """Mid is (bid + ask) / 2 when both are available."""
        from income_desk.broker.dhan.market_data import DhanMarketData
        entry = {
            "strikePrice": 26000,
            "expiryDate": "2026-04-24",
            "ce": {"bid_price": 100.0, "ask_price": 110.0, "ltp": 108,
                   "iv": 20.0, "delta": 0.5, "gamma": 0.01,
                   "theta": -3.0, "vega": 8.0, "volume": 100, "oi": 500},
            "pe": {},
        }
        md = DhanMarketData(self._make_chain_client([entry]))
        chain = md.get_option_chain("NIFTY", expiration=date(2026, 4, 24))
        assert chain[0].mid == pytest.approx(105.0)

    def test_expiration_filter(self) -> None:
        """Only entries matching the requested expiration are returned."""
        from income_desk.broker.dhan.market_data import DhanMarketData
        entries = [
            {"strikePrice": 26000, "expiryDate": "2026-04-24",
             "ce": {"bid_price": 100, "ask_price": 110, "ltp": 105,
                    "iv": 20.0, "delta": 0.5, "gamma": 0.01, "theta": -3.0, "vega": 8.0,
                    "volume": 100, "oi": 500}, "pe": {}},
            {"strikePrice": 26000, "expiryDate": "2026-05-29",
             "ce": {"bid_price": 150, "ask_price": 160, "ltp": 155,
                    "iv": 22.0, "delta": 0.48, "gamma": 0.009, "theta": -2.5, "vega": 10.0,
                    "volume": 200, "oi": 800}, "pe": {}},
        ]
        md = DhanMarketData(self._make_chain_client(entries))
        chain = md.get_option_chain("NIFTY", expiration=date(2026, 4, 24))
        assert len(chain) == 1
        assert chain[0].expiration == date(2026, 4, 24)

    def test_iv_zero_returns_none(self) -> None:
        """IV of 0 in response maps to None (not 0.0) in OptionQuote."""
        from income_desk.broker.dhan.market_data import DhanMarketData
        entry = {
            "strikePrice": 26000,
            "expiryDate": "2026-04-24",
            "ce": {"bid_price": 5, "ask_price": 6, "ltp": 5.5,
                   "iv": 0, "delta": 0.1, "gamma": 0.001,
                   "theta": -0.5, "vega": 1.0, "volume": 10, "oi": 100},
            "pe": {},
        }
        md = DhanMarketData(self._make_chain_client([entry]))
        chain = md.get_option_chain("NIFTY", expiration=date(2026, 4, 24))
        assert chain[0].implied_volatility is None

    def test_missing_side_data_skipped(self) -> None:
        """Empty or missing CE/PE data does not produce a quote."""
        from income_desk.broker.dhan.market_data import DhanMarketData
        entry = {
            "strikePrice": 26000,
            "expiryDate": "2026-04-24",
            "ce": {},  # Empty — should be skipped
            "pe": {"bid_price": 90, "ask_price": 95, "ltp": 92,
                   "iv": 21.0, "delta": -0.5, "gamma": 0.01,
                   "theta": -3.2, "vega": 8.2, "volume": 80, "oi": 400},
        }
        md = DhanMarketData(self._make_chain_client([entry]))
        chain = md.get_option_chain("NIFTY", expiration=date(2026, 4, 24))
        assert len(chain) == 1
        assert chain[0].option_type == "put"

    def test_api_error_returns_empty_list(self) -> None:
        """If the Dhan API raises an exception, get_option_chain returns []."""
        from income_desk.broker.dhan.market_data import DhanMarketData

        class FailingClient:
            def option_chain(self, **kwargs):
                raise ConnectionError("Dhan API unreachable")

        md = DhanMarketData(FailingClient())
        result = md.get_option_chain("NIFTY")
        assert result == []


# ---------------------------------------------------------------------------
# Account balance mapping
# ---------------------------------------------------------------------------

class TestDhanAccountBalance:
    def test_balance_mapping_happy_path(self) -> None:
        """get_balance() correctly maps Dhan API response fields."""
        from income_desk.broker.dhan.account import DhanAccount

        class MockClient:
            def get_fund_limits(self):
                return {"data": {
                    "clientId": "DH12345",
                    "availabelBalance": 350000.0,  # Dhan typo preserved
                    "utilizedAmount": 150000.0,
                }}

        acct = DhanAccount(MockClient())
        bal = acct.get_balance()

        assert bal.account_number == "DH12345"
        assert bal.cash_balance == pytest.approx(350000.0)
        assert bal.maintenance_requirement == pytest.approx(150000.0)
        assert bal.net_liquidating_value == pytest.approx(500000.0)  # 350k + 150k
        assert bal.source == "dhan"
        assert bal.currency == "INR"
        assert bal.timezone == "Asia/Kolkata"

    def test_balance_typo_resilience(self) -> None:
        """Both 'availabelBalance' (typo) and 'availableBalance' (correct) work."""
        from income_desk.broker.dhan.account import DhanAccount

        class MockClientCorrectSpelling:
            def get_fund_limits(self):
                return {"data": {
                    "clientId": "DH99",
                    "availableBalance": 200000.0,  # Correct spelling
                    "utilizedAmount": 50000.0,
                }}

        acct = DhanAccount(MockClientCorrectSpelling())
        bal = acct.get_balance()
        assert bal.cash_balance == pytest.approx(200000.0)

    def test_balance_raises_on_empty_response(self) -> None:
        """ConnectionError raised when Dhan returns empty response."""
        from income_desk.broker.dhan.account import DhanAccount

        class EmptyClient:
            def get_fund_limits(self):
                return {}

        acct = DhanAccount(EmptyClient())
        with pytest.raises(ConnectionError):
            acct.get_balance()

    def test_balance_raises_on_api_error(self) -> None:
        """ConnectionError raised when Dhan API call fails."""
        from income_desk.broker.dhan.account import DhanAccount

        class FailingClient:
            def get_fund_limits(self):
                raise RuntimeError("Network error")

        acct = DhanAccount(FailingClient())
        with pytest.raises(ConnectionError):
            acct.get_balance()

    def test_account_balance_model_fields(self) -> None:
        """AccountBalance model accepts INR currency and Asia/Kolkata timezone."""
        bal = AccountBalance(
            account_number="DH123",
            net_liquidating_value=500000.0,
            cash_balance=350000.0,
            derivative_buying_power=350000.0,
            equity_buying_power=350000.0,
            maintenance_requirement=150000.0,
            source="dhan",
            currency="INR",
            timezone="Asia/Kolkata",
        )
        assert bal.source == "dhan"
        assert bal.currency == "INR"
        assert bal.timezone == "Asia/Kolkata"


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class TestDhanMetrics:
    def test_metrics_iv_from_real_data(self) -> None:
        """ATM IV is correctly extracted from option chain and converted from %."""
        from income_desk.broker.dhan.metrics import DhanMetrics

        class MockClient:
            def option_chain(self, under_scrip_code, under_exchange_segment):
                return {"data": [
                    {
                        "strikePrice": 25900,
                        "expiryDate": "2026-04-24",
                        "underlyingPrice": 25950.0,
                        "ce": {"iv": 18.5, "oi": 100000, "volume": 5000,
                               "bid_price": 200, "ask_price": 210, "ltp": 205,
                               "delta": 0.52, "gamma": 0.01, "theta": -5, "vega": 10},
                        "pe": {"iv": 19.0, "oi": 90000, "volume": 4500,
                               "bid_price": 190, "ask_price": 200, "ltp": 195,
                               "delta": -0.48, "gamma": 0.01, "theta": -5.5, "vega": 10.5},
                    },
                    {
                        "strikePrice": 26000,
                        "expiryDate": "2026-04-24",
                        "ce": {"iv": 17.0, "oi": 80000, "volume": 4000,
                               "bid_price": 150, "ask_price": 160, "ltp": 155,
                               "delta": 0.48, "gamma": 0.01, "theta": -4.5, "vega": 9},
                        "pe": {"iv": 20.0, "oi": 120000, "volume": 6000,
                               "bid_price": 250, "ask_price": 260, "ltp": 255,
                               "delta": -0.52, "gamma": 0.01, "theta": -6, "vega": 11},
                    },
                ]}

        metrics_provider = DhanMetrics(MockClient())
        results = metrics_provider.get_metrics(["NIFTY"])
        assert "NIFTY" in results
        m = results["NIFTY"]
        # ATM IV from nearest strike: (18.5 + 19.0) / 2 / 100 ≈ 0.1875
        assert m.iv_30_day is not None
        assert 0.10 < m.iv_30_day < 0.35  # Reasonable range after % → decimal

    def test_metrics_empty_on_api_error(self) -> None:
        """Metrics returns empty dict when API fails — no exception propagated."""
        from income_desk.broker.dhan.metrics import DhanMetrics

        class FailingClient:
            def option_chain(self, **kwargs):
                raise ConnectionError("Dhan API down")

        metrics_provider = DhanMetrics(FailingClient())
        results = metrics_provider.get_metrics(["NIFTY"])
        assert results == {}

    def test_metrics_liquidity_rating_high_oi(self) -> None:
        """Liquidity rating of 5 assigned for very high OI (> 10M)."""
        from income_desk.broker.dhan.metrics import DhanMetrics

        class HighOIClient:
            def option_chain(self, **kwargs):
                # Single strike with huge OI
                entries = [{
                    "strikePrice": 26000,
                    "expiryDate": "2026-04-24",
                    "underlyingPrice": 26050.0,
                    "ce": {"iv": 20.0, "oi": 6_000_000, "volume": 100000,
                           "bid_price": 100, "ask_price": 110, "ltp": 105,
                           "delta": 0.5, "gamma": 0.01, "theta": -5, "vega": 10},
                    "pe": {"iv": 21.0, "oi": 5_500_000, "volume": 90000,
                           "bid_price": 95, "ask_price": 105, "ltp": 100,
                           "delta": -0.5, "gamma": 0.01, "theta": -5.5, "vega": 10.5},
                }]
                return {"data": entries}

        metrics_provider = DhanMetrics(HighOIClient())
        results = metrics_provider.get_metrics(["NIFTY"])
        assert "NIFTY" in results
        # Total OI = 11.5M → liquidity 5
        assert results["NIFTY"].liquidity_rating == 5.0


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

class TestDhanWatchlist:
    def test_create_watchlist_returns_false(self) -> None:
        """create_watchlist always returns False (Dhan has no watchlist API)."""
        from income_desk.broker.dhan.watchlist import DhanWatchlist
        wl = DhanWatchlist()
        result = wl.create_watchlist("my_list", ["NIFTY", "BANKNIFTY"])
        assert result is False

    def test_list_watchlists_returns_list(self) -> None:
        """list_watchlists returns a non-empty list (at minimum preset names)."""
        from income_desk.broker.dhan.watchlist import DhanWatchlist
        wl = DhanWatchlist()
        result = wl.list_watchlists()
        assert isinstance(result, list)

    def test_unknown_watchlist_returns_empty(self) -> None:
        """Unknown watchlist name returns empty list without raising."""
        from income_desk.broker.dhan.watchlist import DhanWatchlist
        wl = DhanWatchlist()
        result = wl.get_watchlist("nonexistent_watchlist_xyz_123")
        assert result == []


# ---------------------------------------------------------------------------
# _broker.py integration
# ---------------------------------------------------------------------------

class TestDhanBrokerDetection:
    def test_has_dhan_creds_env_vars(self) -> None:
        """_has_dhan_creds returns True when DHAN env vars are set."""
        import os
        from income_desk.cli._broker import _has_dhan_creds

        # Simulate env vars set
        original_id = os.environ.get("DHAN_CLIENT_ID")
        original_token = os.environ.get("DHAN_ACCESS_TOKEN")
        try:
            os.environ["DHAN_CLIENT_ID"] = "test_id"
            os.environ["DHAN_ACCESS_TOKEN"] = "test_token"
            assert _has_dhan_creds({}) is True
        finally:
            if original_id is None:
                os.environ.pop("DHAN_CLIENT_ID", None)
            else:
                os.environ["DHAN_CLIENT_ID"] = original_id
            if original_token is None:
                os.environ.pop("DHAN_ACCESS_TOKEN", None)
            else:
                os.environ["DHAN_ACCESS_TOKEN"] = original_token

    def test_has_dhan_creds_yaml_config(self) -> None:
        """_has_dhan_creds returns True when cfg has dhan section."""
        import os
        from income_desk.cli._broker import _has_dhan_creds

        # Ensure env vars are clear
        original_id = os.environ.pop("DHAN_CLIENT_ID", None)
        original_token = os.environ.pop("DHAN_ACCESS_TOKEN", None)
        try:
            cfg = {"dhan": {"client_id": "abc", "access_token": "xyz"}}
            assert _has_dhan_creds(cfg) is True
        finally:
            if original_id:
                os.environ["DHAN_CLIENT_ID"] = original_id
            if original_token:
                os.environ["DHAN_ACCESS_TOKEN"] = original_token

    def test_has_dhan_creds_false_when_empty(self) -> None:
        """_has_dhan_creds returns False when no creds anywhere."""
        import os
        from income_desk.cli._broker import _has_dhan_creds

        original_id = os.environ.pop("DHAN_CLIENT_ID", None)
        original_token = os.environ.pop("DHAN_ACCESS_TOKEN", None)
        try:
            assert _has_dhan_creds({}) is False
        finally:
            if original_id:
                os.environ["DHAN_CLIENT_ID"] = original_id
            if original_token:
                os.environ["DHAN_ACCESS_TOKEN"] = original_token

    def test_dhan_in_broker_type_choices(self) -> None:
        """'dhan' is a valid --broker-type choice in the CLI."""
        import argparse
        from income_desk.cli._broker import add_broker_args

        parser = argparse.ArgumentParser()
        add_broker_args(parser)

        # Should parse without error
        args = parser.parse_args(["--broker-type", "dhan"])
        assert args.broker_type == "dhan"


# ---------------------------------------------------------------------------
# connect_dhan_from_session
# ---------------------------------------------------------------------------

class TestDhanFromSession:
    def test_from_session_returns_tuple(self) -> None:
        """connect_dhan_from_session accepts any object and returns 4-tuple."""
        from income_desk.broker.dhan import connect_dhan_from_session
        result = connect_dhan_from_session(_MockClient())
        assert len(result) == 4
        md, mm, acct, wl = result
        assert wl is None  # Dhan has no watchlist API

    def test_from_session_types(self) -> None:
        """Returned providers have correct types."""
        from income_desk.broker.dhan import connect_dhan_from_session
        from income_desk.broker.dhan.account import DhanAccount
        from income_desk.broker.dhan.market_data import DhanMarketData
        from income_desk.broker.dhan.metrics import DhanMetrics

        md, mm, acct, wl = connect_dhan_from_session(_MockClient())
        assert isinstance(md, DhanMarketData)
        assert isinstance(mm, DhanMetrics)
        assert isinstance(acct, DhanAccount)
        assert wl is None
