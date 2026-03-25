"""Tests for create_user_analyzer() SaaS factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from income_desk.service.analyzer import create_user_analyzer, MarketAnalyzer


class TestCreateUserAnalyzerEdgeCases:
    """Validation / error-path tests (no broker SDK needed)."""

    def test_unknown_broker_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown broker 'foobar'"):
            create_user_analyzer(broker="foobar", session=object())

    def test_planned_broker_raises_not_implemented(self):
        for name in ("schwab", "alpaca", "ibkr"):
            with pytest.raises(NotImplementedError, match="does not have"):
                create_user_analyzer(broker=name, session=object())

    def test_broker_name_is_case_insensitive(self):
        """'Schwab' should hit NotImplementedError, not ValueError."""
        with pytest.raises(NotImplementedError):
            create_user_analyzer(broker="Schwab", session=object())

    @patch("income_desk.service.analyzer.MarketAnalyzer")
    @patch("income_desk.broker.tastytrade.connect_from_sessions")
    def test_creates_data_service_if_none(self, mock_connect, mock_ma):
        mock_md, mock_mm, mock_wl = MagicMock(), MagicMock(), MagicMock()
        mock_connect.return_value = (mock_md, mock_mm, mock_wl)
        mock_ma.return_value = MagicMock(spec=MarketAnalyzer)

        result = create_user_analyzer(broker="tastytrade", session=MagicMock())

        # DataService was not passed, so the factory should create one
        call_kwargs = mock_ma.call_args.kwargs
        assert call_kwargs["data_service"] is not None
        assert call_kwargs["market_data"] is mock_md
        assert call_kwargs["market_metrics"] is mock_mm
        assert call_kwargs["watchlist_provider"] is mock_wl

    @patch("income_desk.broker.tastytrade.connect_from_sessions")
    def test_reuses_provided_data_service(self, mock_connect):
        mock_md, mock_mm, mock_wl = MagicMock(), MagicMock(), MagicMock()
        mock_connect.return_value = (mock_md, mock_mm, mock_wl)
        shared_ds = MagicMock()

        with patch("income_desk.service.analyzer.MarketAnalyzer") as mock_ma:
            mock_ma.return_value = MagicMock(spec=MarketAnalyzer)
            create_user_analyzer(
                broker="tastytrade", session=MagicMock(), data_service=shared_ds,
            )
            assert mock_ma.call_args.kwargs["data_service"] is shared_ds
