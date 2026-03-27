"""Release readiness validation — exercises every API along the trading workflow.

Runs deterministic test scenarios across all 8 workflow stages, captures exact
API call signatures (inputs + outputs) so eTrading can replay and verify its
implementation, and produces a GO / NO-GO release verdict.

Designed to run daily as part of CI or manually before releases.

Usage::

    from income_desk.regression.release_readiness import run_release_readiness
    report = run_release_readiness()
    report.write_html("release_readiness.html")
    report.write_manifest("release_readiness_manifest.json")
"""

from __future__ import annotations

import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time as dt_time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from income_desk.adapters.simulated import (
    SimulatedMarketData,
    SimulatedMetrics,
    create_ideal_income,
    create_india_trading,
)


# ── Models ──────────────────────────────────────────────────────────────────


class StageVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIP = "SKIP"


class APICall(BaseModel):
    """A single API call with inputs, outputs, and invariant checks."""

    api: str  # Function name
    module: str  # Module path
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] | None = None
    output_type: str = ""
    invariants_checked: list[str] = Field(default_factory=list)
    invariants_passed: list[bool] = Field(default_factory=list)
    error: str | None = None
    duration_ms: float = 0


class StageResult(BaseModel):
    """Result of validating one workflow stage."""

    stage: str
    stage_number: int
    description: str
    verdict: StageVerdict = StageVerdict.PASS
    api_calls: list[APICall] = Field(default_factory=list)
    duration_ms: float = 0
    error: str | None = None
    notes: list[str] = Field(default_factory=list)

    @property
    def total_invariants(self) -> int:
        return sum(len(c.invariants_checked) for c in self.api_calls)

    @property
    def passed_invariants(self) -> int:
        return sum(sum(c.invariants_passed) for c in self.api_calls)

    @property
    def failed_invariants(self) -> int:
        return self.total_invariants - self.passed_invariants


class ReadinessReport(BaseModel):
    """Complete release readiness report."""

    version: str = ""
    run_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    run_date: str = Field(default_factory=lambda: date.today().isoformat())
    markets_tested: list[str] = Field(default_factory=list)
    stages: list[StageResult] = Field(default_factory=list)
    regression_result: dict[str, Any] | None = None
    overall_verdict: str = "NO-GO"
    total_apis_tested: int = 0
    total_invariants: int = 0
    passed_invariants: int = 0
    duration_ms: float = 0
    gaps_found: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)

    def compute_verdict(self) -> None:
        """Compute overall verdict from stage results."""
        self.total_apis_tested = sum(len(s.api_calls) for s in self.stages)
        self.total_invariants = sum(s.total_invariants for s in self.stages)
        self.passed_invariants = sum(s.passed_invariants for s in self.stages)

        failed_stages = [s for s in self.stages if s.verdict == StageVerdict.FAIL]
        if not failed_stages and self.total_invariants > 0:
            pass_rate = self.passed_invariants / self.total_invariants
            if pass_rate >= 0.95:
                self.overall_verdict = "GO"
            elif pass_rate >= 0.80:
                self.overall_verdict = "CONDITIONAL-GO"
            else:
                self.overall_verdict = "NO-GO"
        elif not failed_stages:
            self.overall_verdict = "GO"
        else:
            self.overall_verdict = "NO-GO"


# ── Helpers ─────────────────────────────────────────────────────────────────


def _serialize(obj: Any) -> Any:
    """Make any object JSON-serializable."""
    if obj is None:
        return None
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, (list, tuple)):
        return [_serialize(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dt_time):
        return obj.isoformat()
    if isinstance(obj, StrEnum):
        return obj.value
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


def _check(call: APICall, description: str, condition: bool) -> None:
    """Record an invariant check."""
    call.invariants_checked.append(description)
    call.invariants_passed.append(condition)


def _run_api(
    api_name: str,
    module: str,
    func: callable,
    inputs: dict[str, Any],
    invariant_checks: callable | None = None,
) -> APICall:
    """Execute an API call, capture timing, serialize I/O, run invariant checks.

    ``func`` is a zero-arg callable (lambda that captures its arguments).
    ``inputs`` is for documentation only — recorded in the manifest for replay.
    """
    call = APICall(api=api_name, module=module, inputs=_serialize(inputs))
    t0 = time.perf_counter()
    try:
        result = func()
        call.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        call.outputs = _serialize(result)
        call.output_type = type(result).__name__ if result is not None else "None"
        if invariant_checks:
            invariant_checks(call, result)
    except Exception as e:
        call.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        call.error = f"{type(e).__name__}: {e}"
    return call


# ── Stage Runners ───────────────────────────────────────────────────────────


def _build_iron_condor():
    """Build a deterministic iron condor TradeSpec for testing."""
    from income_desk.trade_spec_factory import build_iron_condor
    return build_iron_condor(
        ticker="SPY",
        underlying_price=580.0,
        short_put=570.0,
        long_put=565.0,
        short_call=590.0,
        long_call=595.0,
        expiration=date(2026, 4, 17),
        entry_price=1.60,
        profit_target_pct=0.50,
        stop_loss_pct=2.0,
        exit_dte=21,
    )


def _build_credit_spread():
    """Build a deterministic credit spread TradeSpec for testing."""
    from income_desk.trade_spec_factory import build_credit_spread
    return build_credit_spread(
        ticker="GLD",
        underlying_price=466.0,
        short_strike=455.0,
        long_strike=450.0,
        option_type="put",
        expiration=date(2026, 4, 17),
        entry_price=1.20,
    )


def _build_india_ic():
    """Build an India-market iron condor for NIFTY."""
    from income_desk.trade_spec_factory import build_iron_condor
    return build_iron_condor(
        ticker="NIFTY",
        underlying_price=23500.0,
        short_put=23200.0,
        long_put=23000.0,
        short_call=23800.0,
        long_call=24000.0,
        expiration=date(2026, 4, 2),
        entry_price=80.0,
        profit_target_pct=0.50,
        stop_loss_pct=2.0,
        exit_dte=7,
    )


def _run_stage_1_scan(sim_us: SimulatedMarketData, sim_india: SimulatedMarketData) -> StageResult:
    """Stage 1: SCAN — Context assessment + screening."""
    from income_desk import DataService, MarketAnalyzer

    stage = StageResult(stage="SCAN", stage_number=1, description="Market context assessment and candidate screening")
    t0 = time.perf_counter()

    # US market context
    ma_us = MarketAnalyzer(
        data_service=DataService(),
        market_data=sim_us,
        market_metrics=SimulatedMetrics(sim_us),
    )

    call = _run_api(
        "context.assess", "income_desk.service.context",
        lambda: ma_us.context.assess(),
        {},
        lambda c, r: (
            _check(c, "context returns MarketContext", r is not None),
            _check(c, "environment_label is valid", r.environment_label in ("risk-on", "cautious", "defensive", "crisis")) if r else None,
            _check(c, "position_size_factor is 0-1", 0 <= r.position_size_factor <= 1.0) if r else None,
            _check(c, "trading_allowed is bool", isinstance(r.trading_allowed, bool)) if r else None,
        ),
    )
    stage.api_calls.append(call)

    # Regime detection for US tickers
    us_tickers = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
    for ticker in us_tickers:
        call = _run_api(
            "regime.detect", "income_desk.service.regime_service",
            lambda t=ticker: ma_us.regime.detect(t),
            {"ticker": ticker},
            lambda c, r: (
                _check(c, f"regime returns RegimeResult for {c.inputs.get('ticker', '?')}", r is not None),
                _check(c, "regime_id in 1-4", r.regime.value in (1, 2, 3, 4)) if r else None,
                _check(c, "confidence > 0", r.confidence > 0) if r else None,
            ),
        )
        stage.api_calls.append(call)

    # India market context
    ma_india = MarketAnalyzer(
        data_service=DataService(),
        market_data=sim_india,
        market_metrics=SimulatedMetrics(sim_india),
    )
    india_tickers = ["NIFTY", "BANKNIFTY"]
    for ticker in india_tickers:
        call = _run_api(
            "regime.detect", "income_desk.service.regime_service",
            lambda t=ticker: ma_india.regime.detect(t),
            {"ticker": ticker, "market": "India"},
            lambda c, r: (
                _check(c, f"India regime returns RegimeResult for {c.inputs.get('ticker', '?')}", r is not None),
                _check(c, "regime_id in 1-4", r.regime.value in (1, 2, 3, 4)) if r else None,
            ),
        )
        stage.api_calls.append(call)

    stage.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    if any(c.error for c in stage.api_calls):
        stage.verdict = StageVerdict.FAIL
    elif any(not all(c.invariants_passed) for c in stage.api_calls):
        stage.verdict = StageVerdict.WARN
    return stage


def _run_stage_2_rank(sim_us: SimulatedMarketData) -> StageResult:
    """Stage 2: RANK — Trade ranking and opportunity assessment."""
    from income_desk import DataService, MarketAnalyzer

    stage = StageResult(stage="RANK", stage_number=2, description="Trade ranking and opportunity scoring")
    t0 = time.perf_counter()

    ma = MarketAnalyzer(
        data_service=DataService(),
        market_data=sim_us,
        market_metrics=SimulatedMetrics(sim_us),
    )

    tickers = ["SPY", "GLD", "TLT"]
    iv_rank_map = {t: sim_us._tickers.get(t, {}).get("iv_rank", 50) for t in tickers}

    call = _run_api(
        "ranking.rank", "income_desk.service.ranking",
        lambda: ma.ranking.rank(tickers, skip_intraday=True, iv_rank_map=iv_rank_map),
        {"tickers": tickers, "skip_intraday": True, "iv_rank_map": iv_rank_map},
        lambda c, r: (
            _check(c, "ranking returns TradeRankingResult", r is not None),
            _check(c, "top_trades is non-empty", len(r.top_trades) > 0) if r else None,
            _check(c, "all scores in 0-1", all(0 <= e.composite_score <= 1 for e in r.top_trades)) if r and r.top_trades else None,
            _check(c, "actionable entries (verdict=go) have trade_spec",
                   all(e.trade_spec is not None for e in r.top_trades if str(e.verdict) == "go")) if r and r.top_trades else None,
            _check(c, "entries are sorted by score descending",
                   all(r.top_trades[i].composite_score >= r.top_trades[i + 1].composite_score
                       for i in range(len(r.top_trades) - 1))) if r and len(r.top_trades) > 1 else None,
        ),
    )
    stage.api_calls.append(call)

    stage.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    if any(c.error for c in stage.api_calls):
        stage.verdict = StageVerdict.FAIL
    elif any(not all(c.invariants_passed) for c in stage.api_calls):
        stage.verdict = StageVerdict.WARN
    return stage


def _run_stage_3_gate() -> StageResult:
    """Stage 3: GATE — Account and portfolio filtering."""
    from income_desk.trade_lifecycle import (
        FilteredTrades,
        OpenPosition,
        PortfolioFilterResult,
        RiskLimits,
        filter_trades_by_account,
        filter_trades_with_portfolio,
    )
    from income_desk.models.ranking import RankedEntry, ScoreBreakdown

    stage = StageResult(stage="GATE", stage_number=3, description="Account and portfolio risk gating")
    t0 = time.perf_counter()

    # Build mock ranked entries from known TradeSpecs
    ic = _build_iron_condor()
    cs = _build_credit_spread()

    _default_breakdown = ScoreBreakdown(
        verdict_score=1.0, confidence_score=0.8, regime_alignment=0.85,
        risk_reward=0.7, technical_quality=0.75, phase_alignment=0.7,
        income_bias_boost=0.03, black_swan_penalty=0.0,
        macro_penalty=0.0, earnings_penalty=0.0,
    )

    mock_entries = [
        RankedEntry(
            rank=1, ticker="SPY", strategy_type="iron_condor",
            composite_score=0.78, verdict="go", direction="neutral",
            trade_spec=ic, breakdown=_default_breakdown,
            strategy_name="iron_condor", rationale="R1 income play",
            risk_notes=["defined risk"],
        ),
        RankedEntry(
            rank=2, ticker="GLD", strategy_type="iron_condor",
            composite_score=0.72, verdict="go", direction="neutral",
            trade_spec=cs, breakdown=_default_breakdown,
            strategy_name="credit_spread", rationale="R1 income play",
            risk_notes=["defined risk"],
        ),
    ]

    # filter_trades_by_account
    call = _run_api(
        "filter_trades_by_account", "income_desk.trade_lifecycle",
        lambda: filter_trades_by_account(mock_entries, available_buying_power=25_000),
        {"ranked_entries": "[2 RankedEntry]", "available_buying_power": 25_000},
        lambda c, r: (
            _check(c, "returns FilteredTrades", isinstance(r, FilteredTrades)),
            _check(c, "total_input matches", r.total_input == 2),
            _check(c, "affordable + filtered = total", len(r.affordable) + len(r.filtered_out) == r.total_input),
            _check(c, "available_buying_power preserved", r.available_buying_power == 25_000),
        ),
    )
    stage.api_calls.append(call)

    # filter_trades_with_portfolio
    open_positions = [
        OpenPosition(ticker="QQQ", structure_type="iron_condor", sector="tech", max_loss=500, buying_power_used=500),
    ]
    call = _run_api(
        "filter_trades_with_portfolio", "income_desk.trade_lifecycle",
        lambda: filter_trades_with_portfolio(
            mock_entries, open_positions, account_nlv=100_000,
            available_buying_power=25_000, risk_limits=RiskLimits(max_positions=5),
        ),
        {
            "ranked_entries": "[2 RankedEntry]",
            "open_positions": [p.model_dump() for p in open_positions],
            "account_nlv": 100_000,
            "available_buying_power": 25_000,
            "risk_limits": RiskLimits(max_positions=5).model_dump(),
        },
        lambda c, r: (
            _check(c, "returns PortfolioFilterResult", isinstance(r, PortfolioFilterResult)),
            _check(c, "approved + rejected = total", len(r.approved) + len(r.rejected) == r.total_input),
            _check(c, "portfolio_risk_pct >= 0", r.portfolio_risk_pct >= 0),
            _check(c, "slots_remaining >= 0", r.slots_remaining >= 0),
            _check(c, "summary is non-empty", len(r.summary) > 0),
        ),
    )
    stage.api_calls.append(call)

    stage.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    if any(c.error for c in stage.api_calls):
        stage.verdict = StageVerdict.FAIL
    elif any(not all(c.invariants_passed) for c in stage.api_calls):
        stage.verdict = StageVerdict.WARN
    return stage


def _run_stage_4_size() -> StageResult:
    """Stage 4: SIZE — Position sizing via Kelly criterion."""
    from income_desk.features.position_sizing import (
        CorrelationAdjustment,
        KellyResult,
        PortfolioExposure,
        compute_kelly_fraction,
        compute_position_size,
    )

    stage = StageResult(stage="SIZE", stage_number=4, description="Kelly criterion position sizing")
    t0 = time.perf_counter()

    # compute_kelly_fraction
    inputs_kelly = {"pop_pct": 0.65, "max_profit": 310.0, "max_loss": 190.0}
    call = _run_api(
        "compute_kelly_fraction", "income_desk.features.position_sizing",
        lambda: compute_kelly_fraction(**inputs_kelly),
        inputs_kelly,
        lambda c, r: (
            _check(c, "kelly fraction is float", isinstance(r, float)),
            _check(c, "kelly >= 0 (positive EV trade)", r >= 0),
            _check(c, "kelly <= 0.25 (hard cap)", r <= 0.25),
        ),
    )
    stage.api_calls.append(call)

    # compute_position_size (full sizing)
    inputs_size = {
        "pop_pct": 0.65,
        "max_profit": 310.0,
        "max_loss": 190.0,
        "capital": 100_000.0,
        "risk_per_contract": 190.0,
        "regime_id": 1,
        "wing_width": 5.0,
        "safety_factor": 0.5,
        "max_contracts": 20,
    }
    call = _run_api(
        "compute_position_size", "income_desk.features.position_sizing",
        lambda: compute_position_size(**inputs_size),
        inputs_size,
        lambda c, r: (
            _check(c, "returns KellyResult", isinstance(r, KellyResult)),
            _check(c, "recommended_contracts >= 0", r.recommended_contracts >= 0),
            _check(c, "recommended <= max_contracts", r.recommended_contracts <= 20),
            _check(c, "full_kelly >= half_kelly", r.full_kelly_fraction >= r.half_kelly_fraction),
            _check(c, "rationale is non-empty", len(r.rationale) > 0),
        ),
    )
    stage.api_calls.append(call)

    # Negative EV trade — Kelly should be 0
    inputs_neg = {"pop_pct": 0.30, "max_profit": 100.0, "max_loss": 500.0}
    call = _run_api(
        "compute_kelly_fraction", "income_desk.features.position_sizing",
        lambda: compute_kelly_fraction(**inputs_neg),
        {**inputs_neg, "_note": "negative_EV_trade"},
        lambda c, r: (
            _check(c, "negative EV returns kelly <= 0", r <= 0),
        ),
    )
    stage.api_calls.append(call)

    stage.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    if any(c.error for c in stage.api_calls):
        stage.verdict = StageVerdict.FAIL
    elif any(not all(c.invariants_passed) for c in stage.api_calls):
        stage.verdict = StageVerdict.WARN
    return stage


def _run_stage_5_enter() -> StageResult:
    """Stage 5: ENTER — Income entry confirmation, yield, Greeks."""
    from income_desk.models.quotes import OptionQuote
    from income_desk.trade_lifecycle import (
        AggregatedGreeks,
        Breakevens,
        IncomeYield,
        aggregate_greeks,
        check_income_entry,
        compute_breakevens,
        compute_income_yield,
        estimate_pop,
    )

    stage = StageResult(stage="ENTER", stage_number=5, description="Entry confirmation, yield metrics, Greeks aggregation")
    t0 = time.perf_counter()

    ic = _build_iron_condor()
    cs = _build_credit_spread()

    # compute_income_yield — iron condor
    call = _run_api(
        "compute_income_yield", "income_desk.trade_lifecycle",
        lambda: compute_income_yield(ic, entry_credit=1.60, contracts=1),
        {"trade_spec": "SPY iron_condor", "entry_credit": 1.60, "contracts": 1},
        lambda c, r: (
            _check(c, "returns IncomeYield", isinstance(r, IncomeYield)),
            _check(c, "max_profit > 0", r.max_profit > 0),
            _check(c, "max_loss > 0", r.max_loss > 0),
            _check(c, "max_profit = credit * lot_size", r.max_profit == 1.60 * 100),
            _check(c, "credit_to_width_pct in 0-1", 0 < r.credit_to_width_pct <= 1),
            _check(c, "annualized_roc > 0", r.annualized_roc_pct > 0),
            _check(c, "breakeven_low < underlying", r.breakeven_low < 580.0) if r.breakeven_low else None,
            _check(c, "breakeven_high > underlying", r.breakeven_high > 580.0) if r.breakeven_high else None,
        ),
    )
    stage.api_calls.append(call)

    # compute_income_yield — credit spread
    call = _run_api(
        "compute_income_yield", "income_desk.trade_lifecycle",
        lambda: compute_income_yield(cs, entry_credit=1.20, contracts=2),
        {"trade_spec": "GLD credit_spread", "entry_credit": 1.20, "contracts": 2},
        lambda c, r: (
            _check(c, "returns IncomeYield", isinstance(r, IncomeYield)),
            _check(c, "contracts reflected", r.contracts == 2),
            _check(c, "max_profit = credit * lot * contracts", r.max_profit == 1.20 * 100 * 2),
        ),
    )
    stage.api_calls.append(call)

    # compute_breakevens
    call = _run_api(
        "compute_breakevens", "income_desk.trade_lifecycle",
        lambda: compute_breakevens(ic, entry_price=1.60),
        {"trade_spec": "SPY iron_condor", "entry_price": 1.60},
        lambda c, r: (
            _check(c, "returns Breakevens", isinstance(r, Breakevens)),
            _check(c, "low breakeven present", r.low is not None),
            _check(c, "high breakeven present", r.high is not None),
            _check(c, "low < high", r.low < r.high) if r.low and r.high else None,
            _check(c, "low = short_put - credit = 568.40", r.low == 568.40) if r.low else None,
            _check(c, "high = short_call + credit = 591.60", r.high == 591.60) if r.high else None,
        ),
    )
    stage.api_calls.append(call)

    # estimate_pop
    inputs_pop = {
        "trade_spec": ic,
        "entry_price": 1.60,
        "regime_id": 1,
        "atr_pct": 1.2,
        "current_price": 580.0,
        "contracts": 1,
        "iv_rank": 43.0,
    }
    call = _run_api(
        "estimate_pop", "income_desk.trade_lifecycle",
        lambda: estimate_pop(**inputs_pop),
        {k: _serialize(v) for k, v in inputs_pop.items()},
        lambda c, r: (
            _check(c, "returns POPEstimate", r is not None),
            _check(c, "pop_pct in 0-1", 0 <= r.pop_pct <= 1) if r else None,
            _check(c, "expected_value is computed", r.expected_value != 0) if r else None,
            _check(c, "method is regime_historical", r.method == "regime_historical") if r else None,
            _check(c, "trade_quality is set", r.trade_quality in ("excellent", "good", "marginal", "poor")) if r else None,
            _check(c, "trade_quality_score in 0-1", 0 <= r.trade_quality_score <= 1) if r else None,
        ),
    )
    stage.api_calls.append(call)

    # check_income_entry
    inputs_entry = {
        "iv_rank": 50.0, "iv_percentile": 55.0, "dte": 35,
        "rsi": 48.0, "atr_pct": 1.2, "regime_id": 1,
    }
    call = _run_api(
        "check_income_entry", "income_desk.trade_lifecycle",
        lambda: check_income_entry(**inputs_entry),
        inputs_entry,
        lambda c, r: (
            _check(c, "returns IncomeEntryCheck", r is not None),
            _check(c, "score in 0-1", 0 <= r.score <= 1),
            _check(c, "ideal conditions confirmed", r.confirmed is True),
            _check(c, "conditions list populated", len(r.conditions) >= 4),
        ),
    )
    stage.api_calls.append(call)

    # check_income_entry — bad conditions (R4, high RSI)
    inputs_bad = {
        "iv_rank": 10.0, "iv_percentile": 12.0, "dte": 5,
        "rsi": 82.0, "atr_pct": 3.5, "regime_id": 4,
    }
    call = _run_api(
        "check_income_entry", "income_desk.trade_lifecycle",
        lambda: check_income_entry(**inputs_bad),
        {**inputs_bad, "_note": "bad_conditions"},
        lambda c, r: (
            _check(c, "bad conditions NOT confirmed", r.confirmed is False),
            _check(c, "score < 0.6 for bad conditions", r.score < 0.6),
        ),
    )
    stage.api_calls.append(call)

    # aggregate_greeks
    exp = date(2026, 4, 17)
    leg_quotes = [
        OptionQuote(ticker="SPY", expiration=exp, strike=570.0, option_type="put",
                    bid=1.50, ask=1.70, mid=1.60, delta=-0.15, gamma=0.02, theta=-0.05, vega=0.10),
        OptionQuote(ticker="SPY", expiration=exp, strike=565.0, option_type="put",
                    bid=0.30, ask=0.50, mid=0.40, delta=-0.05, gamma=0.01, theta=-0.02, vega=0.04),
        OptionQuote(ticker="SPY", expiration=exp, strike=590.0, option_type="call",
                    bid=1.40, ask=1.60, mid=1.50, delta=0.15, gamma=0.02, theta=-0.05, vega=0.10),
        OptionQuote(ticker="SPY", expiration=exp, strike=595.0, option_type="call",
                    bid=0.20, ask=0.40, mid=0.30, delta=0.05, gamma=0.01, theta=-0.02, vega=0.04),
    ]
    call = _run_api(
        "aggregate_greeks", "income_desk.trade_lifecycle",
        lambda: aggregate_greeks(ic, leg_quotes, contracts=1),
        {"trade_spec": "SPY iron_condor", "leg_quotes": "[4 OptionQuote]", "contracts": 1},
        lambda c, r: (
            _check(c, "returns AggregatedGreeks", isinstance(r, AggregatedGreeks)),
            _check(c, "net_delta is near-zero for IC", abs(r.net_delta) < 1.0) if r else None,
            _check(c, "daily_theta_dollars computed", r.daily_theta_dollars != 0) if r else None,
        ),
    )
    stage.api_calls.append(call)

    stage.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    if any(c.error for c in stage.api_calls):
        stage.verdict = StageVerdict.FAIL
    elif any(not all(c.invariants_passed) for c in stage.api_calls):
        stage.verdict = StageVerdict.WARN
    return stage


def _run_stage_6_monitor() -> StageResult:
    """Stage 6: MONITOR — Exit condition monitoring."""
    from income_desk.trade_lifecycle import ExitMonitorResult, monitor_exit_conditions

    stage = StageResult(stage="MONITOR", stage_number=6, description="Exit condition monitoring and health checks")
    t0 = time.perf_counter()

    # Profit target hit scenario
    call = _run_api(
        "monitor_exit_conditions", "income_desk.trade_lifecycle",
        lambda: monitor_exit_conditions(
            trade_id="ic-001", ticker="SPY", structure_type="iron_condor",
            order_side="credit", entry_price=1.60, current_mid_price=0.75,
            contracts=1, dte_remaining=25, regime_id=1,
            profit_target_pct=0.50, stop_loss_pct=2.0, exit_dte=21,
        ),
        {
            "trade_id": "ic-001", "ticker": "SPY", "structure_type": "iron_condor",
            "order_side": "credit", "entry_price": 1.60, "current_mid_price": 0.75,
            "contracts": 1, "dte_remaining": 25, "regime_id": 1,
            "profit_target_pct": 0.50, "stop_loss_pct": 2.0, "exit_dte": 21,
            "_note": "profit_target_hit",
        },
        lambda c, r: (
            _check(c, "returns ExitMonitorResult", isinstance(r, ExitMonitorResult)),
            _check(c, "should_close is True (profit target hit)", r.should_close is True),
            _check(c, "pnl_pct > 0 (profitable)", r.pnl_pct > 0),
            _check(c, "pnl_dollars > 0", r.pnl_dollars > 0),
            _check(c, "signals non-empty", len(r.signals) > 0),
            _check(c, "most_urgent is set", r.most_urgent is not None),
            _check(c, "commentary is non-empty", len(r.commentary) > 0),
        ),
    )
    stage.api_calls.append(call)

    # Stop loss scenario
    call = _run_api(
        "monitor_exit_conditions", "income_desk.trade_lifecycle",
        lambda: monitor_exit_conditions(
            trade_id="ic-002", ticker="SPY", structure_type="iron_condor",
            order_side="credit", entry_price=1.60, current_mid_price=5.00,
            contracts=1, dte_remaining=15, regime_id=4,
            entry_regime_id=1, profit_target_pct=0.50, stop_loss_pct=2.0,
            exit_dte=21,
        ),
        {
            "trade_id": "ic-002", "entry_price": 1.60, "current_mid_price": 5.00,
            "regime_id": 4, "entry_regime_id": 1,
            "_note": "stop_loss_hit_with_regime_change",
        },
        lambda c, r: (
            _check(c, "should_close is True (stop loss)", r.should_close is True),
            _check(c, "pnl_pct < 0 (losing)", r.pnl_pct < 0),
            _check(c, "pnl_dollars < 0", r.pnl_dollars < 0),
            _check(c, "regime change signal present",
                   any(s.rule == "regime_change" for s in r.signals)),
        ),
    )
    stage.api_calls.append(call)

    # Healthy trade — no exit needed
    call = _run_api(
        "monitor_exit_conditions", "income_desk.trade_lifecycle",
        lambda: monitor_exit_conditions(
            trade_id="ic-003", ticker="GLD", structure_type="credit_spread",
            order_side="credit", entry_price=1.20, current_mid_price=1.00,
            contracts=1, dte_remaining=30, regime_id=1,
            profit_target_pct=0.50, stop_loss_pct=2.0, exit_dte=21,
        ),
        {
            "trade_id": "ic-003", "entry_price": 1.20, "current_mid_price": 1.00,
            "dte_remaining": 30,
            "_note": "healthy_trade_hold",
        },
        lambda c, r: (
            _check(c, "should_close is False (healthy)", r.should_close is False),
            _check(c, "pnl_pct > 0 but below target",
                   0 < r.pnl_pct < 0.50),
        ),
    )
    stage.api_calls.append(call)

    stage.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    if any(c.error for c in stage.api_calls):
        stage.verdict = StageVerdict.FAIL
    elif any(not all(c.invariants_passed) for c in stage.api_calls):
        stage.verdict = StageVerdict.WARN
    return stage


def _run_stage_7_adjust() -> StageResult:
    """Stage 7: ADJUST — Assignment risk and adjustment analysis."""
    from income_desk.features.assignment_handler import assess_assignment_risk

    stage = StageResult(stage="ADJUST", stage_number=7, description="Assignment risk assessment and adjustment analysis")
    t0 = time.perf_counter()

    # Assignment risk assessment
    ic = _build_iron_condor()
    inputs_risk = {
        "trade_spec": ic,
        "current_price": 572.0,
        "dte_remaining": 5,
    }
    call = _run_api(
        "assess_assignment_risk", "income_desk.features.assignment_handler",
        lambda: assess_assignment_risk(**inputs_risk),
        {k: _serialize(v) for k, v in inputs_risk.items()},
        lambda c, r: (
            _check(c, "returns AssignmentRiskResult", r is not None),
            _check(c, "has risk_level", hasattr(r, "risk_level") or hasattr(r, "overall_risk")),
        ),
    )
    stage.api_calls.append(call)

    stage.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    if any(c.error for c in stage.api_calls):
        stage.verdict = StageVerdict.FAIL
    elif any(not all(c.invariants_passed) for c in stage.api_calls):
        stage.verdict = StageVerdict.WARN
    return stage


def _run_stage_8_analytics() -> StageResult:
    """Stage 8: ANALYTICS — P&L, structure risk, portfolio analytics, circuit breakers."""
    from income_desk.trade_analytics import (
        CircuitBreakerConfig,
        LegPnLInput,
        PositionSnapshot,
        compute_pnl_attribution,
        compute_portfolio_analytics,
        compute_structure_risk,
        compute_trade_pnl,
        evaluate_circuit_breakers,
    )

    stage = StageResult(stage="ANALYTICS", stage_number=8, description="P&L attribution, structure risk, portfolio analytics, circuit breakers")
    t0 = time.perf_counter()

    # compute_pnl_attribution
    inputs_pnl = {
        "entry_delta": -0.10, "entry_gamma": 0.02, "entry_theta": 0.05, "entry_vega": -0.15,
        "underlying_change": 3.0, "iv_change": 0.02, "days_elapsed": 5.0, "actual_pnl": -50.0,
    }
    call = _run_api(
        "compute_pnl_attribution", "income_desk.trade_analytics",
        lambda: compute_pnl_attribution(**inputs_pnl),
        inputs_pnl,
        lambda c, r: (
            _check(c, "returns PnLAttribution", r is not None),
            _check(c, "components sum to model_pnl",
                   abs((r.delta_pnl + r.gamma_pnl + r.theta_pnl + r.vega_pnl) - r.model_pnl) < 0.01),
            _check(c, "unexplained = actual - model",
                   abs(r.unexplained_pnl - (r.actual_pnl - r.model_pnl)) < 0.01),
        ),
    )
    stage.api_calls.append(call)

    # compute_trade_pnl
    legs = [
        LegPnLInput(quantity=-1, entry_price=1.60, current_price=1.00, open_price=1.20),
        LegPnLInput(quantity=1, entry_price=0.40, current_price=0.30, open_price=0.35),
        LegPnLInput(quantity=-1, entry_price=1.50, current_price=1.10, open_price=1.30),
        LegPnLInput(quantity=1, entry_price=0.30, current_price=0.25, open_price=0.28),
    ]
    call = _run_api(
        "compute_trade_pnl", "income_desk.trade_analytics",
        lambda: compute_trade_pnl(legs),
        {"legs": [l.model_dump() for l in legs]},
        lambda c, r: (
            _check(c, "returns TradePnL", r is not None),
            _check(c, "legs count matches", len(r.legs) == 4),
            _check(c, "pnl_inception is numeric", isinstance(r.pnl_inception, (int, float))),
            _check(c, "entry_cost > 0", r.entry_cost > 0),
        ),
    )
    stage.api_calls.append(call)

    # compute_structure_risk — iron condor (use legs from built trade spec)
    ic_spec = _build_iron_condor()
    ic_legs = ic_spec.legs
    call = _run_api(
        "compute_structure_risk", "income_desk.trade_analytics",
        lambda: compute_structure_risk("iron_condor", ic_legs, net_credit_debit=1.60, multiplier=100, contracts=1),
        {"structure_type": "iron_condor", "net_credit_debit": 1.60, "multiplier": 100, "contracts": 1},
        lambda c, r: (
            _check(c, "returns StructureRisk", r is not None),
            _check(c, "max_profit = credit * 100", r.max_profit == 160.0),
            _check(c, "max_loss = (wing - credit) * 100", r.max_loss == 340.0),
            _check(c, "risk_profile is defined", r.risk_profile == "defined"),
            _check(c, "breakeven_low present", r.breakeven_low is not None),
            _check(c, "breakeven_high present", r.breakeven_high is not None),
            _check(c, "wing_width = 5", r.wing_width == 5.0),
            _check(c, "risk_reward_ratio > 0", r.risk_reward_ratio > 0) if r.risk_reward_ratio else None,
        ),
    )
    stage.api_calls.append(call)

    # compute_portfolio_analytics
    positions = [
        PositionSnapshot(ticker="SPY", structure_type="iron_condor", entry_price=1.60,
                         current_price=1.00, open_price=1.20, quantity=-1,
                         delta=-0.10, theta=0.05, underlying_price=580.0, max_loss=340.0),
        PositionSnapshot(ticker="GLD", structure_type="credit_spread", entry_price=1.20,
                         current_price=0.80, open_price=1.00, quantity=-1,
                         delta=-0.08, theta=0.03, underlying_price=466.0, max_loss=380.0),
    ]
    call = _run_api(
        "compute_portfolio_analytics", "income_desk.trade_analytics",
        lambda: compute_portfolio_analytics(positions, account_nlv=100_000.0),
        {"positions": [p.model_dump() for p in positions], "account_nlv": 100_000.0},
        lambda c, r: (
            _check(c, "returns PortfolioAnalytics", r is not None),
            _check(c, "by_underlying has 2 tickers", len(r.by_underlying) == 2),
            _check(c, "total_margin_at_risk >= 0", r.total_margin_at_risk >= 0),
            _check(c, "margin_utilization_pct >= 0", r.margin_utilization_pct >= 0),
        ),
    )
    stage.api_calls.append(call)

    # evaluate_circuit_breakers
    call = _run_api(
        "evaluate_circuit_breakers", "income_desk.trade_analytics",
        lambda: evaluate_circuit_breakers(
            daily_pnl_pct=-1.5, weekly_pnl_pct=-3.0, portfolio_drawdown_pct=5.0,
            consecutive_losses=2, config=CircuitBreakerConfig(),
        ),
        {"daily_pnl_pct": -1.5, "weekly_pnl_pct": -3.0, "portfolio_drawdown_pct": 5.0, "consecutive_losses": 2},
        lambda c, r: (
            _check(c, "returns CircuitBreakerResult", r is not None),
            _check(c, "can_open_new is bool", isinstance(r.can_open_new, bool)),
            _check(c, "no breakers tripped for moderate loss", len(r.breakers_tripped) == 0),
        ),
    )
    stage.api_calls.append(call)

    # evaluate_circuit_breakers — tripped scenario
    call = _run_api(
        "evaluate_circuit_breakers", "income_desk.trade_analytics",
        lambda: evaluate_circuit_breakers(
            daily_pnl_pct=-3.0, weekly_pnl_pct=-6.0, portfolio_drawdown_pct=12.0,
            consecutive_losses=4, config=CircuitBreakerConfig(),
        ),
        {"daily_pnl_pct": -3.0, "weekly_pnl_pct": -6.0, "portfolio_drawdown_pct": 12.0,
         "consecutive_losses": 4, "_note": "breaker_tripped"},
        lambda c, r: (
            _check(c, "breakers tripped for severe loss", len(r.breakers_tripped) > 0),
            _check(c, "is_paused or is_halted", r.is_paused or r.is_halted),
            _check(c, "can_open_new is False", r.can_open_new is False),
        ),
    )
    stage.api_calls.append(call)

    stage.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    if any(c.error for c in stage.api_calls):
        stage.verdict = StageVerdict.FAIL
    elif any(not all(c.invariants_passed) for c in stage.api_calls):
        stage.verdict = StageVerdict.WARN
    return stage


def _run_regression_pipeline(sim_us: SimulatedMarketData) -> dict[str, Any]:
    """Run existing regression pipeline validation."""
    from income_desk.regression.pipeline_validation import validate_full_pipeline

    try:
        result = validate_full_pipeline(sim_us)
        return _serialize(result)
    except Exception as e:
        return {"error": str(e), "traceback": traceback.format_exc()}


# ── Main Runner ─────────────────────────────────────────────────────────────


def run_release_readiness(
    parallel: bool = True,
    include_india: bool = True,
) -> ReadinessReport:
    """Execute the full release readiness validation.

    Exercises every API in the 8-stage trading workflow with deterministic
    inputs, validates number invariants, and captures call signatures
    for eTrading replay verification.

    Args:
        parallel: Run independent stages in parallel (default True).
        include_india: Include India market tests (default True).

    Returns:
        ReadinessReport with all results, API manifests, and GO/NO-GO verdict.
    """
    import income_desk

    report = ReadinessReport(
        version=getattr(income_desk, "__version__", "unknown"),
        markets_tested=["US", "India"] if include_india else ["US"],
    )
    t0 = time.perf_counter()

    # Build simulated markets
    sim_us = create_ideal_income()
    sim_india = create_india_trading() if include_india else None

    if parallel:
        # Stages 1-2 need MarketAnalyzer (heavier); 3-8 are pure computation (fast)
        # Run scan/rank sequentially (they share sim), then 3-8 in parallel
        stage_1 = _run_stage_1_scan(sim_us, sim_india or create_india_trading())
        report.stages.append(stage_1)

        stage_2 = _run_stage_2_rank(sim_us)
        report.stages.append(stage_2)

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                pool.submit(_run_stage_3_gate): 3,
                pool.submit(_run_stage_4_size): 4,
                pool.submit(_run_stage_5_enter): 5,
                pool.submit(_run_stage_6_monitor): 6,
                pool.submit(_run_stage_7_adjust): 7,
                pool.submit(_run_stage_8_analytics): 8,
            }
            results_by_stage = {}
            for future in as_completed(futures):
                stage_num = futures[future]
                try:
                    results_by_stage[stage_num] = future.result()
                except Exception as e:
                    results_by_stage[stage_num] = StageResult(
                        stage=f"STAGE_{stage_num}", stage_number=stage_num,
                        description="Failed to execute",
                        verdict=StageVerdict.FAIL, error=str(e),
                    )

            for n in sorted(results_by_stage):
                report.stages.append(results_by_stage[n])
    else:
        report.stages.append(_run_stage_1_scan(sim_us, sim_india or create_india_trading()))
        report.stages.append(_run_stage_2_rank(sim_us))
        report.stages.append(_run_stage_3_gate())
        report.stages.append(_run_stage_4_size())
        report.stages.append(_run_stage_5_enter())
        report.stages.append(_run_stage_6_monitor())
        report.stages.append(_run_stage_7_adjust())
        report.stages.append(_run_stage_8_analytics())

    # Run existing regression pipeline
    report.regression_result = _run_regression_pipeline(sim_us)

    report.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    report.compute_verdict()

    # Identify gaps and improvements
    for stage in report.stages:
        if stage.verdict == StageVerdict.FAIL:
            report.gaps_found.append(f"STAGE {stage.stage_number} ({stage.stage}): {stage.error or 'invariant failures'}")
        for call in stage.api_calls:
            if call.error:
                report.gaps_found.append(f"{call.api}: {call.error}")
            for desc, passed in zip(call.invariants_checked, call.invariants_passed):
                if not passed:
                    report.gaps_found.append(f"{call.api}: FAILED — {desc}")

    return report
