"""Trade commentary generation — 6-dimension per-trade narrative analysis.

Each dimension analyzer is a pure function:
    (trade data) -> DimensionFinding

The composer combines dimensions into TradeCommentary.
"""
from __future__ import annotations

from income_desk.retrospection.models import (
    DecisionCommentary,
    DecisionRecord,
    DimensionFinding,
    LegRecord,
    PositionSize,
    TradeCommentary,
    TradeClosed,
    TradeOpened,
    TradeSnapshot,
)

# ── Constants ──────────────────────────────────────────────────────────

# Regime-strategy compatibility (from CLAUDE.md)
_REGIME_RECOMMENDED: dict[str, set[str]] = {
    "R1": {"iron_condor", "strangle", "straddle", "ratio_spread", "calendar",
            "iron_butterfly", "credit_spread", "double_calendar", "pmcc"},
    "R2": {"iron_condor", "iron_butterfly", "calendar", "ratio_spread", "credit_spread"},
    "R3": {"diagonal", "leap", "momentum", "breakout", "debit_spread"},
    "R4": {"breakout", "momentum", "debit_spread"},
}

_REGIME_AVOID: dict[str, set[str]] = {
    "R1": {"breakout", "momentum", "debit_spread"},
    "R2": {"breakout", "momentum", "debit_spread"},
    "R3": {"iron_condor", "strangle", "straddle", "iron_butterfly"},
    "R4": {"iron_condor", "strangle", "straddle", "iron_butterfly",
            "calendar", "ratio_spread", "credit_spread"},
}

_REGIME_NAMES = {
    "R1": "Low-Vol Mean Reverting",
    "R2": "High-Vol Mean Reverting",
    "R3": "Low-Vol Trending",
    "R4": "High-Vol Trending",
}

_THETA_STRATEGIES = {
    "iron_condor", "iron_butterfly", "strangle", "straddle",
    "ratio_spread", "calendar", "credit_spread", "double_calendar",
}

_EQUITY_STRATEGIES = {
    "equity_long", "equity_short", "equity_sell", "equity_buy",
}


def _score_to_grade(score: int) -> str:
    if score >= 93: return "A"
    if score >= 90: return "A-"
    if score >= 87: return "B+"
    if score >= 83: return "B"
    if score >= 80: return "B-"
    if score >= 77: return "C+"
    if score >= 73: return "C"
    if score >= 70: return "C-"
    if score >= 60: return "D"
    return "F"


# ── Dimension 1: Regime Alignment ──────────────────────────────────────


def analyze_regime_alignment(
    strategy: str,
    regime: str | None,
    confidence: float | None,
) -> DimensionFinding:
    """Evaluate whether the strategy fits the regime state."""
    if regime is None:
        return DimensionFinding(
            dimension="regime_alignment", grade="C", score=50,
            narrative="No regime data at entry — cannot confirm strategy suitability.",
            details={"regime": None, "strategy": strategy, "reason": "missing_regime"},
        )

    regime_upper = str(regime).upper()
    if not regime_upper.startswith("R"):
        regime_upper = f"R{regime_upper}"

    regime_name = _REGIME_NAMES.get(regime_upper, regime_upper)
    recommended = _REGIME_RECOMMENDED.get(regime_upper, set())
    avoid = _REGIME_AVOID.get(regime_upper, set())

    conf = confidence or 0.0
    conf_str = f"{conf:.0%}" if conf > 0 else "unknown"

    if strategy in avoid:
        score = 25 if conf < 0.60 else 15
        return DimensionFinding(
            dimension="regime_alignment",
            grade="F" if score <= 20 else "D",
            score=score,
            narrative=(
                f"{strategy} in {regime_upper} ({regime_name}) at {conf_str} confidence "
                f"— this strategy should be avoided in this regime."
            ),
            details={"regime": regime_upper, "strategy": strategy,
                     "confidence": conf, "alignment": "avoid"},
        )

    if strategy in recommended:
        if conf < 0.50:
            return DimensionFinding(
                dimension="regime_alignment", grade="B", score=70,
                narrative=(
                    f"{strategy} fits {regime_upper} ({regime_name}), but confidence "
                    f"is only {conf_str} — regime uncertain."
                ),
                details={"regime": regime_upper, "strategy": strategy,
                         "confidence": conf, "alignment": "recommended_low_conf"},
            )
        return DimensionFinding(
            dimension="regime_alignment", grade="A", score=92,
            narrative=(
                f"{strategy} in {regime_upper} ({regime_name}) at {conf_str} confidence "
                f"— good strategy-regime fit."
            ),
            details={"regime": regime_upper, "strategy": strategy,
                     "confidence": conf, "alignment": "recommended"},
        )

    # Neutral — not recommended, not avoided
    return DimensionFinding(
        dimension="regime_alignment", grade="B-", score=65,
        narrative=(
            f"{strategy} is not in the recommended set for {regime_upper} "
            f"({regime_name}), but not explicitly avoided either."
        ),
        details={"regime": regime_upper, "strategy": strategy,
                 "confidence": conf, "alignment": "neutral"},
    )


# ── Dimension 2: Strike Placement ─────────────────────────────────────


def analyze_strike_placement(
    legs: list[LegRecord],
    strategy: str,
    underlying_price: float,
) -> DimensionFinding:
    """Evaluate strike selection quality based on deltas and distance."""
    if strategy in _EQUITY_STRATEGIES:
        return DimensionFinding(
            dimension="strike_placement", grade="B", score=70,
            narrative="Equity position — strike placement not applicable.",
            details={"reason": "equity"},
        )

    if not legs:
        return DimensionFinding(
            dimension="strike_placement", grade="C", score=50,
            narrative="No leg data — cannot evaluate strike placement.",
            details={"reason": "no_legs"},
        )

    # Find short legs (STO) and extract deltas
    # eTrading sends 'delta' (snapshot), ID model also has 'entry_delta'
    short_legs = [l for l in legs if l.action == "STO"]
    short_deltas = []
    for l in short_legs:
        d = l.entry_delta if l.entry_delta is not None else l.delta
        if d is not None:
            short_deltas.append(abs(d))

    if not short_deltas:
        return DimensionFinding(
            dimension="strike_placement", grade="C", score=50,
            narrative="No short leg delta data — cannot grade strike placement.",
            details={"reason": "no_short_deltas"},
        )

    avg_delta = sum(short_deltas) / len(short_deltas)
    max_delta = max(short_deltas)

    if avg_delta <= 0.16:
        grade, score = "A-", 88
        desc = (f"Conservative short deltas (avg {avg_delta:.2f}) "
                f"— safe but may collect less premium.")
    elif avg_delta <= 0.25:
        grade, score = "A", 92
        desc = f"Short deltas avg {avg_delta:.2f} — ideal range for income strategies."
    elif avg_delta <= 0.30:
        grade, score = "B", 75
        desc = (f"Short deltas avg {avg_delta:.2f} "
                f"— slightly wide of ideal 0.16-0.25 range.")
    elif avg_delta <= 0.40:
        grade, score = "C+", 60
        desc = (f"Short deltas avg {avg_delta:.2f} (max {max_delta:.2f}) "
                f"— aggressive for income. Standard target is 0.16-0.30.")
    else:
        grade, score = "D", 35
        desc = (f"Short deltas avg {avg_delta:.2f} "
                f"— too aggressive. High probability of breach.")

    # Wing width from strikes
    wing_info: dict[str, float] = {}
    shorts_by_type = {l.option_type: l.strike for l in short_legs if l.strike}
    longs = [l for l in legs if l.action == "BTO" and l.strike]
    for ll in longs:
        if ll.option_type in shorts_by_type:
            wing_info[ll.option_type] = abs(shorts_by_type[ll.option_type] - ll.strike)

    details: dict = {
        "avg_short_delta": round(avg_delta, 4),
        "max_short_delta": round(max_delta, 4),
        "short_deltas": [round(d, 4) for d in short_deltas],
        "underlying_price": underlying_price,
    }
    if wing_info:
        details["wing_widths"] = wing_info

    return DimensionFinding(
        dimension="strike_placement", grade=grade, score=score,
        narrative=desc, details=details,
    )


# ── Dimension 3: Entry Pricing ─────────────────────────────────────────


def analyze_entry_pricing(
    entry_price: float,
    legs: list[LegRecord],
    strategy: str,
    wing_width: float | None = None,
    lot_size: int = 100,
    currency: str = "USD",
) -> DimensionFinding:
    """Evaluate entry pricing quality — credit/width ratio, premium collected."""
    curr_sym = "Rs." if currency == "INR" else "$"

    if not entry_price or entry_price <= 0:
        return DimensionFinding(
            dimension="entry_pricing", grade="C", score=50,
            narrative="No entry price data — cannot evaluate premium quality.",
            details={"reason": "no_entry_price"},
        )

    if wing_width and wing_width > 0:
        # Try to compute net credit from individual leg prices (most accurate)
        # Net credit = sum of short leg prices - sum of long leg prices
        short_premium = sum(l.entry_price for l in legs if l.action == "STO" and l.entry_price)
        long_premium = sum(l.entry_price for l in legs if l.action == "BTO" and l.entry_price)
        if short_premium > 0 and long_premium > 0:
            effective_credit = short_premium - long_premium
        else:
            effective_credit = entry_price
            # If credit >> wing_width, entry_price is likely total (not per-unit)
            if effective_credit > wing_width * 2:
                effective_credit = entry_price / lot_size

        ratio = effective_credit / wing_width
        ratio_pct = ratio * 100

        if ratio >= 0.50:
            grade, score = "A", 92
            desc = (f"Collected {curr_sym}{effective_credit:.2f}/unit on {wing_width:.0f}-wide "
                    f"wings — {ratio_pct:.1f}% of max width. Excellent premium.")
        elif ratio >= 0.33:
            grade, score = "B", 75
            desc = (f"Collected {curr_sym}{effective_credit:.2f}/unit on {wing_width:.0f}-wide "
                    f"wings — {ratio_pct:.1f}% of width. Good premium.")
        elif ratio >= 0.20:
            grade, score = "C", 55
            desc = (f"Collected {curr_sym}{effective_credit:.2f}/unit on {wing_width:.0f}-wide "
                    f"wings — {ratio_pct:.1f}% of width. Thin premium for the risk.")
        else:
            grade, score = "D", 35
            desc = (f"Collected {curr_sym}{effective_credit:.2f}/unit on {wing_width:.0f}-wide "
                    f"wings — only {ratio_pct:.1f}%. Risk/reward unfavorable.")

        details = {
            "entry_price": entry_price,
            "effective_credit_per_unit": round(effective_credit, 2),
            "wing_width": wing_width,
            "credit_pct": round(ratio_pct, 1),
            "lot_size": lot_size, "currency": currency,
            "total_credit": round(entry_price * lot_size, 2) if effective_credit == entry_price else round(entry_price, 2),
        }
    else:
        grade, score = "B", 70
        desc = (f"Entry at {curr_sym}{entry_price:.2f} per contract "
                f"({curr_sym}{entry_price * lot_size:.0f} total). "
                f"Cannot evaluate credit/width ratio without wing width.")
        details = {
            "entry_price": entry_price, "lot_size": lot_size,
            "currency": currency,
            "total_credit": round(entry_price * lot_size, 2),
        }

    return DimensionFinding(
        dimension="entry_pricing", grade=grade, score=score,
        narrative=desc, details=details,
    )


# ── Dimension 4: Position Sizing ───────────────────────────────────────


def analyze_position_sizing(
    position_size: PositionSize | None,
) -> DimensionFinding:
    """Evaluate position sizing vs account risk guidelines."""
    if position_size is None:
        return DimensionFinding(
            dimension="position_sizing", grade="C", score=50,
            narrative="No position sizing data — cannot evaluate risk allocation.",
            details={"reason": "no_data"},
        )

    pct = position_size.capital_at_risk_pct
    contracts = position_size.contracts

    if pct <= 2.0:
        grade, score = "A", 92
        desc = f"{pct:.1f}% of NLV at risk ({contracts} contracts) — well within 2% guideline."
    elif pct <= 3.0:
        grade, score = "B", 78
        desc = f"{pct:.1f}% of NLV at risk ({contracts} contracts) — acceptable, near 3% soft limit."
    elif pct <= 5.0:
        grade, score = "C", 55
        desc = f"{pct:.1f}% of NLV at risk ({contracts} contracts) — elevated. Target <=3%."
    else:
        grade, score = "D", 30
        desc = f"{pct:.1f}% of NLV at risk ({contracts} contracts) — oversized. Max recommended is 3-5%."

    return DimensionFinding(
        dimension="position_sizing", grade=grade, score=score,
        narrative=desc,
        details={"capital_at_risk_pct": pct, "contracts": contracts},
    )


# ── Dimension 5: Exit Quality (closed trades) ─────────────────────────


def analyze_exit_quality(trade: TradeClosed) -> DimensionFinding:
    """Evaluate exit timing and decision quality for closed trades."""
    score = 70
    observations: list[str] = []

    if trade.exit_reason == "profit_target":
        score += 15
        observations.append("Exited at profit target — good discipline.")
    elif trade.exit_reason == "stop_loss":
        score -= 5
        observations.append("Stop loss triggered — loss is expected sometimes.")
    elif trade.exit_reason == "expiration":
        score -= 5
        observations.append("Held to expiration — consider earlier exit for capital efficiency.")

    # Was profitable but closed at loss?
    if (trade.max_pnl_during_hold is not None
            and trade.max_pnl_during_hold > 0
            and trade.total_pnl < 0):
        score -= 15
        observations.append(
            f"Was profitable (max ${trade.max_pnl_during_hold:.0f}) but closed at "
            f"${trade.total_pnl:.0f}. Review exit timing — tighter profit target "
            f"or trail stop could have captured the gain."
        )

    # Profit left on table
    if (trade.max_pnl_during_hold is not None
            and trade.total_pnl > 0
            and trade.max_pnl_during_hold > trade.total_pnl * 1.5):
        left = trade.max_pnl_during_hold - trade.total_pnl
        observations.append(
            f"Left ~${left:.0f} on table (max was ${trade.max_pnl_during_hold:.0f}, "
            f"captured ${trade.total_pnl:.0f})."
        )

    # Holding period for theta strategies
    if trade.strategy_type in _THETA_STRATEGIES and trade.holding_days > 28:
        score -= 10
        observations.append(
            f"Held {trade.holding_days} days for theta strategy — target 21-28 DTE exit."
        )

    # Regime change during hold
    if (trade.entry_regime and trade.exit_regime
            and trade.entry_regime != trade.exit_regime):
        score -= 5
        observations.append(
            f"Regime changed {trade.entry_regime} -> {trade.exit_regime} during hold. "
            f"Consider adding regime-change exit rule."
        )

    score = max(0, min(100, score))
    narrative = " ".join(observations) if observations else "Standard exit — no notable issues."

    return DimensionFinding(
        dimension="exit_quality", grade=_score_to_grade(score), score=score,
        narrative=narrative,
        details={
            "exit_reason": trade.exit_reason,
            "total_pnl": trade.total_pnl,
            "max_pnl": trade.max_pnl_during_hold,
            "holding_days": trade.holding_days,
            "entry_regime": trade.entry_regime,
            "exit_regime": trade.exit_regime,
        },
    )


# ── Dimension 6: Hindsight (open snapshots) ───────────────────────────


def analyze_hindsight(snap: TradeSnapshot) -> DimensionFinding:
    """Evaluate current position state with hindsight — how's it doing now?"""
    score = 70
    observations: list[str] = []

    pnl_pct = snap.current_pnl_pct or 0
    dte = snap.dte_remaining

    # PnL trajectory
    if pnl_pct >= 50:
        score += 15
        observations.append(f"Position at {pnl_pct:.0f}% profit — approaching target.")
    elif pnl_pct >= 20:
        score += 5
        observations.append(f"Position at {pnl_pct:.0f}% profit — on track.")
    elif pnl_pct <= -50:
        score -= 20
        observations.append(f"Position at {pnl_pct:.0f}% — significant loss. Consider management.")
    elif pnl_pct < 0:
        score -= 10
        observations.append(f"Position at {pnl_pct:.0f}% — underwater but manageable.")

    # DTE urgency
    if dte is not None:
        if dte <= 3 and pnl_pct < 0:
            score -= 15
            observations.append(f"Only {dte} DTE remaining with a loss — gamma risk elevated.")
        elif dte <= 7 and pnl_pct < -25:
            score -= 10
            observations.append(
                f"{dte} DTE with {pnl_pct:.0f}% loss — consider closing to avoid further risk."
            )
        elif dte <= 5 and pnl_pct > 0:
            observations.append(f"{dte} DTE, profitable — consider closing to lock in gains.")

    # Underlying movement
    underlying_move_pct = None
    if snap.underlying_price_at_entry and snap.underlying_price_now:
        underlying_move_pct = round(
            (snap.underlying_price_now - snap.underlying_price_at_entry)
            / snap.underlying_price_at_entry * 100, 2
        )
        if abs(underlying_move_pct) > 3:
            direction = "up" if underlying_move_pct > 0 else "down"
            observations.append(
                f"Underlying moved {underlying_move_pct:+.1f}% {direction} since entry."
            )
            if pnl_pct < 0:
                score -= 5

    # Delta exposure
    if snap.current_delta is not None and abs(snap.current_delta) > 0.30:
        observations.append(
            f"Net delta at {snap.current_delta:.2f} — directional exposure building."
        )
        score -= 5

    score = max(0, min(100, score))
    narrative = " ".join(observations) if observations else "Position within expected parameters."

    return DimensionFinding(
        dimension="hindsight", grade=_score_to_grade(score), score=score,
        narrative=narrative,
        details={
            "current_pnl_pct": pnl_pct,
            "dte_remaining": dte,
            "current_delta": snap.current_delta,
            "underlying_move_pct": underlying_move_pct,
        },
    )


# ── Composer ───────────────────────────────────────────────────────────


def compose_trade_commentary(
    trade: TradeOpened | TradeClosed | TradeSnapshot,
    trade_type: str = "opened",
) -> TradeCommentary:
    """Compose full commentary for a single trade across all applicable dimensions."""
    dims: list[DimensionFinding] = []

    ticker = trade.ticker
    strategy = trade.strategy_type
    market = getattr(trade, "market", "US")

    # 1. Regime alignment
    regime = None
    confidence = None
    if isinstance(trade, TradeOpened) and trade.entry_analytics:
        regime = trade.entry_analytics.regime_at_entry
    elif isinstance(trade, TradeClosed):
        regime = trade.entry_regime
    dims.append(analyze_regime_alignment(strategy, regime, confidence))

    # 2. Strike placement
    legs: list[LegRecord] = getattr(trade, "legs", [])
    underlying = 0.0
    if isinstance(trade, TradeOpened):
        underlying = trade.entry_underlying_price
    elif isinstance(trade, TradeSnapshot):
        underlying = trade.underlying_price_at_entry or 0.0
    dims.append(analyze_strike_placement(legs, strategy, underlying))

    # 3. Entry pricing
    entry_price = getattr(trade, "entry_price", 0.0)
    wing_width = _derive_wing_width(legs)
    lot_size = 100 if market == "US" else 25
    currency = "INR" if market == "India" else "USD"
    dims.append(analyze_entry_pricing(
        entry_price, legs, strategy, wing_width, lot_size, currency,
    ))

    # 4. Position sizing
    pos_size = getattr(trade, "position_size", None)
    dims.append(analyze_position_sizing(pos_size))

    # 5. Exit quality (closed only)
    if isinstance(trade, TradeClosed):
        dims.append(analyze_exit_quality(trade))

    # 6. Hindsight (snapshot only)
    if isinstance(trade, TradeSnapshot):
        dims.append(analyze_hindsight(trade))

    # Compose overall narrative from notable findings
    key_points = [d.narrative for d in dims if d.score <= 60 or d.score >= 85]
    if not key_points:
        key_points = [d.narrative for d in dims[:2]]
    overall = f"{ticker} {strategy}: " + " ".join(key_points[:3])

    # Should have avoided?
    avoid = any(d.dimension == "regime_alignment" and d.grade in ("D", "F") for d in dims)
    avoid_reason = next(
        (d.narrative for d in dims
         if d.dimension == "regime_alignment" and d.grade in ("D", "F")),
        None,
    )

    # Capital efficiency flag: equity_long on options-eligible stock = red flag
    if strategy in _EQUITY_STRATEGIES and market == "US":
        avoid = True
        avoid_reason = (
            f"{ticker} booked as {strategy} — this stock has liquid options. "
            f"An iron condor or credit spread would use ~10x less capital. "
            f"Check if the options ranking pipeline evaluated {ticker}."
        )

    # Key lesson — pick the lowest-scoring dimension
    worst = min(dims, key=lambda d: d.score)
    lesson = worst.narrative if worst.score < 70 else None

    return TradeCommentary(
        trade_id=getattr(trade, "trade_id", ""),
        ticker=ticker,
        strategy=strategy,
        market=market,
        overall_narrative=overall,
        dimensions=dims,
        should_have_avoided=avoid,
        avoidance_reason=avoid_reason,
        key_lesson=lesson,
    )


def _derive_wing_width(legs: list[LegRecord]) -> float | None:
    """Derive wing width from leg strikes (short - long on same side)."""
    shorts = {l.option_type: l.strike for l in legs if l.action == "STO" and l.strike}
    longs = {l.option_type: l.strike for l in legs if l.action == "BTO" and l.strike}
    widths = []
    for ot in ("put", "call"):
        if ot in shorts and ot in longs:
            widths.append(abs(shorts[ot] - longs[ot]))
    return widths[0] if widths else None


# ── Decision Commentary ────────────────────────────────────────────────


def generate_decision_commentary(decisions: list[DecisionRecord]) -> DecisionCommentary:
    """Analyze the day's approval/rejection patterns."""
    approved = [d for d in decisions if d.response == "approved"]
    rejected = [d for d in decisions if d.response != "approved"]

    reason_counts: dict[str, int] = {}
    near_misses: list[dict] = []
    missed_opps: list[dict] = []

    # Reasons that are correct gate behavior — not real missed opportunities
    _EXPECTED_REJECTIONS = {"duplicate", "already hold", "portfolio full", "portfolio fu"}

    for d in rejected:
        reason = d.gate_result or "unknown"
        lower = reason.lower()
        if "score" in lower and "<" in reason:
            bucket = "low_score"
        elif "no_go" in lower:
            bucket = "no_go_verdict"
        elif "structure" in lower:
            bucket = "structure_blocked"
        elif "cap" in lower:
            bucket = "score_capped"
        elif "duplicate" in lower:
            bucket = "duplicate_position"
        elif "already hold" in lower:
            bucket = "already_held"
        elif "portfolio" in lower:
            bucket = "portfolio_full"
        elif "no trade_spec" in lower or "no legs" in lower:
            bucket = "no_trade_spec"
        else:
            bucket = reason[:30]
        reason_counts[bucket] = reason_counts.get(bucket, 0) + 1

        # Skip expected rejections from near-miss / missed-opp lists
        is_expected = any(tag in lower for tag in _EXPECTED_REJECTIONS)

        if 0.35 <= d.score < 0.50 and not is_expected:
            near_misses.append({
                "ticker": d.ticker, "strategy": d.strategy,
                "score": d.score, "gate_result": d.gate_result,
            })

        if d.score >= 0.50 and not is_expected:
            missed_opps.append({
                "ticker": d.ticker, "strategy": d.strategy,
                "score": d.score, "gate_result": d.gate_result,
            })

    narrative = (
        f"{len(decisions)} decisions: {len(approved)} approved, "
        f"{len(rejected)} rejected. "
    )
    if near_misses:
        narrative += f"{len(near_misses)} near-misses (score 0.35-0.50). "
    if missed_opps:
        narrative += (
            f"{len(missed_opps)} potential missed opportunities "
            f"(score >= 0.50 but rejected). "
        )

    return DecisionCommentary(
        near_misses=near_misses,
        missed_opportunities=missed_opps,
        rejection_summary=reason_counts,
        narrative=narrative,
    )
