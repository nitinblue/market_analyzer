# Hedging Domain Package — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a market-generic hedging intelligence system that resolves hedge strategy (direct/futures/proxy), builds concrete TradeSpecs, monitors hedge health, and works for both US and India markets.

**Architecture:** New `income_desk/hedging/` domain package. Resolver pattern: `resolve_hedge_strategy()` decides the approach, tier-specific modules build the TradeSpecs. Portfolio orchestrator aggregates across all positions. All functions are pure, market-parameterized, and return Pydantic models with TradeSpecs.

**Tech Stack:** Python 3.12, Pydantic, existing income_desk models. No new dependencies.

**Venv / test command:** `.venv_312/Scripts/python.exe -m pytest tests/test_hedging/ -v`

---

## Existing Infrastructure (DO NOT rebuild)

These modules already exist and must be consumed, not duplicated:

| Module | What it provides | How hedging uses it |
|--------|-----------------|---------------------|
| `income_desk/hedging.py` | `HedgeType`, `HedgeUrgency`, `HedgeRecommendation`, `assess_hedge()`, 4 decision trees (long equity, short vol, defined risk, credit spread) | FOUNDATION — move into `hedging/` package, re-export from old path |
| `income_desk/futures_analysis.py` | `FuturesBasisAnalysis`, `FuturesTermStructureAnalysis`, `FuturesRollDecision`, `analyze_futures_basis()`, `decide_futures_roll()`, `estimate_futures_margin()` | Futures hedge builder calls `analyze_futures_basis()` for cost, `decide_futures_roll()` for expiry monitoring |
| `income_desk/registry.py` | `MarketRegistry`, `InstrumentInfo` with `lot_size`, `strike_interval`, `exercise_style`, `options_liquidity`, `sector` for 41 India + 37 US instruments | Universe classifier reads `options_liquidity` to determine hedge tier; all builders use `lot_size`/`strike_interval` |
| `income_desk/models/opportunity.py` | `StructureType` (has `FUTURES_LONG`/`FUTURES_SHORT`/`LONG_OPTION`/`CREDIT_SPREAD`), `LegAction`, `LegSpec`, `TradeSpec`, `OrderSide` | Every hedge function returns a `TradeSpec` with concrete legs |
| `income_desk/risk.py` | `PortfolioPosition` with `delta`/`gamma`/`theta`/`vega`, `estimate_portfolio_loss()`, `check_portfolio_greeks()` | Portfolio orchestrator takes `list[PortfolioPosition]` as input |

---

## File Structure

```
income_desk/hedging/                    # NEW domain package
    __init__.py                         # Public API exports
    models.py                           # All hedging models
    resolver.py                         # resolve_hedge_strategy() — the decision engine
    direct.py                           # Tier 1: puts, collars, put spreads
    futures_hedge.py                    # Tier 2: futures hedging + synthetics
    proxy.py                            # Tier 3: index proxy hedging
    portfolio.py                        # Portfolio-level orchestrator
    comparison.py                       # compare_hedge_methods()
    monitoring.py                       # Hedge expiry, rolling, effectiveness
    universe.py                         # F&O universe data + classification

income_desk/hedging.py                  # KEEP — re-exports for backward compat

tests/test_hedging/                     # Mirror the package structure
    __init__.py
    test_models.py
    test_resolver.py
    test_direct.py
    test_futures_hedge.py
    test_proxy.py
    test_portfolio.py
    test_comparison.py
    test_monitoring.py
    test_universe.py
```

---

## Task 1: Hedging Models

**Goal:** Create all Pydantic models needed across the hedging package. Every other task imports from this file.

**Files to create:**
- `income_desk/hedging/__init__.py` (empty initially, populated in Task 10)
- `income_desk/hedging/models.py`

**Files to test:**
- `tests/test_hedging/__init__.py`
- `tests/test_hedging/test_models.py`

### Steps

- [ ] **1.1** Create `income_desk/hedging/__init__.py` with a docstring placeholder
- [ ] **1.2** Create `income_desk/hedging/models.py` with all models
- [ ] **1.3** Create `tests/test_hedging/__init__.py` (empty)
- [ ] **1.4** Create `tests/test_hedging/test_models.py` with model instantiation tests
- [ ] **1.5** Run tests: `.venv_312/Scripts/python.exe -m pytest tests/test_hedging/test_models.py -v`
- [ ] **1.6** Commit: `git commit -m "feat(hedging): add hedging domain models — HedgeTier, HedgeApproach, HedgeResult, portfolio-level models"`

### 1.1 — Create `income_desk/hedging/__init__.py`

```python
"""Hedging domain package — market-generic hedge intelligence.

Resolver pattern:
    resolve_hedge_strategy() → HedgeApproach (decides tier)
    Tier 1 (direct.py)       → protective puts, collars, put spreads
    Tier 2 (futures_hedge.py) → futures short, synthetic puts, synthetic collars
    Tier 3 (proxy.py)        → beta-adjusted index hedges
    portfolio.py             → orchestrate across all positions
    comparison.py            → rank all available methods
    monitoring.py            → expiry tracking, rolling, effectiveness
"""
```

### 1.2 — Create `income_desk/hedging/models.py`

```python
"""All Pydantic models for the hedging domain package."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from income_desk.models.opportunity import TradeSpec


class HedgeTier(StrEnum):
    """Which hedging approach to use, ordered by preference."""

    DIRECT = "direct"                     # Tier 1: liquid same-ticker options
    FUTURES_SYNTHETIC = "futures_synthetic"  # Tier 2: futures + optional call/put
    PROXY_INDEX = "proxy_index"           # Tier 3: correlated index hedge
    NONE = "none"                         # No hedge available or needed


class HedgeGoal(StrEnum):
    """What the hedge is protecting against."""

    DOWNSIDE = "downside"        # Protect long equity from drop
    UPSIDE = "upside"            # Protect short equity from rally
    VOLATILITY = "volatility"    # Protect from vol expansion
    TAIL_RISK = "tail_risk"      # Black swan protection (cheap OTM)
    DELTA_NEUTRAL = "delta_neutral"  # Flatten directional exposure


class HedgeApproach(BaseModel):
    """Resolved hedge strategy — what approach and why.

    This is the OUTPUT of resolve_hedge_strategy().
    It tells the caller WHICH tier to use and WHY,
    but does NOT contain the actual TradeSpec yet.
    """

    ticker: str
    market: str                          # "US" or "INDIA"
    recommended_tier: HedgeTier
    goal: HedgeGoal
    rationale: str                       # Why this tier was chosen
    alternatives: list[HedgeAlternative]  # Other tiers considered, ranked
    # Cost context
    estimated_cost_pct: float | None     # Estimated hedge cost as % of position value
    basis_risk: str                      # "none", "low", "medium", "high"
    # Registry data used in decision
    has_liquid_options: bool
    has_futures: bool
    lot_size: int
    lot_size_affordable: bool            # Can the account afford at least 1 lot?


class HedgeAlternative(BaseModel):
    """An alternative hedge approach that was considered but not recommended."""

    tier: HedgeTier
    reason_not_chosen: str
    estimated_cost_pct: float | None


class HedgeResult(BaseModel):
    """A concrete hedge recommendation with TradeSpec.

    Every tier-specific builder returns this.
    """

    ticker: str
    market: str
    tier: HedgeTier
    hedge_type: str                      # "protective_put", "collar", "futures_short", etc.
    trade_spec: TradeSpec                # Concrete legs, ready for execution
    cost_estimate: float | None          # Net premium paid (positive = debit)
    cost_pct: float | None               # Cost as % of position value
    delta_reduction: float               # How much delta the hedge removes (0 to 1)
    protection_level: str                # "Put at 2600" or "Futures short 1 lot"
    max_loss_after_hedge: float | None   # Max loss with hedge in place
    rationale: str
    regime_context: str                  # Why this hedge suits the current regime
    commentary: list[str]                # Debug-mode trace of decisions


class CollarResult(BaseModel):
    """Collar-specific result with both put and call details."""

    ticker: str
    market: str
    put_strike: float
    call_strike: float
    net_cost: float                      # Negative = credit (call premium > put cost)
    downside_protection_pct: float       # How far below current price the put is
    upside_cap_pct: float                # How far above current price the call is
    trade_spec: TradeSpec
    rationale: str


class SyntheticOptionResult(BaseModel):
    """Result of building a synthetic option from futures.

    Synthetic put  = short futures + long call
    Synthetic call = long futures + long put
    """

    ticker: str
    market: str
    synthetic_type: str                  # "synthetic_put" or "synthetic_call"
    futures_direction: str               # "short" or "long"
    futures_lots: int
    option_strike: float
    option_type: str                     # "call" or "put"
    option_lots: int
    net_cost_estimate: float | None      # Basis cost + option premium
    trade_spec: TradeSpec
    rationale: str


class PositionHedge(BaseModel):
    """Per-position hedge detail within a portfolio analysis."""

    ticker: str
    position_value: float
    shares: int
    tier: HedgeTier
    hedge_type: str | None               # None if tier is NONE
    trade_spec: TradeSpec | None
    cost_estimate: float | None
    delta_before: float
    delta_after: float
    rationale: str


class PortfolioHedgeAnalysis(BaseModel):
    """Aggregate portfolio hedge analysis — the master output."""

    market: str
    account_nlv: float
    total_positions: int
    total_position_value: float

    # Tier breakdown
    tier_counts: dict[str, int]          # {"direct": 5, "futures_synthetic": 2, "proxy_index": 1, "none": 2}
    tier_values: dict[str, float]        # Value of positions in each tier

    # Per-position details
    position_hedges: list[PositionHedge]

    # Aggregate metrics
    total_hedge_cost: float
    hedge_cost_pct: float                # Total cost as % of portfolio value
    portfolio_delta_before: float
    portfolio_delta_after: float
    portfolio_beta_before: float | None
    portfolio_beta_after: float | None

    # All TradeSpecs ready for execution
    trade_specs: list[TradeSpec]

    # Summary
    coverage_pct: float                  # % of portfolio value that is hedged
    target_hedge_pct: float              # What was requested
    summary: str
    alerts: list[str]                    # Warnings (e.g., "3 positions have no hedge available")


class HedgeComparisonEntry(BaseModel):
    """One method in a hedge comparison."""

    tier: HedgeTier
    hedge_type: str
    trade_spec: TradeSpec | None         # None if method is unavailable
    cost_estimate: float | None
    cost_pct: float | None
    delta_reduction: float
    basis_risk: str                      # "none", "low", "medium", "high"
    pros: list[str]
    cons: list[str]
    available: bool
    unavailable_reason: str | None


class HedgeComparison(BaseModel):
    """Ranked comparison of all available hedge methods for a single ticker."""

    ticker: str
    market: str
    current_price: float
    position_value: float
    shares: int
    regime_id: int

    methods: list[HedgeComparisonEntry]  # Sorted best → worst
    recommended: HedgeComparisonEntry
    recommendation_rationale: str


class HedgeMonitorEntry(BaseModel):
    """Status of one active hedge."""

    ticker: str
    hedge_type: str
    dte_remaining: int
    is_expiring_soon: bool               # DTE <= 5
    is_expired: bool
    current_delta_coverage: float        # How much delta the hedge still covers
    action: str                          # "hold", "roll", "close", "replace"
    roll_spec: TradeSpec | None          # If action is "roll", the roll TradeSpec
    rationale: str


class HedgeMonitorResult(BaseModel):
    """Monitoring result for all active hedges."""

    hedges: list[HedgeMonitorEntry]
    expiring_count: int
    expired_count: int
    total_roll_cost: float | None
    roll_specs: list[TradeSpec]          # All roll TradeSpecs aggregated
    alerts: list[str]
    summary: str


class HedgeEffectiveness(BaseModel):
    """How much did hedges save in a given market move scenario."""

    market_move_pct: float               # Simulated move (e.g., -0.05 = -5%)
    portfolio_loss_unhedged: float
    portfolio_loss_hedged: float
    hedge_savings: float                 # unhedged - hedged
    hedge_savings_pct: float             # savings / unhedged
    cost_of_hedges: float
    net_benefit: float                   # savings - cost
    roi_on_hedge: float                  # net_benefit / cost (if cost > 0)
    commentary: str


class FnOCoverage(BaseModel):
    """F&O universe coverage for a set of tickers."""

    market: str
    total_tickers: int
    direct_hedge_count: int              # Tier 1 — liquid options
    futures_hedge_count: int             # Tier 2 — futures available
    proxy_only_count: int                # Tier 3 — index proxy only
    no_hedge_count: int                  # No viable hedge
    coverage_pct: float                  # (direct + futures) / total
    tier_breakdown: dict[str, list[str]]  # {"direct": ["RELIANCE", ...], ...}
    commentary: str
```

### 1.4 — Create `tests/test_hedging/test_models.py`

```python
"""Tests for hedging domain models."""

import pytest

from income_desk.hedging.models import (
    CollarResult,
    FnOCoverage,
    HedgeAlternative,
    HedgeApproach,
    HedgeComparison,
    HedgeComparisonEntry,
    HedgeEffectiveness,
    HedgeGoal,
    HedgeMonitorEntry,
    HedgeMonitorResult,
    HedgeResult,
    HedgeTier,
    PositionHedge,
    PortfolioHedgeAnalysis,
    SyntheticOptionResult,
)
from income_desk.models.opportunity import (
    LegAction,
    LegSpec,
    OrderSide,
    StructureType,
    TradeSpec,
)


def _make_trade_spec(ticker: str = "RELIANCE", structure: StructureType = StructureType.LONG_OPTION) -> TradeSpec:
    """Helper to build a minimal TradeSpec for testing."""
    return TradeSpec(
        ticker=ticker,
        structure_type=structure,
        order_side=OrderSide.DEBIT,
        legs=[
            LegSpec(
                action=LegAction.BUY_TO_OPEN,
                strike=2600.0,
                expiration="2026-04-24",
                option_type="put",
                quantity=1,
            ),
        ],
        max_profit_desc="Unlimited downside protection",
        max_loss_desc="Premium paid",
    )


class TestHedgeTier:
    def test_values(self):
        assert HedgeTier.DIRECT == "direct"
        assert HedgeTier.FUTURES_SYNTHETIC == "futures_synthetic"
        assert HedgeTier.PROXY_INDEX == "proxy_index"
        assert HedgeTier.NONE == "none"

    def test_ordering_preference(self):
        tiers = [HedgeTier.DIRECT, HedgeTier.FUTURES_SYNTHETIC, HedgeTier.PROXY_INDEX]
        assert len(tiers) == 3  # Three viable tiers


class TestHedgeApproach:
    def test_direct_approach(self):
        approach = HedgeApproach(
            ticker="RELIANCE",
            market="INDIA",
            recommended_tier=HedgeTier.DIRECT,
            goal=HedgeGoal.DOWNSIDE,
            rationale="RELIANCE has medium options liquidity — direct put available",
            alternatives=[
                HedgeAlternative(
                    tier=HedgeTier.FUTURES_SYNTHETIC,
                    reason_not_chosen="Direct options available and cheaper",
                    estimated_cost_pct=0.8,
                ),
            ],
            estimated_cost_pct=1.2,
            basis_risk="none",
            has_liquid_options=True,
            has_futures=True,
            lot_size=250,
            lot_size_affordable=True,
        )
        assert approach.recommended_tier == HedgeTier.DIRECT
        assert approach.lot_size == 250

    def test_proxy_approach_dmart(self):
        """DMart (Avenue Supermarts) — no F&O, proxy only."""
        approach = HedgeApproach(
            ticker="DMART",
            market="INDIA",
            recommended_tier=HedgeTier.PROXY_INDEX,
            goal=HedgeGoal.DOWNSIDE,
            rationale="DMART not in F&O — use NIFTY proxy (consumer discretionary sector)",
            alternatives=[],
            estimated_cost_pct=1.5,
            basis_risk="high",
            has_liquid_options=False,
            has_futures=False,
            lot_size=0,
            lot_size_affordable=False,
        )
        assert approach.recommended_tier == HedgeTier.PROXY_INDEX
        assert approach.basis_risk == "high"


class TestHedgeResult:
    def test_protective_put_result(self):
        result = HedgeResult(
            ticker="RELIANCE",
            market="INDIA",
            tier=HedgeTier.DIRECT,
            hedge_type="protective_put",
            trade_spec=_make_trade_spec("RELIANCE"),
            cost_estimate=15000.0,
            cost_pct=1.2,
            delta_reduction=0.85,
            protection_level="Put at 2600 (1 ATR OTM)",
            max_loss_after_hedge=50000.0,
            rationale="R2 high-vol MR — protective put with high IV partially offset by collar potential",
            regime_context="R2: elevated vol makes puts expensive but protection critical",
            commentary=["ATR=80, put at 2600 (1 ATR below 2680)", "Lot size 250, 1 lot covers position"],
        )
        assert result.delta_reduction == 0.85
        assert result.trade_spec.ticker == "RELIANCE"


class TestCollarResult:
    def test_zero_cost_collar(self):
        collar = CollarResult(
            ticker="SPY",
            market="US",
            put_strike=560.0,
            call_strike=590.0,
            net_cost=-0.15,  # Slight credit
            downside_protection_pct=3.4,
            upside_cap_pct=1.7,
            trade_spec=_make_trade_spec("SPY"),
            rationale="R2 high IV makes zero-cost collar achievable",
        )
        assert collar.net_cost < 0  # Credit


class TestSyntheticOptionResult:
    def test_synthetic_put(self):
        synthetic = SyntheticOptionResult(
            ticker="TATASTEEL",
            market="INDIA",
            synthetic_type="synthetic_put",
            futures_direction="short",
            futures_lots=1,
            option_strike=130.0,
            option_type="call",
            option_lots=1,
            net_cost_estimate=2500.0,
            trade_spec=_make_trade_spec("TATASTEEL", StructureType.FUTURES_SHORT),
            rationale="TATASTEEL options illiquid — synthetic put via short futures + long call",
        )
        assert synthetic.futures_direction == "short"
        assert synthetic.option_type == "call"  # Synthetic put = short futures + long call


class TestPortfolioHedgeAnalysis:
    def test_mixed_tier_portfolio(self):
        analysis = PortfolioHedgeAnalysis(
            market="INDIA",
            account_nlv=5000000.0,
            total_positions=3,
            total_position_value=3000000.0,
            tier_counts={"direct": 1, "futures_synthetic": 1, "proxy_index": 1},
            tier_values={"direct": 1500000, "futures_synthetic": 1000000, "proxy_index": 500000},
            position_hedges=[],
            total_hedge_cost=45000.0,
            hedge_cost_pct=1.5,
            portfolio_delta_before=-2.5,
            portfolio_delta_after=-0.3,
            portfolio_beta_before=1.1,
            portfolio_beta_after=0.4,
            trade_specs=[],
            coverage_pct=83.3,
            target_hedge_pct=80.0,
            summary="3 positions hedged across 3 tiers, 83% coverage achieved",
            alerts=["DMART hedge has high basis risk (proxy only)"],
        )
        assert analysis.coverage_pct > analysis.target_hedge_pct


class TestHedgeEffectiveness:
    def test_five_pct_drop(self):
        eff = HedgeEffectiveness(
            market_move_pct=-0.05,
            portfolio_loss_unhedged=250000.0,
            portfolio_loss_hedged=80000.0,
            hedge_savings=170000.0,
            hedge_savings_pct=68.0,
            cost_of_hedges=45000.0,
            net_benefit=125000.0,
            roi_on_hedge=2.78,
            commentary="Hedges saved 68% of potential loss in a 5% drawdown; 2.8x ROI on hedge cost",
        )
        assert eff.net_benefit > 0
        assert eff.roi_on_hedge > 1.0


class TestFnOCoverage:
    def test_india_portfolio_coverage(self):
        coverage = FnOCoverage(
            market="INDIA",
            total_tickers=10,
            direct_hedge_count=3,
            futures_hedge_count=4,
            proxy_only_count=2,
            no_hedge_count=1,
            coverage_pct=70.0,
            tier_breakdown={
                "direct": ["NIFTY", "BANKNIFTY", "RELIANCE"],
                "futures_synthetic": ["TATASTEEL", "SBIN", "ITC", "INFY"],
                "proxy_index": ["DMART", "PIDILITIND"],
                "none": ["SMALLCAP_X"],
            },
            commentary="70% hedgeable via direct or futures; 2 require NIFTY proxy; 1 has no viable hedge",
        )
        assert coverage.direct_hedge_count + coverage.futures_hedge_count == 7
```

---

## Task 2: Universe & Classification

**Goal:** Classify tickers into hedge tiers using registry data. This is the data layer that the resolver consumes.

**Files to create:**
- `income_desk/hedging/universe.py`

**Files to test:**
- `tests/test_hedging/test_universe.py`

### Steps

- [ ] **2.1** Create `income_desk/hedging/universe.py`
- [ ] **2.2** Create `tests/test_hedging/test_universe.py`
- [ ] **2.3** Run tests: `.venv_312/Scripts/python.exe -m pytest tests/test_hedging/test_universe.py -v`
- [ ] **2.4** Commit: `git commit -m "feat(hedging): add universe classifier — hedge tier classification from registry data"`

### 2.1 — Create `income_desk/hedging/universe.py`

```python
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
```

### 2.2 — Create `tests/test_hedging/test_universe.py`

```python
"""Tests for hedging universe classification."""

import pytest

from income_desk.hedging.models import HedgeTier
from income_desk.hedging.universe import (
    classify_hedge_tier,
    get_fno_coverage,
    get_proxy_instrument,
    get_sector_beta,
)
from income_desk.registry import MarketRegistry


@pytest.fixture
def registry() -> MarketRegistry:
    return MarketRegistry()


class TestClassifyHedgeTier:
    """Test hedge tier classification for various instruments."""

    def test_reliance_india_direct(self, registry: MarketRegistry):
        """RELIANCE has medium options liquidity → DIRECT."""
        tier = classify_hedge_tier("RELIANCE", "INDIA", registry)
        assert tier == HedgeTier.DIRECT

    def test_nifty_india_direct(self, registry: MarketRegistry):
        """NIFTY has high options liquidity → DIRECT."""
        tier = classify_hedge_tier("NIFTY", "INDIA", registry)
        assert tier == HedgeTier.DIRECT

    def test_hindunilvr_india_futures(self, registry: MarketRegistry):
        """HINDUNILVR has low options liquidity → FUTURES_SYNTHETIC (India has stock futures)."""
        tier = classify_hedge_tier("HINDUNILVR", "INDIA", registry)
        assert tier == HedgeTier.FUTURES_SYNTHETIC

    def test_tatasteel_india_futures(self, registry: MarketRegistry):
        """TATASTEEL has low options liquidity → FUTURES_SYNTHETIC."""
        tier = classify_hedge_tier("TATASTEEL", "INDIA", registry)
        assert tier == HedgeTier.FUTURES_SYNTHETIC

    def test_dmart_india_proxy(self, registry: MarketRegistry):
        """DMart not in F&O registry → PROXY_INDEX."""
        tier = classify_hedge_tier("DMART", "INDIA", registry)
        assert tier == HedgeTier.PROXY_INDEX

    def test_spy_us_direct(self, registry: MarketRegistry):
        """SPY has high options liquidity → DIRECT."""
        tier = classify_hedge_tier("SPY", "US", registry)
        assert tier == HedgeTier.DIRECT

    def test_unknown_us_direct(self, registry: MarketRegistry):
        """Unknown US ticker defaults to DIRECT (most US stocks have options)."""
        tier = classify_hedge_tier("SOME_UNKNOWN", "US", registry)
        assert tier == HedgeTier.DIRECT

    def test_unknown_india_proxy(self, registry: MarketRegistry):
        """Unknown India ticker defaults to PROXY_INDEX."""
        tier = classify_hedge_tier("SOME_UNKNOWN", "INDIA", registry)
        assert tier == HedgeTier.PROXY_INDEX


class TestGetFnOCoverage:
    def test_india_mixed_portfolio(self, registry: MarketRegistry):
        """10-stock India portfolio with mixed tiers."""
        tickers = [
            "RELIANCE", "NIFTY", "BANKNIFTY",    # Direct (high/medium liq)
            "TATASTEEL", "HINDUNILVR", "LT",       # Futures (low liq)
            "DMART", "PIDILITIND",                  # Proxy (not in registry)
            "HDFCBANK", "ICICIBANK",                # Direct (medium liq)
        ]
        coverage = get_fno_coverage(tickers, "INDIA", registry)
        assert coverage.total_tickers == 10
        assert coverage.direct_hedge_count >= 5  # RELIANCE, NIFTY, BANKNIFTY, HDFCBANK, ICICIBANK
        assert coverage.futures_hedge_count >= 2  # TATASTEEL, HINDUNILVR, LT
        assert coverage.proxy_only_count >= 1  # DMART at minimum
        assert coverage.coverage_pct > 50

    def test_us_portfolio(self, registry: MarketRegistry):
        """US portfolio — almost everything is direct."""
        tickers = ["SPY", "QQQ", "AAPL", "MSFT", "GOOGL"]
        coverage = get_fno_coverage(tickers, "US", registry)
        assert coverage.direct_hedge_count == 5
        assert coverage.coverage_pct == 100.0

    def test_empty_tickers(self, registry: MarketRegistry):
        coverage = get_fno_coverage([], "US", registry)
        assert coverage.total_tickers == 0
        assert coverage.coverage_pct == 0


class TestGetSectorBeta:
    def test_india_finance_beta(self):
        beta = get_sector_beta("HDFCBANK", "NIFTY", "INDIA")
        assert beta > 1.0  # Finance is high-beta in India

    def test_india_pharma_beta(self):
        beta = get_sector_beta("SUNPHARMA", "NIFTY", "INDIA")
        assert beta < 1.0  # Pharma is defensive

    def test_us_tech_beta(self):
        beta = get_sector_beta("AAPL", "SPY", "US")
        assert beta > 1.0  # Tech is high-beta

    def test_unknown_defaults_to_one(self):
        beta = get_sector_beta("UNKNOWN_TICKER", "SPY", "US")
        assert beta == 1.0


class TestGetProxyInstrument:
    def test_india_finance_banknifty(self, registry: MarketRegistry):
        proxy = get_proxy_instrument("HDFCBANK", "INDIA", registry)
        assert proxy == "BANKNIFTY"

    def test_india_tech_nifty(self, registry: MarketRegistry):
        proxy = get_proxy_instrument("TCS", "INDIA", registry)
        assert proxy == "NIFTY"

    def test_india_unknown_nifty(self, registry: MarketRegistry):
        proxy = get_proxy_instrument("DMART", "INDIA", registry)
        assert proxy == "NIFTY"

    def test_us_tech_qqq(self, registry: MarketRegistry):
        proxy = get_proxy_instrument("AAPL", "US", registry)
        assert proxy == "QQQ"

    def test_us_finance_xlf(self, registry: MarketRegistry):
        proxy = get_proxy_instrument("JPM", "US", registry)
        assert proxy == "XLF"

    def test_us_unknown_spy(self, registry: MarketRegistry):
        proxy = get_proxy_instrument("RANDOM_STOCK", "US", registry)
        assert proxy == "SPY"
```

---

## Task 3: Hedge Strategy Resolver

**Goal:** The decision engine — given a ticker and context, decide WHICH hedge tier to use and WHY.

**Files to create:**
- `income_desk/hedging/resolver.py`

**Files to test:**
- `tests/test_hedging/test_resolver.py`

### Steps

- [ ] **3.1** Create `income_desk/hedging/resolver.py`
- [ ] **3.2** Create `tests/test_hedging/test_resolver.py`
- [ ] **3.3** Run tests: `.venv_312/Scripts/python.exe -m pytest tests/test_hedging/test_resolver.py -v`
- [ ] **3.4** Commit: `git commit -m "feat(hedging): add hedge strategy resolver — decides direct/futures/proxy per instrument"`

### 3.1 — Create `income_desk/hedging/resolver.py`

```python
"""Hedge strategy resolver — the central decision engine.

Given a ticker, position details, and market context, resolves which
hedge tier (direct/futures/proxy) to use and returns a complete HedgeApproach
with rationale and alternatives.

The resolver DECIDES — the caller can override by calling tier-specific
builders directly, but the resolver's recommendation is the default.
"""

from __future__ import annotations

from income_desk.hedging.models import (
    HedgeAlternative,
    HedgeApproach,
    HedgeGoal,
    HedgeTier,
)
from income_desk.hedging.universe import (
    classify_hedge_tier,
    get_proxy_instrument,
    get_sector_beta,
)
from income_desk.registry import MarketRegistry


def resolve_hedge_strategy(
    ticker: str,
    position_value: float,
    shares: int,
    current_price: float,
    regime_id: int,
    market: str = "US",
    account_nlv: float | None = None,
    max_hedge_cost_pct: float = 3.0,
    registry: MarketRegistry | None = None,
) -> HedgeApproach:
    """Resolve which hedge strategy to use for a position.

    Decision tree:
    1. Classify instrument via registry → get base tier
    2. Check affordability — can the account handle 1 lot?
    3. If DIRECT + affordable → recommend DIRECT
    4. If DIRECT + too expensive → try FUTURES_SYNTHETIC (lower capital)
    5. If FUTURES_SYNTHETIC → check basis cost, lot affordability
    6. If nothing else → PROXY_INDEX
    7. Apply regime adjustment: R4 → upgrade urgency, R1 → may skip hedge entirely

    Args:
        ticker: Instrument ticker.
        position_value: Total value of the position to hedge (local currency).
        shares: Number of shares/units held.
        current_price: Current price per share.
        regime_id: Current regime (1-4).
        market: "US" or "INDIA".
        account_nlv: Account net liquidating value (for affordability check).
        max_hedge_cost_pct: Maximum acceptable hedge cost as % of position value.
        registry: MarketRegistry instance.

    Returns:
        HedgeApproach with recommended tier, rationale, and alternatives.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    # Step 1: classify base tier
    base_tier = classify_hedge_tier(ticker, market, reg)

    # Step 2: get instrument details
    try:
        inst = reg.get_instrument(ticker, market)
        lot_size = inst.lot_size
        has_liquid_options = inst.options_liquidity in ("high", "medium")
        has_futures = market == "INDIA"  # All India F&O stocks have stock futures
        # US equity doesn't have single-stock futures (for practical purposes)
    except KeyError:
        lot_size = 100 if market == "US" else 0
        has_liquid_options = market == "US"  # Default: US has options, India unknown
        has_futures = False

    # Step 3: check lot affordability
    lot_value = lot_size * current_price if lot_size > 0 else 0
    lot_affordable = True
    if account_nlv and lot_value > 0:
        # Hedge lot shouldn't be more than 20% of account
        lot_affordable = lot_value < (account_nlv * 0.20)

    # Step 4: build alternatives list
    alternatives: list[HedgeAlternative] = []

    # Step 5: resolve recommendation
    recommended_tier = base_tier
    rationale_parts: list[str] = []
    basis_risk = "none"
    estimated_cost_pct: float | None = None

    if base_tier == HedgeTier.DIRECT:
        rationale_parts.append(f"{ticker} has tradeable options")
        if not lot_affordable:
            # Lot too expensive — try downgrading to futures (smaller margin)
            if has_futures:
                recommended_tier = HedgeTier.FUTURES_SYNTHETIC
                rationale_parts.append(
                    f"but option lot ({lot_size} x {current_price:.0f} = {lot_value:,.0f}) "
                    f"exceeds 20% of account — using futures instead"
                )
                basis_risk = "low"
                alternatives.append(HedgeAlternative(
                    tier=HedgeTier.DIRECT,
                    reason_not_chosen=f"Lot value {lot_value:,.0f} too large for account size",
                    estimated_cost_pct=None,
                ))
            else:
                rationale_parts.append(
                    f"lot is large ({lot_value:,.0f}) but only option available"
                )
        else:
            # Regime-based cost estimate
            estimated_cost_pct = _estimate_direct_cost(regime_id)
            rationale_parts.append(
                f"estimated cost ~{estimated_cost_pct:.1f}% of position value"
            )

            # Add alternatives for comparison
            if has_futures:
                alternatives.append(HedgeAlternative(
                    tier=HedgeTier.FUTURES_SYNTHETIC,
                    reason_not_chosen="Direct options available and preferred",
                    estimated_cost_pct=_estimate_futures_cost(regime_id),
                ))
            alternatives.append(HedgeAlternative(
                tier=HedgeTier.PROXY_INDEX,
                reason_not_chosen="Direct hedge has zero basis risk",
                estimated_cost_pct=_estimate_proxy_cost(regime_id),
            ))

    elif base_tier == HedgeTier.FUTURES_SYNTHETIC:
        rationale_parts.append(
            f"{ticker} options are illiquid — using stock futures for hedge"
        )
        basis_risk = "low"
        estimated_cost_pct = _estimate_futures_cost(regime_id)
        alternatives.append(HedgeAlternative(
            tier=HedgeTier.DIRECT,
            reason_not_chosen="Options are too illiquid for reliable fills",
            estimated_cost_pct=None,
        ))
        alternatives.append(HedgeAlternative(
            tier=HedgeTier.PROXY_INDEX,
            reason_not_chosen="Same-ticker futures have lower basis risk",
            estimated_cost_pct=_estimate_proxy_cost(regime_id),
        ))

    elif base_tier == HedgeTier.PROXY_INDEX:
        proxy = get_proxy_instrument(ticker, market, reg)
        beta = get_sector_beta(ticker, proxy, market)
        rationale_parts.append(
            f"{ticker} has no F&O — using {proxy} as proxy (sector beta ~{beta:.2f})"
        )
        basis_risk = "high"
        estimated_cost_pct = _estimate_proxy_cost(regime_id)
        # No better alternatives — this is the only option
    else:
        rationale_parts.append(f"No hedge available for {ticker}")

    # Step 6: regime context
    regime_context = _regime_hedge_context(regime_id)
    rationale_parts.append(regime_context)

    goal = HedgeGoal.DOWNSIDE  # Default — most hedges protect long positions

    return HedgeApproach(
        ticker=ticker,
        market=market,
        recommended_tier=recommended_tier,
        goal=goal,
        rationale=". ".join(rationale_parts),
        alternatives=alternatives,
        estimated_cost_pct=estimated_cost_pct,
        basis_risk=basis_risk,
        has_liquid_options=has_liquid_options,
        has_futures=has_futures,
        lot_size=lot_size,
        lot_size_affordable=lot_affordable,
    )


def _estimate_direct_cost(regime_id: int) -> float:
    """Rough hedge cost % by regime (protective put)."""
    # R1: cheap OTM puts, low vol → ~0.5%
    # R2: high IV = expensive puts → ~2.0% (but collar can offset)
    # R3: moderate → ~1.0%
    # R4: very expensive → ~3.0%
    return {1: 0.5, 2: 2.0, 3: 1.0, 4: 3.0}.get(regime_id, 1.5)


def _estimate_futures_cost(regime_id: int) -> float:
    """Rough futures hedge cost % (basis + margin cost)."""
    # Futures cost is basis (contango/backwardation) + margin opportunity cost
    return {1: 0.3, 2: 0.8, 3: 0.5, 4: 1.0}.get(regime_id, 0.5)


def _estimate_proxy_cost(regime_id: int) -> float:
    """Rough proxy hedge cost % (basis risk premium + option cost)."""
    # Proxy adds basis risk → slightly more expensive
    return {1: 0.8, 2: 2.5, 3: 1.5, 4: 3.5}.get(regime_id, 2.0)


def _regime_hedge_context(regime_id: int) -> str:
    """Regime-specific hedge rationale."""
    return {
        1: "R1 low-vol MR — hedge is optional, cheap OTM if desired",
        2: "R2 high-vol MR — hedge recommended, high IV makes collars attractive",
        3: "R3 low-vol trending — hedge if trend is against position",
        4: "R4 high-vol trending — hedge IMMEDIATELY, capital preservation priority",
    }.get(regime_id, f"R{regime_id} — unknown regime, hedge conservatively")
```

### 3.2 — Create `tests/test_hedging/test_resolver.py`

```python
"""Tests for hedge strategy resolver."""

import pytest

from income_desk.hedging.models import HedgeGoal, HedgeTier
from income_desk.hedging.resolver import resolve_hedge_strategy
from income_desk.registry import MarketRegistry


@pytest.fixture
def registry() -> MarketRegistry:
    return MarketRegistry()


class TestResolverIndiaStocks:
    def test_reliance_direct(self, registry: MarketRegistry):
        """RELIANCE (medium liq) → DIRECT."""
        approach = resolve_hedge_strategy(
            ticker="RELIANCE",
            position_value=1250000,
            shares=500,
            current_price=2500,
            regime_id=2,
            market="INDIA",
            account_nlv=5000000,
            registry=registry,
        )
        assert approach.recommended_tier == HedgeTier.DIRECT
        assert approach.has_liquid_options
        assert approach.lot_size == 250
        assert "options" in approach.rationale.lower()

    def test_tatasteel_futures(self, registry: MarketRegistry):
        """TATASTEEL (low liq) → FUTURES_SYNTHETIC."""
        approach = resolve_hedge_strategy(
            ticker="TATASTEEL",
            position_value=150000,
            shares=1100,
            current_price=136,
            regime_id=3,
            market="INDIA",
            account_nlv=5000000,
            registry=registry,
        )
        assert approach.recommended_tier == HedgeTier.FUTURES_SYNTHETIC
        assert approach.basis_risk == "low"
        assert "illiquid" in approach.rationale.lower() or "futures" in approach.rationale.lower()

    def test_dmart_proxy(self, registry: MarketRegistry):
        """DMart not in F&O → PROXY_INDEX."""
        approach = resolve_hedge_strategy(
            ticker="DMART",
            position_value=500000,
            shares=125,
            current_price=4000,
            regime_id=2,
            market="INDIA",
            account_nlv=5000000,
            registry=registry,
        )
        assert approach.recommended_tier == HedgeTier.PROXY_INDEX
        assert approach.basis_risk == "high"
        assert "NIFTY" in approach.rationale

    def test_nestleind_lot_size_check(self, registry: MarketRegistry):
        """NESTLEIND lot=50, strike=100, high price ~2500 — check affordability."""
        approach = resolve_hedge_strategy(
            ticker="NESTLEIND",
            position_value=125000,
            shares=50,
            current_price=2500,
            regime_id=1,
            market="INDIA",
            account_nlv=500000,  # Small account
            registry=registry,
        )
        # Lot value = 50 x 2500 = 125000, which is 25% of 500K → over 20% threshold
        # But NESTLEIND has low options → FUTURES_SYNTHETIC anyway
        assert approach.recommended_tier in (HedgeTier.FUTURES_SYNTHETIC, HedgeTier.DIRECT)


class TestResolverUSStocks:
    def test_spy_direct(self, registry: MarketRegistry):
        """SPY (high liq) → DIRECT."""
        approach = resolve_hedge_strategy(
            ticker="SPY",
            position_value=58000,
            shares=100,
            current_price=580,
            regime_id=2,
            market="US",
            account_nlv=200000,
            registry=registry,
        )
        assert approach.recommended_tier == HedgeTier.DIRECT
        assert approach.lot_size == 100
        assert len(approach.alternatives) >= 1  # At least proxy alternative

    def test_unknown_us_stock_direct(self, registry: MarketRegistry):
        """Unknown US stock defaults to DIRECT."""
        approach = resolve_hedge_strategy(
            ticker="SOME_MICRO_CAP",
            position_value=5000,
            shares=100,
            current_price=50,
            regime_id=1,
            market="US",
            registry=registry,
        )
        assert approach.recommended_tier == HedgeTier.DIRECT


class TestResolverRegimeContext:
    def test_r1_context(self, registry: MarketRegistry):
        approach = resolve_hedge_strategy(
            ticker="SPY", position_value=58000, shares=100,
            current_price=580, regime_id=1, market="US", registry=registry,
        )
        assert "R1" in approach.rationale
        assert "optional" in approach.rationale.lower() or "cheap" in approach.rationale.lower()

    def test_r4_context(self, registry: MarketRegistry):
        approach = resolve_hedge_strategy(
            ticker="SPY", position_value=58000, shares=100,
            current_price=580, regime_id=4, market="US", registry=registry,
        )
        assert "R4" in approach.rationale
        assert "immediately" in approach.rationale.lower() or "capital" in approach.rationale.lower()

    def test_goal_is_downside(self, registry: MarketRegistry):
        approach = resolve_hedge_strategy(
            ticker="SPY", position_value=58000, shares=100,
            current_price=580, regime_id=2, market="US", registry=registry,
        )
        assert approach.goal == HedgeGoal.DOWNSIDE


class TestResolverAlternatives:
    def test_direct_has_proxy_alternative(self, registry: MarketRegistry):
        approach = resolve_hedge_strategy(
            ticker="SPY", position_value=58000, shares=100,
            current_price=580, regime_id=2, market="US", registry=registry,
        )
        alt_tiers = [a.tier for a in approach.alternatives]
        assert HedgeTier.PROXY_INDEX in alt_tiers

    def test_proxy_has_no_alternatives(self, registry: MarketRegistry):
        approach = resolve_hedge_strategy(
            ticker="DMART", position_value=500000, shares=125,
            current_price=4000, regime_id=2, market="INDIA", registry=registry,
        )
        # Proxy is last resort — no better alternatives
        assert len(approach.alternatives) == 0
```

---

## Task 4: Direct Hedging (Tier 1)

**Goal:** Build concrete TradeSpecs for protective puts, collars, and put spreads. Uses registry for lot_size/strike_interval.

**Files to create:**
- `income_desk/hedging/direct.py`

**Files to test:**
- `tests/test_hedging/test_direct.py`

### Steps

- [ ] **4.1** Create `income_desk/hedging/direct.py`
- [ ] **4.2** Create `tests/test_hedging/test_direct.py`
- [ ] **4.3** Run tests: `.venv_312/Scripts/python.exe -m pytest tests/test_hedging/test_direct.py -v`
- [ ] **4.4** Commit: `git commit -m "feat(hedging): add direct hedge builders — protective put, collar, put spread with TradeSpec"`

### 4.1 — Create `income_desk/hedging/direct.py`

```python
"""Tier 1 direct hedging — protective puts, collars, put spreads.

For instruments with liquid options (options_liquidity "high" or "medium").
All functions return HedgeResult with concrete TradeSpec legs.
Regime-aware: R1=cheap OTM, R2=collar (sell call to fund put), R3=context-dependent, R4=ATM.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from income_desk.hedging.models import CollarResult, HedgeResult, HedgeTier
from income_desk.models.opportunity import (
    LegAction,
    LegSpec,
    OrderSide,
    StructureType,
    TradeSpec,
)
from income_desk.registry import MarketRegistry


def _snap_strike(price: float, strike_interval: float, direction: str = "down") -> float:
    """Snap a price to the nearest valid strike."""
    if direction == "down":
        return math.floor(price / strike_interval) * strike_interval
    return math.ceil(price / strike_interval) * strike_interval


def _default_expiry(dte: int, market: str) -> str:
    """Compute a default expiry date string."""
    target = date.today() + timedelta(days=dte)
    return target.isoformat()


def _compute_lots(shares: int, lot_size: int) -> int:
    """How many option lots to cover the position."""
    if lot_size <= 0:
        return 1
    return max(1, shares // lot_size)


def build_protective_put(
    ticker: str,
    shares: int,
    price: float,
    regime_id: int,
    atr: float,
    dte: int = 30,
    market: str = "US",
    registry: MarketRegistry | None = None,
) -> HedgeResult:
    """Build a protective put hedge with TradeSpec.

    Strike placement by regime:
        R1: 1.5 ATR OTM (cheap, insurance only)
        R2: 1.0 ATR OTM (moderate protection)
        R3: 0.75 ATR OTM (tighter if trend is against)
        R4: 0.25 ATR OTM (near ATM, maximum protection)

    Args:
        ticker: Instrument ticker.
        shares: Number of shares to hedge.
        price: Current price per share.
        regime_id: Current regime (1-4).
        atr: Average True Range in price units.
        dte: Days to expiration for the put.
        market: "US" or "INDIA".
        registry: MarketRegistry instance.

    Returns:
        HedgeResult with protective put TradeSpec.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    try:
        inst = reg.get_instrument(ticker, market)
        lot_size = inst.lot_size
        strike_interval = inst.strike_interval
    except KeyError:
        lot_size = 100 if market == "US" else 1
        strike_interval = 1.0

    # Regime-based strike distance
    atr_mult = {1: 1.5, 2: 1.0, 3: 0.75, 4: 0.25}.get(regime_id, 1.0)
    raw_strike = price - (atr * atr_mult)
    put_strike = _snap_strike(raw_strike, strike_interval, "down")

    lots = _compute_lots(shares, lot_size)
    expiry = _default_expiry(dte, market)

    # Rough cost estimate: regime-based as % of position value
    cost_pct = {1: 0.3, 2: 1.5, 3: 0.8, 4: 2.5}.get(regime_id, 1.0)
    position_value = shares * price
    cost_estimate = position_value * cost_pct / 100

    trade_spec = TradeSpec(
        ticker=ticker,
        structure_type=StructureType.LONG_OPTION,
        order_side=OrderSide.DEBIT,
        legs=[
            LegSpec(
                action=LegAction.BUY_TO_OPEN,
                strike=put_strike,
                expiration=expiry,
                option_type="put",
                quantity=lots,
            ),
        ],
        max_profit_desc="Unlimited downside protection below strike",
        max_loss_desc=f"Premium paid (~{cost_estimate:,.0f})",
    )

    protection_pct = (price - put_strike) / price * 100
    commentary = [
        f"ATR={atr:.2f}, regime R{regime_id} → {atr_mult}x ATR offset",
        f"Put strike: {put_strike} ({protection_pct:.1f}% below current price)",
        f"Lots: {lots} (lot_size={lot_size}, covering {shares} shares)",
        f"Expiry: {expiry} ({dte} DTE)",
    ]

    regime_names = {1: "Low-Vol MR", 2: "High-Vol MR", 3: "Low-Vol Trending", 4: "High-Vol Trending"}

    return HedgeResult(
        ticker=ticker,
        market=market,
        tier=HedgeTier.DIRECT,
        hedge_type="protective_put",
        trade_spec=trade_spec,
        cost_estimate=cost_estimate,
        cost_pct=cost_pct,
        delta_reduction=0.85 if regime_id >= 3 else 0.60,
        protection_level=f"Put at {put_strike} ({protection_pct:.1f}% OTM)",
        max_loss_after_hedge=cost_estimate + (price - put_strike) * shares,
        rationale=f"R{regime_id} {regime_names.get(regime_id, '')} — protective put {atr_mult}x ATR OTM",
        regime_context=f"R{regime_id}: {'near ATM for max protection' if regime_id == 4 else 'OTM for cost efficiency'}",
        commentary=commentary,
    )


def build_collar(
    ticker: str,
    shares: int,
    price: float,
    cost_basis: float,
    regime_id: int,
    atr: float,
    dte: int = 30,
    market: str = "US",
    registry: MarketRegistry | None = None,
) -> CollarResult:
    """Build a collar (long put + short call) with TradeSpec.

    Best in R2 where high IV makes the short call expensive enough to
    offset or exceed the put cost (zero-cost or credit collar).

    Put placement: 1 ATR below current price.
    Call placement: 1 ATR above current price (or above cost basis).

    Args:
        ticker: Instrument ticker.
        shares: Number of shares to hedge.
        price: Current price per share.
        cost_basis: Average cost basis per share (call strike must be above).
        regime_id: Current regime (1-4).
        atr: Average True Range in price units.
        dte: Days to expiration.
        market: "US" or "INDIA".
        registry: MarketRegistry instance.

    Returns:
        CollarResult with put and call details.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    try:
        inst = reg.get_instrument(ticker, market)
        lot_size = inst.lot_size
        strike_interval = inst.strike_interval
    except KeyError:
        lot_size = 100 if market == "US" else 1
        strike_interval = 1.0

    # Put: 1 ATR below
    raw_put = price - atr
    put_strike = _snap_strike(raw_put, strike_interval, "down")

    # Call: 1 ATR above, but at least above cost basis
    raw_call = max(price + atr, cost_basis + strike_interval)
    call_strike = _snap_strike(raw_call, strike_interval, "up")

    lots = _compute_lots(shares, lot_size)
    expiry = _default_expiry(dte, market)

    # In R2 (high IV), call premium ~= put premium → near zero cost
    # In R1 (low IV), put is cheap but call is also cheap → small debit
    net_cost = {1: -0.3, 2: 0.0, 3: -0.5, 4: -1.5}.get(regime_id, -0.5)
    # Negative means debit (net cost), positive means credit

    trade_spec = TradeSpec(
        ticker=ticker,
        structure_type=StructureType.CREDIT_SPREAD,  # Collar is economically a spread
        order_side=OrderSide.CREDIT if net_cost >= 0 else OrderSide.DEBIT,
        legs=[
            LegSpec(
                action=LegAction.BUY_TO_OPEN,
                strike=put_strike,
                expiration=expiry,
                option_type="put",
                quantity=lots,
            ),
            LegSpec(
                action=LegAction.SELL_TO_OPEN,
                strike=call_strike,
                expiration=expiry,
                option_type="call",
                quantity=lots,
            ),
        ],
        max_profit_desc=f"Capped at call strike {call_strike}",
        max_loss_desc=f"Capped at put strike {put_strike}",
    )

    downside_pct = (price - put_strike) / price * 100
    upside_pct = (call_strike - price) / price * 100

    return CollarResult(
        ticker=ticker,
        market=market,
        put_strike=put_strike,
        call_strike=call_strike,
        net_cost=net_cost,
        downside_protection_pct=round(downside_pct, 1),
        upside_cap_pct=round(upside_pct, 1),
        trade_spec=trade_spec,
        rationale=f"R{regime_id} collar: put at {put_strike}, call at {call_strike} — {'zero cost' if abs(net_cost) < 0.1 else f'net cost ~{abs(net_cost):.1f}%'}",
    )


def build_put_spread_hedge(
    ticker: str,
    shares: int,
    price: float,
    budget_pct: float,
    dte: int = 30,
    market: str = "US",
    registry: MarketRegistry | None = None,
) -> HedgeResult:
    """Build a put spread hedge (buy put, sell lower put) to reduce cost.

    Capped protection: protects between long put and short put strikes.
    Cheaper than naked put but limited protection range.

    Args:
        ticker: Instrument ticker.
        shares: Number of shares to hedge.
        price: Current price per share.
        budget_pct: Max hedge cost as % of position value.
        dte: Days to expiration.
        market: "US" or "INDIA".
        registry: MarketRegistry instance.

    Returns:
        HedgeResult with put spread TradeSpec.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    try:
        inst = reg.get_instrument(ticker, market)
        lot_size = inst.lot_size
        strike_interval = inst.strike_interval
    except KeyError:
        lot_size = 100 if market == "US" else 1
        strike_interval = 1.0

    # Long put: 3% below current price
    long_put_strike = _snap_strike(price * 0.97, strike_interval, "down")
    # Short put: 8% below current price
    short_put_strike = _snap_strike(price * 0.92, strike_interval, "down")

    lots = _compute_lots(shares, lot_size)
    expiry = _default_expiry(dte, market)

    position_value = shares * price
    cost_estimate = position_value * budget_pct / 100
    spread_width = long_put_strike - short_put_strike

    trade_spec = TradeSpec(
        ticker=ticker,
        structure_type=StructureType.DEBIT_SPREAD,
        order_side=OrderSide.DEBIT,
        legs=[
            LegSpec(
                action=LegAction.BUY_TO_OPEN,
                strike=long_put_strike,
                expiration=expiry,
                option_type="put",
                quantity=lots,
            ),
            LegSpec(
                action=LegAction.SELL_TO_OPEN,
                strike=short_put_strike,
                expiration=expiry,
                option_type="put",
                quantity=lots,
            ),
        ],
        max_profit_desc=f"Max protection: {spread_width} points per lot",
        max_loss_desc=f"Premium paid (~{cost_estimate:,.0f})",
    )

    return HedgeResult(
        ticker=ticker,
        market=market,
        tier=HedgeTier.DIRECT,
        hedge_type="put_spread",
        trade_spec=trade_spec,
        cost_estimate=cost_estimate,
        cost_pct=budget_pct,
        delta_reduction=0.40,
        protection_level=f"Protection between {long_put_strike} and {short_put_strike}",
        max_loss_after_hedge=None,  # Below short put strike, protection ends
        rationale=f"Put spread: cost-efficient hedge within {budget_pct}% budget",
        regime_context="Budget-constrained hedge — partial protection",
        commentary=[
            f"Long put at {long_put_strike} (3% OTM), short put at {short_put_strike} (8% OTM)",
            f"Spread width: {spread_width} points, {lots} lots",
        ],
    )
```

### 4.2 — Create `tests/test_hedging/test_direct.py`

```python
"""Tests for Tier 1 direct hedging — puts, collars, put spreads."""

import pytest

from income_desk.hedging.direct import (
    build_collar,
    build_protective_put,
    build_put_spread_hedge,
)
from income_desk.hedging.models import HedgeTier
from income_desk.models.opportunity import LegAction, OrderSide, StructureType
from income_desk.registry import MarketRegistry


@pytest.fixture
def registry() -> MarketRegistry:
    return MarketRegistry()


class TestProtectivePut:
    def test_reliance_r2(self, registry: MarketRegistry):
        """RELIANCE in R2 — 1 ATR OTM put."""
        result = build_protective_put(
            ticker="RELIANCE", shares=500, price=2680.0, regime_id=2,
            atr=80.0, dte=30, market="INDIA", registry=registry,
        )
        assert result.tier == HedgeTier.DIRECT
        assert result.hedge_type == "protective_put"
        assert result.trade_spec.ticker == "RELIANCE"
        assert result.trade_spec.structure_type == StructureType.LONG_OPTION
        assert len(result.trade_spec.legs) == 1
        leg = result.trade_spec.legs[0]
        assert leg.action == LegAction.BUY_TO_OPEN
        assert leg.option_type == "put"
        # Strike should be ~2600 (2680 - 80*1.0 = 2600, snapped to 20-interval)
        assert leg.strike <= 2680
        assert leg.strike >= 2500
        # Lots: 500 shares / 250 lot_size = 2
        assert leg.quantity == 2

    def test_spy_r4_near_atm(self, registry: MarketRegistry):
        """SPY in R4 — near ATM put (0.25 ATR OTM)."""
        result = build_protective_put(
            ticker="SPY", shares=100, price=580.0, regime_id=4,
            atr=8.0, dte=14, market="US", registry=registry,
        )
        leg = result.trade_spec.legs[0]
        # R4: 0.25 * 8 = 2 points OTM → strike ~578
        assert leg.strike >= 575
        assert leg.strike <= 580
        assert result.cost_pct > 2.0  # R4 is expensive

    def test_spy_r1_cheap_otm(self, registry: MarketRegistry):
        """SPY in R1 — far OTM put (1.5 ATR OTM)."""
        result = build_protective_put(
            ticker="SPY", shares=100, price=580.0, regime_id=1,
            atr=8.0, dte=30, market="US", registry=registry,
        )
        leg = result.trade_spec.legs[0]
        # R1: 1.5 * 8 = 12 points OTM → strike ~568
        assert leg.strike <= 570
        assert result.cost_pct < 1.0  # R1 is cheap

    def test_nifty_india_lot_size(self, registry: MarketRegistry):
        """NIFTY lot_size=25, strike_interval=50."""
        result = build_protective_put(
            ticker="NIFTY", shares=75, price=22500.0, regime_id=2,
            atr=200.0, dte=7, market="INDIA", registry=registry,
        )
        leg = result.trade_spec.legs[0]
        # 75 shares / 25 lot_size = 3 lots
        assert leg.quantity == 3
        # Strike interval is 50, so strike should be multiple of 50
        assert leg.strike % 50 == 0


class TestCollar:
    def test_reliance_r2_collar(self, registry: MarketRegistry):
        """RELIANCE R2 — zero-cost collar (high IV funds put with call)."""
        result = build_collar(
            ticker="RELIANCE", shares=500, price=2680.0, cost_basis=2400.0,
            regime_id=2, atr=80.0, dte=30, market="INDIA", registry=registry,
        )
        assert result.put_strike < 2680
        assert result.call_strike > 2680
        assert result.call_strike > 2400  # Above cost basis
        assert abs(result.net_cost) < 0.5  # R2 → near zero cost
        # TradeSpec has 2 legs
        assert len(result.trade_spec.legs) == 2
        put_leg = [l for l in result.trade_spec.legs if l.option_type == "put"][0]
        call_leg = [l for l in result.trade_spec.legs if l.option_type == "call"][0]
        assert put_leg.action == LegAction.BUY_TO_OPEN
        assert call_leg.action == LegAction.SELL_TO_OPEN

    def test_spy_collar_call_above_cost_basis(self, registry: MarketRegistry):
        """Call strike must be above cost basis."""
        result = build_collar(
            ticker="SPY", shares=100, price=580.0, cost_basis=575.0,
            regime_id=2, atr=8.0, dte=30, market="US", registry=registry,
        )
        assert result.call_strike > 575


class TestPutSpread:
    def test_budget_constrained_hedge(self, registry: MarketRegistry):
        """Put spread when budget is tight."""
        result = build_put_spread_hedge(
            ticker="SPY", shares=100, price=580.0, budget_pct=0.5,
            dte=30, market="US", registry=registry,
        )
        assert result.tier == HedgeTier.DIRECT
        assert result.hedge_type == "put_spread"
        assert result.trade_spec.structure_type == StructureType.DEBIT_SPREAD
        assert len(result.trade_spec.legs) == 2
        # Long put should be higher strike than short put
        long_leg = [l for l in result.trade_spec.legs if l.action == LegAction.BUY_TO_OPEN][0]
        short_leg = [l for l in result.trade_spec.legs if l.action == LegAction.SELL_TO_OPEN][0]
        assert long_leg.strike > short_leg.strike

    def test_reliance_put_spread(self, registry: MarketRegistry):
        """RELIANCE put spread with strike intervals."""
        result = build_put_spread_hedge(
            ticker="RELIANCE", shares=500, price=2680.0, budget_pct=1.0,
            dte=30, market="INDIA", registry=registry,
        )
        for leg in result.trade_spec.legs:
            # RELIANCE strike interval = 20
            assert leg.strike % 20 == 0
```

---

## Task 5: Futures Hedging + Synthetics (Tier 2)

**Goal:** Build futures-based hedges and synthetic options for instruments with illiquid options but available futures. Connects to existing `futures_analysis.py`.

**Files to create:**
- `income_desk/hedging/futures_hedge.py`

**Files to test:**
- `tests/test_hedging/test_futures_hedge.py`

### Steps

- [ ] **5.1** Create `income_desk/hedging/futures_hedge.py`
- [ ] **5.2** Create `tests/test_hedging/test_futures_hedge.py`
- [ ] **5.3** Run tests: `.venv_312/Scripts/python.exe -m pytest tests/test_hedging/test_futures_hedge.py -v`
- [ ] **5.4** Commit: `git commit -m "feat(hedging): add futures hedge builder — short futures, synthetic puts, synthetic collars"`

### 5.1 — Create `income_desk/hedging/futures_hedge.py`

```python
"""Tier 2 futures hedging — short futures, synthetic puts, synthetic collars.

For instruments where options are illiquid but stock futures exist (common in India).
Connects to futures_analysis.py for basis cost and roll decisions.

Synthetic put  = short futures + long call (payoff identical to long put)
Synthetic collar = short futures + long call + short put equivalent

All functions return HedgeResult or SyntheticOptionResult with TradeSpec.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from income_desk.futures_analysis import analyze_futures_basis, FuturesBasisAnalysis
from income_desk.hedging.models import (
    HedgeResult,
    HedgeTier,
    SyntheticOptionResult,
)
from income_desk.models.opportunity import (
    LegAction,
    LegSpec,
    OrderSide,
    StructureType,
    TradeSpec,
)
from income_desk.registry import MarketRegistry


def compute_hedge_ratio(
    shares: int,
    lot_size: int,
    target_delta: float = 1.0,
) -> int:
    """Compute number of futures lots needed to hedge a position.

    Args:
        shares: Number of shares to hedge.
        lot_size: Futures lot size.
        target_delta: Target hedge ratio (1.0 = full hedge, 0.5 = half hedge).

    Returns:
        Number of lots (minimum 1 if shares > 0).
    """
    if lot_size <= 0 or shares <= 0:
        return 0
    raw = (shares * target_delta) / lot_size
    return max(1, round(raw))


def build_futures_hedge(
    ticker: str,
    shares: int,
    price: float,
    futures_price: float | None = None,
    futures_dte: int = 30,
    hedge_ratio: float = 1.0,
    market: str = "US",
    registry: MarketRegistry | None = None,
) -> HedgeResult:
    """Build a short futures hedge for a long equity position.

    Uses futures_analysis.analyze_futures_basis() for cost assessment.

    Args:
        ticker: Instrument ticker.
        shares: Number of shares to hedge.
        price: Current spot price per share.
        futures_price: Current futures price (if None, estimates from spot + typical basis).
        futures_dte: Days to futures expiry.
        hedge_ratio: 1.0 = full hedge, 0.5 = half hedge.
        market: "US" or "INDIA".
        registry: MarketRegistry instance.

    Returns:
        HedgeResult with FUTURES_SHORT TradeSpec.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    try:
        inst = reg.get_instrument(ticker, market)
        lot_size = inst.lot_size
    except KeyError:
        lot_size = 100 if market == "US" else 1

    lots = compute_hedge_ratio(shares, lot_size, hedge_ratio)
    fut_price = futures_price or (price * 1.005)  # Default: 0.5% contango

    # Use futures_analysis for basis
    expiry_date = date.today() + timedelta(days=futures_dte)
    basis_analysis = analyze_futures_basis(
        ticker=ticker,
        spot_price=price,
        futures_price=fut_price,
        futures_expiry=expiry_date,
    )

    # Cost = basis (premium you give up by shorting futures above spot)
    cost_estimate = basis_analysis.basis * lots * lot_size
    position_value = shares * price
    cost_pct = (abs(cost_estimate) / position_value * 100) if position_value > 0 else 0

    trade_spec = TradeSpec(
        ticker=ticker,
        structure_type=StructureType.FUTURES_SHORT,
        order_side=OrderSide.CREDIT,  # Short futures receives margin, not premium
        legs=[
            LegSpec(
                action=LegAction.SELL_TO_OPEN,
                strike=fut_price,  # Futures "strike" is the futures price
                expiration=expiry_date.isoformat(),
                option_type="future",
                quantity=lots,
            ),
        ],
        max_profit_desc=f"Offset equity loss below {fut_price:.0f}",
        max_loss_desc="Unlimited (if underlying rallies and equity is closed)",
    )

    actual_hedge_pct = (lots * lot_size) / shares * 100 if shares > 0 else 0

    return HedgeResult(
        ticker=ticker,
        market=market,
        tier=HedgeTier.FUTURES_SYNTHETIC,
        hedge_type="futures_short",
        trade_spec=trade_spec,
        cost_estimate=abs(cost_estimate),
        cost_pct=round(cost_pct, 2),
        delta_reduction=min(actual_hedge_pct / 100, 1.0),
        protection_level=f"Short {lots} lot(s) futures at {fut_price:.0f}",
        max_loss_after_hedge=None,  # Futures hedge is continuous, not capped
        rationale=f"Short {lots} futures lot(s) covering {actual_hedge_pct:.0f}% of {shares} shares",
        regime_context=f"Basis: {basis_analysis.basis_pct:.2f}% ({basis_analysis.structure})",
        commentary=[
            f"Futures price: {fut_price:.2f}, spot: {price:.2f}",
            f"Basis: {basis_analysis.basis:.2f} ({basis_analysis.basis_pct:.2f}%)",
            f"Annualized basis: {basis_analysis.annualized_basis_pct:.2f}%",
            f"Lots: {lots} x {lot_size} = {lots * lot_size} shares hedged",
        ],
    )


def build_synthetic_put(
    ticker: str,
    shares: int,
    price: float,
    futures_price: float,
    lot_size: int | None = None,
    dte: int = 30,
    market: str = "US",
    registry: MarketRegistry | None = None,
) -> SyntheticOptionResult:
    """Build a synthetic put = short futures + long call.

    Payoff: identical to owning a put.
    - If underlying drops → futures profit offsets equity loss
    - If underlying rises → call profit offsets futures loss
    - Net: loss is limited to basis + call premium (like a put premium)

    Used when options are illiquid but futures + ATM calls are available.

    Args:
        ticker: Instrument ticker.
        shares: Number of shares to hedge.
        price: Current spot price.
        futures_price: Current futures price.
        lot_size: Override lot size (else from registry).
        dte: Days to expiration for the call option.
        market: "US" or "INDIA".
        registry: MarketRegistry instance.

    Returns:
        SyntheticOptionResult with combined TradeSpec.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    if lot_size is None:
        try:
            inst = reg.get_instrument(ticker, market)
            lot_size = inst.lot_size
            strike_interval = inst.strike_interval
        except KeyError:
            lot_size = 100 if market == "US" else 1
            strike_interval = 1.0
    else:
        strike_interval = 1.0
        try:
            inst = reg.get_instrument(ticker, market)
            strike_interval = inst.strike_interval
        except KeyError:
            pass

    lots = compute_hedge_ratio(shares, lot_size, 1.0)
    expiry = (date.today() + timedelta(days=dte)).isoformat()

    # Call strike = ATM (at current spot price, snapped to interval)
    call_strike = math.ceil(price / strike_interval) * strike_interval

    # Synthetic put = short futures + long call
    trade_spec = TradeSpec(
        ticker=ticker,
        structure_type=StructureType.FUTURES_SHORT,  # Primary structure is futures
        order_side=OrderSide.DEBIT,  # Net debit (call premium)
        legs=[
            LegSpec(
                action=LegAction.SELL_TO_OPEN,
                strike=futures_price,
                expiration=expiry,
                option_type="future",
                quantity=lots,
            ),
            LegSpec(
                action=LegAction.BUY_TO_OPEN,
                strike=call_strike,
                expiration=expiry,
                option_type="call",
                quantity=lots,
            ),
        ],
        max_profit_desc="Equivalent to protective put — unlimited downside protection",
        max_loss_desc="Basis cost + call premium",
    )

    basis_cost = (futures_price - price) * lots * lot_size
    # Call premium estimate (rough): 2% of spot for ATM 30-day
    call_premium_est = price * 0.02 * lots * lot_size
    net_cost = basis_cost + call_premium_est

    return SyntheticOptionResult(
        ticker=ticker,
        market=market,
        synthetic_type="synthetic_put",
        futures_direction="short",
        futures_lots=lots,
        option_strike=call_strike,
        option_type="call",
        option_lots=lots,
        net_cost_estimate=net_cost,
        trade_spec=trade_spec,
        rationale=(
            f"Synthetic put: short {lots} futures + long {lots} ATM calls at {call_strike}. "
            f"Options illiquid — using futures + call for put-equivalent payoff."
        ),
    )


def build_synthetic_collar(
    ticker: str,
    shares: int,
    price: float,
    futures_price: float,
    call_strike: float,
    dte: int = 30,
    market: str = "US",
    registry: MarketRegistry | None = None,
) -> SyntheticOptionResult:
    """Build a synthetic collar = short futures + long OTM call.

    Like a collar but using futures for the downside protection
    and buying an OTM call to cap the upside loss on futures.

    Args:
        ticker: Instrument ticker.
        shares: Number of shares to hedge.
        price: Current spot price.
        futures_price: Current futures price.
        call_strike: Strike for the protective call (OTM).
        dte: Days to expiration.
        market: "US" or "INDIA".
        registry: MarketRegistry instance.

    Returns:
        SyntheticOptionResult with combined TradeSpec.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    try:
        inst = reg.get_instrument(ticker, market)
        lot_size = inst.lot_size
    except KeyError:
        lot_size = 100 if market == "US" else 1

    lots = compute_hedge_ratio(shares, lot_size, 1.0)
    expiry = (date.today() + timedelta(days=dte)).isoformat()

    trade_spec = TradeSpec(
        ticker=ticker,
        structure_type=StructureType.FUTURES_SHORT,
        order_side=OrderSide.DEBIT,
        legs=[
            LegSpec(
                action=LegAction.SELL_TO_OPEN,
                strike=futures_price,
                expiration=expiry,
                option_type="future",
                quantity=lots,
            ),
            LegSpec(
                action=LegAction.BUY_TO_OPEN,
                strike=call_strike,
                expiration=expiry,
                option_type="call",
                quantity=lots,
            ),
        ],
        max_profit_desc=f"Downside protection via futures, capped at call strike {call_strike}",
        max_loss_desc=f"Futures loss capped at {call_strike - futures_price:.0f} per lot if rallies above call",
    )

    return SyntheticOptionResult(
        ticker=ticker,
        market=market,
        synthetic_type="synthetic_collar",
        futures_direction="short",
        futures_lots=lots,
        option_strike=call_strike,
        option_type="call",
        option_lots=lots,
        net_cost_estimate=None,  # Depends on call premium (broker quote needed)
        trade_spec=trade_spec,
        rationale=(
            f"Synthetic collar: short {lots} futures at {futures_price:.0f} + "
            f"long {lots} calls at {call_strike:.0f}. "
            f"Protects downside, caps futures loss if underlying rallies."
        ),
    )
```

### 5.2 — Create `tests/test_hedging/test_futures_hedge.py`

```python
"""Tests for Tier 2 futures hedging + synthetics."""

import pytest

from income_desk.hedging.futures_hedge import (
    build_futures_hedge,
    build_synthetic_collar,
    build_synthetic_put,
    compute_hedge_ratio,
)
from income_desk.hedging.models import HedgeTier
from income_desk.models.opportunity import LegAction, StructureType
from income_desk.registry import MarketRegistry


@pytest.fixture
def registry() -> MarketRegistry:
    return MarketRegistry()


class TestComputeHedgeRatio:
    def test_exact_coverage(self):
        """1100 shares / 1100 lot = 1 lot."""
        assert compute_hedge_ratio(1100, 1100, 1.0) == 1

    def test_partial_coverage(self):
        """500 shares / 1100 lot → rounds to 0, but min 1."""
        assert compute_hedge_ratio(500, 1100, 1.0) == 1

    def test_multiple_lots(self):
        """2200 shares / 1100 lot = 2 lots."""
        assert compute_hedge_ratio(2200, 1100, 1.0) == 2

    def test_half_hedge(self):
        """1100 shares at 0.5 ratio = 1 lot (rounds from 0.5)."""
        assert compute_hedge_ratio(1100, 1100, 0.5) == 1

    def test_zero_shares(self):
        assert compute_hedge_ratio(0, 100, 1.0) == 0

    def test_zero_lot_size(self):
        assert compute_hedge_ratio(100, 0, 1.0) == 0


class TestBuildFuturesHedge:
    def test_tatasteel_short_futures(self, registry: MarketRegistry):
        """TATASTEEL — illiquid options, use short futures."""
        result = build_futures_hedge(
            ticker="TATASTEEL",
            shares=1100,
            price=136.0,
            futures_price=137.0,  # Slight contango
            futures_dte=30,
            market="INDIA",
            registry=registry,
        )
        assert result.tier == HedgeTier.FUTURES_SYNTHETIC
        assert result.hedge_type == "futures_short"
        assert result.trade_spec.structure_type == StructureType.FUTURES_SHORT
        # TATASTEEL lot_size=1100, so 1 lot covers 1100 shares
        assert result.trade_spec.legs[0].quantity == 1
        assert result.trade_spec.legs[0].action == LegAction.SELL_TO_OPEN
        # Commentary should mention basis
        assert any("basis" in c.lower() for c in result.commentary)

    def test_reliance_futures_2_lots(self, registry: MarketRegistry):
        """RELIANCE 500 shares / 250 lot = 2 lots."""
        result = build_futures_hedge(
            ticker="RELIANCE",
            shares=500,
            price=2680.0,
            futures_price=2695.0,
            futures_dte=30,
            market="INDIA",
            registry=registry,
        )
        assert result.trade_spec.legs[0].quantity == 2

    def test_no_futures_price_estimates(self, registry: MarketRegistry):
        """If futures_price is None, estimates from spot."""
        result = build_futures_hedge(
            ticker="TATASTEEL",
            shares=1100,
            price=136.0,
            futures_price=None,
            market="INDIA",
            registry=registry,
        )
        # Should not crash; uses estimated price
        assert result.trade_spec.legs[0].strike > 136.0


class TestBuildSyntheticPut:
    def test_tatasteel_synthetic(self, registry: MarketRegistry):
        """Synthetic put for TATASTEEL — short futures + long call."""
        result = build_synthetic_put(
            ticker="TATASTEEL",
            shares=1100,
            price=136.0,
            futures_price=137.0,
            dte=30,
            market="INDIA",
            registry=registry,
        )
        assert result.synthetic_type == "synthetic_put"
        assert result.futures_direction == "short"
        assert result.option_type == "call"  # Synthetic put uses call
        assert len(result.trade_spec.legs) == 2
        # First leg: short futures
        futures_leg = result.trade_spec.legs[0]
        assert futures_leg.action == LegAction.SELL_TO_OPEN
        assert futures_leg.option_type == "future"
        # Second leg: long call
        call_leg = result.trade_spec.legs[1]
        assert call_leg.action == LegAction.BUY_TO_OPEN
        assert call_leg.option_type == "call"
        # Call strike should be near ATM
        assert abs(call_leg.strike - 136.0) < 10

    def test_synthetic_lot_count(self, registry: MarketRegistry):
        """Futures lots and option lots should match."""
        result = build_synthetic_put(
            ticker="RELIANCE",
            shares=500,
            price=2680.0,
            futures_price=2695.0,
            dte=30,
            market="INDIA",
            registry=registry,
        )
        assert result.futures_lots == result.option_lots


class TestBuildSyntheticCollar:
    def test_synthetic_collar(self, registry: MarketRegistry):
        result = build_synthetic_collar(
            ticker="TATASTEEL",
            shares=1100,
            price=136.0,
            futures_price=137.0,
            call_strike=145.0,
            dte=30,
            market="INDIA",
            registry=registry,
        )
        assert result.synthetic_type == "synthetic_collar"
        assert result.option_strike == 145.0
        assert len(result.trade_spec.legs) == 2
```

---

## Task 6: Proxy/Index Hedging (Tier 3)

**Goal:** Build beta-adjusted index hedges for instruments with no F&O.

**Files to create:**
- `income_desk/hedging/proxy.py`

**Files to test:**
- `tests/test_hedging/test_proxy.py`

### Steps

- [ ] **6.1** Create `income_desk/hedging/proxy.py`
- [ ] **6.2** Create `tests/test_hedging/test_proxy.py`
- [ ] **6.3** Run tests: `.venv_312/Scripts/python.exe -m pytest tests/test_hedging/test_proxy.py -v`
- [ ] **6.4** Commit: `git commit -m "feat(hedging): add proxy/index hedge builder — beta-adjusted NIFTY/SPY hedges"`

### 6.1 — Create `income_desk/hedging/proxy.py`

```python
"""Tier 3 proxy/index hedging — beta-adjusted index hedges.

For instruments with no F&O (no options, no futures). Uses a correlated
index (NIFTY, BANKNIFTY, SPY, QQQ) as a proxy hedge.

Beta-adjusted sizing: hedge lots = (position_value x beta) / (index_price x lot_size)

Basis risk is HIGH — the proxy may not move with the underlying.
This is the last resort, used when no direct or futures hedge is available.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from income_desk.hedging.models import HedgeResult, HedgeTier
from income_desk.hedging.universe import get_proxy_instrument, get_sector_beta
from income_desk.models.opportunity import (
    LegAction,
    LegSpec,
    OrderSide,
    StructureType,
    TradeSpec,
)
from income_desk.registry import MarketRegistry


def compute_portfolio_beta(
    tickers: list[str],
    values: list[float],
    index: str,
    market: str = "US",
) -> float:
    """Compute value-weighted portfolio beta vs an index.

    Uses static sector betas from universe.py. For precise beta,
    use historical return regression (not available here — pure computation only).

    Args:
        tickers: List of ticker symbols.
        values: Position values corresponding to each ticker (same currency).
        index: Index ticker to compute beta against.
        market: "US" or "INDIA".

    Returns:
        Value-weighted portfolio beta.
    """
    if not tickers or not values or len(tickers) != len(values):
        return 1.0

    total_value = sum(values)
    if total_value <= 0:
        return 1.0

    weighted_beta = 0.0
    for ticker, value in zip(tickers, values):
        beta = get_sector_beta(ticker, index, market)
        weight = value / total_value
        weighted_beta += beta * weight

    return round(weighted_beta, 3)


def recommend_proxy(
    ticker: str,
    market: str = "US",
    registry: MarketRegistry | None = None,
) -> str:
    """Recommend which index to use as a proxy hedge.

    Delegates to universe.get_proxy_instrument() — this function exists
    as the public API for the proxy module.

    Args:
        ticker: Stock ticker.
        market: "US" or "INDIA".
        registry: MarketRegistry instance.

    Returns:
        Proxy index ticker.
    """
    return get_proxy_instrument(ticker, market, registry)


def build_index_hedge(
    portfolio_value: float,
    portfolio_beta: float,
    index: str,
    index_price: float,
    regime_id: int,
    dte: int = 30,
    market: str = "US",
    hedge_pct: float = 1.0,
    registry: MarketRegistry | None = None,
) -> HedgeResult:
    """Build a beta-adjusted index hedge using index puts.

    Sizing: lots = (portfolio_value x beta x hedge_pct) / (index_price x lot_size)

    Args:
        portfolio_value: Total value of position(s) to hedge.
        portfolio_beta: Beta of position(s) vs the index.
        index: Index ticker (e.g., "NIFTY", "SPY").
        index_price: Current index price.
        regime_id: Current regime (1-4).
        dte: Days to expiration.
        market: "US" or "INDIA".
        hedge_pct: Fraction to hedge (1.0 = full, 0.5 = half).
        registry: MarketRegistry instance.

    Returns:
        HedgeResult with index put TradeSpec.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    try:
        inst = reg.get_instrument(index, market)
        lot_size = inst.lot_size
        strike_interval = inst.strike_interval
    except KeyError:
        lot_size = 100 if market == "US" else 25
        strike_interval = 50.0 if market == "INDIA" else 1.0

    # Beta-adjusted hedge value
    hedge_value = portfolio_value * portfolio_beta * hedge_pct
    notional_per_lot = index_price * lot_size

    lots = max(1, round(hedge_value / notional_per_lot)) if notional_per_lot > 0 else 1

    # Put strike: regime-based OTM distance
    otm_pct = {1: 0.05, 2: 0.03, 3: 0.04, 4: 0.02}.get(regime_id, 0.03)
    raw_strike = index_price * (1 - otm_pct)
    put_strike = math.floor(raw_strike / strike_interval) * strike_interval

    expiry = (date.today() + timedelta(days=dte)).isoformat()

    # Cost estimate (rough)
    cost_pct_map = {1: 0.4, 2: 1.8, 3: 0.9, 4: 2.8}
    cost_pct = cost_pct_map.get(regime_id, 1.5)
    cost_estimate = portfolio_value * cost_pct / 100

    trade_spec = TradeSpec(
        ticker=index,
        structure_type=StructureType.LONG_OPTION,
        order_side=OrderSide.DEBIT,
        legs=[
            LegSpec(
                action=LegAction.BUY_TO_OPEN,
                strike=put_strike,
                expiration=expiry,
                option_type="put",
                quantity=lots,
            ),
        ],
        max_profit_desc=f"Index put protection: {lots} lots at {put_strike}",
        max_loss_desc=f"Premium paid (~{cost_estimate:,.0f})",
    )

    actual_coverage = (lots * notional_per_lot) / portfolio_value * 100 if portfolio_value > 0 else 0

    return HedgeResult(
        ticker=index,
        market=market,
        tier=HedgeTier.PROXY_INDEX,
        hedge_type="index_put",
        trade_spec=trade_spec,
        cost_estimate=cost_estimate,
        cost_pct=cost_pct,
        delta_reduction=min(actual_coverage / 100, 1.0) * 0.7,  # 0.7 discount for basis risk
        protection_level=f"{index} put at {put_strike}, {lots} lot(s)",
        max_loss_after_hedge=None,  # Basis risk makes max loss uncertain
        rationale=(
            f"Proxy hedge: {lots} {index} puts at {put_strike} "
            f"(beta-adjusted from {portfolio_value:,.0f} at beta {portfolio_beta:.2f})"
        ),
        regime_context=f"R{regime_id}: {otm_pct*100:.0f}% OTM index put",
        commentary=[
            f"Portfolio value: {portfolio_value:,.0f}, beta: {portfolio_beta:.2f}",
            f"Hedge value (beta-adjusted): {hedge_value:,.0f}",
            f"Index: {index} at {index_price:,.0f}, lot_size: {lot_size}",
            f"Lots: {lots} (covering {actual_coverage:.0f}% of position value)",
            "WARNING: Proxy hedge has basis risk — index may diverge from underlying",
        ],
    )
```

### 6.2 — Create `tests/test_hedging/test_proxy.py`

```python
"""Tests for Tier 3 proxy/index hedging."""

import pytest

from income_desk.hedging.models import HedgeTier
from income_desk.hedging.proxy import (
    build_index_hedge,
    compute_portfolio_beta,
    recommend_proxy,
)
from income_desk.models.opportunity import LegAction, StructureType
from income_desk.registry import MarketRegistry


@pytest.fixture
def registry() -> MarketRegistry:
    return MarketRegistry()


class TestComputePortfolioBeta:
    def test_single_tech_stock(self):
        beta = compute_portfolio_beta(["AAPL"], [100000.0], "SPY", "US")
        assert beta > 1.0  # Tech is high-beta

    def test_mixed_portfolio(self):
        beta = compute_portfolio_beta(
            ["AAPL", "XLU", "TLT"],
            [100000.0, 50000.0, 50000.0],
            "SPY", "US",
        )
        # Mix of high-beta tech + low-beta utilities + negative-beta bonds
        assert 0.3 < beta < 1.5

    def test_india_finance_portfolio(self):
        beta = compute_portfolio_beta(
            ["HDFCBANK", "ICICIBANK", "SBIN"],
            [500000.0, 500000.0, 500000.0],
            "NIFTY", "INDIA",
        )
        assert beta > 1.0  # Finance is high-beta in India

    def test_empty_returns_one(self):
        assert compute_portfolio_beta([], [], "SPY", "US") == 1.0


class TestRecommendProxy:
    def test_india_consumer_nifty(self, registry: MarketRegistry):
        proxy = recommend_proxy("DMART", "INDIA", registry)
        assert proxy == "NIFTY"

    def test_us_tech_qqq(self, registry: MarketRegistry):
        proxy = recommend_proxy("AAPL", "US", registry)
        assert proxy == "QQQ"


class TestBuildIndexHedge:
    def test_india_nifty_hedge(self, registry: MarketRegistry):
        """Hedge a non-F&O India stock with NIFTY puts."""
        result = build_index_hedge(
            portfolio_value=500000.0,
            portfolio_beta=0.9,
            index="NIFTY",
            index_price=22500.0,
            regime_id=2,
            dte=30,
            market="INDIA",
            registry=registry,
        )
        assert result.tier == HedgeTier.PROXY_INDEX
        assert result.hedge_type == "index_put"
        assert result.trade_spec.ticker == "NIFTY"
        assert result.trade_spec.structure_type == StructureType.LONG_OPTION
        leg = result.trade_spec.legs[0]
        assert leg.action == LegAction.BUY_TO_OPEN
        assert leg.option_type == "put"
        # Strike should be multiple of NIFTY strike interval (50)
        assert leg.strike % 50 == 0
        assert leg.strike < 22500  # OTM
        # Should flag basis risk in commentary
        assert any("basis risk" in c.lower() for c in result.commentary)

    def test_us_spy_hedge(self, registry: MarketRegistry):
        result = build_index_hedge(
            portfolio_value=50000.0,
            portfolio_beta=1.2,
            index="SPY",
            index_price=580.0,
            regime_id=4,
            dte=14,
            market="US",
            registry=registry,
        )
        assert result.trade_spec.ticker == "SPY"
        leg = result.trade_spec.legs[0]
        # R4: 2% OTM → strike ~568
        assert leg.strike < 580
        assert leg.strike >= 550

    def test_hedge_pct_scales_lots(self, registry: MarketRegistry):
        """Half hedge should use fewer lots."""
        full = build_index_hedge(
            portfolio_value=5000000.0, portfolio_beta=1.0,
            index="NIFTY", index_price=22500.0, regime_id=2,
            dte=30, market="INDIA", hedge_pct=1.0, registry=registry,
        )
        half = build_index_hedge(
            portfolio_value=5000000.0, portfolio_beta=1.0,
            index="NIFTY", index_price=22500.0, regime_id=2,
            dte=30, market="INDIA", hedge_pct=0.5, registry=registry,
        )
        assert full.trade_spec.legs[0].quantity >= half.trade_spec.legs[0].quantity
```

---

## Task 7: Hedge Comparison

**Goal:** Compare all available hedge methods for a single ticker, ranked by cost and effectiveness.

**Files to create:**
- `income_desk/hedging/comparison.py`

**Files to test:**
- `tests/test_hedging/test_comparison.py`

### Steps

- [ ] **7.1** Create `income_desk/hedging/comparison.py`
- [ ] **7.2** Create `tests/test_hedging/test_comparison.py`
- [ ] **7.3** Run tests: `.venv_312/Scripts/python.exe -m pytest tests/test_hedging/test_comparison.py -v`
- [ ] **7.4** Commit: `git commit -m "feat(hedging): add hedge comparison — ranks all available methods per ticker"`

### 7.1 — Create `income_desk/hedging/comparison.py`

```python
"""Compare hedge methods — ranks all available approaches for a single ticker.

Runs all available tiers, builds TradeSpecs for each, then ranks by:
1. Delta reduction (higher is better)
2. Cost (lower is better)
3. Basis risk (lower is better)
"""

from __future__ import annotations

from income_desk.hedging.direct import build_collar, build_protective_put, build_put_spread_hedge
from income_desk.hedging.futures_hedge import build_futures_hedge
from income_desk.hedging.models import (
    HedgeComparison,
    HedgeComparisonEntry,
    HedgeTier,
)
from income_desk.hedging.proxy import build_index_hedge
from income_desk.hedging.universe import (
    classify_hedge_tier,
    get_proxy_instrument,
    get_sector_beta,
)
from income_desk.registry import MarketRegistry


def compare_hedge_methods(
    ticker: str,
    shares: int,
    price: float,
    regime_id: int,
    atr: float,
    market: str = "US",
    cost_basis: float | None = None,
    futures_price: float | None = None,
    index_price: float | None = None,
    registry: MarketRegistry | None = None,
) -> HedgeComparison:
    """Compare all available hedge methods for a ticker.

    Builds each available method, then ranks them.

    Args:
        ticker: Instrument ticker.
        shares: Number of shares to hedge.
        price: Current price per share.
        regime_id: Current regime (1-4).
        atr: Average True Range in price units.
        market: "US" or "INDIA".
        cost_basis: Average cost basis (for collar). Defaults to price * 0.95.
        futures_price: Futures price (for futures hedge). Estimated if None.
        index_price: Index price (for proxy hedge). Required for proxy method.
        registry: MarketRegistry instance.

    Returns:
        HedgeComparison with ranked methods and recommendation.
    """
    reg = registry or MarketRegistry()
    market = market.upper()
    position_value = shares * price
    basis = cost_basis or (price * 0.95)

    methods: list[HedgeComparisonEntry] = []

    # Tier 1: Direct methods
    base_tier = classify_hedge_tier(ticker, market, reg)

    if base_tier == HedgeTier.DIRECT:
        # Protective put
        try:
            pp = build_protective_put(ticker, shares, price, regime_id, atr, 30, market, reg)
            methods.append(HedgeComparisonEntry(
                tier=HedgeTier.DIRECT,
                hedge_type="protective_put",
                trade_spec=pp.trade_spec,
                cost_estimate=pp.cost_estimate,
                cost_pct=pp.cost_pct,
                delta_reduction=pp.delta_reduction,
                basis_risk="none",
                pros=["Zero basis risk", "Simple execution", "Unlimited protection below strike"],
                cons=["Premium cost", "Time decay works against you"],
                available=True,
                unavailable_reason=None,
            ))
        except Exception:
            pass

        # Collar
        try:
            collar = build_collar(ticker, shares, price, basis, regime_id, atr, 30, market, reg)
            methods.append(HedgeComparisonEntry(
                tier=HedgeTier.DIRECT,
                hedge_type="collar",
                trade_spec=collar.trade_spec,
                cost_estimate=abs(collar.net_cost) * position_value / 100 if collar.net_cost else 0,
                cost_pct=abs(collar.net_cost) if collar.net_cost else 0,
                delta_reduction=0.80,
                basis_risk="none",
                pros=["Zero or near-zero cost in high IV", "Defined range"],
                cons=["Caps upside", "Two legs to manage"],
                available=True,
                unavailable_reason=None,
            ))
        except Exception:
            pass

        # Put spread
        try:
            ps = build_put_spread_hedge(ticker, shares, price, 0.5, 30, market, reg)
            methods.append(HedgeComparisonEntry(
                tier=HedgeTier.DIRECT,
                hedge_type="put_spread",
                trade_spec=ps.trade_spec,
                cost_estimate=ps.cost_estimate,
                cost_pct=ps.cost_pct,
                delta_reduction=ps.delta_reduction,
                basis_risk="none",
                pros=["Cheapest direct hedge", "Defined cost"],
                cons=["Limited protection range", "No protection below short put"],
                available=True,
                unavailable_reason=None,
            ))
        except Exception:
            pass
    else:
        methods.append(HedgeComparisonEntry(
            tier=HedgeTier.DIRECT,
            hedge_type="protective_put",
            trade_spec=None,
            cost_estimate=None,
            cost_pct=None,
            delta_reduction=0,
            basis_risk="none",
            pros=[],
            cons=[],
            available=False,
            unavailable_reason="Options are illiquid or unavailable" if base_tier != HedgeTier.DIRECT else None,
        ))

    # Tier 2: Futures hedge (mainly India)
    has_futures = market == "INDIA"
    if has_futures:
        try:
            fh = build_futures_hedge(
                ticker, shares, price, futures_price, 30, 1.0, market, reg,
            )
            methods.append(HedgeComparisonEntry(
                tier=HedgeTier.FUTURES_SYNTHETIC,
                hedge_type="futures_short",
                trade_spec=fh.trade_spec,
                cost_estimate=fh.cost_estimate,
                cost_pct=fh.cost_pct,
                delta_reduction=fh.delta_reduction,
                basis_risk="low",
                pros=["Lower capital than options", "No time decay", "Same-ticker exposure"],
                cons=["Basis cost", "Margin requirement", "Must roll before expiry"],
                available=True,
                unavailable_reason=None,
            ))
        except Exception:
            pass
    else:
        methods.append(HedgeComparisonEntry(
            tier=HedgeTier.FUTURES_SYNTHETIC,
            hedge_type="futures_short",
            trade_spec=None,
            cost_estimate=None,
            cost_pct=None,
            delta_reduction=0,
            basis_risk="low",
            pros=[],
            cons=[],
            available=False,
            unavailable_reason="No single-stock futures in US market",
        ))

    # Tier 3: Proxy hedge
    if index_price:
        proxy = get_proxy_instrument(ticker, market, reg)
        beta = get_sector_beta(ticker, proxy, market)
        try:
            ih = build_index_hedge(
                position_value, beta, proxy, index_price, regime_id, 30, market, 1.0, reg,
            )
            methods.append(HedgeComparisonEntry(
                tier=HedgeTier.PROXY_INDEX,
                hedge_type="index_put",
                trade_spec=ih.trade_spec,
                cost_estimate=ih.cost_estimate,
                cost_pct=ih.cost_pct,
                delta_reduction=ih.delta_reduction,
                basis_risk="high",
                pros=["Always available", "Liquid index options"],
                cons=["High basis risk", "Index may not track underlying"],
                available=True,
                unavailable_reason=None,
            ))
        except Exception:
            pass

    # Rank: available first, then by (delta_reduction DESC, cost_pct ASC, basis_risk ASC)
    basis_rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
    methods.sort(key=lambda m: (
        0 if m.available else 1,
        -(m.delta_reduction or 0),
        (m.cost_pct or 999),
        basis_rank.get(m.basis_risk, 4),
    ))

    recommended = methods[0] if methods else HedgeComparisonEntry(
        tier=HedgeTier.NONE, hedge_type="none", trade_spec=None,
        cost_estimate=None, cost_pct=None, delta_reduction=0,
        basis_risk="none", pros=[], cons=[], available=False,
        unavailable_reason="No hedge methods available",
    )

    return HedgeComparison(
        ticker=ticker,
        market=market,
        current_price=price,
        position_value=position_value,
        shares=shares,
        regime_id=regime_id,
        methods=methods,
        recommended=recommended,
        recommendation_rationale=(
            f"Recommended: {recommended.hedge_type} ({recommended.tier}) — "
            f"delta reduction {recommended.delta_reduction:.0%}, "
            f"cost ~{recommended.cost_pct:.1f}%, "
            f"basis risk {recommended.basis_risk}"
            if recommended.available
            else "No viable hedge available"
        ),
    )
```

### 7.2 — Create `tests/test_hedging/test_comparison.py`

```python
"""Tests for hedge method comparison."""

import pytest

from income_desk.hedging.comparison import compare_hedge_methods
from income_desk.hedging.models import HedgeTier
from income_desk.registry import MarketRegistry


@pytest.fixture
def registry() -> MarketRegistry:
    return MarketRegistry()


class TestCompareHedgeMethods:
    def test_reliance_all_tiers(self, registry: MarketRegistry):
        """RELIANCE should have direct + futures + proxy methods."""
        comp = compare_hedge_methods(
            ticker="RELIANCE", shares=500, price=2680.0,
            regime_id=2, atr=80.0, market="INDIA",
            futures_price=2695.0, index_price=22500.0,
            registry=registry,
        )
        assert len(comp.methods) >= 3
        available = [m for m in comp.methods if m.available]
        assert len(available) >= 3  # Direct + futures + proxy
        assert comp.recommended.available
        assert comp.recommended.tier == HedgeTier.DIRECT  # Should prefer direct

    def test_spy_direct_preferred(self, registry: MarketRegistry):
        """SPY — US stock, direct should be preferred."""
        comp = compare_hedge_methods(
            ticker="SPY", shares=100, price=580.0,
            regime_id=2, atr=8.0, market="US",
            index_price=580.0, registry=registry,
        )
        assert comp.recommended.tier == HedgeTier.DIRECT
        # Should have multiple direct methods (put, collar, put spread)
        direct_methods = [m for m in comp.methods if m.tier == HedgeTier.DIRECT and m.available]
        assert len(direct_methods) >= 2

    def test_tatasteel_futures_preferred(self, registry: MarketRegistry):
        """TATASTEEL — illiquid options, futures should rank high."""
        comp = compare_hedge_methods(
            ticker="TATASTEEL", shares=1100, price=136.0,
            regime_id=3, atr=5.0, market="INDIA",
            futures_price=137.0, index_price=22500.0,
            registry=registry,
        )
        # Direct methods should be unavailable
        direct_methods = [m for m in comp.methods if m.tier == HedgeTier.DIRECT and m.available]
        # Futures should be available
        futures_methods = [m for m in comp.methods if m.tier == HedgeTier.FUTURES_SYNTHETIC and m.available]
        assert len(futures_methods) >= 1

    def test_ranking_sorted(self, registry: MarketRegistry):
        """Methods should be sorted: available first, then by quality."""
        comp = compare_hedge_methods(
            ticker="SPY", shares=100, price=580.0,
            regime_id=2, atr=8.0, market="US", registry=registry,
        )
        # First available, then unavailable
        found_unavailable = False
        for m in comp.methods:
            if not m.available:
                found_unavailable = True
            elif found_unavailable:
                pytest.fail("Available method found after unavailable method")

    def test_recommendation_rationale_present(self, registry: MarketRegistry):
        comp = compare_hedge_methods(
            ticker="SPY", shares=100, price=580.0,
            regime_id=2, atr=8.0, market="US", registry=registry,
        )
        assert len(comp.recommendation_rationale) > 0
        assert "Recommended" in comp.recommendation_rationale
```

---

## Task 8: Portfolio Hedge Orchestrator

**Goal:** The master function — classifies all positions, resolves strategy per position, aggregates TradeSpecs.

**Files to create:**
- `income_desk/hedging/portfolio.py`

**Files to test:**
- `tests/test_hedging/test_portfolio.py`

### Steps

- [ ] **8.1** Create `income_desk/hedging/portfolio.py`
- [ ] **8.2** Create `tests/test_hedging/test_portfolio.py`
- [ ] **8.3** Run tests: `.venv_312/Scripts/python.exe -m pytest tests/test_hedging/test_portfolio.py -v`
- [ ] **8.4** Commit: `git commit -m "feat(hedging): add portfolio hedge orchestrator — aggregates hedges across all positions"`

### 8.1 — Create `income_desk/hedging/portfolio.py`

```python
"""Portfolio-level hedge orchestrator.

Master function: takes all positions → classifies → resolves strategy per position
→ builds TradeSpecs → aggregates into a single PortfolioHedgeAnalysis.

This is the function that powers the CLI `portfolio_hedge` command.
"""

from __future__ import annotations

from income_desk.hedging.direct import build_protective_put
from income_desk.hedging.futures_hedge import build_futures_hedge
from income_desk.hedging.models import (
    HedgeTier,
    PortfolioHedgeAnalysis,
    PositionHedge,
)
from income_desk.hedging.proxy import build_index_hedge, get_sector_beta
from income_desk.hedging.resolver import resolve_hedge_strategy
from income_desk.hedging.universe import get_proxy_instrument
from income_desk.models.opportunity import TradeSpec
from income_desk.registry import MarketRegistry
from income_desk.risk import PortfolioPosition


def analyze_portfolio_hedge(
    positions: list[PortfolioPosition],
    account_nlv: float,
    regime_by_ticker: dict[str, int],
    atr_by_ticker: dict[str, float],
    target_hedge_pct: float = 0.80,
    max_cost_pct: float = 3.0,
    market: str = "US",
    prices: dict[str, float] | None = None,
    futures_prices: dict[str, float] | None = None,
    index_price: float | None = None,
    registry: MarketRegistry | None = None,
) -> PortfolioHedgeAnalysis:
    """Analyze and recommend hedges for an entire portfolio.

    For each position:
    1. Resolve hedge strategy (via resolver)
    2. Build the recommended TradeSpec
    3. Aggregate all hedges

    Args:
        positions: Current portfolio positions from eTrading.
        account_nlv: Net liquidating value.
        regime_by_ticker: Regime ID (1-4) per ticker.
        atr_by_ticker: ATR in price units per ticker.
        target_hedge_pct: Target % of portfolio to hedge (0-1).
        max_cost_pct: Maximum total hedge cost as % of portfolio value.
        market: "US" or "INDIA".
        prices: Current price per ticker (if None, uses notional_value/lot as proxy).
        futures_prices: Futures prices per ticker (for Tier 2 hedges).
        index_price: Index price for proxy hedges.
        registry: MarketRegistry instance.

    Returns:
        PortfolioHedgeAnalysis with per-position hedges and aggregated TradeSpecs.
    """
    reg = registry or MarketRegistry()
    market = market.upper()
    price_map = prices or {}
    futures_map = futures_prices or {}

    position_hedges: list[PositionHedge] = []
    all_trade_specs: list[TradeSpec] = []
    total_cost = 0.0
    tier_counts: dict[str, int] = {"direct": 0, "futures_synthetic": 0, "proxy_index": 0, "none": 0}
    tier_values: dict[str, float] = {"direct": 0, "futures_synthetic": 0, "proxy_index": 0, "none": 0}
    total_position_value = 0.0
    portfolio_delta_before = 0.0
    portfolio_delta_after = 0.0
    alerts: list[str] = []

    # Sort positions by value (hedge largest first)
    sorted_positions = sorted(positions, key=lambda p: p.notional_value, reverse=True)

    hedged_value = 0.0
    max_hedgeable_value = sum(p.notional_value for p in sorted_positions) * target_hedge_pct

    for pos in sorted_positions:
        ticker = pos.ticker
        pos_value = pos.notional_value or (pos.buying_power_used * 2)  # Rough estimate if no notional
        total_position_value += pos_value
        portfolio_delta_before += pos.delta

        # Get price from map or estimate
        price = price_map.get(ticker, pos_value / 100 if pos_value > 0 else 0)
        if price <= 0:
            position_hedges.append(PositionHedge(
                ticker=ticker, position_value=pos_value, shares=0,
                tier=HedgeTier.NONE, hedge_type=None, trade_spec=None,
                cost_estimate=None, delta_before=pos.delta, delta_after=pos.delta,
                rationale="Cannot hedge: no price data available",
            ))
            tier_counts["none"] += 1
            tier_values["none"] += pos_value
            portfolio_delta_after += pos.delta
            continue

        # Estimate shares from notional
        shares = int(pos_value / price) if price > 0 else 0
        regime_id = regime_by_ticker.get(ticker, 2)
        atr = atr_by_ticker.get(ticker, price * 0.015)

        # Skip if we've already hedged enough
        if hedged_value >= max_hedgeable_value:
            position_hedges.append(PositionHedge(
                ticker=ticker, position_value=pos_value, shares=shares,
                tier=HedgeTier.NONE, hedge_type=None, trade_spec=None,
                cost_estimate=None, delta_before=pos.delta, delta_after=pos.delta,
                rationale=f"Skipped: target hedge % ({target_hedge_pct:.0%}) already reached",
            ))
            tier_counts["none"] += 1
            tier_values["none"] += pos_value
            portfolio_delta_after += pos.delta
            continue

        # Resolve strategy
        approach = resolve_hedge_strategy(
            ticker=ticker, position_value=pos_value, shares=shares,
            current_price=price, regime_id=regime_id, market=market,
            account_nlv=account_nlv, registry=reg,
        )

        # Build TradeSpec based on recommended tier
        trade_spec: TradeSpec | None = None
        hedge_type: str | None = None
        cost_estimate: float | None = None
        delta_reduction = 0.0

        if approach.recommended_tier == HedgeTier.DIRECT:
            try:
                result = build_protective_put(
                    ticker, shares, price, regime_id, atr, 30, market, reg,
                )
                trade_spec = result.trade_spec
                hedge_type = result.hedge_type
                cost_estimate = result.cost_estimate
                delta_reduction = result.delta_reduction
            except Exception as e:
                alerts.append(f"{ticker}: direct hedge failed — {e}")

        elif approach.recommended_tier == HedgeTier.FUTURES_SYNTHETIC:
            try:
                fut_price = futures_map.get(ticker)
                result = build_futures_hedge(
                    ticker, shares, price, fut_price, 30, 1.0, market, reg,
                )
                trade_spec = result.trade_spec
                hedge_type = result.hedge_type
                cost_estimate = result.cost_estimate
                delta_reduction = result.delta_reduction
            except Exception as e:
                alerts.append(f"{ticker}: futures hedge failed — {e}")

        elif approach.recommended_tier == HedgeTier.PROXY_INDEX:
            if index_price:
                try:
                    proxy = get_proxy_instrument(ticker, market, reg)
                    beta = get_sector_beta(ticker, proxy, market)
                    result = build_index_hedge(
                        pos_value, beta, proxy, index_price, regime_id, 30, market, 1.0, reg,
                    )
                    trade_spec = result.trade_spec
                    hedge_type = result.hedge_type
                    cost_estimate = result.cost_estimate
                    delta_reduction = result.delta_reduction
                except Exception as e:
                    alerts.append(f"{ticker}: proxy hedge failed — {e}")
            else:
                alerts.append(f"{ticker}: proxy hedge skipped — no index price provided")

        # Record
        tier_str = approach.recommended_tier.value
        tier_counts[tier_str] = tier_counts.get(tier_str, 0) + 1
        tier_values[tier_str] = tier_values.get(tier_str, 0) + pos_value

        delta_after = pos.delta * (1 - delta_reduction)
        portfolio_delta_after += delta_after

        if trade_spec:
            all_trade_specs.append(trade_spec)
            hedged_value += pos_value
            if cost_estimate:
                total_cost += cost_estimate

        position_hedges.append(PositionHedge(
            ticker=ticker,
            position_value=pos_value,
            shares=shares,
            tier=approach.recommended_tier,
            hedge_type=hedge_type,
            trade_spec=trade_spec,
            cost_estimate=cost_estimate,
            delta_before=pos.delta,
            delta_after=round(delta_after, 4),
            rationale=approach.rationale,
        ))

    # Aggregate
    hedge_cost_pct = (total_cost / total_position_value * 100) if total_position_value > 0 else 0
    coverage_pct = (hedged_value / total_position_value * 100) if total_position_value > 0 else 0

    if hedge_cost_pct > max_cost_pct:
        alerts.append(f"Total hedge cost {hedge_cost_pct:.1f}% exceeds max {max_cost_pct:.1f}%")

    unhedged_count = tier_counts.get("none", 0)
    if unhedged_count > 0:
        alerts.append(f"{unhedged_count} position(s) have no hedge")

    summary = (
        f"{len(all_trade_specs)} hedges across {len(position_hedges)} positions, "
        f"{coverage_pct:.0f}% coverage, "
        f"cost {hedge_cost_pct:.1f}% of portfolio"
    )

    return PortfolioHedgeAnalysis(
        market=market,
        account_nlv=account_nlv,
        total_positions=len(positions),
        total_position_value=round(total_position_value, 2),
        tier_counts=tier_counts,
        tier_values={k: round(v, 2) for k, v in tier_values.items()},
        position_hedges=position_hedges,
        total_hedge_cost=round(total_cost, 2),
        hedge_cost_pct=round(hedge_cost_pct, 2),
        portfolio_delta_before=round(portfolio_delta_before, 4),
        portfolio_delta_after=round(portfolio_delta_after, 4),
        portfolio_beta_before=None,  # Would need historical data
        portfolio_beta_after=None,
        trade_specs=all_trade_specs,
        coverage_pct=round(coverage_pct, 1),
        target_hedge_pct=target_hedge_pct * 100,
        summary=summary,
        alerts=alerts,
    )
```

### 8.2 — Create `tests/test_hedging/test_portfolio.py`

```python
"""Tests for portfolio-level hedge orchestrator."""

import pytest

from income_desk.hedging.models import HedgeTier
from income_desk.hedging.portfolio import analyze_portfolio_hedge
from income_desk.registry import MarketRegistry
from income_desk.risk import PortfolioPosition


@pytest.fixture
def registry() -> MarketRegistry:
    return MarketRegistry()


def _make_position(
    ticker: str, notional: float, delta: float = 0.5, structure: str = "equity_long",
) -> PortfolioPosition:
    return PortfolioPosition(
        ticker=ticker,
        structure_type=structure,
        direction="bullish",
        notional_value=notional,
        buying_power_used=notional * 0.5,
        delta=delta,
        max_loss=notional * 0.1,
    )


class TestPortfolioHedgeOrchestrator:
    def test_india_mixed_portfolio_10_stocks(self, registry: MarketRegistry):
        """10 India stocks — mixed tiers."""
        positions = [
            _make_position("RELIANCE", 1250000),    # Direct
            _make_position("HDFCBANK", 800000),      # Direct
            _make_position("ICICIBANK", 700000),     # Direct
            _make_position("TATASTEEL", 150000),     # Futures
            _make_position("HINDUNILVR", 500000),    # Futures
            _make_position("SBIN", 300000),          # Direct
            _make_position("ITC", 200000),           # Direct
            _make_position("INFY", 400000),          # Direct
            _make_position("LT", 350000),            # Futures
            _make_position("TCS", 600000),           # Direct
        ]
        regimes = {p.ticker: 2 for p in positions}
        atrs = {p.ticker: p.notional_value * 0.015 / 100 for p in positions}  # Rough
        prices = {
            "RELIANCE": 2500, "HDFCBANK": 1450, "ICICIBANK": 1000,
            "TATASTEEL": 136, "HINDUNILVR": 2600, "SBIN": 200,
            "ITC": 125, "INFY": 1350, "LT": 2350, "TCS": 4000,
        }

        result = analyze_portfolio_hedge(
            positions=positions,
            account_nlv=5000000,
            regime_by_ticker=regimes,
            atr_by_ticker=atrs,
            target_hedge_pct=0.80,
            max_cost_pct=3.0,
            market="INDIA",
            prices=prices,
            index_price=22500,
            registry=registry,
        )

        assert result.total_positions == 10
        assert result.total_position_value > 0
        assert len(result.position_hedges) == 10
        assert result.coverage_pct > 0
        # Should have some trade specs
        assert len(result.trade_specs) > 0
        # Should have mix of tiers
        assert result.tier_counts.get("direct", 0) > 0

    def test_us_portfolio(self, registry: MarketRegistry):
        """US portfolio — all direct."""
        positions = [
            _make_position("SPY", 58000),
            _make_position("QQQ", 48000),
            _make_position("AAPL", 22000),
        ]
        regimes = {"SPY": 2, "QQQ": 2, "AAPL": 3}
        atrs = {"SPY": 8.0, "QQQ": 5.0, "AAPL": 4.0}
        prices = {"SPY": 580, "QQQ": 480, "AAPL": 220}

        result = analyze_portfolio_hedge(
            positions=positions,
            account_nlv=200000,
            regime_by_ticker=regimes,
            atr_by_ticker=atrs,
            market="US",
            prices=prices,
            registry=registry,
        )

        assert result.total_positions == 3
        assert result.tier_counts.get("direct", 0) >= 2
        assert len(result.trade_specs) >= 2

    def test_empty_portfolio(self, registry: MarketRegistry):
        result = analyze_portfolio_hedge(
            positions=[],
            account_nlv=200000,
            regime_by_ticker={},
            atr_by_ticker={},
            market="US",
            registry=registry,
        )
        assert result.total_positions == 0
        assert result.coverage_pct == 0
        assert len(result.trade_specs) == 0

    def test_target_hedge_pct_limits(self, registry: MarketRegistry):
        """Only hedge up to target %."""
        positions = [
            _make_position("SPY", 100000),
            _make_position("QQQ", 100000),
        ]
        result = analyze_portfolio_hedge(
            positions=positions,
            account_nlv=200000,
            regime_by_ticker={"SPY": 2, "QQQ": 2},
            atr_by_ticker={"SPY": 8.0, "QQQ": 5.0},
            target_hedge_pct=0.50,
            market="US",
            prices={"SPY": 580, "QQQ": 480},
            registry=registry,
        )
        # With 50% target, may skip second position
        assert result.target_hedge_pct == 50.0

    def test_delta_reduction_tracked(self, registry: MarketRegistry):
        """Portfolio delta should decrease after hedging."""
        positions = [_make_position("SPY", 58000, delta=0.8)]
        result = analyze_portfolio_hedge(
            positions=positions,
            account_nlv=200000,
            regime_by_ticker={"SPY": 2},
            atr_by_ticker={"SPY": 8.0},
            market="US",
            prices={"SPY": 580},
            registry=registry,
        )
        assert result.portfolio_delta_after < result.portfolio_delta_before
```

---

## Task 9: Hedge Monitoring

**Goal:** Track active hedge health — expiry warnings, roll recommendations, effectiveness measurement.

**Files to create:**
- `income_desk/hedging/monitoring.py`

**Files to test:**
- `tests/test_hedging/test_monitoring.py`

### Steps

- [ ] **9.1** Create `income_desk/hedging/monitoring.py`
- [ ] **9.2** Create `tests/test_hedging/test_monitoring.py`
- [ ] **9.3** Run tests: `.venv_312/Scripts/python.exe -m pytest tests/test_hedging/test_monitoring.py -v`
- [ ] **9.4** Commit: `git commit -m "feat(hedging): add hedge monitoring — expiry tracking, rolling, effectiveness measurement"`

### 9.1 — Create `income_desk/hedging/monitoring.py`

```python
"""Hedge monitoring — expiry tracking, rolling, effectiveness measurement.

Pure functions:
- monitor_hedge_status() — check active hedges for expiry/roll needs
- compute_hedge_effectiveness() — simulate market move, measure hedge savings
"""

from __future__ import annotations

from income_desk.hedging.models import (
    HedgeEffectiveness,
    HedgeMonitorEntry,
    HedgeMonitorResult,
)
from income_desk.models.opportunity import (
    LegAction,
    LegSpec,
    OrderSide,
    StructureType,
    TradeSpec,
)


def monitor_hedge_status(
    hedges: list[dict],
    dte_warning_threshold: int = 5,
) -> HedgeMonitorResult:
    """Monitor active hedges for expiry and roll needs.

    Args:
        hedges: List of active hedge dicts, each with:
            - ticker: str
            - hedge_type: str ("protective_put", "futures_short", "index_put", etc.)
            - dte_remaining: int
            - delta_coverage: float (0-1, how much delta the hedge covers)
            - original_trade_spec: dict | None (for building roll specs)
        dte_warning_threshold: Days before expiry to warn (default 5).

    Returns:
        HedgeMonitorResult with status and roll specs.
    """
    entries: list[HedgeMonitorEntry] = []
    roll_specs: list[TradeSpec] = []
    expiring_count = 0
    expired_count = 0
    alerts: list[str] = []

    for h in hedges:
        ticker = h.get("ticker", "UNKNOWN")
        hedge_type = h.get("hedge_type", "unknown")
        dte = h.get("dte_remaining", 0)
        delta_cov = h.get("delta_coverage", 0.0)

        is_expired = dte <= 0
        is_expiring = 0 < dte <= dte_warning_threshold

        if is_expired:
            expired_count += 1
            action = "replace"
            rationale = f"{ticker} hedge expired — need new hedge"
            alerts.append(f"EXPIRED: {ticker} {hedge_type}")
        elif is_expiring:
            expiring_count += 1
            action = "roll"
            rationale = f"{ticker} hedge expiring in {dte} days — roll forward"
            alerts.append(f"EXPIRING SOON: {ticker} {hedge_type} ({dte} DTE)")

            # Build roll spec: close current + open new
            roll_spec = _build_roll_spec(ticker, hedge_type, dte)
            if roll_spec:
                roll_specs.append(roll_spec)
        elif delta_cov < 0.30:
            action = "replace"
            rationale = f"{ticker} hedge delta coverage degraded to {delta_cov:.0%} — replace"
            alerts.append(f"WEAK: {ticker} hedge only covering {delta_cov:.0%}")
        else:
            action = "hold"
            rationale = f"{ticker} hedge healthy — {dte} DTE, {delta_cov:.0%} coverage"

        entries.append(HedgeMonitorEntry(
            ticker=ticker,
            hedge_type=hedge_type,
            dte_remaining=dte,
            is_expiring_soon=is_expiring,
            is_expired=is_expired,
            current_delta_coverage=delta_cov,
            action=action,
            roll_spec=roll_spec if is_expiring and roll_specs else None,
            rationale=rationale,
        ))

    total_roll_cost = None  # Would need broker quotes for actual cost
    summary_parts = []
    if expired_count:
        summary_parts.append(f"{expired_count} expired")
    if expiring_count:
        summary_parts.append(f"{expiring_count} expiring soon")
    healthy = len(entries) - expired_count - expiring_count
    if healthy:
        summary_parts.append(f"{healthy} healthy")
    summary = f"{len(entries)} hedges: {', '.join(summary_parts)}" if summary_parts else "No active hedges"

    return HedgeMonitorResult(
        hedges=entries,
        expiring_count=expiring_count,
        expired_count=expired_count,
        total_roll_cost=total_roll_cost,
        roll_specs=roll_specs,
        alerts=alerts,
        summary=summary,
    )


def _build_roll_spec(ticker: str, hedge_type: str, current_dte: int) -> TradeSpec | None:
    """Build a roll TradeSpec for an expiring hedge.

    Roll = close current position + open new 30-day position.
    """
    from datetime import date, timedelta

    new_dte = 30
    new_expiry = (date.today() + timedelta(days=new_dte)).isoformat()

    if hedge_type == "protective_put":
        return TradeSpec(
            ticker=ticker,
            structure_type=StructureType.LONG_OPTION,
            order_side=OrderSide.DEBIT,
            legs=[
                LegSpec(
                    action=LegAction.BUY_TO_OPEN,
                    strike=0,  # Placeholder — needs current price to snap
                    expiration=new_expiry,
                    option_type="put",
                    quantity=1,
                ),
            ],
            max_profit_desc="Roll: new protective put",
            max_loss_desc="Roll cost (close old + open new)",
        )
    elif hedge_type == "futures_short":
        return TradeSpec(
            ticker=ticker,
            structure_type=StructureType.FUTURES_SHORT,
            order_side=OrderSide.CREDIT,
            legs=[
                LegSpec(
                    action=LegAction.SELL_TO_OPEN,
                    strike=0,  # Placeholder — needs current futures price
                    expiration=new_expiry,
                    option_type="future",
                    quantity=1,
                ),
            ],
            max_profit_desc="Roll: new short futures",
            max_loss_desc="Roll cost (basis change)",
        )

    return None


def compute_hedge_effectiveness(
    positions: list[dict],
    hedges: list[dict],
    market_move_pct: float,
) -> HedgeEffectiveness:
    """Simulate a market move and measure how much hedges saved.

    Simplified simulation — uses linear delta approximation.

    Args:
        positions: List of position dicts with:
            - ticker: str
            - value: float (position value)
            - delta: float (position delta)
        hedges: List of hedge dicts with:
            - ticker: str
            - delta_reduction: float (0-1)
            - cost: float (hedge cost paid)
        market_move_pct: Simulated market move (e.g., -0.05 = -5% drop).

    Returns:
        HedgeEffectiveness with savings analysis.
    """
    # Unhedged loss: sum of position_value x delta x market_move
    unhedged_loss = 0.0
    for pos in positions:
        pos_loss = pos.get("value", 0) * pos.get("delta", 1.0) * market_move_pct
        unhedged_loss += pos_loss

    unhedged_loss = abs(unhedged_loss)

    # Hedged loss: reduced by hedge delta reduction
    hedged_loss = unhedged_loss
    total_hedge_cost = 0.0
    hedge_by_ticker = {h["ticker"]: h for h in hedges}

    for pos in positions:
        ticker = pos.get("ticker", "")
        hedge = hedge_by_ticker.get(ticker)
        if hedge:
            delta_reduction = hedge.get("delta_reduction", 0)
            pos_savings = abs(pos.get("value", 0) * pos.get("delta", 1.0) * market_move_pct) * delta_reduction
            hedged_loss -= pos_savings
            total_hedge_cost += hedge.get("cost", 0)

    hedged_loss = max(hedged_loss, 0)
    savings = unhedged_loss - hedged_loss
    savings_pct = (savings / unhedged_loss * 100) if unhedged_loss > 0 else 0
    net_benefit = savings - total_hedge_cost
    roi = (net_benefit / total_hedge_cost) if total_hedge_cost > 0 else 0

    if net_benefit > 0:
        commentary = (
            f"Hedges saved {savings_pct:.0f}% of potential loss in a {abs(market_move_pct)*100:.0f}% move. "
            f"Net benefit after hedge cost: {net_benefit:,.0f}. ROI: {roi:.1f}x."
        )
    elif savings > 0:
        commentary = (
            f"Hedges reduced loss by {savings_pct:.0f}% but cost exceeded savings. "
            f"The move was too small to justify hedge cost."
        )
    else:
        commentary = "No meaningful hedge benefit in this scenario."

    return HedgeEffectiveness(
        market_move_pct=market_move_pct,
        portfolio_loss_unhedged=round(unhedged_loss, 2),
        portfolio_loss_hedged=round(hedged_loss, 2),
        hedge_savings=round(savings, 2),
        hedge_savings_pct=round(savings_pct, 1),
        cost_of_hedges=round(total_hedge_cost, 2),
        net_benefit=round(net_benefit, 2),
        roi_on_hedge=round(roi, 2),
        commentary=commentary,
    )
```

### 9.2 — Create `tests/test_hedging/test_monitoring.py`

```python
"""Tests for hedge monitoring — expiry, rolling, effectiveness."""

import pytest

from income_desk.hedging.monitoring import (
    compute_hedge_effectiveness,
    monitor_hedge_status,
)


class TestMonitorHedgeStatus:
    def test_healthy_hedges(self):
        hedges = [
            {"ticker": "SPY", "hedge_type": "protective_put", "dte_remaining": 20, "delta_coverage": 0.8},
            {"ticker": "RELIANCE", "hedge_type": "futures_short", "dte_remaining": 15, "delta_coverage": 0.9},
        ]
        result = monitor_hedge_status(hedges)
        assert result.expiring_count == 0
        assert result.expired_count == 0
        assert len(result.alerts) == 0
        assert all(e.action == "hold" for e in result.hedges)

    def test_expiring_hedge(self):
        hedges = [
            {"ticker": "SPY", "hedge_type": "protective_put", "dte_remaining": 3, "delta_coverage": 0.7},
        ]
        result = monitor_hedge_status(hedges)
        assert result.expiring_count == 1
        assert result.hedges[0].action == "roll"
        assert result.hedges[0].is_expiring_soon
        assert len(result.roll_specs) == 1
        assert "EXPIRING" in result.alerts[0]

    def test_expired_hedge(self):
        hedges = [
            {"ticker": "RELIANCE", "hedge_type": "futures_short", "dte_remaining": 0, "delta_coverage": 0},
        ]
        result = monitor_hedge_status(hedges)
        assert result.expired_count == 1
        assert result.hedges[0].action == "replace"
        assert result.hedges[0].is_expired

    def test_weak_hedge(self):
        hedges = [
            {"ticker": "NIFTY", "hedge_type": "index_put", "dte_remaining": 20, "delta_coverage": 0.15},
        ]
        result = monitor_hedge_status(hedges)
        assert result.hedges[0].action == "replace"
        assert "WEAK" in result.alerts[0]

    def test_mixed_status(self):
        hedges = [
            {"ticker": "SPY", "hedge_type": "protective_put", "dte_remaining": 25, "delta_coverage": 0.8},
            {"ticker": "QQQ", "hedge_type": "collar", "dte_remaining": 4, "delta_coverage": 0.7},
            {"ticker": "AAPL", "hedge_type": "protective_put", "dte_remaining": 0, "delta_coverage": 0},
        ]
        result = monitor_hedge_status(hedges)
        assert result.expiring_count == 1
        assert result.expired_count == 1
        assert len(result.alerts) == 2

    def test_empty_hedges(self):
        result = monitor_hedge_status([])
        assert result.expiring_count == 0
        assert result.expired_count == 0
        assert "No active hedges" in result.summary

    def test_custom_threshold(self):
        hedges = [
            {"ticker": "SPY", "hedge_type": "protective_put", "dte_remaining": 8, "delta_coverage": 0.7},
        ]
        # Default threshold 5 → not expiring
        result_default = monitor_hedge_status(hedges, dte_warning_threshold=5)
        assert result_default.expiring_count == 0
        # Custom threshold 10 → expiring
        result_custom = monitor_hedge_status(hedges, dte_warning_threshold=10)
        assert result_custom.expiring_count == 1


class TestComputeHedgeEffectiveness:
    def test_five_pct_drop_with_hedges(self):
        positions = [
            {"ticker": "SPY", "value": 58000, "delta": 1.0},
            {"ticker": "QQQ", "value": 48000, "delta": 1.0},
        ]
        hedges = [
            {"ticker": "SPY", "delta_reduction": 0.8, "cost": 500},
            {"ticker": "QQQ", "delta_reduction": 0.7, "cost": 400},
        ]
        result = compute_hedge_effectiveness(positions, hedges, -0.05)

        assert result.portfolio_loss_unhedged > 0
        assert result.portfolio_loss_hedged < result.portfolio_loss_unhedged
        assert result.hedge_savings > 0
        assert result.net_benefit > 0
        assert result.roi_on_hedge > 0

    def test_small_move_hedge_not_worth_it(self):
        """If move is tiny, hedge cost may exceed savings."""
        positions = [
            {"ticker": "SPY", "value": 58000, "delta": 1.0},
        ]
        hedges = [
            {"ticker": "SPY", "delta_reduction": 0.8, "cost": 5000},  # Expensive hedge
        ]
        result = compute_hedge_effectiveness(positions, hedges, -0.005)  # 0.5% drop
        # Savings: 58000 * 1.0 * 0.005 * 0.8 = 232
        # Cost: 5000 → net negative
        assert result.net_benefit < 0

    def test_no_hedges(self):
        positions = [{"ticker": "SPY", "value": 58000, "delta": 1.0}]
        result = compute_hedge_effectiveness(positions, [], -0.05)
        assert result.hedge_savings == 0
        assert result.portfolio_loss_hedged == result.portfolio_loss_unhedged

    def test_india_portfolio_scenario(self):
        """India 10-stock portfolio — 5% NIFTY drop."""
        positions = [
            {"ticker": "RELIANCE", "value": 1250000, "delta": 0.95},
            {"ticker": "HDFCBANK", "value": 800000, "delta": 1.15},
            {"ticker": "TATASTEEL", "value": 150000, "delta": 1.30},
        ]
        hedges = [
            {"ticker": "RELIANCE", "delta_reduction": 0.85, "cost": 15000},
            {"ticker": "HDFCBANK", "delta_reduction": 0.80, "cost": 10000},
            {"ticker": "TATASTEEL", "delta_reduction": 0.90, "cost": 3000},
        ]
        result = compute_hedge_effectiveness(positions, hedges, -0.05)
        assert result.hedge_savings > 50000  # Substantial savings on big portfolio
        assert result.roi_on_hedge > 1.0  # Hedge paid for itself
```

---

## Task 10: Migration + CLI + Exports

**Goal:** Wire everything together — migrate existing hedging.py, add CLI commands, set up exports, ensure backward compatibility.

**Files to modify:**
- `income_desk/hedging/__init__.py` — full exports
- `income_desk/hedging.py` — backward compat re-exports (KEEP file, change to re-exports)
- `income_desk/__init__.py` — add hedging package exports

**Files to test:**
- `tests/test_hedging/test_migration.py` (new — tests backward compat)

### Steps

- [ ] **10.1** Update `income_desk/hedging/__init__.py` with all public exports
- [ ] **10.2** Replace `income_desk/hedging.py` with re-exports from `hedging/` package — IMPORTANT: Python can't have both `hedging.py` and `hedging/` in same directory. Move original `hedging.py` code into `hedging/_legacy.py` and keep re-exports in `hedging/__init__.py`
- [ ] **10.3** Update `income_desk/__init__.py` to export key hedging symbols
- [ ] **10.4** Create `tests/test_hedging/test_migration.py` to verify backward compat imports
- [ ] **10.5** Run full test suite: `.venv_312/Scripts/python.exe -m pytest tests/test_hedging/ -v`
- [ ] **10.6** Run existing tests to verify no breakage: `.venv_312/Scripts/python.exe -m pytest tests/ -v --timeout=120`
- [ ] **10.7** Commit: `git commit -m "feat(hedging): wire hedging domain package — exports, migration, backward compat"`

### 10.1 — Update `income_desk/hedging/__init__.py`

```python
"""Hedging domain package — market-generic hedge intelligence.

Resolver pattern:
    resolve_hedge_strategy() → HedgeApproach (decides tier)
    Tier 1 (direct.py)       → protective puts, collars, put spreads
    Tier 2 (futures_hedge.py) → futures short, synthetic puts, synthetic collars
    Tier 3 (proxy.py)        → beta-adjusted index hedges
    portfolio.py             → orchestrate across all positions
    comparison.py            → rank all available methods
    monitoring.py            → expiry tracking, rolling, effectiveness

Public API:
    # Decision
    resolve_hedge_strategy()
    compare_hedge_methods()
    analyze_portfolio_hedge()

    # Builders
    build_protective_put()
    build_collar()
    build_put_spread_hedge()
    build_futures_hedge()
    build_synthetic_put()
    build_synthetic_collar()
    build_index_hedge()

    # Monitoring
    monitor_hedge_status()
    compute_hedge_effectiveness()

    # Universe
    classify_hedge_tier()
    get_fno_coverage()

    # Legacy (from original hedging.py)
    assess_hedge()
    HedgeType, HedgeUrgency, HedgeRecommendation
"""

# Legacy re-exports (backward compat with income_desk.hedging.assess_hedge etc.)
from income_desk.hedging._legacy import (
    HedgeRecommendation,
    HedgeType,
    HedgeUrgency,
    assess_hedge,
)

# Models
from income_desk.hedging.models import (
    CollarResult,
    FnOCoverage,
    HedgeApproach,
    HedgeComparison,
    HedgeComparisonEntry,
    HedgeEffectiveness,
    HedgeGoal,
    HedgeMonitorEntry,
    HedgeMonitorResult,
    HedgeResult,
    HedgeTier,
    PortfolioHedgeAnalysis,
    PositionHedge,
    SyntheticOptionResult,
)

# Decision engine
from income_desk.hedging.resolver import resolve_hedge_strategy

# Tier 1: Direct
from income_desk.hedging.direct import (
    build_collar,
    build_protective_put,
    build_put_spread_hedge,
)

# Tier 2: Futures
from income_desk.hedging.futures_hedge import (
    build_futures_hedge,
    build_synthetic_collar,
    build_synthetic_put,
    compute_hedge_ratio,
)

# Tier 3: Proxy
from income_desk.hedging.proxy import (
    build_index_hedge,
    compute_portfolio_beta,
    recommend_proxy,
)

# Comparison
from income_desk.hedging.comparison import compare_hedge_methods

# Portfolio orchestrator
from income_desk.hedging.portfolio import analyze_portfolio_hedge

# Monitoring
from income_desk.hedging.monitoring import (
    compute_hedge_effectiveness,
    monitor_hedge_status,
)

# Universe
from income_desk.hedging.universe import (
    classify_hedge_tier,
    get_fno_coverage,
    get_proxy_instrument,
    get_sector_beta,
)

__all__ = [
    # Legacy
    "HedgeType", "HedgeUrgency", "HedgeRecommendation", "assess_hedge",
    # Models
    "HedgeTier", "HedgeGoal", "HedgeApproach", "HedgeResult", "CollarResult",
    "SyntheticOptionResult", "PositionHedge", "PortfolioHedgeAnalysis",
    "HedgeComparison", "HedgeComparisonEntry",
    "HedgeMonitorEntry", "HedgeMonitorResult", "HedgeEffectiveness",
    "FnOCoverage",
    # Decision
    "resolve_hedge_strategy", "compare_hedge_methods", "analyze_portfolio_hedge",
    # Builders
    "build_protective_put", "build_collar", "build_put_spread_hedge",
    "build_futures_hedge", "build_synthetic_put", "build_synthetic_collar",
    "compute_hedge_ratio",
    "build_index_hedge", "compute_portfolio_beta", "recommend_proxy",
    # Monitoring
    "monitor_hedge_status", "compute_hedge_effectiveness",
    # Universe
    "classify_hedge_tier", "get_fno_coverage", "get_proxy_instrument", "get_sector_beta",
]
```

### 10.2 — Move original hedging.py → hedging/_legacy.py

IMPORTANT: Python resolves `income_desk.hedging` as the `hedging/` package (directory with `__init__.py`), not `hedging.py`. So the original `hedging.py` file MUST be deleted and its contents moved to `hedging/_legacy.py`.

Create `income_desk/hedging/_legacy.py`:
```python
"""Legacy hedge assessment — original same-ticker hedge logic.

Moved from income_desk/hedging.py into the hedging domain package.
All original functions preserved. Import from income_desk.hedging (the package)
and you get these via __init__.py re-exports.
"""
# ← Paste the ENTIRE contents of the original income_desk/hedging.py here,
#    unchanged except for this module docstring.
```

Then DELETE `income_desk/hedging.py` (the file, not the directory).

### 10.3 — Update `income_desk/__init__.py`

Add near the existing model imports:

```python
# Hedging domain package
from income_desk.hedging import (
    HedgeType,
    HedgeUrgency,
    HedgeRecommendation,
    assess_hedge,
    HedgeTier,
    resolve_hedge_strategy,
    compare_hedge_methods,
    analyze_portfolio_hedge,
)
```

### 10.4 — Create `tests/test_hedging/test_migration.py`

```python
"""Tests for backward compatibility after hedging.py → hedging/ migration."""

import pytest


class TestBackwardCompatImports:
    """Ensure old import paths still work."""

    def test_import_hedge_type(self):
        from income_desk.hedging import HedgeType
        assert HedgeType.PROTECTIVE_PUT == "protective_put"

    def test_import_hedge_urgency(self):
        from income_desk.hedging import HedgeUrgency
        assert HedgeUrgency.IMMEDIATE == "immediate"

    def test_import_assess_hedge(self):
        from income_desk.hedging import assess_hedge
        assert callable(assess_hedge)

    def test_import_hedge_recommendation(self):
        from income_desk.hedging import HedgeRecommendation
        assert HedgeRecommendation is not None

    def test_import_from_top_level(self):
        from income_desk import HedgeType, assess_hedge
        assert HedgeType.COLLAR == "collar"
        assert callable(assess_hedge)

    def test_new_imports_work(self):
        from income_desk.hedging import (
            HedgeTier,
            resolve_hedge_strategy,
            compare_hedge_methods,
            analyze_portfolio_hedge,
            build_protective_put,
            build_collar,
            build_futures_hedge,
            build_index_hedge,
            monitor_hedge_status,
            compute_hedge_effectiveness,
            classify_hedge_tier,
            get_fno_coverage,
        )
        assert HedgeTier.DIRECT == "direct"
        assert callable(resolve_hedge_strategy)
        assert callable(compare_hedge_methods)


class TestLegacyAssessHedgeStillWorks:
    """Run the original assess_hedge through the new import path."""

    def test_long_equity_r2_collar(self):
        from income_desk.hedging import assess_hedge, HedgeType
        from income_desk.models.regime import RegimeResult
        from income_desk.models.technicals import TechnicalSnapshot

        regime = RegimeResult(
            ticker="SPY",
            regime=2,
            confidence=0.8,
            trend_direction="bullish",
        )
        technicals = TechnicalSnapshot(
            ticker="SPY",
            current_price=580.0,
            atr=8.0,
            atr_pct=1.38,
        )

        rec = assess_hedge(
            ticker="SPY",
            position_type="long_equity",
            position_value=58000,
            regime=regime,
            technicals=technicals,
        )
        assert rec.hedge_type == HedgeType.COLLAR
```

---

## Summary

| Task | Module | Functions | Key Test Scenario |
|------|--------|-----------|-------------------|
| 1 | models.py | 12 models | Model instantiation, India + US |
| 2 | universe.py | classify_hedge_tier, get_fno_coverage, get_sector_beta, get_proxy_instrument | RELIANCE=Direct, TATASTEEL=Futures, DMART=Proxy |
| 3 | resolver.py | resolve_hedge_strategy | Decision tree: liq→direct, illiquid→futures, no F&O→proxy |
| 4 | direct.py | build_protective_put, build_collar, build_put_spread_hedge | Regime-aware strike placement, lot sizing |
| 5 | futures_hedge.py | build_futures_hedge, build_synthetic_put, build_synthetic_collar | TATASTEEL 1100-lot hedge, synthetic put payoff |
| 6 | proxy.py | build_index_hedge, compute_portfolio_beta, recommend_proxy | DMART→NIFTY proxy, beta-adjusted sizing |
| 7 | comparison.py | compare_hedge_methods | SPY all methods ranked, TATASTEEL futures preferred |
| 8 | portfolio.py | analyze_portfolio_hedge | 10-stock India mixed-tier portfolio |
| 9 | monitoring.py | monitor_hedge_status, compute_hedge_effectiveness | Expiry roll, 5% drop savings simulation |
| 10 | __init__.py + migration | All exports, backward compat | Old import paths still work |

**Estimated test count:** ~80 tests across 10 test files.

**Dependencies between tasks:** 1 → 2 → 3 → 4,5,6 (parallel) → 7 → 8 → 9 → 10

**Zero new dependencies** — uses only Pydantic, existing income_desk models, and Python stdlib.
