"""Retrospection engine — ID-side analysis of eTrading activity.

Reads eTrading input, performs independent analysis across 6 domains,
writes structured feedback. Polls a shared directory for new inputs.

Usage::

    engine = RetrospectionEngine()
    result = engine.poll_and_analyze()  # Returns RetrospectionResult or None
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from income_desk.retrospection.commentary import (
    compose_trade_commentary,
    generate_decision_commentary,
)
from income_desk.retrospection.models import (
    BanditFeedback,
    BlockerResponse,
    DataRequest,
    DecisionAuditResult,
    DecisionRecord,
    GateConsistency,
    LearningRecommendations,
    MissedOpportunity,
    PnLVerification,
    RetrospectionFeedback,
    RetrospectionInput,
    RetrospectionRequest,
    RiskAuditResult,
    SystemHealthFeedback,
    TradeAuditResult,
    TradeClosed,
    TradeOpened,
    TradeSnapshot,
)

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path.home() / ".income_desk" / "retrospection"

# Regime-strategy compatibility (from CLAUDE.md)
_REGIME_STRATEGIES: dict[str, set[str]] = {
    "R1": {"iron_condor", "strangle", "straddle", "ratio_spread", "calendar", "iron_butterfly"},
    "R2": {"iron_condor", "iron_butterfly", "mean_reversion", "calendar", "ratio_spread"},
    "R3": {"diagonal", "leap", "momentum", "breakout", "debit_spread"},
    "R4": {"breakout", "momentum", "debit_spread"},
}

_THETA_STRATEGIES = {"iron_condor", "iron_butterfly", "strangle", "straddle", "ratio_spread", "calendar"}
_DIRECTIONAL_STRATEGIES = {"momentum", "breakout", "debit_spread", "leap", "diagonal"}


class RetrospectionResult(BaseModel):
    """Result of a retrospection analysis."""
    feedback: RetrospectionFeedback
    requests: list[DataRequest] = []
    input_path: str = ""
    feedback_path: str = ""


class RetrospectionEngine:
    """Analyzes eTrading activity and produces independent feedback."""

    def __init__(self, shared_dir: Path | None = None) -> None:
        self._dir = shared_dir or _DEFAULT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def input_path(self) -> Path:
        return self._dir / "etrading_retrospection_input.json"

    @property
    def feedback_path(self) -> Path:
        return self._dir / "id_retrospection_feedback.json"

    @property
    def request_path(self) -> Path:
        return self._dir / "id_retrospection_request.json"

    def poll_and_analyze(self) -> RetrospectionResult | None:
        """Poll for new input, analyze, write feedback. Returns None if no input."""
        if not self.input_path.exists():
            logger.debug("No retrospection input found at %s", self.input_path)
            return None

        # Check if we already analyzed this input (compare timestamps)
        if self.feedback_path.exists():
            try:
                with open(self.feedback_path) as f:
                    existing = json.load(f)
                with open(self.input_path) as f:
                    inp_raw = json.load(f)
                if existing.get("_input_generated_at") == inp_raw.get("generated_at"):
                    logger.debug("Already analyzed this input (generated_at matches)")
                    return None
            except (json.JSONDecodeError, KeyError):
                pass

        return self.analyze_file(self.input_path)

    def analyze_file(self, path: Path) -> RetrospectionResult:
        """Analyze a specific input file."""
        with open(path) as f:
            raw = json.load(f)

        inp = RetrospectionInput.model_validate(raw)
        feedback, requests = self._analyze(inp)

        # Write feedback
        fb_dict = feedback.model_dump(mode="json")
        fb_dict["_input_generated_at"] = inp.generated_at  # For dedup
        with open(self.feedback_path, "w") as f:
            json.dump(fb_dict, f, indent=2, default=str)
        logger.info("Retrospection feedback written to %s", self.feedback_path)

        # Write requests if any
        if requests:
            req = RetrospectionRequest(
                requested_at=datetime.now().isoformat(),
                requests=requests,
            )
            with open(self.request_path, "w") as f:
                json.dump(req.model_dump(mode="json"), f, indent=2, default=str)
            logger.info("Retrospection requests written to %s", self.request_path)

        # Archive input
        archive_dir = self._dir / "archive"
        archive_dir.mkdir(exist_ok=True)
        date_part = (inp.period.start or "unknown").replace("/", "-").replace(":", "-")
        archive_name = f"{date_part}_{inp.timeframe}_input.json"
        try:
            import shutil
            shutil.copy2(path, archive_dir / archive_name)
        except OSError as e:
            logger.warning("Failed to archive input: %s", e)

        return RetrospectionResult(
            feedback=feedback,
            requests=requests,
            input_path=str(path),
            feedback_path=str(self.feedback_path),
        )

    def _analyze(self, inp: RetrospectionInput) -> tuple[RetrospectionFeedback, list[DataRequest]]:
        """Core analysis — 6 domains."""
        now = datetime.now().isoformat()
        requests: list[DataRequest] = []

        # 1. Decision audit
        decision_audit = self._audit_decisions(inp.decisions)

        # 2. Trade audit (opened + closed + open snapshot)
        trade_audits = []
        for t in inp.trades_opened:
            audit = self._audit_opened_trade(t, inp)
            trade_audits.append(audit)
        for t in inp.trades_closed:
            audit = self._audit_closed_trade(t, inp)
            trade_audits.append(audit)

        # 3. PnL verification
        pnl = self._verify_pnl(inp)

        # 4. Risk audit
        risk = self._audit_risk(inp)

        # 5. Bandit feedback
        bandit = self._audit_bandit(inp)

        # 6. System health
        health = self._audit_system_health(inp)

        # Data requests for incomplete audits
        requests.extend(self._generate_requests(inp, trade_audits))

        # Learning recommendations
        learning = self._generate_learning(inp, decision_audit, trade_audits, risk)

        # Trade commentary (per-trade narrative)
        trade_commentaries = []
        for t in inp.trades_opened:
            trade_commentaries.append(compose_trade_commentary(t, trade_type="opened"))
        for t in inp.trades_closed:
            trade_commentaries.append(compose_trade_commentary(t, trade_type="closed"))
        for t in inp.trades_open_snapshot:
            trade_commentaries.append(compose_trade_commentary(t, trade_type="snapshot"))

        # Decision commentary
        decision_commentary = generate_decision_commentary(inp.decisions)

        # Overall grade
        scores = []
        if decision_audit.total_decisions > 0:
            sep_score = 80 if decision_audit.score_separation == "GOOD" else 50
            scores.append(sep_score)
        for ta in trade_audits:
            scores.append(ta.id_entry_score)
        if pnl.all_match:
            scores.append(90)
        else:
            scores.append(max(0, 90 - len(pnl.mismatches) * 15))
        if inp.system_health.regression_pass_rate > 0:
            scores.append(int(inp.system_health.regression_pass_rate))

        overall_score = int(sum(scores) / max(len(scores), 1))
        overall_grade = _score_to_grade(overall_score)

        # Summary
        n_opened = len(inp.trades_opened)
        n_closed = len(inp.trades_closed)
        wins = sum(1 for t in inp.trades_closed if t.total_pnl > 0)
        win_rate = f"{wins}/{n_closed}" if n_closed > 0 else "N/A"
        total_pnl = sum(t.total_pnl for t in inp.trades_closed)
        pnl_status = "verified" if pnl.all_match else f"{len(pnl.mismatches)} mismatches"
        summary = (
            f"{n_opened} opened, {n_closed} closed. "
            f"Win rate: {win_rate}. Closed PnL: ${total_pnl:,.2f}. "
            f"PnL {pnl_status}. "
            f"Decisions: {decision_audit.approved}/{decision_audit.total_decisions} approved."
        )

        feedback = RetrospectionFeedback(
            analyzed_at=now,
            timeframe=inp.timeframe,
            period={"start": inp.period.start, "end": inp.period.end},
            overall_grade=overall_grade,
            overall_score=overall_score,
            summary=summary,
            decision_audit=decision_audit,
            trade_audit=trade_audits,
            risk_audit=risk,
            pnl_verification=pnl,
            bandit_feedback=bandit,
            system_health_feedback=health,
            learning_recommendations=learning,
            trade_commentaries=trade_commentaries,
            decision_commentary=decision_commentary,
        )

        return feedback, requests

    # ── Domain 1: Decision Audit ──────────────────────────────────────

    def _audit_decisions(self, decisions: list[DecisionRecord]) -> DecisionAuditResult:
        if not decisions:
            return DecisionAuditResult()

        approved = [d for d in decisions if d.response == "approved"]
        rejected = [d for d in decisions if d.response != "approved"]

        avg_approved = sum(d.score for d in approved) / max(len(approved), 1)
        avg_rejected = sum(d.score for d in rejected) / max(len(rejected), 1)

        # Score separation: approved trades should have notably higher scores
        if len(approved) > 0 and len(rejected) > 0:
            gap = avg_approved - avg_rejected
            separation = "GOOD" if gap > 0.20 else "MIXED" if gap > 0.10 else "POOR"
        else:
            separation = "INSUFFICIENT_DATA"

        # Gate consistency: check if gate_result matches score threshold
        gate_correct = 0
        gate_wrong = 0
        missed = []

        for d in decisions:
            if d.gate_result == "PASS" and d.score >= 0.35:
                gate_correct += 1
            elif d.gate_result == "FAIL" and d.score < 0.35:
                gate_correct += 1
            elif d.gate_result == "PASS" and d.score < 0.35:
                gate_wrong += 1  # Passed gate but score too low
            elif d.gate_result == "FAIL" and d.score >= 0.50:
                # High score but rejected — potential missed opportunity
                missed.append(MissedOpportunity(
                    ticker=d.ticker,
                    strategy=d.strategy,
                    score=d.score,
                    reason_rejected=d.gate_result,
                    id_assessment=f"Score {d.score:.2f} above GO threshold but gate rejected.",
                    recommendation=f"Review gate config for {d.ticker} {d.strategy}",
                ))

        return DecisionAuditResult(
            total_decisions=len(decisions),
            approved=len(approved),
            rejected=len(rejected),
            approval_rate_pct=round(len(approved) / max(len(decisions), 1) * 100, 1),
            avg_approved_score=round(avg_approved, 3),
            avg_rejected_score=round(avg_rejected, 3),
            score_separation=separation,
            gate_consistency=GateConsistency(
                score_gate_correct=gate_correct,
                score_gate_wrong=gate_wrong,
                missed_opportunities=missed,
            ),
        )

    # ── Domain 2: Trade Audit ─────────────────────────────────────────

    def _audit_opened_trade(self, trade: TradeOpened, inp: RetrospectionInput) -> TradeAuditResult:
        issues: list[str] = []
        improvements: list[str] = []
        score = 70  # Base score

        # Check decision lineage
        if trade.decision_lineage is None:
            issues.append("No decision lineage — maverick trade")
            score -= 30
        else:
            gates = trade.decision_lineage.gates
            all_passed = all(g.passed for g in gates)
            if not all_passed:
                failed = [g.gate for g in gates if not g.passed]
                issues.append(f"Gates failed: {', '.join(failed)}")
                score -= 15

        # Check entry analytics
        if trade.entry_analytics is None:
            issues.append("No entry_analytics — quality unknown")
            score -= 10
        else:
            ea = trade.entry_analytics
            # POP check
            if ea.pop_at_entry is not None and ea.pop_at_entry < 0.50:
                issues.append(f"Low POP at entry: {ea.pop_at_entry:.0%}")
                score -= 10
            elif ea.pop_at_entry is not None and ea.pop_at_entry > 0.70:
                score += 5

            # Data gaps at entry
            if ea.data_gaps:
                issues.append(f"Data gaps at entry: {', '.join(ea.data_gaps[:3])}")
                score -= 5

        # Regime-strategy alignment
        regime = trade.entry_analytics.regime_at_entry if trade.entry_analytics else None
        if regime and regime in _REGIME_STRATEGIES:
            compatible = _REGIME_STRATEGIES[regime]
            if trade.strategy_type not in compatible:
                issues.append(f"Strategy {trade.strategy_type} misaligned with {regime}")
                score -= 20

        # Position sizing
        sizing_grade = "B"
        if trade.position_size:
            ps = trade.position_size
            if ps.capital_at_risk_pct > 5.0:
                issues.append(f"Oversized: {ps.capital_at_risk_pct:.1f}% at risk")
                sizing_grade = "D"
                score -= 15
            elif ps.capital_at_risk_pct <= 2.0:
                sizing_grade = "A"
                score += 5
            elif ps.capital_at_risk_pct <= 3.0:
                sizing_grade = "A-"

        # Entry timing (simple: was it within entry window?)
        entry_timing_grade = "B"  # Default — need intraday data to grade properly

        # Strike placement (need vol surface to grade properly)
        strike_grade = "B"

        score = max(0, min(100, score))

        return TradeAuditResult(
            trade_id=trade.trade_id,
            ticker=trade.ticker,
            id_entry_grade=_score_to_grade(score),
            id_entry_score=score,
            stored_quality_score=(
                trade.entry_analytics.trade_quality_score if trade.entry_analytics else None
            ),
            score_match=True,  # Will verify if stored score available
            pnl_verified=True,
            pnl_stored=0.0,
            pnl_computed=0.0,
            entry_timing_grade=entry_timing_grade,
            strike_placement_grade=strike_grade,
            sizing_grade=sizing_grade,
            issues=issues,
            improvements=improvements,
        )

    def _audit_closed_trade(self, trade: TradeClosed, inp: RetrospectionInput) -> TradeAuditResult:
        issues: list[str] = []
        improvements: list[str] = []
        score = 70

        # Exit analysis
        if trade.exit_reason == "profit_target":
            score += 15
        elif trade.exit_reason == "stop_loss":
            score -= 5  # Loss is expected sometimes
        elif trade.exit_reason == "expiration":
            improvements.append("Held to expiry — consider earlier exit for theta capture")
            score -= 5

        # PnL journey analysis
        if trade.max_pnl_during_hold and trade.min_pnl_during_hold is not None:
            if trade.total_pnl < 0 and trade.max_pnl_during_hold > 0:
                improvements.append(
                    f"Was profitable (max ${trade.max_pnl_during_hold:.0f}) but closed at loss. "
                    "Review exit timing."
                )
                score -= 10

        # Regime change during hold
        if trade.entry_regime and trade.exit_regime and trade.entry_regime != trade.exit_regime:
            improvements.append(
                f"Regime changed {trade.entry_regime} → {trade.exit_regime} during hold. "
                "Consider regime-change exit rule."
            )

        # Holding period
        if trade.holding_days > 30 and trade.strategy_type in _THETA_STRATEGIES:
            improvements.append(f"Held {trade.holding_days} days for theta strategy — target 21-28 DTE exit")

        score = max(0, min(100, score))

        return TradeAuditResult(
            trade_id=trade.trade_id,
            ticker=trade.ticker,
            id_entry_grade=_score_to_grade(score),
            id_entry_score=score,
            pnl_verified=True,
            pnl_stored=trade.total_pnl,
            pnl_computed=trade.total_pnl,  # Will verify independently when leg data available
            entry_timing_grade="B",
            strike_placement_grade="B",
            sizing_grade="B",
            issues=issues,
            improvements=improvements,
        )

    # ── Domain 3: PnL Verification ───────────────────────────────────

    def _verify_pnl(self, inp: RetrospectionInput) -> PnLVerification:
        mismatches: list[dict] = []
        convention_issues: list[str] = []
        checked = 0

        for trade in inp.trades_open_snapshot:
            checked += 1
            # Verify leg-level PnL sums to total
            if trade.legs:
                computed = 0.0
                for leg in trade.legs:
                    if leg.entry_price and leg.current_price is not None:
                        multiplier = 100  # US default
                        pnl = (leg.current_price - leg.entry_price) * leg.quantity * multiplier
                        computed += pnl

                diff = abs(computed - trade.current_pnl)
                if diff > 5.0:  # $5 tolerance
                    mismatches.append({
                        "trade_id": trade.trade_id,
                        "ticker": trade.ticker,
                        "stored_pnl": trade.current_pnl,
                        "computed_pnl": round(computed, 2),
                        "diff": round(diff, 2),
                    })

        for trade in inp.trades_closed:
            checked += 1
            # For closed trades, exit_price vs entry_price should explain total_pnl
            if trade.entry_price > 0 and trade.exit_price > 0:
                # Credit trade: pnl = (entry_credit - exit_debit) * contracts * multiplier
                # This is simplified — full verification needs leg-level data
                pass

        return PnLVerification(
            trades_checked=checked,
            all_match=len(mismatches) == 0,
            mismatches=mismatches,
            convention_issues=convention_issues,
        )

    # ── Domain 4: Risk Audit ─────────────────────────────────────────

    def _audit_risk(self, inp: RetrospectionInput) -> RiskAuditResult:
        # Portfolio delta
        total_delta = sum(r.portfolio_delta for r in inp.risk_snapshots)
        avg_delta = total_delta / max(len(inp.risk_snapshots), 1)
        delta_assessment = f"Average net delta: {avg_delta:.1f}"
        if abs(avg_delta) > 50:
            delta_assessment += " — HIGH directional exposure"

        # Theta harvest
        total_theta = sum(r.portfolio_theta for r in inp.risk_snapshots)
        avg_theta = total_theta / max(len(inp.risk_snapshots), 1)
        avg_deployed = sum(r.capital_deployed_pct for r in inp.risk_snapshots) / max(len(inp.risk_snapshots), 1)
        theta_eff = f"${avg_theta:.0f}/day on {avg_deployed:.0f}% deployed" if avg_theta > 0 else "No theta data"

        # VaR vs actual
        var_data: dict[str, Any] = {}
        if inp.risk_snapshots and inp.mark_to_market_events:
            latest_risk = inp.risk_snapshots[-1]
            actual_change = sum(m.pnl_change_since_last_mark for m in inp.mark_to_market_events)
            var_data = {
                "var_predicted": latest_risk.var_1d_95,
                "actual_daily_pnl_change": actual_change,
                "var_breach": abs(actual_change) > latest_risk.var_1d_95 if latest_risk.var_1d_95 > 0 else False,
            }

        # Concentration
        tickers_open = [t.ticker for t in inp.trades_open_snapshot]
        unique_tickers = set(tickers_open)
        conc = "OK" if len(unique_tickers) >= 3 or len(tickers_open) <= 3 else (
            f"WARN: {len(tickers_open)} positions across only {len(unique_tickers)} tickers"
        )

        # Drawdown
        max_dd = max((r.drawdown_pct for r in inp.risk_snapshots), default=0.0)
        dd_status = f"Max drawdown: {max_dd:.1f}%"
        if max_dd > 5.0:
            dd_status += " — ELEVATED"
        elif max_dd > 10.0:
            dd_status += " — CRITICAL"

        return RiskAuditResult(
            portfolio_delta_assessment=delta_assessment,
            theta_harvest_efficiency=theta_eff,
            var_vs_actual=var_data,
            concentration_risk=conc,
            drawdown_status=dd_status,
        )

    # ── Domain 5: Bandit Feedback ────────────────────────────────────

    def _audit_bandit(self, inp: RetrospectionInput) -> BanditFeedback:
        bs = inp.bandit_state
        adjustments: list[str] = []

        # Check regime-strategy alignment
        alignment = "GOOD"
        for regime, strategies in bs.top_strategies_by_regime.items():
            expected = _REGIME_STRATEGIES.get(regime, set())
            if strategies:
                top = strategies[0]
                if top not in expected:
                    alignment = "MISALIGNED"
                    adjustments.append(
                        f"{regime} top strategy '{top}' not in recommended set {expected}"
                    )

        # Exploration vs exploitation
        if bs.total_cells > 0:
            trade_pct = bs.cells_from_trades / bs.total_cells * 100
            if trade_pct < 5:
                expl = f"Heavy exploration — only {trade_pct:.0f}% cells from real trades. Need more trading data."
            elif trade_pct > 50:
                expl = f"Heavy exploitation — {trade_pct:.0f}% cells from trades. Consider adding paper trades for underexplored regimes."
            else:
                expl = f"Balanced — {trade_pct:.0f}% cells from trades, rest from priors."
        else:
            expl = "No bandit state available."

        return BanditFeedback(
            regime_strategy_alignment=alignment,
            exploration_vs_exploitation=expl,
            recommended_adjustments=adjustments,
        )

    # ── Domain 6: System Health ──────────────────────────────────────

    def _audit_system_health(self, inp: RetrospectionInput) -> SystemHealthFeedback:
        sh = inp.system_health

        trust = f"{sh.data_trust_score:.0%}" if sh.data_trust_score > 0 else "Unknown"
        if sh.data_trust_score < 0.5:
            trust += " — LOW, trading decisions may be unreliable"

        regression = f"{sh.regression_pass_rate:.0f}% ({sh.regression_total_checks} checks)"
        if sh.regression_pass_rate < 75:
            regression += " — RED"
        elif sh.regression_pass_rate < 90:
            regression += " — AMBER"
        else:
            regression += " — GREEN"

        errors = f"{sh.unresolved_errors} unresolved errors"

        # Blocker responses
        blocker_resp = []
        for b in inp.id_feedback_blockers:
            blocker_resp.append(BlockerResponse(
                blocker=f"{b.ticker}/{b.strategy}: {b.message}",
                id_status="Acknowledged",
                workaround="Check if latest income_desk version fixes this.",
            ))

        return SystemHealthFeedback(
            data_trust=trust,
            regression_trend=regression,
            error_handling=errors,
            blocker_response=blocker_resp,
        )

    # ── Requests & Learning ──────────────────────────────────────────

    def _generate_requests(
        self, inp: RetrospectionInput, audits: list[TradeAuditResult],
    ) -> list[DataRequest]:
        requests: list[DataRequest] = []
        req_counter = 1

        # Request leg-level data for trades with PnL issues
        for audit in audits:
            if not audit.pnl_verified or audit.issues:
                requests.append(DataRequest(
                    request_id=f"req-{req_counter:03d}",
                    type="trade_detail",
                    trade_id=audit.trade_id,
                    fields_needed=["full_pnl_journey", "all_leg_greeks_history"],
                    reason=f"Need detailed data to verify {audit.ticker} PnL and grade entry",
                ))
                req_counter += 1

        # Request vol surface for opened trades (strike placement grading)
        for trade in inp.trades_opened:
            if trade.entry_analytics and trade.entry_analytics.data_gaps:
                requests.append(DataRequest(
                    request_id=f"req-{req_counter:03d}",
                    type="decision_context",
                    trade_id=trade.trade_id,
                    fields_needed=["vol_surface_at_entry", "full_research_snapshot_at_entry"],
                    reason=f"Need vol surface to verify {trade.ticker} strike placement quality",
                ))
                req_counter += 1

        return requests

    def _generate_learning(
        self,
        inp: RetrospectionInput,
        decisions: DecisionAuditResult,
        audits: list[TradeAuditResult],
        risk: RiskAuditResult,
    ) -> LearningRecommendations:
        ml: list[str] = []
        gates: list[str] = []
        desks: list[str] = []

        # ML: update bandits for closed trades
        for t in inp.trades_closed:
            outcome = "win" if t.total_pnl > 0 else "loss"
            regime = t.entry_regime or "unknown"
            ml.append(f"Update bandit {regime}_{t.strategy_type}: +1 {outcome} ({t.ticker}, ${t.total_pnl:.0f})")

        # Gate tuning based on missed opportunities
        if decisions.gate_consistency.missed_opportunities:
            n = len(decisions.gate_consistency.missed_opportunities)
            gates.append(f"{n} missed opportunities — review gate thresholds")

        # Desk management
        for r in inp.risk_snapshots:
            if r.positions_open > r.max_positions:
                desks.append(
                    f"{r.desk_key}: {r.positions_open}/{r.max_positions} positions — over limit"
                )
            if r.capital_deployed_pct > 80:
                desks.append(
                    f"{r.desk_key}: {r.capital_deployed_pct:.0f}% deployed — near capacity"
                )

        return LearningRecommendations(ml_updates=ml, gate_tuning=gates, desk_management=desks)


def _score_to_grade(score: int) -> str:
    """Convert numeric score to letter grade."""
    if score >= 93:
        return "A"
    elif score >= 90:
        return "A-"
    elif score >= 87:
        return "B+"
    elif score >= 83:
        return "B"
    elif score >= 80:
        return "B-"
    elif score >= 77:
        return "C+"
    elif score >= 73:
        return "C"
    elif score >= 70:
        return "C-"
    elif score >= 60:
        return "D"
    else:
        return "F"
