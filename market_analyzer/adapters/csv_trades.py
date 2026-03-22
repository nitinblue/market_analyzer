"""Import trades from broker CSV exports.

Supports: thinkorswim, TastyTrade, Fidelity, Schwab, IBKR, Webull, generic.
Users export trade history from their broker, income-desk parses it into positions.

Usage:
    from market_analyzer.adapters.csv_trades import import_trades_csv, detect_broker_format

    positions = import_trades_csv("path/to/trades.csv")
    # Returns ImportResult with list of ImportedPosition objects

    # Or detect format first:
    fmt = detect_broker_format("path/to/trades.csv")
    print(f"Detected: {fmt}")  # "thinkorswim", "tastytrade", "generic", etc.
"""
from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel


class ImportedPosition(BaseModel):
    """A position parsed from a broker CSV export."""

    ticker: str
    option_type: str | None       # "call", "put", None for equity
    strike: float | None
    expiration: date | None
    quantity: int                  # Positive = long, negative = short
    entry_price: float
    entry_date: date
    structure_type: str            # "iron_condor", "credit_spread", "equity_long", "option_single_leg", etc.
    broker_source: str             # "thinkorswim", "tastytrade", etc.
    raw_symbol: str                # Original symbol from CSV


class ImportResult(BaseModel):
    """Result of a CSV import operation."""

    positions: list[ImportedPosition]
    total_imported: int
    skipped: int
    errors: list[str]
    broker_detected: str
    file_path: str


# Column name mappings for each broker format.
# "detect" lists columns that uniquely identify the broker format.
_BROKER_FORMATS: dict[str, dict] = {
    "thinkorswim": {
        "detect": ["Trade Date", "Spread", "Side", "Qty", "Pos Effect"],
        "date_col": "Trade Date",
        "symbol_col": "Symbol",
        "qty_col": "Qty",
        "price_col": "Price",
        "side_col": "Side",
        "date_format": "%m/%d/%Y",
    },
    "tastytrade": {
        "detect": ["Date", "Action", "Symbol", "Instrument Type", "Value"],
        "date_col": "Date",
        "symbol_col": "Symbol",
        "qty_col": "Quantity",
        "price_col": "Average Price",
        "side_col": "Action",
        "date_format": "%Y-%m-%dT%H:%M:%S",
    },
    "schwab": {
        "detect": ["Date", "Action", "Symbol", "Description", "Quantity", "Price"],
        "date_col": "Date",
        "symbol_col": "Symbol",
        "qty_col": "Quantity",
        "price_col": "Price",
        "side_col": "Action",
        "date_format": "%m/%d/%Y",
    },
    "ibkr": {
        "detect": ["TradeDate", "Symbol", "Put/Call", "Strike", "Expiry", "Quantity"],
        "date_col": "TradeDate",
        "symbol_col": "Symbol",
        "qty_col": "Quantity",
        "price_col": "Price",
        "side_col": "Buy/Sell",
        "date_format": "%Y%m%d",
    },
    "fidelity_positions": {
        "detect": ["Account Number", "Account Name", "Symbol", "Description", "Quantity", "Last Price", "Cost Basis Total"],
        "date_col": None,
        "symbol_col": "Symbol",
        "qty_col": "Quantity",
        "price_col": "Average Cost Basis",
        "side_col": None,
        "date_format": None,
    },
    "fidelity": {
        "detect": ["Run Date", "Action", "Symbol", "Description", "Quantity", "Price"],
        "date_col": "Run Date",
        "symbol_col": "Symbol",
        "qty_col": "Quantity",
        "price_col": "Price",
        "side_col": "Action",
        "date_format": "%m/%d/%Y",
    },
    "webull": {
        "detect": ["Filled Time", "Symbol", "Side", "Filled Qty", "Avg Filled Price"],
        "date_col": "Filled Time",
        "symbol_col": "Symbol",
        "qty_col": "Filled Qty",
        "price_col": "Avg Filled Price",
        "side_col": "Side",
        "date_format": "%m/%d/%Y %H:%M:%S",
    },
}


def detect_broker_format(file_path: str | Path) -> str:
    """Detect which broker exported this CSV by inspecting column headers.

    Returns one of: "thinkorswim", "tastytrade", "schwab", "ibkr",
    "fidelity", "webull", "generic", or "unknown".
    """
    path = Path(file_path)
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                return "unknown"
    except OSError:
        return "unknown"

    headers_set = {h.strip() for h in headers}

    for broker, fmt in _BROKER_FORMATS.items():
        detect_cols: list[str] = fmt["detect"]
        if all(col in headers_set for col in detect_cols):
            return broker

    # Generic: lowercase column check
    generic_cols = {"symbol", "date", "price", "quantity"}
    lower_headers = {h.lower().strip() for h in headers}
    if generic_cols.issubset(lower_headers):
        return "generic"

    return "unknown"


def import_trades_csv(
    file_path: str | Path,
    broker: str | None = None,
) -> ImportResult:
    """Import trades from a broker CSV export.

    Auto-detects broker format if *broker* is not specified.
    Returns :class:`ImportResult` with all parsed positions.

    Args:
        file_path: Path to the CSV file exported from the broker.
        broker: Force a specific broker parser.  When ``None`` the format
            is auto-detected from the CSV headers.

    Returns:
        :class:`ImportResult` — positions, counts, and any parse errors.
    """
    path = Path(file_path)

    if not path.exists():
        return ImportResult(
            positions=[],
            total_imported=0,
            skipped=0,
            errors=[f"File not found: {path}"],
            broker_detected="unknown",
            file_path=str(path),
        )

    if broker is None:
        broker = detect_broker_format(path)

    if broker == "unknown":
        return ImportResult(
            positions=[],
            total_imported=0,
            skipped=0,
            errors=[
                "Could not detect broker format. "
                "Use broker= parameter or ensure CSV has standard headers."
            ],
            broker_detected="unknown",
            file_path=str(path),
        )

    if broker == "fidelity_positions":
        return _import_fidelity_positions(path)

    fmt = _BROKER_FORMATS.get(broker)
    if fmt is None:
        # Unknown named broker — fall back to generic parser
        return _import_generic(path, broker)

    if broker == "generic":
        return _import_generic(path, broker)

    positions: list[ImportedPosition] = []
    errors: list[str] = []
    skipped = 0

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, 2):
            try:
                pos = _parse_row(row, fmt, broker)
                if pos is not None:
                    positions.append(pos)
                else:
                    skipped += 1
            except Exception as exc:
                errors.append(f"Row {row_num}: {exc}")
                skipped += 1

    return ImportResult(
        positions=positions,
        total_imported=len(positions),
        skipped=skipped,
        errors=errors,
        broker_detected=broker,
        file_path=str(path),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_row(row: dict[str, str], fmt: dict, broker: str) -> ImportedPosition | None:
    """Parse a single CSV row using a broker format descriptor."""
    symbol = row.get(fmt["symbol_col"], "").strip()
    if not symbol:
        return None

    qty_raw = row.get(fmt["qty_col"], "0").strip().replace(",", "")
    try:
        qty = int(float(qty_raw))
    except ValueError:
        return None

    if qty == 0:
        return None

    price_raw = row.get(fmt["price_col"], "0").strip().replace("$", "").replace(",", "")
    try:
        price = abs(float(price_raw))
    except ValueError:
        price = 0.0

    date_str = row.get(fmt["date_col"], "").strip()
    entry_date = _parse_date(date_str, fmt["date_format"])

    ticker, option_type, strike, expiration = _parse_symbol(symbol, broker)

    if option_type:
        structure = "option_single_leg"
    elif qty > 0:
        structure = "equity_long"
    else:
        structure = "equity_short"

    return ImportedPosition(
        ticker=ticker,
        option_type=option_type,
        strike=strike,
        expiration=expiration,
        quantity=qty,
        entry_price=price,
        entry_date=entry_date,
        structure_type=structure,
        broker_source=broker,
        raw_symbol=symbol,
    )


def _parse_date(date_str: str, fmt: str) -> date:
    """Parse a date string; fall back to today on any parse error."""
    try:
        return datetime.strptime(date_str, fmt).date()
    except (ValueError, TypeError):
        return date.today()


def _parse_symbol(
    symbol: str, broker: str
) -> tuple[str, str | None, float | None, date | None]:
    """Parse an option symbol into (ticker, option_type, strike, expiration).

    Handles three common formats:
    - OCC:        ``SPY   260424C00580000``  (also with leading dot)
    - thinkorswim: ``.SPY260424C580``
    - TastyTrade: ``SPY 04/24/26 C 580``
    - Plain equity: ``SPY``
    """
    clean = symbol.strip()

    # OCC format: optional dot, ticker (1-6 chars), YYMMDD, C/P, 8-digit strike*1000
    occ_match = re.match(
        r"\.?([A-Z]{1,6})\s*(\d{6})([CP])(\d+)", clean.replace(" ", "")
    )
    if occ_match:
        ticker = occ_match.group(1)
        exp_str = occ_match.group(2)
        option_type = "call" if occ_match.group(3) == "C" else "put"
        strike = int(occ_match.group(4)) / 1000
        exp = _parse_date(exp_str, "%y%m%d")
        return ticker, option_type, strike, exp

    # TastyTrade format: SPY 04/24/26 C 580
    tt_match = re.match(
        r"([A-Z]{1,6})\s+(\d{2}/\d{2}/\d{2})\s+([CP])\s+([\d.]+)", clean
    )
    if tt_match:
        ticker = tt_match.group(1)
        option_type = "call" if tt_match.group(3) == "C" else "put"
        strike = float(tt_match.group(4))
        exp = _parse_date(tt_match.group(2), "%m/%d/%y")
        return ticker, option_type, strike, exp

    # Plain equity symbol — strip leading dot (ToS sometimes prefixes)
    ticker = clean.split()[0].lstrip(".")
    return ticker, None, None, None


def _parse_fidelity_symbol(
    symbol: str,
) -> tuple[str, str | None, float | None, date | None]:
    """Parse Fidelity option symbol format.

    Examples::

        " -META260424C625"  → META, call, 625.0, 2026-04-24
        "GBTC"              → GBTC, None, None, None
        " -SPY260321P570"   → SPY, put, 570.0, 2026-03-21
    """
    # Strip leading whitespace and dash (Fidelity prefixes options with " -")
    clean = symbol.strip().lstrip("-").strip()

    # Try option pattern: TICKER + YYMMDD + C/P + STRIKE (no zero-padding)
    match = re.match(r"([A-Z]{1,6})(\d{6})([CP])(\d+\.?\d*)", clean)
    if match:
        ticker = match.group(1)
        exp_str = match.group(2)
        opt_type = "call" if match.group(3) == "C" else "put"
        strike = float(match.group(4))
        try:
            exp: date | None = datetime.strptime(exp_str, "%y%m%d").date()
        except ValueError:
            exp = None
        return ticker, opt_type, strike, exp

    # Plain equity
    return clean, None, None, None


def _import_fidelity_positions(path: Path) -> ImportResult:
    """Parse Fidelity portfolio positions CSV (positions export format)."""
    positions: list[ImportedPosition] = []
    errors: list[str] = []
    skipped = 0

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, 2):
            # DictReader may return None key when trailing commas produce extra fields;
            # also stop on footer/disclaimer rows that lack a real Symbol column.
            if row.get("Symbol") is None and row.get("Account Number") is None:
                skipped += 1
                continue

            symbol = (row.get("Symbol") or "").strip()

            # Skip cash/money-market, pending-activity, and blank rows.
            if (
                not symbol
                or "SPAXX" in symbol
                or symbol.lower().startswith("pending")
            ):
                skipped += 1
                continue

            # Parse quantity
            qty_str = (row.get("Quantity") or "").strip().replace(",", "")
            try:
                qty = int(float(qty_str))
            except (ValueError, TypeError):
                skipped += 1
                continue

            if qty == 0:
                skipped += 1
                continue

            # Parse average cost basis as entry price (strip $, +, commas)
            price_str = (row.get("Average Cost Basis") or "").strip()
            price_str = price_str.replace("$", "").replace("+", "").replace(",", "")
            try:
                price = abs(float(price_str))
            except (ValueError, TypeError):
                price = 0.0

            # Parse symbol
            ticker, opt_type, strike, exp = _parse_fidelity_symbol(symbol)

            if opt_type:
                structure = "option_single_leg"
            elif qty > 0:
                structure = "equity_long"
            else:
                structure = "equity_short"

            try:
                positions.append(
                    ImportedPosition(
                        ticker=ticker,
                        option_type=opt_type,
                        strike=strike,
                        expiration=exp,
                        quantity=qty,
                        entry_price=price,
                        entry_date=date.today(),
                        structure_type=structure,
                        broker_source="fidelity_positions",
                        raw_symbol=symbol,
                    )
                )
            except Exception as exc:
                errors.append(f"Row {row_num}: {exc}")
                skipped += 1

    return ImportResult(
        positions=positions,
        total_imported=len(positions),
        skipped=skipped,
        errors=errors,
        broker_detected="fidelity_positions",
        file_path=str(path),
    )


def _import_generic(path: Path, broker: str) -> ImportResult:
    """Fallback parser for generic CSV files with lowercase column names."""
    positions: list[ImportedPosition] = []
    errors: list[str] = []
    skipped = 0

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, 2):
            # Normalise keys to lowercase for flexible matching
            norm = {k.lower().strip(): v for k, v in row.items()}
            try:
                symbol = norm.get("symbol", "").strip()
                if not symbol:
                    skipped += 1
                    continue

                qty_raw = norm.get("quantity", norm.get("qty", "0")).strip().replace(",", "")
                qty = int(float(qty_raw))
                if qty == 0:
                    skipped += 1
                    continue

                price_raw = (
                    norm.get("price", "0").strip().replace("$", "").replace(",", "")
                )
                price = abs(float(price_raw))

                date_raw = norm.get("date", "").strip()
                entry_date = _parse_date(date_raw, "%Y-%m-%d")

                ticker, opt_type, strike, exp = _parse_symbol(symbol, "generic")

                if opt_type:
                    structure = "option_single_leg"
                elif qty > 0:
                    structure = "equity_long"
                else:
                    structure = "equity_short"

                positions.append(
                    ImportedPosition(
                        ticker=ticker,
                        option_type=opt_type,
                        strike=strike,
                        expiration=exp,
                        quantity=qty,
                        entry_price=price,
                        entry_date=entry_date,
                        structure_type=structure,
                        broker_source=broker,
                        raw_symbol=symbol,
                    )
                )
            except Exception as exc:
                errors.append(f"Row {row_num}: {exc}")
                skipped += 1

    return ImportResult(
        positions=positions,
        total_imported=len(positions),
        skipped=skipped,
        errors=errors,
        broker_detected=broker,
        file_path=str(path),
    )
