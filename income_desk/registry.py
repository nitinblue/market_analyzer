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
    # Scanning metadata (for broker-independent universe)
    sector: str = ""  # "tech", "finance", "energy", "commodity", "bonds", "index", etc.
    scan_groups: list[str] = []  # ["income", "mega_cap", "sector_etf", "nifty50", etc.]
    options_liquidity: str = "unknown"  # "high", "medium", "low", "none"


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

    def get_universe(
        self,
        preset: str | None = None,
        market: str | None = None,
        sector: str | None = None,
        asset_type: str | None = None,
        options_liquidity: str | None = None,
    ) -> list[str]:
        """Get a scannable ticker universe — broker-independent.

        Presets:
            "income"      — High options liquidity, suitable for theta/income strategies
            "directional" — Liquid equities for breakout/momentum plays
            "india_fno"   — All India F&O instruments (index + stocks)
            "us_etf"      — US ETFs with weekly options
            "us_mega"     — US mega-cap equities
            "nifty50"     — India NIFTY 50 constituent proxies
            "sector_etf"  — US sector ETFs
            "all"         — Everything in the market

        Or filter by: market, sector, asset_type, options_liquidity.
        """
        instruments = list(self._instruments.values())

        if preset:
            preset = preset.lower()
            if preset == "all":
                pass  # No filter
            else:
                instruments = [i for i in instruments if preset in i.scan_groups]

        if market:
            instruments = [i for i in instruments if i.market == market.upper()]

        if sector:
            instruments = [i for i in instruments if i.sector == sector.lower()]

        if asset_type:
            instruments = [i for i in instruments if i.asset_type == asset_type.lower()]

        if options_liquidity:
            instruments = [i for i in instruments if i.options_liquidity == options_liquidity.lower()]

        return [i.ticker for i in instruments]

    def add_instrument(self, instrument: InstrumentInfo) -> None:
        """Add a custom instrument to the registry (for eTrading extensibility).

        Allows the platform to add broker-provided instruments at runtime
        without modifying MA source code.
        """
        self._instruments[instrument.ticker.upper()] = instrument

    def strategy_available(
        self, strategy: str, ticker: str, market: str | None = None
    ) -> bool:
        """Check if a strategy is available for an instrument/market.

        Beyond the market-level matrix, applies instrument-level overrides:
        - calendar/diagonal blocked for India equities (monthly-only expiry,
          insufficient term structure for multi-expiry strategies).
        """
        try:
            inst = self.get_instrument(ticker, market)
            mkt = inst.market
        except KeyError:
            inst = None
            mkt = (market or "US").upper()

        key = (mkt, strategy.lower())
        available = self._strategy_matrix.get(key, False)

        # India equities have monthly-only options — calendar and diagonal
        # require weekly expiries for meaningful term structure.
        if (
            available
            and inst is not None
            and inst.market == "INDIA"
            and inst.asset_type == "equity"
            and strategy.lower() in ("calendar", "diagonal")
        ):
            return False

        return available

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
    # (ticker, yfinance, asset_type, sector, scan_groups, options_liquidity)
    us_data = [
        # Broad market ETFs (highest options liquidity)
        ("SPY", "SPY", "etf", "index", ["income", "us_etf", "directional"], "high"),
        ("QQQ", "QQQ", "etf", "tech", ["income", "us_etf", "directional"], "high"),
        ("IWM", "IWM", "etf", "small_cap", ["income", "us_etf", "directional"], "high"),
        ("DIA", "DIA", "etf", "index", ["income", "us_etf"], "high"),
        ("SPX", "^GSPC", "index", "index", ["income"], "high"),
        # Commodity/Bond ETFs
        ("GLD", "GLD", "etf", "commodity", ["income", "us_etf", "directional"], "high"),
        ("SLV", "SLV", "etf", "commodity", ["income", "us_etf"], "medium"),
        ("TLT", "TLT", "etf", "bonds", ["income", "us_etf", "macro"], "high"),
        ("HYG", "HYG", "etf", "bonds", ["macro"], "medium"),
        ("UUP", "UUP", "etf", "currency", ["macro"], "low"),
        ("TIP", "TIP", "etf", "bonds", ["macro"], "low"),
        # Sector ETFs
        ("XLF", "XLF", "etf", "finance", ["sector_etf", "us_etf", "income"], "high"),
        ("XLE", "XLE", "etf", "energy", ["sector_etf", "us_etf", "income"], "high"),
        ("XLK", "XLK", "etf", "tech", ["sector_etf", "us_etf"], "high"),
        ("XLV", "XLV", "etf", "healthcare", ["sector_etf", "us_etf"], "medium"),
        ("XLI", "XLI", "etf", "industrial", ["sector_etf", "us_etf"], "medium"),
        ("XLP", "XLP", "etf", "consumer_staples", ["sector_etf", "us_etf"], "medium"),
        ("XLU", "XLU", "etf", "utilities", ["sector_etf", "us_etf"], "medium"),
        ("XLY", "XLY", "etf", "consumer_disc", ["sector_etf", "us_etf"], "medium"),
        ("XLRE", "XLRE", "etf", "real_estate", ["sector_etf", "us_etf"], "low"),
        ("XLC", "XLC", "etf", "communication", ["sector_etf", "us_etf"], "medium"),
        ("XLB", "XLB", "etf", "materials", ["sector_etf", "us_etf"], "low"),
        ("SMH", "SMH", "etf", "semiconductor", ["sector_etf", "us_etf", "directional"], "high"),
        ("EFA", "EFA", "etf", "international", ["us_etf"], "medium"),
        # Mega-cap equities
        ("AAPL", "AAPL", "equity", "tech", ["us_mega", "directional"], "high"),
        ("MSFT", "MSFT", "equity", "tech", ["us_mega", "directional"], "high"),
        ("AMZN", "AMZN", "equity", "tech", ["us_mega", "directional"], "high"),
        ("GOOGL", "GOOGL", "equity", "tech", ["us_mega", "directional"], "high"),
        ("META", "META", "equity", "tech", ["us_mega", "directional"], "high"),
        ("NVDA", "NVDA", "equity", "semiconductor", ["us_mega", "directional"], "high"),
        ("TSLA", "TSLA", "equity", "auto", ["us_mega", "directional"], "high"),
        ("AMD", "AMD", "equity", "semiconductor", ["us_mega", "directional"], "high"),
        ("JPM", "JPM", "equity", "finance", ["us_mega", "directional"], "high"),
        ("BAC", "BAC", "equity", "finance", ["us_mega"], "medium"),
        ("XOM", "XOM", "equity", "energy", ["us_mega", "directional"], "high"),
        ("UNH", "UNH", "equity", "healthcare", ["us_mega"], "medium"),
        ("HD", "HD", "equity", "consumer_disc", ["us_mega"], "medium"),
        ("V", "V", "equity", "finance", ["us_mega"], "medium"),
        ("MA", "MA", "equity", "finance", ["us_mega"], "medium"),
        ("CRM", "CRM", "equity", "tech", ["us_mega"], "medium"),
        ("NFLX", "NFLX", "equity", "communication", ["us_mega", "directional"], "high"),
    ]
    for ticker, yf, asset, sector, groups, liq in us_data:
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
            sector=sector,
            scan_groups=groups,
            options_liquidity=liq,
        )

    # --- India index instruments ---
    # (ticker, yfinance, lot, strike_interval, expiry_day, sector, scan_groups, options_liquidity)
    india_indices = [
        ("NIFTY", "^NSEI", 25, 50, "thursday", "index", ["income", "india_fno", "india_index"], "high"),
        ("BANKNIFTY", "^NSEBANK", 15, 100, "wednesday", "finance", ["income", "india_fno", "india_index"], "high"),
        ("FINNIFTY", "NIFTY_FIN_SERVICE.NS", 40, 50, "tuesday", "finance", ["india_fno", "india_index"], "medium"),
    ]
    for ticker, yf, lot, strike_int, expiry_day, sector, groups, liq in india_indices:
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
            asset_type="index",
            yfinance_symbol=yf,
            sector=sector,
            scan_groups=groups,
            options_liquidity=liq,
        )

    # --- India stock instruments (top F&O stocks) ---
    # (ticker, lot_size, strike_interval, sector, scan_groups, options_liquidity)
    india_stocks = [
        # Large-cap, relatively liquid options
        ("RELIANCE", 250, 20, "energy", ["india_fno", "nifty50", "directional"], "medium"),
        ("TCS", 150, 25, "tech", ["india_fno", "nifty50", "directional"], "medium"),
        ("INFY", 300, 25, "tech", ["india_fno", "nifty50", "directional"], "medium"),
        ("HDFCBANK", 550, 10, "finance", ["india_fno", "nifty50", "directional"], "medium"),
        ("ICICIBANK", 700, 10, "finance", ["india_fno", "nifty50", "directional"], "medium"),
        ("SBIN", 1500, 5, "finance", ["india_fno", "nifty50", "directional"], "medium"),
        ("BHARTIARTL", 475, 10, "telecom", ["india_fno", "nifty50"], "low"),
        ("ITC", 1600, 5, "consumer_staples", ["india_fno", "nifty50", "directional"], "medium"),
        ("BAJFINANCE", 125, 50, "finance", ["india_fno", "nifty50"], "medium"),
        # TATAMOTORS: yfinance symbol TATAMOTORS.NS returns 404 as of 2026-03.
        # Commented out until correct yfinance alias is confirmed post-DVR merger.
        # ("TATAMOTORS", 1125, 5, "auto", ["india_fno", "nifty50", "directional"], "medium"),
        # Mid-tier liquidity
        ("HINDUNILVR", 300, 10, "consumer_staples", ["india_fno", "nifty50"], "low"),
        ("LT", 150, 25, "industrial", ["india_fno", "nifty50"], "low"),
        ("AXISBANK", 600, 10, "finance", ["india_fno", "nifty50", "directional"], "medium"),
        ("KOTAKBANK", 400, 10, "finance", ["india_fno", "nifty50"], "low"),
        ("MARUTI", 100, 50, "auto", ["india_fno", "nifty50"], "low"),
        ("ASIANPAINT", 300, 10, "consumer_disc", ["india_fno", "nifty50"], "low"),
        ("TITAN", 175, 25, "consumer_disc", ["india_fno", "nifty50"], "low"),
        ("SUNPHARMA", 350, 10, "pharma", ["india_fno", "nifty50"], "low"),
        ("HDFCLIFE", 1100, 5, "finance", ["india_fno"], "low"),
        ("WIPRO", 1500, 5, "tech", ["india_fno", "nifty50"], "low"),
        # Additional NIFTY 50 stocks (equity scanning universe)
        ("ADANIENT", 500, 10, "conglomerate", ["nifty50", "directional"], "low"),
        ("ADANIPORTS", 1000, 5, "infrastructure", ["nifty50"], "low"),
        ("APOLLOHOSP", 125, 50, "healthcare", ["nifty50"], "low"),
        ("BAJAJ_AUTO", 250, 25, "auto", ["nifty50"], "low"),
        ("BAJAJFINSV", 500, 10, "finance", ["nifty50"], "low"),
        ("BPCL", 900, 5, "energy", ["nifty50"], "low"),
        ("BRITANNIA", 200, 25, "consumer_staples", ["nifty50"], "low"),
        ("CIPLA", 650, 10, "pharma", ["nifty50"], "low"),
        ("COALINDIA", 2100, 2, "mining", ["nifty50"], "low"),
        ("DIVISLAB", 150, 25, "pharma", ["nifty50"], "low"),
        ("DRREDDY", 125, 50, "pharma", ["nifty50"], "low"),
        ("EICHERMOT", 175, 25, "auto", ["nifty50"], "low"),
        ("GRASIM", 350, 10, "materials", ["nifty50"], "low"),
        ("HCLTECH", 350, 10, "tech", ["nifty50"], "low"),
        ("HEROMOTOCO", 150, 25, "auto", ["nifty50"], "low"),
        ("HINDALCO", 1300, 5, "metals", ["nifty50", "directional"], "low"),
        ("INDUSINDBK", 500, 10, "finance", ["nifty50", "directional"], "low"),
        ("JSWSTEEL", 675, 5, "metals", ["nifty50", "directional"], "low"),
        ("M_M", 350, 10, "auto", ["nifty50", "directional"], "low"),
        ("NESTLEIND", 50, 100, "consumer_staples", ["nifty50"], "low"),
        ("NTPC", 2800, 2, "power", ["nifty50"], "low"),
        ("ONGC", 3850, 2, "energy", ["nifty50"], "low"),
        ("POWERGRID", 2700, 2, "power", ["nifty50"], "low"),
        ("TATACONSUM", 550, 10, "consumer_staples", ["nifty50"], "low"),
        ("TATASTEEL", 1100, 5, "metals", ["nifty50", "directional"], "low"),
        ("TECHM", 600, 10, "tech", ["nifty50"], "low"),
        ("ULTRACEMCO", 100, 50, "materials", ["nifty50"], "low"),
    ]

    # yfinance symbol overrides for India stocks where ticker != yfinance alias
    _india_yf_overrides: dict[str, str] = {
        "M_M": "M&M.NS",
        "BAJAJ_AUTO": "BAJAJ-AUTO.NS",
        "BAJAJFINSV": "BAJAJFINSV.NS",
    }

    for ticker, lot, strike_int, sector, groups, liq in india_stocks:
        yf_sym = _india_yf_overrides.get(ticker, f"{ticker}.NS")
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
            yfinance_symbol=yf_sym,
            sector=sector,
            scan_groups=groups,
            options_liquidity=liq,
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
