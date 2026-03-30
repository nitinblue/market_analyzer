"""Capital deployment engine for long-term systematic investing.

Systematic, valuation-aware, regime-adjusted capital deployment over 6-18 months.
Covers market valuation, deployment planning, asset allocation, core holdings,
and rebalancing.

All functions are pure computation — accept data, return Pydantic models.
No global state, no side effects.
"""

from __future__ import annotations

from datetime import date, timedelta
from enum import StrEnum

import numpy as np
import pandas as pd
from pydantic import BaseModel


# ═══════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════


class ValuationZone(StrEnum):
    DEEP_VALUE = "deep_value"
    VALUE = "value"
    FAIR = "fair"
    EXPENSIVE = "expensive"
    BUBBLE = "bubble"


class RiskTolerance(StrEnum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class MarketValuation(BaseModel):
    """Valuation context for a market/index."""

    ticker: str
    name: str
    current_pe: float | None
    pe_5y_avg: float | None
    pe_10y_avg: float | None
    pe_percentile: float | None  # Where current P/E sits in 5yr range (0-100)
    earnings_yield: float | None  # 1/PE as %
    dividend_yield: float | None
    from_52w_high_pct: float
    from_52w_low_pct: float

    zone: ValuationZone
    zone_score: float  # -1 (deep value) to +1 (bubble)

    historical_return_at_this_pe: str | None
    commentary: list[str]


class MonthlyAllocation(BaseModel):
    """What to invest in a single month."""

    month: int  # 1, 2, 3, ...
    date: date
    amount: float  # Total for this month

    equity_amount: float
    equity_instruments: list[str]
    gold_amount: float
    debt_amount: float
    cash_reserve: float

    acceleration_reason: str | None = None
    deceleration_reason: str | None = None


class DeploymentSchedule(BaseModel):
    """Monthly capital deployment plan."""

    total_capital: float
    currency: str
    deployment_months: int
    start_date: date

    monthly_allocations: list[MonthlyAllocation]

    base_monthly: float  # Equal split: total / months
    regime_adjustment: str
    valuation_adjustment: str

    total_equity_pct: float
    total_gold_pct: float
    total_debt_pct: float
    total_cash_reserve_pct: float

    commentary: list[str]
    summary: str


class AssetAllocation(BaseModel):
    """Recommended asset allocation."""

    equity_pct: float
    gold_pct: float
    debt_pct: float
    cash_pct: float

    equity_split: dict[str, float]  # e.g. {"nifty_50": 40, "nifty_next_50": 15, ...}

    rationale: list[str]
    regime_context: str
    rebalance_trigger: str


class CoreHolding(BaseModel):
    """A single recommended core holding."""

    ticker: str
    name: str
    allocation_pct: float  # % of total portfolio
    category: str  # "large_cap_index", "sectoral", "gold", "debt", etc.
    instrument_type: str  # "etf", "stock", "mf", "sgb"
    rationale: str
    entry_approach: str  # "lump_sum", "sip_6m", "sip_12m"


class CorePortfolio(BaseModel):
    """Recommended core portfolio for long-term deployment."""

    market: str
    total_capital: float
    currency: str
    holdings: list[CoreHolding]
    total_equity_pct: float
    total_gold_pct: float
    total_debt_pct: float
    commentary: list[str]

    deployment: DeploymentSchedule | None = None


class RebalanceAction(BaseModel):
    """A single rebalancing action."""

    asset: str  # "equity", "gold", "debt", "cash"
    current_pct: float
    target_pct: float
    drift_pct: float
    action: str  # "buy", "sell", "hold"
    amount: float  # How much to buy/sell (in currency)
    rationale: str


class RebalanceCheck(BaseModel):
    """Rebalancing assessment."""

    needs_rebalance: bool
    actions: list[RebalanceAction]
    trigger: str  # "drift >5%", "within threshold", etc.
    commentary: list[str]


# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

# Base asset allocation by risk tolerance
_BASE_ALLOCATION: dict[str, dict[str, float]] = {
    "conservative": {"equity": 40.0, "gold": 25.0, "debt": 25.0, "cash": 10.0},
    "moderate": {"equity": 60.0, "gold": 15.0, "debt": 15.0, "cash": 10.0},
    "aggressive": {"equity": 75.0, "gold": 10.0, "debt": 5.0, "cash": 10.0},
}

# Regime adjustments (additive, applied to equity/gold/debt/cash)
_REGIME_ADJUSTMENTS: dict[str, dict[str, float]] = {
    "risk_on": {"equity": 10.0, "gold": -5.0, "debt": -5.0, "cash": 0.0},
    "risk_off": {"equity": -10.0, "gold": 10.0, "debt": 0.0, "cash": 0.0},
    "stagflation": {"equity": -15.0, "gold": 15.0, "debt": 0.0, "cash": 0.0},
    "deflationary": {"equity": -20.0, "gold": 0.0, "debt": 10.0, "cash": 10.0},
}

# Valuation adjustments
_VALUATION_ADJUSTMENTS: dict[str, dict[str, float]] = {
    "deep_value": {"equity": 10.0, "gold": 0.0, "debt": -5.0, "cash": -5.0},
    "value": {"equity": 5.0, "gold": 0.0, "debt": -2.5, "cash": -2.5},
    "fair": {"equity": 0.0, "gold": 0.0, "debt": 0.0, "cash": 0.0},
    "expensive": {"equity": -10.0, "gold": 0.0, "debt": 0.0, "cash": 10.0},
    "bubble": {"equity": -20.0, "gold": 0.0, "debt": 5.0, "cash": 15.0},
}

# Equity sub-splits by market
_INDIA_EQUITY_SPLIT: dict[str, float] = {
    "nifty_50": 40.0,
    "nifty_next_50": 15.0,
    "banking": 10.0,
    "value_stocks": 20.0,
    "mid_cap": 15.0,
}

_US_EQUITY_SPLIT: dict[str, float] = {
    "sp500": 45.0,
    "qqq": 20.0,
    "quality_stocks": 20.0,
    "international": 15.0,
}

# India core holdings
_INDIA_EQUITY_INSTRUMENTS = [
    "NIFTYBEES", "JUNIORBEES", "BANKBEES",
    "HDFCBANK", "INFY", "TCS", "RELIANCE", "ITC",
]
_INDIA_GOLD_INSTRUMENTS = ["GOLDBEES", "SGB"]
_INDIA_DEBT_INSTRUMENTS = ["LIQUIDBEES", "SHORT-TERM-DEBT-FUND"]

# US core holdings
_US_EQUITY_INSTRUMENTS = [
    "VOO", "QQQ", "AAPL", "MSFT", "JNJ", "BRK-B", "PG",
]
_US_GOLD_INSTRUMENTS = ["GLD"]
_US_DEBT_INSTRUMENTS = ["TLT", "SHY"]

# Regime-to-macro mapping for deployment adjustment
_REGIME_DEPLOYMENT_FACTOR: dict[int, tuple[float, str]] = {
    1: (1.0, "Low-vol mean reverting — normal deployment pace"),
    2: (1.0, "High-vol mean reverting — normal deployment pace"),
    3: (0.9, "Low-vol trending — slight caution, trend may continue"),
    4: (1.2, "High-vol trending — accelerate deployment (buy fear)"),
}

# Valuation deployment factor
_VALUATION_DEPLOYMENT_FACTOR: dict[str, tuple[float, str]] = {
    "deep_value": (1.3, "Deep value — accelerate +30%"),
    "value": (1.15, "Value territory — accelerate +15%"),
    "fair": (1.0, "Fair valuation — normal pace"),
    "expensive": (0.7, "Expensive — decelerate -30%"),
    "bubble": (0.5, "Bubble territory — decelerate -50%, hold cash"),
}

# PE percentile to historical return context
_PE_RETURN_CONTEXT: dict[str, str] = {
    "bottom_20": "When P/E was in the bottom 20% of its range, 3-year avg return was typically 12-18% annualized",
    "below_avg": "When P/E was below average, 3-year avg return was typically 8-12% annualized",
    "near_avg": "When P/E was near average, 3-year avg return was typically 6-10% annualized",
    "above_avg": "When P/E was above average, 3-year avg return was typically 3-6% annualized",
    "top_20": "When P/E was in the top 20% of its range, 3-year avg return was typically 0-4% annualized",
}


# ═══════════════════════════════════════════════════════════════════
# CD1: Market Valuation
# ═══════════════════════════════════════════════════════════════════


def compute_market_valuation(
    ticker: str,
    ohlcv: pd.DataFrame,
    current_pe: float | None = None,
    dividend_yield: float | None = None,
    bond_yield: float | None = None,
) -> MarketValuation:
    """Compute valuation zone from price history and fundamentals.

    If current_pe is None, tries to fetch from yfinance .info.
    Uses 52-week price position as proxy for PE range when PE history unavailable.

    Args:
        ticker: Index or ETF ticker.
        ohlcv: OHLCV DataFrame with DatetimeIndex.
        current_pe: Current trailing P/E ratio.
        dividend_yield: Current annual dividend yield (0-100 scale).
        bond_yield: 10-year government bond yield for equity risk premium.

    Returns:
        MarketValuation with zone classification and commentary.
    """
    if ohlcv.empty:
        raise ValueError(f"Empty OHLCV data for {ticker}")

    close = ohlcv["Close"]

    # --- 52-week metrics ---
    one_year_ago = close.index[-1] - pd.Timedelta(days=365)
    recent = close[close.index >= one_year_ago]
    if len(recent) < 10:
        recent = close.tail(252)

    high_52w = float(recent.max())
    low_52w = float(recent.min())
    current_price = float(close.iloc[-1])

    from_52w_high_pct = ((current_price - high_52w) / high_52w) * 100.0
    from_52w_low_pct = ((current_price - low_52w) / low_52w) * 100.0

    # 52-week position: 0 = at low, 100 = at high
    price_range = high_52w - low_52w
    if price_range > 0:
        position_52w = ((current_price - low_52w) / price_range) * 100.0
    else:
        position_52w = 50.0

    # --- Try to fetch PE from yfinance if not provided ---
    fetched_pe = current_pe
    fetched_div_yield = dividend_yield
    if fetched_pe is None:
        try:
            import yfinance as yf
            from income_desk.data.providers.yfinance import resolve_yfinance_ticker

            info = yf.Ticker(resolve_yfinance_ticker(ticker)).info
            fetched_pe = info.get("trailingPE") or info.get("forwardPE")
            if fetched_div_yield is None:
                raw_yield = info.get("dividendYield")
                if raw_yield is not None:
                    # yfinance returns as decimal (e.g. 0.013 = 1.3%)
                    fetched_div_yield = raw_yield * 100.0
        except Exception:
            pass

    # --- PE percentile estimation ---
    # Use 52-week price position as proxy for PE percentile (when PE history unavailable)
    pe_percentile: float | None = None
    pe_5y_avg: float | None = None
    pe_10y_avg: float | None = None

    if fetched_pe is not None:
        # Estimate PE percentile from price position within 52-week range
        pe_percentile = position_52w  # Price position approximates PE position

        # Rough PE averages from price means
        five_years_ago = close.index[-1] - pd.Timedelta(days=5 * 365)
        ten_years_ago = close.index[-1] - pd.Timedelta(days=10 * 365)
        price_5y = close[close.index >= five_years_ago]
        price_10y = close[close.index >= ten_years_ago]

        if len(price_5y) > 20:
            avg_5y_price = float(price_5y.mean())
            # Scale PE proportionally to price ratio
            pe_5y_avg = round(fetched_pe * (avg_5y_price / current_price), 1)
        if len(price_10y) > 20:
            avg_10y_price = float(price_10y.mean())
            pe_10y_avg = round(fetched_pe * (avg_10y_price / current_price), 1)
    else:
        # Without PE, use price position directly
        pe_percentile = position_52w

    # --- Earnings yield ---
    earnings_yield: float | None = None
    if fetched_pe is not None and fetched_pe > 0:
        earnings_yield = round((1.0 / fetched_pe) * 100.0, 2)

    # --- Zone classification ---
    zone, zone_score = _classify_valuation_zone(
        pe_percentile=pe_percentile,
        from_52w_high_pct=from_52w_high_pct,
        current_pe=fetched_pe,
        pe_5y_avg=pe_5y_avg,
    )

    # --- Historical return context ---
    historical_return: str | None = None
    if pe_percentile is not None:
        if pe_percentile < 20:
            historical_return = _PE_RETURN_CONTEXT["bottom_20"]
        elif pe_percentile < 40:
            historical_return = _PE_RETURN_CONTEXT["below_avg"]
        elif pe_percentile < 60:
            historical_return = _PE_RETURN_CONTEXT["near_avg"]
        elif pe_percentile < 80:
            historical_return = _PE_RETURN_CONTEXT["above_avg"]
        else:
            historical_return = _PE_RETURN_CONTEXT["top_20"]

    # --- Commentary ---
    commentary = _build_valuation_commentary(
        ticker=ticker,
        zone=zone,
        current_pe=fetched_pe,
        pe_5y_avg=pe_5y_avg,
        from_52w_high_pct=from_52w_high_pct,
        earnings_yield=earnings_yield,
        bond_yield=bond_yield,
        dividend_yield=fetched_div_yield,
    )

    # --- Ticker name ---
    name = _ticker_display_name(ticker)

    return MarketValuation(
        ticker=ticker,
        name=name,
        current_pe=fetched_pe,
        pe_5y_avg=pe_5y_avg,
        pe_10y_avg=pe_10y_avg,
        pe_percentile=round(pe_percentile, 1) if pe_percentile is not None else None,
        earnings_yield=earnings_yield,
        dividend_yield=fetched_div_yield,
        from_52w_high_pct=round(from_52w_high_pct, 2),
        from_52w_low_pct=round(from_52w_low_pct, 2),
        zone=zone,
        zone_score=round(zone_score, 3),
        historical_return_at_this_pe=historical_return,
        commentary=commentary,
    )


def _classify_valuation_zone(
    pe_percentile: float | None,
    from_52w_high_pct: float,
    current_pe: float | None,
    pe_5y_avg: float | None,
) -> tuple[ValuationZone, float]:
    """Classify valuation zone and compute zone score.

    Returns (zone, score) where score is -1 (deep value) to +1 (bubble).
    """
    if pe_percentile is None:
        return ValuationZone.FAIR, 0.0

    # Compute score from PE percentile: map 0-100 to -1 to +1
    score = (pe_percentile - 50.0) / 50.0

    # Adjust for distance from 52-week high
    if from_52w_high_pct < -15:
        score -= 0.2  # Well below highs → more value-ish
    elif from_52w_high_pct > -2:
        score += 0.1  # Near highs → more expensive

    # Adjust for PE vs 5y average
    if current_pe is not None and pe_5y_avg is not None and pe_5y_avg > 0:
        pe_ratio = current_pe / pe_5y_avg
        if pe_ratio < 0.85:
            score -= 0.15  # PE well below average
        elif pe_ratio > 1.15:
            score += 0.15  # PE well above average

    # Clamp score
    score = max(-1.0, min(1.0, score))

    # Classify zone
    if score < -0.5:
        zone = ValuationZone.DEEP_VALUE
    elif score < -0.2:
        zone = ValuationZone.VALUE
    elif score < 0.2:
        zone = ValuationZone.FAIR
    elif score < 0.5:
        zone = ValuationZone.EXPENSIVE
    else:
        zone = ValuationZone.BUBBLE

    return zone, score


def _build_valuation_commentary(
    ticker: str,
    zone: ValuationZone,
    current_pe: float | None,
    pe_5y_avg: float | None,
    from_52w_high_pct: float,
    earnings_yield: float | None,
    bond_yield: float | None,
    dividend_yield: float | None,
) -> list[str]:
    """Build human-readable valuation commentary."""
    comments: list[str] = []

    zone_labels = {
        ValuationZone.DEEP_VALUE: "deep value territory — historically attractive for long-term entry",
        ValuationZone.VALUE: "value territory — reasonably attractive for systematic deployment",
        ValuationZone.FAIR: "fair valuation — normal deployment pace appropriate",
        ValuationZone.EXPENSIVE: "expensive — consider slowing deployment, building cash reserve",
        ValuationZone.BUBBLE: "bubble territory — minimize new equity deployment, maximize cash",
    }
    comments.append(f"{ticker} is in {zone_labels[zone]}")

    if current_pe is not None:
        comments.append(f"P/E ratio: {current_pe:.1f}")
        if pe_5y_avg is not None:
            pct_diff = ((current_pe - pe_5y_avg) / pe_5y_avg) * 100
            if pct_diff > 0:
                comments.append(f"P/E is {pct_diff:.0f}% above 5-year average ({pe_5y_avg:.1f})")
            else:
                comments.append(f"P/E is {abs(pct_diff):.0f}% below 5-year average ({pe_5y_avg:.1f})")

    if from_52w_high_pct < -20:
        comments.append(f"Trading {abs(from_52w_high_pct):.1f}% below 52-week high — significant correction")
    elif from_52w_high_pct < -10:
        comments.append(f"Trading {abs(from_52w_high_pct):.1f}% below 52-week high — moderate pullback")
    elif from_52w_high_pct > -2:
        comments.append("Near 52-week highs — limited margin of safety")

    if earnings_yield is not None and bond_yield is not None:
        erp = earnings_yield - bond_yield
        if erp > 3:
            comments.append(
                f"Equity risk premium: {erp:.1f}% (earnings yield {earnings_yield:.1f}% vs bond {bond_yield:.1f}%) — equities attractive vs bonds"
            )
        elif erp > 0:
            comments.append(
                f"Equity risk premium: {erp:.1f}% — modest premium over bonds"
            )
        else:
            comments.append(
                f"Equity risk premium: {erp:.1f}% — bonds offer better yield than stocks"
            )

    if dividend_yield is not None and dividend_yield > 2.0:
        comments.append(f"Dividend yield {dividend_yield:.1f}% provides income cushion")

    return comments


def _ticker_display_name(ticker: str) -> str:
    """Map ticker to display name."""
    names: dict[str, str] = {
        "SPY": "S&P 500 ETF",
        "SPX": "S&P 500 Index",
        "^GSPC": "S&P 500 Index",
        "QQQ": "Nasdaq 100 ETF",
        "VOO": "Vanguard S&P 500 ETF",
        "GLD": "SPDR Gold ETF",
        "TLT": "20+ Year Treasury Bond ETF",
        "SHY": "1-3 Year Treasury Bond ETF",
        "NIFTYBEES": "Nippon India NIFTY 50 ETF",
        "JUNIORBEES": "Nippon India NIFTY Next 50 ETF",
        "BANKBEES": "Nippon India Bank ETF",
        "GOLDBEES": "Nippon India Gold ETF",
        "LIQUIDBEES": "Nippon India Liquid ETF",
        "^NSEI": "NIFTY 50 Index",
        "NIFTY": "NIFTY 50 Index",
    }
    return names.get(ticker, ticker)


# ═══════════════════════════════════════════════════════════════════
# CD2: Deployment Planner
# ═══════════════════════════════════════════════════════════════════


def plan_deployment(
    total_capital: float,
    currency: str = "INR",
    deployment_months: int = 12,
    market: str = "INDIA",
    current_regime_id: int = 2,
    valuation_zone: str = "fair",
    risk_tolerance: str = "moderate",
) -> DeploymentSchedule:
    """Create a systematic capital deployment plan.

    Rules:
    - Base: equal split across months (total / months)
    - Regime adjustment: R4 (volatile) -> accelerate 20%. R1 (calm) -> normal.
    - Valuation adjustment: deep_value -> accelerate 30%. Expensive -> decelerate 30%.
    - Risk tolerance: determines equity/gold/debt/cash split.
    - Always keep 10% cash reserve minimum.

    Args:
        total_capital: Total amount to deploy.
        currency: Currency code (INR, USD).
        deployment_months: Number of months to spread deployment over.
        market: Market to deploy in (INDIA, US).
        current_regime_id: Current regime (1-4).
        valuation_zone: Current valuation zone.
        risk_tolerance: conservative, moderate, or aggressive.

    Returns:
        DeploymentSchedule with monthly allocations.
    """
    if deployment_months < 1:
        raise ValueError("deployment_months must be >= 1")
    if total_capital <= 0:
        raise ValueError("total_capital must be positive")

    risk_tol = risk_tolerance.lower()
    if risk_tol not in _BASE_ALLOCATION:
        raise ValueError(f"risk_tolerance must be one of: {list(_BASE_ALLOCATION.keys())}")

    val_zone = valuation_zone.lower()
    base_monthly = total_capital / deployment_months

    # Get regime and valuation factors
    regime_factor, regime_desc = _REGIME_DEPLOYMENT_FACTOR.get(
        current_regime_id, (1.0, "Unknown regime — normal pace")
    )
    val_factor, val_desc = _VALUATION_DEPLOYMENT_FACTOR.get(
        val_zone, (1.0, "Unknown valuation — normal pace")
    )

    # Combined factor
    combined_factor = regime_factor * val_factor

    # Asset allocation percentages
    alloc = _BASE_ALLOCATION[risk_tol].copy()
    equity_pct = alloc["equity"]
    gold_pct = alloc["gold"]
    debt_pct = alloc["debt"]
    cash_pct = alloc["cash"]

    # Select instruments by market
    is_india = market.upper() in ("INDIA", "IN")
    if is_india:
        equity_instruments = _INDIA_EQUITY_INSTRUMENTS[:5]
    else:
        equity_instruments = _US_EQUITY_INSTRUMENTS[:5]

    # Build monthly allocations
    monthly_allocations: list[MonthlyAllocation] = []
    start = date.today()
    remaining = total_capital
    total_deployed = 0.0

    for m in range(1, deployment_months + 1):
        month_date = start + timedelta(days=30 * (m - 1))

        # Apply combined factor but never deploy more than remaining
        month_amount = base_monthly * combined_factor
        month_amount = min(month_amount, remaining)
        month_amount = max(month_amount, 0.0)

        eq_amt = month_amount * (equity_pct / 100.0)
        gold_amt = month_amount * (gold_pct / 100.0)
        debt_amt = month_amount * (debt_pct / 100.0)
        cash_amt = month_amount * (cash_pct / 100.0)

        accel_reason = None
        decel_reason = None
        if combined_factor > 1.05:
            accel_reason = f"Accelerating: {regime_desc}. {val_desc}."
        elif combined_factor < 0.95:
            decel_reason = f"Decelerating: {regime_desc}. {val_desc}."

        monthly_allocations.append(
            MonthlyAllocation(
                month=m,
                date=month_date,
                amount=round(month_amount, 2),
                equity_amount=round(eq_amt, 2),
                equity_instruments=equity_instruments,
                gold_amount=round(gold_amt, 2),
                debt_amount=round(debt_amt, 2),
                cash_reserve=round(cash_amt, 2),
                acceleration_reason=accel_reason,
                deceleration_reason=decel_reason,
            )
        )
        remaining -= month_amount
        total_deployed += month_amount

    # If remaining capital after all months (due to deceleration), note it
    commentary: list[str] = []
    commentary.append(
        f"Deploying {currency} {total_capital:,.0f} over {deployment_months} months"
    )
    commentary.append(f"Base monthly amount: {currency} {base_monthly:,.0f}")

    if combined_factor > 1.05:
        commentary.append(f"Deployment ACCELERATED by {(combined_factor - 1) * 100:.0f}%")
    elif combined_factor < 0.95:
        commentary.append(f"Deployment DECELERATED by {(1 - combined_factor) * 100:.0f}%")
        undeployed = total_capital - total_deployed
        if undeployed > 0:
            commentary.append(
                f"{currency} {undeployed:,.0f} held back as dry powder — deploy when valuation improves"
            )

    commentary.append(
        f"Asset split: {equity_pct:.0f}% equity, {gold_pct:.0f}% gold, "
        f"{debt_pct:.0f}% debt, {cash_pct:.0f}% cash"
    )

    summary = (
        f"Deploy {currency} {total_capital:,.0f} over {deployment_months}mo | "
        f"{equity_pct:.0f}E / {gold_pct:.0f}G / {debt_pct:.0f}D / {cash_pct:.0f}C | "
        f"pace {'accelerated' if combined_factor > 1.05 else 'decelerated' if combined_factor < 0.95 else 'normal'}"
    )

    return DeploymentSchedule(
        total_capital=total_capital,
        currency=currency,
        deployment_months=deployment_months,
        start_date=start,
        monthly_allocations=monthly_allocations,
        base_monthly=round(base_monthly, 2),
        regime_adjustment=regime_desc,
        valuation_adjustment=val_desc,
        total_equity_pct=equity_pct,
        total_gold_pct=gold_pct,
        total_debt_pct=debt_pct,
        total_cash_reserve_pct=cash_pct,
        commentary=commentary,
        summary=summary,
    )


# ═══════════════════════════════════════════════════════════════════
# CD3: Asset Allocation
# ═══════════════════════════════════════════════════════════════════


def compute_asset_allocation(
    market: str = "INDIA",
    regime: str = "risk_off",
    valuation_zone: str = "value",
    risk_tolerance: str = "moderate",
    age: int | None = None,
    has_existing_equity: bool = False,
    has_existing_gold: bool = False,
) -> AssetAllocation:
    """Compute recommended asset allocation.

    Base allocation is determined by risk tolerance. Regime and valuation
    adjustments shift percentages. Age optionally reduces equity.

    Args:
        market: INDIA or US.
        regime: risk_on, risk_off, stagflation, deflationary.
        valuation_zone: deep_value, value, fair, expensive, bubble.
        risk_tolerance: conservative, moderate, aggressive.
        age: Optional age — reduces equity by (age - 30) * 0.5% if > 30.
        has_existing_equity: If True, reduce equity allocation slightly.
        has_existing_gold: If True, reduce gold allocation slightly.

    Returns:
        AssetAllocation with rationale.
    """
    risk_tol = risk_tolerance.lower()
    if risk_tol not in _BASE_ALLOCATION:
        raise ValueError(f"risk_tolerance must be one of: {list(_BASE_ALLOCATION.keys())}")

    # Start with base allocation
    alloc = _BASE_ALLOCATION[risk_tol].copy()

    rationale: list[str] = []
    rationale.append(
        f"Base ({risk_tol}): {alloc['equity']:.0f}E / {alloc['gold']:.0f}G / "
        f"{alloc['debt']:.0f}D / {alloc['cash']:.0f}C"
    )

    # Apply regime adjustment
    regime_key = regime.lower()
    if regime_key in _REGIME_ADJUSTMENTS:
        adj = _REGIME_ADJUSTMENTS[regime_key]
        for k in alloc:
            alloc[k] += adj[k]
        rationale.append(f"Regime ({regime_key}): equity {adj['equity']:+.0f}%, gold {adj['gold']:+.0f}%")

    # Apply valuation adjustment
    val_key = valuation_zone.lower()
    if val_key in _VALUATION_ADJUSTMENTS:
        adj = _VALUATION_ADJUSTMENTS[val_key]
        for k in alloc:
            alloc[k] += adj[k]
        rationale.append(f"Valuation ({val_key}): equity {adj['equity']:+.0f}%, cash {adj['cash']:+.0f}%")

    # Age adjustment
    if age is not None and age > 30:
        age_reduction = min((age - 30) * 0.5, 30.0)  # Cap at 30% reduction
        alloc["equity"] -= age_reduction
        alloc["debt"] += age_reduction * 0.6
        alloc["cash"] += age_reduction * 0.4
        rationale.append(f"Age ({age}): equity -{age_reduction:.0f}%, debt/cash +{age_reduction:.0f}%")

    # Existing holdings adjustment
    if has_existing_equity:
        alloc["equity"] -= 5.0
        alloc["cash"] += 5.0
        rationale.append("Already have equity — reducing by 5%")
    if has_existing_gold:
        alloc["gold"] -= 5.0
        alloc["cash"] += 5.0
        rationale.append("Already have gold — reducing by 5%")

    # Clamp: nothing below 0, ensure sums to 100
    for k in alloc:
        alloc[k] = max(0.0, alloc[k])
    total = sum(alloc.values())
    if total > 0:
        for k in alloc:
            alloc[k] = round((alloc[k] / total) * 100.0, 1)

    # Equity sub-split by market
    is_india = market.upper() in ("INDIA", "IN")
    equity_split = _INDIA_EQUITY_SPLIT.copy() if is_india else _US_EQUITY_SPLIT.copy()

    # Regime context string
    regime_labels = {
        "risk_on": "Risk-on: growth favored, equity bias higher",
        "risk_off": "Risk-off: defensive, gold/debt favored",
        "stagflation": "Stagflation: commodities/gold favored, equities challenged",
        "deflationary": "Deflationary: cash/debt king, equities weakest",
    }
    regime_context = regime_labels.get(regime_key, f"Regime: {regime}")

    return AssetAllocation(
        equity_pct=alloc["equity"],
        gold_pct=alloc["gold"],
        debt_pct=alloc["debt"],
        cash_pct=alloc["cash"],
        equity_split=equity_split,
        rationale=rationale,
        regime_context=regime_context,
        rebalance_trigger="Rebalance when any asset class drifts >5% from target",
    )


# ═══════════════════════════════════════════════════════════════════
# CD4: Core Holdings Recommender
# ═══════════════════════════════════════════════════════════════════


def recommend_core_portfolio(
    total_capital: float,
    currency: str = "INR",
    market: str = "INDIA",
    regime_id: int = 2,
    valuation_zone: str = "value",
    risk_tolerance: str = "moderate",
    deployment_months: int = 12,
) -> CorePortfolio:
    """Recommend a core portfolio for long-term capital deployment.

    India holdings: NIFTYBEES, JUNIORBEES, BANKBEES, top value stocks,
    Gold ETF/SGB, short-term debt fund.

    US holdings: VOO/SPY, QQQ, top quality stocks, GLD, TLT/SHY.

    Args:
        total_capital: Total amount to deploy.
        currency: Currency code.
        market: INDIA or US.
        regime_id: Current regime (1-4) for deployment adjustment.
        valuation_zone: Current valuation zone.
        risk_tolerance: conservative, moderate, or aggressive.
        deployment_months: Number of months for deployment schedule.

    Returns:
        CorePortfolio with holdings and optional deployment schedule.
    """
    # Get asset allocation
    regime_map = {1: "risk_on", 2: "risk_off", 3: "risk_on", 4: "risk_off"}
    regime_label = regime_map.get(regime_id, "risk_off")
    alloc = compute_asset_allocation(
        market=market,
        regime=regime_label,
        valuation_zone=valuation_zone,
        risk_tolerance=risk_tolerance,
    )

    holdings: list[CoreHolding] = []
    is_india = market.upper() in ("INDIA", "IN")

    if is_india:
        holdings = _build_india_holdings(alloc, valuation_zone)
    else:
        holdings = _build_us_holdings(alloc, valuation_zone)

    # Build deployment schedule
    deployment = plan_deployment(
        total_capital=total_capital,
        currency=currency,
        deployment_months=deployment_months,
        market=market,
        current_regime_id=regime_id,
        valuation_zone=valuation_zone,
        risk_tolerance=risk_tolerance,
    )

    commentary: list[str] = []
    commentary.append(
        f"Core portfolio for {market} market — {risk_tolerance} risk tolerance"
    )
    commentary.append(
        f"Allocation: {alloc.equity_pct:.0f}% equity, {alloc.gold_pct:.0f}% gold, "
        f"{alloc.debt_pct:.0f}% debt, {alloc.cash_pct:.0f}% cash"
    )
    commentary.append(f"Valuation zone: {valuation_zone} — {deployment.valuation_adjustment}")
    if regime_id == 4:
        commentary.append("R4 regime — high volatility = opportunity for long-term buyers")
    elif regime_id == 1:
        commentary.append("R1 regime — calm markets, deploy at normal pace")

    return CorePortfolio(
        market=market.upper(),
        total_capital=total_capital,
        currency=currency,
        holdings=holdings,
        total_equity_pct=alloc.equity_pct,
        total_gold_pct=alloc.gold_pct,
        total_debt_pct=alloc.debt_pct,
        commentary=commentary,
        deployment=deployment,
    )


def _build_india_holdings(alloc: AssetAllocation, valuation_zone: str) -> list[CoreHolding]:
    """Build India-specific core holdings."""
    equity_pct = alloc.equity_pct
    gold_pct = alloc.gold_pct
    debt_pct = alloc.debt_pct

    holdings: list[CoreHolding] = []

    # Index ETFs
    nifty_pct = equity_pct * 0.40
    holdings.append(CoreHolding(
        ticker="NIFTYBEES",
        name="Nippon India NIFTY 50 ETF",
        allocation_pct=round(nifty_pct, 1),
        category="large_cap_index",
        instrument_type="etf",
        rationale="Core large-cap exposure via NIFTY 50. Lowest cost, highest liquidity.",
        entry_approach="sip_12m" if valuation_zone in ("expensive", "bubble") else "sip_6m",
    ))

    junior_pct = equity_pct * 0.15
    holdings.append(CoreHolding(
        ticker="JUNIORBEES",
        name="Nippon India NIFTY Next 50 ETF",
        allocation_pct=round(junior_pct, 1),
        category="large_cap_index",
        instrument_type="etf",
        rationale="Next 50 large-caps — higher growth potential than NIFTY 50.",
        entry_approach="sip_12m",
    ))

    bank_pct = equity_pct * 0.10
    holdings.append(CoreHolding(
        ticker="BANKBEES",
        name="Nippon India Bank ETF",
        allocation_pct=round(bank_pct, 1),
        category="sectoral",
        instrument_type="etf",
        rationale="Banking sector — interest rate cycle play, core India growth sector.",
        entry_approach="sip_6m",
    ))

    # Value stocks (top 5)
    value_tickers = [
        ("HDFCBANK", "HDFC Bank", "Private banking leader, consistent compounder"),
        ("INFY", "Infosys", "IT services bellwether, dollar earnings hedge"),
        ("TCS", "TCS", "Largest IT company, stable earnings, dividend payer"),
        ("RELIANCE", "Reliance Industries", "Diversified conglomerate — energy, telecom, retail"),
        ("ITC", "ITC", "High dividend yield, FMCG + agriculture diversification"),
    ]
    stock_pct_each = (equity_pct * 0.20) / len(value_tickers)
    for ticker, name, rationale in value_tickers:
        holdings.append(CoreHolding(
            ticker=ticker,
            name=name,
            allocation_pct=round(stock_pct_each, 1),
            category="value_stocks",
            instrument_type="stock",
            rationale=rationale,
            entry_approach="sip_12m",
        ))

    # Mid-cap allocation (via ETF or direct)
    midcap_pct = equity_pct * 0.15
    holdings.append(CoreHolding(
        ticker="MIDCAPBEES",
        name="NIFTY Midcap 150 ETF",
        allocation_pct=round(midcap_pct, 1),
        category="mid_cap",
        instrument_type="etf",
        rationale="Mid-cap exposure for higher growth. Higher volatility — deploy slowly.",
        entry_approach="sip_12m",
    ))

    # Gold
    gold_sgb_pct = gold_pct * 0.6
    gold_etf_pct = gold_pct * 0.4
    holdings.append(CoreHolding(
        ticker="SGB",
        name="Sovereign Gold Bond",
        allocation_pct=round(gold_sgb_pct, 1),
        category="gold",
        instrument_type="sgb",
        rationale="Tax-free on maturity (8yr), 2.5% annual interest. Best gold instrument in India.",
        entry_approach="lump_sum",
    ))
    holdings.append(CoreHolding(
        ticker="GOLDBEES",
        name="Nippon India Gold ETF",
        allocation_pct=round(gold_etf_pct, 1),
        category="gold",
        instrument_type="etf",
        rationale="Liquid gold exposure for rebalancing. Supplement SGBs.",
        entry_approach="sip_6m",
    ))

    # Debt
    holdings.append(CoreHolding(
        ticker="SHORT-TERM-DEBT-FUND",
        name="Short Duration Debt Fund",
        allocation_pct=round(debt_pct, 1),
        category="debt",
        instrument_type="mf",
        rationale="Low duration risk, stable returns. Park deployment capital here.",
        entry_approach="lump_sum",
    ))

    return holdings


def _build_us_holdings(alloc: AssetAllocation, valuation_zone: str) -> list[CoreHolding]:
    """Build US-specific core holdings."""
    equity_pct = alloc.equity_pct
    gold_pct = alloc.gold_pct
    debt_pct = alloc.debt_pct

    holdings: list[CoreHolding] = []

    # S&P 500
    sp_pct = equity_pct * 0.45
    holdings.append(CoreHolding(
        ticker="VOO",
        name="Vanguard S&P 500 ETF",
        allocation_pct=round(sp_pct, 1),
        category="large_cap_index",
        instrument_type="etf",
        rationale="Core US large-cap exposure. Lowest expense ratio, tracks S&P 500.",
        entry_approach="sip_12m" if valuation_zone in ("expensive", "bubble") else "sip_6m",
    ))

    # QQQ
    qqq_pct = equity_pct * 0.20
    holdings.append(CoreHolding(
        ticker="QQQ",
        name="Invesco QQQ (Nasdaq 100)",
        allocation_pct=round(qqq_pct, 1),
        category="growth_index",
        instrument_type="etf",
        rationale="Tech/growth exposure. Higher beta, higher potential returns.",
        entry_approach="sip_12m",
    ))

    # Quality stocks
    quality_tickers = [
        ("AAPL", "Apple", "Quality compounder, massive buyback + services growth"),
        ("MSFT", "Microsoft", "Cloud + AI leader, recurring revenue, wide moat"),
        ("JNJ", "Johnson & Johnson", "Defensive healthcare, dividend aristocrat"),
        ("BRK-B", "Berkshire Hathaway", "Diversified value, cash-rich, Buffett allocation"),
        ("PG", "Procter & Gamble", "Consumer staples, dividend growth, defensive"),
    ]
    stock_pct_each = (equity_pct * 0.20) / len(quality_tickers)
    for ticker, name, rationale in quality_tickers:
        holdings.append(CoreHolding(
            ticker=ticker,
            name=name,
            allocation_pct=round(stock_pct_each, 1),
            category="quality_stocks",
            instrument_type="stock",
            rationale=rationale,
            entry_approach="sip_12m",
        ))

    # International
    intl_pct = equity_pct * 0.15
    holdings.append(CoreHolding(
        ticker="VXUS",
        name="Vanguard Total International Stock ETF",
        allocation_pct=round(intl_pct, 1),
        category="international",
        instrument_type="etf",
        rationale="Ex-US diversification. Reduces home country concentration.",
        entry_approach="sip_6m",
    ))

    # Gold
    holdings.append(CoreHolding(
        ticker="GLD",
        name="SPDR Gold Shares",
        allocation_pct=round(gold_pct, 1),
        category="gold",
        instrument_type="etf",
        rationale="Inflation hedge, crisis hedge, portfolio diversifier.",
        entry_approach="sip_6m",
    ))

    # Debt
    tlt_pct = debt_pct * 0.5
    shy_pct = debt_pct * 0.5
    holdings.append(CoreHolding(
        ticker="TLT",
        name="iShares 20+ Year Treasury Bond ETF",
        allocation_pct=round(tlt_pct, 1),
        category="debt",
        instrument_type="etf",
        rationale="Long-duration treasuries — deflation hedge, flight-to-quality asset.",
        entry_approach="lump_sum",
    ))
    holdings.append(CoreHolding(
        ticker="SHY",
        name="iShares 1-3 Year Treasury Bond ETF",
        allocation_pct=round(shy_pct, 1),
        category="debt",
        instrument_type="etf",
        rationale="Short-duration treasuries — cash equivalent, minimal interest rate risk.",
        entry_approach="lump_sum",
    ))

    return holdings


# ═══════════════════════════════════════════════════════════════════
# CD5: Rebalancing Engine
# ═══════════════════════════════════════════════════════════════════


def check_rebalance(
    current_allocation: dict[str, float],
    target_allocation: dict[str, float],
    portfolio_value: float,
    drift_threshold_pct: float = 5.0,
) -> RebalanceCheck:
    """Check if portfolio needs rebalancing.

    Compare current vs target allocation. If any asset class drifts
    beyond threshold, generate buy/sell actions.

    Args:
        current_allocation: Current weights, e.g. {"equity": 70, "gold": 12, "debt": 8, "cash": 10}.
        target_allocation: Target weights, e.g. {"equity": 60, "gold": 15, "debt": 15, "cash": 10}.
        portfolio_value: Total portfolio value in currency.
        drift_threshold_pct: Trigger rebalance if any asset drifts beyond this (default 5%).

    Returns:
        RebalanceCheck with actions if rebalancing is needed.
    """
    actions: list[RebalanceAction] = []
    max_drift = 0.0

    # Normalize current allocation to ensure it sums to 100
    curr_total = sum(current_allocation.values())
    if curr_total <= 0:
        raise ValueError("current_allocation values must sum to > 0")

    normalized_current: dict[str, float] = {}
    for k, v in current_allocation.items():
        normalized_current[k] = (v / curr_total) * 100.0

    # Check all assets that appear in either current or target
    all_assets = set(normalized_current.keys()) | set(target_allocation.keys())

    for asset in sorted(all_assets):
        curr_pct = normalized_current.get(asset, 0.0)
        tgt_pct = target_allocation.get(asset, 0.0)
        drift = curr_pct - tgt_pct
        abs_drift = abs(drift)
        max_drift = max(max_drift, abs_drift)

        # Determine action
        if abs_drift < 0.5:
            action_type = "hold"
            amount = 0.0
            rationale = f"{asset}: on target ({curr_pct:.1f}% vs {tgt_pct:.1f}%)"
        elif drift > 0:
            action_type = "sell"
            amount = (abs_drift / 100.0) * portfolio_value
            rationale = f"{asset}: overweight by {abs_drift:.1f}% — sell {amount:,.0f} to rebalance"
        else:
            action_type = "buy"
            amount = (abs_drift / 100.0) * portfolio_value
            rationale = f"{asset}: underweight by {abs_drift:.1f}% — buy {amount:,.0f} to rebalance"

        actions.append(RebalanceAction(
            asset=asset,
            current_pct=round(curr_pct, 1),
            target_pct=round(tgt_pct, 1),
            drift_pct=round(drift, 1),
            action=action_type,
            amount=round(amount, 2),
            rationale=rationale,
        ))

    needs_rebalance = max_drift > drift_threshold_pct

    if needs_rebalance:
        trigger = f"drift >{drift_threshold_pct:.0f}% (max drift: {max_drift:.1f}%)"
    else:
        trigger = f"within threshold (max drift: {max_drift:.1f}%, threshold: {drift_threshold_pct:.0f}%)"

    commentary: list[str] = []
    if needs_rebalance:
        drifted = [a for a in actions if abs(a.drift_pct) > drift_threshold_pct]
        commentary.append(
            f"Rebalancing recommended — {len(drifted)} asset(s) beyond {drift_threshold_pct:.0f}% threshold"
        )
        for a in drifted:
            commentary.append(f"  {a.asset}: {a.current_pct:.1f}% vs target {a.target_pct:.1f}% ({a.action} {a.amount:,.0f})")
    else:
        commentary.append(
            f"No rebalancing needed — all assets within {drift_threshold_pct:.0f}% threshold"
        )
        commentary.append(f"Max drift: {max_drift:.1f}%")

    return RebalanceCheck(
        needs_rebalance=needs_rebalance,
        actions=actions,
        trigger=trigger,
        commentary=commentary,
    )


# ═══════════════════════════════════════════════════════════════════
# CD6: LEAP vs Stock Comparison
# ═══════════════════════════════════════════════════════════════════


class LeapVsStockAnalysis(BaseModel):
    """Cost-benefit comparison: buying stock vs buying LEAP call for core holding."""

    ticker: str
    current_price: float
    shares_equivalent: int  # 100 (1 contract = 100 shares)

    # Stock purchase
    stock_cost: float  # 100 shares x price
    stock_annual_dividend: float  # Dividend yield x stock_cost
    stock_breakeven: float  # = entry price
    stock_max_loss: str  # "unlimited below entry"

    # LEAP purchase (deep ITM call, 80+ delta)
    leap_cost: float  # Premium for 1 LEAP (per-share x lot_size)
    leap_delta: float  # ~0.80
    leap_strike: float
    leap_expiration: str
    leap_dte: int
    leap_daily_theta: float  # Daily time decay in $
    leap_annual_theta_cost: float  # Theta x 365
    leap_breakeven: float  # Strike + premium per share
    leap_max_loss: str  # "premium paid"
    leap_capital_saved: float  # stock_cost - leap_cost

    # Comparison
    capital_efficiency: float  # stock_cost / leap_cost (e.g., 8x)
    dividend_forgone: float  # Annual dividend NOT received
    theta_cost_annual: float  # Annual time decay
    net_annual_cost_of_leap: float  # theta + dividend forgone - interest on saved capital
    interest_on_saved_capital: float  # Capital saved x risk-free rate

    # Verdict
    leap_advantage: bool  # True if LEAP is more efficient
    verdict: str  # "LEAP preferred" or "Stock preferred"
    rationale: list[str]

    # When to use each
    leap_best_when: list[str]
    stock_best_when: list[str]


def compare_leap_vs_stock(
    ticker: str,
    current_price: float,
    dividend_yield_pct: float = 0.0,
    leap_premium: float | None = None,
    leap_strike: float | None = None,
    leap_dte: int = 365,
    iv: float = 0.20,
    risk_free_rate: float = 0.05,
    lot_size: int = 100,
) -> LeapVsStockAnalysis:
    """Compare buying stock outright vs LEAP call for core holding position.

    LEAP: Deep in-the-money call (80+ delta), 12-18 month expiry.
    Gives ~80% of upside at ~10% of capital cost.

    Use when: capital efficiency matters, willing to forgo dividend,
    comfortable rolling every 6-12 months.

    Args:
        ticker: Stock ticker symbol.
        current_price: Current stock price.
        dividend_yield_pct: Annual dividend yield as percentage (e.g. 1.5 for 1.5%).
        leap_premium: Known LEAP call premium per share (from broker). If None, estimated.
        leap_strike: LEAP strike price. If None, defaults to ~80% of current price (20% ITM).
        leap_dte: Days to expiry for the LEAP (default 365).
        iv: Implied volatility (decimal, e.g. 0.20 for 20%). Used for premium estimation.
        risk_free_rate: Annual risk-free rate (decimal, e.g. 0.05 for 5%).
        lot_size: Shares per contract (100 for US).

    Returns:
        LeapVsStockAnalysis with full comparison.
    """
    if current_price <= 0:
        raise ValueError("current_price must be positive")
    if leap_dte < 1:
        raise ValueError("leap_dte must be >= 1")

    # --- Strike ---
    if leap_strike is None:
        leap_strike = round(current_price * 0.80, 2)  # 20% ITM

    # --- Premium estimation ---
    intrinsic = max(current_price - leap_strike, 0.0)
    if leap_premium is None:
        # Simplified BS approximation for deep ITM call:
        # premium ~= intrinsic + time_value
        # time_value ~= price * iv * sqrt(dte/365) * 0.4 (for deep ITM)
        time_value = current_price * iv * np.sqrt(leap_dte / 365.0) * 0.4
        leap_premium_per_share = intrinsic + time_value
    else:
        leap_premium_per_share = leap_premium

    # --- Delta estimate ---
    # Deep ITM calls have high delta; rough estimate based on moneyness
    moneyness = current_price / leap_strike if leap_strike > 0 else 1.0
    if moneyness >= 1.3:
        delta = 0.90
    elif moneyness >= 1.2:
        delta = 0.85
    elif moneyness >= 1.1:
        delta = 0.80
    elif moneyness >= 1.0:
        delta = 0.70
    else:
        delta = 0.55

    # --- Costs ---
    stock_cost = current_price * lot_size
    leap_total_cost = leap_premium_per_share * lot_size
    capital_saved = stock_cost - leap_total_cost

    # --- Dividend ---
    annual_dividend = stock_cost * (dividend_yield_pct / 100.0)

    # --- Theta ---
    # Daily theta for deep ITM LEAP (time_value / DTE is rough approximation)
    time_value_total = (leap_premium_per_share - intrinsic) * lot_size
    daily_theta = time_value_total / leap_dte if leap_dte > 0 else 0.0
    annual_theta_cost = daily_theta * 365.0

    # --- Interest on saved capital ---
    interest_on_saved = capital_saved * risk_free_rate

    # --- Net annual cost ---
    net_annual_cost = annual_theta_cost + annual_dividend - interest_on_saved

    # --- Capital efficiency ---
    capital_efficiency = stock_cost / leap_total_cost if leap_total_cost > 0 else 0.0

    # --- Breakevens ---
    stock_breakeven = current_price
    leap_breakeven = leap_strike + leap_premium_per_share

    # --- Expiration string ---
    from datetime import timedelta as td

    exp_date = date.today() + td(days=leap_dte)
    leap_expiration = exp_date.strftime("%Y-%m-%d")

    # --- Verdict ---
    # LEAP preferred if net annual cost < 2% of stock cost AND capital efficiency > 5x
    cost_pct_of_stock = (net_annual_cost / stock_cost * 100.0) if stock_cost > 0 else 999.0
    leap_advantage = cost_pct_of_stock < 2.0 and capital_efficiency > 5.0

    rationale: list[str] = []
    if leap_advantage:
        verdict = "LEAP preferred"
        rationale.append(
            f"Capital efficiency {capital_efficiency:.1f}x — LEAP uses "
            f"${leap_total_cost:,.0f} vs ${stock_cost:,.0f} for stock"
        )
        rationale.append(
            f"Net annual cost of LEAP: ${net_annual_cost:,.0f} "
            f"({cost_pct_of_stock:.1f}% of stock cost)"
        )
        if capital_saved > 0:
            rationale.append(
                f"${capital_saved:,.0f} freed up — can earn ${interest_on_saved:,.0f}/yr "
                f"in risk-free rate or deploy elsewhere"
            )
    else:
        verdict = "Stock preferred"
        if capital_efficiency <= 5.0:
            rationale.append(
                f"Capital efficiency only {capital_efficiency:.1f}x — LEAP not cheap enough"
            )
        if cost_pct_of_stock >= 2.0:
            rationale.append(
                f"Net annual cost of LEAP is {cost_pct_of_stock:.1f}% of stock cost — too expensive"
            )
        if dividend_yield_pct > 2.0:
            rationale.append(
                f"Dividend yield {dividend_yield_pct:.1f}% is significant — stock ownership preferred"
            )

    if dividend_yield_pct > 0:
        rationale.append(
            f"LEAP forfeits ${annual_dividend:,.0f}/yr in dividends"
        )

    leap_best_when = [
        "Capital is limited and you want leveraged exposure",
        "Stock is expensive and you want to limit max loss",
        "You plan to hold 6-18 months (roll before expiry)",
        "Dividend yield is low (<1.5%)",
        "IV is low (cheap time value)",
    ]
    stock_best_when = [
        "You want dividend income",
        "Long-term hold (>2 years) without rolling hassle",
        "Stock has high dividend yield (>2%)",
        "IV is elevated (expensive LEAP premiums)",
        "You want to sell covered calls against the position",
    ]

    return LeapVsStockAnalysis(
        ticker=ticker,
        current_price=current_price,
        shares_equivalent=lot_size,
        stock_cost=round(stock_cost, 2),
        stock_annual_dividend=round(annual_dividend, 2),
        stock_breakeven=round(stock_breakeven, 2),
        stock_max_loss="unlimited below entry",
        leap_cost=round(leap_total_cost, 2),
        leap_delta=round(delta, 2),
        leap_strike=round(leap_strike, 2),
        leap_expiration=leap_expiration,
        leap_dte=leap_dte,
        leap_daily_theta=round(daily_theta, 2),
        leap_annual_theta_cost=round(annual_theta_cost, 2),
        leap_breakeven=round(leap_breakeven, 2),
        leap_max_loss=f"premium paid (${leap_total_cost:,.0f})",
        leap_capital_saved=round(capital_saved, 2),
        capital_efficiency=round(capital_efficiency, 2),
        dividend_forgone=round(annual_dividend, 2),
        theta_cost_annual=round(annual_theta_cost, 2),
        net_annual_cost_of_leap=round(net_annual_cost, 2),
        interest_on_saved_capital=round(interest_on_saved, 2),
        leap_advantage=leap_advantage,
        verdict=verdict,
        rationale=rationale,
        leap_best_when=leap_best_when,
        stock_best_when=stock_best_when,
    )


# ═══════════════════════════════════════════════════════════════════
# CD7: Wheel Strategy Analysis
# ═══════════════════════════════════════════════════════════════════


class WheelStrategyAnalysis(BaseModel):
    """The Wheel: sell put -> get assigned -> sell covered call -> repeat."""

    ticker: str
    current_price: float

    # Phase 1: Cash-Secured Put
    put_strike: float  # Target entry (e.g., 5% below current)
    put_premium: float  # Estimated premium received (total, not per-share)
    put_dte: int  # Days to expiry (30-45 typical)
    put_annualized_yield: float  # Premium / strike x (365/DTE) as %
    put_breakeven: float  # Strike - premium per share
    put_capital_required: float  # Strike x 100 (cash secured)

    # Phase 2: Covered Call (if assigned)
    call_strike: float  # Target exit (e.g., 5% above assignment price)
    call_premium: float  # Estimated premium (total)
    call_dte: int
    call_annualized_yield: float  # As %
    call_breakeven: float  # Assignment price - put premium - call premium (per share)

    # Full wheel metrics
    total_premium_if_wheeled: float  # Put premium + call premium
    effective_cost_basis: float  # Put strike - total premium per share
    cost_reduction_pct: float  # How much premiums reduce your cost basis (%)
    annualized_wheel_yield: float  # Annual yield from premium collection (%)

    # Risk assessment
    max_loss_scenario: str  # Stock goes to 0: lose stock cost - premiums
    assignment_probability: str  # Based on delta
    regime_suitability: str  # Best in R1/R2

    # Verdict
    verdict: str
    rationale: list[str]

    # Comparison with outright buy
    vs_stock_advantage: str  # "Lower cost basis by X%" or "Higher yield"


def analyze_wheel_strategy(
    ticker: str,
    current_price: float,
    iv: float = 0.20,
    regime_id: int = 1,
    put_delta: float = 0.30,
    call_delta: float = 0.30,
    dte: int = 35,
    dividend_yield_pct: float = 0.0,
    risk_free_rate: float = 0.05,
    lot_size: int = 100,
) -> WheelStrategyAnalysis:
    """Analyze the Wheel strategy for a stock.

    The Wheel:
    1. Sell cash-secured put at put_strike (collect premium while waiting to buy)
    2. If assigned: you now own stock at (strike - premium) = effective basis
    3. Sell covered call at call_strike (collect premium while waiting to sell)
    4. If called away: you sold at (strike + premium) = effective exit
    5. Repeat

    Best in: R1 (low vol, mean reverting), R2 (high premiums, mean reverting)
    Worst in: R4 (explosive moves, get assigned at bad prices)

    Args:
        ticker: Stock ticker symbol.
        current_price: Current stock price.
        iv: Current implied volatility (decimal).
        regime_id: Current regime (1-4).
        put_delta: Target put delta (0.30 = ~70% POP).
        call_delta: Target call delta (0.30 = ~70% POP).
        dte: Days to expiry for each cycle.
        dividend_yield_pct: Annual dividend yield as percentage.
        risk_free_rate: Annual risk-free rate (decimal).
        lot_size: Shares per contract (100 for US).

    Returns:
        WheelStrategyAnalysis with full wheel analysis.
    """
    if current_price <= 0:
        raise ValueError("current_price must be positive")
    if dte < 1:
        raise ValueError("dte must be >= 1")

    sqrt_dte = np.sqrt(dte / 365.0)

    # --- Put strike: approximately delta-based distance from current price ---
    # For a 30-delta put, strike is roughly: price * (1 - delta * iv * sqrt(dte/365))
    put_distance = put_delta * iv * sqrt_dte
    put_strike = round(current_price * (1.0 - put_distance), 2)

    # --- Put premium estimation ---
    # Rough approximation: premium ~= price * iv * sqrt(dte/365) * delta * 1.5
    put_premium_per_share = current_price * iv * sqrt_dte * put_delta * 1.5
    put_premium_total = put_premium_per_share * lot_size

    # Put metrics
    put_capital_required = put_strike * lot_size
    put_breakeven = put_strike - put_premium_per_share
    put_annualized_yield = (
        (put_premium_per_share / put_strike) * (365.0 / dte) * 100.0
        if put_strike > 0 and dte > 0
        else 0.0
    )

    # --- Call strike: above the put strike (assignment price) ---
    call_distance = call_delta * iv * sqrt_dte
    call_strike = round(put_strike * (1.0 + call_distance), 2)

    # --- Call premium estimation ---
    call_premium_per_share = put_strike * iv * sqrt_dte * call_delta * 1.5
    call_premium_total = call_premium_per_share * lot_size

    # Call metrics
    call_annualized_yield = (
        (call_premium_per_share / put_strike) * (365.0 / dte) * 100.0
        if put_strike > 0 and dte > 0
        else 0.0
    )

    # --- Full wheel metrics ---
    total_premium_per_share = put_premium_per_share + call_premium_per_share
    total_premium_total = put_premium_total + call_premium_total
    effective_cost_basis = put_strike - total_premium_per_share
    cost_reduction_pct = (
        (total_premium_per_share / put_strike) * 100.0
        if put_strike > 0
        else 0.0
    )

    # Annualized wheel yield: two cycles per total DTE period
    total_cycle_dte = dte * 2  # put cycle + call cycle
    annualized_wheel_yield = (
        (total_premium_per_share / put_strike) * (365.0 / total_cycle_dte) * 100.0
        if put_strike > 0 and total_cycle_dte > 0
        else 0.0
    )

    # Call breakeven (after both premiums collected)
    call_breakeven = put_strike - total_premium_per_share

    # --- Risk assessment ---
    max_loss = put_strike * lot_size - total_premium_total
    max_loss_scenario = (
        f"Stock goes to $0: lose ${max_loss:,.0f} "
        f"(assignment at ${put_strike:.0f} minus ${total_premium_total:,.0f} premiums)"
    )

    # Assignment probability based on delta
    pop_pct = (1.0 - put_delta) * 100.0
    if put_delta <= 0.20:
        assignment_probability = f"Low (~{100.0 - pop_pct:.0f}% chance) — conservative entry"
    elif put_delta <= 0.35:
        assignment_probability = f"Moderate (~{100.0 - pop_pct:.0f}% chance) — balanced risk/premium"
    else:
        assignment_probability = f"High (~{100.0 - pop_pct:.0f}% chance) — aggressive, higher premium"

    # Regime suitability
    regime_suitability_map = {
        1: "IDEAL — R1 low-vol mean reverting: perfect for wheel. "
           "Stock stays range-bound, premiums are consistent.",
        2: "GOOD — R2 high-vol mean reverting: higher premiums compensate for wider swings. "
           "Use wider strikes.",
        3: "RISKY — R3 low-vol trending: stock may trend away from strikes. "
           "Directional risk. Consider pausing wheel.",
        4: "AVOID — R4 high-vol trending: explosive moves create assignment risk at bad prices. "
           "Pause wheel strategy.",
    }
    regime_suitability = regime_suitability_map.get(
        regime_id, f"Unknown regime R{regime_id}"
    )

    # --- Verdict ---
    rationale: list[str] = []

    if regime_id in (1, 2):
        if put_annualized_yield > 8.0:
            verdict = "ATTRACTIVE — Wheel yields well in current regime"
            rationale.append(
                f"Put yield {put_annualized_yield:.1f}% annualized — above 8% threshold"
            )
        else:
            verdict = "ACCEPTABLE — Wheel works but yields are modest"
            rationale.append(
                f"Put yield {put_annualized_yield:.1f}% annualized — acceptable but not exciting"
            )
    elif regime_id == 3:
        verdict = "CAUTION — Trending market adds directional risk"
        rationale.append("R3 trending regime: stock may move persistently against strikes")
    else:
        verdict = "AVOID — High-vol trending regime is worst case for wheel"
        rationale.append("R4 regime: explosive moves create assignment at bad levels")

    rationale.append(
        f"Effective cost basis: ${effective_cost_basis:.2f} "
        f"(${current_price - effective_cost_basis:.2f} below current price)"
    )
    rationale.append(
        f"Total premiums reduce cost basis by {cost_reduction_pct:.1f}%"
    )

    if dividend_yield_pct > 0:
        rationale.append(
            f"After assignment, collect {dividend_yield_pct:.1f}% dividend "
            f"+ covered call premiums"
        )

    # Vs stock advantage
    discount = current_price - effective_cost_basis
    discount_pct = (discount / current_price * 100.0) if current_price > 0 else 0.0
    vs_stock_advantage = (
        f"Lower cost basis by ${discount:.2f} ({discount_pct:.1f}%) vs buying stock outright"
    )

    return WheelStrategyAnalysis(
        ticker=ticker,
        current_price=round(current_price, 2),
        put_strike=round(put_strike, 2),
        put_premium=round(put_premium_total, 2),
        put_dte=dte,
        put_annualized_yield=round(put_annualized_yield, 2),
        put_breakeven=round(put_breakeven, 2),
        put_capital_required=round(put_capital_required, 2),
        call_strike=round(call_strike, 2),
        call_premium=round(call_premium_total, 2),
        call_dte=dte,
        call_annualized_yield=round(call_annualized_yield, 2),
        call_breakeven=round(call_breakeven, 2),
        total_premium_if_wheeled=round(total_premium_total, 2),
        effective_cost_basis=round(effective_cost_basis, 2),
        cost_reduction_pct=round(cost_reduction_pct, 2),
        annualized_wheel_yield=round(annualized_wheel_yield, 2),
        max_loss_scenario=max_loss_scenario,
        assignment_probability=assignment_probability,
        regime_suitability=regime_suitability,
        verdict=verdict,
        rationale=rationale,
        vs_stock_advantage=vs_stock_advantage,
    )


# ═══════════════════════════════════════════════════════════════════
# CD8: Core Holding Entry Analysis
# ═══════════════════════════════════════════════════════════════════


def analyze_core_holding_entry(
    ticker: str,
    current_price: float,
    dividend_yield_pct: float = 0.0,
    iv: float = 0.20,
    regime_id: int = 1,
    lot_size: int = 100,
    market: str = "US",
) -> dict:
    """For a core holding, compare: outright stock, LEAP, wheel.

    Returns dict with all three analyses. India: stock only (no LEAPs).

    Args:
        ticker: Stock ticker symbol.
        current_price: Current stock price.
        dividend_yield_pct: Annual dividend yield as percentage.
        iv: Implied volatility (decimal).
        regime_id: Current regime (1-4).
        lot_size: Shares per contract.
        market: "US" or "INDIA".

    Returns:
        Dict with keys: ticker, market, stock_cost, leap, wheel.
    """
    result: dict = {"ticker": ticker, "market": market}

    # Stock is always an option
    result["stock_cost"] = current_price * lot_size

    # LEAP (US only — India options market lacks deep ITM LEAPs)
    if market.upper() == "US":
        result["leap"] = compare_leap_vs_stock(
            ticker, current_price, dividend_yield_pct,
            iv=iv, lot_size=lot_size,
        )
        result["wheel"] = analyze_wheel_strategy(
            ticker, current_price, iv=iv, regime_id=regime_id,
            dividend_yield_pct=dividend_yield_pct, lot_size=lot_size,
        )
    else:
        result["leap"] = None  # No LEAPs in India
        result["wheel"] = None  # India options too illiquid for wheel on most stocks

    return result
