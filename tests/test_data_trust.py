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
