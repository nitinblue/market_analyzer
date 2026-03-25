"""Tests for get_current_prices() and mark_positions_to_market()."""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from income_desk.trade_analytics import (
    MarkedPositions,
    PositionInput,
    PriceResult,
    get_current_prices,
    mark_positions_to_market,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_market_data(prices: dict[str, float | None]) -> MagicMock:
    """Create a mock MarketDataProvider returning specified prices."""
    md = MagicMock()
    md.get_underlying_price.side_effect = lambda t: prices.get(t)
    return md


def _make_data_service(closes: dict[str, float | None]) -> MagicMock:
    """Create a mock DataService returning OHLCV with a last Close."""
    ds = MagicMock()

    def _get_ohlcv(ticker, **kwargs):
        val = closes.get(ticker)
        if val is None:
            return pd.DataFrame()
        return pd.DataFrame({"Close": [val]})

    ds.get_ohlcv.side_effect = _get_ohlcv
    return ds


# ---------------------------------------------------------------------------
# get_current_prices tests
# ---------------------------------------------------------------------------


def test_broker_price_preferred_over_yfinance():
    """Broker live price should be used when available, even if yfinance works."""
    md = _make_market_data({"SPY": 520.50})
    ds = _make_data_service({"SPY": 519.00})

    result = get_current_prices(["SPY"], market_data=md, data_service=ds)

    assert "SPY" in result
    pr = result["SPY"]
    assert pr.price == 520.50
    assert pr.source == "broker_live"
    assert pr.trust == "HIGH"
    # yfinance should NOT have been called
    ds.get_ohlcv.assert_not_called()


def test_yfinance_fallback_when_no_broker():
    """When no broker is provided, yfinance delayed price should be used."""
    ds = _make_data_service({"AAPL": 185.25})

    result = get_current_prices(["AAPL"], market_data=None, data_service=ds)

    pr = result["AAPL"]
    assert pr.price == 185.25
    assert pr.source == "yfinance_delayed"
    assert pr.trust == "LOW"


def test_yfinance_fallback_when_broker_returns_none():
    """If broker returns None for a ticker, fall back to yfinance."""
    md = _make_market_data({"XYZ": None})
    ds = _make_data_service({"XYZ": 42.00})

    result = get_current_prices(["XYZ"], market_data=md, data_service=ds)

    pr = result["XYZ"]
    assert pr.price == 42.00
    assert pr.source == "yfinance_delayed"
    assert pr.trust == "LOW"


def test_unavailable_when_both_fail():
    """If both broker and yfinance fail, return unavailable."""
    md = _make_market_data({"FAKE": None})
    ds = _make_data_service({"FAKE": None})

    result = get_current_prices(["FAKE"], market_data=md, data_service=ds)

    pr = result["FAKE"]
    assert pr.price == 0
    assert pr.source == "unavailable"
    assert pr.trust == "NONE"


# ---------------------------------------------------------------------------
# mark_positions_to_market tests
# ---------------------------------------------------------------------------


def test_pnl_calculation_equity():
    """Equity PnL: (current - entry) * quantity * 1."""
    ds = _make_data_service({"MSFT": 400.00})
    positions = [
        PositionInput(
            trade_id="eq1",
            ticker="MSFT",
            entry_price=380.00,
            quantity=10,
            multiplier=1,
        ),
    ]

    result = mark_positions_to_market(positions, data_service=ds)

    assert len(result.positions) == 1
    mp = result.positions[0]
    assert mp.pnl == pytest.approx((400.0 - 380.0) * 10 * 1)  # 200.0
    assert mp.pnl_pct == pytest.approx((400.0 - 380.0) / 380.0 * 100.0)
    assert result.total_pnl == pytest.approx(200.0)
    assert result.tickers_marked == 1
    assert result.tickers_failed == 0


def test_pnl_calculation_options():
    """Options PnL: (current - entry) * quantity * 100."""
    md = _make_market_data({"SPY": 520.00})
    positions = [
        PositionInput(
            trade_id="opt1",
            ticker="SPY",
            entry_price=5.00,
            quantity=-2,
            multiplier=100,
            structure_type="short_put",
        ),
    ]

    result = mark_positions_to_market(positions, market_data=md)

    mp = result.positions[0]
    # Short 2 contracts: (520 - 5) * (-2) * 100 = -103_000
    expected_pnl = (520.00 - 5.00) * (-2) * 100
    assert mp.pnl == pytest.approx(expected_pnl)
    assert mp.data_source == "broker_live"
    assert mp.trust == "HIGH"
    assert result.total_pnl == pytest.approx(expected_pnl)


def test_trust_level_propagation():
    """overall_trust should be the worst trust across all positions."""
    md = _make_market_data({"SPY": 520.00, "GLD": None})
    ds = _make_data_service({"GLD": 230.00})

    positions = [
        PositionInput(
            trade_id="t1", ticker="SPY", entry_price=500.0, quantity=1, multiplier=1,
        ),
        PositionInput(
            trade_id="t2", ticker="GLD", entry_price=220.0, quantity=1, multiplier=1,
        ),
    ]

    result = mark_positions_to_market(positions, market_data=md, data_service=ds)

    # SPY=HIGH, GLD=LOW → overall should be LOW
    assert result.overall_trust == "LOW"
    assert result.tickers_marked == 2
    assert result.tickers_failed == 0

    # SPY position trust
    spy_pos = next(p for p in result.positions if p.ticker == "SPY")
    assert spy_pos.trust == "HIGH"

    # GLD position trust
    gld_pos = next(p for p in result.positions if p.ticker == "GLD")
    assert gld_pos.trust == "LOW"


def test_trust_level_propagation_with_failure():
    """If any ticker is unavailable, overall_trust should be NONE."""
    md = _make_market_data({"SPY": 520.00, "FAKE": None})
    ds = _make_data_service({"FAKE": None})

    positions = [
        PositionInput(
            trade_id="t1", ticker="SPY", entry_price=500.0, quantity=1, multiplier=1,
        ),
        PositionInput(
            trade_id="t2", ticker="FAKE", entry_price=10.0, quantity=5, multiplier=1,
        ),
    ]

    result = mark_positions_to_market(positions, market_data=md, data_service=ds)

    assert result.overall_trust == "NONE"
    assert result.tickers_marked == 1
    assert result.tickers_failed == 1
