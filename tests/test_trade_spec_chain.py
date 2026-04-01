"""Tests for chain-aware strike selection in _trade_spec_helpers.py."""

from __future__ import annotations

from datetime import date

import pytest

from income_desk.models.chain import AvailableStrike, ChainContext
from income_desk.models.opportunity import LegAction, OrderSide, StructureType
from income_desk.opportunity.option_plays._trade_spec_helpers import (
    build_trade_spec_from_chain,
    pick_credit_spread_from_chain,
    pick_ic_strikes_from_chain,
    pick_ifly_strikes_from_chain,
)


def _strike(strike: float, opt_type: str, iv: float = 0.25) -> AvailableStrike:
    """Helper to build an AvailableStrike with sensible defaults."""
    return AvailableStrike(
        strike=strike,
        option_type=opt_type,
        bid=1.00,
        ask=1.20,
        mid=1.10,
        iv=iv,
        open_interest=500,
        volume=100,
    )


def _make_chain(
    price: float = 100.0,
    put_strikes: list[float] | None = None,
    call_strikes: list[float] | None = None,
) -> ChainContext:
    """Build a ChainContext with uniform strikes around price."""
    if put_strikes is None:
        put_strikes = [price - i for i in range(1, 11)]  # 99..90
    if call_strikes is None:
        call_strikes = [price + i for i in range(1, 11)]  # 101..110
    return ChainContext(
        ticker="TEST",
        expiration=date(2026, 5, 15),
        lot_size=100,
        underlying_price=price,
        put_strikes=sorted([_strike(s, "put") for s in put_strikes], key=lambda x: x.strike),
        call_strikes=sorted([_strike(s, "call") for s in call_strikes], key=lambda x: x.strike),
    )


# ──────────────────────────────────────────────────────────────────────
# pick_ic_strikes_from_chain
# ──────────────────────────────────────────────────────────────────────


class TestPickICStrikes:
    def test_r1_picks_1_atr_distance(self):
        chain = _make_chain(price=100.0)
        atr = 3.0
        result = pick_ic_strikes_from_chain(chain, atr, regime_id=1)
        assert result is not None
        # R1: price - 1.0*ATR = 97 -> nearest put = 97
        assert result["short_put"].strike == 97.0
        # R1: price + 1.0*ATR = 103 -> nearest call = 103
        assert result["short_call"].strike == 103.0
        # Long put below 97 -> 96
        assert result["long_put"].strike == 96.0
        # Long call above 103 -> 104
        assert result["long_call"].strike == 104.0

    def test_r2_picks_0_8_atr_distance(self):
        chain = _make_chain(price=100.0)
        atr = 5.0
        result = pick_ic_strikes_from_chain(chain, atr, regime_id=2)
        assert result is not None
        # R2: price - 0.8*5 = 96 -> nearest put = 96
        assert result["short_put"].strike == 96.0
        # R2: price + 0.8*5 = 104 -> nearest call = 104
        assert result["short_call"].strike == 104.0

    def test_returns_none_no_puts(self):
        chain = _make_chain(price=100.0, put_strikes=[])
        result = pick_ic_strikes_from_chain(chain, atr=3.0, regime_id=1)
        assert result is None

    def test_returns_none_no_calls(self):
        chain = _make_chain(price=100.0, call_strikes=[])
        result = pick_ic_strikes_from_chain(chain, atr=3.0, regime_id=1)
        assert result is None

    def test_returns_none_no_long_put_below(self):
        """Only one put strike available — can't form a wing."""
        chain = _make_chain(price=100.0, put_strikes=[97.0])
        result = pick_ic_strikes_from_chain(chain, atr=3.0, regime_id=1)
        assert result is None

    def test_returns_none_no_long_call_above(self):
        """Only one call strike available — can't form a wing."""
        chain = _make_chain(price=100.0, call_strikes=[103.0])
        result = pick_ic_strikes_from_chain(chain, atr=3.0, regime_id=1)
        assert result is None

    def test_snaps_to_nearest_available(self):
        """Target falls between two strikes — picks the nearest one."""
        chain = _make_chain(price=100.0, put_strikes=[90, 95, 98],
                            call_strikes=[102, 105, 110])
        atr = 3.5  # R1: target put = 96.5, target call = 103.5
        result = pick_ic_strikes_from_chain(chain, atr, regime_id=1)
        assert result is not None
        assert result["short_put"].strike == 95.0  # nearest to 96.5
        assert result["short_call"].strike == 102.0  # nearest to 103.5


# ──────────────────────────────────────────────────────────────────────
# pick_ifly_strikes_from_chain
# ──────────────────────────────────────────────────────────────────────


class TestPickIFlyStrikes:
    def test_atm_strikes_same(self):
        chain = _make_chain(price=100.0, put_strikes=[98, 99, 100, 101],
                            call_strikes=[99, 100, 101, 102])
        result = pick_ifly_strikes_from_chain(chain, atr=3.0, regime_id=2)
        assert result is not None
        # Both short strikes should be at ATM
        assert result["short_put"].strike == result["short_call"].strike

    def test_wings_outside_atm(self):
        chain = _make_chain(price=100.0, put_strikes=[95, 96, 97, 98, 99, 100],
                            call_strikes=[100, 101, 102, 103, 104, 105])
        result = pick_ifly_strikes_from_chain(chain, atr=3.0, regime_id=2)
        assert result is not None
        atm = result["short_put"].strike
        assert result["long_put"].strike < atm
        assert result["long_call"].strike > atm

    def test_returns_none_no_strikes(self):
        chain = _make_chain(price=100.0, put_strikes=[], call_strikes=[])
        result = pick_ifly_strikes_from_chain(chain, atr=3.0, regime_id=1)
        assert result is None

    def test_returns_none_wing_not_outside(self):
        """If only ATM strikes exist, can't form wings."""
        chain = _make_chain(price=100.0, put_strikes=[100], call_strikes=[100])
        result = pick_ifly_strikes_from_chain(chain, atr=3.0, regime_id=1)
        assert result is None


# ──────────────────────────────────────────────────────────────────────
# pick_credit_spread_from_chain
# ──────────────────────────────────────────────────────────────────────


class TestPickCreditSpread:
    def test_put_spread(self):
        chain = _make_chain(price=100.0)
        result = pick_credit_spread_from_chain(chain, atr=3.0, regime_id=1, direction="put")
        assert result is not None
        assert result["short"].option_type == "put"
        assert result["long"].option_type == "put"
        assert result["long"].strike < result["short"].strike

    def test_call_spread(self):
        chain = _make_chain(price=100.0)
        result = pick_credit_spread_from_chain(chain, atr=3.0, regime_id=1, direction="call")
        assert result is not None
        assert result["short"].option_type == "call"
        assert result["long"].option_type == "call"
        assert result["long"].strike > result["short"].strike

    def test_put_returns_none_no_wing(self):
        chain = _make_chain(price=100.0, put_strikes=[97])
        result = pick_credit_spread_from_chain(chain, atr=3.0, regime_id=1, direction="put")
        assert result is None

    def test_call_returns_none_no_wing(self):
        chain = _make_chain(price=100.0, call_strikes=[103])
        result = pick_credit_spread_from_chain(chain, atr=3.0, regime_id=1, direction="call")
        assert result is None


# ──────────────────────────────────────────────────────────────────────
# build_trade_spec_from_chain
# ──────────────────────────────────────────────────────────────────────


class TestBuildTradeSpecFromChain:
    def test_iron_condor_spec(self):
        chain = _make_chain(price=100.0)
        strikes = pick_ic_strikes_from_chain(chain, atr=3.0, regime_id=1)
        assert strikes is not None

        spec = build_trade_spec_from_chain(chain, StructureType.IRON_CONDOR, strikes, regime_id=1)
        assert spec.ticker == "TEST"
        assert spec.underlying_price == 100.0
        assert spec.target_expiration == date(2026, 5, 15)
        assert spec.structure_type == StructureType.IRON_CONDOR
        assert spec.order_side == OrderSide.CREDIT
        assert spec.lot_size == 100
        assert len(spec.legs) == 4
        # Verify leg actions
        roles = {leg.role: leg.action for leg in spec.legs}
        assert roles["short_put"] == LegAction.SELL_TO_OPEN
        assert roles["long_put"] == LegAction.BUY_TO_OPEN
        assert roles["short_call"] == LegAction.SELL_TO_OPEN
        assert roles["long_call"] == LegAction.BUY_TO_OPEN

    def test_iron_condor_wing_width(self):
        chain = _make_chain(price=100.0)
        strikes = pick_ic_strikes_from_chain(chain, atr=3.0, regime_id=1)
        assert strikes is not None

        spec = build_trade_spec_from_chain(chain, StructureType.IRON_CONDOR, strikes, regime_id=1)
        # short_put=97, long_put=96 -> wing_width=1
        assert spec.wing_width_points == 1.0

    def test_iron_butterfly_spec(self):
        chain = _make_chain(price=100.0, put_strikes=[95, 96, 97, 98, 99, 100],
                            call_strikes=[100, 101, 102, 103, 104, 105])
        strikes = pick_ifly_strikes_from_chain(chain, atr=3.0, regime_id=2)
        assert strikes is not None

        spec = build_trade_spec_from_chain(chain, StructureType.IRON_BUTTERFLY, strikes, regime_id=2)
        assert spec.structure_type == StructureType.IRON_BUTTERFLY
        assert spec.order_side == OrderSide.CREDIT
        assert len(spec.legs) == 4

    def test_credit_spread_spec(self):
        chain = _make_chain(price=100.0)
        strikes = pick_credit_spread_from_chain(chain, atr=3.0, regime_id=1, direction="put")
        assert strikes is not None

        spec = build_trade_spec_from_chain(chain, StructureType.CREDIT_SPREAD, strikes, regime_id=1)
        assert spec.structure_type == StructureType.CREDIT_SPREAD
        assert spec.order_side == OrderSide.CREDIT
        assert len(spec.legs) == 2
        assert spec.wing_width_points > 0

    def test_iv_from_chain_strikes(self):
        """Each leg's atm_iv_at_expiry should come from the chain strike's IV."""
        chain = _make_chain(price=100.0)
        # put_strikes sorted ascending: [90,91,...,99] -> index 7=97, index 6=96
        # call_strikes sorted ascending: [101,102,...,110] -> index 2=103, index 3=104
        chain.put_strikes[7].iv = 0.30  # strike 97
        chain.put_strikes[6].iv = 0.32  # strike 96
        chain.call_strikes[2].iv = 0.22  # strike 103
        chain.call_strikes[3].iv = 0.24  # strike 104

        strikes = pick_ic_strikes_from_chain(chain, atr=3.0, regime_id=1)
        assert strikes is not None
        spec = build_trade_spec_from_chain(chain, StructureType.IRON_CONDOR, strikes, regime_id=1)

        iv_by_role = {leg.role: leg.atm_iv_at_expiry for leg in spec.legs}
        assert iv_by_role["short_put"] == 0.30
        assert iv_by_role["long_put"] == 0.32
        assert iv_by_role["short_call"] == 0.22
        assert iv_by_role["long_call"] == 0.24

    def test_lot_size_from_chain(self):
        """lot_size should come from chain, not registry."""
        chain = _make_chain(price=100.0)
        chain.lot_size = 50  # Non-standard lot size

        strikes = pick_ic_strikes_from_chain(chain, atr=3.0, regime_id=1)
        assert strikes is not None
        spec = build_trade_spec_from_chain(chain, StructureType.IRON_CONDOR, strikes, regime_id=1)
        assert spec.lot_size == 50

    def test_unsupported_structure_raises(self):
        chain = _make_chain(price=100.0)
        strikes = pick_ic_strikes_from_chain(chain, atr=3.0, regime_id=1)
        assert strikes is not None

        with pytest.raises(ValueError, match="Unsupported structure_type"):
            build_trade_spec_from_chain(chain, "straddle", strikes, regime_id=1)

    def test_entry_window_set(self):
        chain = _make_chain(price=100.0)
        strikes = pick_ic_strikes_from_chain(chain, atr=3.0, regime_id=1)
        assert strikes is not None

        spec = build_trade_spec_from_chain(chain, StructureType.IRON_CONDOR, strikes, regime_id=1)
        assert spec.entry_window_start is not None
        assert spec.entry_window_end is not None

    def test_spec_rationale_includes_chain(self):
        chain = _make_chain(price=100.0)
        strikes = pick_ic_strikes_from_chain(chain, atr=3.0, regime_id=1)
        assert strikes is not None

        spec = build_trade_spec_from_chain(chain, StructureType.IRON_CONDOR, strikes, regime_id=1)
        assert "broker chain" in spec.spec_rationale.lower()
