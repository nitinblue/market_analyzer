"""Tests for market_analyzer.adapters.csv_trades — broker CSV import."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from market_analyzer.adapters.csv_trades import (
    ImportedPosition,
    ImportResult,
    _parse_symbol,
    detect_broker_format,
    import_trades_csv,
)


# ---------------------------------------------------------------------------
# detect_broker_format
# ---------------------------------------------------------------------------


class TestDetectBrokerFormat:
    def test_thinkorswim(self, tmp_path: Path) -> None:
        csv = tmp_path / "trades.csv"
        csv.write_text(
            "Trade Date,Spread,Side,Qty,Pos Effect,Symbol,Price\n"
            "01/15/2026,,BUY,1,TO OPEN,.SPY260424C580,3.50\n"
        )
        assert detect_broker_format(csv) == "thinkorswim"

    def test_tastytrade(self, tmp_path: Path) -> None:
        csv = tmp_path / "trades.csv"
        csv.write_text(
            "Date,Action,Symbol,Instrument Type,Value,Quantity,Average Price\n"
            "2026-01-15T10:30:00,BUY_TO_OPEN,SPY 04/24/26 C 580,Equity Option,350,1,3.50\n"
        )
        assert detect_broker_format(csv) == "tastytrade"

    def test_schwab(self, tmp_path: Path) -> None:
        csv = tmp_path / "trades.csv"
        csv.write_text(
            "Date,Action,Symbol,Description,Quantity,Price,Fees,Amount\n"
            "01/15/2026,Sell to Open,SPY,SPY IC,1,1.50,0.65,-150\n"
        )
        assert detect_broker_format(csv) == "schwab"

    def test_ibkr(self, tmp_path: Path) -> None:
        csv = tmp_path / "trades.csv"
        csv.write_text(
            "TradeDate,Symbol,Put/Call,Strike,Expiry,Quantity,Price,Buy/Sell\n"
            "20260115,SPY,C,580,20260424,1,3.50,BUY\n"
        )
        assert detect_broker_format(csv) == "ibkr"

    def test_fidelity(self, tmp_path: Path) -> None:
        csv = tmp_path / "trades.csv"
        csv.write_text(
            "Run Date,Action,Symbol,Description,Quantity,Price,Settlement Date\n"
            "01/15/2026,YOU BOUGHT,SPY,SPY STOCK,10,580.00,01/17/2026\n"
        )
        assert detect_broker_format(csv) == "fidelity"

    def test_webull(self, tmp_path: Path) -> None:
        csv = tmp_path / "trades.csv"
        csv.write_text(
            "Filled Time,Symbol,Side,Filled Qty,Avg Filled Price,Order Type\n"
            "01/15/2026 10:30:00,SPY,BUY,10,580.00,LIMIT\n"
        )
        assert detect_broker_format(csv) == "webull"

    def test_generic(self, tmp_path: Path) -> None:
        csv = tmp_path / "trades.csv"
        csv.write_text(
            "symbol,date,quantity,price\n"
            "SPY,2026-01-15,100,580.00\n"
        )
        assert detect_broker_format(csv) == "generic"

    def test_unknown(self, tmp_path: Path) -> None:
        csv = tmp_path / "trades.csv"
        csv.write_text("foo,bar,baz\n1,2,3\n")
        assert detect_broker_format(csv) == "unknown"

    def test_empty_file(self, tmp_path: Path) -> None:
        csv = tmp_path / "empty.csv"
        csv.write_text("")
        assert detect_broker_format(csv) == "unknown"

    def test_missing_file(self, tmp_path: Path) -> None:
        result = detect_broker_format(tmp_path / "nonexistent.csv")
        assert result == "unknown"


# ---------------------------------------------------------------------------
# _parse_symbol
# ---------------------------------------------------------------------------


class TestParseSymbol:
    def test_occ_call(self) -> None:
        ticker, opt_type, strike, exp = _parse_symbol("SPY   260424C00580000", "generic")
        assert ticker == "SPY"
        assert opt_type == "call"
        assert strike == pytest.approx(580.0)
        assert exp == date(2026, 4, 24)

    def test_occ_put_with_dot(self) -> None:
        ticker, opt_type, strike, exp = _parse_symbol(".SPY260424P00540000", "thinkorswim")
        assert ticker == "SPY"
        assert opt_type == "put"
        assert strike == pytest.approx(540.0)
        assert exp == date(2026, 4, 24)

    def test_tastytrade_call(self) -> None:
        ticker, opt_type, strike, exp = _parse_symbol(
            "SPY 04/24/26 C 580", "tastytrade"
        )
        assert ticker == "SPY"
        assert opt_type == "call"
        assert strike == pytest.approx(580.0)
        assert exp == date(2026, 4, 24)

    def test_tastytrade_put(self) -> None:
        ticker, opt_type, strike, exp = _parse_symbol(
            "QQQ 03/21/26 P 450", "tastytrade"
        )
        assert ticker == "QQQ"
        assert opt_type == "put"
        assert strike == pytest.approx(450.0)

    def test_plain_equity(self) -> None:
        ticker, opt_type, strike, exp = _parse_symbol("AAPL", "generic")
        assert ticker == "AAPL"
        assert opt_type is None
        assert strike is None
        assert exp is None

    def test_equity_with_dot_prefix(self) -> None:
        ticker, opt_type, strike, exp = _parse_symbol(".AAPL", "thinkorswim")
        assert ticker == "AAPL"
        assert opt_type is None

    def test_fractional_strike(self) -> None:
        ticker, opt_type, strike, exp = _parse_symbol("SPY   260424C00582500", "generic")
        assert strike == pytest.approx(582.5)


# ---------------------------------------------------------------------------
# import_trades_csv — thinkorswim
# ---------------------------------------------------------------------------


class TestImportThinkorswim:
    def test_basic_import(self, tmp_path: Path) -> None:
        csv = tmp_path / "tos.csv"
        csv.write_text(
            "Trade Date,Spread,Side,Qty,Pos Effect,Symbol,Price\n"
            "01/15/2026,,SELL,-1,TO OPEN,.SPY260424C00580000,3.50\n"
        )
        result = import_trades_csv(csv)
        assert result.broker_detected == "thinkorswim"
        assert result.total_imported == 1
        pos = result.positions[0]
        assert pos.ticker == "SPY"
        assert pos.option_type == "call"
        assert pos.strike == pytest.approx(580.0)
        assert pos.quantity == -1
        assert pos.entry_price == pytest.approx(3.50)
        assert pos.broker_source == "thinkorswim"

    def test_explicit_broker(self, tmp_path: Path) -> None:
        csv = tmp_path / "tos.csv"
        csv.write_text(
            "Trade Date,Spread,Side,Qty,Pos Effect,Symbol,Price\n"
            "01/15/2026,,BUY,2,TO OPEN,SPY,580.00\n"
        )
        result = import_trades_csv(csv, broker="thinkorswim")
        assert result.total_imported == 1
        assert result.positions[0].quantity == 2

    def test_zero_qty_skipped(self, tmp_path: Path) -> None:
        csv = tmp_path / "tos.csv"
        csv.write_text(
            "Trade Date,Spread,Side,Qty,Pos Effect,Symbol,Price\n"
            "01/15/2026,,BUY,0,TO OPEN,SPY,580.00\n"
        )
        result = import_trades_csv(csv)
        assert result.total_imported == 0
        assert result.skipped == 1


# ---------------------------------------------------------------------------
# import_trades_csv — tastytrade
# ---------------------------------------------------------------------------


class TestImportTastytrade:
    def test_basic_import(self, tmp_path: Path) -> None:
        csv = tmp_path / "tt.csv"
        csv.write_text(
            "Date,Action,Symbol,Instrument Type,Value,Quantity,Average Price\n"
            "2026-01-15T10:30:00,SELL_TO_OPEN,SPY 04/24/26 C 580,Equity Option,-350,-1,3.50\n"
        )
        result = import_trades_csv(csv)
        assert result.broker_detected == "tastytrade"
        assert result.total_imported == 1
        pos = result.positions[0]
        assert pos.ticker == "SPY"
        assert pos.option_type == "call"
        assert pos.strike == pytest.approx(580.0)

    def test_entry_date_parsed(self, tmp_path: Path) -> None:
        csv = tmp_path / "tt.csv"
        csv.write_text(
            "Date,Action,Symbol,Instrument Type,Value,Quantity,Average Price\n"
            "2026-03-10T09:45:00,BUY_TO_OPEN,QQQ 03/21/26 P 450,Equity Option,200,1,2.00\n"
        )
        result = import_trades_csv(csv)
        assert result.positions[0].entry_date == date(2026, 3, 10)


# ---------------------------------------------------------------------------
# import_trades_csv — Schwab
# ---------------------------------------------------------------------------


class TestImportSchwab:
    def test_basic_import(self, tmp_path: Path) -> None:
        csv = tmp_path / "schwab.csv"
        csv.write_text(
            "Date,Action,Symbol,Description,Quantity,Price,Fees,Amount\n"
            "01/15/2026,Sell to Open,SPY,SPY IC,-1,1.50,0.65,-150\n"
        )
        result = import_trades_csv(csv)
        assert result.broker_detected == "schwab"
        assert result.total_imported == 1


# ---------------------------------------------------------------------------
# import_trades_csv — IBKR
# ---------------------------------------------------------------------------


class TestImportIBKR:
    def test_basic_import(self, tmp_path: Path) -> None:
        csv = tmp_path / "ibkr.csv"
        csv.write_text(
            "TradeDate,Symbol,Put/Call,Strike,Expiry,Quantity,Price,Buy/Sell\n"
            "20260115,SPY,C,580,20260424,1,3.50,BUY\n"
        )
        result = import_trades_csv(csv)
        assert result.broker_detected == "ibkr"
        assert result.total_imported == 1


# ---------------------------------------------------------------------------
# import_trades_csv — generic
# ---------------------------------------------------------------------------


class TestImportGeneric:
    def test_basic_generic(self, tmp_path: Path) -> None:
        csv = tmp_path / "generic.csv"
        csv.write_text(
            "symbol,date,quantity,price\n"
            "SPY,2026-01-15,100,580.00\n"
            "AAPL,2026-01-15,50,210.00\n"
        )
        result = import_trades_csv(csv)
        assert result.broker_detected == "generic"
        assert result.total_imported == 2
        tickers = {p.ticker for p in result.positions}
        assert "SPY" in tickers
        assert "AAPL" in tickers

    def test_equity_structure_long(self, tmp_path: Path) -> None:
        csv = tmp_path / "generic.csv"
        csv.write_text(
            "symbol,date,quantity,price\n"
            "SPY,2026-01-15,100,580.00\n"
        )
        result = import_trades_csv(csv)
        assert result.positions[0].structure_type == "equity_long"

    def test_equity_structure_short(self, tmp_path: Path) -> None:
        csv = tmp_path / "generic.csv"
        csv.write_text(
            "symbol,date,quantity,price\n"
            "SPY,2026-01-15,-10,580.00\n"
        )
        result = import_trades_csv(csv)
        assert result.positions[0].structure_type == "equity_short"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_missing_file(self) -> None:
        result = import_trades_csv("/nonexistent/path/trades.csv")
        assert result.total_imported == 0
        assert len(result.errors) > 0
        assert result.broker_detected == "unknown"

    def test_unknown_format(self, tmp_path: Path) -> None:
        csv = tmp_path / "unknown.csv"
        csv.write_text("foo,bar,baz\n1,2,3\n")
        result = import_trades_csv(csv)
        assert result.total_imported == 0
        assert result.broker_detected == "unknown"
        assert any("Could not detect" in e for e in result.errors)

    def test_explicit_unknown_broker_falls_back_to_generic(
        self, tmp_path: Path
    ) -> None:
        csv = tmp_path / "trades.csv"
        csv.write_text(
            "symbol,date,quantity,price\n"
            "SPY,2026-01-15,10,580.00\n"
        )
        # Passing an unknown broker name falls back to generic parsing
        result = import_trades_csv(csv, broker="my_custom_broker")
        # Generic parser should pick up the rows
        assert result.total_imported >= 1

    def test_import_result_model(self, tmp_path: Path) -> None:
        csv = tmp_path / "trades.csv"
        csv.write_text(
            "symbol,date,quantity,price\n"
            "SPY,2026-01-15,10,580.00\n"
        )
        result = import_trades_csv(csv)
        assert isinstance(result, ImportResult)
        assert isinstance(result.positions[0], ImportedPosition)

    def test_bom_utf8_header(self, tmp_path: Path) -> None:
        """Files with BOM (Excel exports) should still be parsed correctly."""
        csv = tmp_path / "bom.csv"
        # Write with BOM manually
        csv.write_bytes(
            b"\xef\xbb\xbfsymbol,date,quantity,price\n"
            b"SPY,2026-01-15,10,580.00\n"
        )
        result = import_trades_csv(csv)
        assert result.total_imported == 1
