"""Historical IV tracking and percentile computation.

Stores daily IV snapshots per ticker. Computes rolling percentiles for:
- Front/back IV (is current IV extreme?)
- Term structure (is current contango/backwardation extreme?)
- Skew ratio (is current skew extreme?)

MA is stateless — the history is passed IN by the caller (eTrading stores it).
For standalone/CLI use, can build from recent vol surface computations.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class DailyIVSnapshot(BaseModel):
    """Single day's IV summary for a ticker — stored for history."""

    date: date
    ticker: str
    front_iv: float  # Nearest-expiry ATM IV
    back_iv: float  # ~30-60 DTE ATM IV
    term_slope: float  # (back - front) / front
    skew_ratio: float  # put_skew / call_skew at front expiry
    calendar_edge: float  # 0-1 calendar edge score


class IVPercentiles(BaseModel):
    """Current IV metrics with historical percentile context."""

    ticker: str
    as_of_date: date

    # Current values
    front_iv: float
    back_iv: float
    term_slope: float
    skew_ratio: float

    # Percentiles (0-100, where current value sits in history)
    front_iv_percentile: float  # "Front IV is at 75th percentile of last 60 days"
    back_iv_percentile: float
    term_slope_percentile: float  # "Term structure is at 90th percentile" = extreme
    skew_percentile: float
    calendar_edge_percentile: float

    # Interpretations
    front_iv_extreme: bool  # >80th or <20th percentile
    term_structure_extreme: bool  # >80th or <20th percentile
    skew_extreme: bool

    # Calendar/diagonal signals
    calendar_opportunity: str  # "strong", "moderate", "weak", "none"
    calendar_rationale: str
    diagonal_opportunity: str
    diagonal_rationale: str

    commentary: list[str]
    history_days: int  # How many days of history used


def compute_iv_percentiles(
    current: DailyIVSnapshot,
    history: list[DailyIVSnapshot],
    lookback_days: int = 60,
) -> IVPercentiles:
    """Compute percentile context from IV history.

    Args:
        current: Today's IV snapshot
        history: Past daily IV snapshots (eTrading provides from DB, or built from cache)
        lookback_days: How many days to use for percentile computation
    """
    today = current.date

    # Filter to lookback window
    recent = [
        s
        for s in history
        if (today - s.date).days <= lookback_days and s.date < today
    ]
    recent.sort(key=lambda s: s.date)
    n = len(recent)

    if n < 10:
        # Not enough history for meaningful percentiles
        return IVPercentiles(
            ticker=current.ticker,
            as_of_date=today,
            front_iv=current.front_iv,
            back_iv=current.back_iv,
            term_slope=current.term_slope,
            skew_ratio=current.skew_ratio,
            front_iv_percentile=50,
            back_iv_percentile=50,
            term_slope_percentile=50,
            skew_percentile=50,
            calendar_edge_percentile=50,
            front_iv_extreme=False,
            term_structure_extreme=False,
            skew_extreme=False,
            calendar_opportunity="unknown",
            calendar_rationale="Insufficient IV history (<10 days)",
            diagonal_opportunity="unknown",
            diagonal_rationale="Insufficient IV history (<10 days)",
            commentary=[
                "Need at least 10 days of IV history for percentile computation",
                f"Currently have {n} days",
            ],
            history_days=n,
        )

    # Compute percentiles
    def _pctl(current_val: float, hist_vals: list[float]) -> float:
        if not hist_vals:
            return 50.0
        below = sum(1 for v in hist_vals if v < current_val)
        return round(below / len(hist_vals) * 100, 1)

    front_pctl = _pctl(current.front_iv, [s.front_iv for s in recent])
    back_pctl = _pctl(current.back_iv, [s.back_iv for s in recent])
    slope_pctl = _pctl(current.term_slope, [s.term_slope for s in recent])
    skew_pctl = _pctl(current.skew_ratio, [s.skew_ratio for s in recent])
    edge_pctl = _pctl(current.calendar_edge, [s.calendar_edge for s in recent])

    front_extreme = front_pctl > 80 or front_pctl < 20
    term_extreme = slope_pctl > 80 or slope_pctl < 20
    skew_extreme_ = skew_pctl > 80 or skew_pctl < 20

    commentary = [
        f"IV History: {n} days lookback for {current.ticker}",
        f"Front IV: {current.front_iv:.1%} ({front_pctl:.0f}th percentile)"
        f" — {'HIGH' if front_pctl > 70 else 'LOW' if front_pctl < 30 else 'normal'}",
        f"Back IV: {current.back_iv:.1%} ({back_pctl:.0f}th percentile)",
        f"Term slope: {current.term_slope:+.3f} ({slope_pctl:.0f}th percentile)"
        f" — {'EXTREME' if term_extreme else 'normal'}",
        f"Skew ratio: {current.skew_ratio:.2f} ({skew_pctl:.0f}th percentile)"
        f" — {'EXTREME' if skew_extreme_ else 'normal'}",
    ]

    # Calendar opportunity: backwardation OR extreme contango + high front IV
    cal_opp = "none"
    cal_rationale = ""

    if current.term_slope < -0.02 and front_pctl > 60:
        # Backwardation with elevated front IV — strong calendar setup
        cal_opp = "strong"
        cal_rationale = (
            f"Backwardation (slope {current.term_slope:+.3f}) with front IV at "
            f"{front_pctl:.0f}th percentile. "
            "Front month IV is elevated — sell front, buy back. "
            "Calendar edge is historically attractive."
        )
    elif current.term_slope < 0 and front_pctl > 40:
        cal_opp = "moderate"
        cal_rationale = (
            f"Mild backwardation with front IV at {front_pctl:.0f}th percentile. "
            "Decent calendar setup but not extreme."
        )
    elif current.term_slope > 0.05 and slope_pctl > 80:
        # Extreme contango — maybe the contango will narrow
        cal_opp = "moderate"
        cal_rationale = (
            f"Steep contango at {slope_pctl:.0f}th percentile (extreme). "
            "May offer reverse calendar if contango expected to narrow."
        )
    else:
        cal_opp = "weak" if current.term_slope >= 0 else "none"
        cal_rationale = (
            f"Term structure at {slope_pctl:.0f}th percentile"
            " — not extreme enough for high-conviction calendar."
        )

    commentary.append(f"Calendar: {cal_opp.upper()} — {cal_rationale[:80]}")

    # Diagonal opportunity: extreme skew + direction
    diag_opp = "none"
    diag_rationale = ""

    if skew_pctl > 80:
        diag_opp = "strong"
        diag_rationale = (
            f"Skew at {skew_pctl:.0f}th percentile (extreme). "
            "Puts are relatively expensive — bull call diagonal benefits "
            "from selling expensive put skew."
        )
    elif skew_pctl > 60:
        diag_opp = "moderate"
        diag_rationale = (
            f"Skew at {skew_pctl:.0f}th percentile — elevated. "
            "Moderate diagonal edge."
        )
    elif skew_pctl < 20:
        diag_opp = "moderate"
        diag_rationale = (
            f"Skew at {skew_pctl:.0f}th percentile (compressed). "
            "Calls are relatively expensive — bear put diagonal may benefit."
        )
    else:
        diag_opp = "weak"
        diag_rationale = (
            f"Skew at {skew_pctl:.0f}th percentile — normal. "
            "No strong diagonal edge."
        )

    commentary.append(f"Diagonal: {diag_opp.upper()} — {diag_rationale[:80]}")

    return IVPercentiles(
        ticker=current.ticker,
        as_of_date=today,
        front_iv=current.front_iv,
        back_iv=current.back_iv,
        term_slope=current.term_slope,
        skew_ratio=current.skew_ratio,
        front_iv_percentile=front_pctl,
        back_iv_percentile=back_pctl,
        term_slope_percentile=slope_pctl,
        skew_percentile=skew_pctl,
        calendar_edge_percentile=edge_pctl,
        front_iv_extreme=front_extreme,
        term_structure_extreme=term_extreme,
        skew_extreme=skew_extreme_,
        calendar_opportunity=cal_opp,
        calendar_rationale=cal_rationale,
        diagonal_opportunity=diag_opp,
        diagonal_rationale=diag_rationale,
        commentary=commentary,
        history_days=n,
    )


def build_iv_snapshot_from_surface(
    ticker: str,
    vol_surface: object | None,  # VolatilitySurface object
    as_of: date | None = None,
) -> DailyIVSnapshot | None:
    """Convert a VolatilitySurface to a DailyIVSnapshot for history storage.

    eTrading should call this daily after computing vol surface, and store the result.
    Over time, builds up the history needed for percentile computation.
    """
    if vol_surface is None:
        return None

    today = as_of or date.today()

    front_iv = getattr(vol_surface, "front_iv", 0) or 0
    back_iv = getattr(vol_surface, "back_iv", 0) or 0
    term_slope = getattr(vol_surface, "term_slope", 0) or 0
    calendar_edge = getattr(vol_surface, "calendar_edge_score", 0) or 0

    # Skew ratio from first skew slice
    skew_ratio = 1.0
    skew_slices = getattr(vol_surface, "skew_by_expiry", []) or []
    if skew_slices:
        first = skew_slices[0]
        sr = getattr(first, "skew_ratio", 1.0)
        if sr is not None:
            skew_ratio = sr

    return DailyIVSnapshot(
        date=today,
        ticker=ticker,
        front_iv=round(front_iv, 4),
        back_iv=round(back_iv, 4),
        term_slope=round(term_slope, 4),
        skew_ratio=round(skew_ratio, 4),
        calendar_edge=round(calendar_edge, 4),
    )
