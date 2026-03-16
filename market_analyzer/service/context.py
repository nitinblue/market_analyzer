"""MarketContextService: environment assessment — is it safe to trade?"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from market_analyzer.config import get_settings
from market_analyzer.models.black_swan import AlertLevel
from market_analyzer.models.context import (
    InstrumentAvailability,
    IntermarketDashboard,
    IntermarketEntry,
    MarketContext,
)
from market_analyzer.models.regime import RegimeID

if TYPE_CHECKING:
    from market_analyzer.service.black_swan import BlackSwanService
    from market_analyzer.service.macro import MacroService
    from market_analyzer.service.regime import RegimeService

logger = logging.getLogger(__name__)


class MarketContextService:
    """Assess overall market environment before trading.

    Combines macro calendar, tail-risk (black swan), and intermarket
    regime reads to produce an environment label and trading gate.
    """

    def __init__(
        self,
        regime_service: RegimeService | None = None,
        macro_service: MacroService | None = None,
        black_swan_service: BlackSwanService | None = None,
        market: str | None = None,
    ) -> None:
        self.regime_service = regime_service
        self.macro_service = macro_service
        self.black_swan_service = black_swan_service
        self._market = market or get_settings().markets.default_market

    def assess(self, as_of: date | None = None, debug: bool = False) -> MarketContext:
        """Produce a complete market environment assessment.

        Raises ValueError if required services are not configured.
        """
        if self.macro_service is None:
            raise ValueError("MarketContextService requires a MacroService")
        if self.black_swan_service is None:
            raise ValueError("MarketContextService requires a BlackSwanService")

        today = as_of or date.today()

        # Macro calendar
        macro = self.macro_service.calendar(as_of=as_of)

        # Tail-risk
        black_swan = self.black_swan_service.alert(as_of_date=as_of)

        # Intermarket dashboard
        intermarket = self.intermarket()

        # Environment label
        environment_label = self._classify_environment(black_swan.alert_level, intermarket)

        # Trading gate
        trading_allowed = black_swan.alert_level != AlertLevel.CRITICAL

        # Position size factor — scale down in stress
        size_factor = {
            AlertLevel.NORMAL: 1.0,
            AlertLevel.ELEVATED: 0.75,
            AlertLevel.HIGH: 0.50,
            AlertLevel.CRITICAL: 0.0,
        }.get(black_swan.alert_level, 1.0)

        # Summary
        macro_upcoming = len(macro.events_next_7_days)
        summary_parts = [
            f"Environment: {environment_label}",
            f"Black swan: {black_swan.alert_level}",
            f"Macro events next 7d: {macro_upcoming}",
        ]
        if not trading_allowed:
            summary_parts.append("TRADING HALTED — critical stress")
        if intermarket.divergence:
            summary_parts.append("Intermarket divergence detected")

        # Compute tradeable instruments
        tradeable = self._compute_tradeable(
            environment_label, black_swan.alert_level, intermarket, today,
        )

        result = MarketContext(
            as_of_date=today,
            market=self._market,
            macro=macro,
            black_swan=black_swan,
            intermarket=intermarket,
            environment_label=environment_label,
            trading_allowed=trading_allowed,
            position_size_factor=size_factor,
            tradeable=tradeable,
            summary=" | ".join(summary_parts),
        )

        if debug:
            result.commentary.extend([
                f"Market context assessment as of {result.as_of_date}",
                f"Environment: {result.environment_label}",
                f"Black swan: {result.black_swan.alert_level} (score {result.black_swan.composite_score:.2f})",
                f"Trading allowed: {result.trading_allowed}",
                f"Position size factor: {result.position_size_factor}",
            ])

        return result

    def _compute_tradeable(
        self,
        environment: str,
        alert_level: AlertLevel,
        intermarket: IntermarketDashboard,
        today: date,
    ) -> InstrumentAvailability:
        """Determine what instruments/strategies are viable today."""

        # Dominant regime drives strategy availability
        regime = intermarket.dominant_regime
        regime_id = int(regime) if regime else 2

        # === OPTIONS ===
        if alert_level == AlertLevel.CRITICAL:
            opt_available = False
            opt_note = "HALTED — black swan critical. No options trading."
            opt_strategies = []
        elif regime_id == 4:
            opt_available = True
            opt_note = "R4 explosive — defined risk ONLY. No naked premium selling."
            opt_strategies = ["protective_put", "debit_spread", "iron_condor (wide)"]
        elif regime_id == 3:
            opt_available = True
            opt_note = "R3 trending — directional spreads preferred. Light theta."
            opt_strategies = ["debit_spread", "credit_spread (with trend)", "diagonal"]
        elif regime_id == 2:
            opt_available = True
            opt_note = "R2 high-vol MR — rich premiums. Wider strikes, defined risk."
            opt_strategies = ["iron_condor", "iron_butterfly", "credit_spread", "calendar", "strangle (with wings)"]
        else:
            opt_available = True
            opt_note = "R1 ideal — full options suite. Premium selling favored."
            opt_strategies = ["iron_condor", "iron_butterfly", "credit_spread", "calendar",
                              "diagonal", "straddle", "strangle", "ratio_spread"]

        # === STOCKS ===
        if alert_level == AlertLevel.CRITICAL:
            stock_available = False
            stock_note = "HALTED — protect capital. No new equity positions."
            stock_strategies = []
        elif environment == "crisis":
            stock_available = False
            stock_note = "Crisis — no new stock positions. Monitor existing only."
            stock_strategies = []
        elif environment == "defensive":
            stock_available = True
            stock_note = "Defensive — small positions only. Value + dividend strategies."
            stock_strategies = ["value", "dividend"]
        elif regime_id == 4:
            stock_available = True
            stock_note = "R4 volatile — only deep value with wide stops. Smaller size."
            stock_strategies = ["value", "turnaround (small size)"]
        else:
            stock_available = True
            stock_note = "Normal — all equity strategies available."
            stock_strategies = ["value", "growth", "dividend", "quality_momentum", "turnaround"]

        # === FUTURES ===
        if alert_level == AlertLevel.CRITICAL:
            fut_available = False
            fut_note = "HALTED — no futures. Leverage + crisis = catastrophic."
            fut_strategies = []
        elif regime_id == 4:
            fut_available = True
            fut_note = "R4 — futures with EXTREME CAUTION. Reduce size 50%. Tight stops."
            fut_strategies = ["hedging only", "micro contracts"]
        elif regime_id == 3:
            fut_available = True
            fut_note = "R3 trending — directional futures viable. Follow the trend."
            fut_strategies = ["directional (with trend)", "calendar spread", "futures options (defined risk)"]
        elif regime_id == 2:
            fut_available = True
            fut_note = "R2 high-vol — futures options premium selling. Wider strikes."
            fut_strategies = ["futures options (iron condor)", "calendar spread", "directional (small)"]
        else:
            fut_available = True
            fut_note = "R1 calm — all futures strategies. Premium selling ideal."
            fut_strategies = ["futures options (strangle/IC)", "calendar spread", "directional", "basis trade"]

        # === INDIA WEEKLY EXPIRY ===
        india_expiry_today = False
        india_expiry_inst = ""
        if self._market.upper() in ("INDIA", "IN"):
            weekday = today.weekday()  # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
            if weekday == 3:  # Thursday
                india_expiry_today = True
                india_expiry_inst = "NIFTY"
            elif weekday == 2:  # Wednesday
                india_expiry_today = True
                india_expiry_inst = "BANKNIFTY"
            elif weekday == 1:  # Tuesday
                india_expiry_today = True
                india_expiry_inst = "FINNIFTY"

        # Summary
        parts = []
        if opt_available:
            parts.append(f"Options: YES ({len(opt_strategies)} strategies)")
        else:
            parts.append("Options: NO")
        if stock_available:
            parts.append(f"Stocks: YES ({len(stock_strategies)} strategies)")
        else:
            parts.append("Stocks: NO")
        if fut_available:
            parts.append(f"Futures: YES ({len(fut_strategies)} strategies)")
        else:
            parts.append("Futures: NO")
        if india_expiry_today:
            parts.append(f"India expiry: {india_expiry_inst}")

        return InstrumentAvailability(
            options_available=opt_available,
            options_note=opt_note,
            options_strategies=opt_strategies,
            stocks_available=stock_available,
            stocks_note=stock_note,
            stocks_strategies=stock_strategies,
            futures_available=fut_available,
            futures_note=fut_note,
            futures_strategies=fut_strategies,
            india_weekly_expiry_today=india_expiry_today,
            india_expiry_instrument=india_expiry_inst,
            summary=" | ".join(parts),
        )

    def intermarket(self) -> IntermarketDashboard:
        """Read regimes of market reference tickers.

        Returns a dashboard even if regime_service is unavailable (empty entries).
        """
        cfg = get_settings().markets
        market_def = cfg.markets.get(self._market)
        if market_def is None or self.regime_service is None:
            return IntermarketDashboard(
                entries=[],
                summary="Intermarket data unavailable",
            )

        entries: list[IntermarketEntry] = []
        for ticker in market_def.reference_tickers:
            try:
                result = self.regime_service.detect(ticker)
                entries.append(IntermarketEntry(
                    ticker=ticker,
                    regime=result.regime,
                    confidence=result.confidence,
                    trend_direction=result.trend_direction,
                ))
            except Exception as exc:
                logger.warning("Failed to detect regime for %s: %s", ticker, exc)

        if not entries:
            return IntermarketDashboard(
                entries=[],
                summary="No intermarket data available",
            )

        # Compute metrics
        risk_on = sum(1 for e in entries if e.regime in (RegimeID.R1_LOW_VOL_MR, RegimeID.R3_LOW_VOL_TREND))
        risk_off = sum(1 for e in entries if e.regime in (RegimeID.R2_HIGH_VOL_MR, RegimeID.R4_HIGH_VOL_TREND))

        # Dominant regime
        from collections import Counter
        regime_counts = Counter(e.regime for e in entries)
        dominant = regime_counts.most_common(1)[0][0] if regime_counts else None

        # Divergence: no clear majority
        divergence = len(set(e.regime for e in entries)) >= 3 if len(entries) >= 3 else False

        parts = [f"Risk-on: {risk_on}, Risk-off: {risk_off}"]
        if dominant:
            parts.append(f"Dominant: R{dominant}")
        if divergence:
            parts.append("Divergence detected")

        return IntermarketDashboard(
            entries=entries,
            dominant_regime=dominant,
            risk_on_count=risk_on,
            risk_off_count=risk_off,
            divergence=divergence,
            summary=" | ".join(parts),
        )

    @staticmethod
    def _classify_environment(
        alert_level: AlertLevel,
        intermarket: IntermarketDashboard,
    ) -> str:
        """Classify the market environment."""
        if alert_level == AlertLevel.CRITICAL:
            return "crisis"
        if alert_level == AlertLevel.HIGH:
            return "defensive"
        if alert_level == AlertLevel.ELEVATED:
            return "cautious"
        # Even if alert is normal, check intermarket
        if intermarket.risk_off_count > intermarket.risk_on_count:
            return "cautious"
        return "risk-on"
