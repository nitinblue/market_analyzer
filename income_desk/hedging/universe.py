"""F&O universe classification for hedging.

Classifies tickers into hedge tiers based on registry data:
- Tier 1 (DIRECT): instrument has liquid options (options_liquidity "high" or "medium")
- Tier 2 (FUTURES_SYNTHETIC): instrument has futures but options are illiquid
- Tier 3 (PROXY_INDEX): instrument has no F&O, must use index proxy
- NONE: no viable hedge

Uses income_desk.registry.MarketRegistry — no duplication of instrument data.
"""

from __future__ import annotations

from income_desk.hedging.models import FnOCoverage, HedgeTier
from income_desk.registry import InstrumentInfo, MarketRegistry


# Sector → proxy index mapping
_INDIA_SECTOR_PROXY: dict[str, str] = {
    "finance": "BANKNIFTY",
    "tech": "NIFTY",
    "energy": "NIFTY",
    "auto": "NIFTY",
    "pharma": "NIFTY",
    "metals": "NIFTY",
    "consumer_staples": "NIFTY",
    "consumer_disc": "NIFTY",
    "telecom": "NIFTY",
    "industrial": "NIFTY",
    "infrastructure": "NIFTY",
    "conglomerate": "NIFTY",
    "mining": "NIFTY",
    "power": "NIFTY",
    "materials": "NIFTY",
    "healthcare": "NIFTY",
    "index": "NIFTY",         # Index instruments are self-hedging, but fallback to NIFTY
}

_US_SECTOR_PROXY: dict[str, str] = {
    "tech": "QQQ",
    "semiconductor": "QQQ",
    "finance": "XLF",
    "energy": "XLE",
    "healthcare": "XLV",
    "consumer_disc": "XLY",
    "consumer_staples": "XLP",
    "industrial": "XLI",
    "utilities": "XLU",
    "real_estate": "XLRE",
    "communication": "XLC",
    "materials": "XLB",
    "bonds": "TLT",
    "commodity": "GLD",
    "small_cap": "IWM",
    "index": "SPY",
    "auto": "SPY",
    "international": "SPY",
}


def classify_hedge_tier(
    ticker: str,
    market: str = "US",
    registry: MarketRegistry | None = None,
) -> HedgeTier:
    """Classify a ticker's best available hedge tier.

    Decision logic:
    1. Look up instrument in registry
    2. If options_liquidity is "high" or "medium" → DIRECT
    3. If options_liquidity is "low" (has F&O listing but thin) → FUTURES_SYNTHETIC
       (India stock futures exist for all F&O stocks)
    4. If not in registry at all → PROXY_INDEX
    5. If market is US and not in registry → DIRECT (US stocks generally have options)

    Args:
        ticker: Instrument ticker.
        market: "US" or "INDIA".
        registry: MarketRegistry instance (created if None).

    Returns:
        HedgeTier classification.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    try:
        inst = reg.get_instrument(ticker, market)
    except KeyError:
        # Not in registry
        if market == "US":
            return HedgeTier.DIRECT  # Most US stocks have liquid options
        return HedgeTier.PROXY_INDEX  # Unknown India stock — proxy only

    return _classify_from_instrument(inst)


def _classify_from_instrument(inst: InstrumentInfo) -> HedgeTier:
    """Classify hedge tier from InstrumentInfo."""
    liq = inst.options_liquidity.lower()

    if liq in ("high", "medium"):
        return HedgeTier.DIRECT

    if liq == "low":
        # "low" in registry means it HAS F&O listing, just thin liquidity
        # India: all F&O stocks have mandatory stock futures → use futures
        # US: "low" liquidity options still tradeable directly
        if inst.market == "INDIA":
            return HedgeTier.FUTURES_SYNTHETIC
        return HedgeTier.DIRECT  # US low-liq options still usable

    # "none" or "unknown"
    return HedgeTier.PROXY_INDEX


def get_fno_coverage(
    tickers: list[str],
    market: str = "US",
    registry: MarketRegistry | None = None,
) -> FnOCoverage:
    """Assess F&O coverage for a set of tickers.

    Args:
        tickers: List of ticker symbols.
        market: "US" or "INDIA".
        registry: MarketRegistry instance.

    Returns:
        FnOCoverage with tier breakdown and coverage stats.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    tier_breakdown: dict[str, list[str]] = {
        "direct": [],
        "futures_synthetic": [],
        "proxy_index": [],
        "none": [],
    }

    for ticker in tickers:
        tier = classify_hedge_tier(ticker, market, reg)
        tier_breakdown[tier.value].append(ticker)

    direct_count = len(tier_breakdown["direct"])
    futures_count = len(tier_breakdown["futures_synthetic"])
    proxy_count = len(tier_breakdown["proxy_index"])
    none_count = len(tier_breakdown["none"])
    total = len(tickers)

    coverage_pct = ((direct_count + futures_count) / total * 100) if total > 0 else 0

    parts = []
    if direct_count:
        parts.append(f"{direct_count} direct")
    if futures_count:
        parts.append(f"{futures_count} futures")
    if proxy_count:
        parts.append(f"{proxy_count} proxy-only")
    if none_count:
        parts.append(f"{none_count} no hedge")
    commentary = f"{coverage_pct:.0f}% hedgeable: {', '.join(parts)}"

    return FnOCoverage(
        market=market,
        total_tickers=total,
        direct_hedge_count=direct_count,
        futures_hedge_count=futures_count,
        proxy_only_count=proxy_count,
        no_hedge_count=none_count,
        coverage_pct=round(coverage_pct, 1),
        tier_breakdown=tier_breakdown,
        commentary=commentary,
    )


def get_sector_beta(
    ticker: str,
    index: str,
    market: str = "US",
) -> float:
    """Get approximate sector beta vs an index.

    Static approximation — for precise beta, use historical returns.
    These are defaults for hedge ratio sizing.

    Args:
        ticker: Stock ticker.
        index: Index ticker (e.g., "NIFTY", "SPY").
        market: "US" or "INDIA".

    Returns:
        Approximate beta (1.0 = moves with index).
    """
    # Approximate sector betas (static, conservative)
    _INDIA_BETAS: dict[str, float] = {
        "finance": 1.15,
        "tech": 0.85,
        "energy": 0.95,
        "auto": 1.10,
        "pharma": 0.70,
        "metals": 1.30,
        "consumer_staples": 0.60,
        "consumer_disc": 0.90,
        "telecom": 0.75,
        "industrial": 1.05,
        "infrastructure": 1.00,
        "conglomerate": 1.10,
        "mining": 1.25,
        "power": 0.80,
        "materials": 1.15,
        "healthcare": 0.70,
    }
    _US_BETAS: dict[str, float] = {
        "tech": 1.20,
        "semiconductor": 1.40,
        "finance": 1.10,
        "energy": 1.15,
        "healthcare": 0.80,
        "consumer_disc": 1.10,
        "consumer_staples": 0.65,
        "industrial": 1.05,
        "utilities": 0.55,
        "real_estate": 0.85,
        "communication": 1.05,
        "materials": 1.00,
        "bonds": -0.20,
        "commodity": 0.15,
        "small_cap": 1.20,
        "auto": 1.30,
    }

    reg = MarketRegistry()
    try:
        inst = reg.get_instrument(ticker, market)
        sector = inst.sector
    except KeyError:
        return 1.0  # Unknown — assume market beta

    betas = _INDIA_BETAS if market.upper() == "INDIA" else _US_BETAS
    return betas.get(sector, 1.0)


def get_proxy_instrument(
    ticker: str,
    market: str = "US",
    registry: MarketRegistry | None = None,
) -> str:
    """Recommend a proxy index for hedging a ticker.

    Uses sector classification to pick the best correlated liquid index.

    Args:
        ticker: Stock ticker.
        market: "US" or "INDIA".
        registry: MarketRegistry instance.

    Returns:
        Proxy ticker (e.g., "NIFTY", "SPY", "QQQ").
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    try:
        inst = reg.get_instrument(ticker, market)
        sector = inst.sector
    except KeyError:
        # Unknown ticker — use broad market index
        return "NIFTY" if market == "INDIA" else "SPY"

    proxy_map = _INDIA_SECTOR_PROXY if market == "INDIA" else _US_SECTOR_PROXY
    return proxy_map.get(sector, "NIFTY" if market == "INDIA" else "SPY")
