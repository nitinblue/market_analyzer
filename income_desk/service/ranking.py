"""TradeRankingService: rank trade ideas across tickers and strategies."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

import pandas as pd

from income_desk.config import get_settings
from income_desk.features.ranking import (
    ConfigWeightProvider,
    WeightProvider,
    composite_from_breakdown,
    compute_composite_score,
)
from income_desk.models.black_swan import AlertLevel
from income_desk.models.opportunity import (
    BreakoutOpportunity,
    LEAPOpportunity,
    MomentumOpportunity,
    TradeSpec,
    Verdict,
    ZeroDTEOpportunity,
)
from income_desk.opportunity.option_plays.iron_condor import IronCondorOpportunity
from income_desk.opportunity.option_plays.iron_butterfly import IronButterflyOpportunity
from income_desk.opportunity.option_plays.calendar import CalendarOpportunity
from income_desk.opportunity.option_plays.diagonal import DiagonalOpportunity
from income_desk.opportunity.option_plays.ratio_spread import RatioSpreadOpportunity
from income_desk.opportunity.option_plays.earnings import EarningsOpportunity
from income_desk.opportunity.setups.mean_reversion import MeanReversionOpportunity
from income_desk.models.chain import ChainBundle
from income_desk.models.ranking import (
    RankedEntry,
    RankingFeedback,
    StrategyType,
    TradeRankingResult,
    WatchItem,
)

if TYPE_CHECKING:
    from income_desk.broker.base import MarketMetricsProvider
    from income_desk.data.service import DataService
    from income_desk.service.black_swan import BlackSwanService
    from income_desk.service.levels import LevelsService
    from income_desk.service.opportunity import OpportunityService

logger = logging.getLogger(__name__)

# Type alias for any opportunity result
OpportunityResult = Union[
    ZeroDTEOpportunity, LEAPOpportunity, BreakoutOpportunity, MomentumOpportunity,
    IronCondorOpportunity, IronButterflyOpportunity, CalendarOpportunity,
    DiagonalOpportunity, RatioSpreadOpportunity, EarningsOpportunity,
    MeanReversionOpportunity,
]

# Map StrategyType -> OpportunityService method name
_ASSESS_METHODS: dict[StrategyType, str] = {
    StrategyType.ZERO_DTE: "assess_zero_dte",
    StrategyType.LEAP: "assess_leap",
    StrategyType.BREAKOUT: "assess_breakout",
    StrategyType.MOMENTUM: "assess_momentum",
    StrategyType.IRON_CONDOR: "assess_iron_condor",
    StrategyType.IRON_BUTTERFLY: "assess_iron_butterfly",
    StrategyType.CALENDAR: "assess_calendar",
    StrategyType.DIAGONAL: "assess_diagonal",
    StrategyType.RATIO_SPREAD: "assess_ratio_spread",
    StrategyType.EARNINGS: "assess_earnings",
    StrategyType.MEAN_REVERSION: "assess_mean_reversion",
}

# Assessor methods that accept an iv_rank keyword argument
_IV_RANK_ASSESSORS: set[str] = {
    "assess_iron_condor",
    "assess_iron_butterfly",
    "assess_calendar",
    "assess_earnings",
    "assess_leap",
}


def _extract_regime_id(result: OpportunityResult) -> int:
    """Extract regime_id from any opportunity result."""
    return result.regime_id


def _extract_phase_id(result: OpportunityResult) -> int:
    """Extract phase_id from opportunity result (default 1 for 0DTE which lacks it)."""
    return getattr(result, "phase_id", 1)


def _extract_days_to_earnings(result: OpportunityResult) -> int | None:
    return getattr(result, "days_to_earnings", None)


def _extract_strategy_name(result: OpportunityResult) -> str:
    """Extract specific strategy name (e.g. 'iron_condor')."""
    if isinstance(result, ZeroDTEOpportunity):
        return result.zero_dte_strategy.value
    elif isinstance(result, LEAPOpportunity):
        return result.leap_strategy.value
    elif isinstance(result, BreakoutOpportunity):
        return result.breakout_strategy.value
    elif isinstance(result, MomentumOpportunity):
        return result.momentum_strategy.value
    elif isinstance(result, IronCondorOpportunity):
        return result.iron_condor_strategy
    elif isinstance(result, IronButterflyOpportunity):
        return result.iron_butterfly_strategy
    elif isinstance(result, CalendarOpportunity):
        return result.calendar_strategy
    elif isinstance(result, DiagonalOpportunity):
        return result.diagonal_strategy
    elif isinstance(result, RatioSpreadOpportunity):
        return result.ratio_strategy
    elif isinstance(result, (EarningsOpportunity, MeanReversionOpportunity)):
        return str(result.strategy)
    return "unknown"


def _extract_macro_events_7d(result: OpportunityResult) -> int:
    """Extract macro event count. Available directly on some results."""
    if isinstance(result, ZeroDTEOpportunity):
        return 1 if result.has_macro_event_today else 0
    elif isinstance(result, LEAPOpportunity):
        return result.macro_events_next_30_days  # best proxy
    return 0


def _extract_direction(result: OpportunityResult) -> str:
    """Extract direction from heterogeneous result types."""
    # Types with StrategyRecommendation object
    if hasattr(result, "strategy") and hasattr(result.strategy, "direction"):
        return result.strategy.direction
    # Diagonal uses trend_direction
    if hasattr(result, "trend_direction"):
        return result.trend_direction
    # Earnings, MeanReversion, RatioSpread have direction directly
    if hasattr(result, "direction"):
        return result.direction
    return "neutral"


def _extract_rationale(result: OpportunityResult) -> str:
    """Extract rationale from heterogeneous result types."""
    if hasattr(result, "strategy") and hasattr(result.strategy, "rationale"):
        return result.strategy.rationale
    return getattr(result, "summary", "")


def _extract_risk_notes(result: OpportunityResult) -> list[str]:
    """Extract risk notes from heterogeneous result types."""
    if hasattr(result, "strategy") and hasattr(result.strategy, "risk_notes"):
        return result.strategy.risk_notes
    notes: list[str] = []
    if hasattr(result, "has_naked_leg") and result.has_naked_leg:
        notes.append(getattr(result, "margin_warning", "Naked leg — margin required"))
    return notes


def _extract_trade_spec(result: OpportunityResult) -> TradeSpec | None:
    """Extract trade_spec from any opportunity result."""
    return getattr(result, "trade_spec", None)


_SETTLEMENT_BONUS = 0.05  # Cash-settled bonus for 0DTE
_SETTLEMENT_PENALTY = 0.05  # Physical-settled penalty for 0DTE


def _apply_settlement_adjustment(ticker: str, composite: float) -> float:
    """Adjust composite score based on settlement type for 0DTE strategies.

    Cash-settled / European instruments (SPX, NIFTY) get a small bonus;
    physically-settled / American instruments (SPY, QQQ) get a penalty.
    This naturally sorts cash-settled higher for 0DTE.
    """
    try:
        from income_desk.registry import MarketRegistry
        inst = MarketRegistry().get_instrument(ticker)
    except (KeyError, ImportError):
        return composite

    if inst.settlement == "cash" and inst.exercise_style == "european":
        composite = min(1.0, composite + _SETTLEMENT_BONUS)
    elif inst.settlement == "physical" and inst.exercise_style == "american":
        composite = max(0.0, composite - _SETTLEMENT_PENALTY)

    return composite


class TradeRankingService:
    """Rank trade ideas across tickers and strategy types.

    Runs opportunity assessments, scores each ticker x strategy pair,
    and returns ranked results with grouping by ticker and by strategy.
    """

    def __init__(
        self,
        opportunity_service: OpportunityService,
        levels_service: LevelsService,
        black_swan_service: BlackSwanService,
        data_service: DataService | None = None,
        weight_provider: WeightProvider | None = None,
        market_metrics: MarketMetricsProvider | None = None,
        market_data: Any | None = None,
    ) -> None:
        self.opportunity = opportunity_service
        self.levels = levels_service
        self.black_swan = black_swan_service
        self.data_service = data_service
        self.weight_provider = weight_provider or ConfigWeightProvider()
        self._market_metrics = market_metrics
        self.market_data = market_data

    def rank(
        self,
        tickers: list[str],
        strategies: list[StrategyType] | None = None,
        as_of: date | None = None,
        skip_intraday: bool = False,
        debug: bool = False,
        iv_rank_map: dict[str, float | None] | None = None,
        chains: dict[str, ChainBundle] | None = None,
    ) -> TradeRankingResult:
        """Run all assessments, score, and rank.

        Args:
            tickers: List of tickers to assess.
            strategies: Strategy types to evaluate. None = all 4.
            as_of: Override assessment date.
            skip_intraday: If True, skip DXLink/yfinance intraday candle
                fetches (ORB data). Useful for daily plan generation where
                ORB is not needed and intraday fetches add 45s+ latency.

        Returns:
            TradeRankingResult with ranked entries.
        """
        as_of = as_of or date.today()
        strategies = strategies or [s for s in StrategyType if s in _ASSESS_METHODS]

        # 0. Auto-fetch IV rank if metrics provider available and map not passed
        if iv_rank_map is None and self._market_metrics is not None:
            try:
                metrics = self._market_metrics.get_metrics(tickers)
                iv_rank_map = {t: m.iv_rank for t, m in metrics.items() if m.iv_rank is not None}
            except Exception:
                logger.debug("Failed to fetch market metrics for IV rank", exc_info=True)

        # 1. Black swan gate check
        black_swan_level = AlertLevel.NORMAL
        black_swan_score = 0.0
        black_swan_gate = False

        try:
            bs_alert = self.black_swan.alert(as_of_date=as_of)
            black_swan_level = bs_alert.alert_level
            black_swan_score = bs_alert.composite_score
            black_swan_gate = bs_alert.alert_level == AlertLevel.CRITICAL
        except Exception:
            logger.warning("Black swan check failed, proceeding without gate", exc_info=True)

        # If CRITICAL, return empty ranking with gate=True
        if black_swan_gate:
            return TradeRankingResult(
                as_of_date=as_of,
                tickers=tickers,
                top_trades=[],
                by_ticker={t: [] for t in tickers},
                by_strategy={s: [] for s in strategies},
                black_swan_level=black_swan_level.value,
                black_swan_gate=True,
                total_assessed=0,
                total_actionable=0,
                summary=f"CRITICAL black swan alert (score={black_swan_score:.2f}). All trading halted.",
            )

        # 2. For each ticker x strategy, run assessment
        entries: list[RankedEntry] = []
        opp_results: dict[int, OpportunityResult] = {}  # keyed by id(entry) for debug
        ticker_regime: dict[str, int] = {}  # first regime_id seen per ticker (for watch items)
        total_assessed = 0

        for ticker in tickers:
            # Get technicals once per ticker (used in scoring)
            technicals = None
            try:
                technicals = self.opportunity.technical_service.snapshot(ticker)
            except Exception:
                logger.warning("Failed to get technicals for %s", ticker, exc_info=True)
                continue

            # Get levels once per ticker (for R:R)
            levels_result = None
            try:
                levels_result = self.levels.analyze(ticker)
            except Exception:
                logger.debug("Levels analysis failed for %s, R:R will default", ticker)

            # Get macro event count (from the opportunity service's macro)
            macro_events_7d = 0
            try:
                macro = self.opportunity.macro_service.calendar(as_of=as_of)
                macro_events_7d = len(macro.events_next_7_days)
            except Exception:
                pass

            # Use pre-fetched bundle if available, else fall back to fetching
            bundle = chains.get(ticker) if chains else None
            chain_ctx = bundle.chain_context if bundle else None
            vol_surf = bundle.vol_surface if bundle else None

            # Fallback: fetch broker chain if no bundle provided (backward compat)
            if bundle is None and self.market_data is not None:
                try:
                    raw_chain = self.market_data.get_option_chain(ticker)
                    price = self.market_data.get_underlying_price(ticker)
                    if raw_chain and price:
                        from income_desk.opportunity.option_plays._chain_context import build_chain_context
                        chain_ctx = build_chain_context(ticker, raw_chain, price)
                except Exception:
                    pass

            for strategy in strategies:
                total_assessed += 1
                method_name = _ASSESS_METHODS.get(strategy)
                if method_name is None:
                    continue
                assess_fn = getattr(self.opportunity, method_name, None)
                if assess_fn is None:
                    continue

                try:
                    # Build kwargs for the assessor call
                    kwargs: dict[str, Any] = {"as_of": as_of}

                    # Pass chain and vol_surface from bundle to assessors
                    if chain_ctx is not None:
                        kwargs["chain"] = chain_ctx
                    if vol_surf is not None:
                        kwargs["vol_surface"] = vol_surf

                    # Skip intraday (ORB/DXLink) for 0DTE during plan generation
                    if skip_intraday and strategy == StrategyType.ZERO_DTE:
                        kwargs["intraday"] = pd.DataFrame()

                    # Thread IV rank to assessors that accept it
                    if method_name in _IV_RANK_ASSESSORS and iv_rank_map:
                        iv_rank = iv_rank_map.get(ticker)
                        if iv_rank is not None:
                            kwargs["iv_rank"] = iv_rank

                    result: OpportunityResult = assess_fn(ticker, **kwargs)

                    regime_id = _extract_regime_id(result)
                    if ticker not in ticker_regime:
                        ticker_regime[ticker] = regime_id
                    phase_id = _extract_phase_id(result)
                    days_to_earnings = _extract_days_to_earnings(result)

                    # Get weights from provider
                    weights = self.weight_provider.get_weights(ticker, strategy)

                    # Compute score
                    breakdown = compute_composite_score(
                        verdict=result.verdict,
                        confidence=result.confidence,
                        regime_id=regime_id,
                        phase_id=phase_id,
                        strategy=strategy,
                        technicals=technicals,
                        levels=levels_result,
                        black_swan_score=black_swan_score,
                        events_next_7_days=macro_events_7d,
                        days_to_earnings=days_to_earnings,
                        weights=weights,
                    )
                    composite = composite_from_breakdown(breakdown, weights)

                    # Settlement preference: cash-settled/European gets a bonus
                    # for 0DTE; physically-settled/American gets a penalty.
                    if strategy == StrategyType.ZERO_DTE:
                        composite = _apply_settlement_adjustment(ticker, composite)

                    entry = RankedEntry(
                        rank=0,  # assigned after sorting
                        ticker=ticker,
                        strategy_type=strategy,
                        verdict=result.verdict,
                        composite_score=round(composite, 4),
                        breakdown=breakdown,
                        strategy_name=_extract_strategy_name(result),
                        direction=_extract_direction(result),
                        rationale=_extract_rationale(result),
                        risk_notes=_extract_risk_notes(result),
                        trade_spec=_extract_trade_spec(result),
                    )

                    # Propagate data_gaps from assessor result
                    if hasattr(result, "data_gaps") and result.data_gaps:
                        entry.data_gaps.extend(result.data_gaps)

                    entries.append(entry)
                    opp_results[id(entry)] = result
                except Exception:
                    logger.warning(
                        "Assessment failed for %s/%s", ticker, strategy, exc_info=True
                    )
                    continue

        # 3. Sort by composite_score descending, assign ranks
        entries.sort(key=lambda e: e.composite_score, reverse=True)
        for i, entry in enumerate(entries):
            entry.rank = i + 1

        # Populate debug commentary after scoring
        if debug:
            for entry in entries:
                opp_result = opp_results.get(id(entry))
                if opp_result is None:
                    continue
                regime_id = _extract_regime_id(opp_result)
                entry.commentary.extend([
                    f"{entry.ticker} {entry.strategy_type}: verdict={opp_result.verdict} confidence={opp_result.confidence:.0%}",
                    f"  Regime R{regime_id} alignment={entry.breakdown.regime_alignment:.2f}",
                    f"Score {entry.composite_score:.2f} = verdict({entry.breakdown.verdict_score:.2f}) x confidence({entry.breakdown.confidence_score:.2f})",
                    f"  + regime_align({entry.breakdown.regime_alignment:.2f}) + phase_align({entry.breakdown.phase_alignment:.2f})",
                    f"  + income_boost({entry.breakdown.income_bias_boost:.2f}) - BS_penalty({entry.breakdown.black_swan_penalty:.2f})",
                    f"  - macro({entry.breakdown.macro_penalty:.2f}) - earnings({entry.breakdown.earnings_penalty:.2f})",
                ])
                # Add hard_stops if present
                if hasattr(opp_result, "hard_stops") and opp_result.hard_stops:
                    entry.commentary.append(
                        f"  Hard stops: {', '.join(h.name for h in opp_result.hard_stops)}"
                    )
                # Note data_gaps in commentary
                if entry.data_gaps:
                    gap_names = ", ".join(g.field for g in entry.data_gaps)
                    entry.commentary.append(f"  Data gaps: {gap_names}")

        # 4. Group by ticker and by strategy
        by_ticker: dict[str, list[RankedEntry]] = defaultdict(list)
        by_strategy: dict[StrategyType, list[RankedEntry]] = defaultdict(list)

        for entry in entries:
            by_ticker[entry.ticker].append(entry)
            by_strategy[entry.strategy_type].append(entry)

        # Ensure all tickers/strategies appear even if empty
        for t in tickers:
            if t not in by_ticker:
                by_ticker[t] = []
        for s in strategies:
            if s not in by_strategy:
                by_strategy[s] = []

        total_actionable = sum(1 for e in entries if e.verdict != Verdict.NO_GO)

        # 5. Build regime transition watch items
        watch_items = self._build_watch_items(ticker_regime, iv_rank_map)

        # Generate summary
        summary = self._build_summary(entries, total_assessed, total_actionable, black_swan_level)

        return TradeRankingResult(
            as_of_date=as_of,
            tickers=tickers,
            top_trades=entries,
            by_ticker=dict(by_ticker),
            by_strategy=dict(by_strategy),
            black_swan_level=black_swan_level.value,
            black_swan_gate=False,
            total_assessed=total_assessed,
            total_actionable=total_actionable,
            summary=summary,
            watch_items=watch_items,
        )

    def record_feedback(self, feedback: RankingFeedback) -> None:
        """Store feedback for future RL training. Appends to parquet."""
        try:
            import pandas as pd

            feedback_dir = Path.home() / ".income_desk" / "feedback"
            feedback_dir.mkdir(parents=True, exist_ok=True)
            path = feedback_dir / "ranking_feedback.parquet"

            row = feedback.model_dump()
            df_new = pd.DataFrame([row])

            if path.exists():
                df_existing = pd.read_parquet(path)
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
            else:
                df_combined = df_new

            df_combined.to_parquet(path, index=False)
            logger.info("Recorded ranking feedback: %s/%s", feedback.ticker, feedback.strategy_type)
        except Exception:
            logger.warning("Failed to record ranking feedback", exc_info=True)

    @staticmethod
    def _build_watch_items(
        ticker_regime: dict[str, int],
        iv_rank_map: dict[str, float | None] | None,
    ) -> list[WatchItem]:
        """Identify tickers in non-income regimes (R3/R4) with elevated IV rank.

        These are worth watching because a regime transition would unlock
        exceptional premium-selling opportunities.
        """
        if not iv_rank_map:
            return []

        items: list[WatchItem] = []
        for ticker, regime_id in ticker_regime.items():
            ivr = iv_rank_map.get(ticker)
            if ivr is None:
                continue

            if regime_id == 3 and ivr > 50:
                items.append(WatchItem(
                    ticker=ticker,
                    current_regime=3,
                    target_regime=2,
                    iv_rank=ivr,
                    trigger="R3 \u2192 R2 transition",
                    rationale=(
                        f"IVR {ivr:.1f}% \u2014 when vol stays high but trend exhausts, "
                        "premium will be exceptional for income strategies"
                    ),
                ))
            elif regime_id == 4 and ivr > 40:
                items.append(WatchItem(
                    ticker=ticker,
                    current_regime=4,
                    target_regime=2,
                    iv_rank=ivr,
                    trigger="R4 \u2192 R2 transition",
                    rationale=(
                        f"IVR {ivr:.1f}% \u2014 post-crash recovery is the highest "
                        "premium cycle for income strategies"
                    ),
                ))

        # Sort by IV rank descending — highest premium opportunity first
        items.sort(key=lambda w: w.iv_rank or 0, reverse=True)
        return items

    @staticmethod
    def _build_summary(
        entries: list[RankedEntry],
        total_assessed: int,
        total_actionable: int,
        alert_level: AlertLevel,
    ) -> str:
        if not entries:
            return f"No trades assessed. Alert level: {alert_level.value}."

        best = entries[0]
        go_count = sum(1 for e in entries if e.verdict == Verdict.GO)

        parts = [
            f"Ranked {total_assessed} ticker/strategy pairs.",
            f"{total_actionable} actionable ({go_count} GO, {total_actionable - go_count} CAUTION).",
        ]
        if best.composite_score > 0:
            parts.append(
                f"Top: {best.ticker} {best.strategy_type} "
                f"(score={best.composite_score:.2f}, {best.verdict})."
            )
        if alert_level != AlertLevel.NORMAL:
            parts.append(f"Alert: {alert_level.value}.")

        return " ".join(parts)
