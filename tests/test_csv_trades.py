"""Tests for income_desk.adapters.csv_trades — broker CSV import."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from income_desk.adapters.csv_trades import (
    ImportedPosition,
    ImportResult,
    _extract_account_from_filename,
    _parse_fidelity_symbol,
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


# ---------------------------------------------------------------------------
# _parse_fidelity_symbol
# ---------------------------------------------------------------------------

_FIDELITY_HDR = (
    "Account Number,Account Name,Symbol,Description,Quantity,Last Price,"
    "Last Price Change,Current Value,Today's Gain/Loss Dollar,"
    "Today's Gain/Loss Percent,Total Gain/Loss Dollar,Total Gain/Loss Percent,"
    "Percent Of Account,Cost Basis Total,Average Cost Basis,Type\n"
)


class TestParseFidelitySymbol:
    def test_call_option(self) -> None:
        ticker, opt_type, strike, exp = _parse_fidelity_symbol(" -META260424C625")
        assert ticker == "META"
        assert opt_type == "call"
        assert strike == pytest.approx(625.0)
        assert exp == date(2026, 4, 24)

    def test_put_option(self) -> None:
        ticker, opt_type, strike, exp = _parse_fidelity_symbol(" -SPY260321P570")
        assert ticker == "SPY"
        assert opt_type == "put"
        assert strike == pytest.approx(570.0)
        assert exp == date(2026, 3, 21)

    def test_plain_equity(self) -> None:
        ticker, opt_type, strike, exp = _parse_fidelity_symbol("GBTC")
        assert ticker == "GBTC"
        assert opt_type is None
        assert strike is None
        assert exp is None

    def test_option_no_leading_space(self) -> None:
        ticker, opt_type, strike, exp = _parse_fidelity_symbol("-META260424C625")
        assert ticker == "META"
        assert opt_type == "call"
        assert strike == pytest.approx(625.0)


# ---------------------------------------------------------------------------
# import_trades_csv — fidelity_positions (synthetic)
# ---------------------------------------------------------------------------


class TestFidelityPositionsFormat:
    def test_fidelity_positions_detection(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "fidelity_pos.csv"
        csv_file.write_text(
            _FIDELITY_HDR
            + "123,IRA,AAPL,APPLE INC,50,$210.00,+$2.00,$10500.00,+$100.00,+0.96%,"
            "+$500.00,+5.00%,10.00%,$10000.00,$200.00,Cash,\n"
        )
        assert detect_broker_format(csv_file) == "fidelity_positions"

    def test_equity_long_imported(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "fidelity_pos.csv"
        csv_file.write_text(
            _FIDELITY_HDR
            + "123,IRA,AAPL,APPLE INC,50,$210.00,+$2.00,$10500.00,+$100.00,+0.96%,"
            "+$500.00,+5.00%,10.00%,$10000.00,$200.00,Cash,\n"
        )
        result = import_trades_csv(csv_file)
        assert result.broker_detected == "fidelity_positions"
        assert result.total_imported == 1
        aapl = result.positions[0]
        assert aapl.ticker == "AAPL"
        assert aapl.quantity == 50
        assert aapl.entry_price == pytest.approx(200.0)
        assert aapl.structure_type == "equity_long"
        assert aapl.broker_source == "fidelity_positions"

    def test_option_leg_imported(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "fidelity_pos.csv"
        csv_file.write_text(
            _FIDELITY_HDR
            + "123,IRA, -SPY260424C580,SPY APR 24 2026 $580 CALL,-1,$5.00,-$1.00,"
            "-$500.00,+$100.00,+16.67%,+$200.00,+28.57%,-0.50%,$700.00,$7.00,Margin,\n"
        )
        result = import_trades_csv(csv_file)
        assert result.total_imported == 1
        spy = result.positions[0]
        assert spy.ticker == "SPY"
        assert spy.option_type == "call"
        assert spy.strike == pytest.approx(580.0)
        assert spy.expiration == date(2026, 4, 24)
        assert spy.quantity == -1
        assert spy.entry_price == pytest.approx(7.0)
        assert spy.structure_type == "option_single_leg"

    def test_skips_spaxx_and_pending(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "fidelity_pos.csv"
        csv_file.write_text(
            _FIDELITY_HDR
            + "123,IRA,SPAXX**,HELD IN MONEY MARKET,,,,$50000.00,,,,,50.00%,,,Cash,\n"
            + "123,IRA,Pending activity,,,,,$2000.00,,,,,,,,,\n"
        )
        result = import_trades_csv(csv_file)
        assert result.total_imported == 0
        assert result.skipped >= 2

    def test_mixed_positions(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "fidelity_pos.csv"
        csv_file.write_text(
            _FIDELITY_HDR
            + "123,IRA,AAPL,APPLE INC,50,$210.00,+$2.00,$10500.00,+$100.00,+0.96%,"
            "+$500.00,+5.00%,10.00%,$10000.00,$200.00,Cash,\n"
            + "123,IRA, -SPY260424C580,SPY APR 24 2026 $580 CALL,-1,$5.00,-$1.00,"
            "-$500.00,+$100.00,+16.67%,+$200.00,+28.57%,-0.50%,$700.00,$7.00,Margin,\n"
            + "123,IRA,SPAXX**,HELD IN MONEY MARKET,,,,$50000.00,,,,,50.00%,,,Cash,\n"
        )
        result = import_trades_csv(csv_file)
        assert result.broker_detected == "fidelity_positions"
        assert result.total_imported == 2
        tickers = {p.ticker for p in result.positions}
        assert "AAPL" in tickers
        assert "SPY" in tickers

    def test_footer_disclaimer_skipped(self, tmp_path: Path) -> None:
        """Fidelity appends multi-line disclaimer text — should not crash or import."""
        csv_file = tmp_path / "fidelity_pos.csv"
        csv_file.write_text(
            _FIDELITY_HDR
            + "123,IRA,GBTC,GRAYSCALE BITCOIN TRUST ETF,108,$54.65,-$0.06,"
            "$5902.20,-$6.48,-0.11%,-$3493.80,-37.19%,3.24%,$9396.00,$87.00,Cash,\n"
            + "\n"
            + '"The data and information in this spreadsheet is provided to you solely"\n'
        )
        result = import_trades_csv(csv_file)
        assert result.total_imported == 1
        assert result.errors == []


# ---------------------------------------------------------------------------
# import_trades_csv — real Fidelity CSV (integration, skipped if absent)
# ---------------------------------------------------------------------------


class TestRealFidelityImport:
    _REAL_CSV = Path(
        r"C:\Users\nitin\PythonProjects\eTrading\data\imports"
        r"\Portfolio_Positions_Mar-22-2026.csv"
    )

    def test_format_detection(self) -> None:
        if not self._REAL_CSV.exists():
            pytest.skip("Real Fidelity CSV not available")
        assert detect_broker_format(self._REAL_CSV) == "fidelity_positions"

    def test_real_fidelity_csv(self) -> None:
        if not self._REAL_CSV.exists():
            pytest.skip("Real Fidelity CSV not available")

        result = import_trades_csv(self._REAL_CSV)
        assert result.broker_detected == "fidelity_positions"
        # GBTC + 4 META IC legs = 5 minimum
        assert result.total_imported >= 5
        assert result.errors == []

        # META IC: all 4 legs present
        meta = [p for p in result.positions if p.ticker == "META"]
        assert len(meta) == 4

        calls = [p for p in meta if p.option_type == "call"]
        puts = [p for p in meta if p.option_type == "put"]
        assert len(calls) == 2
        assert len(puts) == 2

        strikes = sorted(p.strike for p in meta)
        assert strikes == [580.0, 590.0, 625.0, 635.0]

        # IC structure: short 625C, long 635C, long 580P, short 590P
        short_calls = [p for p in calls if p.quantity < 0]
        long_calls = [p for p in calls if p.quantity > 0]
        short_puts = [p for p in puts if p.quantity < 0]
        long_puts = [p for p in puts if p.quantity > 0]
        assert len(short_calls) == 1 and short_calls[0].strike == pytest.approx(625.0)
        assert len(long_calls) == 1 and long_calls[0].strike == pytest.approx(635.0)
        assert len(short_puts) == 1 and short_puts[0].strike == pytest.approx(590.0)
        assert len(long_puts) == 1 and long_puts[0].strike == pytest.approx(580.0)

        # GBTC equity position
        gbtc = [p for p in result.positions if p.ticker == "GBTC"]
        assert len(gbtc) == 1
        assert gbtc[0].quantity == 108
        assert gbtc[0].structure_type == "equity_long"
        assert gbtc[0].entry_price == pytest.approx(87.0)


# ---------------------------------------------------------------------------
# Account number extraction
# ---------------------------------------------------------------------------


class TestAccountNumberExtraction:
    def test_fidelity_positions_from_column(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "fidelity_pos.csv"
        csv_file.write_text(
            _FIDELITY_HDR
            + "259510977,IRA,AAPL,APPLE INC,50,$210.00,+$2.00,$10500.00,+$100.00,"
            "+0.96%,+$500.00,+5.00%,10.00%,$10000.00,$200.00,Cash,\n"
        )
        result = import_trades_csv(csv_file)
        assert result.account_number == "259510977"

    def test_fidelity_from_filename(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "Portfolio_Positions_259-510977.csv"
        csv_file.write_text(
            _FIDELITY_HDR
            + ",IRA,AAPL,APPLE INC,50,$210.00,+$2.00,$10500.00,+$100.00,"
            "+0.96%,+$500.00,+5.00%,10.00%,$10000.00,$200.00,Cash,\n"
        )
        result = import_trades_csv(csv_file)
        assert result.account_number == "259510977"

    def test_tastytrade_account_column(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "tt.csv"
        csv_file.write_text(
            "Date,Action,Symbol,Instrument Type,Value,Quantity,Average Price,Account Number\n"
            "2026-01-15T10:30:00,SELL_TO_OPEN,SPY 04/24/26 C 580,Equity Option,-350,-1,3.50,5WT12345\n"
        )
        result = import_trades_csv(csv_file)
        assert result.account_number == "5WT12345"

    def test_ibkr_account_column(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "ibkr.csv"
        csv_file.write_text(
            "TradeDate,Symbol,Put/Call,Strike,Expiry,Quantity,Price,Buy/Sell,Account\n"
            "20260115,SPY,C,580,20260424,1,3.50,BUY,U1234567\n"
        )
        result = import_trades_csv(csv_file)
        assert result.account_number == "U1234567"

    def test_no_account_returns_none(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "generic.csv"
        csv_file.write_text(
            "symbol,date,quantity,price\n"
            "SPY,2026-01-15,100,580.00\n"
        )
        result = import_trades_csv(csv_file)
        assert result.account_number is None

    def test_filename_extraction_helper(self, tmp_path: Path) -> None:
        p = tmp_path / "Portfolio_Positions_259-510977.csv"
        p.touch()
        assert _extract_account_from_filename(p) == "259510977"

    def test_filename_no_match(self, tmp_path: Path) -> None:
        p = tmp_path / "trades.csv"
        p.touch()
        assert _extract_account_from_filename(p) is None

    def test_missing_file_no_account(self) -> None:
        result = import_trades_csv("/nonexistent/path/trades.csv")
        assert result.account_number is None

    def test_unknown_format_no_account(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "unknown.csv"
        csv_file.write_text("foo,bar,baz\n1,2,3\n")
        result = import_trades_csv(csv_file)
        assert result.account_number is None
