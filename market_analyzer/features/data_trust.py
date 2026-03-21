"""Data trust computation — scores reliability of MA outputs."""

from __future__ import annotations

from market_analyzer.models.transparency import DataSource, DataTrust, DegradedField


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
