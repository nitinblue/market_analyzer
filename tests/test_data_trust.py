"""Tests for data trust framework."""
import pytest
from market_analyzer.models.transparency import (
    DataSource,
    DataTrust,
    DegradedField,
    TrustLevel,
)
from market_analyzer.features.data_trust import compute_data_trust


class TestDataTrustModel:
    def test_high_trust(self):
        t = DataTrust.from_score(0.90, DataSource.BROKER_LIVE)
        assert t.trust_level == TrustLevel.HIGH
        assert t.trust_score == 0.90

    def test_medium_trust(self):
        t = DataTrust.from_score(0.65, DataSource.YFINANCE_LIVE)
        assert t.trust_level == TrustLevel.MEDIUM

    def test_low_trust(self):
        t = DataTrust.from_score(0.35, DataSource.ESTIMATED)
        assert t.trust_level == TrustLevel.LOW

    def test_unreliable(self):
        t = DataTrust.from_score(0.10, DataSource.NONE)
        assert t.trust_level == TrustLevel.UNRELIABLE

    def test_clamped_to_0_1(self):
        t = DataTrust.from_score(1.5, DataSource.BROKER_LIVE)
        assert t.trust_score == 1.0
        t2 = DataTrust.from_score(-0.5, DataSource.NONE)
        assert t2.trust_score == 0.0

    def test_degraded_fields_in_summary(self):
        t = DataTrust.from_score(0.40, DataSource.ESTIMATED, [
            DegradedField(field="iv_rank", source=DataSource.NONE, reason="missing"),
        ])
        assert "iv_rank" in t.summary

    def test_serialization(self):
        t = DataTrust.from_score(0.85, DataSource.BROKER_LIVE)
        d = t.model_dump()
        assert "trust_score" in d
        assert "trust_level" in d

    def test_boundary_high_at_080(self):
        t = DataTrust.from_score(0.80, DataSource.BROKER_LIVE)
        assert t.trust_level == TrustLevel.HIGH

    def test_boundary_medium_at_050(self):
        t = DataTrust.from_score(0.50, DataSource.YFINANCE_LIVE)
        assert t.trust_level == TrustLevel.MEDIUM

    def test_boundary_low_at_020(self):
        t = DataTrust.from_score(0.20, DataSource.ESTIMATED)
        assert t.trust_level == TrustLevel.LOW

    def test_boundary_unreliable_below_020(self):
        t = DataTrust.from_score(0.19, DataSource.NONE)
        assert t.trust_level == TrustLevel.UNRELIABLE

    def test_no_degraded_summary_shows_source(self):
        t = DataTrust.from_score(0.85, DataSource.BROKER_LIVE)
        assert "broker_live" in t.summary

    def test_multiple_degraded_fields_truncated_at_3(self):
        fields = [
            DegradedField(field=f"field_{i}", source=DataSource.NONE, reason="missing")
            for i in range(5)
        ]
        t = DataTrust.from_score(0.30, DataSource.YFINANCE_LIVE, fields)
        # Summary should mention count, not list all 5
        assert "5 field(s) degraded" in t.summary
        # Only first 3 appear in the summary name list
        assert "field_3" not in t.summary
        assert "field_4" not in t.summary

    def test_primary_source_stored(self):
        t = DataTrust.from_score(0.70, DataSource.YFINANCE_CACHED)
        assert t.primary_source == DataSource.YFINANCE_CACHED

    def test_score_rounded_to_2dp(self):
        t = DataTrust.from_score(0.8333, DataSource.BROKER_LIVE)
        assert t.trust_score == 0.83


class TestComputeDataTrust:
    def test_full_broker_high_trust(self):
        """All data available from broker → high trust."""
        t = compute_data_trust(
            has_broker=True,
            has_iv_rank=True,
            has_vol_surface=True,
            has_levels=True,
            has_fundamentals=True,
            entry_credit_source="broker",
            regime_confidence=0.95,
        )
        assert t.trust_level == TrustLevel.HIGH
        assert t.trust_score >= 0.85
        assert len(t.degraded_fields) == 0

    def test_no_broker_medium_trust(self):
        """No broker but good yfinance data → medium or low trust."""
        t = compute_data_trust(
            has_broker=False,
            has_iv_rank=False,
            has_vol_surface=True,
            has_levels=True,
            has_fundamentals=True,
            entry_credit_source="estimated",
            regime_confidence=0.90,
        )
        assert t.trust_level in (TrustLevel.MEDIUM, TrustLevel.LOW)
        assert any(d.field == "option_quotes" for d in t.degraded_fields)

    def test_nothing_available_unreliable(self):
        """Minimal data → low/unreliable trust."""
        t = compute_data_trust(
            has_broker=False,
            has_iv_rank=False,
            has_vol_surface=False,
            has_levels=False,
            has_fundamentals=False,
            entry_credit_source="none",
            regime_confidence=0.40,
        )
        assert t.trust_score < 0.30
        assert len(t.degraded_fields) >= 3

    def test_broker_without_iv_rank_still_good(self):
        """Broker connected but IV rank missing → still decent."""
        t = compute_data_trust(
            has_broker=True,
            has_iv_rank=False,
            has_vol_surface=True,
            entry_credit_source="broker",
            regime_confidence=0.85,
        )
        assert t.trust_score >= 0.70

    def test_low_regime_confidence_penalized(self):
        """Regime confidence < 60% reduces trust."""
        high = compute_data_trust(regime_confidence=0.90)
        low = compute_data_trust(regime_confidence=0.50)
        assert high.trust_score > low.trust_score

    def test_data_gaps_reduce_trust(self):
        """Each data gap subtracts from trust."""
        from market_analyzer.models.transparency import DataGap
        gaps = [DataGap(field="x", reason="missing", impact="high") for _ in range(3)]
        no_gaps = compute_data_trust(has_broker=True, regime_confidence=0.90)
        with_gaps = compute_data_trust(has_broker=True, regime_confidence=0.90, data_gaps=gaps)
        assert with_gaps.trust_score < no_gaps.trust_score

    def test_estimated_credit_partial_score(self):
        """Estimated credit gets partial credit, not full."""
        broker_credit = compute_data_trust(entry_credit_source="broker")
        estimated = compute_data_trust(entry_credit_source="estimated")
        none_credit = compute_data_trust(entry_credit_source="none")
        assert broker_credit.trust_score > estimated.trust_score > none_credit.trust_score

    def test_primary_source_reflects_broker(self):
        t = compute_data_trust(has_broker=True)
        assert t.primary_source == DataSource.BROKER_LIVE
        t2 = compute_data_trust(has_broker=False)
        assert t2.primary_source == DataSource.YFINANCE_LIVE

    def test_base_score_is_yfinance(self):
        """Default call (no flags) → yfinance base, low/unreliable trust."""
        t = compute_data_trust()
        assert t.primary_source == DataSource.YFINANCE_LIVE
        # Base 0.30 - 0.10 regime penalty + 0.03 estimated credit = 0.23
        assert t.trust_score < 0.40

    def test_max_gap_penalty_capped_at_015(self):
        """Gap penalty is capped at 0.15 regardless of gap count."""
        from market_analyzer.models.transparency import DataGap
        many_gaps = [DataGap(field=f"g{i}", reason="r", impact="h") for i in range(10)]
        few_gaps = [DataGap(field=f"g{i}", reason="r", impact="h") for i in range(3)]
        t_many = compute_data_trust(has_broker=True, regime_confidence=0.90, data_gaps=many_gaps)
        t_few = compute_data_trust(has_broker=True, regime_confidence=0.90, data_gaps=few_gaps)
        # Both penalized, but many_gaps shouldn't be worse by more than 0.15 total
        base = compute_data_trust(has_broker=True, regime_confidence=0.90)
        assert base.trust_score - t_many.trust_score <= 0.16  # <=0.15 cap + rounding

    def test_regime_confidence_exactly_060_no_penalty(self):
        """Regime confidence at exactly 60% should NOT trigger penalty."""
        penalized = compute_data_trust(regime_confidence=0.59)
        not_penalized = compute_data_trust(regime_confidence=0.60)
        assert not_penalized.trust_score > penalized.trust_score

    def test_levels_and_fundamentals_add_score(self):
        base = compute_data_trust(has_broker=True, regime_confidence=0.80)
        with_extras = compute_data_trust(
            has_broker=True, has_levels=True, has_fundamentals=True, regime_confidence=0.80
        )
        assert with_extras.trust_score > base.trust_score

    def test_no_broker_option_quotes_in_degraded(self):
        t = compute_data_trust(has_broker=False)
        fields = [d.field for d in t.degraded_fields]
        assert "option_quotes" in fields

    def test_no_iv_rank_in_degraded(self):
        t = compute_data_trust(has_iv_rank=False)
        fields = [d.field for d in t.degraded_fields]
        assert "iv_rank" in fields

    def test_no_vol_surface_in_degraded(self):
        t = compute_data_trust(has_vol_surface=False)
        fields = [d.field for d in t.degraded_fields]
        assert "vol_surface" in fields

    def test_estimated_credit_in_degraded(self):
        t = compute_data_trust(entry_credit_source="estimated")
        fields = [d.field for d in t.degraded_fields]
        assert "entry_credit" in fields

    def test_none_credit_in_degraded(self):
        t = compute_data_trust(entry_credit_source="none")
        fields = [d.field for d in t.degraded_fields]
        assert "entry_credit" in fields

    def test_broker_credit_not_in_degraded(self):
        t = compute_data_trust(has_broker=True, entry_credit_source="broker")
        fields = [d.field for d in t.degraded_fields]
        assert "entry_credit" not in fields

    def test_full_broker_no_degraded_fields(self):
        t = compute_data_trust(
            has_broker=True,
            has_iv_rank=True,
            has_vol_surface=True,
            has_levels=True,
            has_fundamentals=True,
            entry_credit_source="broker",
            regime_confidence=0.95,
        )
        assert t.degraded_fields == []

    def test_trust_score_always_in_range(self):
        """Trust score must always be in [0.0, 1.0]."""
        for regime_conf in [0.0, 0.3, 0.6, 0.9, 1.0]:
            t = compute_data_trust(regime_confidence=regime_conf)
            assert 0.0 <= t.trust_score <= 1.0


from market_analyzer.models.transparency import ContextGap, TrustReport
from market_analyzer.features.data_trust import compute_context_quality, compute_trust_report


class TestContextQuality:
    def test_full_context_high(self):
        score, level, gaps = compute_context_quality(
            has_levels=True, has_iv_rank=True, has_vol_surface=True,
            has_fundamentals=True, has_days_to_earnings=True,
            has_entry_credit=True, has_regime=True, has_technicals=True,
            has_ticker_type=True, has_correlation_data=True,
            has_portfolio_exposure=True,
        )
        assert level == TrustLevel.HIGH
        assert score >= 0.90
        assert len(gaps) == 0

    def test_minimal_context_low(self):
        score, level, gaps = compute_context_quality(
            has_regime=True, has_technicals=True,
        )
        assert level == TrustLevel.LOW
        assert score < 0.50
        assert len(gaps) >= 3

    def test_no_regime_critical_gap(self):
        score, level, gaps = compute_context_quality(has_regime=False, has_technicals=True)
        critical = [g for g in gaps if g.importance == "critical"]
        assert any(g.parameter == "regime" for g in critical)

    def test_missing_levels_important_gap(self):
        score, level, gaps = compute_context_quality(
            has_regime=True, has_technicals=True, has_levels=False,
        )
        important = [g for g in gaps if g.importance == "important"]
        assert any(g.parameter == "levels" for g in important)

    def test_no_entry_credit_critical(self):
        score, level, gaps = compute_context_quality(
            has_regime=True, has_technicals=True, has_entry_credit=False,
        )
        critical = [g for g in gaps if g.importance == "critical"]
        assert any(g.parameter == "entry_credit" for g in critical)


class TestTrustReport:
    def test_full_trust_report_high(self):
        report = compute_trust_report(
            has_broker=True, has_iv_rank=True, has_vol_surface=True,
            has_levels=True, has_fundamentals=True,
            entry_credit_source="broker", regime_confidence=0.95,
            has_days_to_earnings=True, has_entry_credit=True,
            has_ticker_type=True, has_correlation_data=True,
            has_portfolio_exposure=True,
        )
        assert report.overall_level == TrustLevel.HIGH
        assert report.is_actionable is True
        assert report.overall_trust >= 0.80

    def test_good_data_bad_context(self):
        """Broker connected but caller didn't pass levels/IV rank/credit."""
        report = compute_trust_report(
            has_broker=True, regime_confidence=0.90,
            has_iv_rank=False, has_vol_surface=False, has_levels=False,
            has_entry_credit=False,
        )
        # Data is good (broker), context is poor (missing inputs)
        assert report.data_quality.trust_level in (TrustLevel.HIGH, TrustLevel.MEDIUM)
        assert report.context_level in (TrustLevel.LOW, TrustLevel.MEDIUM)
        # Overall limited by weaker dimension
        assert report.overall_trust <= report.data_quality.trust_score

    def test_bad_data_good_context(self):
        """No broker but caller passed everything they could."""
        report = compute_trust_report(
            has_broker=False, regime_confidence=0.90,
            has_iv_rank=False, has_vol_surface=True, has_levels=True,
            has_fundamentals=True, has_days_to_earnings=True,
            has_entry_credit=True, entry_credit_source="estimated",
            has_ticker_type=True,
        )
        # Context is decent, data is limited
        assert report.overall_trust <= report.data_quality.trust_score

    def test_is_actionable_threshold(self):
        """Trust >= 0.50 is actionable."""
        good = compute_trust_report(
            has_broker=True, has_iv_rank=True, has_vol_surface=True,
            has_entry_credit=True, entry_credit_source="broker",
            regime_confidence=0.90,
        )
        assert good.is_actionable is True

        bad = compute_trust_report(has_broker=False, regime_confidence=0.40)
        assert bad.is_actionable is False

    def test_summary_shows_both_dimensions(self):
        report = compute_trust_report(has_broker=True, regime_confidence=0.90)
        assert "Data:" in report.summary
        assert "Context:" in report.summary

    def test_summary_shows_critical_missing(self):
        report = compute_trust_report(
            has_broker=False, regime_confidence=0.90,
            has_entry_credit=False,
        )
        assert "MISSING" in report.summary

    def test_serialization(self):
        report = compute_trust_report(has_broker=True, regime_confidence=0.90)
        d = report.model_dump()
        assert "data_quality" in d
        assert "context_score" in d
        assert "overall_trust" in d
        assert "context_gaps" in d


from market_analyzer.models.transparency import CalculationMode


class TestCalculationModes:
    def test_full_mode_penalizes_missing_portfolio(self):
        """Full mode: missing correlation/exposure are absent from score."""
        report = compute_trust_report(
            mode="full",
            has_broker=True, has_iv_rank=True, has_vol_surface=True,
            has_levels=True, has_entry_credit=True,
            entry_credit_source="broker", regime_confidence=0.90,
            has_correlation_data=False, has_portfolio_exposure=False,
        )
        # Portfolio context missing in full mode — these points are not awarded
        # so the report is not perfect even with most inputs present
        assert report.context_score < 1.0

    def test_standalone_mode_ignores_portfolio(self):
        """Standalone mode: missing correlation/exposure is expected."""
        full = compute_trust_report(
            mode="full",
            has_broker=True, has_iv_rank=True, regime_confidence=0.90,
            has_correlation_data=False, has_portfolio_exposure=False,
        )
        standalone = compute_trust_report(
            mode="standalone",
            has_broker=True, has_iv_rank=True, regime_confidence=0.90,
            has_correlation_data=False, has_portfolio_exposure=False,
        )
        # Standalone should have equal or higher context score
        assert standalone.context_score >= full.context_score

    def test_standalone_still_requires_regime(self):
        """Even standalone needs regime — it's fundamental."""
        report = compute_trust_report(
            mode="standalone", has_regime=False,
        )
        critical = [g for g in report.context_gaps if g.importance == "critical"]
        assert any(g.parameter == "regime" for g in critical)

    def test_standalone_still_requires_entry_credit(self):
        """Standalone still needs entry credit for POP/EV."""
        report = compute_trust_report(
            mode="standalone", has_entry_credit=False,
        )
        critical = [g for g in report.context_gaps if g.importance == "critical"]
        assert any(g.parameter == "entry_credit" for g in critical)

    def test_full_mode_is_default(self):
        """Default mode is full — portfolio gaps are counted."""
        report_default = compute_trust_report(
            has_broker=True, regime_confidence=0.90,
            has_correlation_data=False, has_portfolio_exposure=False,
        )
        report_full = compute_trust_report(
            mode="full",
            has_broker=True, regime_confidence=0.90,
            has_correlation_data=False, has_portfolio_exposure=False,
        )
        # Default and explicit full should be identical
        assert report_default.context_score == report_full.context_score

    def test_full_mode_with_everything_high_trust(self):
        """Full mode with all inputs = highest possible trust."""
        report = compute_trust_report(
            mode="full",
            has_broker=True, has_iv_rank=True, has_vol_surface=True,
            has_levels=True, has_fundamentals=True,
            entry_credit_source="broker", regime_confidence=0.95,
            has_days_to_earnings=True, has_entry_credit=True,
            has_ticker_type=True, has_correlation_data=True,
            has_portfolio_exposure=True,
        )
        assert report.overall_level == TrustLevel.HIGH
        assert report.is_actionable is True

    def test_calculation_mode_enum_values(self):
        """CalculationMode enum has correct string values."""
        assert CalculationMode.FULL == "full"
        assert CalculationMode.STANDALONE == "standalone"

    def test_standalone_no_portfolio_gaps(self):
        """Standalone mode produces no gaps for portfolio-level inputs."""
        report = compute_trust_report(
            mode="standalone",
            has_broker=True, has_iv_rank=True, regime_confidence=0.90,
            has_correlation_data=False, has_portfolio_exposure=False,
            has_ticker_type=False,
        )
        portfolio_params = {"correlation_data", "portfolio_exposure", "ticker_type"}
        gap_params = {g.parameter for g in report.context_gaps}
        # None of the portfolio-level params should appear as gaps in standalone
        assert portfolio_params.isdisjoint(gap_params)

    def test_full_mode_context_score_lower_than_standalone_without_portfolio(self):
        """Full mode scores lower than standalone when portfolio context is absent."""
        common_kwargs = dict(
            has_broker=True, has_iv_rank=True, regime_confidence=0.90,
            has_correlation_data=False, has_portfolio_exposure=False,
            has_ticker_type=False,
        )
        full = compute_trust_report(mode="full", **common_kwargs)
        standalone = compute_trust_report(mode="standalone", **common_kwargs)
        # Standalone treats portfolio params as present (+0.07 total)
        assert standalone.context_score > full.context_score


from market_analyzer.models.transparency import FitnessCategory


class TestFitnessForPurpose:
    def test_high_trust_fit_for_everything(self):
        report = compute_trust_report(
            has_broker=True, has_iv_rank=True, has_vol_surface=True,
            has_levels=True, has_fundamentals=True,
            entry_credit_source="broker", regime_confidence=0.95,
            has_days_to_earnings=True, has_entry_credit=True,
            has_ticker_type=True, has_correlation_data=True,
            has_portfolio_exposure=True,
        )
        assert "live_execution" in report.fit_for
        assert "ALL purposes" in report.fit_for_summary

    def test_medium_trust_fit_for_screening(self):
        report = compute_trust_report(
            has_broker=False, has_vol_surface=True,
            regime_confidence=0.90,
        )
        assert "screening" in report.fit_for
        assert "live_execution" not in report.fit_for

    def test_low_trust_research_only(self):
        report = compute_trust_report(
            has_broker=False, regime_confidence=0.40,
        )
        assert "research" in report.fit_for or "education" in report.fit_for
        assert "live_execution" not in report.fit_for
        assert "position_monitoring" not in report.fit_for

    def test_education_always_included(self):
        report = compute_trust_report()  # Minimal
        assert "education" in report.fit_for

    def test_fit_for_serializes(self):
        report = compute_trust_report(has_broker=True, regime_confidence=0.90)
        d = report.model_dump()
        assert "fit_for" in d
        assert "fit_for_summary" in d
        assert isinstance(d["fit_for"], list)

    def test_not_fit_for_mentioned_in_summary(self):
        report = compute_trust_report(has_broker=False, regime_confidence=0.90)
        # Should mention what it's NOT fit for or at least what it IS fit for
        assert "NOT fit for" in report.fit_for_summary or "Fit for" in report.fit_for_summary

    def test_journaling_always_included(self):
        report = compute_trust_report()
        assert "journaling" in report.fit_for

    def test_fit_for_threshold_live_execution_at_080(self):
        """live_execution only appears at >= 0.80 overall trust."""
        # Build a report that barely hits 0.80 — full broker + all context
        high_report = compute_trust_report(
            has_broker=True, has_iv_rank=True, has_vol_surface=True,
            has_levels=True, has_fundamentals=True,
            entry_credit_source="broker", regime_confidence=0.95,
            has_days_to_earnings=True, has_entry_credit=True,
            has_ticker_type=True, has_correlation_data=True,
            has_portfolio_exposure=True,
        )
        assert "live_execution" in high_report.fit_for

        # No broker → data trust ~0.33, overall < 0.80
        low_report = compute_trust_report(has_broker=False, regime_confidence=0.90)
        assert "live_execution" not in low_report.fit_for

    def test_fit_for_ordering_progressive(self):
        """Higher trust reports are supersets of lower trust reports."""
        low_report = compute_trust_report(has_broker=False, regime_confidence=0.40)
        med_report = compute_trust_report(has_broker=False, has_vol_surface=True,
                                          regime_confidence=0.90)
        # med should have at least as many categories as low
        assert len(med_report.fit_for) >= len(low_report.fit_for)

    def test_summary_fitness_in_trust_report_summary(self):
        """compute_trust_report() summary string includes fitness hint."""
        report = compute_trust_report(
            has_broker=True, has_iv_rank=True, has_vol_surface=True,
            entry_credit_source="broker", regime_confidence=0.90,
            has_entry_credit=True,
        )
        assert "Fit for:" in report.summary
