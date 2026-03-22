"""DTE optimization: select optimal expiration from vol surface.

Pure function — no data fetching, no broker required.
Uses vol surface term structure to find the expiration with the
highest theta-per-day (theta proxy = ATM_IV * sqrt(1/DTE)).
"""

from __future__ import annotations

import math
from datetime import date

from pydantic import BaseModel

from income_desk.models.vol_surface import VolatilitySurface

# Regime → preferred DTE range and rationale
_REGIME_DTE_PREFERENCE: dict[int, tuple[int, int, str]] = {
    1: (30, 45, "R1 standard theta harvesting window"),
    2: (21, 30, "R2 shorter exposure to vol swings"),
    3: (21, 30, "R3 minimize time in adverse trend"),
    4: (14, 21, "R4 defined risk, minimum exposure"),
}


class DTERecommendation(BaseModel):
    """Result of DTE optimization from vol surface."""

    recommended_dte: int
    recommended_expiration: date
    theta_proxy: float
    iv_at_expiration: float
    all_candidates: list[dict]  # All evaluated DTEs with scores
    regime_preference: str  # "30-45 DTE (R1 standard)"
    rationale: str


def select_optimal_dte(
    vol_surface: VolatilitySurface,
    regime_id: int = 1,
    strategy: str = "income",
    min_dte: int = 14,
    max_dte: int = 60,
) -> DTERecommendation | None:
    """Select optimal DTE from vol surface term structure.

    Computes theta_proxy = atm_iv * sqrt(1/days_to_expiry) for each
    expiration in the valid range. Higher theta_proxy means more daily
    theta per unit of IV — better for income trades.

    Applies regime preference as a tiebreaker: within the regime-preferred
    range, candidates get a 10% bonus to theta_proxy.

    Args:
        vol_surface: Computed vol surface with term_structure.
        regime_id: Current regime (1-4).
        strategy: Trade strategy type (for rationale context).
        min_dte: Minimum DTE to consider.
        max_dte: Maximum DTE to consider.

    Returns:
        DTERecommendation with best expiration, or None if no valid candidates.
    """
    pref_min, pref_max, pref_desc = _REGIME_DTE_PREFERENCE.get(
        regime_id, (30, 45, f"R{regime_id} default"),
    )

    candidates: list[dict] = []

    for pt in vol_surface.term_structure:
        dte = pt.days_to_expiry
        if dte < min_dte or dte > max_dte or dte <= 0:
            continue

        theta_proxy = pt.atm_iv * math.sqrt(1.0 / dte)

        # Regime preference bonus: 10% if within preferred range
        in_preferred = pref_min <= dte <= pref_max
        adjusted_proxy = theta_proxy * 1.10 if in_preferred else theta_proxy

        candidates.append({
            "expiration": pt.expiration.isoformat(),
            "dte": dte,
            "atm_iv": round(pt.atm_iv, 4),
            "theta_proxy": round(theta_proxy, 6),
            "adjusted_proxy": round(adjusted_proxy, 6),
            "in_regime_preference": in_preferred,
        })

    if not candidates:
        return None

    # Sort by adjusted_proxy descending
    candidates.sort(key=lambda c: c["adjusted_proxy"], reverse=True)
    best = candidates[0]

    # Find the matching TermStructurePoint for the best candidate
    best_expiration = date.fromisoformat(best["expiration"])

    regime_pref_str = f"{pref_min}-{pref_max} DTE ({pref_desc})"

    rationale = (
        f"Selected {best['dte']} DTE (exp {best['expiration']}) with "
        f"theta proxy {best['theta_proxy']:.4f} (IV {best['atm_iv']:.1%}). "
        f"Regime preference: {regime_pref_str}."
    )
    if best["in_regime_preference"]:
        rationale += " Within regime-preferred range (10% bonus applied)."

    return DTERecommendation(
        recommended_dte=best["dte"],
        recommended_expiration=best_expiration,
        theta_proxy=best["theta_proxy"],
        iv_at_expiration=best["atm_iv"],
        all_candidates=candidates,
        regime_preference=regime_pref_str,
        rationale=rationale,
    )
