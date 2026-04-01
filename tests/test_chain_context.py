"""Tests for ChainContext model and build_chain_context builder."""
from __future__ import annotations
from datetime import date
from types import SimpleNamespace

import pytest

from income_desk.models.chain import AvailableStrike, ChainContext
from income_desk.opportunity.option_plays._chain_context import (
    MIN_OI,
    build_chain_context,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_strike(strike: float, option_type: str, bid: float = 1.0, ask: float = 1.5,
                 iv: float | None = 0.25, delta: float | None = -0.30,
                 oi: int = 200, volume: int = 50) -> AvailableStrike:
    return AvailableStrike(
        strike=strike, option_type=option_type,
        bid=bid, ask=ask, mid=(bid + ask) / 2,
        iv=iv, delta=delta, open_interest=oi, volume=volume,
    )


def _make_chain_quote(strike: float, option_type: str, bid: float = 1.0,
                      ask: float = 1.5, oi: int = 200, volume: int = 50,
                      iv: float = 0.25, delta: float = -0.30,
                      expiration: date | None = None,
                      lot_size: int = 100) -> SimpleNamespace:
    return SimpleNamespace(
        strike=strike, option_type=option_type,
        bid=bid, ask=ask,
        open_interest=oi, volume=volume,
        implied_volatility=iv, delta=delta,
        expiration=expiration or date(2026, 4, 18),
        lot_size=lot_size,
    )


@pytest.fixture
def sample_ctx() -> ChainContext:
    puts = [_make_strike(s, "put") for s in [95.0, 97.5, 100.0, 102.5, 105.0]]
    calls = [_make_strike(s, "call") for s in [100.0, 102.5, 105.0, 107.5, 110.0]]
    return ChainContext(
        ticker="SPY", expiration=date(2026, 4, 18), lot_size=100,
        underlying_price=103.0,
        put_strikes=puts, call_strikes=calls,
    )


# ---------------------------------------------------------------------------
# ChainContext model tests
# ---------------------------------------------------------------------------

class TestNearestPutCall:
    def test_nearest_put_exact(self, sample_ctx: ChainContext):
        s = sample_ctx.nearest_put(100.0)
        assert s is not None
        assert s.strike == 100.0

    def test_nearest_put_between(self, sample_ctx: ChainContext):
        s = sample_ctx.nearest_put(98.0)
        assert s is not None
        assert s.strike == 97.5

    def test_nearest_call_exact(self, sample_ctx: ChainContext):
        s = sample_ctx.nearest_call(105.0)
        assert s is not None
        assert s.strike == 105.0

    def test_nearest_call_between(self, sample_ctx: ChainContext):
        s = sample_ctx.nearest_call(106.0)
        assert s is not None
        assert s.strike == 105.0

    def test_nearest_put_empty(self):
        ctx = ChainContext(
            ticker="X", expiration=date(2026, 4, 18), lot_size=100,
            underlying_price=100.0, put_strikes=[], call_strikes=[],
        )
        assert ctx.nearest_put(100.0) is None

    def test_nearest_call_empty(self):
        ctx = ChainContext(
            ticker="X", expiration=date(2026, 4, 18), lot_size=100,
            underlying_price=100.0, put_strikes=[], call_strikes=[],
        )
        assert ctx.nearest_call(100.0) is None


class TestBetween:
    def test_puts_between(self, sample_ctx: ChainContext):
        result = sample_ctx.puts_between(97.0, 103.0)
        strikes = [s.strike for s in result]
        assert strikes == [97.5, 100.0, 102.5]

    def test_calls_between(self, sample_ctx: ChainContext):
        result = sample_ctx.calls_between(104.0, 108.0)
        strikes = [s.strike for s in result]
        assert strikes == [105.0, 107.5]

    def test_puts_between_no_match(self, sample_ctx: ChainContext):
        assert sample_ctx.puts_between(80.0, 90.0) == []


class TestBelowAbove:
    def test_put_below(self, sample_ctx: ChainContext):
        result = sample_ctx.put_below(100.0, n=2)
        strikes = [s.strike for s in result]
        assert strikes == [97.5, 95.0]  # descending, nearest first

    def test_put_below_single(self, sample_ctx: ChainContext):
        result = sample_ctx.put_below(100.0, n=1)
        assert len(result) == 1
        assert result[0].strike == 97.5

    def test_call_above(self, sample_ctx: ChainContext):
        result = sample_ctx.call_above(105.0, n=2)
        strikes = [s.strike for s in result]
        assert strikes == [107.5, 110.0]  # ascending, nearest first

    def test_call_above_single(self, sample_ctx: ChainContext):
        result = sample_ctx.call_above(105.0, n=1)
        assert len(result) == 1
        assert result[0].strike == 107.5

    def test_put_below_none_available(self, sample_ctx: ChainContext):
        assert sample_ctx.put_below(90.0) == []

    def test_call_above_none_available(self, sample_ctx: ChainContext):
        assert sample_ctx.call_above(120.0) == []


# ---------------------------------------------------------------------------
# build_chain_context tests
# ---------------------------------------------------------------------------

class TestBuildChainContext:
    def test_empty_chain_returns_none(self):
        assert build_chain_context("SPY", [], 100.0) is None

    def test_filters_zero_bid(self):
        chain = [
            _make_chain_quote(100.0, "put", bid=0.0, ask=1.0, oi=200),
            _make_chain_quote(105.0, "call", bid=1.0, ask=1.5, oi=200),
        ]
        ctx = build_chain_context("SPY", chain, 103.0)
        assert ctx is not None
        assert len(ctx.put_strikes) == 0
        assert len(ctx.call_strikes) == 1

    def test_filters_low_oi(self):
        chain = [
            _make_chain_quote(100.0, "put", bid=1.0, ask=1.5, oi=10),   # below MIN_OI
            _make_chain_quote(102.0, "put", bid=1.0, ask=1.5, oi=200),  # above MIN_OI
        ]
        ctx = build_chain_context("SPY", chain, 103.0)
        assert ctx is not None
        assert len(ctx.put_strikes) == 1
        assert ctx.put_strikes[0].strike == 102.0

    def test_all_filtered_returns_none(self):
        chain = [
            _make_chain_quote(100.0, "put", bid=0.0, ask=1.0, oi=10),
        ]
        assert build_chain_context("SPY", chain, 103.0) is None

    def test_sorts_strikes_ascending(self):
        chain = [
            _make_chain_quote(105.0, "put", oi=200),
            _make_chain_quote(100.0, "put", oi=200),
            _make_chain_quote(102.5, "put", oi=200),
        ]
        ctx = build_chain_context("SPY", chain, 103.0)
        assert ctx is not None
        strikes = [s.strike for s in ctx.put_strikes]
        assert strikes == [100.0, 102.5, 105.0]

    def test_basic_fields(self):
        chain = [
            _make_chain_quote(100.0, "put", bid=2.0, ask=2.5, oi=300,
                              expiration=date(2026, 5, 1), lot_size=100),
        ]
        ctx = build_chain_context("AAPL", chain, 105.0)
        assert ctx is not None
        assert ctx.ticker == "AAPL"
        assert ctx.expiration == date(2026, 5, 1)
        assert ctx.lot_size == 100
        assert ctx.underlying_price == 105.0
        assert ctx.put_strikes[0].mid == pytest.approx(2.25)
