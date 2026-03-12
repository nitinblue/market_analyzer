"""Tests for TastyTrade session — mocked SDK, no network."""

import os
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

from market_analyzer.broker.tastytrade.session import TastyTradeBrokerSession, _resolve_env


# --- Credential resolution ---

class TestResolveEnv:
    def test_plain_value_unchanged(self):
        assert _resolve_env("my_secret_value") == "my_secret_value"

    def test_env_var_dollar_braces(self):
        with patch.dict(os.environ, {"TT_LIVE_SECRET": "resolved_secret"}):
            assert _resolve_env("${TT_LIVE_SECRET}") == "resolved_secret"

    def test_env_var_dollar_only(self):
        with patch.dict(os.environ, {"TT_LIVE_TOKEN": "resolved_token"}):
            assert _resolve_env("$TT_LIVE_TOKEN") == "resolved_token"

    def test_missing_env_var_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove the var if it exists
            os.environ.pop("TT_NONEXISTENT_VAR", None)
            with pytest.raises(ValueError, match="not set"):
                _resolve_env("${TT_NONEXISTENT_VAR}")

    def test_empty_value_unchanged(self):
        assert _resolve_env("") == ""


# --- Session lifecycle ---

MOCK_YAML = """
broker:
  live:
    client_secret: live_secret
    refresh_token: live_token
  paper:
    client_secret: paper_secret
    refresh_token: paper_token
"""


# Env vars to clear so tests fall through to YAML
_TT_ENV_VARS = [
    "TASTYTRADE_CLIENT_SECRET_LIVE", "TASTYTRADE_REFRESH_TOKEN_LIVE",
    "TASTYTRADE_CLIENT_SECRET_PAPER", "TASTYTRADE_REFRESH_TOKEN_PAPER",
    "TASTYTRADE_CLIENT_SECRET_DATA", "TASTYTRADE_REFRESH_TOKEN_DATA",
]


def _clear_tt_env():
    """Context manager dict to clear TT env vars so YAML path is tested."""
    return {k: "" for k in _TT_ENV_VARS}


class TestSessionLoadCredentialsFromEnv:
    """Env var loading (preferred path)."""

    def test_loads_live_from_env(self):
        env = {
            "TASTYTRADE_CLIENT_SECRET_LIVE": "env_secret",
            "TASTYTRADE_REFRESH_TOKEN_LIVE": "env_token",
            "TASTYTRADE_CLIENT_SECRET_DATA": "env_data_secret",
            "TASTYTRADE_REFRESH_TOKEN_DATA": "env_data_token",
        }
        with patch.dict(os.environ, env):
            session = TastyTradeBrokerSession()
            session._load_credentials()
            assert session._client_secret == "env_secret"
            assert session._refresh_token == "env_token"
            assert session._data_client_secret == "env_data_secret"
            assert session._data_refresh_token == "env_data_token"

    def test_data_falls_back_to_trading_creds(self):
        """When DATA env vars are absent, data fields are empty at load time.

        The actual fallback (DATA→LIVE) happens in connect() at data_session
        creation: ``data_secret = self._data_client_secret or self._client_secret``.
        """
        env = {
            "TASTYTRADE_CLIENT_SECRET_LIVE": "env_secret",
            "TASTYTRADE_REFRESH_TOKEN_LIVE": "env_token",
        }
        with patch.dict(os.environ, env, clear=False):
            # Remove DATA vars
            os.environ.pop("TASTYTRADE_CLIENT_SECRET_DATA", None)
            os.environ.pop("TASTYTRADE_REFRESH_TOKEN_DATA", None)
            session = TastyTradeBrokerSession()
            session._load_credentials()
            # DATA fields are empty — fallback is in connect()
            assert session._data_client_secret == ""
            assert session._data_refresh_token == ""
            # Primary creds loaded correctly
            assert session._client_secret == "env_secret"
            assert session._refresh_token == "env_token"


class TestSessionLoadCredentials:
    def test_session_loads_credentials(self, tmp_path):
        """YAML parsing with plain values (no env vars)."""
        cred_file = tmp_path / "tastytrade_broker.yaml"
        cred_file.write_text(MOCK_YAML)

        with patch.dict(os.environ, _clear_tt_env(), clear=False):
            session = TastyTradeBrokerSession(config_path=str(cred_file))
            session._load_credentials()

        assert session._client_secret == "live_secret"
        assert session._refresh_token == "live_token"

    def test_session_loads_paper_credentials(self, tmp_path):
        cred_file = tmp_path / "tastytrade_broker.yaml"
        cred_file.write_text(MOCK_YAML)

        with patch.dict(os.environ, _clear_tt_env(), clear=False):
            session = TastyTradeBrokerSession(config_path=str(cred_file), is_paper=True)
            session._load_credentials()

        assert session._client_secret == "paper_secret"
        assert session._refresh_token == "paper_token"

    def test_missing_credentials_file_raises(self):
        with patch.dict(os.environ, _clear_tt_env(), clear=False):
            session = TastyTradeBrokerSession(config_path="/nonexistent/path.yaml")
            with pytest.raises(FileNotFoundError, match="not found"):
                session._load_credentials()

    def test_data_section_falls_back_to_live(self, tmp_path):
        """If no 'data' section, DXLink uses live credentials."""
        cred_file = tmp_path / "tastytrade_broker.yaml"
        cred_file.write_text(MOCK_YAML)

        with patch.dict(os.environ, _clear_tt_env(), clear=False):
            session = TastyTradeBrokerSession(config_path=str(cred_file))
            session._load_credentials()

        assert session._data_client_secret == "live_secret"
        assert session._data_refresh_token == "live_token"


class TestSessionConnect:
    def test_connect_creates_sdk_session(self, tmp_path):
        """Verify credentials load correctly before connect."""
        cred_file = tmp_path / "tastytrade_broker.yaml"
        cred_file.write_text(MOCK_YAML)

        with patch.dict(os.environ, _clear_tt_env(), clear=False):
            session = TastyTradeBrokerSession(config_path=str(cred_file))
            session._load_credentials()

        assert session._client_secret == "live_secret"
        assert session._refresh_token == "live_token"
        assert not session.is_connected  # Not yet connected

    def test_disconnected_session_properties(self):
        """No crash when accessing properties before connect."""
        session = TastyTradeBrokerSession()
        assert not session.is_connected
        assert session.broker_name == "tastytrade"

        with pytest.raises(RuntimeError, match="Not connected"):
            _ = session.sdk_session

        with pytest.raises(RuntimeError, match="Not connected"):
            _ = session.data_session

        with pytest.raises(RuntimeError, match="Not connected"):
            _ = session.account


class TestStreamerSymbolConversion:
    def test_leg_to_streamer_symbol(self):
        """LegSpec → .SPY260320P580"""
        from market_analyzer.broker.tastytrade.market_data import TastyTradeMarketData
        from market_analyzer.models.opportunity import LegAction, LegSpec

        # Create a mock session
        mock_session = MagicMock()
        md = TastyTradeMarketData(mock_session)

        leg = LegSpec(
            role="short_put", action=LegAction.SELL_TO_OPEN,
            option_type="put", strike=580.0,
            strike_label="580 put",
            expiration=date(2026, 3, 20), days_to_expiry=22,
            atm_iv_at_expiry=0.22,
        )

        sym = md.leg_to_streamer_symbol_with_ticker("SPY", leg)
        assert sym == ".SPY260320P580"

    def test_call_symbol(self):
        from market_analyzer.broker.tastytrade.market_data import TastyTradeMarketData
        from market_analyzer.models.opportunity import LegAction, LegSpec

        mock_session = MagicMock()
        md = TastyTradeMarketData(mock_session)

        leg = LegSpec(
            role="short_call", action=LegAction.SELL_TO_OPEN,
            option_type="call", strike=600.0,
            strike_label="600 call",
            expiration=date(2026, 4, 17), days_to_expiry=50,
            atm_iv_at_expiry=0.25,
        )

        sym = md.leg_to_streamer_symbol_with_ticker("SPY", leg)
        assert sym == ".SPY260417C600"
