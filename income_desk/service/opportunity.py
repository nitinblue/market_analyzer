"""OpportunityService: option plays + setup assessment."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

from income_desk.models.opportunity import (
    BreakoutOpportunity,
    LEAPOpportunity,
    MomentumOpportunity,
    ZeroDTEOpportunity,
)

if TYPE_CHECKING:
    from income_desk.data.service import DataService
    from income_desk.models.chain import ChainContext
    from income_desk.models.vol_surface import VolatilitySurface
    from income_desk.service.fundamental import FundamentalService
    from income_desk.service.macro import MacroService
    from income_desk.service.phase import PhaseService
    from income_desk.service.regime import RegimeService
    from income_desk.service.technical import TechnicalService
    from income_desk.service.vol_surface import VolSurfaceService


class OpportunityService:
    """Assess trading opportunities across multiple time horizons."""

    def __init__(
        self,
        regime_service: RegimeService | None = None,
        technical_service: TechnicalService | None = None,
        phase_service: PhaseService | None = None,
        fundamental_service: FundamentalService | None = None,
        macro_service: MacroService | None = None,
        data_service: DataService | None = None,
        vol_surface_service: VolSurfaceService | None = None,
    ) -> None:
        self.regime_service = regime_service
        self.technical_service = technical_service
        self.phase_service = phase_service
        self.fundamental_service = fundamental_service
        self.macro_service = macro_service
        self.data_service = data_service
        self.vol_surface_service = vol_surface_service

    def _get_ohlcv(self, ticker: str, ohlcv: pd.DataFrame | None) -> pd.DataFrame:
        if ohlcv is not None:
            return ohlcv
        if self.data_service is None:
            raise ValueError(
                "Either provide ohlcv DataFrame or initialize OpportunityService with a DataService"
            )
        return self.data_service.get_ohlcv(ticker)

    def _get_fundamentals(self, ticker: str):
        """Best-effort fundamentals fetch (None on failure)."""
        if self.fundamental_service is None:
            return None
        try:
            return self.fundamental_service.get(ticker)
        except Exception:
            return None

    def assess_zero_dte(
        self,
        ticker: str,
        ohlcv: pd.DataFrame | None = None,
        intraday: pd.DataFrame | None = None,
        as_of: date | None = None,
        vol_surface: VolatilitySurface | None = None,
        chain: ChainContext | None = None,
    ) -> ZeroDTEOpportunity:
        """Assess 0DTE opportunity for a single instrument."""
        from income_desk.opportunity.option_plays.zero_dte import assess_zero_dte as _assess

        if self.regime_service is None or self.technical_service is None:
            raise ValueError("OpportunityService requires regime and technical services")
        if self.macro_service is None:
            raise ValueError("OpportunityService requires macro service")

        df = self._get_ohlcv(ticker, ohlcv)
        regime = self.regime_service.detect(ticker, df)
        technicals = self.technical_service.snapshot(ticker, df)
        macro = self.macro_service.calendar(as_of=as_of)

        orb = None
        if self.technical_service is not None:
            try:
                orb = self.technical_service.orb(
                    ticker, intraday=intraday, daily_atr=technicals.atr,
                )
            except Exception:
                pass  # ORB is optional; don't fail 0DTE assessment over it

        fundamentals = self._get_fundamentals(ticker)
        vol_surface = self._get_vol_surface(ticker, provided=vol_surface)

        return _assess(
            ticker=ticker,
            regime=regime,
            technicals=technicals,
            macro=macro,
            fundamentals=fundamentals,
            orb=orb,
            vol_surface=vol_surface,
            as_of=as_of,
        )

    def assess_leap(
        self,
        ticker: str,
        ohlcv: pd.DataFrame | None = None,
        as_of: date | None = None,
        iv_rank: float | None = None,
        vol_surface: VolatilitySurface | None = None,
        chain: ChainContext | None = None,
    ) -> LEAPOpportunity:
        """Assess LEAP opportunity for a single instrument."""
        from income_desk.opportunity.option_plays.leap import assess_leap as _assess

        if self.regime_service is None or self.technical_service is None:
            raise ValueError("OpportunityService requires regime and technical services")
        if self.phase_service is None or self.macro_service is None:
            raise ValueError("OpportunityService requires phase and macro services")

        df = self._get_ohlcv(ticker, ohlcv)
        regime = self.regime_service.detect(ticker, df)
        technicals = self.technical_service.snapshot(ticker, df)
        phase = self.phase_service.detect(ticker, df)
        macro = self.macro_service.calendar(as_of=as_of)
        fundamentals = self._get_fundamentals(ticker)
        vol_surface = self._get_vol_surface(ticker, provided=vol_surface)

        return _assess(
            ticker=ticker,
            regime=regime,
            technicals=technicals,
            phase=phase,
            macro=macro,
            fundamentals=fundamentals,
            vol_surface=vol_surface,
            as_of=as_of,
            iv_rank=iv_rank,
        )

    def assess_breakout(
        self,
        ticker: str,
        ohlcv: pd.DataFrame | None = None,
        as_of: date | None = None,
        vol_surface: VolatilitySurface | None = None,
        chain: ChainContext | None = None,
    ) -> BreakoutOpportunity:
        """Assess breakout opportunity for a single instrument."""
        from income_desk.opportunity.setups.breakout import assess_breakout as _assess

        if self.regime_service is None or self.technical_service is None:
            raise ValueError("OpportunityService requires regime and technical services")
        if self.phase_service is None or self.macro_service is None:
            raise ValueError("OpportunityService requires phase and macro services")

        df = self._get_ohlcv(ticker, ohlcv)
        regime = self.regime_service.detect(ticker, df)
        technicals = self.technical_service.snapshot(ticker, df)
        phase = self.phase_service.detect(ticker, df)
        macro = self.macro_service.calendar(as_of=as_of)
        fundamentals = self._get_fundamentals(ticker)
        vol_surface = self._get_vol_surface(ticker, provided=vol_surface)

        return _assess(
            ticker=ticker,
            regime=regime,
            technicals=technicals,
            phase=phase,
            macro=macro,
            fundamentals=fundamentals,
            vol_surface=vol_surface,
            as_of=as_of,
        )

    def assess_momentum(
        self,
        ticker: str,
        ohlcv: pd.DataFrame | None = None,
        as_of: date | None = None,
        vol_surface: VolatilitySurface | None = None,
        chain: ChainContext | None = None,
    ) -> MomentumOpportunity:
        """Assess momentum opportunity for a single instrument."""
        from income_desk.opportunity.setups.momentum import assess_momentum as _assess

        if self.regime_service is None or self.technical_service is None:
            raise ValueError("OpportunityService requires regime and technical services")
        if self.phase_service is None or self.macro_service is None:
            raise ValueError("OpportunityService requires phase and macro services")

        df = self._get_ohlcv(ticker, ohlcv)
        regime = self.regime_service.detect(ticker, df)
        technicals = self.technical_service.snapshot(ticker, df)
        phase = self.phase_service.detect(ticker, df)
        macro = self.macro_service.calendar(as_of=as_of)
        fundamentals = self._get_fundamentals(ticker)
        vol_surface = self._get_vol_surface(ticker, provided=vol_surface)

        return _assess(
            ticker=ticker,
            regime=regime,
            technicals=technicals,
            phase=phase,
            macro=macro,
            fundamentals=fundamentals,
            vol_surface=vol_surface,
            as_of=as_of,
        )

    def assess_orb(
        self,
        ticker: str,
        intraday: pd.DataFrame,
        ohlcv: pd.DataFrame | None = None,
        as_of: date | None = None,
        vol_surface: VolatilitySurface | None = None,
        chain: ChainContext | None = None,
    ):
        """Assess ORB setup opportunity (requires intraday data)."""
        from income_desk.opportunity.setups.orb import assess_orb as _assess

        if self.regime_service is None or self.technical_service is None:
            raise ValueError("OpportunityService requires regime and technical services")

        df = self._get_ohlcv(ticker, ohlcv)
        regime = self.regime_service.detect(ticker, df)
        technicals = self.technical_service.snapshot(ticker, df)

        orb = self.technical_service.orb(
            ticker, intraday=intraday, daily_atr=technicals.atr
        )

        phase = None
        if self.phase_service is not None:
            phase = self.phase_service.detect(ticker, df)

        macro = None
        if self.macro_service is not None:
            macro = self.macro_service.calendar(as_of=as_of)

        fundamentals = self._get_fundamentals(ticker)
        vol_surface = self._get_vol_surface(ticker, provided=vol_surface)

        return _assess(
            ticker=ticker,
            regime=regime,
            technicals=technicals,
            orb=orb,
            phase=phase,
            macro=macro,
            fundamentals=fundamentals,
            vol_surface=vol_surface,
            as_of=as_of,
        )

    def assess_earnings(
        self,
        ticker: str,
        ohlcv: pd.DataFrame | None = None,
        as_of: date | None = None,
        iv_rank: float | None = None,
        vol_surface: VolatilitySurface | None = None,
        chain: ChainContext | None = None,
    ):
        """Assess earnings play opportunity."""
        from income_desk.opportunity.option_plays.earnings import assess_earnings_play as _assess

        if self.regime_service is None or self.technical_service is None:
            raise ValueError("OpportunityService requires regime and technical services")

        df = self._get_ohlcv(ticker, ohlcv)
        regime = self.regime_service.detect(ticker, df)
        technicals = self.technical_service.snapshot(ticker, df)
        fundamentals = self._get_fundamentals(ticker)
        vol_surface = self._get_vol_surface(ticker, provided=vol_surface)

        return _assess(
            ticker=ticker, regime=regime, technicals=technicals,
            fundamentals=fundamentals, vol_surface=vol_surface, as_of=as_of,
            iv_rank=iv_rank,
        )

    def assess_mean_reversion(
        self,
        ticker: str,
        ohlcv: pd.DataFrame | None = None,
        as_of: date | None = None,
        vol_surface: VolatilitySurface | None = None,
        chain: ChainContext | None = None,
    ):
        """Assess mean reversion opportunity."""
        from income_desk.opportunity.setups.mean_reversion import assess_mean_reversion as _assess

        if self.regime_service is None or self.technical_service is None:
            raise ValueError("OpportunityService requires regime and technical services")

        df = self._get_ohlcv(ticker, ohlcv)
        regime = self.regime_service.detect(ticker, df)
        technicals = self.technical_service.snapshot(ticker, df)
        phase = self.phase_service.detect(ticker, df) if self.phase_service else None
        macro = self.macro_service.calendar(as_of=as_of) if self.macro_service else None
        fundamentals = self._get_fundamentals(ticker)
        vol_surface = self._get_vol_surface(ticker, provided=vol_surface)

        return _assess(
            ticker=ticker, regime=regime, technicals=technicals,
            phase=phase, macro=macro, fundamentals=fundamentals,
            vol_surface=vol_surface, as_of=as_of,
        )

    # --- Vol-surface-dependent option plays ---

    def _get_vol_surface(self, ticker: str, provided: VolatilitySurface | None = None):
        """Best-effort vol surface fetch (None on failure).

        If *provided* is not None it is returned immediately, skipping
        the network call.
        """
        if provided is not None:
            return provided
        if self.vol_surface_service is None:
            return None
        try:
            return self.vol_surface_service.surface(ticker)
        except Exception:
            return None

    def assess_calendar(
        self,
        ticker: str,
        ohlcv: pd.DataFrame | None = None,
        as_of: date | None = None,
        iv_rank: float | None = None,
        vol_surface: VolatilitySurface | None = None,
        chain: ChainContext | None = None,
    ):
        """Assess calendar spread opportunity."""
        from income_desk.opportunity.option_plays.calendar import assess_calendar as _assess

        if self.regime_service is None or self.technical_service is None:
            raise ValueError("OpportunityService requires regime and technical services")

        df = self._get_ohlcv(ticker, ohlcv)
        regime = self.regime_service.detect(ticker, df)
        technicals = self.technical_service.snapshot(ticker, df)
        fundamentals = self._get_fundamentals(ticker)
        vol_surface = self._get_vol_surface(ticker, provided=vol_surface)

        return _assess(
            ticker=ticker, regime=regime, technicals=technicals,
            vol_surface=vol_surface, fundamentals=fundamentals, as_of=as_of,
            iv_rank=iv_rank,
        )

    def assess_diagonal(
        self,
        ticker: str,
        ohlcv: pd.DataFrame | None = None,
        as_of: date | None = None,
        vol_surface: VolatilitySurface | None = None,
        chain: ChainContext | None = None,
    ):
        """Assess diagonal spread opportunity."""
        from income_desk.opportunity.option_plays.diagonal import assess_diagonal as _assess

        if self.regime_service is None or self.technical_service is None:
            raise ValueError("OpportunityService requires regime and technical services")

        df = self._get_ohlcv(ticker, ohlcv)
        regime = self.regime_service.detect(ticker, df)
        technicals = self.technical_service.snapshot(ticker, df)
        phase = self.phase_service.detect(ticker, df) if self.phase_service else None
        fundamentals = self._get_fundamentals(ticker)
        vol_surface = self._get_vol_surface(ticker, provided=vol_surface)

        return _assess(
            ticker=ticker, regime=regime, technicals=technicals,
            vol_surface=vol_surface, phase=phase, fundamentals=fundamentals, as_of=as_of,
        )

    def assess_iron_condor(
        self,
        ticker: str,
        ohlcv: pd.DataFrame | None = None,
        as_of: date | None = None,
        iv_rank: float | None = None,
        vol_surface: VolatilitySurface | None = None,
        chain: ChainContext | None = None,
    ):
        """Assess iron condor opportunity — the #1 income strategy."""
        from income_desk.opportunity.option_plays.iron_condor import assess_iron_condor as _assess

        if self.regime_service is None or self.technical_service is None:
            raise ValueError("OpportunityService requires regime and technical services")

        df = self._get_ohlcv(ticker, ohlcv)
        regime = self.regime_service.detect(ticker, df)
        technicals = self.technical_service.snapshot(ticker, df)
        fundamentals = self._get_fundamentals(ticker)
        vol_surface = self._get_vol_surface(ticker, provided=vol_surface)

        return _assess(
            ticker=ticker, regime=regime, technicals=technicals,
            vol_surface=vol_surface, fundamentals=fundamentals, as_of=as_of,
            iv_rank=iv_rank,
        )

    def assess_iron_butterfly(
        self,
        ticker: str,
        ohlcv: pd.DataFrame | None = None,
        as_of: date | None = None,
        iv_rank: float | None = None,
        vol_surface: VolatilitySurface | None = None,
        chain: ChainContext | None = None,
    ):
        """Assess iron butterfly opportunity."""
        from income_desk.opportunity.option_plays.iron_butterfly import assess_iron_butterfly as _assess

        if self.regime_service is None or self.technical_service is None:
            raise ValueError("OpportunityService requires regime and technical services")

        df = self._get_ohlcv(ticker, ohlcv)
        regime = self.regime_service.detect(ticker, df)
        technicals = self.technical_service.snapshot(ticker, df)
        fundamentals = self._get_fundamentals(ticker)
        vol_surface = self._get_vol_surface(ticker, provided=vol_surface)

        return _assess(
            ticker=ticker, regime=regime, technicals=technicals,
            vol_surface=vol_surface, fundamentals=fundamentals, as_of=as_of,
            iv_rank=iv_rank,
        )

    def assess_ratio_spread(
        self,
        ticker: str,
        ohlcv: pd.DataFrame | None = None,
        as_of: date | None = None,
        vol_surface: VolatilitySurface | None = None,
        chain: ChainContext | None = None,
    ):
        """Assess ratio spread opportunity."""
        from income_desk.opportunity.option_plays.ratio_spread import assess_ratio_spread as _assess

        if self.regime_service is None or self.technical_service is None:
            raise ValueError("OpportunityService requires regime and technical services")

        df = self._get_ohlcv(ticker, ohlcv)
        regime = self.regime_service.detect(ticker, df)
        technicals = self.technical_service.snapshot(ticker, df)
        phase = self.phase_service.detect(ticker, df) if self.phase_service else None
        fundamentals = self._get_fundamentals(ticker)
        vol_surface = self._get_vol_surface(ticker, provided=vol_surface)

        return _assess(
            ticker=ticker, regime=regime, technicals=technicals,
            vol_surface=vol_surface, phase=phase, fundamentals=fundamentals, as_of=as_of,
        )
