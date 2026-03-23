"""Interest rate risk assessment — bond sensitivity, yield curve impact.

Pure functions — no data fetching, no broker required.
Assesses how much a ticker or portfolio is exposed to interest rate moves.
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class RateRiskLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    ELEVATED = "elevated"
    HIGH = "high"


class RateRiskAssessment(BaseModel):
    """Interest rate risk for a single ticker."""

    ticker: str
    rate_sensitivity: str          # "high", "moderate", "low"
    estimated_duration: float      # Bond duration proxy (0 for most equities)
    yield_correlation: float       # Correlation with TNX (10Y yield); negative = prices fall when yields rise
    rate_risk_level: RateRiskLevel

    # Impact estimates
    impact_per_25bp: float         # Estimated % price change per 25bp yield change
    impact_per_100bp: float        # Estimated % price change per 100bp yield change

    # Current environment
    current_yield_trend: str       # "rising", "falling", "stable", "volatile"

    reasons: list[str]
    recommendation: str            # "avoid_long_duration", "reduce_exposure", "no_action"
    summary: str


class PortfolioRateRisk(BaseModel):
    """Portfolio-level rate risk aggregation."""

    ticker_risks: list[RateRiskAssessment]
    portfolio_duration: float                    # Weighted average duration
    portfolio_rate_sensitivity: str              # "low"/"moderate"/"high"
    estimated_portfolio_impact_100bp: float      # % portfolio impact per 100bp yield change
    high_risk_tickers: list[str]                 # Tickers that need attention
    recommendation: str
    summary: str


# ---------------------------------------------------------------------------
# Rate sensitivity table
# (sensitivity_label, duration_years, yield_correlation_with_TNX)
# yield_correlation: negative = bond-like (prices fall when yields rise)
# ---------------------------------------------------------------------------

_RATE_SENSITIVITY: dict[str, tuple[str, float, float]] = {
    # High sensitivity — long-duration / bond-like
    "TLT": ("high", 17.0, -0.85),    # iShares 20+ Year Treasury; strong inverse rate correlation
    "TMF": ("high", 51.0, -0.95),    # 3x levered 20Y treasury
    "EDV": ("high", 25.0, -0.90),    # Extended Duration Treasury
    "ZROZ": ("high", 25.0, -0.88),   # Long zero-coupon treasury
    "LQD": ("high", 8.5, -0.65),     # Investment grade corporate bonds
    "IEF": ("moderate", 7.5, -0.70), # 7-10 year treasury
    "IEI": ("moderate", 4.5, -0.55), # 3-7 year treasury
    "TIP": ("moderate", 7.0, -0.50), # TIPS (inflation protected; rate sensitivity partially hedged)
    "BOND": ("high", 9.0, -0.72),    # PIMCO active bond
    "SHY": ("low", 2.0, -0.30),      # 1-3 year treasury (short duration)
    "BIL": ("low", 0.1, -0.05),      # T-bills (near-zero duration)
    "GOVT": ("moderate", 6.0, -0.65),# Diversified treasury
    "AGG": ("moderate", 6.5, -0.60), # Aggregate bond market
    "BND": ("moderate", 6.3, -0.58), # Vanguard aggregate bond
    "HYG": ("moderate", 4.0, -0.40), # High yield (credit risk offsets some rate risk)
    "JNK": ("moderate", 3.8, -0.38), # High yield ETF
    "HYEM": ("moderate", 5.0, -0.35),# EM high yield

    # Moderate sensitivity — rate-sensitive sectors
    "XLU": ("moderate", 0.0, -0.45), # Utilities — dividend yield competes with bonds
    "XLRE": ("moderate", 0.0, -0.40),# Real estate — cap rates tied to interest rates
    "VNQ": ("moderate", 0.0, -0.42), # Vanguard REIT
    "XLF": ("moderate", 0.0, 0.35),  # Financials — benefit from rising rates (NIM expansion)
    "KRE": ("moderate", 0.0, 0.40),  # Regional banks — strong rate beneficiary
    "KBE": ("moderate", 0.0, 0.38),  # Bank ETF

    # Low sensitivity — most broad equities
    "SPY": ("low", 0.0, -0.15),      # S&P 500 — mild negative correlation
    "SPX": ("low", 0.0, -0.15),      # S&P 500 (cash index)
    "QQQ": ("low", 0.0, -0.20),      # Tech slightly more rate sensitive (growth = long duration equity)
    "NDX": ("low", 0.0, -0.20),      # Nasdaq 100
    "IWM": ("low", 0.0, -0.10),      # Small cap — low rate sensitivity
    "DIA": ("low", 0.0, -0.12),      # Dow Jones
    "GLD": ("low", 0.0, -0.25),      # Gold — inversely correlated with real rates
    "SLV": ("low", 0.0, -0.20),      # Silver
    "GDX": ("low", 0.0, -0.30),      # Gold miners — higher sensitivity than physical gold
    "USO": ("low", 0.0, -0.05),      # Oil — supply/demand driven, low rate sensitivity
    "XLE": ("low", 0.0, 0.05),       # Energy — mild rate correlation
    "XLV": ("low", 0.0, -0.10),      # Healthcare — defensive, low rate sensitivity
    "XLK": ("low", 0.0, -0.22),      # Technology — growth = long duration
    "ARKK": ("low", 0.0, -0.35),     # Speculative tech — very rate sensitive (high duration equity)
    "TNA": ("low", 0.0, -0.10),      # 3x small cap

    # India banking — highly sensitive to RBI repo rate
    "HDFCBANK": ("high", 0.0, 0.40),    # HDFC Bank — large private bank, NIM-driven
    "ICICIBANK": ("high", 0.0, 0.38),   # ICICI Bank — private bank, rate beneficiary
    "SBIN": ("high", 0.0, 0.45),        # SBI — PSU bank, most rate-sensitive
    "AXISBANK": ("high", 0.0, 0.38),    # Axis Bank — private bank
    "KOTAKBANK": ("moderate", 0.0, 0.30),# Kotak Mahindra — less rate-sensitive than peers
}


def _yield_trend_label(current_yield_change_bps: float) -> str:
    """Classify recent yield change into a trend label."""
    if abs(current_yield_change_bps) > 15:
        return "volatile"
    elif current_yield_change_bps > 5:
        return "rising"
    elif current_yield_change_bps < -5:
        return "falling"
    return "stable"


def assess_rate_risk(
    ticker: str,
    current_yield_change_bps: float = 0.0,
    regime_id: int = 1,
    atr_pct: float = 1.0,
) -> RateRiskAssessment:
    """Assess interest rate risk for a single ticker.

    Args:
        ticker:                    The ticker symbol to assess.
        current_yield_change_bps:  Recent change in 10Y Treasury yield in basis points
                                   (positive = yields rising). Used to calibrate current risk.
        regime_id:                 Current market regime (1-4). R4 adds extra concern.
        atr_pct:                   ATR as % of price. Used for equity rate impact estimation.

    Returns:
        RateRiskAssessment with risk level, impact estimates, and recommendation.
    """
    sensitivity, duration, yield_corr = _RATE_SENSITIVITY.get(
        ticker.upper(), ("low", 0.0, -0.10),
    )

    yield_trend = _yield_trend_label(current_yield_change_bps)

    # Impact estimates
    if duration > 0:
        # Bond-like: price change ≈ -duration × yield_change_pct
        # 25bp = 0.25% = 0.0025; 100bp = 1.0% = 0.01
        impact_25bp = -duration * 0.0025
        impact_100bp = -duration * 0.01
    else:
        # Equity: use correlation-based heuristic
        # Assume 1% of ATR per 100bp yield change, scaled by correlation magnitude
        base = atr_pct / 100.0  # Convert ATR pct to decimal
        impact_25bp = yield_corr * base * 0.25
        impact_100bp = yield_corr * base * 1.0

    # Determine risk level
    # Note: positive yield_corr (e.g. financials) means RISING yields are beneficial,
    # so elevated/volatile rates are not a risk — they're a tailwind.
    if sensitivity == "high" and yield_trend in ("volatile", "rising"):
        level = RateRiskLevel.HIGH
    elif sensitivity == "high":
        level = RateRiskLevel.ELEVATED
    elif sensitivity == "moderate" and yield_trend == "volatile":
        # Positive corr (financials): volatile rates still mean uncertainty but lower risk
        if yield_corr > 0:
            level = RateRiskLevel.MODERATE
        else:
            level = RateRiskLevel.ELEVATED
    elif sensitivity == "moderate" and yield_trend == "rising":
        # Financials (positive yield_corr) actually benefit from rising rates
        if yield_corr > 0:
            level = RateRiskLevel.LOW
        else:
            level = RateRiskLevel.MODERATE
    elif sensitivity == "moderate":
        level = RateRiskLevel.MODERATE
    else:
        level = RateRiskLevel.LOW

    # R4 (high-vol trending) adds a notch
    if regime_id == 4 and level in (RateRiskLevel.LOW, RateRiskLevel.MODERATE):
        level = RateRiskLevel.MODERATE

    # Build reasons
    reasons: list[str] = []
    if duration > 0:
        reasons.append(
            f"{ticker} has duration ~{duration:.1f}y — "
            f"{abs(impact_100bp):.1%} price impact per 100bp yield change"
        )
    else:
        reasons.append(
            f"{ticker} has {sensitivity} rate sensitivity "
            f"(yield correlation {yield_corr:+.2f})"
        )

    if yield_trend == "rising" and yield_corr < -0.3:
        reasons.append(f"Rising yields ({current_yield_change_bps:+.0f}bp) are a headwind for {ticker}")
    elif yield_trend == "falling" and yield_corr < -0.3:
        reasons.append(f"Falling yields ({current_yield_change_bps:+.0f}bp) are a tailwind for {ticker}")
    elif yield_trend == "volatile":
        reasons.append(f"Volatile rate environment ({current_yield_change_bps:+.0f}bp) increases uncertainty")

    if yield_corr > 0.3 and yield_trend == "rising":
        reasons.append(f"{ticker} benefits from rising rates (positive yield correlation)")

    # Recommendation
    if level == RateRiskLevel.HIGH:
        rec = "avoid_long_duration"
    elif level == RateRiskLevel.ELEVATED:
        rec = "reduce_exposure"
    else:
        rec = "no_action"

    # Summary
    impact_dir = "drop" if impact_100bp < 0 else "gain"
    impact_mag = abs(impact_100bp)
    summary = (
        f"{ticker}: {sensitivity} rate sensitivity, "
        f"yields {yield_trend} → risk={level.value}. "
        f"~{impact_mag:.1%} {impact_dir} per 100bp. "
        f"Action: {rec.replace('_', ' ')}."
    )

    return RateRiskAssessment(
        ticker=ticker,
        rate_sensitivity=sensitivity,
        estimated_duration=duration,
        yield_correlation=yield_corr,
        rate_risk_level=level,
        impact_per_25bp=round(impact_25bp, 4),
        impact_per_100bp=round(impact_100bp, 4),
        current_yield_trend=yield_trend,
        reasons=reasons,
        recommendation=rec,
        summary=summary,
    )


def assess_portfolio_rate_risk(
    tickers: list[str],
    weights: dict[str, float] | None = None,
    current_yield_change_bps: float = 0.0,
    regime_id: int = 1,
) -> PortfolioRateRisk:
    """Assess interest rate risk for a portfolio of tickers.

    Args:
        tickers:                   List of ticker symbols in the portfolio.
        weights:                   Portfolio weights per ticker (fractions summing to 1).
                                   If None, equal-weights all tickers.
        current_yield_change_bps:  Recent 10Y yield change in basis points.
        regime_id:                 Current market regime (1-4).

    Returns:
        PortfolioRateRisk with aggregate duration, impact estimate, and recommendations.
    """
    if not tickers:
        return PortfolioRateRisk(
            ticker_risks=[],
            portfolio_duration=0.0,
            portfolio_rate_sensitivity="low",
            estimated_portfolio_impact_100bp=0.0,
            high_risk_tickers=[],
            recommendation="no_action",
            summary="No tickers provided.",
        )

    # Normalize weights
    n = len(tickers)
    if weights is None:
        w = {t: 1.0 / n for t in tickers}
    else:
        total = sum(weights.values())
        w = {t: weights.get(t, 1.0 / n) / total for t in tickers}

    # Assess each ticker
    ticker_risks: list[RateRiskAssessment] = []
    for t in tickers:
        risk = assess_rate_risk(
            ticker=t,
            current_yield_change_bps=current_yield_change_bps,
            regime_id=regime_id,
        )
        ticker_risks.append(risk)

    # Weighted aggregates
    portfolio_duration = sum(
        r.estimated_duration * w.get(r.ticker, 1.0 / n)
        for r in ticker_risks
    )
    portfolio_impact_100bp = sum(
        r.impact_per_100bp * w.get(r.ticker, 1.0 / n)
        for r in ticker_risks
    )

    # Identify high-risk tickers
    high_risk_tickers = [
        r.ticker for r in ticker_risks
        if r.rate_risk_level in (RateRiskLevel.HIGH, RateRiskLevel.ELEVATED)
    ]

    # Portfolio-level sensitivity label
    high_count = sum(1 for r in ticker_risks if r.rate_sensitivity == "high")
    mod_count = sum(1 for r in ticker_risks if r.rate_sensitivity == "moderate")
    if high_count / n >= 0.3:
        portfolio_sensitivity = "high"
    elif (high_count + mod_count) / n >= 0.4:
        portfolio_sensitivity = "moderate"
    else:
        portfolio_sensitivity = "low"

    # Recommendation
    if high_risk_tickers and portfolio_sensitivity in ("high", "moderate"):
        rec = "reduce_long_duration_exposure"
    elif high_risk_tickers:
        rec = "monitor_rate_sensitive_positions"
    else:
        rec = "no_action"

    # Summary
    impact_dir = "negative" if portfolio_impact_100bp < 0 else "positive"
    summary = (
        f"{len(tickers)}-ticker portfolio: {portfolio_sensitivity} rate sensitivity, "
        f"avg duration {portfolio_duration:.1f}y, "
        f"~{abs(portfolio_impact_100bp):.1%} {impact_dir} impact per 100bp. "
        f"{len(high_risk_tickers)} high-risk tickers: {', '.join(high_risk_tickers) or 'none'}. "
        f"Action: {rec.replace('_', ' ')}."
    )

    return PortfolioRateRisk(
        ticker_risks=ticker_risks,
        portfolio_duration=round(portfolio_duration, 2),
        portfolio_rate_sensitivity=portfolio_sensitivity,
        estimated_portfolio_impact_100bp=round(portfolio_impact_100bp, 4),
        high_risk_tickers=high_risk_tickers,
        recommendation=rec,
        summary=summary,
    )
