"""Trade gate framework — classifies checks as hard/soft/informational.

Not all gates should block trades. This module:
1. Classifies every risk check as BLOCK / SCALE / WARN
2. Provides a single `evaluate_trade_gates()` function that runs all checks
3. Tracks rejected trades for shadow portfolio learning
4. Analyzes gate effectiveness from historical rejection data

Capital preservation gates BLOCK. Quality gates SCALE. Info gates WARN.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel


class GateAction(StrEnum):
    """What a gate does when it fires."""

    BLOCK = "block"    # Hard stop — trade does NOT proceed
    SCALE = "scale"    # Reduce position size but allow trade
    WARN = "warn"      # Log warning, allow trade at full size
    PASS = "pass"      # Gate passed — no action


class GateResult(BaseModel):
    """Result of a single gate check."""

    gate_name: str
    action: GateAction
    detail: str
    scale_factor: float = 1.0  # 1.0 = full size, 0.5 = half size, 0 = blocked
    category: str  # "capital_preservation", "quality", "concentration", "macro", "data"


class TradeGateReport(BaseModel):
    """Complete gate evaluation for a single trade."""

    ticker: str
    strategy: str
    gates: list[GateResult]
    final_action: GateAction     # Worst gate determines: BLOCK > SCALE > WARN > PASS
    final_scale_factor: float    # Product of all scale factors (0 if blocked)
    blocked_by: list[str]        # Names of gates that blocked
    scaled_by: list[str]         # Names of gates that scaled down
    warnings: list[str]          # Names of gates that warned
    can_proceed: bool            # True if final_action != BLOCK
    commentary: str


class RejectedTrade(BaseModel):
    """A trade that was rejected by gates — for shadow portfolio tracking."""

    rejected_date: date
    ticker: str
    strategy_type: str
    structure_type: str | None
    direction: str
    composite_score: float
    entry_price: float | None
    gate_blocked_by: list[str]   # Which gates blocked it
    gate_report: TradeGateReport
    # Shadow tracking (eTrading fills these later)
    hypothetical_exit_price: float | None = None
    hypothetical_pnl_pct: float | None = None
    would_have_won: bool | None = None


class GateEffectivenessReport(BaseModel):
    """Analysis of how well gates are performing — are they too tight or too loose?"""

    total_trades_evaluated: int
    total_passed: int
    total_blocked: int
    total_scaled: int
    block_rate_pct: float         # % of trades blocked

    # Per-gate effectiveness
    gate_stats: list[GateStats]

    # Shadow portfolio analysis
    shadow_trades: int            # How many rejected trades were tracked
    shadow_win_rate: float | None # Win rate of rejected trades (would they have won?)
    actual_win_rate: float | None # Win rate of accepted trades

    # Recommendation
    gates_too_tight: list[str]    # Gates that block good trades
    gates_too_loose: list[str]    # Gates that let bad trades through
    recommendation: str


class GateStats(BaseModel):
    """Effectiveness statistics for a single gate."""

    gate_name: str
    times_fired: int
    times_blocked: int
    times_scaled: int
    times_warned: int
    # When this gate blocked, what happened to the trade?
    blocked_trades_would_have_won_pct: float | None  # From shadow portfolio
    # When this gate passed, what happened?
    passed_trades_won_pct: float | None
    is_too_tight: bool  # Blocking too many winners
    is_too_loose: bool  # Letting too many losers through


# ═══ GATE DEFINITIONS ═══
# Which checks are BLOCK vs SCALE vs WARN

_GATE_CLASSIFICATION = {
    # Capital preservation — HARD BLOCKS (non-negotiable)
    "drawdown_circuit_breaker": GateAction.BLOCK,
    "macro_halt":              GateAction.BLOCK,   # DEFLATIONARY regime
    "position_limit":          GateAction.BLOCK,   # Max positions reached
    "buying_power":            GateAction.BLOCK,   # Not enough BP
    "max_portfolio_risk":      GateAction.BLOCK,   # Total risk > 25% NLV

    # Quality gates — SCALE DOWN (reduce size, don't block)
    "trade_quality_score":     GateAction.SCALE,   # POP+EV+R:R < threshold → half size
    "macro_regime_caution":    GateAction.SCALE,   # RISK_OFF/STAGFLATION → 50% size
    "iv_rank_missing":         GateAction.SCALE,   # No IV data → 75% size
    "execution_quality":       GateAction.SCALE,   # WIDE_SPREAD → 50% size
    "entry_window":            GateAction.SCALE,   # Outside optimal window → 75%

    # Concentration gates — WARN (alert but allow)
    "strategy_concentration":  GateAction.WARN,    # >50% in one strategy
    "directional_concentration": GateAction.WARN,  # Net bullish/bearish
    "correlation_risk":        GateAction.WARN,    # Correlated positions
    "ticker_limit":            GateAction.WARN,    # Approaching per-ticker max
    "sector_concentration":    GateAction.WARN,    # >30% in one sector

    # Informational — WARN (log, don't affect sizing)
    "model_staleness":         GateAction.WARN,    # Regime model > 60 days
    "data_gaps":               GateAction.WARN,    # Missing data in analysis
    "overnight_risk":          GateAction.WARN,    # Elevated overnight risk
}


def evaluate_trade_gates(
    ticker: str,
    strategy: str,
    trade_quality_score: float = 1.0,
    drawdown_triggered: bool = False,
    macro_regime: str = "risk_on",
    position_count: int = 0,
    max_positions: int = 5,
    bp_sufficient: bool = True,
    portfolio_risk_pct: float = 0.0,
    max_portfolio_risk_pct: float = 0.25,
    execution_verdict: str = "go",
    iv_rank_available: bool = True,
    strategy_concentrated: bool = False,
    directional_concentrated: bool = False,
    correlation_high: bool = False,
    ticker_at_limit: bool = False,
    sector_concentrated: bool = False,
    model_stale: bool = False,
    has_data_gaps: bool = False,
    in_entry_window: bool = True,
    overnight_risk_high: bool = False,
    min_quality_score: float = 0.50,
) -> TradeGateReport:
    """Evaluate ALL gates for a trade and return actionable report.

    Returns a report with:
    - Which gates fired (BLOCK/SCALE/WARN)
    - Final action (worst gate wins)
    - Final scale factor (product of all SCALE factors)
    - Whether trade can proceed
    """
    gates: list[GateResult] = []

    # ── HARD BLOCKS (capital preservation) ──

    if drawdown_triggered:
        gates.append(GateResult(
            gate_name="drawdown_circuit_breaker", action=GateAction.BLOCK,
            detail="Account drawdown exceeds threshold — ALL trading halted",
            scale_factor=0.0, category="capital_preservation",
        ))

    if macro_regime in ("deflationary",):
        gates.append(GateResult(
            gate_name="macro_halt", action=GateAction.BLOCK,
            detail=f"Macro regime '{macro_regime}' — trading halted",
            scale_factor=0.0, category="capital_preservation",
        ))

    if position_count >= max_positions:
        gates.append(GateResult(
            gate_name="position_limit", action=GateAction.BLOCK,
            detail=f"Portfolio full ({position_count}/{max_positions} positions)",
            scale_factor=0.0, category="capital_preservation",
        ))

    if not bp_sufficient:
        gates.append(GateResult(
            gate_name="buying_power", action=GateAction.BLOCK,
            detail="Insufficient buying power for this trade",
            scale_factor=0.0, category="capital_preservation",
        ))

    if portfolio_risk_pct > max_portfolio_risk_pct:
        gates.append(GateResult(
            gate_name="max_portfolio_risk", action=GateAction.BLOCK,
            detail=f"Portfolio risk {portfolio_risk_pct:.0%} exceeds {max_portfolio_risk_pct:.0%} limit",
            scale_factor=0.0, category="capital_preservation",
        ))

    # ── SCALE DOWN (quality gates) ──

    if trade_quality_score < min_quality_score:
        factor = max(0.25, trade_quality_score / min_quality_score)
        gates.append(GateResult(
            gate_name="trade_quality_score", action=GateAction.SCALE,
            detail=f"Trade quality {trade_quality_score:.2f} below {min_quality_score:.2f} — scaling to {factor:.0%}",
            scale_factor=factor, category="quality",
        ))

    if macro_regime in ("risk_off", "stagflation"):
        factor = 0.50 if macro_regime == "stagflation" else 0.60
        gates.append(GateResult(
            gate_name="macro_regime_caution", action=GateAction.SCALE,
            detail=f"Macro regime '{macro_regime}' — reducing size to {factor:.0%}",
            scale_factor=factor, category="macro",
        ))

    if not iv_rank_available:
        gates.append(GateResult(
            gate_name="iv_rank_missing", action=GateAction.SCALE,
            detail="IV rank unavailable — reduced confidence in premium assessment",
            scale_factor=0.75, category="data",
        ))

    if execution_verdict != "go":
        factor = 0.50 if execution_verdict == "wide_spread" else 0.0
        action = GateAction.SCALE if factor > 0 else GateAction.BLOCK
        gates.append(GateResult(
            gate_name="execution_quality", action=action,
            detail=f"Execution quality: {execution_verdict}",
            scale_factor=factor, category="quality",
        ))

    if not in_entry_window:
        gates.append(GateResult(
            gate_name="entry_window", action=GateAction.SCALE,
            detail="Outside optimal entry window — fills may be worse",
            scale_factor=0.75, category="quality",
        ))

    # ── WARNINGS (informational) ──

    if strategy_concentrated:
        gates.append(GateResult(
            gate_name="strategy_concentration", action=GateAction.WARN,
            detail="Portfolio >50% in one strategy type — consider diversifying",
            category="concentration",
        ))

    if directional_concentrated:
        gates.append(GateResult(
            gate_name="directional_concentration", action=GateAction.WARN,
            detail="Portfolio directionally concentrated — net bullish or bearish exposure",
            category="concentration",
        ))

    if correlation_high:
        gates.append(GateResult(
            gate_name="correlation_risk", action=GateAction.WARN,
            detail="New trade highly correlated with existing positions",
            category="concentration",
        ))

    if ticker_at_limit:
        gates.append(GateResult(
            gate_name="ticker_limit", action=GateAction.WARN,
            detail=f"Approaching per-ticker position limit for {ticker}",
            category="concentration",
        ))

    if sector_concentrated:
        gates.append(GateResult(
            gate_name="sector_concentration", action=GateAction.WARN,
            detail="Sector concentration approaching limit",
            category="concentration",
        ))

    if model_stale:
        gates.append(GateResult(
            gate_name="model_staleness", action=GateAction.WARN,
            detail="Regime model > 60 days old — consider retraining",
            category="data",
        ))

    if has_data_gaps:
        gates.append(GateResult(
            gate_name="data_gaps", action=GateAction.WARN,
            detail="Analysis has data gaps — check data_gaps field for details",
            category="data",
        ))

    if overnight_risk_high:
        gates.append(GateResult(
            gate_name="overnight_risk", action=GateAction.WARN,
            detail="Elevated overnight gap risk for this position",
            category="capital_preservation",
        ))

    # If no gates fired, add a PASS
    if not gates:
        gates.append(GateResult(
            gate_name="all_clear", action=GateAction.PASS,
            detail="All gates passed — trade approved",
            category="quality",
        ))

    # ── Compute final action ──

    blocked = [g for g in gates if g.action == GateAction.BLOCK]
    scaled = [g for g in gates if g.action == GateAction.SCALE]
    warned = [g for g in gates if g.action == GateAction.WARN]

    if blocked:
        final_action = GateAction.BLOCK
        final_scale = 0.0
    elif scaled:
        final_action = GateAction.SCALE
        final_scale = 1.0
        for g in scaled:
            final_scale *= g.scale_factor
        final_scale = max(0.25, final_scale)  # Floor at 25%
    else:
        final_action = GateAction.PASS
        final_scale = 1.0

    # Commentary
    if blocked:
        commentary = f"BLOCKED by {', '.join(g.gate_name for g in blocked)}. Trade does not proceed."
    elif scaled:
        commentary = f"SCALED to {final_scale:.0%} by {', '.join(g.gate_name for g in scaled)}."
        if warned:
            commentary += f" Warnings: {', '.join(g.gate_name for g in warned)}."
    elif warned:
        commentary = f"APPROVED with warnings: {', '.join(g.gate_name for g in warned)}."
    else:
        commentary = "APPROVED — all gates clear."

    return TradeGateReport(
        ticker=ticker, strategy=strategy,
        gates=gates,
        final_action=final_action,
        final_scale_factor=round(final_scale, 3),
        blocked_by=[g.gate_name for g in blocked],
        scaled_by=[g.gate_name for g in scaled],
        warnings=[g.gate_name for g in warned],
        can_proceed=final_action != GateAction.BLOCK,
        commentary=commentary,
    )


def analyze_gate_effectiveness(
    gate_history: list[dict],
    shadow_outcomes: list[RejectedTrade] | None = None,
    actual_outcomes: list[dict] | None = None,
) -> GateEffectivenessReport:
    """Analyze how well gates are performing — are they too tight or too loose?

    Args:
        gate_history: List of {gate_name, action, ticker, date} from eTrading logs
        shadow_outcomes: Rejected trades with hypothetical P&L (from shadow portfolio)
        actual_outcomes: Accepted trades with actual P&L

    Returns:
        Report showing which gates are too tight (blocking winners) or too loose (allowing losers)
    """
    from collections import defaultdict

    total = len(gate_history)
    passed = sum(1 for g in gate_history if g.get("action") == "pass")
    blocked = sum(1 for g in gate_history if g.get("action") == "block")
    scaled = sum(1 for g in gate_history if g.get("action") == "scale")
    block_rate = blocked / total * 100 if total > 0 else 0

    # Per-gate stats
    gate_fires: dict[str, dict] = defaultdict(lambda: {
        "fired": 0, "blocked": 0, "scaled": 0, "warned": 0,
    })
    for g in gate_history:
        name = g.get("gate_name", "unknown")
        gate_fires[name]["fired"] += 1
        action = g.get("action", "pass")
        if action == "block":
            gate_fires[name]["blocked"] += 1
        elif action == "scale":
            gate_fires[name]["scaled"] += 1
        elif action == "warn":
            gate_fires[name]["warned"] += 1

    # Shadow portfolio analysis
    shadow_win_rate = None
    if shadow_outcomes:
        with_results = [s for s in shadow_outcomes if s.would_have_won is not None]
        if with_results:
            shadow_win_rate = sum(1 for s in with_results if s.would_have_won) / len(with_results)

    # Actual outcomes
    actual_win_rate = None
    if actual_outcomes:
        wins = sum(1 for o in actual_outcomes if o.get("pnl_pct", 0) > 0)
        actual_win_rate = wins / len(actual_outcomes) if actual_outcomes else None

    # Build gate stats
    gate_stats = []
    gates_too_tight = []
    gates_too_loose = []

    for name, counts in gate_fires.items():
        # A gate is "too tight" if it blocks trades that would have won > 60%
        blocked_would_win = None
        if shadow_outcomes:
            blocked_by_this = [s for s in shadow_outcomes if name in s.gate_blocked_by and s.would_have_won is not None]
            if len(blocked_by_this) >= 5:
                blocked_would_win = sum(1 for s in blocked_by_this if s.would_have_won) / len(blocked_by_this)

        is_tight = blocked_would_win is not None and blocked_would_win > 0.60
        is_loose = False  # Would need pass-through outcome data

        if is_tight:
            gates_too_tight.append(name)

        gate_stats.append(GateStats(
            gate_name=name,
            times_fired=counts["fired"],
            times_blocked=counts["blocked"],
            times_scaled=counts["scaled"],
            times_warned=counts["warned"],
            blocked_trades_would_have_won_pct=round(blocked_would_win * 100, 1) if blocked_would_win is not None else None,
            passed_trades_won_pct=None,
            is_too_tight=is_tight,
            is_too_loose=is_loose,
        ))

    # Recommendation
    if gates_too_tight:
        rec = f"Gates too tight: {', '.join(gates_too_tight)}. These are blocking profitable trades. Consider relaxing thresholds."
    elif block_rate > 80:
        rec = "Block rate >80% — system is too conservative. Very few trades will pass. Review thresholds."
    elif shadow_win_rate is not None and shadow_win_rate > 0.65:
        rec = f"Shadow portfolio win rate {shadow_win_rate:.0%} — rejected trades are profitable. Loosen gates."
    elif actual_win_rate is not None and actual_win_rate < 0.40:
        rec = f"Actual win rate {actual_win_rate:.0%} — gates are too loose. Tighten quality thresholds."
    else:
        rec = "Gates appear well-calibrated. Monitor shadow portfolio for drift."

    return GateEffectivenessReport(
        total_trades_evaluated=total,
        total_passed=passed,
        total_blocked=blocked,
        total_scaled=scaled,
        block_rate_pct=round(block_rate, 1),
        gate_stats=gate_stats,
        shadow_trades=len(shadow_outcomes) if shadow_outcomes else 0,
        shadow_win_rate=round(shadow_win_rate, 3) if shadow_win_rate is not None else None,
        actual_win_rate=round(actual_win_rate, 3) if actual_win_rate is not None else None,
        gates_too_tight=gates_too_tight,
        gates_too_loose=gates_too_loose,
        recommendation=rec,
    )
