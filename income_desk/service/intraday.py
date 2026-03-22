"""IntradayService: real-time signal generation for 0DTE position management.

Monitors underlying price action against open 0DTE positions and generates
actionable signals for entry timing, exit triggers, and risk alerts.

Designed to be called frequently (every 1-5 minutes) during market hours,
unlike other services that operate on daily/EOD data.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, date
from typing import TYPE_CHECKING

from income_desk.models.intraday import (
    IntradayMonitorResult,
    IntradaySignal,
    IntradaySignalType,
    IntradaySnapshot,
    IntradayUrgency,
)

if TYPE_CHECKING:
    from income_desk.broker.base import MarketDataProvider, MarketMetricsProvider
    from income_desk.data.service import DataService

logger = logging.getLogger(__name__)

# Market hours (Eastern Time)
_MARKET_OPEN = time(9, 30)
_MARKET_CLOSE = time(16, 0)
_POWER_HOUR = time(15, 0)
_LAST_30 = time(15, 30)

# Thresholds
_STRIKE_APPROACH_PCT = 0.5     # Alert when underlying within 0.5% of short strike
_STRIKE_BREACH_PCT = 0.0       # Breach = at or past the short strike
_VIX_SPIKE_PCT = 10.0          # VIX up 10%+ intraday
_VOLUME_SPIKE_MULT = 2.0       # 2× average volume
_GAMMA_RISK_DTE_THRESHOLD = 0  # Only 0 DTE


class IntradayService:
    """Generate intraday signals for 0DTE position management.

    Usage::

        service = IntradayService(market_data=provider, data_service=ds)
        result = service.monitor(
            positions=[
                {"ticker": "SPY", "short_strikes": [580, 590], "entry_credit": 1.50},
            ]
        )
        for signal in result.signals:
            if signal.urgency == "immediate":
                print(f"ACT NOW: {signal.message}")
    """

    def __init__(
        self,
        market_data: MarketDataProvider | None = None,
        market_metrics: MarketMetricsProvider | None = None,
        data_service: DataService | None = None,
    ) -> None:
        self.market_data = market_data
        self.market_metrics = market_metrics
        self.data_service = data_service

    def monitor(
        self,
        positions: list[dict],
        now: datetime | None = None,
    ) -> IntradayMonitorResult:
        """Monitor 0DTE positions and generate signals.

        Args:
            positions: List of dicts, each with:
                - ticker: str (underlying)
                - short_strikes: list[float] (short strike prices)
                - entry_credit: float (credit received per spread)
                - profit_target_pct: float (e.g., 0.90 for 90%)
                - stop_loss_multiple: float | None (e.g., 2.0 for 2× credit)
                - structure_type: str (e.g., "iron_condor")
            now: Current time (defaults to now).

        Returns:
            IntradayMonitorResult with signals and snapshots.
        """
        now = now or datetime.now()
        result = IntradayMonitorResult(as_of=now)

        # Get unique tickers
        tickers = list({p["ticker"] for p in positions})

        # Fetch current prices
        prices = self._fetch_current_prices(tickers)
        vix = self._fetch_vix()
        minutes_to_close = self._minutes_to_close(now)

        for pos in positions:
            ticker = pos["ticker"]
            price = prices.get(ticker)
            if price is None:
                continue

            short_strikes = pos.get("short_strikes", [])
            entry_credit = pos.get("entry_credit", 0)
            profit_target_pct = pos.get("profit_target_pct", 0.90)
            stop_loss_mult = pos.get("stop_loss_multiple")
            structure = pos.get("structure_type", "unknown")

            snapshot = IntradaySnapshot(
                ticker=ticker,
                timestamp=now,
                price=price,
                vix=vix,
                minutes_to_close=minutes_to_close,
            )

            signals = []

            # --- Strike proximity checks ---
            for strike in short_strikes:
                distance_pct = abs(price - strike) / price * 100

                if distance_pct <= _STRIKE_BREACH_PCT or (
                    (strike <= price and "put" not in structure.lower()) or
                    (strike >= price and "call" not in structure.lower())
                ):
                    # Check if price actually breached the strike
                    breached = (
                        (price >= strike and any(
                            r in structure for r in ("call", "condor", "butterfly")
                        )) or
                        (price <= strike and any(
                            r in structure for r in ("put", "condor", "butterfly")
                        ))
                    )
                    if breached and distance_pct < 0.1:
                        signals.append(IntradaySignal(
                            signal_type=IntradaySignalType.BREACH_SHORT_STRIKE,
                            urgency=IntradayUrgency.IMMEDIATE,
                            ticker=ticker,
                            timestamp=now,
                            message=(
                                f"{ticker} @ ${price:.2f} BREACHED short strike "
                                f"${strike:.2f} — evaluate close"
                            ),
                            action="Close position or roll away from tested side",
                            current_price=price,
                            strike_distance_pct=distance_pct,
                            data={"strike": strike, "structure": structure},
                        ))

                elif distance_pct <= _STRIKE_APPROACH_PCT:
                    signals.append(IntradaySignal(
                        signal_type=IntradaySignalType.APPROACHING_STRIKE,
                        urgency=IntradayUrgency.SOON,
                        ticker=ticker,
                        timestamp=now,
                        message=(
                            f"{ticker} @ ${price:.2f} approaching short strike "
                            f"${strike:.2f} ({distance_pct:.2f}% away)"
                        ),
                        action="Monitor closely; prepare to defend or close",
                        current_price=price,
                        strike_distance_pct=distance_pct,
                        data={"strike": strike},
                    ))

            # --- Time-based signals ---
            if minutes_to_close is not None:
                if minutes_to_close <= 15:
                    signals.append(IntradaySignal(
                        signal_type=IntradaySignalType.EXPIRY_APPROACHING,
                        urgency=IntradayUrgency.IMMEDIATE,
                        ticker=ticker,
                        timestamp=now,
                        message=(
                            f"{ticker} 0DTE: {minutes_to_close} min to close — "
                            f"close or let expire"
                        ),
                        action="Close if profitable; let expire if risk is defined",
                        current_price=price,
                        data={"minutes_to_close": minutes_to_close},
                    ))
                elif minutes_to_close <= 60:
                    signals.append(IntradaySignal(
                        signal_type=IntradaySignalType.TIME_DECAY_WINDOW,
                        urgency=IntradayUrgency.MONITOR,
                        ticker=ticker,
                        timestamp=now,
                        message=(
                            f"{ticker} 0DTE: power hour — {minutes_to_close} min left, "
                            f"theta accelerating"
                        ),
                        action="Monitor; theta working in your favor if OTM",
                        current_price=price,
                        data={"minutes_to_close": minutes_to_close},
                    ))

            # --- VIX spike ---
            if vix is not None and vix > 25:
                signals.append(IntradaySignal(
                    signal_type=IntradaySignalType.VIX_SPIKE,
                    urgency=IntradayUrgency.SOON,
                    ticker=ticker,
                    timestamp=now,
                    message=f"VIX elevated at {vix:.1f} — heightened 0DTE risk",
                    action="Reduce size or widen wings on new entries",
                    current_price=price,
                    data={"vix": vix},
                ))

            snapshot.signals = signals
            result.snapshots.append(snapshot)
            result.signals.extend(signals)

        result.urgent_count = sum(
            1 for s in result.signals if s.urgency == IntradayUrgency.IMMEDIATE
        )
        result.summary = self._build_summary(result)
        return result

    def check_entry_window(
        self,
        ticker: str,
        now: datetime | None = None,
    ) -> IntradaySignal | None:
        """Check if now is a good time to enter a 0DTE trade.

        Best windows:
        - 9:45-10:15 AM: After opening range established
        - 11:00-11:30 AM: After morning noise settles
        - Avoid: first 15 min, last 30 min, lunch doldrums

        Returns a signal with entry guidance, or None if no opinion.
        """
        now = now or datetime.now()
        t = now.time()
        minutes_from_open = (
            (t.hour * 60 + t.minute) - (_MARKET_OPEN.hour * 60 + _MARKET_OPEN.minute)
        )
        minutes_to_close = self._minutes_to_close(now)

        if minutes_from_open < 0 or (minutes_to_close is not None and minutes_to_close <= 0):
            return None  # Market closed

        # First 15 min: avoid
        if minutes_from_open < 15:
            return IntradaySignal(
                signal_type=IntradaySignalType.TIME_DECAY_WINDOW,
                urgency=IntradayUrgency.MONITOR,
                ticker=ticker,
                timestamp=now,
                message=f"Wait — opening volatility ({minutes_from_open} min since open)",
                action="Wait for 9:45+ for opening range to establish",
                current_price=0,
            )

        # Prime window: 15-45 min after open
        if 15 <= minutes_from_open <= 45:
            return IntradaySignal(
                signal_type=IntradaySignalType.TIME_DECAY_WINDOW,
                urgency=IntradayUrgency.INFORMATIONAL,
                ticker=ticker,
                timestamp=now,
                message="Prime 0DTE entry window — opening range established",
                action="Good time to enter if setup is valid",
                current_price=0,
            )

        # Late entry: after 2 PM
        if minutes_to_close is not None and minutes_to_close <= 120:
            return IntradaySignal(
                signal_type=IntradaySignalType.TIME_DECAY_WINDOW,
                urgency=IntradayUrgency.INFORMATIONAL,
                ticker=ticker,
                timestamp=now,
                message=(
                    f"Late 0DTE entry — {minutes_to_close} min left. "
                    f"Theta high but gamma risk elevated"
                ),
                action="Only enter with tight strikes and defined risk",
                current_price=0,
            )

        return None

    def _fetch_current_prices(self, tickers: list[str]) -> dict[str, float]:
        """Fetch current underlying prices."""
        prices: dict[str, float] = {}

        # Try broker market data first (real-time)
        if self.market_data:
            try:
                for ticker in tickers:
                    # Use equity quotes from market data provider
                    quotes = self.market_data.get_quotes([{"ticker": ticker}])
                    if quotes:
                        q = quotes[0] if isinstance(quotes, list) else quotes
                        mid = getattr(q, "mid", None) or getattr(q, "last", None)
                        if mid:
                            prices[ticker] = float(mid)
            except Exception as e:
                logger.warning(f"Broker market data fetch failed: {e}")

        # Fallback to data service (may be delayed)
        if self.data_service and len(prices) < len(tickers):
            for ticker in tickers:
                if ticker not in prices:
                    try:
                        snap = self.data_service.get_latest(ticker)
                        if snap and hasattr(snap, "close"):
                            prices[ticker] = float(snap.close)
                    except Exception:
                        pass

        return prices

    def _fetch_vix(self) -> float | None:
        """Fetch current VIX level."""
        if self.market_metrics:
            try:
                metrics = self.market_metrics.get_metrics(["VIX"])
                if "VIX" in metrics:
                    return float(metrics["VIX"].iv_rank or 0)
            except Exception:
                pass

        if self.data_service:
            try:
                snap = self.data_service.get_latest("^VIX")
                if snap and hasattr(snap, "close"):
                    return float(snap.close)
            except Exception:
                pass

        return None

    @staticmethod
    def _minutes_to_close(now: datetime) -> int | None:
        """Minutes until market close (4:00 PM ET)."""
        t = now.time()
        close_min = _MARKET_CLOSE.hour * 60 + _MARKET_CLOSE.minute
        now_min = t.hour * 60 + t.minute
        remaining = close_min - now_min
        return remaining if remaining >= 0 else None

    @staticmethod
    def _build_summary(result: IntradayMonitorResult) -> str:
        """Build human-readable summary."""
        parts = []
        if result.urgent_count:
            parts.append(f"{result.urgent_count} URGENT signal(s)")
        total = len(result.signals)
        if total > result.urgent_count:
            parts.append(f"{total - result.urgent_count} other signal(s)")
        tickers = list({s.ticker for s in result.snapshots})
        parts.append(f"Monitoring: {', '.join(tickers)}")
        return " | ".join(parts) if parts else "No signals"
