"""Tests for DXLink and symbol utility functions."""

from datetime import date

import pytest


class TestSymbolUtilities:
    """Tests for broker/tastytrade/symbols.py."""

    def test_build_streamer_symbol_call(self):
        from income_desk.broker.tastytrade.symbols import build_streamer_symbol

        result = build_streamer_symbol("SPY", date(2026, 3, 20), "call", 580.0)
        assert result == ".SPY260320C580"

    def test_build_streamer_symbol_put(self):
        from income_desk.broker.tastytrade.symbols import build_streamer_symbol

        result = build_streamer_symbol("GLD", date(2026, 6, 19), "put", 200.0)
        assert result == ".GLD260619P200"

    def test_parse_streamer_symbol_valid(self):
        from income_desk.broker.tastytrade.symbols import parse_streamer_symbol

        parsed = parse_streamer_symbol(".SPY260320P580")
        assert parsed is not None
        assert parsed.ticker == "SPY"
        assert parsed.expiration == date(2026, 3, 20)
        assert parsed.option_type == "put"
        assert parsed.strike == 580.0
        assert parsed.strike_key == "580P"
        assert parsed.cache_key == "580.00|put|2026-03-20"

    def test_parse_streamer_symbol_call(self):
        from income_desk.broker.tastytrade.symbols import parse_streamer_symbol

        parsed = parse_streamer_symbol(".QQQ260320C500")
        assert parsed is not None
        assert parsed.ticker == "QQQ"
        assert parsed.option_type == "call"
        assert parsed.strike == 500.0
        assert parsed.strike_key == "500C"

    def test_parse_streamer_symbol_invalid(self):
        from income_desk.broker.tastytrade.symbols import parse_streamer_symbol

        assert parse_streamer_symbol("SPY260320P580") is None  # missing dot
        assert parse_streamer_symbol("") is None
        assert parse_streamer_symbol(".spy260320P580") is None  # lowercase

    def test_roundtrip_build_parse(self):
        from income_desk.broker.tastytrade.symbols import (
            build_streamer_symbol,
            parse_streamer_symbol,
        )

        original = build_streamer_symbol("AAPL", date(2026, 4, 17), "call", 200.0)
        parsed = parse_streamer_symbol(original)
        assert parsed is not None
        assert parsed.ticker == "AAPL"
        assert parsed.expiration == date(2026, 4, 17)
        assert parsed.option_type == "call"
        assert parsed.strike == 200.0

    def test_occ_to_streamer(self):
        from income_desk.broker.tastytrade.symbols import occ_to_streamer

        result = occ_to_streamer("SPY   260320P00580000")
        assert result == ".SPY260320P580"

    def test_occ_to_streamer_invalid(self):
        from income_desk.broker.tastytrade.symbols import occ_to_streamer

        assert occ_to_streamer("short") is None
        assert occ_to_streamer("") is None

    def test_streamer_to_occ(self):
        from income_desk.broker.tastytrade.symbols import streamer_to_occ

        result = streamer_to_occ(".SPY260320P580")
        assert result is not None
        assert result.startswith("SPY")
        assert "260320" in result
        assert "P" in result
        assert result.endswith("00580000")

    def test_streamer_to_occ_invalid(self):
        from income_desk.broker.tastytrade.symbols import streamer_to_occ

        assert streamer_to_occ("invalid") is None

    def test_roundtrip_occ(self):
        from income_desk.broker.tastytrade.symbols import (
            occ_to_streamer,
            streamer_to_occ,
        )

        streamer = ".SPY260320C600"
        occ = streamer_to_occ(streamer)
        assert occ is not None
        back = occ_to_streamer(occ)
        assert back == streamer

    def test_leg_to_streamer_symbol_with_ticker(self):
        from unittest.mock import MagicMock

        from income_desk.broker.tastytrade.symbols import leg_to_streamer_symbol

        leg = MagicMock()
        leg.expiration = date(2026, 3, 20)
        leg.option_type = "put"
        leg.strike = 570.0

        result = leg_to_streamer_symbol("SPY", leg)
        assert result == ".SPY260320P570"

    def test_parsed_symbol_cache_key_format(self):
        from income_desk.broker.tastytrade.symbols import parse_streamer_symbol

        parsed = parse_streamer_symbol(".GLD260619P200")
        assert parsed is not None
        # Cache key matches OptionQuoteService._leg_cache_key format
        assert parsed.cache_key == "200.00|put|2026-06-19"


class TestDXLinkErrorClassification:
    """Tests for dxlink.py error classification."""

    def test_classify_grant_revoked(self):
        from income_desk.broker.tastytrade.dxlink import DXLinkError, classify_error

        err = Exception("token invalid_grant error")
        assert classify_error(err) == DXLinkError.GRANT_REVOKED

    def test_classify_grant_revoked_alt(self):
        from income_desk.broker.tastytrade.dxlink import DXLinkError, classify_error

        err = Exception("Grant revoked for this token")
        assert classify_error(err) == DXLinkError.GRANT_REVOKED

    def test_classify_timeout(self):
        import asyncio

        from income_desk.broker.tastytrade.dxlink import DXLinkError, classify_error

        assert classify_error(asyncio.TimeoutError()) == DXLinkError.TIMEOUT
        assert classify_error(TimeoutError("timed out")) == DXLinkError.TIMEOUT

    def test_classify_connection(self):
        from income_desk.broker.tastytrade.dxlink import DXLinkError, classify_error

        err = Exception("WebSocket connection refused")
        assert classify_error(err) == DXLinkError.CONNECTION_FAILED

    def test_classify_unknown(self):
        from income_desk.broker.tastytrade.dxlink import DXLinkError, classify_error

        err = Exception("something weird happened")
        assert classify_error(err) == DXLinkError.UNKNOWN


class TestRunSync:
    """Tests for _async.py run_sync bridge."""

    def test_run_sync_simple_coroutine(self):
        from income_desk.broker.tastytrade._async import run_sync

        async def add(a, b):
            return a + b

        assert run_sync(add(2, 3)) == 5

    def test_run_sync_timeout(self):
        import asyncio

        from income_desk.broker.tastytrade._async import run_sync

        async def slow():
            await asyncio.sleep(10)
            return "done"

        with pytest.raises(TimeoutError):
            run_sync(slow(), timeout=0.1)

    def test_run_sync_exception_propagation(self):
        from income_desk.broker.tastytrade._async import run_sync

        async def fail():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            run_sync(fail())

    def test_run_sync_multiple_calls(self):
        """Multiple sequential calls reuse the persistent event loop."""
        from income_desk.broker.tastytrade._async import run_sync

        async def identity(x):
            return x

        results = [run_sync(identity(i)) for i in range(5)]
        assert results == [0, 1, 2, 3, 4]
