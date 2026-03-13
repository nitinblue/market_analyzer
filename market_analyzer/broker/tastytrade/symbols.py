"""Streamer symbol utilities — conversion between formats.

DXLink streamer symbol format: ``.{TICKER}{YYMMDD}{C|P}{STRIKE}``
  e.g. ``.SPY260320P580``

OCC format: ``{TICKER:6}{YYMMDD}{C|P}{STRIKE*1000:08d}``
  e.g. ``SPY   260320P00580000``

Same conventions as eTrading ``tastytrade_adapter.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_analyzer.models.opportunity import LegSpec

# Pattern: .TICKER YYMMDD C|P STRIKE
_STREAMER_RE = re.compile(
    r"^\.([A-Z]+)(\d{6})([CP])(\d+)$"
)


@dataclass(frozen=True)
class ParsedSymbol:
    """Parsed components of a streamer symbol."""

    ticker: str
    expiration: date
    option_type: str  # "call" | "put"
    strike: float
    raw: str

    @property
    def strike_key(self) -> str:
        """Short key: ``580P`` or ``600C``."""
        return f"{int(self.strike)}{self.option_type[0].upper()}"

    @property
    def cache_key(self) -> str:
        """Unique key for caching: ``580.00|put|2026-03-20``."""
        return f"{self.strike:.2f}|{self.option_type}|{self.expiration}"


def build_streamer_symbol(
    ticker: str,
    expiration: date,
    option_type: str,
    strike: float,
) -> str:
    """Build a DXLink streamer symbol from components.

    Args:
        ticker: Underlying ticker (e.g. "SPY").
        expiration: Option expiration date.
        option_type: "call" or "put".
        strike: Strike price.

    Returns:
        Streamer symbol like ``.SPY260320P580``.
    """
    exp_str = expiration.strftime("%y%m%d")
    opt_char = "C" if option_type == "call" else "P"
    strike_int = int(strike)
    return f".{ticker}{exp_str}{opt_char}{strike_int}"


def parse_streamer_symbol(symbol: str) -> ParsedSymbol | None:
    """Parse a DXLink streamer symbol into components.

    Args:
        symbol: e.g. ``.SPY260320P580``

    Returns:
        ParsedSymbol or None if format doesn't match.
    """
    m = _STREAMER_RE.match(symbol)
    if not m:
        return None
    ticker, exp_str, opt_char, strike_str = m.groups()
    exp = date(
        year=2000 + int(exp_str[:2]),
        month=int(exp_str[2:4]),
        day=int(exp_str[4:6]),
    )
    return ParsedSymbol(
        ticker=ticker,
        expiration=exp,
        option_type="call" if opt_char == "C" else "put",
        strike=float(strike_str),
        raw=symbol,
    )


def leg_to_streamer_symbol(ticker: str, leg: LegSpec) -> str:
    """Convert a LegSpec + known ticker to a DXLink streamer symbol.

    This is the preferred method — the ticker is explicit, not parsed
    from ``leg.strike_label``.
    """
    return build_streamer_symbol(
        ticker=ticker,
        expiration=leg.expiration,
        option_type=leg.option_type,
        strike=leg.strike,
    )


def leg_to_streamer_symbol_from_label(leg: LegSpec) -> str | None:
    """Convert a LegSpec to a DXLink streamer symbol using strike_label.

    Parses ticker from ``leg.strike_label`` (e.g. "580 SPY").
    Returns None if ticker can't be inferred.
    """
    try:
        parts = (leg.strike_label or "").split()
        if len(parts) < 2:
            return None
        ticker = parts[1]
        if ticker.lower() in ("put", "call"):
            return None
        return build_streamer_symbol(
            ticker=ticker,
            expiration=leg.expiration,
            option_type=leg.option_type,
            strike=leg.strike,
        )
    except Exception:
        return None


def occ_to_streamer(occ: str) -> str | None:
    """Convert OCC symbol to DXLink streamer symbol.

    OCC format: ``SPY   260320P00580000`` (6-char ticker, YYMMDD, C/P, 8-digit strike*1000)
    Streamer format: ``.SPY260320P580``
    """
    occ = occ.strip()
    if len(occ) < 21:
        return None
    ticker = occ[:6].strip()
    exp_str = occ[6:12]
    opt_char = occ[12]
    strike_raw = occ[13:21]
    try:
        strike = int(strike_raw) / 1000
        return f".{ticker}{exp_str}{opt_char}{int(strike)}"
    except ValueError:
        return None


def streamer_to_occ(symbol: str) -> str | None:
    """Convert DXLink streamer symbol to OCC format.

    Streamer: ``.SPY260320P580`` → OCC: ``SPY   260320P00580000``
    """
    parsed = parse_streamer_symbol(symbol)
    if not parsed:
        return None
    ticker_padded = parsed.ticker.ljust(6)
    exp_str = parsed.expiration.strftime("%y%m%d")
    opt_char = "C" if parsed.option_type == "call" else "P"
    strike_1000 = int(parsed.strike * 1000)
    return f"{ticker_padded}{exp_str}{opt_char}{strike_1000:08d}"
