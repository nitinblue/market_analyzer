"""Same-ticker hedge assessment — regime-aware hedge recommendations.

Follows MA's trading philosophy: hedging is same-ticker only.
No cross-ticker hedging, no beta-weighted index hedging.

Pure functions — eTrading provides position data, MA recommends hedges.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from income_desk.models.regime import RegimeResult
from income_desk.models.technicals import TechnicalSnapshot


class HedgeType(StrEnum):
    PROTECTIVE_PUT = "protective_put"
    COLLAR = "collar"
    DELTA_HEDGE = "delta_hedge"
    ADD_WING = "add_wing"          # Convert undefined to defined risk
    CLOSE_POSITION = "close"       # Don't hedge, just exit
    NO_HEDGE = "no_hedge"


class HedgeUrgency(StrEnum):
    NONE = "none"           # No hedge needed
    MONITOR = "monitor"     # Watch but don't act
    SOON = "soon"           # Hedge within next session
    IMMEDIATE = "immediate" # Hedge now


class HedgeRecommendation(BaseModel):
    """Single deterministic hedge recommendation for a position."""

    ticker: str
    position_type: str        # "long_equity", "short_straddle", "iron_condor", etc.
    hedge_type: HedgeType
    urgency: HedgeUrgency
    rationale: str
    estimated_cost_pct: float | None  # Hedge cost as % of position value
    protection_level: str             # "ATM put at $580" or "collar $570-$595"
    risk_reduction: str               # "Max loss capped at 5%"
    regime_context: str               # Why this regime drives this hedge


def assess_hedge(
    ticker: str,
    position_type: str,       # "long_equity", "short_straddle", "iron_condor", "short_strangle", "credit_spread"
    position_value: float,    # Notional value of position (local currency)
    regime: RegimeResult,
    technicals: TechnicalSnapshot,
) -> HedgeRecommendation:
    """Recommend same-ticker hedge based on position type and regime.

    Decision tree:

    LONG EQUITY:
      R1 -> NO_HEDGE (low vol, mean reverting -- protective put wastes theta)
      R2 -> COLLAR (high IV = sell call to fund put -- zero-cost hedge)
      R3 -> NO_HEDGE if trend favorable, PROTECTIVE_PUT if against
      R4 -> PROTECTIVE_PUT immediately (explosive vol, protect capital)

    SHORT STRADDLE / SHORT STRANGLE (undefined risk):
      R1 -> NO_HEDGE (MR regime supports short vol)
      R2 -> ADD_WING (convert to iron butterfly/condor -- define risk)
      R3 -> DELTA_HEDGE (add directional leg on trending side)
      R4 -> CLOSE_POSITION (undefined risk in R4 = exit immediately)

    IRON CONDOR / IRON BUTTERFLY (defined risk):
      R1 -> NO_HEDGE (wings are the hedge, MR supports)
      R2 -> NO_HEDGE (wings are the hedge, swings revert)
      R3 -> DELTA_HEDGE if trend threatens a short strike
      R4 -> CLOSE_POSITION (wrong trade for this regime)

    CREDIT SPREAD:
      R1 -> NO_HEDGE (defined risk, MR supports)
      R2 -> NO_HEDGE (defined risk)
      R3 -> NO_HEDGE if spread direction matches trend, CLOSE if against
      R4 -> CLOSE_POSITION
    """
    regime_id = int(regime.regime)
    price = technicals.current_price
    atr = technicals.atr
    atr_pct = technicals.atr_pct

    regime_names = {
        1: "Low-Vol Mean Reverting",
        2: "High-Vol Mean Reverting",
        3: "Low-Vol Trending",
        4: "High-Vol Trending",
    }
    regime_name = regime_names.get(regime_id, f"R{regime_id}")

    # Determine trend direction
    trend = regime.trend_direction  # "bullish", "bearish", or None

    if position_type == "long_equity":
        return _hedge_long_equity(
            ticker, regime_id, regime_name, price, atr, atr_pct, trend, position_value
        )
    elif position_type in ("short_straddle", "short_strangle"):
        return _hedge_short_vol(
            ticker, position_type, regime_id, regime_name, price, atr, atr_pct
        )
    elif position_type in ("iron_condor", "iron_butterfly"):
        return _hedge_defined_risk(
            ticker, position_type, regime_id, regime_name, price, atr, trend
        )
    elif position_type == "credit_spread":
        return _hedge_credit_spread(ticker, regime_id, regime_name, price, trend)
    else:
        return HedgeRecommendation(
            ticker=ticker,
            position_type=position_type,
            hedge_type=HedgeType.NO_HEDGE,
            urgency=HedgeUrgency.MONITOR,
            rationale=f"No hedge logic for position type '{position_type}'",
            estimated_cost_pct=None,
            protection_level="n/a",
            risk_reduction="n/a",
            regime_context=f"R{regime_id} {regime_name}",
        )


def _hedge_long_equity(
    ticker: str,
    regime_id: int,
    regime_name: str,
    price: float,
    atr: float,
    atr_pct: float,
    trend: str | None,
    value: float,
) -> HedgeRecommendation:
    if regime_id == 1:
        return HedgeRecommendation(
            ticker=ticker,
            position_type="long_equity",
            hedge_type=HedgeType.NO_HEDGE,
            urgency=HedgeUrgency.NONE,
            rationale="R1 low-vol mean-reverting — protective put wastes premium in range-bound market",
            estimated_cost_pct=None,
            protection_level="n/a",
            risk_reduction="n/a",
            regime_context=f"R1 {regime_name}: vol is low, mean reverting",
        )
    elif regime_id == 2:
        put_strike = round(price - atr, 2)
        call_strike = round(price + atr, 2)
        return HedgeRecommendation(
            ticker=ticker,
            position_type="long_equity",
            hedge_type=HedgeType.COLLAR,
            urgency=HedgeUrgency.SOON,
            rationale="R2 high-vol MR — sell OTM call to fund protective put (zero-cost collar)",
            estimated_cost_pct=0.0,
            protection_level=f"Put at {put_strike:.0f}, Call at {call_strike:.0f}",
            risk_reduction=f"Max loss capped at {atr_pct:.1f}% (1 ATR)",
            regime_context=f"R2 {regime_name}: high IV makes collar cheap/free",
        )
    elif regime_id == 3:
        if trend == "bearish":
            put_strike = round(price - 0.5 * atr, 2)
            cost_est = atr_pct * 0.3  # Rough: put costs ~30% of ATR in low vol
            return HedgeRecommendation(
                ticker=ticker,
                position_type="long_equity",
                hedge_type=HedgeType.PROTECTIVE_PUT,
                urgency=HedgeUrgency.SOON,
                rationale="R3 trending bearish — protect long equity with put",
                estimated_cost_pct=round(cost_est, 2),
                protection_level=f"Put at {put_strike:.0f} (0.5 ATR OTM)",
                risk_reduction=f"Max loss capped below {put_strike:.0f}",
                regime_context=f"R3 {regime_name}: bearish trend threatens long position",
            )
        else:
            return HedgeRecommendation(
                ticker=ticker,
                position_type="long_equity",
                hedge_type=HedgeType.NO_HEDGE,
                urgency=HedgeUrgency.MONITOR,
                rationale="R3 trending bullish — trend supports long position, no hedge needed",
                estimated_cost_pct=None,
                protection_level="n/a",
                risk_reduction="n/a",
                regime_context=f"R3 {regime_name}: bullish trend aligned with long equity",
            )
    else:  # R4
        put_strike = round(price - 0.25 * atr, 2)  # Near ATM
        cost_est = atr_pct * 0.5
        return HedgeRecommendation(
            ticker=ticker,
            position_type="long_equity",
            hedge_type=HedgeType.PROTECTIVE_PUT,
            urgency=HedgeUrgency.IMMEDIATE,
            rationale="R4 explosive vol — protect capital immediately with near-ATM put",
            estimated_cost_pct=round(cost_est, 2),
            protection_level=f"Put at {put_strike:.0f} (near ATM)",
            risk_reduction=f"Max loss capped at {0.25 * atr_pct:.1f}%",
            regime_context=f"R4 {regime_name}: explosive moves — hedge or exit",
        )


def _hedge_short_vol(
    ticker: str,
    pos_type: str,
    regime_id: int,
    regime_name: str,
    price: float,
    atr: float,
    atr_pct: float,
) -> HedgeRecommendation:
    label = "straddle" if "straddle" in pos_type else "strangle"
    if regime_id == 1:
        return HedgeRecommendation(
            ticker=ticker,
            position_type=pos_type,
            hedge_type=HedgeType.NO_HEDGE,
            urgency=HedgeUrgency.NONE,
            rationale=f"R1 low-vol MR — short {label} benefits from theta decay in range",
            estimated_cost_pct=None,
            protection_level="n/a",
            risk_reduction="n/a",
            regime_context=f"R1 {regime_name}: ideal for short vol",
        )
    elif regime_id == 2:
        wing_dist = round(atr, 2)
        return HedgeRecommendation(
            ticker=ticker,
            position_type=pos_type,
            hedge_type=HedgeType.ADD_WING,
            urgency=HedgeUrgency.SOON,
            rationale=(
                f"R2 high-vol MR — add wings to convert {label} to "
                f"iron butterfly/condor (define risk)"
            ),
            estimated_cost_pct=round(atr_pct * 0.15, 2),
            protection_level=f"Buy wings {wing_dist:.0f} points from short strikes",
            risk_reduction="Converts unlimited risk to defined risk",
            regime_context=f"R2 {regime_name}: swings may test — define risk now",
        )
    elif regime_id == 3:
        return HedgeRecommendation(
            ticker=ticker,
            position_type=pos_type,
            hedge_type=HedgeType.DELTA_HEDGE,
            urgency=HedgeUrgency.SOON,
            rationale=(
                f"R3 trending — add directional leg to offset {label} "
                f"delta exposure on trending side"
            ),
            estimated_cost_pct=round(atr_pct * 0.2, 2),
            protection_level="Add debit spread in trend direction",
            risk_reduction="Reduces directional risk from trending market",
            regime_context=f"R3 {regime_name}: trend threatens one side of {label}",
        )
    else:  # R4
        return HedgeRecommendation(
            ticker=ticker,
            position_type=pos_type,
            hedge_type=HedgeType.CLOSE_POSITION,
            urgency=HedgeUrgency.IMMEDIATE,
            rationale=(
                f"R4 explosive — undefined risk on short {label} is unacceptable. "
                f"Close immediately."
            ),
            estimated_cost_pct=None,
            protection_level="CLOSE",
            risk_reduction="100% — remove all risk",
            regime_context=f"R4 {regime_name}: don't hedge undefined risk in R4, just exit",
        )


def _hedge_defined_risk(
    ticker: str,
    pos_type: str,
    regime_id: int,
    regime_name: str,
    price: float,
    atr: float,
    trend: str | None,
) -> HedgeRecommendation:
    label = "iron condor" if "condor" in pos_type else "iron butterfly"
    if regime_id in (1, 2):
        return HedgeRecommendation(
            ticker=ticker,
            position_type=pos_type,
            hedge_type=HedgeType.NO_HEDGE,
            urgency=HedgeUrgency.NONE,
            rationale=(
                f"R{regime_id} MR — {label} wings ARE the hedge. "
                f"Defined risk, theta working."
            ),
            estimated_cost_pct=None,
            protection_level="Wings define max loss",
            risk_reduction="Already hedged by structure",
            regime_context=f"R{regime_id} {regime_name}: mean-reverting supports {label}",
        )
    elif regime_id == 3:
        if trend:
            return HedgeRecommendation(
                ticker=ticker,
                position_type=pos_type,
                hedge_type=HedgeType.DELTA_HEDGE,
                urgency=HedgeUrgency.MONITOR,
                rationale=(
                    f"R3 {trend} trend — monitor {label}. "
                    f"If trend threatens short strike, add directional spread."
                ),
                estimated_cost_pct=round(0.1, 2),
                protection_level="Add debit spread if short strike tested",
                risk_reduction="Offsets directional exposure from trend",
                regime_context=f"R3 {regime_name}: {trend} trend may test one side",
            )
        return HedgeRecommendation(
            ticker=ticker,
            position_type=pos_type,
            hedge_type=HedgeType.NO_HEDGE,
            urgency=HedgeUrgency.MONITOR,
            rationale="R3 trending but no clear direction — monitor",
            estimated_cost_pct=None,
            protection_level="Wings define max loss",
            risk_reduction="Already hedged",
            regime_context=f"R3 {regime_name}",
        )
    else:  # R4
        return HedgeRecommendation(
            ticker=ticker,
            position_type=pos_type,
            hedge_type=HedgeType.CLOSE_POSITION,
            urgency=HedgeUrgency.IMMEDIATE,
            rationale=(
                f"R4 explosive — {label} is wrong trade for this regime. "
                f"Close to preserve capital."
            ),
            estimated_cost_pct=None,
            protection_level="CLOSE",
            risk_reduction="100% — remove all risk",
            regime_context=f"R4 {regime_name}: {label} will hit max loss in explosive moves",
        )


def _hedge_credit_spread(
    ticker: str,
    regime_id: int,
    regime_name: str,
    price: float,
    trend: str | None,
) -> HedgeRecommendation:
    if regime_id in (1, 2):
        return HedgeRecommendation(
            ticker=ticker,
            position_type="credit_spread",
            hedge_type=HedgeType.NO_HEDGE,
            urgency=HedgeUrgency.NONE,
            rationale=f"R{regime_id} MR — credit spread has defined risk, theta working",
            estimated_cost_pct=None,
            protection_level="Long leg defines max loss",
            risk_reduction="Already hedged by spread structure",
            regime_context=f"R{regime_id} {regime_name}: supports theta decay",
        )
    elif regime_id == 3:
        return HedgeRecommendation(
            ticker=ticker,
            position_type="credit_spread",
            hedge_type=HedgeType.NO_HEDGE,
            urgency=HedgeUrgency.MONITOR,
            rationale=(
                "R3 trending — monitor. Credit spread is defined risk. "
                "Close if trend goes against."
            ),
            estimated_cost_pct=None,
            protection_level="Long leg",
            risk_reduction="Already hedged",
            regime_context=f"R3 {regime_name}: watch trend direction vs spread side",
        )
    else:  # R4
        return HedgeRecommendation(
            ticker=ticker,
            position_type="credit_spread",
            hedge_type=HedgeType.CLOSE_POSITION,
            urgency=HedgeUrgency.IMMEDIATE,
            rationale="R4 explosive — credit spread at high risk of max loss. Close.",
            estimated_cost_pct=None,
            protection_level="CLOSE",
            risk_reduction="100%",
            regime_context=f"R4 {regime_name}: explosive moves make credit spreads dangerous",
        )
