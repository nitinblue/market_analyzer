"""MarketAnalyzer: top-level facade composing all services."""

from __future__ import annotations

from typing import TYPE_CHECKING

from income_desk.models.regime import RegimeConfig
from income_desk.service.fundamental import FundamentalService
from income_desk.service.levels import LevelsService
from income_desk.service.macro import MacroService
from income_desk.service.opportunity import OpportunityService
from income_desk.service.phase import PhaseService
from income_desk.service.black_swan import BlackSwanService
from income_desk.service.ranking import TradeRankingService
from income_desk.service.regime import RegimeService
from income_desk.service.technical import TechnicalService
from income_desk.service.context import MarketContextService
from income_desk.service.instrument import InstrumentAnalysisService
from income_desk.service.screening import ScreeningService
from income_desk.service.entry import EntryService
from income_desk.service.strategy import StrategyService
from income_desk.service.exit import ExitService
from income_desk.service.vol_surface import VolSurfaceService
from income_desk.service.adjustment import AdjustmentService
from income_desk.service.intraday import IntradayService
from income_desk.service.option_quotes import OptionQuoteService
from income_desk.service.trading_plan import TradingPlanService
from income_desk.service.universe import UniverseService
from income_desk.registry import MarketRegistry

if TYPE_CHECKING:
    from income_desk.broker.base import (
        AccountProvider,
        MarketDataProvider,
        MarketMetricsProvider,
        WatchlistProvider,
    )
    from income_desk.data.service import DataService


class MarketAnalyzer:
    """Top-level facade composing all market analysis services.

    Usage::

        from income_desk import MarketAnalyzer, DataService

        ma = MarketAnalyzer(data_service=DataService())

        # --- Existing APIs ---
        regime = ma.regime.detect("SPY")
        tech = ma.technicals.snapshot("SPY")
        phase = ma.phase.detect("SPY")
        fund = ma.fundamentals.get("SPY")
        macro = ma.macro.calendar()
        bo = ma.opportunity.assess_breakout("SPY")

        # --- NEW workflow APIs ---
        ctx = ma.context.assess()                     # Q1a: Environment safe?
        analysis = ma.instrument.analyze("SPY")       # Q1b: What's the ticker doing?
        candidates = ma.screening.scan(["SPY","GLD"]) # Q1c: Where are setups?
        entry = ma.entry.confirm("SPY", EntryTriggerType.BREAKOUT_CONFIRMED)  # Q2
        params = ma.strategy.select("SPY", regime=r, technicals=t)            # Q3
        exit_plan = ma.exit.plan("SPY", params, entry_price=580.0,            # Q4
                                 regime=r, technicals=t, levels=l)
    """

    def __init__(
        self,
        data_service: DataService | None = None,
        config: RegimeConfig = RegimeConfig(),
        market: str | None = None,
        market_data: MarketDataProvider | None = None,
        market_metrics: MarketMetricsProvider | None = None,
        account_provider: AccountProvider | None = None,
        watchlist_provider: WatchlistProvider | None = None,
    ) -> None:
        self.data = data_service
        self.account_provider = account_provider
        self.registry = MarketRegistry()

        # --- Existing services (unchanged) ---
        self.regime = RegimeService(config=config, data_service=data_service)
        self.technicals = TechnicalService(
            data_service=data_service, market_data=market_data,
        )
        self.phase = PhaseService(
            regime_service=self.regime, data_service=data_service
        )
        self.fundamentals = FundamentalService()
        self.macro = MacroService()
        self.levels = LevelsService(
            technical_service=self.technicals,
            regime_service=self.regime,
            data_service=data_service,
        )
        self.vol_surface = VolSurfaceService(data_service=data_service)
        self.opportunity = OpportunityService(
            regime_service=self.regime,
            technical_service=self.technicals,
            phase_service=self.phase,
            fundamental_service=self.fundamentals,
            macro_service=self.macro,
            data_service=data_service,
            vol_surface_service=self.vol_surface,
        )
        self.black_swan = BlackSwanService(data_service=data_service)
        self.ranking = TradeRankingService(
            opportunity_service=self.opportunity,
            levels_service=self.levels,
            black_swan_service=self.black_swan,
            data_service=data_service,
        )

        # --- NEW workflow services ---
        self.context = MarketContextService(
            regime_service=self.regime,
            macro_service=self.macro,
            black_swan_service=self.black_swan,
            market=market,
        )
        self.instrument = InstrumentAnalysisService(
            regime_service=self.regime,
            technical_service=self.technicals,
            phase_service=self.phase,
            levels_service=self.levels,
            fundamental_service=self.fundamentals,
            opportunity_service=self.opportunity,
            data_service=data_service,
        )
        self.screening = ScreeningService(
            regime_service=self.regime,
            technical_service=self.technicals,
            phase_service=self.phase,
            data_service=data_service,
        )
        self.entry = EntryService(
            technical_service=self.technicals,
            levels_service=self.levels,
            data_service=data_service,
        )
        self.strategy = StrategyService()
        self.exit = ExitService(
            levels_service=self.levels,
            regime_service=self.regime,
        )
        self.quotes = OptionQuoteService(
            market_data=market_data,
            metrics=market_metrics,
            data_service=data_service,
        )
        self.adjustment = AdjustmentService(quote_service=self.quotes)
        self.intraday = IntradayService(
            market_data=market_data,
            market_metrics=market_metrics,
            data_service=data_service,
        )
        self.universe = UniverseService(
            watchlist_provider=watchlist_provider,
            metrics_provider=market_metrics,
        )
        self.plan = TradingPlanService(analyzer=self)
