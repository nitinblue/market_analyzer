"""Market & instrument static data registry.

Codifies market mechanics: lot sizes, strike intervals, expiry conventions,
settlement types, margin rules, trading hours, symbol formats, strategy availability.

All data is static and loaded at import time. No network calls.
eTrading and MA services use this instead of hardcoding market-specific rules.
"""

from __future__ import annotations

from datetime import time

from pydantic import BaseModel


class MarketInfo(BaseModel):
    """Exchange/market metadata."""

    market_id: str  # "US", "INDIA"
    currency: str  # "USD", "INR"
    timezone: str  # "US/Eastern", "Asia/Kolkata"
    open_time: time
    close_time: time
    settlement_days: int  # T+1
    pre_market_start: time | None = None
    pre_market_end: time | None = None
    force_close_time: time  # When to force-close 0DTE / EOD positions


class InstrumentInfo(BaseModel):
    """Instrument-level static data for options trading."""

    ticker: str  # "NIFTY", "SPY", "RELIANCE"
    market: str  # "US", "INDIA"
    lot_size: int  # 25, 100, 250, etc.
    strike_interval: float  # 50, 1, 0.5, etc.
    expiry_types: list[str]  # ["weekly_thursday", "monthly_last_thursday"]
    weekly_expiry_day: str | None  # "thursday", "wednesday", "friday", None
    settlement: str  # "cash", "physical"
    exercise_style: str  # "american", "european"
    has_0dte: bool
    has_leaps: bool
    max_dte: int  # Max DTE for options (e.g., 90 for India F&O, 1095 for US LEAPs)
    asset_type: str  # "index", "etf", "equity"
    yfinance_symbol: str  # "^NSEI", "SPY", "RELIANCE.NS"


class MarginEstimate(BaseModel):
    """Estimated margin requirement for a strategy."""

    strategy: str
    ticker: str
    margin_amount: float
    currency: str
    method: str  # "reg_t", "span_exposure"
    notes: str


class MarketRegistry:
    """Static data registry for market mechanics.

    Usage::

        registry = MarketRegistry()
        market = registry.get_market("US")
        inst = registry.get_instrument("NIFTY")
        available = registry.strategy_available("leaps", "NIFTY")
    """

    def __init__(self) -> None:
        self._markets = _build_markets()
        self._instruments = _build_instruments()
        self._strategy_matrix = _build_strategy_matrix()

    def get_market(self, market_id: str) -> MarketInfo:
        """Get market metadata. Raises KeyError if not found."""
        market_id = market_id.upper()
        if market_id not in self._markets:
            raise KeyError(
                f"Unknown market: {market_id}. Available: {list(self._markets.keys())}"
            )
        return self._markets[market_id]

    def get_instrument(
        self, ticker: str, market: str | None = None
    ) -> InstrumentInfo:
        """Get instrument info. Auto-detects market if not specified."""
        key = ticker.upper()
        if key in self._instruments:
            inst = self._instruments[key]
            if market and inst.market != market.upper():
                raise KeyError(f"{ticker} is in {inst.market}, not {market}")
            return inst
        raise KeyError(
            f"Unknown instrument: {ticker}. Use to_yfinance() for arbitrary tickers."
        )

    def list_instruments(self, market: str | None = None) -> list[InstrumentInfo]:
        """List all known instruments, optionally filtered by market."""
        if market:
            return [
                i for i in self._instruments.values() if i.market == market.upper()
            ]
        return list(self._instruments.values())

    def strategy_available(
        self, strategy: str, ticker: str, market: str | None = None
    ) -> bool:
        """Check if a strategy is available for an instrument/market."""
        try:
            inst = self.get_instrument(ticker, market)
            mkt = inst.market
        except KeyError:
            mkt = (market or "US").upper()

        key = (mkt, strategy.lower())
        return self._strategy_matrix.get(key, False)

    def to_yfinance(self, ticker: str, market: str | None = None) -> str:
        """Map human ticker to yfinance symbol."""
        try:
            inst = self.get_instrument(ticker, market)
            return inst.yfinance_symbol
        except KeyError:
            # Fallback: if market is India and no .NS suffix, add it
            if market and market.upper() == "INDIA" and not ticker.endswith(".NS"):
                return f"{ticker}.NS"
            return ticker

    def estimate_margin(
        self,
        strategy: str,
        ticker: str,
        wing_width: float = 5.0,
        contracts: int = 1,
        market: str | None = None,
    ) -> MarginEstimate:
        """Estimate margin requirement for a strategy on an instrument."""
        try:
            inst = self.get_instrument(ticker, market)
            lot_size = inst.lot_size
            mkt = inst.market
        except KeyError:
            lot_size = 100
            mkt = (market or "US").upper()

        if mkt == "US":
            # Reg-T: defined risk = wing_width × lot_size × contracts
            margin = wing_width * lot_size * contracts
            return MarginEstimate(
                strategy=strategy,
                ticker=ticker,
                margin_amount=margin,
                currency="USD",
                method="reg_t",
                notes=f"Defined risk: {wing_width} × {lot_size} × {contracts}",
            )
        else:  # India SPAN
            # Approximate: SPAN margin for defined risk uses wing_width × lot_size
            margin = wing_width * lot_size * contracts
            return MarginEstimate(
                strategy=strategy,
                ticker=ticker,
                margin_amount=margin,
                currency="INR",
                method="span_exposure",
                notes=(
                    f"Approximate SPAN: {wing_width} × {lot_size} × {contracts}. "
                    "Actual varies."
                ),
            )


# ---------------------------------------------------------------------------
# Static data builders
# ---------------------------------------------------------------------------


def _build_markets() -> dict[str, MarketInfo]:
    return {
        "US": MarketInfo(
            market_id="US",
            currency="USD",
            timezone="US/Eastern",
            open_time=time(9, 30),
            close_time=time(16, 0),
            settlement_days=1,
            pre_market_start=time(4, 0),
            pre_market_end=time(9, 30),
            force_close_time=time(15, 45),
        ),
        "INDIA": MarketInfo(
            market_id="INDIA",
            currency="INR",
            timezone="Asia/Kolkata",
            open_time=time(9, 15),
            close_time=time(15, 30),
            settlement_days=1,
            pre_market_start=time(9, 0),
            pre_market_end=time(9, 15),
            force_close_time=time(15, 15),
        ),
    }


def _build_instruments() -> dict[str, InstrumentInfo]:
    instruments: dict[str, InstrumentInfo] = {}

    # --- US instruments ---
    for ticker, yf, asset in [
        ("SPY", "SPY", "etf"),
        ("QQQ", "QQQ", "etf"),
        ("IWM", "IWM", "etf"),
        ("SPX", "^GSPC", "index"),
        ("GLD", "GLD", "etf"),
        ("TLT", "TLT", "etf"),
        ("AAPL", "AAPL", "equity"),
        ("MSFT", "MSFT", "equity"),
        ("AMZN", "AMZN", "equity"),
        ("GOOGL", "GOOGL", "equity"),
        ("META", "META", "equity"),
        ("NVDA", "NVDA", "equity"),
        ("TSLA", "TSLA", "equity"),
        ("AMD", "AMD", "equity"),
    ]:
        instruments[ticker] = InstrumentInfo(
            ticker=ticker,
            market="US",
            lot_size=100,
            strike_interval=1.0,
            expiry_types=["weekly_friday", "monthly", "quarterly", "leaps"],
            weekly_expiry_day="friday",
            settlement="physical" if asset != "index" else "cash",
            exercise_style="american" if asset != "index" else "european",
            has_0dte=ticker in ("SPY", "QQQ", "IWM", "SPX"),
            has_leaps=True,
            max_dte=1095,
            asset_type=asset,
            yfinance_symbol=yf,
        )

    # --- India index instruments ---
    india_indices = [
        ("NIFTY", "^NSEI", 25, 50, "thursday", "index"),
        ("BANKNIFTY", "^NSEBANK", 15, 100, "wednesday", "index"),
        ("FINNIFTY", "NIFTY_FIN_SERVICE.NS", 40, 50, "tuesday", "index"),
    ]
    for ticker, yf, lot, strike_int, expiry_day, asset in india_indices:
        instruments[ticker] = InstrumentInfo(
            ticker=ticker,
            market="INDIA",
            lot_size=lot,
            strike_interval=float(strike_int),
            expiry_types=[f"weekly_{expiry_day}", "monthly_last_thursday"],
            weekly_expiry_day=expiry_day,
            settlement="cash",
            exercise_style="european",
            has_0dte=True,
            has_leaps=False,
            max_dte=90,
            asset_type=asset,
            yfinance_symbol=yf,
        )

    # --- India stock instruments (top 20) ---
    india_stocks = [
        ("RELIANCE", 250, 20),
        ("TCS", 150, 25),
        ("INFY", 300, 25),
        ("HDFCBANK", 550, 10),
        ("ICICIBANK", 700, 10),
        ("SBIN", 1500, 5),
        ("BHARTIARTL", 475, 10),
        ("ITC", 1600, 5),
        ("BAJFINANCE", 125, 50),
        ("TATAMOTORS", 1125, 5),
        ("HINDUNILVR", 300, 10),
        ("LT", 150, 25),
        ("AXISBANK", 600, 10),
        ("KOTAKBANK", 400, 10),
        ("MARUTI", 100, 50),
        ("ASIANPAINT", 300, 10),
        ("TITAN", 175, 25),
        ("SUNPHARMA", 350, 10),
        ("HDFCLIFE", 1100, 5),
        ("WIPRO", 1500, 5),
    ]
    for ticker, lot, strike_int in india_stocks:
        instruments[ticker] = InstrumentInfo(
            ticker=ticker,
            market="INDIA",
            lot_size=lot,
            strike_interval=float(strike_int),
            expiry_types=["monthly_last_thursday"],
            weekly_expiry_day=None,
            settlement="physical",
            exercise_style="european",
            has_0dte=False,
            has_leaps=False,
            max_dte=90,
            asset_type="equity",
            yfinance_symbol=f"{ticker}.NS",
        )

    return instruments


def _build_strategy_matrix() -> dict[tuple[str, str], bool]:
    """(market, strategy) -> available."""
    us_yes = [
        "iron_condor",
        "iron_butterfly",
        "credit_spread",
        "debit_spread",
        "calendar",
        "diagonal",
        "straddle",
        "strangle",
        "covered_call",
        "leaps",
        "zero_dte",
        "ratio_spread",
        "pmcc",
        "earnings",
        "jade_lizard",
    ]
    india_yes = [
        "iron_condor",
        "iron_butterfly",
        "credit_spread",
        "debit_spread",
        "calendar",
        "diagonal",
        "straddle",
        "strangle",
        "covered_call",
        "zero_dte",
        "ratio_spread",
        "earnings",
        "jade_lizard",
    ]
    india_no = ["leaps", "pmcc"]  # No LEAPs in India

    matrix: dict[tuple[str, str], bool] = {}
    for s in us_yes:
        matrix[("US", s)] = True
    for s in india_yes:
        matrix[("INDIA", s)] = True
    for s in india_no:
        matrix[("INDIA", s)] = False
    return matrix
