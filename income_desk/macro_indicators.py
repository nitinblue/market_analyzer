"""Macro economic indicators from market data.

Tracks bond market, yield curve, dollar strength, credit spreads,
and inflation expectations using freely available ETF/index data.

All functions are pure computation — accept OHLCV DataFrames from DataService.
No external API calls (FRED, etc.) — everything from yfinance-compatible tickers.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

import numpy as np
import pandas as pd
from pydantic import BaseModel


class MacroTrend(StrEnum):
    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"


class MacroRiskLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    ELEVATED = "elevated"
    HIGH = "high"


class BondMarketIndicator(BaseModel):
    """US bond market health from TNX and TLT."""

    tnx_yield: float  # 10Y yield (%)
    tnx_change_20d: float  # 20-day change in yield (basis points)
    tnx_trend: MacroTrend  # Rising/falling/stable
    tlt_return_20d_pct: float  # Long bond 20-day return
    tlt_trend: MacroTrend  # Rising (yields falling) / Falling (yields rising)
    interpretation: str  # "Yields rising — bearish for equity valuation"


class CreditSpreadIndicator(BaseModel):
    """Credit spread proxy from HYG vs TLT."""

    hyg_tlt_ratio: float  # HYG/TLT ratio — lower = wider spreads = more fear
    ratio_change_20d: float  # 20-day change in ratio
    ratio_percentile_60d: float  # Where current ratio sits in 60-day range (0-100)
    spread_trend: MacroTrend  # Widening (fear) / Tightening (greed)
    risk_level: MacroRiskLevel  # Based on speed of spread widening
    interpretation: str


class DollarStrengthIndicator(BaseModel):
    """USD strength from UUP or dollar proxy."""

    uup_return_20d_pct: float  # Dollar ETF 20-day return
    dollar_trend: MacroTrend
    impact_on_india: str  # "Strong dollar -> INR pressure -> India equity headwind"
    impact_on_us: str  # "Strong dollar -> multinational earnings headwind"
    interpretation: str


class InflationExpectationIndicator(BaseModel):
    """Inflation expectations from TIP vs TLT spread."""

    tip_tlt_ratio: float  # TIP/TLT — rising = inflation expectations rising
    ratio_change_20d: float
    inflation_trend: MacroTrend
    interpretation: str


class MacroIndicatorDashboard(BaseModel):
    """Complete macro economic indicator dashboard."""

    as_of_date: date
    market: str  # "US" or "INDIA"
    bond_market: BondMarketIndicator | None
    credit_spreads: CreditSpreadIndicator | None
    dollar_strength: DollarStrengthIndicator | None
    inflation_expectations: InflationExpectationIndicator | None
    overall_risk: MacroRiskLevel
    signals: list[str]  # Key takeaways
    trading_impact: str  # What this means for options trading
    commentary: list[str] = []


def _compute_trend(series: pd.Series, window: int = 20) -> MacroTrend:
    """Determine if a series is trending up, down, or flat."""
    if len(series) < window:
        return MacroTrend.STABLE
    recent = series.tail(window)
    change = (
        (recent.iloc[-1] - recent.iloc[0]) / abs(recent.iloc[0])
        if recent.iloc[0] != 0
        else 0
    )
    if change > 0.02:
        return MacroTrend.RISING
    elif change < -0.02:
        return MacroTrend.FALLING
    return MacroTrend.STABLE


def _percentile_in_window(series: pd.Series, window: int = 60) -> float:
    """Where current value sits in recent window (0-100)."""
    recent = series.tail(window).dropna()
    if len(recent) < 5:
        return 50.0
    current = recent.iloc[-1]
    return round(float((recent < current).sum() / len(recent) * 100), 1)


def compute_bond_market(
    tnx_ohlcv: pd.DataFrame | None,
    tlt_ohlcv: pd.DataFrame | None,
) -> BondMarketIndicator | None:
    """Compute bond market indicators from TNX (10Y yield) and TLT (long bond ETF)."""
    if tnx_ohlcv is None or len(tnx_ohlcv) < 20:
        return None

    tnx_close = tnx_ohlcv["Close"]
    tnx_yield = float(tnx_close.iloc[-1])
    tnx_20d_ago = float(tnx_close.iloc[-20]) if len(tnx_close) >= 20 else tnx_yield
    tnx_change_bp = (tnx_yield - tnx_20d_ago) * 100  # Convert to basis points
    tnx_trend = _compute_trend(tnx_close)

    tlt_return = 0.0
    tlt_trend = MacroTrend.STABLE
    if tlt_ohlcv is not None and len(tlt_ohlcv) >= 20:
        tlt_close = tlt_ohlcv["Close"]
        tlt_return = float((tlt_close.iloc[-1] / tlt_close.iloc[-20] - 1) * 100)
        tlt_trend = _compute_trend(tlt_close)

    if tnx_trend == MacroTrend.RISING:
        interp = (
            f"10Y yield at {tnx_yield:.2f}% and rising (+{tnx_change_bp:.0f}bp/20d)"
            " — tightening financial conditions, headwind for equity valuations"
        )
    elif tnx_trend == MacroTrend.FALLING:
        interp = (
            f"10Y yield at {tnx_yield:.2f}% and falling ({tnx_change_bp:.0f}bp/20d)"
            " — easing financial conditions, supportive for risk assets"
        )
    else:
        interp = f"10Y yield stable at {tnx_yield:.2f}% — neutral macro backdrop"

    return BondMarketIndicator(
        tnx_yield=round(tnx_yield, 3),
        tnx_change_20d=round(tnx_change_bp, 1),
        tnx_trend=tnx_trend,
        tlt_return_20d_pct=round(tlt_return, 2),
        tlt_trend=tlt_trend,
        interpretation=interp,
    )


def compute_credit_spreads(
    hyg_ohlcv: pd.DataFrame | None,
    tlt_ohlcv: pd.DataFrame | None,
) -> CreditSpreadIndicator | None:
    """Compute credit spread proxy from HYG/TLT ratio."""
    if hyg_ohlcv is None or tlt_ohlcv is None:
        return None
    if len(hyg_ohlcv) < 20 or len(tlt_ohlcv) < 20:
        return None

    hyg = hyg_ohlcv["Close"]
    tlt = tlt_ohlcv["Close"]

    # Align dates
    aligned = pd.concat([hyg, tlt], axis=1, join="inner")
    aligned.columns = ["hyg", "tlt"]
    aligned = aligned.dropna()

    if len(aligned) < 20:
        return None

    ratio = aligned["hyg"] / aligned["tlt"]
    current_ratio = float(ratio.iloc[-1])
    ratio_20d_ago = float(ratio.iloc[-20]) if len(ratio) >= 20 else current_ratio
    change = current_ratio - ratio_20d_ago

    percentile = _percentile_in_window(ratio, 60)
    trend = _compute_trend(ratio)

    # Risk level based on percentile (lower ratio = wider spreads = more risk)
    if percentile < 10:
        risk = MacroRiskLevel.HIGH
    elif percentile < 25:
        risk = MacroRiskLevel.ELEVATED
    elif percentile < 50:
        risk = MacroRiskLevel.MODERATE
    else:
        risk = MacroRiskLevel.LOW

    if trend == MacroTrend.FALLING:
        interp = (
            "Credit spreads widening (HYG underperforming TLT)"
            " — risk aversion increasing. Reduce premium selling."
        )
    elif trend == MacroTrend.RISING:
        interp = (
            "Credit spreads tightening"
            " — risk appetite returning. Favorable for income strategies."
        )
    else:
        interp = "Credit spreads stable — neutral credit environment."

    return CreditSpreadIndicator(
        hyg_tlt_ratio=round(current_ratio, 4),
        ratio_change_20d=round(change, 4),
        ratio_percentile_60d=percentile,
        spread_trend=trend,
        risk_level=risk,
        interpretation=interp,
    )


def compute_dollar_strength(
    uup_ohlcv: pd.DataFrame | None,
) -> DollarStrengthIndicator | None:
    """Compute USD strength from UUP (dollar bull ETF)."""
    if uup_ohlcv is None or len(uup_ohlcv) < 20:
        return None

    close = uup_ohlcv["Close"]
    ret_20d = float((close.iloc[-1] / close.iloc[-20] - 1) * 100)
    trend = _compute_trend(close)

    india_impact = (
        "Strong dollar pressures INR — India equity headwind"
        if trend == MacroTrend.RISING
        else (
            "Weak dollar supports INR — India equity tailwind"
            if trend == MacroTrend.FALLING
            else "Dollar stable — neutral FX impact"
        )
    )

    us_impact = (
        "Strong dollar hurts multinational earnings"
        if trend == MacroTrend.RISING
        else (
            "Weak dollar boosts multinational earnings"
            if trend == MacroTrend.FALLING
            else "Dollar stable — neutral earnings impact"
        )
    )

    interp = (
        f"Dollar {'strengthening' if trend == MacroTrend.RISING else 'weakening' if trend == MacroTrend.FALLING else 'stable'}"
        f" ({ret_20d:+.1f}% / 20d)"
    )

    return DollarStrengthIndicator(
        uup_return_20d_pct=round(ret_20d, 2),
        dollar_trend=trend,
        impact_on_india=india_impact,
        impact_on_us=us_impact,
        interpretation=interp,
    )


def compute_inflation_expectations(
    tip_ohlcv: pd.DataFrame | None,
    tlt_ohlcv: pd.DataFrame | None,
) -> InflationExpectationIndicator | None:
    """Compute inflation expectations from TIP/TLT ratio (breakeven inflation proxy)."""
    if tip_ohlcv is None or tlt_ohlcv is None:
        return None
    if len(tip_ohlcv) < 20 or len(tlt_ohlcv) < 20:
        return None

    tip = tip_ohlcv["Close"]
    tlt = tlt_ohlcv["Close"]

    aligned = pd.concat([tip, tlt], axis=1, join="inner").dropna()
    aligned.columns = ["tip", "tlt"]

    if len(aligned) < 20:
        return None

    ratio = aligned["tip"] / aligned["tlt"]
    current = float(ratio.iloc[-1])
    prev = float(ratio.iloc[-20]) if len(ratio) >= 20 else current
    change = current - prev
    trend = _compute_trend(ratio)

    if trend == MacroTrend.RISING:
        interp = (
            "Inflation expectations rising (TIP outperforming TLT)"
            " — Fed may stay hawkish, headwind for duration-sensitive strategies"
        )
    elif trend == MacroTrend.FALLING:
        interp = (
            "Inflation expectations falling"
            " — disinflation trend supports risk assets and longer-duration plays"
        )
    else:
        interp = "Inflation expectations stable — neutral for strategy selection"

    return InflationExpectationIndicator(
        tip_tlt_ratio=round(current, 4),
        ratio_change_20d=round(change, 4),
        inflation_trend=trend,
        interpretation=interp,
    )


def compute_macro_dashboard(
    tnx_ohlcv: pd.DataFrame | None = None,
    tlt_ohlcv: pd.DataFrame | None = None,
    hyg_ohlcv: pd.DataFrame | None = None,
    uup_ohlcv: pd.DataFrame | None = None,
    tip_ohlcv: pd.DataFrame | None = None,
    market: str = "US",
) -> MacroIndicatorDashboard:
    """Compute complete macro indicator dashboard.

    All inputs are optional — dashboard degrades gracefully.
    DataService fetches the data; this function just computes.
    """
    today = date.today()

    bond = compute_bond_market(tnx_ohlcv, tlt_ohlcv)
    credit = compute_credit_spreads(hyg_ohlcv, tlt_ohlcv)
    dollar = compute_dollar_strength(uup_ohlcv)
    inflation = compute_inflation_expectations(tip_ohlcv, tlt_ohlcv)

    # Overall risk
    risk_scores: list[int] = []
    signals: list[str] = []

    if bond:
        signals.append(bond.interpretation)
        if bond.tnx_trend == MacroTrend.RISING and bond.tnx_change_20d > 20:
            risk_scores.append(3)  # HIGH
        elif bond.tnx_trend == MacroTrend.RISING:
            risk_scores.append(2)
        else:
            risk_scores.append(1)

    if credit:
        signals.append(credit.interpretation)
        risk_scores.append(
            {"low": 0, "moderate": 1, "elevated": 2, "high": 3}[credit.risk_level]
        )

    if dollar:
        signals.append(dollar.interpretation)
        if dollar.dollar_trend == MacroTrend.RISING and dollar.uup_return_20d_pct > 2:
            risk_scores.append(2)
        else:
            risk_scores.append(1)

    if inflation:
        signals.append(inflation.interpretation)

    avg_risk = sum(risk_scores) / len(risk_scores) if risk_scores else 1
    if avg_risk >= 2.5:
        overall = MacroRiskLevel.HIGH
    elif avg_risk >= 1.5:
        overall = MacroRiskLevel.ELEVATED
    elif avg_risk >= 0.5:
        overall = MacroRiskLevel.MODERATE
    else:
        overall = MacroRiskLevel.LOW

    # Trading impact
    if overall == MacroRiskLevel.HIGH:
        impact = (
            "Macro headwinds strong — reduce position sizes, favor defined risk,"
            " avoid aggressive theta selling"
        )
    elif overall == MacroRiskLevel.ELEVATED:
        impact = (
            "Macro caution — tighten stops, favor shorter DTE,"
            " prefer cash-settled index options"
        )
    elif overall == MacroRiskLevel.MODERATE:
        impact = "Macro neutral — normal trading parameters apply"
    else:
        impact = (
            "Macro supportive — favorable for income strategies"
            " and longer-duration plays"
        )

    commentary = [f"Macro dashboard as of {today} ({market})"]
    if bond:
        commentary.append(
            f"10Y yield: {bond.tnx_yield:.2f}%"
            f" ({bond.tnx_trend}, {bond.tnx_change_20d:+.0f}bp/20d)"
        )
    if credit:
        commentary.append(
            f"Credit spreads: {credit.spread_trend}"
            f" (HYG/TLT at {credit.ratio_percentile_60d:.0f}th percentile)"
        )
    if dollar:
        commentary.append(
            f"Dollar: {dollar.dollar_trend}"
            f" ({dollar.uup_return_20d_pct:+.1f}%/20d)"
        )
    if inflation:
        commentary.append(f"Inflation expectations: {inflation.inflation_trend}")
    commentary.append(f"Overall macro risk: {overall}")

    return MacroIndicatorDashboard(
        as_of_date=today,
        market=market,
        bond_market=bond,
        credit_spreads=credit,
        dollar_strength=dollar,
        inflation_expectations=inflation,
        overall_risk=overall,
        signals=signals,
        trading_impact=impact,
        commentary=commentary,
    )
