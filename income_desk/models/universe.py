"""Universe filter configuration and scan results.

Defines filter criteria for dynamically building a trading universe
from broker data (market metrics, equity listings, etc.).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class AssetType(StrEnum):
    ETF = "ETF"
    EQUITY = "Equity"
    INDEX = "Index"


class SortField(StrEnum):
    IV_RANK = "iv_rank"
    LIQUIDITY = "liquidity"
    VOLUME = "volume"
    BETA = "beta"
    IV_HV_SPREAD = "iv_hv_spread"
    MARKET_CAP = "market_cap"


class UniverseFilter(BaseModel):
    """Filter criteria for building a dynamic trading universe.

    Two-phase scanning:
      Phase 1 (fast): Pull equity listings from broker, apply basic filters
      Phase 2 (metrics): Batch fetch market metrics, apply IV/liquidity/beta filters
    """

    # -- Phase 1: Asset type & eligibility --
    asset_types: list[AssetType] = [AssetType.ETF]
    min_price: float = 5.0
    max_price: float = 500.0
    is_options_tradeable: bool = True  # Must have listed options

    # -- Phase 2: Liquidity & volume (from market metrics) --
    min_liquidity_rating: int = 3  # TastyTrade 1-5 scale (3+ = tradeable spreads)
    min_liquidity_value: float | None = None  # Raw liquidity metric

    # -- Phase 2: Volatility profile --
    iv_rank_min: float | None = None  # 0-100, minimum IV rank
    iv_rank_max: float | None = None  # 0-100, maximum IV rank
    iv_percentile_min: float | None = None
    iv_percentile_max: float | None = None
    hv_30_day_min: float | None = None  # 30-day historical vol floor
    hv_30_day_max: float | None = None
    iv_hv_spread_min: float | None = None  # IV - HV (positive = IV rich)

    # -- Phase 2: Risk profile --
    beta_min: float | None = None
    beta_max: float | None = None
    market_cap_min: float | None = None  # Minimum market cap ($)
    dividend_yield_min: float | None = None

    # -- Earnings filter --
    exclude_earnings_within_days: int | None = None  # Skip if earnings < N days

    # -- Data quality --
    min_trading_days: int = 100  # Skip newly listed tickers (regime needs ~60 days minimum)

    # -- Result controls --
    max_symbols: int = 50
    sort_by: SortField = SortField.IV_RANK
    sort_descending: bool = True
    exclude_tickers: list[str] = []
    include_tickers: list[str] = []  # Always include (bypass filters)


# -- Preset filters --

PRESET_INCOME = UniverseFilter(
    asset_types=[AssetType.ETF],
    min_liquidity_rating=4,
    iv_rank_min=30.0,
    iv_rank_max=80.0,
    beta_max=1.5,
    max_symbols=30,
    sort_by=SortField.IV_RANK,
    sort_descending=True,
    exclude_earnings_within_days=7,
)

PRESET_DIRECTIONAL = UniverseFilter(
    asset_types=[AssetType.ETF, AssetType.EQUITY],
    min_liquidity_rating=3,
    beta_min=0.8,
    beta_max=2.0,
    max_symbols=40,
    sort_by=SortField.BETA,
    sort_descending=True,
)

PRESET_HIGH_VOL = UniverseFilter(
    asset_types=[AssetType.ETF, AssetType.EQUITY],
    min_liquidity_rating=3,
    iv_rank_min=60.0,
    max_symbols=30,
    sort_by=SortField.IV_RANK,
    sort_descending=True,
)

PRESET_BROAD = UniverseFilter(
    asset_types=[AssetType.ETF, AssetType.EQUITY],
    min_liquidity_rating=2,
    max_symbols=100,
    sort_by=SortField.LIQUIDITY,
    sort_descending=True,
)

PRESETS: dict[str, UniverseFilter] = {
    "income": PRESET_INCOME,
    "directional": PRESET_DIRECTIONAL,
    "high_vol": PRESET_HIGH_VOL,
    "broad": PRESET_BROAD,
}


class UniverseCandidate(BaseModel):
    """A ticker that passed universe filters, with its metrics."""

    ticker: str
    asset_type: str  # ETF, Equity, Index
    iv_rank: float | None = None
    iv_percentile: float | None = None
    iv_index: float | None = None
    hv_30_day: float | None = None
    iv_hv_spread: float | None = None
    beta: float | None = None
    liquidity_rating: float | None = None
    market_cap: float | None = None
    earnings_date: str | None = None
    filter_reason: str | None = None  # Why it passed / was selected


class UniverseScanResult(BaseModel):
    """Result of a universe scan."""

    filter_used: str  # Preset name or "custom"
    total_scanned: int  # How many symbols were evaluated
    total_passed: int  # How many passed filters
    candidates: list[UniverseCandidate]
    include_forced: list[str] = []  # Tickers added via include_tickers
    watchlist_saved: str | None = None  # Name of saved watchlist (if any)
