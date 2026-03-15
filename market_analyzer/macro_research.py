"""Comprehensive macro research — asset scorecards, correlations, regime, sentiment.

Covers US + India across equities, bonds, commodities, currencies, volatility.
Generates human-readable commentary alongside quantitative metrics.
All inputs are DataFrames — caller (DataService or eTrading) fetches the data.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

import numpy as np
import pandas as pd
from pydantic import BaseModel


# ═══════════════════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════════════════


class AssetClass(StrEnum):
    EQUITY = "equity"
    BOND = "bond"
    COMMODITY = "commodity"
    CURRENCY = "currency"
    VOLATILITY = "volatility"
    CREDIT = "credit"


class TrendSignal(StrEnum):
    STRONG_BULLISH = "strong_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    STRONG_BEARISH = "strong_bearish"


class AssetScore(BaseModel):
    """Scorecard for a single asset across one timeframe."""

    ticker: str
    name: str
    asset_class: AssetClass
    timeframe: str  # "daily", "weekly", "monthly"
    # Price data
    current_price: float
    period_return_pct: float
    period_high: float
    period_low: float
    # Trend
    trend: TrendSignal
    vs_sma20_pct: float
    vs_sma50_pct: float
    # Momentum
    rsi: float
    momentum_desc: str  # "strong", "moderate", "weak", "exhausted"
    # Volatility
    atr_pct: float
    volatility_regime: str  # "high", "normal", "low"
    # Position in range
    range_position_pct: float  # Where price sits in period range (0=low, 100=high)
    fifty_two_week_pct: float | None  # Position in 52-week range
    # Signal
    signal: str  # "strong_buy", "buy", "hold", "sell", "strong_sell"
    signal_score: float  # -1 to +1
    # Commentary
    commentary: str


class CorrelationPair(BaseModel):
    """Correlation between two assets."""

    ticker_a: str
    ticker_b: str
    correlation_20d: float
    correlation_60d: float
    diverging: bool  # Short-term correlation very different from long-term
    interpretation: str


class SentimentDashboard(BaseModel):
    """Market sentiment from multiple indicators."""

    vix_level: float
    vix_trend: str  # "rising", "falling", "stable"
    vix_percentile_60d: float  # Where VIX sits in last 60 days
    vix_term_structure: str  # "contango" (normal), "flat", "backwardation" (fear)
    vix_term_ratio: float  # VIX/VIX3M
    india_vix: float | None
    gold_silver_ratio: float | None  # High = fear
    copper_gold_ratio: float | None  # Rising = growth
    equity_risk_premium: float | None  # Earnings yield - 10Y yield
    credit_spread_trend: str  # "widening" (fear), "tightening" (greed), "stable"
    overall_sentiment: str  # "extreme_fear", "fear", "neutral", "greed", "extreme_greed"
    sentiment_score: float  # -1 (extreme fear) to +1 (extreme greed)
    commentary: list[str]


class MacroRegime(StrEnum):
    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"
    STAGFLATION = "stagflation"
    REFLATION = "reflation"
    DEFLATIONARY = "deflationary"
    TRANSITION = "transition"


class RegimeClassification(BaseModel):
    """Current macro regime with evidence."""

    regime: MacroRegime
    confidence: float  # 0-1
    evidence: list[str]  # What's driving this classification
    position_size_factor: float  # 0-1 recommended scaling
    favor_sectors: list[str]
    avoid_sectors: list[str]
    trading_impact: str


class IndiaResearchContext(BaseModel):
    """India-specific macro context."""

    india_vix: float | None
    india_vix_trend: str
    nifty_spy_correlation_20d: float | None
    usd_inr_trend: str  # From UUP as proxy
    fii_flow_signal: str  # "inflow" / "outflow" / "neutral" (from EEM vs NIFTY)
    banknifty_vs_nifty: str  # "banking leading" / "banking lagging" / "in sync"
    commentary: list[str]


# ═══════════════════════════════════════════════════════════════════════════════
# Asset Research Tickers
# ═══════════════════════════════════════════════════════════════════════════════

RESEARCH_ASSETS: dict[str, tuple[str, AssetClass]] = {
    # US Equity
    "SPY": ("S&P 500", AssetClass.EQUITY),
    "QQQ": ("Nasdaq 100", AssetClass.EQUITY),
    "IWM": ("Russell 2000", AssetClass.EQUITY),
    "DIA": ("Dow Jones", AssetClass.EQUITY),
    # India Equity
    "^NSEI": ("NIFTY 50", AssetClass.EQUITY),
    "^NSEBANK": ("Bank NIFTY", AssetClass.EQUITY),
    # Global
    "EFA": ("Developed Markets", AssetClass.EQUITY),
    "EEM": ("Emerging Markets", AssetClass.EQUITY),
    # Commodities
    "GLD": ("Gold", AssetClass.COMMODITY),
    "SLV": ("Silver", AssetClass.COMMODITY),
    "USO": ("Crude Oil", AssetClass.COMMODITY),
    "COPX": ("Copper Miners", AssetClass.COMMODITY),
    # Bonds
    "TLT": ("20Y Treasury Bond", AssetClass.BOND),
    "SHY": ("1-3Y Treasury", AssetClass.BOND),
    "^TNX": ("10Y Yield", AssetClass.BOND),
    # Credit
    "HYG": ("High Yield Corporate", AssetClass.CREDIT),
    "LQD": ("Investment Grade", AssetClass.CREDIT),
    # Currency
    "UUP": ("US Dollar", AssetClass.CURRENCY),
    # Volatility
    "^VIX": ("CBOE VIX", AssetClass.VOLATILITY),
    "^VIX3M": ("VIX 3-Month", AssetClass.VOLATILITY),
    "^INDIAVIX": ("India VIX", AssetClass.VOLATILITY),
    # Inflation
    "TIP": ("TIPS (Inflation Protected)", AssetClass.BOND),
}


# ═══════════════════════════════════════════════════════════════════════════════
# Part 1: Asset Scorecard
# ═══════════════════════════════════════════════════════════════════════════════


def compute_asset_score(
    ticker: str,
    name: str,
    asset_class: AssetClass,
    ohlcv: pd.DataFrame,
    timeframe: str = "daily",
) -> AssetScore | None:
    """Compute scorecard for a single asset.

    Returns None if data is insufficient (< 20 rows).
    """
    if ohlcv is None or len(ohlcv) < 20:
        return None

    close = ohlcv["Close"]
    high = ohlcv["High"]
    low = ohlcv["Low"]
    price = float(close.iloc[-1])

    # Period windows
    windows = {"daily": 5, "weekly": 20, "monthly": 60}
    window = windows.get(timeframe, 20)
    window = min(window, len(close) - 1)

    # Returns
    period_close = close.tail(window)
    period_return = (float(period_close.iloc[-1]) / float(period_close.iloc[0]) - 1) * 100
    period_high = float(high.tail(window).max())
    period_low = float(low.tail(window).min())

    # SMA
    sma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else price
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else price
    vs_sma20 = (price - sma20) / sma20 * 100 if sma20 > 0 else 0
    vs_sma50 = (price - sma50) / sma50 * 100 if sma50 > 0 else 0

    # RSI (14-period exponential)
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else 50

    # ATR (14-period)
    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1]) if len(tr) >= 14 else 0
    atr_pct = atr / price * 100 if price > 0 else 0

    # Trend classification
    if vs_sma20 > 2 and vs_sma50 > 3:
        trend = TrendSignal.STRONG_BULLISH
    elif vs_sma20 > 0.5:
        trend = TrendSignal.BULLISH
    elif vs_sma20 < -2 and vs_sma50 < -3:
        trend = TrendSignal.STRONG_BEARISH
    elif vs_sma20 < -0.5:
        trend = TrendSignal.BEARISH
    else:
        trend = TrendSignal.NEUTRAL

    # Momentum description
    if rsi > 70:
        momentum_desc = "overbought"
    elif rsi > 60:
        momentum_desc = "strong"
    elif rsi > 40:
        momentum_desc = "moderate"
    elif rsi > 30:
        momentum_desc = "weak"
    else:
        momentum_desc = "oversold"

    # Volatility regime (relative to 60-day median ATR)
    if len(close) >= 60:
        hist_atr = tr.rolling(14).mean()
        atr_median = float(hist_atr.tail(60).median())
        if atr > atr_median * 1.3:
            vol_regime = "high"
        elif atr < atr_median * 0.7:
            vol_regime = "low"
        else:
            vol_regime = "normal"
    else:
        vol_regime = "normal"

    # Range position (0 = at period low, 100 = at period high)
    range_width = period_high - period_low
    range_pos = ((price - period_low) / range_width * 100) if range_width > 0 else 50

    # 52-week position
    fifty_two = None
    if len(close) >= 252:
        yr_high = float(high.tail(252).max())
        yr_low = float(low.tail(252).min())
        yr_range = yr_high - yr_low
        if yr_range > 0:
            fifty_two = (price - yr_low) / yr_range * 100

    # Composite signal score (-1 to +1)
    trend_score = {
        "strong_bullish": 1.0,
        "bullish": 0.5,
        "neutral": 0,
        "bearish": -0.5,
        "strong_bearish": -1.0,
    }[trend]
    rsi_score = (rsi - 50) / 50  # -1 to +1
    return_score = max(-1, min(1, period_return / 5))  # Normalize: +-5% -> +-1
    signal_score = trend_score * 0.4 + rsi_score * 0.3 + return_score * 0.3

    if signal_score > 0.5:
        signal = "strong_buy"
    elif signal_score > 0.15:
        signal = "buy"
    elif signal_score > -0.15:
        signal = "hold"
    elif signal_score > -0.5:
        signal = "sell"
    else:
        signal = "strong_sell"

    # Commentary
    parts = [f"{name} ({ticker}):"]
    parts.append(f"{period_return:+.1f}% ({timeframe})")
    parts.append(f"trend {trend.value}")
    parts.append(f"RSI {rsi:.0f} ({momentum_desc})")
    if fifty_two is not None:
        parts.append(f"52wk position {fifty_two:.0f}%")
    parts.append(f"vol {vol_regime}")

    return AssetScore(
        ticker=ticker,
        name=name,
        asset_class=asset_class,
        timeframe=timeframe,
        current_price=round(price, 2),
        period_return_pct=round(period_return, 2),
        period_high=round(period_high, 2),
        period_low=round(period_low, 2),
        trend=trend,
        vs_sma20_pct=round(vs_sma20, 2),
        vs_sma50_pct=round(vs_sma50, 2),
        rsi=round(rsi, 1),
        momentum_desc=momentum_desc,
        atr_pct=round(atr_pct, 2),
        volatility_regime=vol_regime,
        range_position_pct=round(range_pos, 1),
        fifty_two_week_pct=round(fifty_two, 1) if fifty_two is not None else None,
        signal=signal,
        signal_score=round(signal_score, 3),
        commentary=" | ".join(parts),
    )


def compute_all_scorecards(
    data: dict[str, pd.DataFrame],
    timeframe: str = "daily",
) -> list[AssetScore]:
    """Compute scorecards for all available assets.

    Skips any ticker whose DataFrame is missing or too short.
    """
    scores: list[AssetScore] = []
    for ticker, (name, asset_class) in RESEARCH_ASSETS.items():
        ohlcv = data.get(ticker)
        if ohlcv is None:
            continue
        score = compute_asset_score(ticker, name, asset_class, ohlcv, timeframe)
        if score is not None:
            scores.append(score)
    return scores


# ═══════════════════════════════════════════════════════════════════════════════
# Part 2: Correlation Matrix
# ═══════════════════════════════════════════════════════════════════════════════

# Key cross-asset pairs with human-readable descriptions
_KEY_PAIRS: list[tuple[str, str, str]] = [
    ("SPY", "TLT", "Stocks vs Bonds"),
    ("SPY", "GLD", "Stocks vs Gold"),
    ("SPY", "^VIX", "Stocks vs Volatility"),
    ("GLD", "^TNX", "Gold vs Yields"),
    ("GLD", "SLV", "Gold vs Silver"),
    ("USO", "SPY", "Oil vs Stocks"),
    ("HYG", "TLT", "High Yield vs Treasuries"),
    ("UUP", "EEM", "Dollar vs Emerging Markets"),
    ("UUP", "GLD", "Dollar vs Gold"),
    ("^NSEI", "SPY", "India vs US"),
    ("^NSEI", "^NSEBANK", "NIFTY vs BankNIFTY"),
    ("COPX", "GLD", "Copper vs Gold (growth/fear)"),
    ("EEM", "^NSEI", "EM vs India (FII flow proxy)"),
    ("QQQ", "IWM", "Tech vs Small Cap (risk appetite)"),
]


def compute_correlation_matrix(
    data: dict[str, pd.DataFrame],
    window: int = 20,
) -> list[CorrelationPair]:
    """Compute correlations between key asset pairs.

    Skips any pair where either ticker's data is missing.
    A pair is flagged as ``diverging`` when the 20-day and 60-day
    correlations differ by more than 0.3.
    """
    pairs: list[CorrelationPair] = []
    for a, b, desc in _KEY_PAIRS:
        df_a = data.get(a)
        df_b = data.get(b)
        if df_a is None or df_b is None:
            continue

        ret_a = df_a["Close"].pct_change().dropna()
        ret_b = df_b["Close"].pct_change().dropna()

        aligned = pd.concat([ret_a, ret_b], axis=1, join="inner").dropna()
        aligned.columns = ["a", "b"]

        if len(aligned) < window:
            continue

        corr_20 = float(aligned["a"].tail(20).corr(aligned["b"].tail(20)))
        corr_60 = (
            float(aligned["a"].tail(60).corr(aligned["b"].tail(60)))
            if len(aligned) >= 60
            else corr_20
        )

        diverging = abs(corr_20 - corr_60) > 0.3

        # Interpretation
        if abs(corr_20) > 0.7:
            direction = "positive" if corr_20 > 0 else "negative"
            movement = "together" if corr_20 > 0 else "opposite"
            interp = (
                f"Strong {direction} correlation ({corr_20:.2f})"
                f" — {desc} moving {movement}"
            )
        elif diverging:
            interp = (
                f"Correlation shifting: 20d={corr_20:.2f} vs 60d={corr_60:.2f}"
                f" — {desc} relationship changing"
            )
        else:
            interp = f"Moderate correlation ({corr_20:.2f}) — {desc}"

        pairs.append(
            CorrelationPair(
                ticker_a=a,
                ticker_b=b,
                correlation_20d=round(corr_20, 3),
                correlation_60d=round(corr_60, 3),
                diverging=diverging,
                interpretation=interp,
            )
        )

    return pairs


# ═══════════════════════════════════════════════════════════════════════════════
# Part 3: Sentiment Dashboard
# ═══════════════════════════════════════════════════════════════════════════════


def compute_sentiment(
    data: dict[str, pd.DataFrame],
    spy_pe: float | None = None,
) -> SentimentDashboard:
    """Compute market sentiment from multiple indicators.

    Parameters
    ----------
    data:
        Dict of ticker -> OHLCV DataFrame.  Must include ``^VIX`` at minimum
        for a useful result.  Other tickers (``^VIX3M``, ``GLD``, ``SLV``,
        ``COPX``, ``HYG``, ``TLT``, ``^TNX``, ``^INDIAVIX``) enrich the
        output but are individually optional.
    spy_pe:
        Optional trailing P/E ratio for SPY (from ``yfinance .info``).
        Used to compute equity risk premium.
    """
    commentary: list[str] = []

    # ── VIX ──────────────────────────────────────────────────────────────────
    vix_data = data.get("^VIX")
    vix_level = 20.0
    vix_trend = "stable"
    vix_pctl = 50.0
    if vix_data is not None and len(vix_data) >= 5:
        vix_close = vix_data["Close"]
        vix_level = float(vix_close.iloc[-1])
        vix_5d_ago = float(vix_close.iloc[-5]) if len(vix_close) >= 5 else vix_level
        if vix_level > vix_5d_ago * 1.1:
            vix_trend = "rising"
        elif vix_level < vix_5d_ago * 0.9:
            vix_trend = "falling"
        else:
            vix_trend = "stable"
        if len(vix_close) >= 60:
            vix_pctl = float((vix_close.tail(60) < vix_level).sum() / 60 * 100)

    # ── VIX term structure ───────────────────────────────────────────────────
    vix3m_data = data.get("^VIX3M")
    term_structure = "contango"
    term_ratio = 0.9
    if vix_data is not None and vix3m_data is not None:
        vix3m_level = (
            float(vix3m_data["Close"].iloc[-1]) if len(vix3m_data) > 0 else vix_level
        )
        if vix3m_level > 0:
            term_ratio = vix_level / vix3m_level
        if term_ratio > 1.05:
            term_structure = "backwardation"
            commentary.append(
                f"VIX in backwardation ({term_ratio:.2f})"
                " — near-term fear exceeds long-term. Panic indicator."
            )
        elif term_ratio < 0.90:
            term_structure = "contango"
            commentary.append(
                f"VIX in steep contango ({term_ratio:.2f})"
                " — market complacent."
            )
        else:
            term_structure = "flat"

    if vix_level > 30:
        commentary.append(
            f"VIX at {vix_level:.1f} — FEAR territory."
            " Options premiums elevated."
        )
    elif vix_level > 20:
        commentary.append(f"VIX at {vix_level:.1f} — elevated but not panic.")
    else:
        commentary.append(f"VIX at {vix_level:.1f} — calm. Premiums compressed.")

    # ── India VIX ────────────────────────────────────────────────────────────
    india_vix: float | None = None
    india_vix_data = data.get("^INDIAVIX")
    if india_vix_data is not None and len(india_vix_data) > 0:
        india_vix = float(india_vix_data["Close"].iloc[-1])

    # ── Gold / Silver ratio ──────────────────────────────────────────────────
    gsr: float | None = None
    gld = data.get("GLD")
    slv = data.get("SLV")
    if gld is not None and slv is not None and len(gld) > 0 and len(slv) > 0:
        gld_price = float(gld["Close"].iloc[-1])
        slv_price = float(slv["Close"].iloc[-1])
        if slv_price > 0:
            gsr = gld_price / slv_price
            if gsr > 85:
                commentary.append(
                    f"Gold/Silver ratio at {gsr:.1f}"
                    " — elevated fear. Silver underperforming gold."
                )
            elif gsr < 65:
                commentary.append(
                    f"Gold/Silver ratio at {gsr:.1f}"
                    " — risk appetite. Silver leading."
                )

    # ── Copper / Gold ratio ──────────────────────────────────────────────────
    cgr: float | None = None
    copx = data.get("COPX")
    if copx is not None and gld is not None and len(copx) > 0:
        copx_price = float(copx["Close"].iloc[-1])
        gld_price = float(gld["Close"].iloc[-1])
        if gld_price > 0:
            cgr = copx_price / gld_price
            # Trend matters more than level
            if len(copx) >= 20 and len(gld) >= 20:
                cgr_20d_ago = float(copx["Close"].iloc[-20]) / float(
                    gld["Close"].iloc[-20]
                )
                if cgr > cgr_20d_ago * 1.05:
                    commentary.append(
                        "Copper/Gold ratio rising"
                        " — economic growth expectations improving."
                    )
                elif cgr < cgr_20d_ago * 0.95:
                    commentary.append(
                        "Copper/Gold ratio falling"
                        " — defensive positioning, growth concerns."
                    )

    # ── Equity risk premium ──────────────────────────────────────────────────
    erp: float | None = None
    if spy_pe is not None and spy_pe > 0:
        earnings_yield = 100 / spy_pe  # As percentage
        tnx = data.get("^TNX")
        if tnx is not None and len(tnx) > 0:
            ten_y = float(tnx["Close"].iloc[-1])
            erp = earnings_yield - ten_y
            if erp < 0:
                commentary.append(
                    f"Equity risk premium NEGATIVE ({erp:.1f}%)"
                    " — bonds more attractive than stocks on yield."
                )
            elif erp < 1:
                commentary.append(
                    f"Equity risk premium thin ({erp:.1f}%)"
                    " — stocks expensive relative to bonds."
                )

    # ── Credit spread trend ──────────────────────────────────────────────────
    hyg = data.get("HYG")
    tlt = data.get("TLT")
    credit_trend = "stable"
    if hyg is not None and tlt is not None and len(hyg) >= 20 and len(tlt) >= 20:
        ratio = hyg["Close"] / tlt["Close"]
        ratio_now = float(ratio.iloc[-1])
        ratio_20d = float(ratio.iloc[-20])
        if ratio_now < ratio_20d * 0.98:
            credit_trend = "widening"
            commentary.append(
                "Credit spreads widening"
                " — risk aversion building. Reduce premium selling."
            )
        elif ratio_now > ratio_20d * 1.02:
            credit_trend = "tightening"
            commentary.append(
                "Credit spreads tightening — risk appetite returning."
            )

    # ── Overall sentiment score ──────────────────────────────────────────────
    scores: list[float] = []

    # VIX component: high VIX = fear
    if vix_level > 35:
        scores.append(-1.0)
    elif vix_level > 25:
        scores.append(-0.5)
    elif vix_level < 15:
        scores.append(0.8)
    else:
        scores.append(0.0)

    # VIX term structure
    if term_structure == "backwardation":
        scores.append(-0.8)
    elif term_structure == "contango":
        scores.append(0.3)

    # Gold/Silver ratio
    if gsr is not None:
        if gsr > 85:
            scores.append(-0.6)
        elif gsr < 65:
            scores.append(0.5)
        else:
            scores.append(0.0)

    # Credit
    if credit_trend == "widening":
        scores.append(-0.7)
    elif credit_trend == "tightening":
        scores.append(0.5)

    avg_score = sum(scores) / len(scores) if scores else 0

    if avg_score < -0.6:
        overall = "extreme_fear"
    elif avg_score < -0.2:
        overall = "fear"
    elif avg_score > 0.6:
        overall = "extreme_greed"
    elif avg_score > 0.2:
        overall = "greed"
    else:
        overall = "neutral"

    return SentimentDashboard(
        vix_level=round(vix_level, 2),
        vix_trend=vix_trend,
        vix_percentile_60d=round(vix_pctl, 1),
        vix_term_structure=term_structure,
        vix_term_ratio=round(term_ratio, 3),
        india_vix=round(india_vix, 2) if india_vix else None,
        gold_silver_ratio=round(gsr, 1) if gsr else None,
        copper_gold_ratio=round(cgr, 4) if cgr else None,
        equity_risk_premium=round(erp, 2) if erp else None,
        credit_spread_trend=credit_trend,
        overall_sentiment=overall,
        sentiment_score=round(avg_score, 3),
        commentary=commentary,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Part 4: Macro Regime Classification
# ═══════════════════════════════════════════════════════════════════════════════

_SIZE_MAP: dict[MacroRegime, float] = {
    MacroRegime.RISK_ON: 1.0,
    MacroRegime.RISK_OFF: 0.5,
    MacroRegime.STAGFLATION: 0.3,
    MacroRegime.REFLATION: 0.8,
    MacroRegime.DEFLATIONARY: 0.2,
    MacroRegime.TRANSITION: 0.6,
}

_FAVOR_MAP: dict[MacroRegime, list[str]] = {
    MacroRegime.RISK_ON: ["tech", "consumer_disc", "semiconductor"],
    MacroRegime.RISK_OFF: ["utilities", "consumer_staples", "healthcare"],
    MacroRegime.STAGFLATION: ["energy", "commodity", "healthcare"],
    MacroRegime.REFLATION: ["energy", "industrial", "materials", "finance"],
    MacroRegime.DEFLATIONARY: [],
    MacroRegime.TRANSITION: [],
}

_AVOID_MAP: dict[MacroRegime, list[str]] = {
    MacroRegime.RISK_ON: [],
    MacroRegime.RISK_OFF: ["tech", "consumer_disc", "small_cap"],
    MacroRegime.STAGFLATION: ["tech", "consumer_disc", "bonds"],
    MacroRegime.REFLATION: ["utilities", "bonds"],
    MacroRegime.DEFLATIONARY: ["tech", "consumer_disc", "energy"],
    MacroRegime.TRANSITION: [],
}

_IMPACT_MAP: dict[MacroRegime, str] = {
    MacroRegime.RISK_ON: (
        "Normal trading — income strategies work well. Full position sizes."
    ),
    MacroRegime.RISK_OFF: (
        "Defensive — reduce size, favor defined risk, hedge long equity."
        " Protective puts warranted."
    ),
    MacroRegime.STAGFLATION: (
        "Challenging — avoid theta selling (vol expanding),"
        " favor commodities and inflation hedges."
    ),
    MacroRegime.REFLATION: (
        "Moderately aggressive — directional strategies in growth sectors."
        " Avoid bonds."
    ),
    MacroRegime.DEFLATIONARY: (
        "Capital preservation — minimal new trades."
        " Cash is king. Wait for capitulation."
    ),
    MacroRegime.TRANSITION: (
        "Cautious — mixed signals."
        " Reduce position sizes, favor shorter DTE."
    ),
}


def classify_macro_regime(
    scores: list[AssetScore],
    sentiment: SentimentDashboard,
    data: dict[str, pd.DataFrame],
) -> RegimeClassification:
    """Classify the macro regime from cross-asset signals.

    Uses a rule-based approach combining asset scorecards, sentiment,
    and yield trends.  Returns a regime label with confidence, evidence,
    sector tilts, and sizing guidance.
    """
    evidence: list[str] = []

    # Look up key asset scores
    def _find(ticker: str) -> AssetScore | None:
        return next((s for s in scores if s.ticker == ticker), None)

    spy_score = _find("SPY")
    gld_score = _find("GLD")
    tlt_score = _find("TLT")
    uso_score = _find("USO")
    copx_score = _find("COPX")
    hyg_score = _find("HYG")

    spy_bull = spy_score is not None and spy_score.signal_score > 0.1
    spy_bear = spy_score is not None and spy_score.signal_score < -0.1
    gld_bull = gld_score is not None and gld_score.signal_score > 0.1
    tlt_bull = tlt_score is not None and tlt_score.signal_score > 0.1
    uso_bull = uso_score is not None and uso_score.signal_score > 0.1
    copx_bull = copx_score is not None and copx_score.signal_score > 0.1
    hyg_bull = hyg_score is not None and hyg_score.signal_score > 0.1

    # Yield trend
    tnx = data.get("^TNX")
    yields_rising = False
    if tnx is not None and len(tnx) >= 20:
        tnx_now = float(tnx["Close"].iloc[-1])
        tnx_20d = float(tnx["Close"].iloc[-20])
        yields_rising = tnx_now > tnx_20d * 1.02

    vix_elevated = sentiment.vix_level > 25

    # ── Classification rules (ordered by specificity) ────────────────────────

    # RISK ON: stocks up, credit tight, VIX low, gold flat/down
    if spy_bull and hyg_bull and not vix_elevated and not gld_bull:
        regime = MacroRegime.RISK_ON
        evidence.append("Equities rallying")
        evidence.append("Credit spreads tightening")
        evidence.append("VIX contained")
        conf = 0.7

    # RISK OFF: stocks down, gold up, bonds up, VIX elevated
    elif spy_bear and (gld_bull or tlt_bull) and vix_elevated:
        regime = MacroRegime.RISK_OFF
        evidence.append("Equities falling")
        if gld_bull:
            evidence.append("Gold rallying (safe haven)")
        if tlt_bull:
            evidence.append("Treasuries rallying (flight to safety)")
        evidence.append(f"VIX elevated at {sentiment.vix_level:.0f}")
        conf = 0.8

    # STAGFLATION: stocks down, yields up, gold up, oil up
    elif spy_bear and yields_rising and (gld_bull or uso_bull):
        regime = MacroRegime.STAGFLATION
        evidence.append("Equities falling despite rising yields")
        if gld_bull:
            evidence.append("Gold rallying (inflation hedge)")
        if uso_bull:
            evidence.append("Oil rising (supply pressure)")
        evidence.append("Yields rising — Fed can't ease")
        conf = 0.6

    # REFLATION: stocks up, yields up, oil up, copper up
    elif spy_bull and yields_rising and (uso_bull or copx_bull):
        regime = MacroRegime.REFLATION
        evidence.append("Equities rising with yields")
        if uso_bull:
            evidence.append("Oil rising (demand)")
        if copx_bull:
            evidence.append("Copper rising (growth)")
        evidence.append("Growth + inflation both accelerating")
        conf = 0.6

    # DEFLATIONARY: everything falling
    elif spy_bear and not gld_bull and not tlt_bull:
        regime = MacroRegime.DEFLATIONARY
        evidence.append("Equities falling")
        evidence.append("Gold and bonds not rallying — liquidity crisis")
        conf = 0.5

    else:
        regime = MacroRegime.TRANSITION
        evidence.append("Mixed signals across asset classes")
        conf = 0.3

    return RegimeClassification(
        regime=regime,
        confidence=round(conf, 2),
        evidence=evidence,
        position_size_factor=_SIZE_MAP.get(regime, 0.6),
        favor_sectors=_FAVOR_MAP.get(regime, []),
        avoid_sectors=_AVOID_MAP.get(regime, []),
        trading_impact=_IMPACT_MAP.get(regime, "Monitor closely."),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Part 5: India Context
# ═══════════════════════════════════════════════════════════════════════════════


def compute_india_context(
    data: dict[str, pd.DataFrame],
) -> IndiaResearchContext:
    """India-specific macro context.

    Uses ``^INDIAVIX``, ``^NSEI``, ``^NSEBANK``, ``SPY``, ``UUP``,
    and ``EEM`` from the data dict.  All tickers are individually
    optional — missing data is skipped gracefully.
    """
    commentary: list[str] = []

    # ── India VIX ────────────────────────────────────────────────────────────
    india_vix: float | None = None
    india_vix_trend = "unknown"
    ivix = data.get("^INDIAVIX")
    if ivix is not None and len(ivix) >= 5:
        india_vix = float(ivix["Close"].iloc[-1])
        ivix_5d = float(ivix["Close"].iloc[-5])
        if india_vix > ivix_5d * 1.1:
            india_vix_trend = "rising"
            commentary.append(
                f"India VIX rising to {india_vix:.1f} — volatility expanding."
            )
        elif india_vix < ivix_5d * 0.9:
            india_vix_trend = "falling"
            commentary.append(
                f"India VIX falling to {india_vix:.1f} — calming."
            )
        else:
            india_vix_trend = "stable"

    # ── NIFTY-SPY correlation ────────────────────────────────────────────────
    nifty_spy_corr: float | None = None
    nifty = data.get("^NSEI")
    spy = data.get("SPY")
    if nifty is not None and spy is not None:
        n_ret = nifty["Close"].pct_change().dropna()
        s_ret = spy["Close"].pct_change().dropna()
        aligned = pd.concat([n_ret, s_ret], axis=1, join="inner").dropna()
        if len(aligned) >= 20:
            nifty_spy_corr = float(
                aligned.iloc[:, 0].tail(20).corr(aligned.iloc[:, 1].tail(20))
            )
            if abs(nifty_spy_corr) > 0.6:
                commentary.append(
                    f"NIFTY-SPY correlation high ({nifty_spy_corr:.2f})"
                    " — India tracking US closely."
                )
            else:
                commentary.append(
                    f"NIFTY-SPY correlation low ({nifty_spy_corr:.2f})"
                    " — India decoupled from US."
                )

    # ── USD/INR proxy (UUP trend = dollar strength = INR weakness) ───────────
    uup = data.get("UUP")
    usd_inr_trend = "unknown"
    if uup is not None and len(uup) >= 20:
        uup_ret = float((uup["Close"].iloc[-1] / uup["Close"].iloc[-20] - 1) * 100)
        if uup_ret > 1:
            usd_inr_trend = "dollar_strengthening"
            commentary.append(
                f"Dollar strengthening ({uup_ret:+.1f}% / 20d)"
                " — INR under pressure. Headwind for India equities."
            )
        elif uup_ret < -1:
            usd_inr_trend = "dollar_weakening"
            commentary.append(
                f"Dollar weakening ({uup_ret:+.1f}% / 20d)"
                " — INR support. Tailwind for India."
            )
        else:
            usd_inr_trend = "stable"

    # ── FII flow proxy: EEM vs NIFTY divergence ─────────────────────────────
    eem = data.get("EEM")
    fii_signal = "neutral"
    if eem is not None and nifty is not None and len(eem) >= 20 and len(nifty) >= 20:
        eem_ret = float((eem["Close"].iloc[-1] / eem["Close"].iloc[-20] - 1) * 100)
        nifty_ret = float(
            (nifty["Close"].iloc[-1] / nifty["Close"].iloc[-20] - 1) * 100
        )
        if nifty_ret > eem_ret + 2:
            fii_signal = "inflow"
            commentary.append(
                "India outperforming EM peers — likely FII inflows."
            )
        elif nifty_ret < eem_ret - 2:
            fii_signal = "outflow"
            commentary.append(
                "India underperforming EM peers — possible FII outflows."
            )

    # ── BANKNIFTY vs NIFTY ───────────────────────────────────────────────────
    bn = data.get("^NSEBANK")
    bn_signal = "in_sync"
    if bn is not None and nifty is not None and len(bn) >= 20 and len(nifty) >= 20:
        bn_ret = float((bn["Close"].iloc[-1] / bn["Close"].iloc[-20] - 1) * 100)
        n_ret_val = float(
            (nifty["Close"].iloc[-1] / nifty["Close"].iloc[-20] - 1) * 100
        )
        if bn_ret > n_ret_val + 2:
            bn_signal = "banking_leading"
            commentary.append(
                "BankNIFTY outperforming NIFTY — financial sector strength."
            )
        elif bn_ret < n_ret_val - 2:
            bn_signal = "banking_lagging"
            commentary.append(
                "BankNIFTY underperforming NIFTY"
                " — banking sector weakness. Credit concerns?"
            )

    if not commentary:
        commentary.append(
            "India macro context data insufficient"
            " — check data availability."
        )

    return IndiaResearchContext(
        india_vix=round(india_vix, 2) if india_vix else None,
        india_vix_trend=india_vix_trend,
        nifty_spy_correlation_20d=(
            round(nifty_spy_corr, 3) if nifty_spy_corr is not None else None
        ),
        usd_inr_trend=usd_inr_trend,
        fii_flow_signal=fii_signal,
        banknifty_vs_nifty=bn_signal,
        commentary=commentary,
    )


# ---------------------------------------------------------------------------
# Part 6: FRED Economic Data
# ---------------------------------------------------------------------------


class EconomicSnapshot(BaseModel):
    """US economic fundamentals from FRED (graceful when no API key)."""

    fed_funds_rate: float | None = None
    cpi_yoy_pct: float | None = None
    core_cpi_yoy_pct: float | None = None
    unemployment_rate: float | None = None
    gdp_growth_pct: float | None = None
    m2_yoy_growth_pct: float | None = None
    yield_curve_2s10s: float | None = None
    consumer_sentiment: float | None = None
    initial_claims: int | None = None
    high_yield_spread: float | None = None
    economic_regime: str  # "expansion", "late_cycle", "contraction", "recovery"
    commentary: list[str]
    data_source: str  # "fred" or "unavailable"


def compute_economic_snapshot(
    fred_api_key: str | None = None,
) -> EconomicSnapshot:
    """Fetch economic fundamentals from FRED. Graceful if no API key."""

    if not fred_api_key:
        return EconomicSnapshot(
            economic_regime="unknown",
            commentary=[
                "FRED API key not configured — economic data unavailable. "
                "Get free key at https://fred.stlouisfed.org/docs/api/api_key.html"
            ],
            data_source="unavailable",
        )

    try:
        from fredapi import Fred  # type: ignore[import-untyped]

        fred = Fred(api_key=fred_api_key)
    except ImportError:
        return EconomicSnapshot(
            economic_regime="unknown",
            commentary=["fredapi not installed — pip install fredapi"],
            data_source="unavailable",
        )
    except Exception as e:
        return EconomicSnapshot(
            economic_regime="unknown",
            commentary=[f"FRED connection failed: {e}"],
            data_source="unavailable",
        )

    commentary: list[str] = []

    # Helper to safely fetch latest value
    def _get_latest(series_id: str, periods: int = 12) -> float | None:
        try:
            data = fred.get_series(series_id, observation_start="2024-01-01")
            if data is not None and len(data) > 0:
                return float(data.dropna().iloc[-1])
        except Exception:
            pass
        return None

    def _get_yoy_change(series_id: str) -> float | None:
        try:
            data = fred.get_series(series_id, observation_start="2023-01-01")
            if data is not None and len(data) >= 12:
                clean = data.dropna()
                current = float(clean.iloc[-1])
                year_ago = (
                    float(clean.iloc[-12]) if len(clean) >= 12 else float(clean.iloc[0])
                )
                if year_ago > 0:
                    return round((current / year_ago - 1) * 100, 2)
        except Exception:
            pass
        return None

    # Fetch data
    fed_funds = _get_latest("FEDFUNDS")
    cpi_yoy = _get_yoy_change("CPIAUCSL")
    core_cpi_yoy = _get_yoy_change("CPILFESL")
    unemployment = _get_latest("UNRATE")
    gdp = _get_latest("A191RL1Q225SBEA")  # Real GDP growth rate
    m2_yoy = _get_yoy_change("M2SL")
    yield_curve = _get_latest("T10Y2Y")
    sentiment = _get_latest("UMCSENT")
    claims = _get_latest("ICSA")
    hy_spread = _get_latest("BAMLH0A0HYM2")

    # Commentary
    if fed_funds is not None:
        commentary.append(f"Fed funds rate: {fed_funds:.2f}%")
    if cpi_yoy is not None:
        hot_tag = " (above 3% — hot)" if cpi_yoy > 3 else (" (cooling)" if cpi_yoy < 2.5 else "")
        commentary.append(f"CPI YoY: {cpi_yoy:.1f}%{hot_tag}")
    if unemployment is not None:
        labor_tag = (
            " (tight labor)" if unemployment < 4 else (" (loosening)" if unemployment > 5 else "")
        )
        commentary.append(f"Unemployment: {unemployment:.1f}%{labor_tag}")
    if yield_curve is not None:
        if yield_curve < 0:
            commentary.append(
                f"Yield curve INVERTED ({yield_curve:.2f}%) — recession signal"
            )
        else:
            commentary.append(f"Yield curve: +{yield_curve:.2f}% (normal)")
    if m2_yoy is not None:
        m2_tag = " (contracting — tight)" if m2_yoy < 0 else " (expanding)"
        commentary.append(f"M2 money supply YoY: {m2_yoy:+.1f}%{m2_tag}")
    if hy_spread is not None:
        hy_tag = (
            " (stressed)" if hy_spread > 5 else (" (normal)" if hy_spread < 4 else " (watch)")
        )
        commentary.append(f"High yield spread: {hy_spread:.2f}%{hy_tag}")

    # Economic regime classification
    eco_regime: str
    if (
        yield_curve is not None
        and yield_curve < 0
        and unemployment is not None
        and unemployment > 4.5
    ):
        eco_regime = "contraction"
    elif gdp is not None and gdp < 0:
        eco_regime = "contraction"
    elif (
        cpi_yoy is not None
        and cpi_yoy > 4
        and unemployment is not None
        and unemployment < 4
    ):
        eco_regime = "late_cycle"
    elif gdp is not None and gdp > 2 and unemployment is not None and unemployment < 5:
        eco_regime = "expansion"
    else:
        eco_regime = "recovery"

    commentary.append(f"Economic regime: {eco_regime}")

    return EconomicSnapshot(
        fed_funds_rate=fed_funds,
        cpi_yoy_pct=cpi_yoy,
        core_cpi_yoy_pct=core_cpi_yoy,
        unemployment_rate=unemployment,
        gdp_growth_pct=gdp,
        m2_yoy_growth_pct=m2_yoy,
        yield_curve_2s10s=yield_curve,
        consumer_sentiment=sentiment,
        initial_claims=int(claims) if claims else None,
        high_yield_spread=hy_spread,
        economic_regime=eco_regime,
        commentary=commentary,
        data_source="fred",
    )


# ---------------------------------------------------------------------------
# Part 7: Full Research Report
# ---------------------------------------------------------------------------


class MacroResearchReport(BaseModel):
    """Complete macro research report — daily/weekly/monthly."""

    as_of_date: date
    timeframe: str  # "daily", "weekly", "monthly"

    # Regime
    regime: RegimeClassification

    # Scorecards
    asset_scores: list[AssetScore]

    # Correlations
    correlations: list[CorrelationPair]
    divergences: list[str]

    # Sentiment
    sentiment: SentimentDashboard

    # Economics
    economics: EconomicSnapshot | None

    # India
    india: IndiaResearchContext

    # Commentary
    research_note: str  # Full research note (10-20 sentences)
    key_signals: list[str]  # Bullet-point actionable signals
    trading_impact: str  # One-line trading guidance

    # For eTrading consumption
    position_size_factor: float
    favor_sectors: list[str]
    avoid_sectors: list[str]


def generate_research_report(
    data: dict[str, pd.DataFrame],
    timeframe: str = "daily",
    fred_api_key: str | None = None,
    spy_pe: float | None = None,
) -> MacroResearchReport:
    """Generate complete macro research report.

    Args:
        data: Dict of ticker -> OHLCV DataFrame. Missing tickers are skipped gracefully.
        timeframe: "daily", "weekly", or "monthly"
        fred_api_key: Optional FRED API key for economic data
        spy_pe: SPY P/E ratio from yfinance .info (for equity risk premium)
    """
    today = date.today()

    # Scorecards
    scores = compute_all_scorecards(data, timeframe)

    # Correlations
    correlations = compute_correlation_matrix(data)
    divergences = [c.interpretation for c in correlations if c.diverging]

    # Sentiment
    sentiment = compute_sentiment(data, spy_pe)

    # Regime
    regime = classify_macro_regime(scores, sentiment, data)

    # Economics (graceful)
    economics = compute_economic_snapshot(fred_api_key)

    # India
    india = compute_india_context(data)

    # Key signals
    key_signals: list[str] = []

    # From sentiment
    if sentiment.vix_term_structure == "backwardation":
        key_signals.append(
            "VIX BACKWARDATION — near-term panic exceeds long-term. Expect continued volatility."
        )
    if sentiment.gold_silver_ratio and sentiment.gold_silver_ratio > 85:
        key_signals.append(
            f"Gold/Silver ratio at {sentiment.gold_silver_ratio:.0f} — extreme fear."
        )
    if sentiment.equity_risk_premium is not None and sentiment.equity_risk_premium < 0:
        key_signals.append(
            "Negative equity risk premium — bonds yield more than stocks. Valuation pressure."
        )
    if sentiment.credit_spread_trend == "widening":
        key_signals.append("Credit spreads widening — risk aversion building.")

    # From regime
    for ev in regime.evidence:
        key_signals.append(ev)

    # From correlations
    for d in divergences:
        key_signals.append(f"DIVERGENCE: {d}")

    # From India
    if india.fii_flow_signal == "outflow":
        key_signals.append("India: possible FII outflows — underperforming EM peers.")
    if india.banknifty_vs_nifty == "banking_lagging":
        key_signals.append("India: banking sector weakness — credit concerns.")

    # Research note
    note_parts = [f"Macro Research — {today.strftime('%B %d, %Y')} ({timeframe})"]
    note_parts.append(
        f"Regime: {regime.regime.value.upper()} (confidence {regime.confidence:.0%})"
    )
    note_parts.append(regime.trading_impact)
    note_parts.append(
        f"Sentiment: {sentiment.overall_sentiment} (score {sentiment.sentiment_score:+.2f})"
    )

    # Top movers
    if scores:
        sorted_by_return = sorted(scores, key=lambda s: s.period_return_pct, reverse=True)
        top = sorted_by_return[0]
        bottom = sorted_by_return[-1]
        note_parts.append(f"Strongest: {top.name} ({top.period_return_pct:+.1f}%)")
        note_parts.append(f"Weakest: {bottom.name} ({bottom.period_return_pct:+.1f}%)")

    for c in sentiment.commentary[:3]:
        note_parts.append(c)

    if economics and economics.data_source == "fred":
        note_parts.append(f"Economic regime: {economics.economic_regime}")
        for c in economics.commentary[:2]:
            note_parts.append(c)

    for c in india.commentary[:2]:
        note_parts.append(c)

    research_note = "\n".join(note_parts)

    return MacroResearchReport(
        as_of_date=today,
        timeframe=timeframe,
        regime=regime,
        asset_scores=scores,
        correlations=correlations,
        divergences=divergences,
        sentiment=sentiment,
        economics=economics,
        india=india,
        research_note=research_note,
        key_signals=key_signals,
        trading_impact=regime.trading_impact,
        position_size_factor=regime.position_size_factor,
        favor_sectors=regime.favor_sectors,
        avoid_sectors=regime.avoid_sectors,
    )
