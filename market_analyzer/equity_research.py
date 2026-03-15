"""Equity research — stock selection for core holdings.

Fundamental + technical analysis for stock investing across timeframes.
Covers value, growth, dividend, quality, momentum, and sector rotation strategies.
India market: stocks are primary investment due to limited options depth.

All functions are pure computation — accept fundamental data + OHLCV, return scored recommendations.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

import numpy as np
import pandas as pd
from pydantic import BaseModel


# ═══════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════


class InvestmentHorizon(StrEnum):
    LONG_TERM = "long_term"  # 6-12 months+
    MEDIUM_TERM = "medium_term"  # 1-3 months
    SHORT_TERM = "short_term"  # 1-5 days (defer to existing setups/)


class InvestmentStrategy(StrEnum):
    VALUE = "value"  # Low P/E, low P/B, high dividend yield
    GROWTH = "growth"  # High revenue/EPS growth, expanding margins
    DIVIDEND_INCOME = "dividend"  # High sustainable yield, growing dividends
    QUALITY_MOMENTUM = "quality_momentum"  # High ROE + price momentum (GARP)
    SECTOR_ROTATION = "sector_rotation"  # Overweight favored sectors
    TURNAROUND = "turnaround"  # Beaten down > 30% with improving fundamentals
    BLEND = "blend"  # Weighted combination of all


class StockRating(StrEnum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"
    NOT_RATED = "not_rated"


class FundamentalProfile(BaseModel):
    """Fundamental data for a single stock — from yfinance .info."""

    ticker: str
    name: str
    sector: str
    market_cap: float | None  # In local currency
    market_cap_category: str  # "mega", "large", "mid", "small", "micro"

    # Valuation
    pe_trailing: float | None
    pe_forward: float | None
    pb_ratio: float | None  # Price to book
    ps_ratio: float | None  # Price to sales
    peg_ratio: float | None  # P/E to growth
    ev_ebitda: float | None  # Enterprise value / EBITDA

    # Growth
    revenue_growth_yoy: float | None  # % YoY
    earnings_growth_yoy: float | None  # % YoY
    eps_trailing: float | None
    eps_forward: float | None

    # Profitability
    profit_margin: float | None  # Net margin %
    operating_margin: float | None
    roe: float | None  # Return on equity %
    roa: float | None  # Return on assets %

    # Dividend
    dividend_yield: float | None  # Annual %
    payout_ratio: float | None  # % of earnings paid as dividends

    # Balance sheet
    debt_to_equity: float | None
    current_ratio: float | None

    # Price context
    current_price: float | None
    fifty_two_week_high: float | None
    fifty_two_week_low: float | None
    from_52w_high_pct: float | None  # How far below 52-week high (negative = below)

    # Data quality
    data_available: bool = True
    missing_fields: list[str] = []


class StrategyScore(BaseModel):
    """Score for a single stock under one strategy."""

    strategy: InvestmentStrategy
    score: float  # 0-100
    rating: StockRating
    factors: list[str]  # What drove the score (human readable)
    strengths: list[str]
    risks: list[str]


class StockRecommendation(BaseModel):
    """Complete recommendation for a single stock."""

    ticker: str
    name: str
    sector: str
    market: str  # "US", "INDIA"
    horizon: InvestmentHorizon

    # Scores per strategy
    strategy_scores: list[StrategyScore]

    # Overall
    composite_score: float  # 0-100 weighted blend
    rating: StockRating
    primary_strategy: InvestmentStrategy  # Best-fit strategy for this stock

    # Fundamentals summary
    fundamental: FundamentalProfile

    # Technical entry
    entry_price: float | None  # Suggested entry (from technicals)
    stop_loss: float | None  # ATR-based stop
    target_price: float | None  # Fundamental target or technical target
    risk_reward: float | None  # target / stop distance

    # Commentary
    thesis: str  # Investment thesis (2-3 sentences)
    commentary: list[str]  # Detailed analysis points


class EquityScreenResult(BaseModel):
    """Result of screening stocks for a strategy."""

    strategy: InvestmentStrategy
    horizon: InvestmentHorizon
    market: str
    as_of_date: date
    total_screened: int
    recommendations: list[StockRecommendation]
    top_picks: list[StockRecommendation]  # Top 5-10 highest scored
    sector_allocation: dict[str, int]  # Sector -> count of picks
    summary: str
    commentary: list[str]


# ═══════════════════════════════════════════════════════════════════
# Fundamental data fetching
# ═══════════════════════════════════════════════════════════════════


def _safe_get(info: dict, key: str, default: object = None) -> object:
    """Safely get a value from yfinance info dict, converting NaN/Inf to None."""
    v = info.get(key, default)
    if v is None:
        return default
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return default
    return v


def _market_cap_category(mcap: float | None) -> str:
    """Classify market cap into size bucket."""
    if mcap is None:
        return "unknown"
    if mcap > 200e9:
        return "mega"
    if mcap > 10e9:
        return "large"
    if mcap > 2e9:
        return "mid"
    if mcap > 300e6:
        return "small"
    return "micro"


def _pct_field(info: dict, key: str) -> float | None:
    """Get a percentage field from yfinance info, converting fraction to %."""
    v = _safe_get(info, key)
    if v is None:
        return None
    try:
        return round(float(v) * 100, 2)
    except (TypeError, ValueError):
        return None


def _empty_profile(ticker: str) -> FundamentalProfile:
    """Return an empty profile when data fetch fails."""
    return FundamentalProfile(
        ticker=ticker,
        name=ticker,
        sector="unknown",
        data_available=False,
        missing_fields=["all"],
        market_cap=None,
        market_cap_category="unknown",
        pe_trailing=None,
        pe_forward=None,
        pb_ratio=None,
        ps_ratio=None,
        peg_ratio=None,
        ev_ebitda=None,
        revenue_growth_yoy=None,
        earnings_growth_yoy=None,
        eps_trailing=None,
        eps_forward=None,
        profit_margin=None,
        operating_margin=None,
        roe=None,
        roa=None,
        dividend_yield=None,
        payout_ratio=None,
        debt_to_equity=None,
        current_ratio=None,
        current_price=None,
        fifty_two_week_high=None,
        fifty_two_week_low=None,
        from_52w_high_pct=None,
    )


def fetch_fundamental_profile(ticker: str, market: str = "US") -> FundamentalProfile:
    """Fetch fundamental data from yfinance. Graceful on missing data."""
    import yfinance as yf

    # Resolve ticker for yfinance
    try:
        from market_analyzer.registry import MarketRegistry

        yf_ticker = MarketRegistry().get_instrument(ticker).yfinance_symbol
    except (KeyError, ImportError):
        yf_ticker = ticker

    try:
        info = yf.Ticker(yf_ticker).info
    except Exception:
        return _empty_profile(ticker)

    if not info or not isinstance(info, dict):
        return _empty_profile(ticker)

    mcap = _safe_get(info, "marketCap")
    price = (
        _safe_get(info, "regularMarketPrice")
        or _safe_get(info, "currentPrice")
        or _safe_get(info, "previousClose")
    )
    high_52 = _safe_get(info, "fiftyTwoWeekHigh")
    low_52 = _safe_get(info, "fiftyTwoWeekLow")
    from_high = (
        round((price - high_52) / high_52 * 100, 1)
        if price and high_52 and high_52 > 0
        else None
    )

    missing: list[str] = []
    if _safe_get(info, "trailingPE") is None:
        missing.append("pe_trailing")
    if _safe_get(info, "returnOnEquity") is None:
        missing.append("roe")
    if _safe_get(info, "dividendYield") is None:
        missing.append("dividend_yield")

    roe_val = _safe_get(info, "returnOnEquity")
    if roe_val is not None:
        roe_val = round(float(roe_val) * 100, 2)

    roa_val = _safe_get(info, "returnOnAssets")
    if roa_val is not None:
        roa_val = round(float(roa_val) * 100, 2)

    return FundamentalProfile(
        ticker=ticker,
        name=_safe_get(info, "shortName") or _safe_get(info, "longName") or ticker,
        sector=_safe_get(info, "sector") or _safe_get(info, "industry") or "unknown",
        market_cap=mcap,
        market_cap_category=_market_cap_category(mcap),
        pe_trailing=_safe_get(info, "trailingPE"),
        pe_forward=_safe_get(info, "forwardPE"),
        pb_ratio=_safe_get(info, "priceToBook"),
        ps_ratio=_safe_get(info, "priceToSalesTrailing12Months"),
        peg_ratio=_safe_get(info, "pegRatio"),
        ev_ebitda=_safe_get(info, "enterpriseToEbitda"),
        revenue_growth_yoy=_pct_field(info, "revenueGrowth"),
        earnings_growth_yoy=_pct_field(info, "earningsGrowth"),
        eps_trailing=_safe_get(info, "trailingEps"),
        eps_forward=_safe_get(info, "forwardEps"),
        profit_margin=_pct_field(info, "profitMargins"),
        operating_margin=_pct_field(info, "operatingMargins"),
        roe=roe_val,
        roa=roa_val,
        dividend_yield=_pct_field(info, "dividendYield"),
        payout_ratio=_pct_field(info, "payoutRatio"),
        debt_to_equity=_safe_get(info, "debtToEquity"),
        current_ratio=_safe_get(info, "currentRatio"),
        current_price=price,
        fifty_two_week_high=high_52,
        fifty_two_week_low=low_52,
        from_52w_high_pct=from_high,
        data_available=True,
        missing_fields=missing,
    )


# ═══════════════════════════════════════════════════════════════════
# Score-to-rating conversion
# ═══════════════════════════════════════════════════════════════════


def _score_to_rating(score: float) -> StockRating:
    """Convert numeric score (0-100) to a stock rating."""
    if score >= 75:
        return StockRating.STRONG_BUY
    if score >= 60:
        return StockRating.BUY
    if score >= 45:
        return StockRating.HOLD
    if score >= 30:
        return StockRating.SELL
    return StockRating.STRONG_SELL


# ═══════════════════════════════════════════════════════════════════
# Strategy scoring functions
# ═══════════════════════════════════════════════════════════════════


def _score_value(f: FundamentalProfile) -> StrategyScore:
    """Value investing: low P/E, low P/B, high dividend, strong balance sheet."""
    score = 50.0
    factors: list[str] = []
    strengths: list[str] = []
    risks: list[str] = []

    # P/E (lower = better for value)
    if f.pe_trailing is not None:
        if f.pe_trailing < 10:
            score += 15
            strengths.append(f"Low P/E {f.pe_trailing:.1f}")
        elif f.pe_trailing < 15:
            score += 10
            factors.append(f"Reasonable P/E {f.pe_trailing:.1f}")
        elif f.pe_trailing < 20:
            pass
        elif f.pe_trailing < 30:
            score -= 10
            factors.append(f"Elevated P/E {f.pe_trailing:.1f}")
        else:
            score -= 20
            risks.append(f"Expensive P/E {f.pe_trailing:.1f}")

    # P/B (lower = better)
    if f.pb_ratio is not None:
        if f.pb_ratio < 1.0:
            score += 10
            strengths.append(f"Below book value (P/B {f.pb_ratio:.1f})")
        elif f.pb_ratio < 2.0:
            score += 5
        elif f.pb_ratio > 5.0:
            score -= 10
            risks.append(f"High P/B {f.pb_ratio:.1f}")

    # Dividend yield
    if f.dividend_yield is not None and f.dividend_yield > 0:
        if f.dividend_yield > 4:
            score += 10
            strengths.append(f"High yield {f.dividend_yield:.1f}%")
        elif f.dividend_yield > 2:
            score += 5
            factors.append(f"Decent yield {f.dividend_yield:.1f}%")

    # Debt (lower = safer for value)
    if f.debt_to_equity is not None:
        if f.debt_to_equity < 30:
            score += 5
            strengths.append("Low debt")
        elif f.debt_to_equity > 100:
            score -= 10
            risks.append(f"High debt/equity {f.debt_to_equity:.0f}")

    # ROE (profitability check — value trap avoidance)
    if f.roe is not None:
        if f.roe > 15:
            score += 5
            factors.append(f"Good ROE {f.roe:.0f}%")
        elif f.roe < 5:
            score -= 10
            risks.append(f"Low ROE {f.roe:.0f}% — value trap risk")

    # 52-week position (buying near lows = better for value)
    if f.from_52w_high_pct is not None:
        if f.from_52w_high_pct < -30:
            score += 10
            strengths.append(f"{f.from_52w_high_pct:.0f}% from 52wk high — deep value")
        elif f.from_52w_high_pct < -15:
            score += 5

    score = max(0.0, min(100.0, score))
    return StrategyScore(
        strategy=InvestmentStrategy.VALUE,
        score=round(score, 1),
        rating=_score_to_rating(score),
        factors=factors,
        strengths=strengths,
        risks=risks,
    )


def _score_growth(f: FundamentalProfile) -> StrategyScore:
    """Growth investing: high revenue/earnings growth, expanding margins."""
    score = 50.0
    factors: list[str] = []
    strengths: list[str] = []
    risks: list[str] = []

    # Revenue growth
    if f.revenue_growth_yoy is not None:
        if f.revenue_growth_yoy > 25:
            score += 15
            strengths.append(f"Strong revenue growth {f.revenue_growth_yoy:.0f}%")
        elif f.revenue_growth_yoy > 10:
            score += 10
            factors.append(f"Good revenue growth {f.revenue_growth_yoy:.0f}%")
        elif f.revenue_growth_yoy > 0:
            pass
        else:
            score -= 15
            risks.append(f"Revenue declining {f.revenue_growth_yoy:.0f}%")

    # Earnings growth
    if f.earnings_growth_yoy is not None:
        if f.earnings_growth_yoy > 25:
            score += 15
            strengths.append(f"Strong EPS growth {f.earnings_growth_yoy:.0f}%")
        elif f.earnings_growth_yoy > 10:
            score += 10
        elif f.earnings_growth_yoy < 0:
            score -= 10
            risks.append(f"Earnings declining {f.earnings_growth_yoy:.0f}%")

    # Margins (expanding = growth sign)
    if f.profit_margin is not None:
        if f.profit_margin > 20:
            score += 10
            strengths.append(f"High margins {f.profit_margin:.0f}%")
        elif f.profit_margin > 10:
            score += 5
        elif f.profit_margin < 0:
            score -= 15
            risks.append("Unprofitable")

    # PEG ratio (growth at reasonable price)
    if f.peg_ratio is not None:
        if 0 < f.peg_ratio < 1:
            score += 10
            strengths.append(f"PEG {f.peg_ratio:.1f} — growth undervalued")
        elif f.peg_ratio > 2:
            score -= 5
            risks.append(f"PEG {f.peg_ratio:.1f} — growth overpriced")

    # Forward P/E vs trailing (improving = good)
    if (
        f.pe_forward is not None
        and f.pe_trailing is not None
        and f.pe_trailing > 0
    ):
        if f.pe_forward < f.pe_trailing * 0.85:
            score += 5
            factors.append("Forward P/E improving")

    score = max(0.0, min(100.0, score))
    return StrategyScore(
        strategy=InvestmentStrategy.GROWTH,
        score=round(score, 1),
        rating=_score_to_rating(score),
        factors=factors,
        strengths=strengths,
        risks=risks,
    )


def _score_dividend(f: FundamentalProfile) -> StrategyScore:
    """Dividend income: high sustainable yield, growing dividends, low payout."""
    score = 50.0
    factors: list[str] = []
    strengths: list[str] = []
    risks: list[str] = []

    if f.dividend_yield is not None:
        if f.dividend_yield > 5:
            score += 15
            strengths.append(f"High yield {f.dividend_yield:.1f}%")
        elif f.dividend_yield > 3:
            score += 10
            factors.append(f"Good yield {f.dividend_yield:.1f}%")
        elif f.dividend_yield > 1:
            score += 5
        else:
            score -= 20
            risks.append("Low/no dividend")
    else:
        score -= 25
        risks.append("No dividend data")

    # Payout ratio (sustainable < 70%)
    if f.payout_ratio is not None:
        if f.payout_ratio < 50:
            score += 10
            strengths.append(f"Sustainable payout {f.payout_ratio:.0f}%")
        elif f.payout_ratio < 70:
            score += 5
        elif f.payout_ratio > 90:
            score -= 10
            risks.append(f"High payout {f.payout_ratio:.0f}% — cut risk")

    # Balance sheet safety
    if f.debt_to_equity is not None and f.debt_to_equity < 50:
        score += 5
        strengths.append("Low debt supports dividend")
    if f.current_ratio is not None and f.current_ratio > 1.5:
        score += 5
        factors.append("Strong liquidity")

    # Profitability (can they keep paying?)
    if f.roe is not None and f.roe > 12:
        score += 5
        factors.append(f"ROE {f.roe:.0f}% supports dividend growth")

    score = max(0.0, min(100.0, score))
    return StrategyScore(
        strategy=InvestmentStrategy.DIVIDEND_INCOME,
        score=round(score, 1),
        rating=_score_to_rating(score),
        factors=factors,
        strengths=strengths,
        risks=risks,
    )


def _score_quality_momentum(
    f: FundamentalProfile, tech_signal_score: float = 0.0
) -> StrategyScore:
    """Quality + momentum (GARP): high ROE + positive price momentum."""
    score = 50.0
    factors: list[str] = []
    strengths: list[str] = []
    risks: list[str] = []

    # Quality: ROE
    if f.roe is not None:
        if f.roe > 20:
            score += 15
            strengths.append(f"Excellent ROE {f.roe:.0f}%")
        elif f.roe > 15:
            score += 10
            factors.append(f"Good ROE {f.roe:.0f}%")
        elif f.roe > 10:
            score += 5
        else:
            score -= 10
            risks.append(f"Low ROE {f.roe:.0f}%")

    # Quality: margins
    if f.operating_margin is not None and f.operating_margin > 15:
        score += 5
        factors.append(f"Strong operating margin {f.operating_margin:.0f}%")

    # Quality: low debt
    if f.debt_to_equity is not None and f.debt_to_equity < 50:
        score += 5
        strengths.append("Clean balance sheet")

    # Momentum: technical signal score (-1 to +1)
    if tech_signal_score > 0.3:
        score += 10
        strengths.append("Strong price momentum")
    elif tech_signal_score > 0:
        score += 5
        factors.append("Positive momentum")
    elif tech_signal_score < -0.3:
        score -= 10
        risks.append("Negative momentum — wait for reversal")

    # Growth at reasonable price
    if f.peg_ratio is not None and 0 < f.peg_ratio < 1.5:
        score += 5
        strengths.append(f"GARP: PEG {f.peg_ratio:.1f}")

    score = max(0.0, min(100.0, score))
    return StrategyScore(
        strategy=InvestmentStrategy.QUALITY_MOMENTUM,
        score=round(score, 1),
        rating=_score_to_rating(score),
        factors=factors,
        strengths=strengths,
        risks=risks,
    )


def _score_turnaround(f: FundamentalProfile) -> StrategyScore:
    """Turnaround: beaten down > 30% from high with improving fundamentals."""
    score = 30.0  # Start lower — turnarounds are risky
    factors: list[str] = []
    strengths: list[str] = []
    risks: list[str] = ["Turnaround strategy inherently risky — size small"]

    # Must be significantly down from highs
    if f.from_52w_high_pct is not None:
        if f.from_52w_high_pct < -40:
            score += 20
            strengths.append(
                f"Down {f.from_52w_high_pct:.0f}% — deep discount"
            )
        elif f.from_52w_high_pct < -30:
            score += 15
            factors.append(f"Down {f.from_52w_high_pct:.0f}% from high")
        elif f.from_52w_high_pct < -15:
            score += 5
        else:
            score -= 20
            risks.append("Not enough discount for turnaround play")

    # Improving earnings
    if f.earnings_growth_yoy is not None and f.earnings_growth_yoy > 0:
        score += 15
        strengths.append(
            f"Earnings turning positive ({f.earnings_growth_yoy:.0f}%)"
        )

    # Forward P/E lower than trailing (improving outlook)
    if f.pe_forward is not None and f.pe_trailing is not None:
        if f.pe_forward < f.pe_trailing * 0.8:
            score += 10
            strengths.append("Forward P/E improving significantly")

    # Balance sheet must be survivable
    if f.current_ratio is not None and f.current_ratio > 1.0:
        score += 5
        factors.append("Adequate liquidity")
    elif f.current_ratio is not None and f.current_ratio < 0.8:
        score -= 15
        risks.append(
            f"Low current ratio {f.current_ratio:.1f} — bankruptcy risk"
        )

    if f.debt_to_equity is not None and f.debt_to_equity > 200:
        score -= 15
        risks.append(
            f"Very high debt {f.debt_to_equity:.0f} — survival concern"
        )

    score = max(0.0, min(100.0, score))
    return StrategyScore(
        strategy=InvestmentStrategy.TURNAROUND,
        score=round(score, 1),
        rating=_score_to_rating(score),
        factors=factors,
        strengths=strengths,
        risks=risks,
    )


def _score_sector_rotation(
    f: FundamentalProfile,
    favored_sectors: list[str] | None = None,
) -> StrategyScore:
    """Sector rotation: overweight favored sectors, underweight lagging ones."""
    score = 50.0
    factors: list[str] = []
    strengths: list[str] = []
    risks: list[str] = []

    if favored_sectors is None:
        favored_sectors = []

    sector_lower = f.sector.lower() if f.sector else ""

    # Sector alignment
    if favored_sectors:
        matched = any(fav.lower() in sector_lower for fav in favored_sectors)
        if matched:
            score += 15
            strengths.append(f"In favored sector: {f.sector}")
        else:
            score -= 10
            risks.append(f"Sector {f.sector} not in rotation focus")
    else:
        factors.append("No sector rotation signal — scoring on fundamentals only")

    # Quality within sector (ROE + margins)
    if f.roe is not None and f.roe > 15:
        score += 10
        factors.append(f"Sector leader: ROE {f.roe:.0f}%")
    if f.revenue_growth_yoy is not None and f.revenue_growth_yoy > 10:
        score += 5
        factors.append(f"Growing within sector ({f.revenue_growth_yoy:.0f}%)")

    # Market cap (prefer larger within sector for rotation)
    if f.market_cap_category in ("mega", "large"):
        score += 5
        factors.append(f"{f.market_cap_category}-cap — sector bellwether")

    score = max(0.0, min(100.0, score))
    return StrategyScore(
        strategy=InvestmentStrategy.SECTOR_ROTATION,
        score=round(score, 1),
        rating=_score_to_rating(score),
        factors=factors,
        strengths=strengths,
        risks=risks,
    )


# ═══════════════════════════════════════════════════════════════════
# Technical signal computation
# ═══════════════════════════════════════════════════════════════════


def _compute_tech_signal(ohlcv: pd.DataFrame) -> float:
    """Compute a technical momentum signal score from OHLCV data.

    Returns a value roughly in [-1, +1]:
      > 0.3 = strong bullish momentum
      < -0.3 = strong bearish momentum
    """
    if ohlcv is None or len(ohlcv) < 50:
        return 0.0

    close = ohlcv["Close"]

    signals: list[float] = []

    # SMA crossover (20/50)
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    if not sma20.empty and not sma50.empty:
        latest_20 = float(sma20.iloc[-1])
        latest_50 = float(sma50.iloc[-1])
        if latest_50 > 0:
            cross = (latest_20 - latest_50) / latest_50
            signals.append(max(-1.0, min(1.0, cross * 20)))  # scale to [-1, 1]

    # RSI signal
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    if not rsi.empty and not np.isnan(float(rsi.iloc[-1])):
        rsi_val = float(rsi.iloc[-1])
        # RSI centered: >50 bullish, <50 bearish
        signals.append((rsi_val - 50) / 50)

    # Price vs 200-day SMA
    if len(close) >= 200:
        sma200 = float(close.rolling(200).mean().iloc[-1])
        if sma200 > 0:
            above_200 = (float(close.iloc[-1]) - sma200) / sma200
            signals.append(max(-1.0, min(1.0, above_200 * 10)))

    if not signals:
        return 0.0
    return sum(signals) / len(signals)


def _compute_entry_levels(
    ohlcv: pd.DataFrame, horizon: InvestmentHorizon
) -> tuple[float | None, float | None, float | None]:
    """Compute entry price, stop loss, and target from OHLCV data.

    Returns (entry_price, stop_loss, target_price).
    """
    if ohlcv is None or len(ohlcv) < 14:
        return None, None, None

    close = ohlcv["Close"]
    high = ohlcv["High"]
    low = ohlcv["Low"]
    price = float(close.iloc[-1])

    # ATR-14
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1]) if len(tr) >= 14 else price * 0.02

    entry_price = price
    stop_loss = round(price - 2.0 * atr, 2)

    if horizon == InvestmentHorizon.LONG_TERM:
        target_price = round(price + 4.0 * atr, 2)  # 2:1 R:R
    else:
        target_price = round(price + 3.0 * atr, 2)  # 1.5:1 R:R

    return entry_price, stop_loss, target_price


# ═══════════════════════════════════════════════════════════════════
# Main recommendation function
# ═══════════════════════════════════════════════════════════════════


def analyze_stock(
    ticker: str,
    ohlcv: pd.DataFrame | None = None,
    fundamental: FundamentalProfile | None = None,
    horizon: InvestmentHorizon = InvestmentHorizon.LONG_TERM,
    market: str = "US",
    favored_sectors: list[str] | None = None,
) -> StockRecommendation:
    """Complete stock analysis — fundamentals + technicals + multi-strategy scoring.

    Args:
        ticker: Stock ticker symbol.
        ohlcv: Optional OHLCV DataFrame. If provided, enables technical signals
               and entry/stop/target computation.
        fundamental: Pre-fetched fundamental profile. If None, fetches from yfinance.
        horizon: Investment horizon (long_term or medium_term).
        market: Market identifier ("US" or "INDIA").
        favored_sectors: Optional list of sectors for sector rotation scoring.

    Returns:
        StockRecommendation with composite score, per-strategy scores, and thesis.
    """
    # Fetch fundamentals if not provided
    if fundamental is None:
        fundamental = fetch_fundamental_profile(ticker, market)

    # Technical signal score from OHLCV
    tech_signal = 0.0
    entry_price = fundamental.current_price
    stop_loss: float | None = None
    target_price: float | None = None

    if ohlcv is not None and len(ohlcv) >= 20:
        tech_signal = _compute_tech_signal(ohlcv)
        entry_price, stop_loss, target_price = _compute_entry_levels(ohlcv, horizon)
        if entry_price is None:
            entry_price = fundamental.current_price

    # Score across all strategies
    value_score = _score_value(fundamental)
    growth_score = _score_growth(fundamental)
    dividend_score = _score_dividend(fundamental)
    quality_score = _score_quality_momentum(fundamental, tech_signal)
    turnaround_score = _score_turnaround(fundamental)
    sector_score = _score_sector_rotation(fundamental, favored_sectors)

    strategy_scores = [
        value_score,
        growth_score,
        dividend_score,
        quality_score,
        turnaround_score,
        sector_score,
    ]

    # Composite: weighted by horizon
    if horizon == InvestmentHorizon.LONG_TERM:
        # Fundamental-heavy
        weights = {
            InvestmentStrategy.VALUE: 0.25,
            InvestmentStrategy.GROWTH: 0.20,
            InvestmentStrategy.DIVIDEND_INCOME: 0.15,
            InvestmentStrategy.QUALITY_MOMENTUM: 0.20,
            InvestmentStrategy.TURNAROUND: 0.10,
            InvestmentStrategy.SECTOR_ROTATION: 0.10,
        }
    else:
        # Technical-heavy for medium term
        weights = {
            InvestmentStrategy.VALUE: 0.10,
            InvestmentStrategy.GROWTH: 0.15,
            InvestmentStrategy.DIVIDEND_INCOME: 0.10,
            InvestmentStrategy.QUALITY_MOMENTUM: 0.35,
            InvestmentStrategy.TURNAROUND: 0.15,
            InvestmentStrategy.SECTOR_ROTATION: 0.15,
        }

    composite = sum(
        s.score * weights.get(s.strategy, 0.0) for s in strategy_scores
    )

    # Primary strategy: highest individual score
    best = max(strategy_scores, key=lambda s: s.score)

    # Risk:Reward
    rr: float | None = None
    if stop_loss and target_price and entry_price:
        risk = entry_price - stop_loss
        reward = target_price - entry_price
        rr = round(reward / risk, 2) if risk > 0 else None

    # Thesis
    thesis_parts = [f"{fundamental.name} ({ticker}):"]
    if best.strategy == InvestmentStrategy.VALUE:
        pe_desc = "cheap" if (fundamental.pe_trailing or 99) < 15 else "reasonable"
        thesis_parts.append(f"Value play — {pe_desc} valuation.")
    elif best.strategy == InvestmentStrategy.GROWTH:
        thesis_parts.append(
            f"Growth story — revenue growing {fundamental.revenue_growth_yoy or 0:.0f}%."
        )
    elif best.strategy == InvestmentStrategy.DIVIDEND_INCOME:
        thesis_parts.append(
            f"Income play — {fundamental.dividend_yield or 0:.1f}% yield."
        )
    elif best.strategy == InvestmentStrategy.QUALITY_MOMENTUM:
        thesis_parts.append(
            f"Quality + momentum — ROE {fundamental.roe or 0:.0f}%, positive trend."
        )
    elif best.strategy == InvestmentStrategy.TURNAROUND:
        thesis_parts.append(
            f"Turnaround — {fundamental.from_52w_high_pct or 0:.0f}% from high, fundamentals improving."
        )
    elif best.strategy == InvestmentStrategy.SECTOR_ROTATION:
        thesis_parts.append(
            f"Sector rotation play — {fundamental.sector} in focus."
        )

    if best.strengths:
        thesis_parts.append(best.strengths[0] + ".")
    if best.risks:
        thesis_parts.append(f"Key risk: {best.risks[0]}.")

    commentary: list[str] = []
    for s in strategy_scores:
        commentary.append(f"{s.strategy.value}: {s.score:.0f}/100 ({s.rating.value})")
        if s.strengths:
            commentary.append(f"  + {'; '.join(s.strengths[:2])}")
        if s.risks:
            commentary.append(f"  - {'; '.join(s.risks[:2])}")

    return StockRecommendation(
        ticker=ticker,
        name=fundamental.name,
        sector=fundamental.sector,
        market=market,
        horizon=horizon,
        strategy_scores=strategy_scores,
        composite_score=round(composite, 1),
        rating=_score_to_rating(composite),
        primary_strategy=best.strategy,
        fundamental=fundamental,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target_price=target_price,
        risk_reward=rr,
        thesis=" ".join(thesis_parts),
        commentary=commentary,
    )


# ═══════════════════════════════════════════════════════════════════
# Screening function
# ═══════════════════════════════════════════════════════════════════


def screen_stocks(
    tickers: list[str],
    ohlcv_data: dict[str, pd.DataFrame] | None = None,
    strategy: InvestmentStrategy | None = None,
    horizon: InvestmentHorizon = InvestmentHorizon.LONG_TERM,
    market: str = "US",
    top_n: int = 10,
    min_score: float = 55.0,
    favored_sectors: list[str] | None = None,
) -> EquityScreenResult:
    """Screen a universe of stocks and return ranked recommendations.

    Args:
        tickers: List of ticker symbols to screen.
        ohlcv_data: Optional dict mapping ticker -> OHLCV DataFrame for technical signals.
        strategy: Filter by specific strategy. If None, uses composite (blend) scoring.
        horizon: Investment horizon for weight tuning.
        market: Market identifier ("US" or "INDIA").
        top_n: Number of top picks to highlight.
        min_score: Minimum score to include in recommendations.
        favored_sectors: Optional list of favored sectors for sector rotation scoring.

    Returns:
        EquityScreenResult with ranked recommendations and top picks.
    """
    today = date.today()
    recommendations: list[StockRecommendation] = []

    for ticker in tickers:
        try:
            ohlcv = ohlcv_data.get(ticker) if ohlcv_data else None
            rec = analyze_stock(
                ticker,
                ohlcv,
                horizon=horizon,
                market=market,
                favored_sectors=favored_sectors,
            )

            # Filter by strategy score if specific strategy requested
            if strategy and strategy != InvestmentStrategy.BLEND:
                strat_score = next(
                    (s for s in rec.strategy_scores if s.strategy == strategy),
                    None,
                )
                if strat_score and strat_score.score >= min_score:
                    recommendations.append(rec)
            elif rec.composite_score >= min_score:
                recommendations.append(rec)
        except Exception:
            continue  # Skip failures gracefully

    # Sort by composite score (or strategy-specific score)
    if strategy and strategy != InvestmentStrategy.BLEND:
        recommendations.sort(
            key=lambda r: next(
                (
                    s.score
                    for s in r.strategy_scores
                    if s.strategy == strategy
                ),
                0,
            ),
            reverse=True,
        )
    else:
        recommendations.sort(key=lambda r: r.composite_score, reverse=True)

    top_picks = recommendations[:top_n]

    # Sector allocation
    sectors: dict[str, int] = {}
    for r in top_picks:
        sectors[r.sector] = sectors.get(r.sector, 0) + 1

    strat_name = strategy.value if strategy else "blend"
    summary = (
        f"Screened {len(tickers)} stocks | "
        f"{len(recommendations)} passed min score {min_score} | "
        f"Top {len(top_picks)} picks | "
        f"Strategy: {strat_name} | Horizon: {horizon.value}"
    )

    commentary = [
        f"Equity Screen — {today} ({market}, {strat_name}, {horizon.value})"
    ]
    if top_picks:
        commentary.append(
            f"Top pick: {top_picks[0].ticker} "
            f"({top_picks[0].composite_score:.0f}/100) — "
            f"{top_picks[0].thesis[:80]}"
        )
    if sectors:
        top_sectors = sorted(sectors.items(), key=lambda x: -x[1])[:3]
        commentary.append(
            f"Sector mix: {', '.join(f'{k}:{v}' for k, v in top_sectors)}"
        )

    return EquityScreenResult(
        strategy=strategy or InvestmentStrategy.BLEND,
        horizon=horizon,
        market=market,
        as_of_date=today,
        total_screened=len(tickers),
        recommendations=recommendations,
        top_picks=top_picks,
        sector_allocation=sectors,
        summary=summary,
        commentary=commentary,
    )
