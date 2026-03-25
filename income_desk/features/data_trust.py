"""Data trust computation — scores reliability of MA outputs."""

from __future__ import annotations

from pydantic import BaseModel

from income_desk.models.transparency import (
    ContextGap,
    DataSource,
    DataTrust,
    DegradedField,
    TrustLevel,
    TrustReport,
)


# ---------------------------------------------------------------------------
# Ticker-level trust
# ---------------------------------------------------------------------------

class TickerTrust(BaseModel):
    """Trust assessment for a single ticker's data availability."""

    ticker: str
    data_source: str  # "broker_live", "yfinance_delayed", "cached", "none"
    trust_level: str  # "HIGH", "MEDIUM", "LOW", "NONE"
    has_greeks: bool = False
    has_iv: bool = False
    has_option_chain: bool = False
    fit_for: str = ""  # "execution", "research", "display_only"


def compute_ticker_trust(
    ticker: str,
    has_broker_quote: bool = False,
    has_greeks: bool = False,
    has_iv: bool = False,
    has_option_chain: bool = False,
    has_ohlcv: bool = True,
) -> TickerTrust:
    """Assess data trust for a single ticker.

    Logic:
        broker_quote + greeks + iv + chain → HIGH / broker_live / execution
        broker_quote only (no greeks)       → MEDIUM / broker_live / research
        no broker, has ohlcv                → LOW / yfinance_delayed / research
        nothing                             → NONE / none / display_only
    """
    if has_broker_quote and has_greeks and has_iv and has_option_chain:
        return TickerTrust(
            ticker=ticker,
            data_source="broker_live",
            trust_level="HIGH",
            has_greeks=True,
            has_iv=True,
            has_option_chain=True,
            fit_for="execution",
        )
    if has_broker_quote:
        return TickerTrust(
            ticker=ticker,
            data_source="broker_live",
            trust_level="MEDIUM",
            has_greeks=has_greeks,
            has_iv=has_iv,
            has_option_chain=has_option_chain,
            fit_for="research",
        )
    if has_ohlcv:
        return TickerTrust(
            ticker=ticker,
            data_source="yfinance_delayed",
            trust_level="LOW",
            has_greeks=False,
            has_iv=False,
            has_option_chain=False,
            fit_for="research",
        )
    return TickerTrust(
        ticker=ticker,
        data_source="none",
        trust_level="NONE",
        has_greeks=False,
        has_iv=False,
        has_option_chain=False,
        fit_for="display_only",
    )


# ---------------------------------------------------------------------------
# Position-level trust
# ---------------------------------------------------------------------------

class LegTrustInput(BaseModel):
    """Per-leg data availability for position trust computation."""

    has_current_price: bool = False
    has_greeks: bool = False
    price_source: str = "none"  # "broker_live", "yfinance_delayed", "none"


class PositionTrust(BaseModel):
    """Trust assessment for a multi-leg position."""

    overall_trust: str  # "HIGH", "MEDIUM", "LOW", "NONE"
    pnl_reliable: bool
    greeks_reliable: bool
    stale_legs: int
    total_legs: int
    last_marked: str | None = None
    message: str = ""


def _leg_trust_level(leg: LegTrustInput) -> str:
    """Return trust level string for one leg."""
    if leg.has_current_price and leg.has_greeks and leg.price_source == "broker_live":
        return "HIGH"
    if leg.has_current_price and leg.price_source == "broker_live":
        return "MEDIUM"
    if leg.has_current_price:
        return "LOW"
    return "NONE"


_TRUST_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "NONE": 0}


def compute_position_trust(
    legs: list[LegTrustInput],
    last_marked: str | None = None,
) -> PositionTrust:
    """Assess data trust for a multi-leg position.

    Logic:
        - All legs broker_live + greeks → HIGH, pnl+greeks reliable
        - All legs have prices (any source) → pnl reliable
        - Any leg missing price → stale_legs += 1, pnl not fully reliable
        - No greeks on any leg → greeks_reliable=False
        - Overall trust = worst leg trust level
    """
    total = len(legs)
    if total == 0:
        return PositionTrust(
            overall_trust="NONE",
            pnl_reliable=False,
            greeks_reliable=False,
            stale_legs=0,
            total_legs=0,
            last_marked=last_marked,
            message="No legs provided",
        )

    stale = sum(1 for leg in legs if not leg.has_current_price)
    any_greeks = any(leg.has_greeks for leg in legs)
    all_greeks = all(leg.has_greeks for leg in legs)
    all_priced = stale == 0

    # Overall trust = worst leg
    worst = min((_leg_trust_level(leg) for leg in legs), key=lambda t: _TRUST_RANK[t])

    pnl_reliable = all_priced
    greeks_reliable = all_greeks

    # Build message
    if worst == "HIGH":
        message = "All legs marked from broker"
    elif all_priced:
        message = "All legs priced — mixed sources"
    elif stale > 0:
        message = f"{stale}/{total} legs stale — PnL estimated"
    else:
        message = "Position data incomplete"

    if not any_greeks:
        message += "; no Greeks available"

    return PositionTrust(
        overall_trust=worst,
        pnl_reliable=pnl_reliable,
        greeks_reliable=greeks_reliable,
        stale_legs=stale,
        total_legs=total,
        last_marked=last_marked,
        message=message,
    )


def compute_data_trust(
    has_broker: bool = False,
    has_iv_rank: bool = False,
    has_vol_surface: bool = False,
    has_levels: bool = False,
    has_fundamentals: bool = False,
    entry_credit_source: str = "estimated",  # "broker", "estimated", "none"
    regime_confidence: float = 0.0,
    data_gaps: list | None = None,
) -> DataTrust:
    """Compute trust score based on data availability.

    Scoring:
        Base: 0.30 (yfinance OHLCV always available — regime + technicals work)
        +0.30 for broker connection (real quotes, Greeks, IV)
        +0.10 for IV rank available
        +0.10 for vol surface computed
        +0.05 for levels analysis
        +0.05 for fundamentals
        +0.10 for real broker entry credit

        Penalties:
        -0.05 per data gap
        -0.10 if regime confidence < 60%

    Returns:
        DataTrust with score, level, source, and degraded fields.
    """
    score = 0.30  # Base: yfinance OHLCV
    degraded: list[DegradedField] = []

    # Broker connection is the biggest trust driver
    if has_broker:
        score += 0.30
        primary = DataSource.BROKER_LIVE
    else:
        primary = DataSource.YFINANCE_LIVE
        degraded.append(DegradedField(
            field="option_quotes",
            source=DataSource.NONE,
            reason="No broker — option prices, Greeks, IV unavailable",
        ))

    if has_iv_rank:
        score += 0.10
    else:
        degraded.append(DegradedField(
            field="iv_rank",
            source=DataSource.NONE,
            reason="IV rank unavailable — premium quality unknown",
        ))

    if has_vol_surface:
        score += 0.10
    else:
        degraded.append(DegradedField(
            field="vol_surface",
            source=DataSource.NONE,
            reason="Vol surface not computed — skew and term structure unknown",
        ))

    if has_levels:
        score += 0.05

    if has_fundamentals:
        score += 0.05

    if entry_credit_source == "broker":
        score += 0.10
    elif entry_credit_source == "estimated":
        score += 0.03
        degraded.append(DegradedField(
            field="entry_credit",
            source=DataSource.ESTIMATED,
            reason="Credit estimated from IV — may be off by 2-3x",
        ))
    else:
        degraded.append(DegradedField(
            field="entry_credit",
            source=DataSource.NONE,
            reason="No entry credit available",
        ))

    # Regime confidence penalty
    if regime_confidence < 0.60:
        score -= 0.10
        degraded.append(DegradedField(
            field="regime",
            source=DataSource.COMPUTED,
            reason=f"Regime confidence {regime_confidence:.0%} — below 60% threshold",
        ))

    # Data gap penalty
    if data_gaps:
        penalty = min(0.15, len(data_gaps) * 0.05)
        score -= penalty

    score = max(0.0, min(1.0, score))
    return DataTrust.from_score(score, primary, degraded)


def compute_context_quality(
    # What optional params were actually provided?
    has_levels: bool = False,
    has_iv_rank: bool = False,
    has_vol_surface: bool = False,
    has_fundamentals: bool = False,
    has_days_to_earnings: bool = False,
    has_entry_credit: bool = False,
    has_regime: bool = True,          # Almost always provided
    has_technicals: bool = True,      # Almost always provided
    has_ticker_type: bool = False,
    has_correlation_data: bool = False,
    has_portfolio_exposure: bool = False,
    mode: str = "full",               # "full" (default) or "standalone"
) -> tuple[float, TrustLevel, list[ContextGap]]:
    """Score how complete the caller's input context is.

    Scoring:
        Base: 0.40 (regime + technicals = minimum viable)
        +0.15 for levels (strike proximity, pullback alerts)
        +0.12 for iv_rank (premium quality assessment)
        +0.10 for vol_surface (skew, DTE optimization)
        +0.08 for entry_credit (POP, EV, Kelly)
        +0.05 for fundamentals (earnings blackout)
        +0.03 for days_to_earnings (earnings gate)
        +0.03 for ticker_type (IV rank thresholds)
        +0.02 for correlation_data (position sizing)
        +0.02 for portfolio_exposure (Kelly adjustment)

    In "standalone" mode, portfolio-level inputs (correlation_data,
    portfolio_exposure, ticker_type) are not expected by the caller and
    missing them does NOT create gaps or reduce the score.  This is the
    correct mode for CLI exploration, backtesting, and "what-if" analysis.

    In "full" mode (the default), all inputs are expected.  Missing
    critical inputs make is_actionable=False.  eTrading MUST use full mode.
    """
    # In standalone mode, portfolio-level params are not expected.
    # Treat them as present so they contribute their score without gaps.
    is_standalone = mode == "standalone"
    effective_correlation = has_correlation_data or is_standalone
    effective_portfolio = has_portfolio_exposure or is_standalone
    effective_ticker_type = has_ticker_type or is_standalone

    score = 0.0
    gaps: list[ContextGap] = []

    if has_regime:
        score += 0.20
    else:
        gaps.append(ContextGap(
            parameter="regime",
            impact="No regime detection — all strategy selection is blind",
            importance="critical",
        ))

    if has_technicals:
        score += 0.20
    else:
        gaps.append(ContextGap(
            parameter="technicals",
            impact="No price data — entry scoring impossible",
            importance="critical",
        ))

    if has_levels:
        score += 0.15
    else:
        gaps.append(ContextGap(
            parameter="levels",
            impact="Strike proximity check skipped, no pullback alerts",
            importance="important",
        ))

    if has_iv_rank:
        score += 0.12
    else:
        gaps.append(ContextGap(
            parameter="iv_rank",
            impact="IV rank quality check skipped — premium quality unknown",
            importance="important",
        ))

    if has_vol_surface:
        score += 0.10
    else:
        gaps.append(ContextGap(
            parameter="vol_surface",
            impact="No skew analysis, no DTE optimization",
            importance="important",
        ))

    if has_entry_credit:
        score += 0.08
    else:
        gaps.append(ContextGap(
            parameter="entry_credit",
            impact="POP, EV, and Kelly sizing are unavailable",
            importance="critical",
        ))

    if has_fundamentals:
        score += 0.05

    if has_days_to_earnings:
        score += 0.03
    else:
        gaps.append(ContextGap(
            parameter="days_to_earnings",
            impact="Earnings blackout gate inactive",
            importance="helpful",
        ))

    # Portfolio-level inputs: only score/gap in full mode
    if effective_ticker_type:
        score += 0.03

    if effective_correlation:
        score += 0.02

    if effective_portfolio:
        score += 0.02

    score = max(0.0, min(1.0, score))

    if score >= 0.80:
        level = TrustLevel.HIGH
    elif score >= 0.50:
        level = TrustLevel.MEDIUM
    elif score >= 0.20:
        level = TrustLevel.LOW
    else:
        level = TrustLevel.UNRELIABLE

    return score, level, gaps


def compute_trust_report(
    # Calculation mode
    mode: str = "full",  # "full" (default, portfolio-aware) or "standalone" (CLI/backtest)
    # Data quality inputs (existing)
    has_broker: bool = False,
    has_iv_rank: bool = False,
    has_vol_surface: bool = False,
    has_levels: bool = False,
    has_fundamentals: bool = False,
    entry_credit_source: str = "estimated",
    regime_confidence: float = 0.0,
    data_gaps: list | None = None,
    # Context quality inputs (new)
    has_days_to_earnings: bool = False,
    has_entry_credit: bool = False,
    has_regime: bool = True,
    has_technicals: bool = True,
    has_ticker_type: bool = False,
    has_correlation_data: bool = False,
    has_portfolio_exposure: bool = False,
) -> TrustReport:
    """Compute full 2-dimensional trust report.

    Args:
        mode: "full" (default) — portfolio-aware, eTrading production mode.
              "standalone" — single-trade analysis; missing portfolio context
              (correlation_data, portfolio_exposure, ticker_type) is expected
              and does not degrade trust.  Use for CLI exploration, backtesting.
    """
    # Dimension 1: Data Quality
    data = compute_data_trust(
        has_broker=has_broker,
        has_iv_rank=has_iv_rank,
        has_vol_surface=has_vol_surface,
        has_levels=has_levels,
        has_fundamentals=has_fundamentals,
        entry_credit_source=entry_credit_source,
        regime_confidence=regime_confidence,
        data_gaps=data_gaps,
    )

    # Dimension 2: Context Quality
    ctx_score, ctx_level, ctx_gaps = compute_context_quality(
        has_levels=has_levels,
        has_iv_rank=has_iv_rank,
        has_vol_surface=has_vol_surface,
        has_fundamentals=has_fundamentals,
        has_days_to_earnings=has_days_to_earnings,
        has_entry_credit=has_entry_credit,
        has_regime=has_regime,
        has_technicals=has_technicals,
        has_ticker_type=has_ticker_type,
        has_correlation_data=has_correlation_data,
        has_portfolio_exposure=has_portfolio_exposure,
        mode=mode,
    )

    # Combined: the weaker dimension limits overall trust
    overall = min(data.trust_score, ctx_score)
    if overall >= 0.80:
        overall_level = TrustLevel.HIGH
    elif overall >= 0.50:
        overall_level = TrustLevel.MEDIUM
    elif overall >= 0.20:
        overall_level = TrustLevel.LOW
    else:
        overall_level = TrustLevel.UNRELIABLE

    # Summary
    parts = [f"Data: {data.trust_level.value} ({data.trust_score:.0%})"]
    parts.append(f"Context: {ctx_level.value} ({ctx_score:.0%})")
    if ctx_gaps:
        critical = [g for g in ctx_gaps if g.importance == "critical"]
        if critical:
            parts.append(f"MISSING: {', '.join(g.parameter for g in critical)}")

    # Fitness hint in summary
    if overall >= 0.80:
        fit_cats = "live execution"
    elif overall >= 0.70:
        fit_cats = "monitoring/risk"
    elif overall >= 0.50:
        fit_cats = "alerting/calibration"
    elif overall >= 0.30:
        fit_cats = "screening/research"
    else:
        fit_cats = "education only"
    parts.append(f"Fit for: {fit_cats}")

    summary = " | ".join(parts)

    return TrustReport(
        data_quality=data,
        context_score=round(ctx_score, 2),
        context_level=ctx_level,
        context_gaps=ctx_gaps,
        overall_trust=round(overall, 2),
        overall_level=overall_level,
        summary=summary,
    )
