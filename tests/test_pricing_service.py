"""Tests for RepricedTrade and LegDetail Pydantic models."""

import pytest
from pydantic import ValidationError

from income_desk.workflow.pricing_service import LegDetail, RepricedTrade


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
