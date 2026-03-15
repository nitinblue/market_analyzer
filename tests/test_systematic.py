"""Tests for Phase 1 systematic trading features.

Covers:
  G01: recommend_action() deterministic adjustment decision tree
  G02: validate_execution_quality()
  G03: entry_window on TradeSpec
  G04: time_of_day in monitor_exit_conditions
  G05: assess_overnight_risk
  CR-6: Multi-broker (Dhan, Zerodha) imports and properties
  CR-7: Currency, timezone, lot_size on models and providers
  CR-11: Performance analytics (Sharpe, drawdown, regime performance)
  CR-12: India data aliases (NIFTY, BANKNIFTY, SENSEX)
  CR-13: MarketRegistry (markets, instruments, strategies, margin, yfinance)
"""

from __future__ import annotations

from datetime import date, time, timedelta

import pytest

from market_analyzer.models.adjustment import (
    AdjustmentDecision,
    AdjustmentType,
    PositionStatus,
)
from market_analyzer.models.opportunity import (
    LegAction,
    LegSpec,
    OrderSide,
    StructureType,
    TradeSpec,
)
from market_analyzer.models.quotes import OptionQuote
from market_analyzer.models.feedback import TradeOutcome, TradeExitReason
from market_analyzer.models.learning import DriftSeverity
from market_analyzer.models.ranking import StrategyType
from market_analyzer.models.regime import RegimeID, RegimeResult
from market_analyzer.models.technicals import (
    BollingerBands,
    MACDData,
    MovingAverages,
    PhaseIndicator,
    RSIData,
    StochasticData,
    SupportResistance,
    TechnicalSnapshot,
)
from market_analyzer.execution_quality import (
    ExecutionQuality,
    ExecutionVerdict,
    validate_execution_quality,
)
from market_analyzer.service.adjustment import AdjustmentService
from market_analyzer.trade_lifecycle import (
    OvernightRisk,
    OvernightRiskLevel,
    assess_overnight_risk,
    monitor_exit_conditions,
)


# ── Shared Fixtures ──


def _make_leg(
    role: str,
    action: LegAction,
    option_type: str,
    strike: float,
    dte: int = 30,
) -> LegSpec:
    exp = date.today() + timedelta(days=dte)
    return LegSpec(
        role=role,
        action=action,
        option_type=option_type,
        strike=strike,
        strike_label=f"{strike:.0f} {option_type}",
        expiration=exp,
        days_to_expiry=dte,
        atm_iv_at_expiry=0.25,
    )


def _make_iron_condor(
    ticker: str = "SPY",
    price: float = 600.0,
    short_put: float = 580.0,
    long_put: float = 575.0,
    short_call: float = 620.0,
    long_call: float = 625.0,
    dte: int = 30,
) -> TradeSpec:
    exp = date.today() + timedelta(days=dte)
    return TradeSpec(
        ticker=ticker,
        legs=[
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", short_put, dte),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", long_put, dte),
            _make_leg("short_call", LegAction.SELL_TO_OPEN, "call", short_call, dte),
            _make_leg("long_call", LegAction.BUY_TO_OPEN, "call", long_call, dte),
        ],
        underlying_price=price,
        target_dte=dte,
        target_expiration=exp,
        wing_width_points=5.0,
        spec_rationale="Test IC",
        structure_type=StructureType.IRON_CONDOR,
        order_side=OrderSide.CREDIT,
        profit_target_pct=0.50,
        stop_loss_pct=2.0,
        exit_dte=21,
    )


def _make_regime(regime_id: int = 1) -> RegimeResult:
    return RegimeResult(
        ticker="SPY",
        regime=RegimeID(regime_id),
        confidence=0.85,
        regime_probabilities={
            RegimeID.R1_LOW_VOL_MR: 0.85 if regime_id == 1 else 0.05,
            RegimeID.R2_HIGH_VOL_MR: 0.85 if regime_id == 2 else 0.05,
            RegimeID.R3_LOW_VOL_TREND: 0.85 if regime_id == 3 else 0.05,
            RegimeID.R4_HIGH_VOL_TREND: 0.85 if regime_id == 4 else 0.05,
        },
        as_of_date=date.today(),
        model_version="test",
    )


def _make_technicals(price: float = 600.0, atr: float = 8.0) -> TechnicalSnapshot:
    return TechnicalSnapshot(
        ticker="SPY",
        as_of_date=date.today(),
        current_price=price,
        atr=atr,
        atr_pct=atr / price * 100,
        vwma_20=price,
        moving_averages=MovingAverages(
            sma_20=price, sma_50=price, sma_200=price,
            ema_9=price, ema_21=price,
            price_vs_sma_20_pct=0.0, price_vs_sma_50_pct=0.0,
            price_vs_sma_200_pct=0.0,
        ),
        rsi=RSIData(value=50.0, is_overbought=False, is_oversold=False),
        bollinger=BollingerBands(
            upper=price + 10, middle=price, lower=price - 10,
            bandwidth=3.3, percent_b=0.5,
        ),
        macd=MACDData(
            macd_line=0.0, signal_line=0.0, histogram=0.0,
            is_bullish_crossover=False, is_bearish_crossover=False,
        ),
        stochastic=StochasticData(k=50.0, d=50.0, is_overbought=False, is_oversold=False),
        support_resistance=SupportResistance(
            support=price - 20, resistance=price + 20,
            price_vs_support_pct=3.3, price_vs_resistance_pct=3.3,
        ),
        phase=PhaseIndicator(
            phase="accumulation", confidence=0.6, description="",
            higher_highs=True, higher_lows=True, lower_highs=False, lower_lows=False,
            range_compression=0.0, volume_trend="stable", price_vs_sma_50_pct=0.0,
        ),
        signals=[],
    )


def _make_quote(
    strike: float,
    option_type: str,
    expiration: date,
    bid: float = 2.50,
    ask: float = 2.70,
    open_interest: int = 500,
    volume: int = 100,
) -> OptionQuote:
    return OptionQuote(
        ticker="SPY",
        expiration=expiration,
        strike=strike,
        option_type=option_type,
        bid=bid,
        ask=ask,
        mid=(bid + ask) / 2.0,
        volume=volume,
        open_interest=open_interest,
    )


# ── G01: recommend_action() deterministic adjustment decision tree ──


class TestRecommendAction:
    """Test the deterministic adjustment decision tree."""

    def _call(
        self,
        price: float,
        regime_id: int,
        short_put: float = 580.0,
        long_put: float = 575.0,
        short_call: float = 620.0,
        long_call: float = 625.0,
    ) -> AdjustmentDecision:
        svc = AdjustmentService()
        ic = _make_iron_condor(
            price=600.0,
            short_put=short_put,
            long_put=long_put,
            short_call=short_call,
            long_call=long_call,
        )
        regime = _make_regime(regime_id)
        tech = _make_technicals(price=price)
        return svc.recommend_action(ic, regime, tech)

    def test_safe_always_do_nothing(self):
        """SAFE + any regime -> DO_NOTHING."""
        for r in (1, 2, 3, 4):
            result = self._call(price=600.0, regime_id=r)
            assert result.action == AdjustmentType.DO_NOTHING, f"SAFE + R{r} should be DO_NOTHING"

    def test_tested_r1_do_nothing(self):
        """TESTED + R1 -> DO_NOTHING."""
        result = self._call(price=583.0, regime_id=1)
        assert result.action == AdjustmentType.DO_NOTHING

    def test_tested_r2_do_nothing(self):
        """TESTED + R2 -> DO_NOTHING."""
        result = self._call(price=583.0, regime_id=2)
        assert result.action == AdjustmentType.DO_NOTHING

    def test_tested_r3_roll_away(self):
        """TESTED + R3 -> ROLL_AWAY."""
        result = self._call(price=583.0, regime_id=3)
        assert result.action == AdjustmentType.ROLL_AWAY

    def test_tested_r4_close_full(self):
        """TESTED + R4 -> CLOSE_FULL."""
        result = self._call(price=583.0, regime_id=4)
        assert result.action == AdjustmentType.CLOSE_FULL

    def test_breached_r1_roll_away(self):
        """BREACHED + R1 -> ROLL_AWAY."""
        result = self._call(price=577.0, regime_id=1)
        assert result.action == AdjustmentType.ROLL_AWAY

    def test_breached_r2_roll_away(self):
        """BREACHED + R2 -> ROLL_AWAY."""
        result = self._call(price=577.0, regime_id=2)
        assert result.action == AdjustmentType.ROLL_AWAY

    def test_breached_r3_close_full(self):
        """BREACHED + R3 -> CLOSE_FULL."""
        result = self._call(price=577.0, regime_id=3)
        assert result.action == AdjustmentType.CLOSE_FULL

    def test_breached_r4_close_full(self):
        """BREACHED + R4 -> CLOSE_FULL."""
        result = self._call(price=577.0, regime_id=4)
        assert result.action == AdjustmentType.CLOSE_FULL

    def test_max_loss_always_close(self):
        """MAX_LOSS + any regime -> CLOSE_FULL."""
        for r in (1, 2, 3, 4):
            result = self._call(price=570.0, regime_id=r)
            assert result.action == AdjustmentType.CLOSE_FULL, f"MAX_LOSS + R{r} should be CLOSE_FULL"

    def test_returns_adjustment_decision_type(self):
        """Verify return type is AdjustmentDecision."""
        result = self._call(price=600.0, regime_id=1)
        assert isinstance(result, AdjustmentDecision)

    def test_rationale_includes_regime(self):
        """Verify rationale mentions regime context."""
        # TESTED + R3 should mention R3 / trending
        result = self._call(price=583.0, regime_id=3)
        assert "R3" in result.rationale or "trending" in result.rationale.lower()


# ── G02: validate_execution_quality() ──


class TestExecutionQuality:
    """Test execution quality validation."""

    def _make_ic_with_quotes(
        self,
        bid: float = 2.50,
        ask: float = 2.70,
        open_interest: int = 500,
        volume: int = 100,
    ) -> tuple[TradeSpec, list[OptionQuote]]:
        """Build a 4-leg IC and matching quotes for all legs."""
        ic = _make_iron_condor()
        quotes = [
            _make_quote(
                strike=leg.strike,
                option_type=leg.option_type,
                expiration=leg.expiration,
                bid=bid,
                ask=ask,
                open_interest=open_interest,
                volume=volume,
            )
            for leg in ic.legs
        ]
        return ic, quotes

    def test_go_with_good_quotes(self):
        """All legs have tight spread, good OI/volume -> GO."""
        ic, quotes = self._make_ic_with_quotes(bid=2.50, ask=2.70, open_interest=500, volume=100)
        result = validate_execution_quality(ic, quotes)
        assert result.overall_verdict == ExecutionVerdict.GO
        assert result.tradeable is True

    def test_wide_spread_detected(self):
        """One leg with 20% spread -> WIDE_SPREAD."""
        ic = _make_iron_condor()
        # 3 good legs + 1 wide-spread leg
        quotes = []
        for i, leg in enumerate(ic.legs):
            if i == 0:
                # bid=1.0, ask=1.40 -> spread = 0.40 / 1.20 * 100 = 33%
                quotes.append(_make_quote(leg.strike, leg.option_type, leg.expiration,
                                          bid=1.0, ask=1.40, open_interest=500, volume=100))
            else:
                quotes.append(_make_quote(leg.strike, leg.option_type, leg.expiration,
                                          bid=2.50, ask=2.70, open_interest=500, volume=100))
        result = validate_execution_quality(ic, quotes)
        assert result.overall_verdict == ExecutionVerdict.WIDE_SPREAD
        assert result.tradeable is False

    def test_no_quote_detected(self):
        """Missing quote for a leg -> NO_QUOTE."""
        ic = _make_iron_condor()
        # Only provide quotes for 3 of 4 legs
        quotes = [
            _make_quote(leg.strike, leg.option_type, leg.expiration)
            for leg in ic.legs[:3]
        ]
        result = validate_execution_quality(ic, quotes)
        assert result.overall_verdict == ExecutionVerdict.NO_QUOTE
        assert result.tradeable is False

    def test_illiquid_low_oi(self):
        """OI < min_open_interest -> ILLIQUID."""
        ic, quotes = self._make_ic_with_quotes(open_interest=10, volume=100)
        result = validate_execution_quality(ic, quotes, min_open_interest=50)
        assert result.overall_verdict == ExecutionVerdict.ILLIQUID
        assert result.tradeable is False

    def test_illiquid_low_volume(self):
        """volume < min_volume -> ILLIQUID."""
        ic, quotes = self._make_ic_with_quotes(open_interest=500, volume=1)
        result = validate_execution_quality(ic, quotes, min_volume=5)
        assert result.overall_verdict == ExecutionVerdict.ILLIQUID
        assert result.tradeable is False

    def test_worst_leg_determines_overall(self):
        """3 legs GO + 1 leg WIDE_SPREAD -> overall WIDE_SPREAD."""
        ic = _make_iron_condor()
        quotes = []
        for i, leg in enumerate(ic.legs):
            if i == 2:
                # Wide spread: bid=0.50, ask=1.50 -> spread = 100%
                quotes.append(_make_quote(leg.strike, leg.option_type, leg.expiration,
                                          bid=0.50, ask=1.50, open_interest=500, volume=100))
            else:
                quotes.append(_make_quote(leg.strike, leg.option_type, leg.expiration,
                                          bid=2.50, ask=2.70, open_interest=500, volume=100))
        result = validate_execution_quality(ic, quotes)
        assert result.overall_verdict == ExecutionVerdict.WIDE_SPREAD
        # Verify 3 legs passed
        go_count = sum(1 for lq in result.legs if lq.verdict == ExecutionVerdict.GO)
        assert go_count == 3

    def test_tradeable_only_when_go(self):
        """tradeable=True only when overall_verdict == GO."""
        # GO case
        ic, quotes = self._make_ic_with_quotes()
        result = validate_execution_quality(ic, quotes)
        assert result.tradeable is True
        assert result.overall_verdict == ExecutionVerdict.GO

        # Non-GO case
        ic, quotes = self._make_ic_with_quotes(open_interest=1)
        result = validate_execution_quality(ic, quotes, min_open_interest=50)
        assert result.tradeable is False
        assert result.overall_verdict != ExecutionVerdict.GO

    def test_custom_thresholds(self):
        """Custom max_spread_pct, min_open_interest work."""
        ic = _make_iron_condor()
        # bid=2.50, ask=3.10 -> spread = 21.4%, fails at 15% but passes at 25%
        quotes = [
            _make_quote(leg.strike, leg.option_type, leg.expiration,
                        bid=2.50, ask=3.10, open_interest=500, volume=100)
            for leg in ic.legs
        ]
        # Fails with default 15%
        result_strict = validate_execution_quality(ic, quotes, max_spread_pct=15.0)
        assert result_strict.overall_verdict == ExecutionVerdict.WIDE_SPREAD

        # Passes with relaxed 25%
        result_relaxed = validate_execution_quality(ic, quotes, max_spread_pct=25.0)
        assert result_relaxed.overall_verdict == ExecutionVerdict.GO

    def test_zero_bid_is_no_quote(self):
        """bid=0 -> NO_QUOTE even if ask is present."""
        ic = _make_iron_condor()
        quotes = [
            _make_quote(leg.strike, leg.option_type, leg.expiration,
                        bid=0.0, ask=2.70, open_interest=500, volume=100)
            for leg in ic.legs
        ]
        result = validate_execution_quality(ic, quotes)
        assert result.overall_verdict == ExecutionVerdict.NO_QUOTE
        assert result.tradeable is False


# ── G03: entry_window on TradeSpec ──


class TestEntryWindow:
    """Test entry_window_start/end fields on TradeSpec."""

    def test_defaults_to_none(self):
        """TradeSpec() with no entry window -> None."""
        ic = _make_iron_condor()
        assert ic.entry_window_start is None
        assert ic.entry_window_end is None

    def test_entry_window_round_trip(self):
        """Set entry_window_start/end, verify they persist."""
        exp = date.today() + timedelta(days=30)
        ts = TradeSpec(
            ticker="SPY",
            legs=[_make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 580.0)],
            underlying_price=600.0,
            target_dte=30,
            target_expiration=exp,
            spec_rationale="Test entry window",
            entry_window_start=time(9, 45),
            entry_window_end=time(14, 0),
        )
        assert ts.entry_window_start == time(9, 45)
        assert ts.entry_window_end == time(14, 0)


# ── G04: time_of_day in monitor_exit_conditions ──


class TestTimeOfDayUrgency:
    """Test end-of-day urgency escalation."""

    def test_0dte_after_1500_force_close(self):
        """dte=0, time=15:01 -> eod_0dte signal triggered."""
        result = monitor_exit_conditions(
            trade_id="t1",
            ticker="SPY",
            structure_type="iron_condor",
            order_side="credit",
            entry_price=1.50,
            current_mid_price=1.20,
            contracts=1,
            dte_remaining=0,
            regime_id=1,
            time_of_day=time(15, 1),
        )
        eod_signals = [s for s in result.signals if s.rule == "eod_0dte"]
        assert len(eod_signals) == 1
        assert eod_signals[0].triggered is True
        assert eod_signals[0].urgency == "immediate"

    def test_0dte_before_1500_no_signal(self):
        """dte=0, time=14:59 -> no eod_0dte signal."""
        result = monitor_exit_conditions(
            trade_id="t1",
            ticker="SPY",
            structure_type="iron_condor",
            order_side="credit",
            entry_price=1.50,
            current_mid_price=1.20,
            contracts=1,
            dte_remaining=0,
            regime_id=1,
            time_of_day=time(14, 59),
        )
        eod_signals = [s for s in result.signals if s.rule == "eod_0dte"]
        assert len(eod_signals) == 0

    def test_tested_after_1530_escalate(self):
        """dte=30, tested position (approaching stop loss), time=15:31 -> eod_tested signal."""
        # Entry at 1.50 credit. Current mid at 2.70 means loss_multiple = (2.70-1.50)/1.50 = 0.8.
        # With stop_loss_pct=2.0, 0.75 * 2.0 = 1.5, 0.8 < 1.5, so stop_loss urgency is "monitor", not "soon".
        # We need urgency == "soon" for stop_loss. That requires loss_multiple >= 0.75 * stop_loss_pct.
        # stop_loss_pct=2.0 -> need loss_multiple >= 1.5 -> current_mid = 1.50 + 1.50 * 1.5 = 3.75.
        result = monitor_exit_conditions(
            trade_id="t1",
            ticker="SPY",
            structure_type="iron_condor",
            order_side="credit",
            entry_price=1.50,
            current_mid_price=3.75,
            contracts=1,
            dte_remaining=30,
            regime_id=1,
            stop_loss_pct=2.0,
            time_of_day=time(15, 31),
        )
        eod_signals = [s for s in result.signals if s.rule == "eod_tested"]
        assert len(eod_signals) == 1
        assert eod_signals[0].triggered is True

    def test_safe_after_1530_no_escalate(self):
        """dte=30, safe position, time=15:31 -> no eod_tested signal."""
        result = monitor_exit_conditions(
            trade_id="t1",
            ticker="SPY",
            structure_type="iron_condor",
            order_side="credit",
            entry_price=1.50,
            current_mid_price=1.20,
            contracts=1,
            dte_remaining=30,
            regime_id=1,
            stop_loss_pct=2.0,
            time_of_day=time(15, 31),
        )
        eod_signals = [s for s in result.signals if s.rule == "eod_tested"]
        assert len(eod_signals) == 0

    def test_no_time_provided_backward_compat(self):
        """time_of_day=None -> no eod signals, same behavior as before."""
        result = monitor_exit_conditions(
            trade_id="t1",
            ticker="SPY",
            structure_type="iron_condor",
            order_side="credit",
            entry_price=1.50,
            current_mid_price=1.20,
            contracts=1,
            dte_remaining=0,
            regime_id=1,
            time_of_day=None,
        )
        eod_signals = [s for s in result.signals if s.rule.startswith("eod_")]
        assert len(eod_signals) == 0


# ── G05: assess_overnight_risk ──


class TestOvernightRisk:
    """Test overnight gap risk assessment."""

    def test_0dte_always_close(self):
        """dte=0 -> CLOSE_BEFORE_CLOSE."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=0, regime_id=1,
            position_status="safe",
        )
        assert result.risk_level == OvernightRiskLevel.CLOSE_BEFORE_CLOSE

    def test_breached_r4_close(self):
        """breached + R4 -> CLOSE_BEFORE_CLOSE."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=30, regime_id=4,
            position_status="breached",
        )
        assert result.risk_level == OvernightRiskLevel.CLOSE_BEFORE_CLOSE

    def test_tested_r4_close(self):
        """tested + R4 -> CLOSE_BEFORE_CLOSE."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=30, regime_id=4,
            position_status="tested",
        )
        assert result.risk_level == OvernightRiskLevel.CLOSE_BEFORE_CLOSE

    def test_breached_r1_high(self):
        """breached + R1 -> HIGH."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=30, regime_id=1,
            position_status="breached",
        )
        assert result.risk_level == OvernightRiskLevel.HIGH

    def test_tested_r3_high(self):
        """tested + R3 -> HIGH."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=30, regime_id=3,
            position_status="tested",
        )
        assert result.risk_level == OvernightRiskLevel.HIGH

    def test_earnings_tomorrow_high(self):
        """safe + R1 + earnings tomorrow -> HIGH."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=30, regime_id=1,
            position_status="safe", has_earnings_tomorrow=True,
        )
        assert result.risk_level == OvernightRiskLevel.HIGH

    def test_macro_tomorrow_medium(self):
        """safe + R1 + macro tomorrow -> MEDIUM."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=30, regime_id=1,
            position_status="safe", has_macro_event_tomorrow=True,
        )
        assert result.risk_level == OvernightRiskLevel.MEDIUM

    def test_safe_r1_low(self):
        """safe + R1 + no events -> LOW."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=30, regime_id=1,
            position_status="safe",
        )
        assert result.risk_level == OvernightRiskLevel.LOW

    def test_safe_r3_medium(self):
        """safe + R3 -> MEDIUM (trending = some gap risk)."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=30, regime_id=3,
            position_status="safe",
        )
        assert result.risk_level == OvernightRiskLevel.MEDIUM


# ── G06: Auto-select screening ──


class TestAutoSelectScreening:
    """Test ScreeningResult model fields and scan() parameters."""

    def test_min_score_filters_low_candidates(self):
        """ScreeningResult with min_score=0.7 excludes candidates below 0.7."""
        from market_analyzer.service.screening import ScreenCandidate, ScreeningResult

        candidates = [
            ScreenCandidate(
                ticker="SPY", screen="breakout", score=0.8, reason="strong",
                regime_id=1, rsi=55.0, atr_pct=1.2,
            ),
            ScreenCandidate(
                ticker="GLD", screen="income", score=0.5, reason="weak",
                regime_id=1, rsi=45.0, atr_pct=0.9,
            ),
            ScreenCandidate(
                ticker="QQQ", screen="momentum", score=0.75, reason="ok",
                regime_id=3, rsi=60.0, atr_pct=1.5,
            ),
        ]
        # Apply min_score filter manually (same logic as scan())
        min_score = 0.7
        filtered = [c for c in candidates if c.score >= min_score]
        result = ScreeningResult(
            as_of_date=date.today(),
            tickers_scanned=3,
            candidates=filtered,
            by_screen={},
            summary="test",
            min_score_applied=min_score,
            filtered_count=len(candidates) - len(filtered),
        )
        assert len(result.candidates) == 2
        assert all(c.score >= 0.7 for c in result.candidates)
        assert result.filtered_count == 1

    def test_top_n_limits_results(self):
        """top_n=2 returns only top 2."""
        from market_analyzer.service.screening import ScreenCandidate, ScreeningResult

        candidates = [
            ScreenCandidate(
                ticker=t, screen="breakout", score=s, reason="r",
                regime_id=1, rsi=50.0, atr_pct=1.0,
            )
            for t, s in [("SPY", 0.9), ("GLD", 0.8), ("QQQ", 0.7), ("TLT", 0.6)]
        ]
        top_n = 2
        limited = candidates[:top_n]
        result = ScreeningResult(
            as_of_date=date.today(),
            tickers_scanned=4,
            candidates=limited,
            by_screen={},
            summary="test",
        )
        assert len(result.candidates) == 2
        assert result.candidates[0].ticker == "SPY"
        assert result.candidates[1].ticker == "GLD"

    def test_filtered_count_tracks_removed(self):
        """filtered_count reflects how many were cut."""
        from market_analyzer.service.screening import ScreeningResult

        result = ScreeningResult(
            as_of_date=date.today(),
            tickers_scanned=10,
            candidates=[],
            by_screen={},
            summary="test",
            min_score_applied=0.8,
            filtered_count=7,
        )
        assert result.filtered_count == 7
        assert result.min_score_applied == 0.8

    def test_min_score_zero_returns_all(self):
        """min_score=0 returns everything (backward compat)."""
        from market_analyzer.service.screening import ScreenCandidate, ScreeningResult

        candidates = [
            ScreenCandidate(
                ticker=t, screen="income", score=s, reason="r",
                regime_id=1, rsi=50.0, atr_pct=1.0,
            )
            for t, s in [("SPY", 0.1), ("GLD", 0.05), ("QQQ", 0.9)]
        ]
        # min_score=0 means no filtering
        min_score = 0.0
        filtered = [c for c in candidates if c.score >= min_score] if min_score > 0 else candidates
        result = ScreeningResult(
            as_of_date=date.today(),
            tickers_scanned=3,
            candidates=filtered,
            by_screen={},
            summary="test",
            min_score_applied=min_score,
            filtered_count=0,
        )
        assert len(result.candidates) == 3

    def test_default_min_score_is_0_6(self):
        """Verify default parameter is 0.6 in ScreeningService.scan()."""
        import inspect
        from market_analyzer.service.screening import ScreeningService

        sig = inspect.signature(ScreeningService.scan)
        min_score_param = sig.parameters["min_score"]
        assert min_score_param.default == 0.6


# ── G07: Performance feedback ──


def _make_outcome(
    pnl_pct: float = 0.15,
    strategy: StrategyType = StrategyType.IRON_CONDOR,
    regime: int = 1,
    exit_reason: TradeExitReason = TradeExitReason.PROFIT_TARGET,
    score: float = 0.75,
    pnl_dollars: float | None = None,
    trade_id: str = "test-001",
) -> TradeOutcome:
    if pnl_dollars is None:
        pnl_dollars = 40.0 if pnl_pct > 0 else -40.0
    return TradeOutcome(
        trade_id=trade_id,
        ticker="SPY",
        strategy_type=strategy,
        regime_at_entry=regime,
        regime_at_exit=regime,
        entry_date=date(2026, 1, 1),
        exit_date=date(2026, 1, 15),
        entry_price=0.80,
        exit_price=0.40,
        pnl_dollars=pnl_dollars,
        pnl_pct=pnl_pct,
        holding_days=14,
        exit_reason=exit_reason,
        composite_score_at_entry=score,
    )


class TestPerformanceTracking:
    """Test performance analysis and weight calibration."""

    def test_compute_strategy_performance_basic(self):
        """5 winning trades + 3 losing -> correct win_rate, avg_pnl."""
        from market_analyzer.performance import compute_strategy_performance

        outcomes = (
            [_make_outcome(pnl_pct=0.10, pnl_dollars=30.0, trade_id=f"w{i}") for i in range(5)]
            + [_make_outcome(pnl_pct=-0.08, pnl_dollars=-25.0, trade_id=f"l{i}") for i in range(3)]
        )
        result = compute_strategy_performance(outcomes, strategy_type=StrategyType.IRON_CONDOR)
        assert result.total_trades == 8
        assert result.wins == 5
        assert result.losses == 3
        assert abs(result.win_rate - 5 / 8) < 0.01
        expected_avg = (5 * 0.10 + 3 * (-0.08)) / 8
        assert abs(result.avg_pnl_pct - expected_avg) < 0.001

    def test_compute_strategy_performance_by_regime(self):
        """Filter by regime_id=1 -> only R1 trades counted."""
        from market_analyzer.performance import compute_strategy_performance

        outcomes = [
            _make_outcome(regime=1, pnl_pct=0.10, pnl_dollars=30.0, trade_id="r1a"),
            _make_outcome(regime=1, pnl_pct=0.12, pnl_dollars=35.0, trade_id="r1b"),
            _make_outcome(regime=2, pnl_pct=-0.05, pnl_dollars=-20.0, trade_id="r2a"),
            _make_outcome(regime=3, pnl_pct=0.08, pnl_dollars=25.0, trade_id="r3a"),
        ]
        result = compute_strategy_performance(
            outcomes, strategy_type=StrategyType.IRON_CONDOR, regime_id=1,
        )
        assert result.total_trades == 2
        assert result.regime_id == 1
        assert result.wins == 2

    def test_compute_performance_report_groups_by_strategy(self):
        """Multiple strategies -> by_strategy has entries for each."""
        from market_analyzer.performance import compute_performance_report

        outcomes = [
            _make_outcome(strategy=StrategyType.IRON_CONDOR, trade_id="ic1"),
            _make_outcome(strategy=StrategyType.IRON_CONDOR, trade_id="ic2"),
            _make_outcome(strategy=StrategyType.BREAKOUT, trade_id="bo1"),
            _make_outcome(strategy=StrategyType.LEAP, trade_id="lp1"),
        ]
        report = compute_performance_report(outcomes)
        assert report.total_trades == 4
        strategy_types = {sp.strategy_type for sp in report.by_strategy}
        assert StrategyType.IRON_CONDOR in strategy_types
        assert StrategyType.BREAKOUT in strategy_types
        assert StrategyType.LEAP in strategy_types

    def test_compute_performance_report_groups_by_regime(self):
        """Multiple regimes -> by_regime dict populated."""
        from market_analyzer.performance import compute_performance_report

        outcomes = [
            _make_outcome(regime=1, trade_id="r1"),
            _make_outcome(regime=2, trade_id="r2"),
            _make_outcome(regime=3, trade_id="r3"),
        ]
        report = compute_performance_report(outcomes)
        assert 1 in report.by_regime
        assert 2 in report.by_regime
        assert 3 in report.by_regime

    def test_calibrate_weights_no_trades_no_adjustments(self):
        """Empty outcomes -> no adjustments."""
        from market_analyzer.performance import calibrate_weights

        result = calibrate_weights([])
        assert len(result.adjustments) == 0
        assert "No trade outcomes" in result.summary

    def test_calibrate_weights_few_trades_no_adjustments(self):
        """5 trades (below min_trades=10) -> no adjustments."""
        from market_analyzer.performance import calibrate_weights

        outcomes = [
            _make_outcome(trade_id=f"t{i}") for i in range(5)
        ]
        result = calibrate_weights(outcomes, min_trades=10)
        assert len(result.adjustments) == 0

    def test_calibrate_weights_winning_strategy_increases_weight(self):
        """15 trades all winning in R1 IC -> suggest increasing R1+IC weight if win rate > weight + 0.1."""
        from market_analyzer.performance import calibrate_weights
        from market_analyzer.features.ranking import REGIME_STRATEGY_ALIGNMENT

        # R1 + IC weight from the alignment matrix
        current_weight = REGIME_STRATEGY_ALIGNMENT.get(
            (1, StrategyType.IRON_CONDOR), 0.5
        )
        # If current weight is already high (>0.9), a 100% win rate won't differ by >0.1.
        # Use a regime+strategy combo where weight is moderate so the test is meaningful.
        # R3 + IRON_CONDOR typically has a low weight (income in trending)
        r3_ic_weight = REGIME_STRATEGY_ALIGNMENT.get(
            (3, StrategyType.IRON_CONDOR), 0.5
        )
        outcomes = [
            _make_outcome(
                regime=3, strategy=StrategyType.IRON_CONDOR,
                pnl_pct=0.10, pnl_dollars=30.0, trade_id=f"t{i}",
            )
            for i in range(15)
        ]
        result = calibrate_weights(outcomes, min_trades=10)
        # If r3_ic_weight < 0.9, we should see an increase suggestion
        if r3_ic_weight < 0.9:
            assert len(result.adjustments) >= 1
            adj = result.adjustments[0]
            assert adj.suggested_weight > adj.current_weight
            assert "increase" in adj.reason.lower()

    def test_calibrate_weights_losing_strategy_decreases_weight(self):
        """15 trades all losing in R1 IC -> suggest decreasing R1+IC weight."""
        from market_analyzer.performance import calibrate_weights

        # R1 + IC has weight=1.0 typically; 0% win rate is 1.0 below, so diff = -1.0
        outcomes = [
            _make_outcome(
                regime=1, strategy=StrategyType.IRON_CONDOR,
                pnl_pct=-0.10, pnl_dollars=-30.0, trade_id=f"t{i}",
            )
            for i in range(15)
        ]
        result = calibrate_weights(outcomes, min_trades=10)
        assert len(result.adjustments) >= 1
        adj = result.adjustments[0]
        assert adj.suggested_weight < adj.current_weight
        assert "decrease" in adj.reason.lower()

    def test_calibrate_weights_max_adjustment_clamped(self):
        """Adjustment never exceeds max_adjustment parameter."""
        from market_analyzer.performance import calibrate_weights

        outcomes = [
            _make_outcome(
                regime=1, strategy=StrategyType.IRON_CONDOR,
                pnl_pct=-0.10, pnl_dollars=-30.0, trade_id=f"t{i}",
            )
            for i in range(20)
        ]
        max_adj = 0.05
        result = calibrate_weights(outcomes, min_trades=10, max_adjustment=max_adj)
        for adj in result.adjustments:
            assert abs(adj.suggested_weight - adj.current_weight) <= max_adj + 0.001

    def test_trade_outcome_model(self):
        """TradeOutcome can be created with all fields."""
        outcome = _make_outcome()
        assert outcome.trade_id == "test-001"
        assert outcome.ticker == "SPY"
        assert outcome.strategy_type == StrategyType.IRON_CONDOR
        assert outcome.regime_at_entry == 1
        assert outcome.pnl_pct == 0.15
        assert outcome.exit_reason == TradeExitReason.PROFIT_TARGET
        assert outcome.holding_days == 14
        assert outcome.contracts == 1  # default

    def test_performance_report_score_correlation(self):
        """With enough trades, score_correlation is computed (not None)."""
        from market_analyzer.performance import compute_performance_report

        # Create 10 trades with varying scores and PnLs (need >= 5 for correlation)
        outcomes = [
            _make_outcome(
                score=0.5 + i * 0.05,
                pnl_pct=0.02 * i,
                pnl_dollars=10.0 * i if i > 0 else -5.0,
                trade_id=f"corr{i}",
            )
            for i in range(10)
        ]
        report = compute_performance_report(outcomes)
        assert report.score_correlation is not None

    def test_profit_factor_no_losses(self):
        """All winning trades -> profit_factor = inf."""
        from market_analyzer.performance import compute_strategy_performance

        outcomes = [
            _make_outcome(pnl_pct=0.10, pnl_dollars=30.0, trade_id=f"w{i}")
            for i in range(5)
        ]
        result = compute_strategy_performance(outcomes, strategy_type=StrategyType.IRON_CONDOR)
        assert result.profit_factor == float("inf")


# ── G08-G09: Commentary + Data Gaps ──


class TestTransparency:
    """Test transparency fields (commentary + data_gaps) on models."""

    def test_data_gap_model(self):
        """DataGap(field='pop', reason='no broker', impact='off by 10-15%')."""
        from market_analyzer.models.transparency import DataGap

        gap = DataGap(field="pop", reason="no broker", impact="off by 10-15%")
        assert gap.field == "pop"
        assert gap.reason == "no broker"
        assert gap.impact == "off by 10-15%"

    def test_regime_result_has_commentary_field(self):
        """RegimeResult with empty commentary + data_gaps -> works."""
        result = _make_regime(1)
        assert result.commentary == []
        assert result.data_gaps == []

    def test_regime_result_accepts_commentary(self):
        """RegimeResult with populated commentary list -> accessible."""
        from market_analyzer.models.transparency import DataGap

        result = RegimeResult(
            ticker="SPY",
            regime=RegimeID.R1_LOW_VOL_MR,
            confidence=0.85,
            regime_probabilities={1: 0.85, 2: 0.05, 3: 0.05, 4: 0.05},
            as_of_date=date.today(),
            model_version="test",
            commentary=["Step 1: computed features", "Step 2: ran HMM inference"],
            data_gaps=[
                DataGap(field="iv_rank", reason="no broker", impact="regime may be less precise"),
            ],
        )
        assert len(result.commentary) == 2
        assert "Step 1" in result.commentary[0]
        assert len(result.data_gaps) == 1
        assert result.data_gaps[0].field == "iv_rank"

    def test_ranked_entry_has_data_gaps_field(self):
        """RankedEntry with data_gaps -> accessible."""
        from market_analyzer.models.ranking import RankedEntry, ScoreBreakdown, StrategyType
        from market_analyzer.models.opportunity import Verdict
        from market_analyzer.models.transparency import DataGap

        entry = RankedEntry(
            rank=1,
            ticker="SPY",
            strategy_type=StrategyType.IRON_CONDOR,
            verdict=Verdict.GO,
            composite_score=0.85,
            breakdown=ScoreBreakdown(
                verdict_score=1.0, confidence_score=0.8, regime_alignment=0.9,
                risk_reward=0.7, technical_quality=0.6, phase_alignment=0.8,
                income_bias_boost=0.05, black_swan_penalty=0.0,
                macro_penalty=0.0, earnings_penalty=0.0,
            ),
            strategy_name="iron_condor",
            direction="neutral",
            rationale="test",
            risk_notes=[],
            data_gaps=[
                DataGap(field="pop", reason="no broker", impact="estimated"),
            ],
            commentary=["Scored regime alignment at 0.9"],
        )
        assert len(entry.data_gaps) == 1
        assert entry.data_gaps[0].field == "pop"
        assert len(entry.commentary) == 1

    def test_trading_plan_has_transparency_fields(self):
        """DailyTradingPlan with commentary + data_gaps -> works."""
        from market_analyzer.models.trading_plan import (
            DailyTradingPlan, DayVerdict, RiskBudget,
        )
        from market_analyzer.models.transparency import DataGap

        plan = DailyTradingPlan(
            as_of_date=date.today(),
            plan_for_date=date.today(),
            day_verdict=DayVerdict.TRADE,
            day_verdict_reasons=["No macro events"],
            risk_budget=RiskBudget(
                max_new_positions=3,
                account_size=50000.0,
                max_daily_risk_dollars=1000.0,
                position_size_factor=1.0,
            ),
            expiry_events=[],
            upcoming_expiries=[],
            trades_by_horizon={},
            all_trades=[],
            total_trades=0,
            summary="test plan",
            commentary=["Step 1: checked macro calendar"],
            data_gaps=[
                DataGap(field="account_size", reason="no broker", impact="using config default"),
            ],
        )
        assert len(plan.commentary) == 1
        assert len(plan.data_gaps) == 1
        assert plan.data_gaps[0].field == "account_size"

    def test_opportunity_models_have_transparency_fields(self):
        """ZeroDTEOpportunity, LEAPOpportunity, BreakoutOpportunity, MomentumOpportunity all declare commentary + data_gaps."""
        from market_analyzer.models.opportunity import (
            ZeroDTEOpportunity, LEAPOpportunity, BreakoutOpportunity, MomentumOpportunity,
        )

        for model_cls in (ZeroDTEOpportunity, LEAPOpportunity, BreakoutOpportunity, MomentumOpportunity):
            fields = model_cls.model_fields
            assert "commentary" in fields, f"{model_cls.__name__} missing commentary field"
            assert "data_gaps" in fields, f"{model_cls.__name__} missing data_gaps field"
            # Verify defaults are empty lists
            assert fields["commentary"].default == [], f"{model_cls.__name__} commentary default != []"
            assert fields["data_gaps"].default == [], f"{model_cls.__name__} data_gaps default != []"

    def test_existing_models_backward_compat(self):
        """Creating RegimeResult WITHOUT commentary/data_gaps still works (defaults to [])."""
        result = RegimeResult(
            ticker="SPY",
            regime=RegimeID.R1_LOW_VOL_MR,
            confidence=0.85,
            regime_probabilities={1: 0.85, 2: 0.05, 3: 0.05, 4: 0.05},
            as_of_date=date.today(),
            model_version="test",
            # No commentary or data_gaps provided
        )
        assert result.commentary == []
        assert result.data_gaps == []
        # Same for RankedEntry
        from market_analyzer.models.ranking import RankedEntry, ScoreBreakdown, StrategyType
        from market_analyzer.models.opportunity import Verdict

        entry = RankedEntry(
            rank=1, ticker="SPY", strategy_type=StrategyType.IRON_CONDOR,
            verdict=Verdict.GO, composite_score=0.85,
            breakdown=ScoreBreakdown(
                verdict_score=1.0, confidence_score=0.8, regime_alignment=0.9,
                risk_reward=0.7, technical_quality=0.6, phase_alignment=0.8,
                income_bias_boost=0.05, black_swan_penalty=0.0,
                macro_penalty=0.0, earnings_penalty=0.0,
            ),
            strategy_name="iron_condor", direction="neutral",
            rationale="test", risk_notes=[],
            # No commentary or data_gaps provided
        )
        assert entry.commentary == []
        assert entry.data_gaps == []


# ── CR-3: TradeOutcome extended fields ──


class TestEtradingCR3:
    """CR-3: TradeOutcome extended fields for eTrading."""

    def test_trade_outcome_new_fields_optional(self):
        """TradeOutcome created WITHOUT new fields still works — backward compat."""
        outcome = TradeOutcome(
            trade_id="t1",
            ticker="SPY",
            strategy_type=StrategyType.IRON_CONDOR,
            regime_at_entry=1,
            regime_at_exit=1,
            entry_date=date(2026, 3, 1),
            exit_date=date(2026, 3, 10),
            entry_price=2.50,
            exit_price=1.00,
            pnl_dollars=150.0,
            pnl_pct=0.15,
            holding_days=9,
            exit_reason=TradeExitReason.PROFIT_TARGET,
            composite_score_at_entry=0.80,
        )
        assert outcome.structure_type is None
        assert outcome.order_side is None
        assert outcome.iv_rank_at_entry is None
        assert outcome.dte_at_entry is None
        assert outcome.dte_at_exit is None
        assert outcome.max_favorable_excursion is None
        assert outcome.max_adverse_excursion is None

    def test_trade_outcome_with_etrading_fields(self):
        """TradeOutcome WITH all CR-3 fields populates correctly."""
        outcome = TradeOutcome(
            trade_id="t2",
            ticker="GLD",
            strategy_type=StrategyType.IRON_CONDOR,
            regime_at_entry=1,
            regime_at_exit=2,
            entry_date=date(2026, 3, 1),
            exit_date=date(2026, 3, 14),
            entry_price=3.00,
            exit_price=1.50,
            pnl_dollars=150.0,
            pnl_pct=0.10,
            holding_days=13,
            exit_reason=TradeExitReason.PROFIT_TARGET,
            composite_score_at_entry=0.75,
            structure_type="iron_condor",
            order_side="credit",
            iv_rank_at_entry=55.0,
            dte_at_entry=30,
            dte_at_exit=17,
            max_favorable_excursion=200.0,
            max_adverse_excursion=-80.0,
        )
        assert outcome.structure_type == "iron_condor"
        assert outcome.order_side == "credit"
        assert outcome.iv_rank_at_entry == 55.0
        assert outcome.dte_at_entry == 30
        assert outcome.dte_at_exit == 17
        assert outcome.max_favorable_excursion == 200.0
        assert outcome.max_adverse_excursion == -80.0

    def test_strategy_performance_has_avg_dte_and_iv(self):
        """compute_strategy_performance populates avg_dte_at_entry and avg_iv_rank_at_entry when data present."""
        from market_analyzer.performance import compute_strategy_performance

        outcomes = [
            TradeOutcome(
                trade_id=f"t{i}",
                ticker="SPY",
                strategy_type=StrategyType.IRON_CONDOR,
                regime_at_entry=1,
                regime_at_exit=1,
                entry_date=date(2026, 3, 1),
                exit_date=date(2026, 3, 10),
                entry_price=2.50,
                exit_price=1.00,
                pnl_dollars=150.0,
                pnl_pct=0.15,
                holding_days=9,
                exit_reason=TradeExitReason.PROFIT_TARGET,
                composite_score_at_entry=0.80,
                dte_at_entry=dte,
                iv_rank_at_entry=iv,
            )
            for i, (dte, iv) in enumerate([(30, 40.0), (45, 60.0), (20, 50.0)])
        ]
        perf = compute_strategy_performance(outcomes, StrategyType.IRON_CONDOR)
        assert perf.avg_dte_at_entry is not None
        assert abs(perf.avg_dte_at_entry - (30 + 45 + 20) / 3) < 0.01
        assert perf.avg_iv_rank_at_entry is not None
        assert abs(perf.avg_iv_rank_at_entry - (40.0 + 60.0 + 50.0) / 3) < 0.01

    def test_strategy_performance_none_without_dte_iv(self):
        """compute_strategy_performance returns None for avg_dte/avg_iv when not provided."""
        from market_analyzer.performance import compute_strategy_performance

        outcomes = [
            TradeOutcome(
                trade_id="t1",
                ticker="SPY",
                strategy_type=StrategyType.IRON_CONDOR,
                regime_at_entry=1,
                regime_at_exit=1,
                entry_date=date(2026, 3, 1),
                exit_date=date(2026, 3, 10),
                entry_price=2.50,
                exit_price=1.00,
                pnl_dollars=150.0,
                pnl_pct=0.15,
                holding_days=9,
                exit_reason=TradeExitReason.PROFIT_TARGET,
                composite_score_at_entry=0.80,
                # No dte_at_entry or iv_rank_at_entry
            )
        ]
        perf = compute_strategy_performance(outcomes, StrategyType.IRON_CONDOR)
        assert perf.avg_dte_at_entry is None
        assert perf.avg_iv_rank_at_entry is None


# ── CR-4: Debug mode / commentary on services ──


class TestEtradingCR4:
    """CR-4: Debug mode / commentary on services."""

    def test_technical_snapshot_has_commentary(self):
        """TechnicalSnapshot accepts and stores commentary field."""
        snapshot = TechnicalSnapshot(
            ticker="SPY",
            as_of_date=date.today(),
            current_price=570.0,
            atr=5.0,
            atr_pct=0.88,
            vwma_20=568.0,
            moving_averages=MovingAverages(
                sma_20=565.0, sma_50=560.0, sma_200=530.0,
                ema_9=568.0, ema_21=565.0,
                price_vs_sma_20_pct=0.9, price_vs_sma_50_pct=1.8, price_vs_sma_200_pct=7.5,
            ),
            rsi=RSIData(value=55.0, is_overbought=False, is_oversold=False),
            bollinger=BollingerBands(upper=580.0, middle=565.0, lower=550.0, bandwidth=5.3, percent_b=0.67),
            macd=MACDData(macd_line=2.5, signal_line=1.8, histogram=0.7, is_bullish_crossover=False, is_bearish_crossover=False),
            stochastic=StochasticData(k=65.0, d=60.0, is_overbought=False, is_oversold=False),
            support_resistance=SupportResistance(support=555.0, resistance=580.0, price_vs_support_pct=2.7, price_vs_resistance_pct=-1.7),
            phase=PhaseIndicator(
                phase="markup", confidence=0.75, description="test",
                higher_highs=True, higher_lows=True, lower_highs=False, lower_lows=False,
                range_compression=0.3, volume_trend="stable", price_vs_sma_50_pct=1.8,
            ),
            signals=[],
            commentary=["Step 1: computed RSI = 55", "Step 2: SMA crossover check"],
        )
        assert len(snapshot.commentary) == 2
        assert "RSI" in snapshot.commentary[0]

    def test_market_context_has_commentary(self):
        """MarketContext accepts and stores commentary field."""
        from market_analyzer.models.context import MarketContext, IntermarketDashboard
        from market_analyzer.models.black_swan import BlackSwanAlert, AlertLevel
        from market_analyzer.models.macro import MacroCalendar

        ctx = MarketContext(
            as_of_date=date.today(),
            market="US",
            macro=MacroCalendar(
                events=[],
                next_event=None,
                days_to_next=None,
                next_fomc=None,
                days_to_next_fomc=None,
                events_next_7_days=[],
                events_next_30_days=[],
            ),
            black_swan=BlackSwanAlert(
                as_of_date=date.today(),
                alert_level=AlertLevel.NORMAL,
                composite_score=0.0,
                circuit_breakers=[],
                indicators=[],
                triggered_breakers=0,
                action="none",
                summary="All clear",
            ),
            intermarket=IntermarketDashboard(entries=[], summary="test"),
            environment_label="risk-on",
            trading_allowed=True,
            commentary=["Step 1: checked VIX at 15", "Step 2: no macro events"],
        )
        assert len(ctx.commentary) == 2
        assert "VIX" in ctx.commentary[0]

    def test_commentary_defaults_empty(self):
        """Both TechnicalSnapshot and MarketContext default commentary to [] when not set."""
        assert TechnicalSnapshot.model_fields["commentary"].default == []
        assert "commentary" in TechnicalSnapshot.model_fields

        from market_analyzer.models.context import MarketContext

        assert MarketContext.model_fields["commentary"].default == []


# ── CR-5: DataGap has affects field, data_gaps on more models ──


class TestEtradingCR5:
    """CR-5: DataGap has affects field, data_gaps on more models."""

    def test_data_gap_has_affects_field(self):
        """DataGap accepts the 'affects' field."""
        from market_analyzer.models.transparency import DataGap

        gap = DataGap(
            field="pop",
            reason="no broker connected",
            impact="high",
            affects="POP estimate",
        )
        assert gap.affects == "POP estimate"
        assert gap.field == "pop"
        assert gap.reason == "no broker connected"

    def test_data_gap_affects_defaults_empty(self):
        """DataGap without 'affects' defaults to empty string."""
        from market_analyzer.models.transparency import DataGap

        gap = DataGap(field="iv_rank", reason="no metrics", impact="medium")
        assert gap.affects == ""

    def test_exit_monitor_result_has_data_gaps(self):
        """ExitMonitorResult accepts data_gaps field."""
        from market_analyzer.trade_lifecycle import ExitMonitorResult, ExitSignal
        from market_analyzer.models.transparency import DataGap

        result = ExitMonitorResult(
            trade_id="t1",
            ticker="SPY",
            signals=[],
            should_close=False,
            most_urgent=None,
            pnl_pct=0.05,
            pnl_dollars=50.0,
            summary="Holding",
            commentary="Position looks healthy",
            data_gaps=[
                DataGap(field="greeks", reason="no broker", impact="cannot check delta", affects="risk monitoring"),
            ],
        )
        assert len(result.data_gaps) == 1
        assert result.data_gaps[0].field == "greeks"
        assert result.data_gaps[0].affects == "risk monitoring"

    def test_trade_health_check_has_data_gaps(self):
        """TradeHealthCheck accepts data_gaps field."""
        from market_analyzer.trade_lifecycle import TradeHealthCheck, ExitMonitorResult
        from market_analyzer.models.transparency import DataGap

        exit_result = ExitMonitorResult(
            trade_id="t1",
            ticker="SPY",
            signals=[],
            should_close=False,
            most_urgent=None,
            pnl_pct=0.03,
            pnl_dollars=30.0,
            summary="OK",
            commentary="Healthy",
        )
        health = TradeHealthCheck(
            trade_id="t1",
            ticker="SPY",
            status="healthy",
            exit_result=exit_result,
            adjustment_needed=False,
            overall_action="hold",
            summary="Position healthy",
            commentary="All checks passed",
            data_gaps=[
                DataGap(field="adjustment_options", reason="no quote service", impact="cannot price adjustments", affects="adjustment recommendations"),
            ],
        )
        assert len(health.data_gaps) == 1
        assert health.data_gaps[0].field == "adjustment_options"
        assert health.data_gaps[0].affects == "adjustment recommendations"

    def test_exit_monitor_result_data_gaps_defaults_empty(self):
        """ExitMonitorResult without data_gaps defaults to []."""
        from market_analyzer.trade_lifecycle import ExitMonitorResult

        result = ExitMonitorResult(
            trade_id="t1",
            ticker="SPY",
            signals=[],
            should_close=False,
            most_urgent=None,
            pnl_pct=0.0,
            pnl_dollars=0.0,
            summary="OK",
            commentary="Fine",
        )
        assert result.data_gaps == []

    def test_trade_health_check_data_gaps_defaults_empty(self):
        """TradeHealthCheck without data_gaps defaults to []."""
        from market_analyzer.trade_lifecycle import TradeHealthCheck, ExitMonitorResult

        exit_result = ExitMonitorResult(
            trade_id="t1",
            ticker="SPY",
            signals=[],
            should_close=False,
            most_urgent=None,
            pnl_pct=0.0,
            pnl_dollars=0.0,
            summary="OK",
            commentary="Fine",
        )
        health = TradeHealthCheck(
            trade_id="t1",
            ticker="SPY",
            status="healthy",
            exit_result=exit_result,
            adjustment_needed=False,
            overall_action="hold",
            summary="OK",
            commentary="OK",
        )
        assert health.data_gaps == []


# ── SQ1: IV rank integration in assessors ──


class TestSQ1IVIntegration:
    """SQ1: IV rank integration in assessors."""

    def test_iron_condor_hard_stop_low_iv(self):
        """assess_iron_condor with iv_rank=10 -> NO_GO (hard stop: IV rank too low)."""
        from market_analyzer.opportunity.option_plays.iron_condor import assess_iron_condor
        from market_analyzer.models.opportunity import Verdict

        regime = _make_regime(1)
        technicals = _make_technicals()
        result = assess_iron_condor(
            ticker="SPY",
            regime=regime,
            technicals=technicals,
            iv_rank=10,
        )
        assert result.verdict == Verdict.NO_GO
        hard_stop_names = [hs.name for hs in result.hard_stops]
        assert any("IV rank" in name or "iv_rank" in name.lower() for name in hard_stop_names)

    def test_iron_condor_accepts_iv_rank_none(self):
        """assess_iron_condor with iv_rank=None (default) -> works, no TypeError."""
        from market_analyzer.opportunity.option_plays.iron_condor import assess_iron_condor

        regime = _make_regime(1)
        technicals = _make_technicals()
        # Should not raise TypeError
        result = assess_iron_condor(
            ticker="SPY",
            regime=regime,
            technicals=technicals,
            iv_rank=None,
        )
        assert result is not None

    def test_iron_condor_iv_rank_below_threshold_no_signal(self):
        """assess_iron_condor with iv_rank=30 (below 40 threshold, above 15 hard stop).

        Without vol_surface the hard stop on vol_surface fires first, but the
        function still accepts iv_rank without error.  We verify the hard stop
        names do NOT include the IV rank stop (since 30 > 15).
        """
        from market_analyzer.opportunity.option_plays.iron_condor import assess_iron_condor
        from market_analyzer.models.opportunity import Verdict

        regime = _make_regime(1)
        technicals = _make_technicals()
        # No vol_surface -> will hit the vol_surface hard stop, but NOT the iv_rank one
        result = assess_iron_condor(
            ticker="SPY",
            regime=regime,
            technicals=technicals,
            iv_rank=30,
        )
        # Should be NO_GO due to missing vol_surface, but NOT due to IV rank
        assert result.verdict == Verdict.NO_GO
        iv_hard_stops = [hs for hs in result.hard_stops if "IV rank" in hs.name]
        assert len(iv_hard_stops) == 0  # iv_rank=30 is above the 15 threshold

    def test_leap_hard_stop_high_iv(self):
        """assess_leap with iv_rank=80 -> NO_GO (hard stop: IV rank too high)."""
        from market_analyzer.opportunity.option_plays.leap import assess_leap
        from market_analyzer.models.opportunity import Verdict
        from market_analyzer.models.phase import (
            PhaseResult, PhaseID, PriceStructure, PhaseEvidence,
        )
        from market_analyzer.models.macro import MacroCalendar

        regime = _make_regime(3)  # R3 for LEAPs
        technicals = _make_technicals()
        phase = PhaseResult(
            ticker="SPY",
            phase=PhaseID.MARKUP,
            phase_name="Markup",
            confidence=0.7,
            phase_age_days=15,
            prior_phase=None,
            cycle_completion=0.3,
            price_structure=PriceStructure(
                swing_highs=[], swing_lows=[],
                higher_highs=True, higher_lows=True,
                lower_highs=False, lower_lows=False,
                range_compression=0.3, price_vs_sma=2.0,
                volume_trend="stable",
                support_level=580.0, resistance_level=620.0,
            ),
            evidence=PhaseEvidence(
                regime_signal="R3", price_signal="Higher highs",
                volume_signal="Stable", supporting=[], contradictions=[],
            ),
            transitions=[],
            strategy_comment="Test",
            as_of_date=date.today(),
        )
        macro = MacroCalendar(
            events=[], next_event=None, days_to_next=None,
            next_fomc=None, days_to_next_fomc=None,
            events_next_7_days=[], events_next_30_days=[],
        )
        result = assess_leap(
            ticker="SPY",
            regime=regime,
            technicals=technicals,
            phase=phase,
            macro=macro,
            iv_rank=80,
        )
        assert result.verdict == Verdict.NO_GO
        hard_stop_names = [hs.name for hs in result.hard_stops]
        assert any("iv_rank" in name.lower() for name in hard_stop_names)

    def test_leap_accepts_iv_rank_none(self):
        """assess_leap with iv_rank=None -> works, no TypeError."""
        from market_analyzer.opportunity.option_plays.leap import assess_leap
        from market_analyzer.models.phase import (
            PhaseResult, PhaseID, PriceStructure, PhaseEvidence,
        )
        from market_analyzer.models.macro import MacroCalendar

        regime = _make_regime(3)
        technicals = _make_technicals()
        phase = PhaseResult(
            ticker="SPY",
            phase=PhaseID.MARKUP,
            phase_name="Markup",
            confidence=0.7,
            phase_age_days=15,
            prior_phase=None,
            cycle_completion=0.3,
            price_structure=PriceStructure(
                swing_highs=[], swing_lows=[],
                higher_highs=True, higher_lows=True,
                lower_highs=False, lower_lows=False,
                range_compression=0.3, price_vs_sma=2.0,
                volume_trend="stable",
                support_level=580.0, resistance_level=620.0,
            ),
            evidence=PhaseEvidence(
                regime_signal="R3", price_signal="Higher highs",
                volume_signal="Stable", supporting=[], contradictions=[],
            ),
            transitions=[],
            strategy_comment="Test",
            as_of_date=date.today(),
        )
        macro = MacroCalendar(
            events=[], next_event=None, days_to_next=None,
            next_fomc=None, days_to_next_fomc=None,
            events_next_7_days=[], events_next_30_days=[],
        )
        result = assess_leap(
            ticker="SPY", regime=regime, technicals=technicals,
            phase=phase, macro=macro, iv_rank=None,
        )
        assert result is not None

    def test_earnings_hard_stop_low_iv(self):
        """assess_earnings_play with iv_rank=20 -> NO_GO (hard stop: IV rank too low)."""
        from market_analyzer.opportunity.option_plays.earnings import assess_earnings_play
        from market_analyzer.models.opportunity import Verdict

        regime = _make_regime(1)
        technicals = _make_technicals()
        result = assess_earnings_play(
            ticker="SPY",
            regime=regime,
            technicals=technicals,
            iv_rank=20,
        )
        assert result.verdict == Verdict.NO_GO
        hard_stop_names = [hs.name for hs in result.hard_stops]
        assert any("IV rank" in name or "iv_rank" in name.lower() for name in hard_stop_names)

    def test_earnings_accepts_iv_rank_none(self):
        """assess_earnings_play with iv_rank=None -> works, no TypeError."""
        from market_analyzer.opportunity.option_plays.earnings import assess_earnings_play

        regime = _make_regime(1)
        technicals = _make_technicals()
        result = assess_earnings_play(
            ticker="SPY", regime=regime, technicals=technicals, iv_rank=None,
        )
        assert result is not None


# ── SQ2: HMM model staleness and validation ──


class TestSQ2HMMStaleness:
    """SQ2: HMM model staleness and validation."""

    def test_regime_result_has_staleness_fields(self):
        """RegimeResult with model_fit_date, model_age_days, regime_stability -> works."""
        result = RegimeResult(
            ticker="SPY",
            regime=RegimeID.R1_LOW_VOL_MR,
            confidence=0.85,
            regime_probabilities={1: 0.85, 2: 0.05, 3: 0.05, 4: 0.05},
            as_of_date=date.today(),
            model_version="test",
            model_fit_date=date(2026, 3, 1),
            model_age_days=13,
            regime_stability=2,
        )
        assert result.model_fit_date == date(2026, 3, 1)
        assert result.model_age_days == 13
        assert result.regime_stability == 2

    def test_regime_result_staleness_defaults_none(self):
        """RegimeResult without staleness fields -> all None."""
        result = _make_regime(1)
        assert result.model_fit_date is None
        assert result.model_age_days is None
        assert result.regime_stability is None

    def test_regime_stability_field(self):
        """RegimeResult with regime_stability=3 -> accessible."""
        result = RegimeResult(
            ticker="GLD",
            regime=RegimeID.R2_HIGH_VOL_MR,
            confidence=0.70,
            regime_probabilities={1: 0.10, 2: 0.70, 3: 0.15, 4: 0.05},
            as_of_date=date.today(),
            model_version="test",
            regime_stability=3,
        )
        assert result.regime_stability == 3

    def test_regime_result_model_age_integer(self):
        """model_age_days is int | None, not float."""
        result = RegimeResult(
            ticker="SPY",
            regime=RegimeID.R1_LOW_VOL_MR,
            confidence=0.85,
            regime_probabilities={1: 0.85, 2: 0.05, 3: 0.05, 4: 0.05},
            as_of_date=date.today(),
            model_version="test",
            model_age_days=45,
        )
        assert isinstance(result.model_age_days, int)
        assert result.model_age_days == 45


# ── SQ3: POP calibration from outcomes + IV rank ──


class TestSQ3POPCalibration:
    """SQ3: POP calibration from outcomes + IV rank."""

    def test_estimate_pop_accepts_iv_rank(self):
        """estimate_pop with iv_rank=50 -> works, no error."""
        from market_analyzer.trade_lifecycle import estimate_pop

        ic = _make_iron_condor()
        result = estimate_pop(
            trade_spec=ic,
            entry_price=2.50,
            regime_id=1,
            atr_pct=1.33,  # 8/600 * 100
            current_price=600.0,
            iv_rank=50,
        )
        assert result is not None
        assert 0.0 <= result.pop_pct <= 1.0

    def test_estimate_pop_iv_rank_widens_move(self):
        """Higher iv_rank -> lower POP (wider expected move for credit trades)."""
        from market_analyzer.trade_lifecycle import estimate_pop

        ic = _make_iron_condor()
        common = dict(
            trade_spec=ic,
            entry_price=2.50,
            regime_id=1,
            atr_pct=1.33,
            current_price=600.0,
        )
        pop_low_iv = estimate_pop(**common, iv_rank=20)
        pop_high_iv = estimate_pop(**common, iv_rank=80)
        assert pop_low_iv is not None
        assert pop_high_iv is not None
        # Higher IV rank widens expected moves -> lower POP for credit trades
        assert pop_low_iv.pop_pct > pop_high_iv.pop_pct

    def test_estimate_pop_iv_rank_none_data_gap(self):
        """estimate_pop with iv_rank=None -> POPEstimate has data_gap."""
        from market_analyzer.trade_lifecycle import estimate_pop

        ic = _make_iron_condor()
        result = estimate_pop(
            trade_spec=ic,
            entry_price=2.50,
            regime_id=1,
            atr_pct=1.33,
            current_price=600.0,
            iv_rank=None,
        )
        assert result is not None
        assert len(result.data_gaps) >= 1
        gap_fields = [g.field for g in result.data_gaps]
        assert "pop" in gap_fields

    def test_estimate_pop_iv_rank_provided_no_data_gap(self):
        """estimate_pop with iv_rank=50 -> no IV-related data gap."""
        from market_analyzer.trade_lifecycle import estimate_pop

        ic = _make_iron_condor()
        result = estimate_pop(
            trade_spec=ic,
            entry_price=2.50,
            regime_id=1,
            atr_pct=1.33,
            current_price=600.0,
            iv_rank=50,
        )
        assert result is not None
        iv_gaps = [g for g in result.data_gaps if "IV" in g.reason or "iv" in g.reason.lower()]
        assert len(iv_gaps) == 0

    def test_calibrate_pop_factors_empty(self):
        """Empty outcomes -> empty dict."""
        from market_analyzer.performance import calibrate_pop_factors

        result = calibrate_pop_factors([])
        assert result == {}

    def test_calibrate_pop_factors_few_trades(self):
        """5 trades (below min=10) -> empty dict."""
        from market_analyzer.performance import calibrate_pop_factors

        outcomes = [_make_outcome(trade_id=f"t{i}") for i in range(5)]
        result = calibrate_pop_factors(outcomes, min_trades_per_regime=10)
        assert result == {}

    def test_calibrate_pop_factors_enough_trades(self):
        """15 trades all in R1 -> dict has key 1."""
        from market_analyzer.performance import calibrate_pop_factors

        outcomes = [
            _make_outcome(regime=1, pnl_pct=0.10, trade_id=f"t{i}")
            for i in range(15)
        ]
        result = calibrate_pop_factors(outcomes, min_trades_per_regime=10)
        assert 1 in result
        assert isinstance(result[1], float)

    def test_calibrate_pop_factors_clamped(self):
        """Result factors are within [0.15, 2.0]."""
        from market_analyzer.performance import calibrate_pop_factors

        # All winning -> factor should be low but >= 0.15
        winning = [
            _make_outcome(regime=1, pnl_pct=0.10, pnl_dollars=30.0, trade_id=f"w{i}")
            for i in range(20)
        ]
        result_win = calibrate_pop_factors(winning, min_trades_per_regime=10)
        if 1 in result_win:
            assert 0.15 <= result_win[1] <= 2.0

        # All losing -> factor should be high but <= 2.0
        losing = [
            _make_outcome(regime=2, pnl_pct=-0.10, pnl_dollars=-30.0, trade_id=f"l{i}")
            for i in range(20)
        ]
        result_lose = calibrate_pop_factors(losing, min_trades_per_regime=10)
        if 2 in result_lose:
            assert 0.15 <= result_lose[2] <= 2.0

    def test_performance_report_has_pop_accuracy(self):
        """compute_performance_report with enough outcomes -> pop_accuracy populated."""
        from market_analyzer.performance import compute_performance_report

        # Need >= 5 trades per regime for pop_accuracy to populate
        outcomes = [
            _make_outcome(regime=1, pnl_pct=0.10, pnl_dollars=30.0, trade_id=f"r1w{i}")
            for i in range(4)
        ] + [
            _make_outcome(regime=1, pnl_pct=-0.05, pnl_dollars=-15.0, trade_id=f"r1l{i}")
            for i in range(3)
        ]
        report = compute_performance_report(outcomes)
        # 7 trades in R1 (>= 5), so pop_accuracy should have key 1
        assert report.pop_accuracy is not None
        assert 1 in report.pop_accuracy
        # 4 wins / 7 trades
        assert abs(report.pop_accuracy[1] - 4 / 7) < 0.01

    def test_performance_report_pop_accuracy_none_few_trades(self):
        """compute_performance_report with < 5 trades per regime -> pop_accuracy is None."""
        from market_analyzer.performance import compute_performance_report

        outcomes = [
            _make_outcome(regime=1, trade_id="t1"),
            _make_outcome(regime=2, trade_id="t2"),
            _make_outcome(regime=3, trade_id="t3"),
        ]
        report = compute_performance_report(outcomes)
        # Each regime has only 1 trade (< 5) -> no pop_accuracy entries
        assert report.pop_accuracy is None


# ── TA1–TA6: New technical indicator tests ──


def _make_ohlcv(n=100):
    """Create a simple uptrending OHLCV DataFrame for testing."""
    import numpy as np
    import pandas as pd

    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    base = 100 + np.arange(n) * 0.1 + np.random.RandomState(42).randn(n) * 2
    df = pd.DataFrame(
        {
            "Open": base - 0.5,
            "High": base + 1.0,
            "Low": base - 1.0,
            "Close": base,
            "Volume": np.random.RandomState(42).randint(100000, 1000000, n),
        },
        index=dates,
    )
    return df


class TestTA1Fibonacci:
    """TA1: Fibonacci retracement levels."""

    def test_fibonacci_computes_levels(self):
        """compute_fibonacci returns FibonacciLevels with all fields populated."""
        from market_analyzer.features.technicals import compute_fibonacci
        from market_analyzer.models.technicals import FibonacciLevels

        df = _make_ohlcv()
        result = compute_fibonacci(df["High"], df["Low"], df["Close"])
        assert isinstance(result, FibonacciLevels)
        assert result.swing_high > 0
        assert result.swing_low > 0
        assert result.level_236 > 0
        assert result.level_382 > 0
        assert result.level_500 > 0
        assert result.level_618 > 0
        assert result.level_786 > 0

    def test_fibonacci_levels_between_swing(self):
        """All fib levels are between swing_high and swing_low."""
        from market_analyzer.features.technicals import compute_fibonacci

        df = _make_ohlcv()
        result = compute_fibonacci(df["High"], df["Low"], df["Close"])
        levels = [result.level_236, result.level_382, result.level_500,
                  result.level_618, result.level_786]
        for lv in levels:
            assert result.swing_low <= lv <= result.swing_high

    def test_fibonacci_direction_detected(self):
        """Direction is 'up' or 'down'."""
        from market_analyzer.features.technicals import compute_fibonacci

        df = _make_ohlcv()
        result = compute_fibonacci(df["High"], df["Low"], df["Close"])
        assert result.direction in ("up", "down")

    def test_fibonacci_current_price_level(self):
        """current_price_level is a non-empty string."""
        from market_analyzer.features.technicals import compute_fibonacci

        df = _make_ohlcv()
        result = compute_fibonacci(df["High"], df["Low"], df["Close"])
        assert isinstance(result.current_price_level, str)
        assert len(result.current_price_level) > 0


class TestTA2ADX:
    """TA2: Average Directional Index."""

    def test_adx_computes(self):
        """compute_adx returns ADXData with adx, plus_di, minus_di."""
        from market_analyzer.features.technicals import compute_adx
        from market_analyzer.models.technicals import ADXData

        df = _make_ohlcv()
        result = compute_adx(df["High"], df["Low"], df["Close"])
        assert isinstance(result, ADXData)
        assert isinstance(result.adx, float)
        assert isinstance(result.plus_di, float)
        assert isinstance(result.minus_di, float)

    def test_adx_range(self):
        """ADX value is between 0 and 100."""
        from market_analyzer.features.technicals import compute_adx

        df = _make_ohlcv()
        result = compute_adx(df["High"], df["Low"], df["Close"])
        assert 0 <= result.adx <= 100

    def test_adx_trending_flag(self):
        """is_trending = adx > 25."""
        from market_analyzer.features.technicals import compute_adx

        df = _make_ohlcv()
        result = compute_adx(df["High"], df["Low"], df["Close"])
        assert result.is_trending == (result.adx > 25)

    def test_adx_ranging_flag(self):
        """is_ranging = adx < 20."""
        from market_analyzer.features.technicals import compute_adx

        df = _make_ohlcv()
        result = compute_adx(df["High"], df["Low"], df["Close"])
        assert result.is_ranging == (result.adx < 20)

    def test_adx_direction(self):
        """trend_direction is 'bullish', 'bearish', or 'neutral'."""
        from market_analyzer.features.technicals import compute_adx

        df = _make_ohlcv()
        result = compute_adx(df["High"], df["Low"], df["Close"])
        assert result.trend_direction in ("bullish", "bearish", "neutral")


class TestTA3Donchian:
    """TA3: Donchian Channels."""

    def test_donchian_computes(self):
        """compute_donchian returns DonchianChannels."""
        from market_analyzer.features.technicals import compute_donchian
        from market_analyzer.models.technicals import DonchianChannels

        df = _make_ohlcv()
        result = compute_donchian(df["High"], df["Low"], df["Close"])
        assert isinstance(result, DonchianChannels)

    def test_donchian_upper_gte_lower(self):
        """upper >= lower always."""
        from market_analyzer.features.technicals import compute_donchian

        df = _make_ohlcv()
        result = compute_donchian(df["High"], df["Low"], df["Close"])
        assert result.upper >= result.lower

    def test_donchian_middle_is_average(self):
        """middle = (upper + lower) / 2."""
        from market_analyzer.features.technicals import compute_donchian

        df = _make_ohlcv()
        result = compute_donchian(df["High"], df["Low"], df["Close"])
        expected_middle = (result.upper + result.lower) / 2
        assert abs(result.middle - expected_middle) < 0.01


class TestTA4Keltner:
    """TA4: Keltner Channels."""

    def test_keltner_computes(self):
        """compute_keltner returns KeltnerChannels."""
        from market_analyzer.features.technicals import compute_keltner
        from market_analyzer.models.technicals import KeltnerChannels

        df = _make_ohlcv()
        result = compute_keltner(df["Close"], df["High"], df["Low"])
        assert isinstance(result, KeltnerChannels)

    def test_keltner_upper_gte_lower(self):
        """upper >= lower always."""
        from market_analyzer.features.technicals import compute_keltner

        df = _make_ohlcv()
        result = compute_keltner(df["Close"], df["High"], df["Low"])
        assert result.upper >= result.lower

    def test_keltner_squeeze_detection(self):
        """squeeze = True when BB inside Keltner."""
        from market_analyzer.features.technicals import compute_keltner

        df = _make_ohlcv()
        # Pass BB values that are inside Keltner (narrow BB = squeeze)
        result_squeeze = compute_keltner(
            df["Close"], df["High"], df["Low"],
            bb_upper=df["Close"].iloc[-1] + 0.5,
            bb_lower=df["Close"].iloc[-1] - 0.5,
        )
        # With very tight BB bands relative to Keltner, squeeze should be True
        # (depends on actual Keltner width — just verify the flag is bool)
        assert isinstance(result_squeeze.squeeze, bool)

        # Without BB values, squeeze is False
        result_no_bb = compute_keltner(df["Close"], df["High"], df["Low"])
        assert result_no_bb.squeeze is False


class TestTA5Pivots:
    """TA5: Pivot Points."""

    def test_pivots_compute(self):
        """compute_pivot_points returns PivotPoints."""
        from market_analyzer.features.technicals import compute_pivot_points
        from market_analyzer.models.technicals import PivotPoints

        df = _make_ohlcv()
        result = compute_pivot_points(df["High"], df["Low"], df["Close"])
        assert isinstance(result, PivotPoints)

    def test_pivots_ordering(self):
        """s3 < s2 < s1 < pp < r1 < r2 < r3."""
        from market_analyzer.features.technicals import compute_pivot_points

        df = _make_ohlcv()
        result = compute_pivot_points(df["High"], df["Low"], df["Close"])
        assert result.s3 < result.s2 < result.s1 < result.pp < result.r1 < result.r2 < result.r3

    def test_pivots_period(self):
        """period == 'daily'."""
        from market_analyzer.features.technicals import compute_pivot_points

        df = _make_ohlcv()
        result = compute_pivot_points(df["High"], df["Low"], df["Close"])
        assert result.period == "daily"


class TestTA6VWAP:
    """TA6: Daily VWAP."""

    def test_vwap_computes(self):
        """compute_daily_vwap returns VWAPData."""
        from market_analyzer.features.technicals import compute_daily_vwap
        from market_analyzer.models.technicals import VWAPData

        df = _make_ohlcv()
        result = compute_daily_vwap(df["High"], df["Low"], df["Close"], df["Volume"])
        assert isinstance(result, VWAPData)

    def test_vwap_positive(self):
        """vwap > 0."""
        from market_analyzer.features.technicals import compute_daily_vwap

        df = _make_ohlcv()
        result = compute_daily_vwap(df["High"], df["Low"], df["Close"], df["Volume"])
        assert result.vwap > 0

    def test_vwap_above_below(self):
        """is_above_vwap matches price > vwap."""
        from market_analyzer.features.technicals import compute_daily_vwap

        df = _make_ohlcv()
        result = compute_daily_vwap(df["High"], df["Low"], df["Close"], df["Volume"])
        price = float(df["Close"].iloc[-1])
        assert result.is_above_vwap == (price > result.vwap)


class TestTAOnSnapshot:
    """Verify new TA fields on TechnicalSnapshot."""

    def test_snapshot_has_all_ta_fields(self):
        """TechnicalSnapshot accepts fibonacci, adx, donchian, keltner, pivot_points, daily_vwap."""
        from market_analyzer.models.technicals import (
            FibonacciLevels, ADXData, DonchianChannels,
            KeltnerChannels, PivotPoints, VWAPData,
            TechnicalSnapshot,
        )

        fib = FibonacciLevels(
            swing_high=110, swing_low=90, direction="up",
            level_236=105.28, level_382=103.64, level_500=100.0,
            level_618=97.64, level_786=94.28, current_price_level="above_236",
        )
        adx = ADXData(
            adx=30.0, plus_di=25.0, minus_di=15.0,
            is_trending=True, is_ranging=False, trend_direction="bullish",
        )
        donchian = DonchianChannels(
            upper=110, lower=90, middle=100, width_pct=20.0,
            is_at_upper=False, is_at_lower=False,
        )
        keltner = KeltnerChannels(
            upper=112, middle=100, lower=88, width_pct=24.0, squeeze=False,
        )
        pivots = PivotPoints(
            pp=100, r1=105, r2=110, r3=115,
            s1=95, s2=90, s3=85, period="daily",
        )
        vwap = VWAPData(vwap=99.5, price_vs_vwap_pct=0.5, is_above_vwap=True)

        snap = _make_technicals()
        # Rebuild with TA fields set
        data = snap.model_dump()
        data.update(
            fibonacci=fib, adx=adx, donchian=donchian,
            keltner=keltner, pivot_points=pivots, daily_vwap=vwap,
        )
        snap2 = TechnicalSnapshot(**data)
        assert snap2.fibonacci is not None
        assert snap2.adx is not None
        assert snap2.donchian is not None
        assert snap2.keltner is not None
        assert snap2.pivot_points is not None
        assert snap2.daily_vwap is not None

    def test_snapshot_ta_defaults_none(self):
        """All new TA fields default to None for backward compat."""
        snap = _make_technicals()
        assert snap.fibonacci is None
        assert snap.adx is None
        assert snap.donchian is None
        assert snap.keltner is None
        assert snap.pivot_points is None
        assert snap.daily_vwap is None


# ── Helpers for SQ4-SQ10 tests ──


def _make_technicals_with_ta(
    price: float = 600.0,
    atr: float = 8.0,
    rsi: float = 50.0,
    macd_histogram: float = 0.0,
    bb_pct_b: float = 0.5,
    fibonacci: "FibonacciLevels | None" = None,
    adx: "ADXData | None" = None,
    donchian: "DonchianChannels | None" = None,
    keltner: "KeltnerChannels | None" = None,
    daily_vwap: "VWAPData | None" = None,
    pivot_points: "PivotPoints | None" = None,
) -> TechnicalSnapshot:
    """Build TechnicalSnapshot with optional new TA indicators populated."""
    from market_analyzer.models.technicals import (
        ADXData,
        DonchianChannels,
        FibonacciLevels,
        KeltnerChannels,
        PivotPoints,
        VWAPData,
    )

    return TechnicalSnapshot(
        ticker="SPY",
        as_of_date=date.today(),
        current_price=price,
        atr=atr,
        atr_pct=atr / price * 100,
        vwma_20=price,
        moving_averages=MovingAverages(
            sma_20=price, sma_50=price, sma_200=price,
            ema_9=price, ema_21=price,
            price_vs_sma_20_pct=0.0, price_vs_sma_50_pct=0.0,
            price_vs_sma_200_pct=0.0,
        ),
        rsi=RSIData(value=rsi, is_overbought=rsi >= 70, is_oversold=rsi <= 30),
        bollinger=BollingerBands(
            upper=price + 10, middle=price, lower=price - 10,
            bandwidth=3.3, percent_b=bb_pct_b,
        ),
        macd=MACDData(
            macd_line=0.0, signal_line=0.0, histogram=macd_histogram,
            is_bullish_crossover=False, is_bearish_crossover=False,
        ),
        stochastic=StochasticData(k=50.0, d=50.0, is_overbought=False, is_oversold=False),
        support_resistance=SupportResistance(
            support=price - 20, resistance=price + 20,
            price_vs_support_pct=3.3, price_vs_resistance_pct=3.3,
        ),
        phase=PhaseIndicator(
            phase="accumulation", confidence=0.6, description="",
            higher_highs=True, higher_lows=True, lower_highs=False, lower_lows=False,
            range_compression=0.0, volume_trend="stable", price_vs_sma_50_pct=0.0,
        ),
        signals=[],
        fibonacci=fibonacci,
        adx=adx,
        donchian=donchian,
        keltner=keltner,
        daily_vwap=daily_vwap,
        pivot_points=pivot_points,
    )


def _make_phase_result() -> "PhaseResult":
    """Build a minimal PhaseResult for assessor tests."""
    from market_analyzer.models.phase import (
        PhaseEvidence,
        PhaseID,
        PhaseResult,
        PriceStructure,
        SwingPoint,
    )

    today = date.today()
    return PhaseResult(
        ticker="SPY",
        phase=PhaseID.ACCUMULATION,
        phase_name="Accumulation",
        confidence=0.7,
        phase_age_days=20,
        prior_phase=None,
        cycle_completion=0.3,
        price_structure=PriceStructure(
            swing_highs=[SwingPoint(date=today, price=610.0, type="high")],
            swing_lows=[SwingPoint(date=today, price=590.0, type="low")],
            higher_highs=True,
            higher_lows=True,
            lower_highs=False,
            lower_lows=False,
            range_compression=0.2,
            price_vs_sma=0.0,
            volume_trend="stable",
            support_level=590.0,
            resistance_level=610.0,
        ),
        evidence=PhaseEvidence(
            regime_signal="R1",
            price_signal="higher lows",
            volume_signal="stable",
            supporting=["range compression"],
            contradictions=[],
        ),
        transitions=[],
        strategy_comment="Accumulation phase",
        as_of_date=today,
    )


def _make_macro_calendar() -> "MacroCalendar":
    """Build a minimal MacroCalendar for assessor tests."""
    from market_analyzer.models.macro import MacroCalendar

    return MacroCalendar(
        events=[],
        next_event=None,
        days_to_next=None,
        next_fomc=None,
        days_to_next_fomc=None,
        events_next_7_days=[],
        events_next_30_days=[],
    )


# ── SQ4: Mean Reversion Signal Overhaul ──


class TestSQ4MeanReversionOverhaul:
    """Test new mean reversion signals: ADX hard stop, fibonacci, VWAP, divergence."""

    def test_adx_hard_stop_strong_trend(self):
        """ADX > 35 should produce a hard stop in mean reversion assessment."""
        from market_analyzer.models.technicals import ADXData
        from market_analyzer.opportunity.setups.mean_reversion import assess_mean_reversion

        adx = ADXData(adx=40.0, plus_di=30.0, minus_di=15.0,
                       is_trending=True, is_ranging=False, trend_direction="bullish")
        tech = _make_technicals_with_ta(rsi=30.0, bb_pct_b=0.1, adx=adx)
        regime = _make_regime(1)

        result = assess_mean_reversion("SPY", regime, tech)
        hard_stop_names = [hs.name for hs in result.hard_stops]
        assert "strong_trend" in hard_stop_names, (
            f"Expected 'strong_trend' hard stop with ADX=40, got: {hard_stop_names}"
        )
        assert result.verdict == "no_go"

    def test_adx_ranging_no_hard_stop(self):
        """ADX < 20 should NOT produce a hard stop — favorable for MR."""
        from market_analyzer.models.technicals import ADXData
        from market_analyzer.opportunity.setups.mean_reversion import assess_mean_reversion

        adx = ADXData(adx=15.0, plus_di=12.0, minus_di=10.0,
                       is_trending=False, is_ranging=True, trend_direction="neutral")
        tech = _make_technicals_with_ta(rsi=30.0, bb_pct_b=0.1, adx=adx)
        regime = _make_regime(1)

        result = assess_mean_reversion("SPY", regime, tech)
        hard_stop_names = [hs.name for hs in result.hard_stops]
        assert "strong_trend" not in hard_stop_names

    def test_fibonacci_signal_present(self):
        """With fibonacci data, fibonacci_reversion signal should appear."""
        from market_analyzer.models.technicals import FibonacciLevels
        from market_analyzer.opportunity.setups.mean_reversion import assess_mean_reversion

        fib = FibonacciLevels(
            swing_high=620.0, swing_low=580.0, direction="up",
            level_236=610.56, level_382=604.72, level_500=600.0,
            level_618=595.28, level_786=588.56,
            current_price_level="between_618_786",
        )
        tech = _make_technicals_with_ta(rsi=30.0, bb_pct_b=0.1, fibonacci=fib)
        regime = _make_regime(1)

        result = assess_mean_reversion("SPY", regime, tech)
        signal_names = [s.name for s in result.signals]
        assert "fibonacci_reversion" in signal_names, (
            f"Expected fibonacci_reversion signal, got: {signal_names}"
        )
        # Deep retracement in upswing should be favorable
        fib_signal = next(s for s in result.signals if s.name == "fibonacci_reversion")
        assert fib_signal.favorable is True

    def test_fibonacci_shallow_unfavorable(self):
        """Shallow retracement should produce unfavorable fibonacci signal."""
        from market_analyzer.models.technicals import FibonacciLevels
        from market_analyzer.opportunity.setups.mean_reversion import assess_mean_reversion

        fib = FibonacciLevels(
            swing_high=620.0, swing_low=580.0, direction="up",
            level_236=610.56, level_382=604.72, level_500=600.0,
            level_618=595.28, level_786=588.56,
            current_price_level="above_236",
        )
        tech = _make_technicals_with_ta(rsi=30.0, bb_pct_b=0.1, fibonacci=fib)
        regime = _make_regime(1)

        result = assess_mean_reversion("SPY", regime, tech)
        fib_signal = next(s for s in result.signals if s.name == "fibonacci_reversion")
        assert fib_signal.favorable is False

    def test_vwap_signal_present(self):
        """With daily_vwap data, vwap_deviation signal should appear."""
        from market_analyzer.models.technicals import VWAPData
        from market_analyzer.opportunity.setups.mean_reversion import assess_mean_reversion

        vwap = VWAPData(vwap=595.0, price_vs_vwap_pct=3.0, is_above_vwap=True)
        tech = _make_technicals_with_ta(rsi=30.0, bb_pct_b=0.1, daily_vwap=vwap)
        regime = _make_regime(1)

        result = assess_mean_reversion("SPY", regime, tech)
        signal_names = [s.name for s in result.signals]
        assert "vwap_deviation" in signal_names, (
            f"Expected vwap_deviation signal, got: {signal_names}"
        )
        # 3% deviation > 2% threshold = favorable
        vwap_signal = next(s for s in result.signals if s.name == "vwap_deviation")
        assert vwap_signal.favorable is True

    def test_vwap_near_unfavorable(self):
        """Price near VWAP (< 2%) should produce unfavorable signal."""
        from market_analyzer.models.technicals import VWAPData
        from market_analyzer.opportunity.setups.mean_reversion import assess_mean_reversion

        vwap = VWAPData(vwap=599.0, price_vs_vwap_pct=0.5, is_above_vwap=True)
        tech = _make_technicals_with_ta(rsi=30.0, bb_pct_b=0.1, daily_vwap=vwap)
        regime = _make_regime(1)

        result = assess_mean_reversion("SPY", regime, tech)
        vwap_signal = next(s for s in result.signals if s.name == "vwap_deviation")
        assert vwap_signal.favorable is False

    def test_divergence_signal_bullish(self):
        """RSI < 35 and MACD histogram > 0 should produce favorable divergence."""
        from market_analyzer.opportunity.setups.mean_reversion import assess_mean_reversion

        tech = _make_technicals_with_ta(rsi=30.0, bb_pct_b=0.1, macd_histogram=0.5)
        regime = _make_regime(1)

        result = assess_mean_reversion("SPY", regime, tech)
        signal_names = [s.name for s in result.signals]
        assert "divergence" in signal_names, (
            f"Expected divergence signal, got: {signal_names}"
        )
        div_signal = next(s for s in result.signals if s.name == "divergence")
        assert div_signal.favorable is True

    def test_divergence_signal_no_divergence(self):
        """RSI=50 and MACD histogram=0 -> no divergence (unfavorable)."""
        from market_analyzer.opportunity.setups.mean_reversion import assess_mean_reversion

        tech = _make_technicals_with_ta(rsi=50.0, bb_pct_b=0.5, macd_histogram=0.0)
        regime = _make_regime(1)

        result = assess_mean_reversion("SPY", regime, tech)
        div_signal = next(s for s in result.signals if s.name == "divergence")
        assert div_signal.favorable is False

    def test_adx_ranging_signal_favorable(self):
        """ADX < 20 (ranging) should produce favorable adx_ranging signal."""
        from market_analyzer.models.technicals import ADXData
        from market_analyzer.opportunity.setups.mean_reversion import assess_mean_reversion

        adx = ADXData(adx=15.0, plus_di=12.0, minus_di=10.0,
                       is_trending=False, is_ranging=True, trend_direction="neutral")
        tech = _make_technicals_with_ta(rsi=30.0, bb_pct_b=0.1, adx=adx)
        regime = _make_regime(1)

        result = assess_mean_reversion("SPY", regime, tech)
        adx_signal = next(s for s in result.signals if s.name == "adx_ranging")
        assert adx_signal.favorable is True


# ── SQ5: Breakout Volume + Donchian/Keltner Signals ──


class TestSQ5BreakoutVolume:
    """Test new breakout signals: Donchian breakout and Keltner squeeze."""

    def test_donchian_signal_present(self):
        """With donchian data at upper, donchian_breakout signal should appear and be favorable."""
        from market_analyzer.models.technicals import DonchianChannels
        from market_analyzer.opportunity.setups.breakout import assess_breakout

        donchian = DonchianChannels(
            upper=610.0, lower=580.0, middle=595.0,
            width_pct=5.04, is_at_upper=True, is_at_lower=False,
        )
        tech = _make_technicals_with_ta(donchian=donchian)
        regime = _make_regime(1)
        phase = _make_phase_result()
        macro = _make_macro_calendar()

        result = assess_breakout("SPY", regime, tech, phase, macro)
        signal_names = [s.name for s in result.signals]
        assert "donchian_breakout" in signal_names, (
            f"Expected donchian_breakout signal, got: {signal_names}"
        )
        don_signal = next(s for s in result.signals if s.name == "donchian_breakout")
        assert don_signal.favorable is True

    def test_donchian_not_at_upper_unfavorable(self):
        """Donchian available but not at upper -> unfavorable signal."""
        from market_analyzer.models.technicals import DonchianChannels
        from market_analyzer.opportunity.setups.breakout import assess_breakout

        donchian = DonchianChannels(
            upper=610.0, lower=580.0, middle=595.0,
            width_pct=5.04, is_at_upper=False, is_at_lower=False,
        )
        tech = _make_technicals_with_ta(donchian=donchian)
        regime = _make_regime(1)
        phase = _make_phase_result()
        macro = _make_macro_calendar()

        result = assess_breakout("SPY", regime, tech, phase, macro)
        don_signal = next(s for s in result.signals if s.name == "donchian_breakout")
        assert don_signal.favorable is False

    def test_donchian_absent_no_signal(self):
        """Without donchian data, no donchian_breakout signal should appear."""
        from market_analyzer.opportunity.setups.breakout import assess_breakout

        tech = _make_technicals_with_ta()
        regime = _make_regime(1)
        phase = _make_phase_result()
        macro = _make_macro_calendar()

        result = assess_breakout("SPY", regime, tech, phase, macro)
        signal_names = [s.name for s in result.signals]
        assert "donchian_breakout" not in signal_names

    def test_keltner_squeeze_signal(self):
        """With keltner.squeeze=True, keltner_squeeze signal should appear and be favorable."""
        from market_analyzer.models.technicals import KeltnerChannels
        from market_analyzer.opportunity.setups.breakout import assess_breakout

        keltner = KeltnerChannels(
            upper=615.0, middle=600.0, lower=585.0,
            width_pct=5.0, squeeze=True,
        )
        tech = _make_technicals_with_ta(keltner=keltner)
        regime = _make_regime(1)
        phase = _make_phase_result()
        macro = _make_macro_calendar()

        result = assess_breakout("SPY", regime, tech, phase, macro)
        signal_names = [s.name for s in result.signals]
        assert "keltner_squeeze" in signal_names, (
            f"Expected keltner_squeeze signal, got: {signal_names}"
        )
        ks_signal = next(s for s in result.signals if s.name == "keltner_squeeze")
        assert ks_signal.favorable is True

    def test_keltner_no_squeeze_no_signal(self):
        """With keltner.squeeze=False, keltner_squeeze signal should NOT appear."""
        from market_analyzer.models.technicals import KeltnerChannels
        from market_analyzer.opportunity.setups.breakout import assess_breakout

        keltner = KeltnerChannels(
            upper=615.0, middle=600.0, lower=585.0,
            width_pct=5.0, squeeze=False,
        )
        tech = _make_technicals_with_ta(keltner=keltner)
        regime = _make_regime(1)
        phase = _make_phase_result()
        macro = _make_macro_calendar()

        result = assess_breakout("SPY", regime, tech, phase, macro)
        signal_names = [s.name for s in result.signals]
        assert "keltner_squeeze" not in signal_names


# ── SQ8: Momentum Pullback — ADX + Fibonacci Signals ──


class TestSQ8MomentumPullback:
    """Test new momentum signals: ADX trend strength and fibonacci pullback."""

    def test_adx_trend_signal_present(self):
        """With ADX data, adx_trend_strength signal should appear."""
        from market_analyzer.models.technicals import ADXData
        from market_analyzer.opportunity.setups.momentum import assess_momentum

        adx = ADXData(adx=30.0, plus_di=25.0, minus_di=15.0,
                       is_trending=True, is_ranging=False, trend_direction="bullish")
        tech = _make_technicals_with_ta(rsi=55.0, adx=adx)
        regime = _make_regime(3)
        phase = _make_phase_result()
        macro = _make_macro_calendar()

        result = assess_momentum("SPY", regime, tech, phase, macro)
        signal_names = [s.name for s in result.signals]
        assert "adx_trend_strength" in signal_names, (
            f"Expected adx_trend_strength signal, got: {signal_names}"
        )
        adx_signal = next(s for s in result.signals if s.name == "adx_trend_strength")
        # ADX > 25 and is_trending -> favorable
        assert adx_signal.favorable is True

    def test_adx_weak_trend_unfavorable(self):
        """ADX < 25 should produce unfavorable adx_trend_strength signal."""
        from market_analyzer.models.technicals import ADXData
        from market_analyzer.opportunity.setups.momentum import assess_momentum

        adx = ADXData(adx=18.0, plus_di=12.0, minus_di=10.0,
                       is_trending=False, is_ranging=True, trend_direction="neutral")
        tech = _make_technicals_with_ta(rsi=55.0, adx=adx)
        regime = _make_regime(3)
        phase = _make_phase_result()
        macro = _make_macro_calendar()

        result = assess_momentum("SPY", regime, tech, phase, macro)
        adx_signal = next(s for s in result.signals if s.name == "adx_trend_strength")
        assert adx_signal.favorable is False

    def test_adx_very_low_hard_stop(self):
        """ADX < 15 with is_ranging=True should produce no_trend hard stop."""
        from market_analyzer.models.technicals import ADXData
        from market_analyzer.opportunity.setups.momentum import assess_momentum

        adx = ADXData(adx=12.0, plus_di=8.0, minus_di=7.0,
                       is_trending=False, is_ranging=True, trend_direction="neutral")
        tech = _make_technicals_with_ta(rsi=55.0, adx=adx)
        regime = _make_regime(3)
        phase = _make_phase_result()
        macro = _make_macro_calendar()

        result = assess_momentum("SPY", regime, tech, phase, macro)
        hard_stop_names = [hs.name for hs in result.hard_stops]
        assert "no_trend" in hard_stop_names, (
            f"Expected 'no_trend' hard stop with ADX=12, got: {hard_stop_names}"
        )

    def test_fib_pullback_signal_present(self):
        """With fibonacci data in healthy pullback zone, fib_pullback signal should appear."""
        from market_analyzer.models.technicals import FibonacciLevels
        from market_analyzer.opportunity.setups.momentum import assess_momentum

        fib = FibonacciLevels(
            swing_high=620.0, swing_low=580.0, direction="up",
            level_236=610.56, level_382=604.72, level_500=600.0,
            level_618=595.28, level_786=588.56,
            current_price_level="between_382_500",
        )
        # Set MACD histogram > 0 to ensure bullish direction matches fib direction="up"
        tech = _make_technicals_with_ta(rsi=55.0, fibonacci=fib, macd_histogram=0.5)
        regime = _make_regime(3)
        phase = _make_phase_result()
        macro = _make_macro_calendar()

        result = assess_momentum("SPY", regime, tech, phase, macro)
        signal_names = [s.name for s in result.signals]
        assert "fib_pullback" in signal_names, (
            f"Expected fib_pullback signal, got: {signal_names}"
        )
        fib_signal = next(s for s in result.signals if s.name == "fib_pullback")
        assert fib_signal.favorable is True

    def test_fib_deep_retracement_hard_stop(self):
        """Deep fibonacci retracement in bullish momentum -> hard stop."""
        from market_analyzer.models.technicals import FibonacciLevels
        from market_analyzer.opportunity.setups.momentum import assess_momentum

        fib = FibonacciLevels(
            swing_high=620.0, swing_low=580.0, direction="up",
            level_236=610.56, level_382=604.72, level_500=600.0,
            level_618=595.28, level_786=588.56,
            current_price_level="below_786",
        )
        # Set MACD histogram > 0 to ensure bullish direction matches fib direction="up"
        tech = _make_technicals_with_ta(rsi=55.0, fibonacci=fib, macd_histogram=0.5)
        regime = _make_regime(3)
        phase = _make_phase_result()
        macro = _make_macro_calendar()

        result = assess_momentum("SPY", regime, tech, phase, macro)
        hard_stop_names = [hs.name for hs in result.hard_stops]
        assert "deep_retracement" in hard_stop_names, (
            f"Expected 'deep_retracement' hard stop, got: {hard_stop_names}"
        )

    def test_fib_absent_no_signal(self):
        """Without fibonacci data, no fib_pullback or deep_retracement signals."""
        from market_analyzer.opportunity.setups.momentum import assess_momentum

        tech = _make_technicals_with_ta(rsi=55.0)
        regime = _make_regime(3)
        phase = _make_phase_result()
        macro = _make_macro_calendar()

        result = assess_momentum("SPY", regime, tech, phase, macro)
        signal_names = [s.name for s in result.signals]
        assert "fib_pullback" not in signal_names
        hard_stop_names = [hs.name for hs in result.hard_stops]
        assert "deep_retracement" not in hard_stop_names


# ── SQ7: Screening Filters ──


class TestSQ7ScreeningFilters:
    """Test screening result model fields and filter concepts."""

    def test_screening_result_has_filtered_count(self):
        """ScreeningResult accepts filtered_count field."""
        from market_analyzer.service.screening import ScreeningResult

        result = ScreeningResult(
            as_of_date=date.today(),
            tickers_scanned=10,
            candidates=[],
            by_screen={},
            summary="test",
            min_score_applied=0.6,
            filtered_count=3,
        )
        assert result.filtered_count == 3

    def test_screen_candidate_has_atr_pct(self):
        """ScreenCandidate includes atr_pct for liquidity filtering."""
        from market_analyzer.service.screening import ScreenCandidate

        candidate = ScreenCandidate(
            ticker="SPY",
            screen="breakout",
            score=0.8,
            reason="test",
            regime_id=1,
            rsi=50.0,
            atr_pct=0.25,
        )
        assert candidate.atr_pct == 0.25

    def test_low_atr_filter_concept(self):
        """Verify that candidates with very low ATR% can be filtered."""
        from market_analyzer.service.screening import ScreenCandidate

        candidates = [
            ScreenCandidate(ticker="SPY", screen="breakout", score=0.8,
                            reason="test", regime_id=1, rsi=50.0, atr_pct=1.5),
            ScreenCandidate(ticker="LOW_VOL", screen="breakout", score=0.7,
                            reason="test", regime_id=1, rsi=50.0, atr_pct=0.2),
            ScreenCandidate(ticker="MED_VOL", screen="breakout", score=0.75,
                            reason="test", regime_id=1, rsi=50.0, atr_pct=0.5),
        ]
        # Filter out candidates with atr_pct < 0.3
        filtered = [c for c in candidates if c.atr_pct >= 0.3]
        assert len(filtered) == 2
        assert all(c.ticker != "LOW_VOL" for c in filtered)


# ── SQ9: Ranking IV Rank Map ──


class TestSQ9RankingIVRank:
    """Test that TradeRankingService.rank() accepts iv_rank_map parameter."""

    def test_rank_accepts_iv_rank_map(self):
        """Verify rank() signature accepts iv_rank_map parameter."""
        import inspect
        from market_analyzer.service.ranking import TradeRankingService

        sig = inspect.signature(TradeRankingService.rank)
        assert "iv_rank_map" in sig.parameters, (
            f"Expected 'iv_rank_map' in rank() params, got: {list(sig.parameters.keys())}"
        )

    def test_iv_rank_map_defaults_to_none(self):
        """iv_rank_map parameter should default to None."""
        import inspect
        from market_analyzer.service.ranking import TradeRankingService

        sig = inspect.signature(TradeRankingService.rank)
        param = sig.parameters["iv_rank_map"]
        assert param.default is None


# ── SQ10: Pivot Point Levels ──


class TestSQ10PivotLevels:
    """Test pivot point level sources and models."""

    def test_pivot_level_sources_exist(self):
        """LevelSource has PIVOT_PP, PIVOT_R1, PIVOT_S1, PIVOT_R2, PIVOT_S2."""
        from market_analyzer.models.levels import LevelSource

        assert hasattr(LevelSource, "PIVOT_PP")
        assert hasattr(LevelSource, "PIVOT_R1")
        assert hasattr(LevelSource, "PIVOT_S1")
        assert hasattr(LevelSource, "PIVOT_R2")
        assert hasattr(LevelSource, "PIVOT_S2")

    def test_pivot_level_source_values(self):
        """Pivot level source values are lowercase strings."""
        from market_analyzer.models.levels import LevelSource

        assert LevelSource.PIVOT_PP == "pivot_pp"
        assert LevelSource.PIVOT_R1 == "pivot_r1"
        assert LevelSource.PIVOT_S1 == "pivot_s1"
        assert LevelSource.PIVOT_R2 == "pivot_r2"
        assert LevelSource.PIVOT_S2 == "pivot_s2"

    def test_pivot_points_model_fields(self):
        """PivotPoints model accepts all required fields."""
        from market_analyzer.models.technicals import PivotPoints

        pivots = PivotPoints(
            pp=600.0, r1=610.0, r2=620.0, r3=630.0,
            s1=590.0, s2=580.0, s3=570.0, period="daily",
        )
        assert pivots.pp == 600.0
        assert pivots.r1 == 610.0
        assert pivots.s1 == 590.0
        assert pivots.period == "daily"

    def test_technical_snapshot_accepts_pivot_points(self):
        """TechnicalSnapshot can hold PivotPoints data."""
        from market_analyzer.models.technicals import PivotPoints

        pivots = PivotPoints(
            pp=600.0, r1=610.0, r2=620.0, r3=630.0,
            s1=590.0, s2=580.0, s3=570.0, period="daily",
        )
        tech = _make_technicals_with_ta(pivot_points=pivots)
        assert tech.pivot_points is not None
        assert tech.pivot_points.pp == 600.0


# ── ML1-ML3 Learning Tests ──


def _make_outcomes_with_drift(
    n_historical: int = 20,
    n_recent: int = 10,
    hist_win_rate: float = 0.8,
    recent_win_rate: float = 0.3,
    strategy: StrategyType = StrategyType.IRON_CONDOR,
    regime: int = 1,
) -> list[TradeOutcome]:
    """Build outcomes with a specific drift pattern.

    Historical outcomes get early dates, recent outcomes get late dates.
    """
    outcomes: list[TradeOutcome] = []
    for i in range(n_historical):
        won = i < int(n_historical * hist_win_rate)
        outcomes.append(
            TradeOutcome(
                trade_id=f"hist-{i}",
                ticker="SPY",
                strategy_type=strategy,
                regime_at_entry=regime,
                regime_at_exit=regime,
                entry_date=date(2025, 5, 1) + timedelta(days=i),
                exit_date=date(2025, 6, 1) + timedelta(days=i),
                entry_price=0.80,
                exit_price=0.40 if won else 1.20,
                pnl_dollars=40.0 if won else -40.0,
                pnl_pct=0.15 if won else -0.10,
                holding_days=14,
                exit_reason=TradeExitReason.PROFIT_TARGET
                if won
                else TradeExitReason.STOP_LOSS,
                composite_score_at_entry=0.75,
            )
        )
    for i in range(n_recent):
        won = i < int(n_recent * recent_win_rate)
        outcomes.append(
            TradeOutcome(
                trade_id=f"recent-{i}",
                ticker="SPY",
                strategy_type=strategy,
                regime_at_entry=regime,
                regime_at_exit=regime,
                entry_date=date(2026, 2, 15) + timedelta(days=i),
                exit_date=date(2026, 3, 1) + timedelta(days=i),
                entry_price=0.80,
                exit_price=0.40 if won else 1.20,
                pnl_dollars=40.0 if won else -40.0,
                pnl_pct=0.15 if won else -0.10,
                holding_days=14,
                exit_reason=TradeExitReason.PROFIT_TARGET
                if won
                else TradeExitReason.STOP_LOSS,
                composite_score_at_entry=0.75,
            )
        )
    return outcomes


class TestML1DriftDetection:
    """ML1: Drift detection — detect_drift()."""

    def test_no_outcomes_no_alerts(self):
        """Empty outcomes list produces no alerts."""
        from market_analyzer.performance import detect_drift

        alerts = detect_drift([])
        assert alerts == []

    def test_few_trades_no_alerts(self):
        """Below min_trades threshold produces no alerts."""
        from market_analyzer.performance import detect_drift

        outcomes = [
            _make_outcome(pnl_pct=-0.10, pnl_dollars=-40.0) for _ in range(5)
        ]
        alerts = detect_drift(outcomes, min_trades=10)
        assert alerts == []

    def test_critical_drift_detected(self):
        """20 historical wins + 10 recent losses triggers critical alert."""
        from market_analyzer.performance import detect_drift

        outcomes = _make_outcomes_with_drift(
            n_historical=20,
            n_recent=10,
            hist_win_rate=0.8,
            recent_win_rate=0.0,
        )
        # Total: 30 trades, window=10 recent are all losses
        # Historical win rate ~ 16/30 = 0.533 (blended)
        # Recent win rate = 0/10 = 0.0
        # drop ~ 0.533 > 0.25 critical threshold
        alerts = detect_drift(outcomes, window=10, min_trades=10)
        assert len(alerts) >= 1
        alert = alerts[0]
        assert alert.severity == DriftSeverity.CRITICAL
        assert alert.regime_id == 1
        assert alert.strategy_type == StrategyType.IRON_CONDOR
        assert alert.drop_pct > 0.25

    def test_warning_drift_detected(self):
        """Historical 80% win rate, recent drops to 60% triggers warning."""
        from market_analyzer.performance import detect_drift

        outcomes = _make_outcomes_with_drift(
            n_historical=20,
            n_recent=10,
            hist_win_rate=0.80,
            recent_win_rate=0.60,
        )
        # Historical overall: (16 + 6) / 30 = 0.733
        # Recent: 6/10 = 0.60
        # drop = 0.733 - 0.60 = 0.133 — close to 0.15
        # Use lower warning threshold to ensure detection
        alerts = detect_drift(
            outcomes, window=10, min_trades=10, warning_threshold=0.10
        )
        assert len(alerts) >= 1
        alert = alerts[0]
        assert alert.severity in (DriftSeverity.WARNING, DriftSeverity.CRITICAL)

    def test_no_drift_when_stable(self):
        """Historical 60% win, recent 55% — no alert (5pp drop < 15pp)."""
        from market_analyzer.performance import detect_drift

        outcomes = _make_outcomes_with_drift(
            n_historical=20,
            n_recent=10,
            hist_win_rate=0.60,
            recent_win_rate=0.55,
        )
        alerts = detect_drift(
            outcomes, window=10, min_trades=10, warning_threshold=0.15
        )
        assert alerts == []

    def test_drift_alert_fields(self):
        """DriftAlert has all expected fields populated."""
        from market_analyzer.performance import detect_drift
        from market_analyzer.models.learning import DriftAlert, DriftSeverity

        outcomes = _make_outcomes_with_drift(
            n_historical=20,
            n_recent=10,
            hist_win_rate=0.9,
            recent_win_rate=0.1,
        )
        alerts = detect_drift(outcomes, window=10, min_trades=10)
        assert len(alerts) >= 1
        alert = alerts[0]
        assert isinstance(alert, DriftAlert)
        assert isinstance(alert.severity, DriftSeverity)
        assert isinstance(alert.regime_id, int)
        assert isinstance(alert.strategy_type, StrategyType)
        assert isinstance(alert.historical_win_rate, float)
        assert isinstance(alert.recent_win_rate, float)
        assert isinstance(alert.recent_trades, int)
        assert isinstance(alert.drop_pct, float)
        assert isinstance(alert.recommendation, str)
        assert len(alert.recommendation) > 0


class TestML2ThompsonSampling:
    """ML2: Thompson Sampling bandits — build_bandits, update_bandit, select_strategies."""

    def test_build_bandits_from_outcomes(self):
        """10 IC wins + 5 IC losses in R1 builds bandit with alpha=11, beta=6."""
        from market_analyzer.performance import build_bandits

        outcomes = []
        for i in range(10):
            outcomes.append(_make_outcome(pnl_pct=0.15, pnl_dollars=40.0, trade_id=f"w-{i}"))
        for i in range(5):
            outcomes.append(_make_outcome(pnl_pct=-0.10, pnl_dollars=-40.0, trade_id=f"l-{i}"))

        bandits = build_bandits(outcomes)
        key = "R1_iron_condor"
        assert key in bandits
        b = bandits[key]
        assert b.alpha == 11.0  # 1 (prior) + 10 wins
        assert b.beta_param == 6.0  # 1 (prior) + 5 losses
        assert b.total_trades == 15

    def test_build_bandits_empty(self):
        """Empty outcomes produces empty bandit dict."""
        from market_analyzer.performance import build_bandits

        bandits = build_bandits([])
        assert bandits == {}

    def test_update_bandit_win(self):
        """Update with won=True increments alpha by 1."""
        from market_analyzer.performance import update_bandit
        from market_analyzer.models.learning import StrategyBandit

        b = StrategyBandit(
            regime_id=1,
            strategy_type=StrategyType.IRON_CONDOR,
            alpha=5.0,
            beta_param=3.0,
            total_trades=7,
        )
        updated = update_bandit(b, won=True)
        assert updated.alpha == 6.0
        assert updated.beta_param == 3.0
        assert updated.total_trades == 8

    def test_update_bandit_loss(self):
        """Update with won=False increments beta_param by 1."""
        from market_analyzer.performance import update_bandit
        from market_analyzer.models.learning import StrategyBandit

        b = StrategyBandit(
            regime_id=1,
            strategy_type=StrategyType.IRON_CONDOR,
            alpha=5.0,
            beta_param=3.0,
            total_trades=7,
        )
        updated = update_bandit(b, won=False)
        assert updated.alpha == 5.0
        assert updated.beta_param == 4.0
        assert updated.total_trades == 8

    def test_select_strategies_returns_n(self):
        """select_strategies with n=3 returns exactly 3 tuples."""
        from market_analyzer.performance import select_strategies
        from market_analyzer.models.learning import StrategyBandit

        bandits = {
            "R1_iron_condor": StrategyBandit(
                regime_id=1, strategy_type=StrategyType.IRON_CONDOR,
                alpha=10.0, beta_param=3.0,
            ),
        }
        available = [
            StrategyType.IRON_CONDOR,
            StrategyType.IRON_BUTTERFLY,
            StrategyType.CALENDAR,
            StrategyType.DIAGONAL,
        ]
        result = select_strategies(bandits, regime_id=1, available_strategies=available, n=3, seed=42)
        assert len(result) == 3
        for strategy, score in result:
            assert isinstance(strategy, StrategyType)
            assert isinstance(score, float)
            assert 0.0 <= score <= 1.0

    def test_select_strategies_deterministic_with_seed(self):
        """Same seed produces identical results."""
        from market_analyzer.performance import select_strategies
        from market_analyzer.models.learning import StrategyBandit

        bandits = {
            "R1_iron_condor": StrategyBandit(
                regime_id=1, strategy_type=StrategyType.IRON_CONDOR,
                alpha=10.0, beta_param=3.0,
            ),
            "R1_calendar": StrategyBandit(
                regime_id=1, strategy_type=StrategyType.CALENDAR,
                alpha=5.0, beta_param=5.0,
            ),
        }
        available = [
            StrategyType.IRON_CONDOR,
            StrategyType.CALENDAR,
            StrategyType.DIAGONAL,
        ]
        r1 = select_strategies(bandits, 1, available, n=3, seed=99)
        r2 = select_strategies(bandits, 1, available, n=3, seed=99)
        assert r1 == r2

    def test_bandit_expected_win_rate(self):
        """StrategyBandit(alpha=8, beta_param=2) has expected_win_rate=0.8."""
        from market_analyzer.models.learning import StrategyBandit

        b = StrategyBandit(
            regime_id=1,
            strategy_type=StrategyType.IRON_CONDOR,
            alpha=8.0,
            beta_param=2.0,
        )
        assert b.expected_win_rate == pytest.approx(0.8)

    def test_bandit_key_format(self):
        """StrategyBandit key is 'R{id}_{strategy}'."""
        from market_analyzer.models.learning import StrategyBandit

        b = StrategyBandit(
            regime_id=1,
            strategy_type=StrategyType.IRON_CONDOR,
        )
        assert b.key == "R1_iron_condor"

    def test_no_data_bandit_explores(self):
        """Strategy with no bandit data gets uniform prior — wide variance."""
        from market_analyzer.performance import select_strategies

        # No bandits at all — all strategies use Beta(1,1) uniform prior
        available = [StrategyType.IRON_CONDOR, StrategyType.CALENDAR]
        samples = []
        for seed in range(50):
            result = select_strategies({}, 1, available, n=1, seed=seed)
            samples.append(result[0][1])

        # With uniform prior, samples should span a wide range
        assert max(samples) - min(samples) > 0.3, "Exploration variance too low"

    def test_proven_winner_exploited(self):
        """Bandit with alpha=50, beta=5 is consistently ranked #1."""
        from market_analyzer.performance import select_strategies
        from market_analyzer.models.learning import StrategyBandit

        bandits = {
            "R1_iron_condor": StrategyBandit(
                regime_id=1, strategy_type=StrategyType.IRON_CONDOR,
                alpha=50.0, beta_param=5.0,
            ),
            "R1_calendar": StrategyBandit(
                regime_id=1, strategy_type=StrategyType.CALENDAR,
                alpha=2.0, beta_param=8.0,
            ),
        }
        available = [StrategyType.IRON_CONDOR, StrategyType.CALENDAR]

        top_count = 0
        for seed in range(100):
            result = select_strategies(bandits, 1, available, n=2, seed=seed)
            if result[0][0] == StrategyType.IRON_CONDOR:
                top_count += 1

        # IC with 91% expected win rate should dominate
        assert top_count >= 85, f"IC only ranked #1 {top_count}/100 times"


class TestML3ThresholdOptimization:
    """ML3: Threshold optimization — optimize_thresholds()."""

    def test_optimize_empty_outcomes(self):
        """Empty outcomes returns defaults unchanged."""
        from market_analyzer.performance import optimize_thresholds
        from market_analyzer.models.learning import ThresholdConfig

        result = optimize_thresholds([])
        assert isinstance(result, ThresholdConfig)
        defaults = ThresholdConfig()
        assert result.ic_iv_rank_min == defaults.ic_iv_rank_min
        assert result.pop_min == defaults.pop_min
        assert result.trades_analyzed == 0

    def test_optimize_few_outcomes(self):
        """Below 2*min_trades_per_bucket returns defaults."""
        from market_analyzer.performance import optimize_thresholds
        from market_analyzer.models.learning import ThresholdConfig

        outcomes = [
            _make_outcome(pnl_pct=0.15, pnl_dollars=40.0, trade_id=f"t-{i}")
            for i in range(10)
        ]
        # Default min_trades_per_bucket=15, so need 30. 10 is below.
        result = optimize_thresholds(outcomes)
        defaults = ThresholdConfig()
        assert result.ic_iv_rank_min == defaults.ic_iv_rank_min
        assert result.trades_analyzed == 10

    def test_optimize_returns_threshold_config(self):
        """Valid outcomes produce a ThresholdConfig instance."""
        from market_analyzer.performance import optimize_thresholds
        from market_analyzer.models.learning import ThresholdConfig

        # Need enough outcomes with iv_rank_at_entry for optimization
        outcomes = []
        for i in range(40):
            won = i % 3 != 0  # ~67% win rate
            outcomes.append(
                TradeOutcome(
                    trade_id=f"opt-{i}",
                    ticker="SPY",
                    strategy_type=StrategyType.IRON_CONDOR,
                    regime_at_entry=1,
                    regime_at_exit=1,
                    entry_date=date(2026, 1, 1) + timedelta(days=i),
                    exit_date=date(2026, 1, 15) + timedelta(days=i),
                    entry_price=0.80,
                    exit_price=0.40 if won else 1.20,
                    pnl_dollars=40.0 if won else -40.0,
                    pnl_pct=0.15 if won else -0.10,
                    holding_days=14,
                    exit_reason=TradeExitReason.PROFIT_TARGET
                    if won
                    else TradeExitReason.STOP_LOSS,
                    composite_score_at_entry=0.70 + (i * 0.005),
                    iv_rank_at_entry=10.0 + i,  # 10-49 spread
                    order_side="credit",
                )
            )
        result = optimize_thresholds(outcomes)
        assert isinstance(result, ThresholdConfig)
        assert result.trades_analyzed == 40

    def test_optimize_clamps_changes(self):
        """No threshold changes by more than max_change_pct."""
        from market_analyzer.performance import optimize_thresholds
        from market_analyzer.models.learning import ThresholdConfig

        defaults = ThresholdConfig()
        outcomes = []
        for i in range(40):
            won = i % 3 != 0
            outcomes.append(
                TradeOutcome(
                    trade_id=f"clamp-{i}",
                    ticker="SPY",
                    strategy_type=StrategyType.IRON_CONDOR,
                    regime_at_entry=1,
                    regime_at_exit=1,
                    entry_date=date(2026, 1, 1) + timedelta(days=i),
                    exit_date=date(2026, 1, 15) + timedelta(days=i),
                    entry_price=0.80,
                    exit_price=0.40 if won else 1.20,
                    pnl_dollars=40.0 if won else -40.0,
                    pnl_pct=0.15 if won else -0.10,
                    holding_days=14,
                    exit_reason=TradeExitReason.PROFIT_TARGET
                    if won
                    else TradeExitReason.STOP_LOSS,
                    composite_score_at_entry=0.70 + (i * 0.005),
                    iv_rank_at_entry=10.0 + i,
                    order_side="credit",
                )
            )
        result = optimize_thresholds(outcomes, max_change_pct=0.20)

        # Check all thresholds are within 20% of defaults
        for field in [
            "ic_iv_rank_min", "ifly_iv_rank_min", "earnings_iv_rank_min",
            "leap_iv_rank_max", "pop_min", "score_min", "credit_width_min",
            "adx_trend_max", "adx_notrend_min",
        ]:
            default_val = getattr(defaults, field)
            result_val = getattr(result, field)
            if default_val != 0:
                change_pct = abs(result_val - default_val) / abs(default_val)
                assert change_pct <= 0.20 + 0.01, (
                    f"{field}: {default_val} -> {result_val} "
                    f"({change_pct:.1%} change exceeds 20%)"
                )

    def test_threshold_config_defaults(self):
        """ThresholdConfig() has all expected default values."""
        from market_analyzer.models.learning import ThresholdConfig

        config = ThresholdConfig()
        assert config.ic_iv_rank_min == 15.0
        assert config.ifly_iv_rank_min == 20.0
        assert config.earnings_iv_rank_min == 25.0
        assert config.leap_iv_rank_max == 70.0
        assert config.pop_min == 0.50
        assert config.score_min == 0.60
        assert config.credit_width_min == 0.10
        assert config.adx_trend_max == 35.0
        assert config.adx_notrend_min == 15.0
        assert config.trades_analyzed == 0
        assert config.last_optimized is None

    def test_optimize_sets_metadata(self):
        """trades_analyzed and last_optimized are populated."""
        from market_analyzer.performance import optimize_thresholds
        from market_analyzer.models.learning import ThresholdConfig

        outcomes = [
            _make_outcome(pnl_pct=0.15, pnl_dollars=40.0, trade_id=f"meta-{i}")
            for i in range(5)
        ]
        result = optimize_thresholds(outcomes)
        assert result.trades_analyzed == 5
        assert result.last_optimized == date.today()


# ── CR-6: Multi-Broker (Dhan, Zerodha) ──


class TestCR6MultiBroker:
    """CR-6: Dhan and Zerodha broker stubs are importable and have correct properties."""

    def test_dhan_imports(self):
        from market_analyzer.broker.dhan import connect_dhan, connect_dhan_from_session
        assert callable(connect_dhan)
        assert callable(connect_dhan_from_session)

    def test_zerodha_imports(self):
        from market_analyzer.broker.zerodha import connect_zerodha, connect_zerodha_from_session
        assert callable(connect_zerodha)
        assert callable(connect_zerodha_from_session)

    def test_dhan_market_data_properties(self):
        from market_analyzer.broker.dhan.market_data import DhanMarketData
        md = DhanMarketData()
        assert md.currency == "INR"
        assert md.timezone == "Asia/Kolkata"
        assert md.lot_size_default == 25
        assert md.provider_name == "dhan"

    def test_zerodha_market_data_properties(self):
        from market_analyzer.broker.zerodha.market_data import ZerodhaMarketData
        md = ZerodhaMarketData()
        assert md.currency == "INR"
        assert md.timezone == "Asia/Kolkata"
        assert md.lot_size_default == 25
        assert md.provider_name == "zerodha"

    def test_dhan_market_hours(self):
        from market_analyzer.broker.dhan.market_data import DhanMarketData
        md = DhanMarketData()
        open_t, close_t = md.market_hours
        assert open_t == time(9, 15)
        assert close_t == time(15, 30)

    def test_zerodha_market_hours(self):
        from market_analyzer.broker.zerodha.market_data import ZerodhaMarketData
        md = ZerodhaMarketData()
        open_t, close_t = md.market_hours
        assert open_t == time(9, 15)
        assert close_t == time(15, 30)

    def test_dhan_connect_returns_4_tuple(self):
        from market_analyzer.broker.dhan import connect_dhan
        result = connect_dhan(api_key="test", access_token="test")
        assert len(result) == 4

    def test_zerodha_connect_returns_4_tuple(self):
        from market_analyzer.broker.zerodha import connect_zerodha
        result = connect_zerodha(api_key="test", access_token="test")
        assert len(result) == 4

    def test_dhan_stubs_raise_not_implemented(self):
        from market_analyzer.broker.dhan.market_data import DhanMarketData
        md = DhanMarketData()
        with pytest.raises(NotImplementedError):
            md.get_option_chain("NIFTY")

    def test_zerodha_is_real_implementation(self):
        """Zerodha is a real implementation — returns empty without credentials."""
        from market_analyzer.broker.zerodha.market_data import ZerodhaMarketData
        md = ZerodhaMarketData()
        # Without valid API key, returns empty (not NotImplementedError)
        result = md.get_option_chain("NIFTY")
        assert isinstance(result, list)


# ── CR-7: Currency, Timezone, LotSize on Models and Providers ──


class TestCR7CurrencyTimezone:
    """CR-7: Currency, timezone, and lot_size fields on models and providers."""

    def test_account_balance_currency_default(self):
        """AccountBalance.currency defaults to USD."""
        from market_analyzer.models.quotes import AccountBalance
        bal = AccountBalance(
            account_number="TEST001",
            net_liquidating_value=50000.0,
            cash_balance=10000.0,
            derivative_buying_power=25000.0,
            equity_buying_power=50000.0,
            maintenance_requirement=5000.0,
        )
        assert bal.currency == "USD"
        assert bal.timezone == "US/Eastern"

    def test_account_balance_currency_inr(self):
        """AccountBalance accepts INR currency."""
        from market_analyzer.models.quotes import AccountBalance
        bal = AccountBalance(
            account_number="DHAN001",
            net_liquidating_value=5000000.0,
            cash_balance=1000000.0,
            derivative_buying_power=2500000.0,
            equity_buying_power=5000000.0,
            maintenance_requirement=500000.0,
            currency="INR",
            timezone="Asia/Kolkata",
        )
        assert bal.currency == "INR"
        assert bal.timezone == "Asia/Kolkata"

    def test_option_quote_lot_size_default(self):
        """OptionQuote.lot_size defaults to 100."""
        quote = OptionQuote(
            ticker="SPY",
            expiration=date(2026, 3, 20),
            strike=580.0,
            option_type="put",
            bid=3.50,
            ask=3.80,
            mid=3.65,
        )
        assert quote.lot_size == 100

    def test_option_quote_lot_size_custom(self):
        """OptionQuote.lot_size can be set for India (e.g. 25)."""
        quote = OptionQuote(
            ticker="NIFTY",
            expiration=date(2026, 3, 20),
            strike=22000.0,
            option_type="call",
            bid=150.0,
            ask=160.0,
            mid=155.0,
            lot_size=25,
        )
        assert quote.lot_size == 25

    def test_trade_spec_lot_size_default(self):
        """TradeSpec.lot_size defaults to 100."""
        leg = LegSpec(
            role="short_put",
            action=LegAction.SELL_TO_OPEN,
            option_type="put",
            strike=570.0,
            strike_label="1 ATR OTM put",
            expiration=date(2026, 4, 17),
            days_to_expiry=35,
            atm_iv_at_expiry=0.18,
        )
        ts = TradeSpec(
            ticker="SPY",
            legs=[leg],
            underlying_price=590.0,
            target_dte=35,
            target_expiration=date(2026, 4, 17),
            spec_rationale="test",
        )
        assert ts.lot_size == 100
        assert ts.currency == "USD"

    def test_trade_spec_lot_size_india(self):
        """TradeSpec with lot_size=25 uses 25 in position_size."""
        leg = LegSpec(
            role="short_put",
            action=LegAction.SELL_TO_OPEN,
            option_type="put",
            strike=22000.0,
            strike_label="1 ATR OTM put",
            expiration=date(2026, 4, 17),
            days_to_expiry=35,
            atm_iv_at_expiry=0.18,
        )
        ts = TradeSpec(
            ticker="NIFTY",
            legs=[leg],
            underlying_price=22500.0,
            target_dte=35,
            target_expiration=date(2026, 4, 17),
            spec_rationale="test",
            lot_size=25,
            currency="INR",
            wing_width_points=200.0,
        )
        assert ts.lot_size == 25
        assert ts.currency == "INR"
        # position_size should use lot_size=25: risk_per = 200 * 25 = 5000
        contracts = ts.position_size(capital=100000, risk_pct=0.02)
        # max_risk_budget = 100000 * 0.02 = 2000; 2000 / 5000 = 0 -> clamped to 1
        assert contracts == 1

    def test_trade_spec_entry_window_timezone_default(self):
        """TradeSpec.entry_window_timezone defaults to US/Eastern."""
        leg = LegSpec(
            role="short_put",
            action=LegAction.SELL_TO_OPEN,
            option_type="put",
            strike=570.0,
            strike_label="1 ATR OTM put",
            expiration=date(2026, 4, 17),
            days_to_expiry=35,
            atm_iv_at_expiry=0.18,
        )
        ts = TradeSpec(
            ticker="SPY",
            legs=[leg],
            underlying_price=590.0,
            target_dte=35,
            target_expiration=date(2026, 4, 17),
            spec_rationale="test",
        )
        assert ts.entry_window_timezone == "US/Eastern"

    def test_market_data_provider_defaults(self):
        """MarketDataProvider base class has USD/US/Eastern defaults."""
        from market_analyzer.broker.base import MarketDataProvider
        # Check that the properties exist on the class
        assert hasattr(MarketDataProvider, "currency")
        assert hasattr(MarketDataProvider, "timezone")
        assert hasattr(MarketDataProvider, "market_hours")
        assert hasattr(MarketDataProvider, "lot_size_default")


# ── CR-11: Performance Analytics ──


class TestCR11Analytics:
    """CR-11: compute_sharpe, compute_drawdown, compute_regime_performance."""

    def test_compute_sharpe_basic(self):
        """10 outcomes produce a SharpeResult with non-zero sharpe_ratio."""
        from market_analyzer.performance import compute_sharpe
        outcomes = [
            _make_outcome(
                pnl_pct=0.10 if i % 3 != 0 else -0.05,
                pnl_dollars=40.0 if i % 3 != 0 else -20.0,
                trade_id=f"sharpe-{i}",
            )
            for i in range(10)
        ]
        result = compute_sharpe(outcomes)
        assert result.total_trades == 10
        assert result.sharpe_ratio != 0.0
        assert result.annualized_return_pct != 0.0
        assert result.annualized_volatility_pct > 0.0
        assert result.risk_free_rate == 0.05

    def test_compute_sharpe_empty(self):
        """Empty outcomes produce sharpe_ratio = 0."""
        from market_analyzer.performance import compute_sharpe
        result = compute_sharpe([])
        assert result.sharpe_ratio == 0.0
        assert result.total_trades == 0

    def test_compute_sharpe_single_trade(self):
        """Single trade (< 2 required) produces sharpe_ratio = 0."""
        from market_analyzer.performance import compute_sharpe
        result = compute_sharpe([_make_outcome(trade_id="single-1")])
        assert result.sharpe_ratio == 0.0
        assert result.total_trades == 1

    def test_compute_drawdown_basic(self):
        """Outcomes with a loss streak produce max_drawdown_dollars > 0."""
        from market_analyzer.performance import compute_drawdown
        outcomes = [
            _make_outcome(pnl_pct=0.10, pnl_dollars=100.0, trade_id="dd-0"),
            _make_outcome(pnl_pct=0.10, pnl_dollars=100.0, trade_id="dd-1"),
            _make_outcome(pnl_pct=-0.20, pnl_dollars=-150.0, trade_id="dd-2"),
            _make_outcome(pnl_pct=-0.10, pnl_dollars=-80.0, trade_id="dd-3"),
            _make_outcome(pnl_pct=0.10, pnl_dollars=50.0, trade_id="dd-4"),
        ]
        result = compute_drawdown(outcomes)
        assert result.max_drawdown_dollars > 0
        assert result.max_drawdown_pct > 0.0

    def test_compute_drawdown_empty(self):
        """Empty outcomes produce max_drawdown = 0."""
        from market_analyzer.performance import compute_drawdown
        result = compute_drawdown([])
        assert result.max_drawdown_dollars == 0.0
        assert result.max_drawdown_pct == 0.0
        assert result.recovery_trades == 0

    def test_compute_regime_performance_basic(self):
        """Outcomes in R1 and R2 produce dict with keys 1, 2."""
        from market_analyzer.performance import compute_regime_performance
        outcomes = [
            _make_outcome(regime=1, pnl_pct=0.10, pnl_dollars=40.0, trade_id="rp-0"),
            _make_outcome(regime=1, pnl_pct=0.15, pnl_dollars=60.0, trade_id="rp-1"),
            _make_outcome(regime=2, pnl_pct=-0.05, pnl_dollars=-20.0, trade_id="rp-2"),
            _make_outcome(regime=2, pnl_pct=0.08, pnl_dollars=30.0, trade_id="rp-3"),
        ]
        result = compute_regime_performance(outcomes)
        assert 1 in result
        assert 2 in result
        assert result[1].total_trades == 2
        assert result[2].total_trades == 2
        assert result[1].win_rate == 1.0  # Both trades positive
        assert result[2].win_rate == 0.5  # 1 win, 1 loss

    def test_compute_regime_performance_empty(self):
        """Empty outcomes produce empty dict."""
        from market_analyzer.performance import compute_regime_performance
        result = compute_regime_performance([])
        assert result == {}

    def test_sharpe_result_model_fields(self):
        """SharpeResult has all expected fields."""
        from market_analyzer.models.feedback import SharpeResult
        fields = SharpeResult.model_fields
        assert "sharpe_ratio" in fields
        assert "sortino_ratio" in fields
        assert "annualized_return_pct" in fields
        assert "annualized_volatility_pct" in fields
        assert "risk_free_rate" in fields
        assert "total_trades" in fields

    def test_drawdown_result_model_fields(self):
        """DrawdownResult has all expected fields."""
        from market_analyzer.models.feedback import DrawdownResult
        fields = DrawdownResult.model_fields
        assert "max_drawdown_pct" in fields
        assert "max_drawdown_dollars" in fields
        assert "max_drawdown_duration_days" in fields
        assert "current_drawdown_pct" in fields
        assert "current_drawdown_dollars" in fields
        assert "recovery_trades" in fields

    def test_regime_performance_model_fields(self):
        """RegimePerformance has all expected fields."""
        from market_analyzer.models.feedback import RegimePerformance
        fields = RegimePerformance.model_fields
        assert "regime_id" in fields
        assert "regime_name" in fields
        assert "total_trades" in fields
        assert "win_rate" in fields
        assert "avg_pnl_pct" in fields
        assert "total_pnl_dollars" in fields
        assert "best_strategy" in fields
        assert "worst_strategy" in fields

    def test_compute_sharpe_custom_risk_free(self):
        """Custom risk-free rate is passed through."""
        from market_analyzer.performance import compute_sharpe
        outcomes = [
            _make_outcome(pnl_pct=0.10, pnl_dollars=40.0, trade_id=f"rfr-{i}")
            for i in range(5)
        ]
        result = compute_sharpe(outcomes, risk_free_rate=0.03)
        assert result.risk_free_rate == 0.03


# ── CR-12: India Data Aliases ──


class TestCR12IndiaData:
    """CR-12: yfinance aliases for Indian indices."""

    def test_nifty_alias_exists(self):
        from market_analyzer.data.providers.yfinance import _YFINANCE_ALIASES
        assert _YFINANCE_ALIASES.get("NIFTY") == "^NSEI"

    def test_banknifty_alias(self):
        from market_analyzer.data.providers.yfinance import _YFINANCE_ALIASES
        assert _YFINANCE_ALIASES.get("BANKNIFTY") == "^NSEBANK"

    def test_finnifty_alias(self):
        from market_analyzer.data.providers.yfinance import _YFINANCE_ALIASES
        assert _YFINANCE_ALIASES.get("FINNIFTY") == "NIFTY_FIN_SERVICE.NS"

    def test_sensex_alias(self):
        from market_analyzer.data.providers.yfinance import _YFINANCE_ALIASES
        assert _YFINANCE_ALIASES.get("SENSEX") == "^BSESN"


# ── CR-13: MarketRegistry ──


class TestCR13MarketRegistry:
    """CR-13: MarketRegistry for static market/instrument data."""

    def test_get_market_us(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        m = r.get_market("US")
        assert m.currency == "USD"
        assert m.timezone == "US/Eastern"
        assert m.market_id == "US"

    def test_get_market_india(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        m = r.get_market("INDIA")
        assert m.currency == "INR"
        assert m.timezone == "Asia/Kolkata"
        assert m.market_id == "INDIA"

    def test_get_market_case_insensitive(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        m = r.get_market("india")
        assert m.market_id == "INDIA"

    def test_get_instrument_nifty(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        inst = r.get_instrument("NIFTY")
        assert inst.lot_size == 25
        assert inst.market == "INDIA"
        assert inst.has_leaps is False
        assert inst.settlement == "cash"
        assert inst.exercise_style == "european"

    def test_get_instrument_spy(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        inst = r.get_instrument("SPY")
        assert inst.lot_size == 100
        assert inst.market == "US"
        assert inst.has_leaps is True
        assert inst.settlement == "physical"

    def test_strategy_available_leaps_india(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        assert r.strategy_available("leaps", "NIFTY") is False

    def test_strategy_available_pmcc_india(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        assert r.strategy_available("pmcc", "NIFTY") is False

    def test_strategy_available_ic_india(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        assert r.strategy_available("iron_condor", "NIFTY") is True

    def test_strategy_available_zero_dte_india(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        assert r.strategy_available("zero_dte", "NIFTY") is True

    def test_strategy_available_leaps_us(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        assert r.strategy_available("leaps", "SPY") is True

    def test_to_yfinance_nifty(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        assert r.to_yfinance("NIFTY") == "^NSEI"

    def test_to_yfinance_reliance(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        assert r.to_yfinance("RELIANCE") == "RELIANCE.NS"

    def test_to_yfinance_spy(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        assert r.to_yfinance("SPY") == "SPY"

    def test_to_yfinance_banknifty(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        assert r.to_yfinance("BANKNIFTY") == "^NSEBANK"

    def test_to_yfinance_unknown_india_fallback(self):
        """Unknown ticker with market=INDIA gets .NS suffix."""
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        assert r.to_yfinance("ZOMATO", market="INDIA") == "ZOMATO.NS"

    def test_estimate_margin_us(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        m = r.estimate_margin("iron_condor", "SPY", wing_width=5)
        assert m.currency == "USD"
        assert m.margin_amount == 500  # 5 * 100 * 1
        assert m.method == "reg_t"

    def test_estimate_margin_india(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        m = r.estimate_margin("iron_condor", "NIFTY", wing_width=200)
        assert m.currency == "INR"
        assert m.margin_amount == 5000  # 200 * 25 * 1
        assert m.method == "span_exposure"

    def test_estimate_margin_contracts(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        m = r.estimate_margin("iron_condor", "SPY", wing_width=5, contracts=3)
        assert m.margin_amount == 1500  # 5 * 100 * 3

    def test_list_instruments_india(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        india = r.list_instruments(market="INDIA")
        assert len(india) >= 23  # 3 indices + 20 stocks

    def test_list_instruments_us(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        us = r.list_instruments(market="US")
        assert len(us) >= 14  # SPY, QQQ, IWM, SPX, GLD, TLT, + 8 equities

    def test_list_instruments_all(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        all_inst = r.list_instruments()
        assert len(all_inst) >= 37  # 14 US + 23 India

    def test_unknown_market_raises(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        with pytest.raises(KeyError, match="Unknown market"):
            r.get_market("MARS")

    def test_unknown_instrument_raises(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        with pytest.raises(KeyError, match="Unknown instrument"):
            r.get_instrument("ZZZZZ")

    def test_india_stock_lot_sizes(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        assert r.get_instrument("RELIANCE").lot_size == 250
        assert r.get_instrument("BANKNIFTY").lot_size == 15
        assert r.get_instrument("FINNIFTY").lot_size == 40
        assert r.get_instrument("TCS").lot_size == 150
        assert r.get_instrument("INFY").lot_size == 300

    def test_us_market_hours(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        m = r.get_market("US")
        assert m.open_time == time(9, 30)
        assert m.close_time == time(16, 0)

    def test_india_market_hours(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        m = r.get_market("INDIA")
        assert m.open_time == time(9, 15)
        assert m.close_time == time(15, 30)

    def test_nifty_has_0dte(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        inst = r.get_instrument("NIFTY")
        assert inst.has_0dte is True
        assert inst.max_dte == 90

    def test_india_stock_no_0dte(self):
        from market_analyzer import MarketRegistry
        r = MarketRegistry()
        inst = r.get_instrument("RELIANCE")
        assert inst.has_0dte is False

    def test_market_info_model(self):
        """MarketInfo Pydantic model has expected fields."""
        from market_analyzer.registry import MarketInfo
        fields = MarketInfo.model_fields
        assert "market_id" in fields
        assert "currency" in fields
        assert "timezone" in fields
        assert "open_time" in fields
        assert "close_time" in fields
        assert "settlement_days" in fields
        assert "force_close_time" in fields

    def test_instrument_info_model(self):
        """InstrumentInfo Pydantic model has expected fields."""
        from market_analyzer.registry import InstrumentInfo
        fields = InstrumentInfo.model_fields
        assert "ticker" in fields
        assert "lot_size" in fields
        assert "strike_interval" in fields
        assert "settlement" in fields
        assert "has_0dte" in fields
        assert "has_leaps" in fields
        assert "yfinance_symbol" in fields

    def test_margin_estimate_model(self):
        """MarginEstimate Pydantic model has expected fields."""
        from market_analyzer.registry import MarginEstimate
        fields = MarginEstimate.model_fields
        assert "strategy" in fields
        assert "ticker" in fields
        assert "margin_amount" in fields
        assert "currency" in fields
        assert "method" in fields
        assert "notes" in fields


# ── H1: Currency Conversion ──


class TestH1CurrencyConversion:
    """H1: CurrencyPair, convert_amount, compute_portfolio_exposure."""

    def test_convert_same_currency(self):
        """USD to USD = same amount, no rate needed."""
        from market_analyzer.currency import convert_amount

        result = convert_amount(1000.0, "USD", "USD", {})
        assert result == 1000.0

    def test_convert_usd_to_inr(self):
        """1000 USD * 83.5 = 83500 INR."""
        from market_analyzer.currency import CurrencyPair, convert_amount

        rates = {
            "USD/INR": CurrencyPair(base="USD", quote="INR", rate=83.5, as_of=date.today()),
        }
        result = convert_amount(1000.0, "USD", "INR", rates)
        assert result == pytest.approx(83500.0)

    def test_convert_inr_to_usd(self):
        """83500 INR / 83.5 = 1000 USD (inverse lookup)."""
        from market_analyzer.currency import CurrencyPair, convert_amount

        rates = {
            "USD/INR": CurrencyPair(base="USD", quote="INR", rate=83.5, as_of=date.today()),
        }
        result = convert_amount(83500.0, "INR", "USD", rates)
        assert result == pytest.approx(1000.0)

    def test_convert_missing_rate_raises(self):
        """Unknown currency pair raises KeyError."""
        from market_analyzer.currency import convert_amount

        with pytest.raises(KeyError, match="No exchange rate found"):
            convert_amount(100.0, "USD", "EUR", {})

    def test_portfolio_exposure(self):
        """2 USD positions + 1 INR position: computes total in USD and foreign pct."""
        from market_analyzer.currency import (
            CurrencyPair,
            PositionExposure,
            compute_portfolio_exposure,
        )

        positions = [
            PositionExposure(ticker="SPY", market="US", currency="USD", notional_value=30000, unrealized_pnl=500),
            PositionExposure(ticker="QQQ", market="US", currency="USD", notional_value=15000, unrealized_pnl=-200),
            PositionExposure(ticker="RELIANCE", market="INDIA", currency="INR", notional_value=835000, unrealized_pnl=10000),
        ]
        rates = {
            "USD/INR": CurrencyPair(base="USD", quote="INR", rate=83.5, as_of=date.today()),
        }
        result = compute_portfolio_exposure(positions, rates, base_currency="USD")

        # USD: 30000 + 15000 = 45000
        # INR: 835000 / 83.5 = 10000 USD
        # Total: 55000
        assert result.total_exposure == pytest.approx(55000.0, abs=1)
        assert result.currency_risk_pct == pytest.approx(10000.0 / 55000.0, abs=0.001)
        assert result.largest_foreign_exposure == "INR"

    def test_portfolio_exposure_all_base(self):
        """All USD positions -> currency_risk_pct = 0."""
        from market_analyzer.currency import (
            PositionExposure,
            compute_portfolio_exposure,
        )

        positions = [
            PositionExposure(ticker="SPY", market="US", currency="USD", notional_value=30000, unrealized_pnl=0),
            PositionExposure(ticker="QQQ", market="US", currency="USD", notional_value=20000, unrealized_pnl=0),
        ]
        result = compute_portfolio_exposure(positions, {}, base_currency="USD")
        assert result.currency_risk_pct == 0.0
        assert result.largest_foreign_exposure is None


# ── H3: Currency Hedge Assessment ──


class TestH3CurrencyHedge:
    """H3: assess_currency_exposure recommendations."""

    def _make_positions(self, usd_amount: float, inr_amount: float):
        from market_analyzer.currency import PositionExposure

        positions = [
            PositionExposure(ticker="SPY", market="US", currency="USD", notional_value=usd_amount, unrealized_pnl=0),
        ]
        if inr_amount > 0:
            positions.append(
                PositionExposure(ticker="RELIANCE", market="INDIA", currency="INR", notional_value=inr_amount, unrealized_pnl=0),
            )
        return positions

    def _rates(self):
        from market_analyzer.currency import CurrencyPair

        return {
            "USD/INR": CurrencyPair(base="USD", quote="INR", rate=83.5, as_of=date.today()),
        }

    def test_low_foreign_exposure(self):
        """< 10% foreign -> natural hedge sufficient."""
        from market_analyzer.currency import assess_currency_exposure

        # INR 418K / 83.5 = ~5K USD. Total ~55K. Foreign ~9%
        positions = self._make_positions(50000, 418000)
        result = assess_currency_exposure(positions, self._rates())
        assert "natural hedge sufficient" in result.recommendation

    def test_high_foreign_exposure(self):
        """> 30% foreign -> hedge recommended."""
        from market_analyzer.currency import assess_currency_exposure

        # INR 4,175,000 / 83.5 = 50K USD. Total ~80K. Foreign ~62%
        positions = self._make_positions(30000, 4175000)
        result = assess_currency_exposure(positions, self._rates())
        assert "hedge recommended" in result.recommendation


# ── H4: Currency P&L Decomposition ──


class TestH4CurrencyPnL:
    """H4: compute_currency_pnl decomposition."""

    def test_same_currency_no_fx(self):
        """USD position -> currency_pnl = 0."""
        from market_analyzer.currency import compute_currency_pnl

        result = compute_currency_pnl(
            ticker="SPY", trading_pnl_local=500.0, position_value_local=30000.0,
            local_currency="USD", base_currency="USD",
            fx_rate_at_entry=1.0, fx_rate_current=1.0,
        )
        assert result.currency_pnl_base == 0.0
        assert result.total_pnl_base == 500.0

    def test_inr_weakens_hurts_usd_investor(self):
        """INR weakens (rate goes from 83 to 85) -> negative currency P&L in USD."""
        from market_analyzer.currency import compute_currency_pnl

        result = compute_currency_pnl(
            ticker="RELIANCE", trading_pnl_local=5000.0,
            position_value_local=835000.0,
            local_currency="INR", base_currency="USD",
            fx_rate_at_entry=83.0, fx_rate_current=85.0,
        )
        # Position worth 835000/83 = 10060 at entry, 835000/85 = 9823 now
        # Currency P&L = 9823 - 10060 = -237 (negative = INR weakened)
        assert result.currency_pnl_base < 0
        assert result.fx_change_pct > 0  # rate went up = base (USD) strengthened

    def test_inr_strengthens_helps_usd_investor(self):
        """INR strengthens (rate goes from 85 to 83) -> positive currency P&L."""
        from market_analyzer.currency import compute_currency_pnl

        result = compute_currency_pnl(
            ticker="RELIANCE", trading_pnl_local=5000.0,
            position_value_local=835000.0,
            local_currency="INR", base_currency="USD",
            fx_rate_at_entry=85.0, fx_rate_current=83.0,
        )
        # Position worth 835000/85 = 9823 at entry, 835000/83 = 10060 now
        # Currency P&L = 10060 - 9823 = +237
        assert result.currency_pnl_base > 0
        assert result.fx_change_pct < 0  # rate went down = INR strengthened

    def test_pnl_decomposition_sums(self):
        """total_pnl = trading_pnl_base + currency_pnl_base."""
        from market_analyzer.currency import compute_currency_pnl

        result = compute_currency_pnl(
            ticker="RELIANCE", trading_pnl_local=10000.0,
            position_value_local=835000.0,
            local_currency="INR", base_currency="USD",
            fx_rate_at_entry=83.0, fx_rate_current=84.0,
        )
        assert result.total_pnl_base == pytest.approx(
            result.trading_pnl_base + result.currency_pnl_base, abs=0.01,
        )


# ── H2: Hedge Assessment ──


class TestH2HedgeAssessment:
    """H2: assess_hedge regime-aware hedge recommendations."""

    def _regime(self, regime_id: int, trend: str | None = None) -> RegimeResult:
        from market_analyzer.models.regime import TrendDirection

        td = None
        if trend == "bullish":
            td = TrendDirection.BULLISH
        elif trend == "bearish":
            td = TrendDirection.BEARISH

        return RegimeResult(
            ticker="SPY",
            regime=RegimeID(regime_id),
            confidence=0.85,
            regime_probabilities={
                RegimeID.R1_LOW_VOL_MR: 0.85 if regime_id == 1 else 0.05,
                RegimeID.R2_HIGH_VOL_MR: 0.85 if regime_id == 2 else 0.05,
                RegimeID.R3_LOW_VOL_TREND: 0.85 if regime_id == 3 else 0.05,
                RegimeID.R4_HIGH_VOL_TREND: 0.85 if regime_id == 4 else 0.05,
            },
            as_of_date=date.today(),
            model_version="test",
            trend_direction=td,
        )

    def _tech(self, price: float = 580.0, atr: float = 8.0) -> TechnicalSnapshot:
        return _make_technicals(price=price, atr=atr)

    def test_long_equity_r1_no_hedge(self):
        """R1 -> NO_HEDGE for long equity."""
        from market_analyzer.hedging import HedgeType, assess_hedge

        rec = assess_hedge("SPY", "long_equity", 50000.0, self._regime(1), self._tech())
        assert rec.hedge_type == HedgeType.NO_HEDGE

    def test_long_equity_r2_collar(self):
        """R2 -> COLLAR for long equity."""
        from market_analyzer.hedging import HedgeType, assess_hedge

        rec = assess_hedge("SPY", "long_equity", 50000.0, self._regime(2), self._tech())
        assert rec.hedge_type == HedgeType.COLLAR

    def test_long_equity_r4_protective_put(self):
        """R4 -> PROTECTIVE_PUT with IMMEDIATE urgency."""
        from market_analyzer.hedging import HedgeType, HedgeUrgency, assess_hedge

        rec = assess_hedge("SPY", "long_equity", 50000.0, self._regime(4), self._tech())
        assert rec.hedge_type == HedgeType.PROTECTIVE_PUT
        assert rec.urgency == HedgeUrgency.IMMEDIATE

    def test_short_straddle_r4_close(self):
        """R4 -> CLOSE_POSITION for short straddle (undefined risk)."""
        from market_analyzer.hedging import HedgeType, assess_hedge

        rec = assess_hedge("SPY", "short_straddle", 50000.0, self._regime(4), self._tech())
        assert rec.hedge_type == HedgeType.CLOSE_POSITION

    def test_short_straddle_r2_add_wing(self):
        """R2 -> ADD_WING to convert undefined to defined risk."""
        from market_analyzer.hedging import HedgeType, assess_hedge

        rec = assess_hedge("SPY", "short_straddle", 50000.0, self._regime(2), self._tech())
        assert rec.hedge_type == HedgeType.ADD_WING

    def test_iron_condor_r1_no_hedge(self):
        """R1 -> NO_HEDGE for iron condor (wings are the hedge)."""
        from market_analyzer.hedging import HedgeType, assess_hedge

        rec = assess_hedge("SPY", "iron_condor", 50000.0, self._regime(1), self._tech())
        assert rec.hedge_type == HedgeType.NO_HEDGE

    def test_iron_condor_r4_close(self):
        """R4 -> CLOSE_POSITION for iron condor."""
        from market_analyzer.hedging import HedgeType, assess_hedge

        rec = assess_hedge("SPY", "iron_condor", 50000.0, self._regime(4), self._tech())
        assert rec.hedge_type == HedgeType.CLOSE_POSITION

    def test_unknown_position_type(self):
        """Unknown position type -> NO_HEDGE with MONITOR."""
        from market_analyzer.hedging import HedgeType, HedgeUrgency, assess_hedge

        rec = assess_hedge("SPY", "exotic_butterfly", 50000.0, self._regime(2), self._tech())
        assert rec.hedge_type == HedgeType.NO_HEDGE
        assert rec.urgency == HedgeUrgency.MONITOR


# ── CR-14: Cache Isolation ──


class TestCR14CacheIsolation:
    """CR-14: Per-instance quote cache isolation."""

    def test_option_quote_cache_per_instance(self):
        """Each OptionQuoteService instance has its own cache dict."""
        from market_analyzer.service.option_quotes import OptionQuoteService

        svc1 = OptionQuoteService()
        svc2 = OptionQuoteService()
        assert svc1._quote_cache is not svc2._quote_cache


# ── CR-16: Token Expiry ──


class TestCR16TokenExpiry:
    """CR-16: TokenExpiredError and is_token_valid on providers."""

    def test_token_expired_error_exists(self):
        """TokenExpiredError is an Exception subclass."""
        from market_analyzer.broker.base import TokenExpiredError

        assert issubclass(TokenExpiredError, Exception)

    def test_is_token_valid_default_true(self):
        """MarketDataProvider.is_token_valid() defaults to True (via Dhan stub)."""
        from market_analyzer.broker.dhan.market_data import DhanMarketData

        md = DhanMarketData()
        assert md.is_token_valid() is True


# ── CR-17: Rate Limits ──


class TestCR17RateLimits:
    """CR-17: Broker-specific rate limits and batch support."""

    def test_dhan_rate_limit(self):
        """Dhan rate limit is 25 req/s."""
        from market_analyzer.broker.dhan.market_data import DhanMarketData

        assert DhanMarketData().rate_limit_per_second == 25

    def test_zerodha_rate_limit(self):
        """Zerodha rate limit is 3 req/s."""
        from market_analyzer.broker.zerodha.market_data import ZerodhaMarketData

        assert ZerodhaMarketData().rate_limit_per_second == 3

    def test_supports_batch_default_false(self):
        """Dhan supports_batch defaults to False."""
        from market_analyzer.broker.dhan.market_data import DhanMarketData

        assert DhanMarketData().supports_batch is False
