"""Tests for RepricedTrade, LegDetail models and reprice_trade / batch_reprice."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from income_desk.models.opportunity import LegAction
from income_desk.workflow.pricing_service import (
    LegDetail,
    RepricedTrade,
    batch_reprice,
    reprice_trade,
)


def _sample_leg(**overrides) -> dict:
    defaults = {
        "strike": 540.0,
        "option_type": "put",
        "action": "sell",
        "bid": 1.20,
        "ask": 1.40,
        "mid": 1.30,
        "iv": 0.22,
        "delta": -0.15,
        "open_interest": 5000,
        "volume": 1200,
    }
    defaults.update(overrides)
    return defaults


def _sample_trade(**overrides) -> dict:
    defaults = {
        "ticker": "SPY",
        "structure": "put_credit_spread",
        "entry_credit": 0.85,
        "credit_source": "chain",
        "wing_width": 5.0,
        "lot_size": 1,
        "current_price": 555.0,
        "atr_pct": 0.012,
        "regime_id": 1,
        "expiry": "2026-04-04",
        "legs_found": True,
        "liquidity_ok": True,
        "block_reason": None,
        "leg_details": [LegDetail(**_sample_leg())],
    }
    defaults.update(overrides)
    return defaults


class TestRepricedTradeImmutable:
    def test_repriced_trade_immutable(self):
        trade = RepricedTrade(**_sample_trade())
        with pytest.raises(ValidationError):
            trade.entry_credit = 9.99
        with pytest.raises(ValidationError):
            trade.ticker = "AAPL"


class TestRepricedTradeFields:
    def test_repriced_trade_fields(self):
        trade = RepricedTrade(**_sample_trade())
        assert trade.ticker == "SPY"
        assert trade.structure == "put_credit_spread"
        assert trade.entry_credit == 0.85
        assert trade.credit_source == "chain"
        assert trade.wing_width == 5.0
        assert trade.lot_size == 1
        assert trade.current_price == 555.0
        assert trade.atr_pct == 0.012
        assert trade.regime_id == 1
        assert trade.expiry == "2026-04-04"
        assert trade.legs_found is True
        assert trade.liquidity_ok is True
        assert trade.block_reason is None
        assert len(trade.leg_details) == 1


class TestLegDetailFields:
    def test_leg_detail_fields(self):
        leg = LegDetail(**_sample_leg())
        assert leg.strike == 540.0
        assert leg.option_type == "put"
        assert leg.action == "sell"
        assert leg.bid == 1.20
        assert leg.ask == 1.40
        assert leg.mid == 1.30
        assert leg.iv == 0.22
        assert leg.delta == -0.15
        assert leg.open_interest == 5000
        assert leg.volume == 1200

    def test_leg_detail_optional_defaults(self):
        leg = LegDetail(
            strike=540.0,
            option_type="call",
            action="buy",
            bid=0.50,
            ask=0.70,
            mid=0.60,
        )
        assert leg.iv is None
        assert leg.delta is None
        assert leg.open_interest == 0
        assert leg.volume == 0


class TestRepricedTradeBlocked:
    def test_repriced_trade_blocked(self):
        trade = RepricedTrade(
            **_sample_trade(
                entry_credit=0.0,
                credit_source="blocked",
                legs_found=False,
                liquidity_ok=False,
                block_reason="No liquid chain for expiry",
                leg_details=[],
            )
        )
        assert trade.credit_source == "blocked"
        assert trade.entry_credit == 0.0
        assert trade.legs_found is False
        assert trade.liquidity_ok is False
        assert trade.block_reason == "No liquid chain for expiry"
        assert trade.leg_details == []


# ── Helpers for reprice_trade tests ──


def _mock_quote(strike: float, option_type: str, bid: float, ask: float,
                oi: int = 500, volume: int = 200, iv: float = 0.20,
                delta: float = -0.15) -> MagicMock:
    """Create a mock OptionQuote."""
    q = MagicMock()
    q.strike = strike
    q.option_type = option_type
    q.bid = bid
    q.ask = ask
    q.mid = round((bid + ask) / 2, 4)
    q.open_interest = oi
    q.volume = volume
    q.implied_volatility = iv
    q.delta = delta
    q.lot_size = 100
    return q


def _mock_leg(strike: float, option_type: str, action: LegAction) -> MagicMock:
    """Create a mock LegSpec."""
    leg = MagicMock()
    leg.strike = strike
    leg.option_type = option_type
    leg.action = action
    return leg


def _mock_trade_spec(legs: list, structure: str = "iron_condor",
                     wing_width: float | None = 5.0) -> MagicMock:
    """Create a mock TradeSpec."""
    ts = MagicMock()
    ts.legs = legs
    ts.structure_type = structure
    ts.wing_width_points = wing_width
    ts.target_expiration = date(2026, 4, 4)
    return ts


def _ic_chain_and_legs():
    """Return a 4-leg iron condor chain and legs.

    Structure: STO 540P, BTO 535P, STO 570C, BTO 575C
    """
    legs = [
        _mock_leg(540.0, "put", LegAction.SELL_TO_OPEN),
        _mock_leg(535.0, "put", LegAction.BUY_TO_OPEN),
        _mock_leg(570.0, "call", LegAction.SELL_TO_OPEN),
        _mock_leg(575.0, "call", LegAction.BUY_TO_OPEN),
    ]
    chain = [
        _mock_quote(540.0, "put", bid=1.80, ask=2.00),   # mid=1.90 sell
        _mock_quote(535.0, "put", bid=1.00, ask=1.20),   # mid=1.10 buy
        _mock_quote(570.0, "call", bid=1.60, ask=1.80),  # mid=1.70 sell
        _mock_quote(575.0, "call", bid=0.80, ask=1.00),  # mid=0.90 buy
    ]
    # Expected net credit: +1.90 -1.10 +1.70 -0.90 = 1.60
    return legs, chain


class TestRepriceTradeFunction:
    def test_reprice_all_legs_found(self):
        """4-leg IC with matching chain -> correct credit, legs_found=True."""
        legs, chain = _ic_chain_and_legs()
        ts = _mock_trade_spec(legs, wing_width=5.0)

        result = reprice_trade(ts, chain, "SPY", 555.0, 0.012, 1)

        assert result.credit_source == "chain"
        assert result.legs_found is True
        assert result.liquidity_ok is True
        assert result.block_reason is None
        assert abs(result.entry_credit - 1.60) < 0.01
        assert len(result.leg_details) == 4
        assert result.ticker == "SPY"
        assert result.regime_id == 1

    def test_reprice_missing_leg(self):
        """Chain missing one strike -> blocked."""
        legs, chain = _ic_chain_and_legs()
        # Remove the 575 call from chain
        chain = [q for q in chain if q.strike != 575.0]
        ts = _mock_trade_spec(legs)

        result = reprice_trade(ts, chain, "SPY", 555.0, 0.012, 1)

        assert result.credit_source == "blocked"
        assert result.legs_found is False
        assert "Missing strikes" in result.block_reason

    def test_reprice_zero_price(self):
        """current_price=0 -> blocked with 'price' in reason."""
        legs, chain = _ic_chain_and_legs()
        ts = _mock_trade_spec(legs)

        result = reprice_trade(ts, chain, "SPY", 0.0, 0.012, 1)

        assert result.credit_source == "blocked"
        assert "price" in result.block_reason.lower()

    def test_reprice_empty_chain(self):
        """Empty chain -> blocked."""
        legs, _ = _ic_chain_and_legs()
        ts = _mock_trade_spec(legs)

        result = reprice_trade(ts, [], "SPY", 555.0, 0.012, 1)

        assert result.credit_source == "blocked"
        assert "No chain data" in result.block_reason

    def test_reprice_illiquid_spread(self):
        """Wide bid-ask spread -> liquidity_ok=False but legs_found=True."""
        legs, chain = _ic_chain_and_legs()
        # Make the 540 put very wide: bid=1.00, ask=3.00 -> mid=2.00, spread/mid=1.0
        chain[0] = _mock_quote(540.0, "put", bid=1.00, ask=3.00)
        ts = _mock_trade_spec(legs)

        result = reprice_trade(ts, chain, "SPY", 555.0, 0.012, 1)

        assert result.credit_source == "chain"
        assert result.legs_found is True
        assert result.liquidity_ok is False
        assert result.block_reason is None


# ── batch_reprice tests ──


def _make_entry(ticker: str, regime_id: int = 1, **overrides) -> dict:
    """Build a minimal entry dict for batch_reprice."""
    legs, _ = _ic_chain_and_legs()
    ts = _mock_trade_spec(legs)
    entry = {"ticker": ticker, "trade_spec": ts, "regime_id": regime_id}
    entry.update(overrides)
    return entry


class TestBatchRepriceFetchesChainOnce:
    @patch("income_desk.workflow.pricing_service.time.sleep")
    def test_batch_reprice_fetches_chain_once(self, mock_sleep):
        """Two entries for the same ticker -> get_option_chain called once."""
        _, chain = _ic_chain_and_legs()
        md = MagicMock()
        md.get_option_chain.return_value = chain
        md.get_underlying_price.return_value = 555.0

        entries = [_make_entry("SPY"), _make_entry("SPY")]
        results = batch_reprice(entries, market_data=md)

        assert len(results) == 2
        md.get_option_chain.assert_called_once_with("SPY")
        # No sleep needed — only one ticker
        mock_sleep.assert_not_called()


class TestBatchRepriceDifferentTickers:
    @patch("income_desk.workflow.pricing_service.time.sleep")
    def test_batch_reprice_different_tickers(self, mock_sleep):
        """Two entries for different tickers -> get_option_chain called twice."""
        _, chain = _ic_chain_and_legs()
        md = MagicMock()
        md.get_option_chain.return_value = chain
        md.get_underlying_price.return_value = 555.0

        entries = [_make_entry("SPY"), _make_entry("QQQ")]
        results = batch_reprice(entries, market_data=md)

        assert len(results) == 2
        assert md.get_option_chain.call_count == 2
        # Sleep between tickers (not before the first)
        mock_sleep.assert_called_once_with(4)


class TestBatchRepriceNoMarketData:
    def test_batch_reprice_no_market_data(self):
        """market_data=None -> entries get estimated credit (not blocked)."""
        entries = [_make_entry("SPY"), _make_entry("QQQ")]
        results = batch_reprice(entries, market_data=None)

        assert len(results) == 2
        for r in results:
            # No broker -> estimated credit from wing width or max_entry_price
            assert r.credit_source in ("estimated", "blocked")
            assert r.block_reason is None or "Cannot estimate" in r.block_reason
