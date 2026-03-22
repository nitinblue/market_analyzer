"""Tests for MarketAnalyzer facade and new service classes."""

import pandas as pd
import pytest

from income_desk.service.analyzer import MarketAnalyzer
from income_desk.service.technical import TechnicalService
from income_desk.service.phase import PhaseService
from income_desk.service.fundamental import FundamentalService
from income_desk.service.macro import MacroService
from income_desk.service.opportunity import OpportunityService
from income_desk.service.regime import RegimeService
from income_desk.models.regime import RegimeResult
from income_desk.models.technicals import TechnicalSnapshot
from income_desk.models.phase import PhaseResult
from income_desk.models.macro import MacroCalendar


class TestMarketAnalyzerInit:
    def test_facade_creates_all_services(self, tmp_path):
        ma = MarketAnalyzer()
        assert isinstance(ma.regime, RegimeService)
        assert isinstance(ma.technicals, TechnicalService)
        assert isinstance(ma.phase, PhaseService)
        assert isinstance(ma.fundamentals, FundamentalService)
        assert isinstance(ma.macro, MacroService)
        assert isinstance(ma.opportunity, OpportunityService)

    def test_facade_shares_data_service(self, tmp_path):
        from income_desk.data.service import DataService

        ds = DataService()
        ma = MarketAnalyzer(data_service=ds)
        assert ma.data is ds
        assert ma.regime.data_service is ds
        assert ma.technicals.data_service is ds
        assert ma.phase.data_service is ds
        assert ma.opportunity.data_service is ds

    def test_facade_wires_regime_to_phase(self):
        ma = MarketAnalyzer()
        assert ma.phase.regime_service is ma.regime

    def test_facade_wires_all_to_opportunity(self):
        ma = MarketAnalyzer()
        assert ma.opportunity.regime_service is ma.regime
        assert ma.opportunity.technical_service is ma.technicals
        assert ma.opportunity.phase_service is ma.phase
        assert ma.opportunity.fundamental_service is ma.fundamentals
        assert ma.opportunity.macro_service is ma.macro


class TestTechnicalService:
    def test_snapshot_with_ohlcv(self, sample_ohlcv_trending):
        svc = TechnicalService()
        snap = svc.snapshot("TEST", ohlcv=sample_ohlcv_trending)
        assert isinstance(snap, TechnicalSnapshot)
        assert snap.ticker == "TEST"

    def test_snapshot_raises_without_data(self):
        svc = TechnicalService()
        with pytest.raises(ValueError, match="Either provide ohlcv"):
            svc.snapshot("TEST")


class TestPhaseService:
    def test_detect_with_ohlcv(self, sample_ohlcv_mixed, tmp_path):
        from income_desk.service.regime_service import RegimeService as RS

        regime_svc = RS(model_dir=tmp_path / "models")
        phase_svc = PhaseService(regime_service=regime_svc)
        result = phase_svc.detect("TEST", ohlcv=sample_ohlcv_mixed)
        assert isinstance(result, PhaseResult)
        assert result.ticker == "TEST"

    def test_detect_raises_without_regime_service(self, sample_ohlcv_mixed):
        phase_svc = PhaseService()
        with pytest.raises(ValueError, match="requires a RegimeService"):
            phase_svc.detect("TEST", ohlcv=sample_ohlcv_mixed)

    def test_detect_raises_without_data(self):
        phase_svc = PhaseService()
        with pytest.raises(ValueError, match="Either provide ohlcv"):
            phase_svc.detect("TEST")


class TestFundamentalService:
    def test_get_delegates_to_fetch(self, mocker):
        sentinel = object()
        mocker.patch(
            "income_desk.fundamentals.fetch.fetch_fundamentals",
            return_value=sentinel,
        )
        svc = FundamentalService()
        result = svc.get("TEST", ttl_minutes=5)
        assert result is sentinel


class TestMacroService:
    def test_calendar_returns_macro_calendar(self):
        from datetime import date

        svc = MacroService()
        cal = svc.calendar(as_of=date(2026, 3, 1))
        assert isinstance(cal, MacroCalendar)


class TestOpportunityService:
    def test_raises_without_required_services(self):
        svc = OpportunityService()
        with pytest.raises(ValueError, match="requires regime and technical"):
            svc.assess_breakout("TEST")

    def test_raises_without_data(self):
        svc = OpportunityService(
            regime_service=RegimeService(),
            technical_service=TechnicalService(),
            phase_service=PhaseService(),
            macro_service=MacroService(),
        )
        with pytest.raises(ValueError, match="Either provide ohlcv"):
            svc.assess_breakout("TEST")


class TestTopLevelImports:
    def test_market_analyzer_importable(self):
        from income_desk import MarketAnalyzer
        assert MarketAnalyzer is not None

    def test_all_services_importable(self):
        from income_desk import (
            MarketAnalyzer,
            RegimeService,
            TechnicalService,
            PhaseService,
            FundamentalService,
            MacroService,
            OpportunityService,
            DataService,
        )
        assert all(cls is not None for cls in [
            MarketAnalyzer, RegimeService, TechnicalService,
            PhaseService, FundamentalService, MacroService,
            OpportunityService, DataService,
        ])

    def test_regime_service_from_both_paths(self):
        from income_desk.service.regime_service import RegimeService as RS1
        from income_desk.service.regime import RegimeService as RS2
        assert RS1 is RS2


class TestFacadeIntegration:
    def test_regime_detect_via_facade(self, sample_ohlcv_mixed, tmp_path):
        from income_desk.models.regime import RegimeConfig

        ma = MarketAnalyzer(config=RegimeConfig())
        ma.regime.model_dir = tmp_path / "models"
        result = ma.regime.detect("TEST", ohlcv=sample_ohlcv_mixed)
        assert isinstance(result, RegimeResult)

    def test_technicals_via_facade(self, sample_ohlcv_trending):
        ma = MarketAnalyzer()
        snap = ma.technicals.snapshot("TEST", ohlcv=sample_ohlcv_trending)
        assert isinstance(snap, TechnicalSnapshot)

    def test_phase_via_facade(self, sample_ohlcv_mixed, tmp_path):
        ma = MarketAnalyzer()
        ma.regime.model_dir = tmp_path / "models"
        result = ma.phase.detect("TEST", ohlcv=sample_ohlcv_mixed)
        assert isinstance(result, PhaseResult)

    def test_macro_via_facade(self):
        from datetime import date

        ma = MarketAnalyzer()
        cal = ma.macro.calendar(as_of=date(2026, 3, 1))
        assert isinstance(cal, MacroCalendar)
