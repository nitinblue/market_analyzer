"""Simulated market data — works when markets are closed.

Generates realistic option chains with bid/ask/Greeks from seed parameters.
Use for: weekend development, eTrading integration testing, demo portfolio, education.
NOT for: real trading decisions. Trust: UNRELIABLE.

Usage::

    from income_desk.adapters.simulated import SimulatedMarketData, SimulatedMetrics
    from income_desk import MarketAnalyzer, DataService

    sim = SimulatedMarketData({
        "SPY": {"price": 580.0, "iv": 0.18, "iv_rank": 43},
        "QQQ": {"price": 490.0, "iv": 0.25, "iv_rank": 55},
        "IWM": {"price": 245.0, "iv": 0.22, "iv_rank": 48},
        "GLD": {"price": 415.0, "iv": 0.28, "iv_rank": 68},
        "TLT": {"price": 86.0,  "iv": 0.13, "iv_rank": 45},
    })

    ma = MarketAnalyzer(
        data_service=DataService(),
        market_data=sim,
        market_metrics=SimulatedMetrics(sim),
    )

    # Full pipeline works — all commands, validation, Kelly, audit, demo portfolio
    # Everything clearly labeled as "simulated" in trust reports
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

SIM_SNAPSHOT_FILE = Path.home() / ".income_desk" / "sim_snapshot.json"

from income_desk.broker.base import MarketDataProvider, MarketMetricsProvider
from income_desk.models.quotes import AccountBalance, MarketMetrics, OptionQuote

if TYPE_CHECKING:
    from income_desk.models.opportunity import LegSpec


class SimulatedMarketData(MarketDataProvider):
    """Generate realistic option chains from seed parameters.

    No broker, no internet, no market hours required.

    Each ticker entry supports these keys:
    - ``price``    (required) current underlying price
    - ``iv``       (optional, default 0.20) annualised IV level
    - ``iv_rank``  (optional) IV rank 0–100
    - ``beta``     (optional, default 1.0)
    - ``liquidity``(optional, default 4.0) liquidity rating
    - ``atr_pct``  (optional) ATR as fraction of price; unused by generator but
                   available for callers that inspect seed data

    Trust level: UNRELIABLE.  Do not use for real trading decisions.
    """

    def __init__(
        self,
        tickers: dict[str, dict],
        account_nlv: float = 100_000.0,
        account_cash: float = 80_000.0,
        account_bp: float = 75_000.0,
        *,
        currency: str = "USD",
        timezone: str = "US/Eastern",
        lot_size_default: int = 100,
    ) -> None:
        self._tickers = {k.upper(): v for k, v in tickers.items()}
        self._account_nlv = account_nlv
        self._account_cash = account_cash
        self._account_bp = account_bp
        self._currency = currency
        self._timezone = timezone
        self._lot_size_default = lot_size_default

    # ── MarketDataProvider identity ──────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return "simulated"

    @property
    def currency(self) -> str:
        return self._currency

    @property
    def timezone(self) -> str:
        return self._timezone

    @property
    def lot_size_default(self) -> int:
        return self._lot_size_default

    @property
    def market_hours(self) -> tuple:
        return (time(9, 30), time(16, 0))

    # ── Discovery ────────────────────────────────────────────────────────

    def supported_tickers(self) -> list[str]:
        """Return all tickers available in this simulation."""
        return sorted(self._tickers.keys())

    def ticker_info(self) -> dict[str, dict]:
        """Return full info for all supported tickers.

        Useful for eTrading / callers to know what data is available
        before making requests.

        Returns:
            Dict of ticker -> {price, iv, iv_rank, atr_pct, ...}
        """
        return {k: dict(v) for k, v in self._tickers.items()}

    def has_ticker(self, ticker: str) -> bool:
        """Check if a ticker is supported in this simulation."""
        return ticker.upper() in self._tickers

    # ── Price / chain ────────────────────────────────────────────────────

    def get_underlying_price(self, ticker: str) -> float | None:
        info = self._tickers.get(ticker.upper())
        return info["price"] if info else None

    def get_option_chain(
        self, ticker: str, expiration: date | None = None
    ) -> list[OptionQuote]:
        """Generate a realistic option chain for *ticker*.

        Produces quotes across 4 standard expirations (7, 21, 35, 60 DTE)
        unless a specific expiration is requested.
        """
        info = self._tickers.get(ticker.upper())
        if not info:
            return []

        price = info["price"]
        iv = info.get("iv", 0.20)

        results: list[OptionQuote] = []
        today = date.today()

        # Market-aware expirations
        if self._currency == "INR":
            # India: nearest weekly + next 2 monthlies
            dtes = [3, 10, 30, 60]  # approximate: this week, next week, monthly, 2-month
        else:
            dtes = [7, 21, 35, 60]

        for dte in dtes:
            exp = today + timedelta(days=dte)
            if expiration and exp != expiration:
                continue

            # Look up lot size from registry
            lot_size = self._lot_size_default
            try:
                from income_desk.registry import MarketRegistry
                inst = MarketRegistry().get_instrument(ticker.upper())
                if inst:
                    lot_size = inst.lot_size
            except (KeyError, ImportError):
                pass

            strike_step = _get_strike_step(price, ticker)
            min_strike = _round_to_step(price * 0.85, strike_step)
            max_strike = _round_to_step(price * 1.15, strike_step)

            strike = min_strike
            while strike <= max_strike:
                for opt_type in ("call", "put"):
                    results.append(
                        _generate_option_quote(
                            ticker=ticker.upper(),
                            strike=strike,
                            option_type=opt_type,
                            expiration=exp,
                            dte=dte,
                            underlying_price=price,
                            iv=iv,
                            lot_size=lot_size,
                        )
                    )
                strike = round(strike + strike_step, 4)

        return results

    def get_quotes(
        self,
        legs: list[LegSpec],
        *,
        ticker: str = "",
        include_greeks: bool = True,
    ) -> list[OptionQuote]:
        """Generate quotes for specific option legs."""
        results: list[OptionQuote] = []
        for leg in legs:
            t = (ticker or getattr(leg, "ticker", None) or "SPY").upper()
            info = self._tickers.get(t)
            if not info:
                results.append(None)  # type: ignore[arg-type]
                continue

            exp = getattr(leg, "expiration", None) or (date.today() + timedelta(days=35))
            dte = getattr(leg, "days_to_expiry", None) or max((exp - date.today()).days, 1)

            quote = _generate_option_quote(
                ticker=t,
                strike=leg.strike,
                option_type=leg.option_type,
                expiration=exp,
                dte=dte,
                underlying_price=info["price"],
                iv=info.get("iv", 0.20),
            )
            results.append(quote)
        return results

    def get_greeks(self, legs_or_ticker="", ticker: str = "") -> dict:
        """Simulated Greeks from chain data.

        Accepts either a list of LegSpec objects or a ticker string.
        When called with a ticker, generates Greeks from the full chain.
        """
        # Handle legacy list[LegSpec] signature
        if isinstance(legs_or_ticker, list):
            quotes = self.get_quotes(legs_or_ticker)
            result: dict[str, dict] = {}
            for leg, q in zip(legs_or_ticker, quotes):
                if q is not None:
                    key = f"{leg.strike}{leg.option_type[0].upper()}"
                    result[key] = {
                        "delta": q.delta,
                        "gamma": q.gamma,
                        "theta": q.theta,
                        "vega": q.vega,
                    }
            return result

        # String ticker path
        if isinstance(legs_or_ticker, str) and legs_or_ticker:
            ticker = legs_or_ticker
        if not ticker:
            return {}

        chain = self.get_option_chain(ticker)
        result = {}
        for q in chain:
            if q.delta is not None:
                key = f"{q.strike:.0f}{'C' if q.option_type == 'call' else 'P'}"
                result[key] = {
                    "delta": q.delta, "gamma": q.gamma,
                    "theta": q.theta, "vega": q.vega,
                    "iv": q.implied_volatility,
                }
        return result

    def get_prices_batch(self, tickers: list[str]) -> dict[str, float]:
        """Batch price fetch for simulated data."""
        result = {}
        for t in tickers:
            p = self.get_underlying_price(t)
            if p is not None:
                result[t.upper()] = p
        return result

    # ── Mutation helpers for test scenarios ─────────────────────────────

    def update_price(self, ticker: str, new_price: float) -> None:
        """Hard-set underlying price."""
        t = ticker.upper()
        if t in self._tickers:
            self._tickers[t]["price"] = new_price

    def simulate_move(self, ticker: str, pct_change: float) -> None:
        """Apply a percentage price move.  E.g. ``simulate_move("SPY", -0.02)`` = −2 %."""
        t = ticker.upper()
        if t in self._tickers:
            old = self._tickers[t]["price"]
            self._tickers[t]["price"] = round(old * (1 + pct_change), 2)


class SimulatedMetrics(MarketMetricsProvider):
    """Simulated IV rank and metrics sourced from SimulatedMarketData seed data."""

    def __init__(self, sim: SimulatedMarketData) -> None:
        self._sim = sim

    def get_metrics(self, tickers: list[str]) -> dict[str, MarketMetrics]:
        result: dict[str, MarketMetrics] = {}
        for t in tickers:
            info = self._sim._tickers.get(t.upper())
            if info:
                iv_rank = info.get("iv_rank")
                result[t] = MarketMetrics(
                    ticker=t,
                    iv_rank=iv_rank,
                    iv_percentile=round(iv_rank * 1.1, 1) if iv_rank is not None else None,
                    iv_30_day=info.get("iv"),
                    beta=info.get("beta", 1.0),
                    liquidity_rating=info.get("liquidity", 4.0),
                )
        return result


class SimulatedAccount:
    """Simulated account balance — no broker required."""

    def __init__(
        self,
        nlv: float = 100_000.0,
        cash: float = 80_000.0,
        bp: float = 75_000.0,
    ) -> None:
        self.nlv = nlv
        self.cash = cash
        self.bp = bp

    def get_balance(self) -> AccountBalance:
        return AccountBalance(
            account_number="SIM-001",
            net_liquidating_value=self.nlv,
            cash_balance=self.cash,
            derivative_buying_power=self.bp,
            equity_buying_power=self.bp,
            maintenance_requirement=self.nlv - self.bp,
            source="simulated",
            currency="USD",
        )


# ── Strike / price helpers ────────────────────────────────────────────────────


def _get_strike_step(price: float, ticker: str = "") -> float:
    """Return realistic strike interval for a given price level.

    Uses registry data for India instruments (NIFTY=50, BANKNIFTY=100, etc.)
    Falls back to US-style price-based intervals.
    """
    if ticker:
        try:
            from income_desk.registry import MarketRegistry
            inst = MarketRegistry().get_instrument(ticker.upper())
            if inst and inst.strike_interval:
                return inst.strike_interval
        except (KeyError, ImportError):
            pass

    # Price-based fallback (US and unregistered tickers)
    if price < 50:
        return 1.0
    if price < 200:
        return 2.5
    if price < 500:
        return 5.0
    if price < 5_000:
        return 10.0
    if price < 20_000:
        return 50.0
    return 100.0  # SENSEX (74,500), BANKNIFTY (52,000)


def _round_to_step(value: float, step: float) -> float:
    return round(round(value / step) * step, 4)


def _generate_option_quote(
    ticker: str,
    strike: float,
    option_type: str,
    expiration: date,
    dte: int,
    underlying_price: float,
    iv: float,
    lot_size: int = 100,
) -> OptionQuote:
    """Generate a single realistic-looking option quote.

    Uses simplified approximations — **not Black-Scholes**.
    Fit for testing and development; NOT for trading decisions.
    """
    dte = max(dte, 1)
    time_factor = math.sqrt(dte / 365)

    # Moneyness: positive = in-the-money for this option type
    if option_type == "call":
        moneyness = (underlying_price - strike) / underlying_price
        intrinsic = max(0.0, underlying_price - strike)
    else:
        moneyness = (strike - underlying_price) / underlying_price
        intrinsic = max(0.0, strike - underlying_price)

    # Time value: peaks at ATM, decays away from the money
    atm_distance = abs(underlying_price - strike) / underlying_price
    # Gaussian proximity centred at ATM, width scaled to IV × sqrt(T)
    width_sq = 2 * iv * iv * dte / 365
    proximity = math.exp(-atm_distance * atm_distance / max(width_sq, 1e-9))
    # Time value scales with IV — elevated IV produces richer premium (matching real market behaviour)
    iv_boost = 1.0 + max(0.0, (iv - 0.20)) * 2.0  # 20% IV → 1.0×, 30% → 1.2×, 40% → 1.4×
    time_value = underlying_price * iv * time_factor * proximity * 0.4 * iv_boost

    mid = round(intrinsic + time_value, 2)
    mid = max(0.01, mid)

    # Bid/ask spread: wider for deep OTM
    spread_pct = 0.02 + atm_distance * 0.05
    spread = max(0.01, round(mid * spread_pct, 2))
    bid = round(max(0.01, mid - spread / 2), 2)
    ask = round(mid + spread / 2, 2)

    # Delta: simplified linear approximation centred at 0.50 for ATM
    if option_type == "call":
        delta = max(0.01, min(0.99, 0.5 + moneyness * 3))
    else:
        delta = max(-0.99, min(-0.01, -0.5 + moneyness * 3))

    # Gamma: highest at ATM, falls off with distance
    gamma = max(0.001, proximity * 0.05 / max(underlying_price * iv * time_factor, 1e-9))

    # Theta: rough approximation — bleed half time value over remaining DTE
    theta = -(time_value * 0.5 / dte)

    # Vega: underlying × sqrt(T) × proximity × scale
    vega = underlying_price * time_factor * proximity * 0.01

    # Volatility skew: OTM puts carry higher IV (empirical feature)
    strike_iv = iv
    if option_type == "put" and strike < underlying_price:
        skew_boost = (underlying_price - strike) / underlying_price * 0.3
        strike_iv = iv + skew_boost

    return OptionQuote(
        ticker=ticker,
        strike=strike,
        option_type=option_type,
        expiration=expiration,
        bid=bid,
        ask=ask,
        mid=mid,
        last=mid,
        implied_volatility=round(strike_iv, 4),
        delta=round(delta, 4),
        gamma=round(gamma, 6),
        theta=round(theta, 4),
        vega=round(vega, 4),
        volume=int(proximity * 10_000),
        open_interest=int(proximity * 50_000),
        lot_size=lot_size,
    )


# ── Snapshot capture / restore ────────────────────────────────────────────────


def refresh_simulation_data(
    ma,  # MarketAnalyzer instance (with broker connected)
    tickers: list[str] | None = None,
) -> dict:
    """Capture live market data and save as simulation snapshot.

    Run this when the market is open. The snapshot is saved to
    ~/.income_desk/sim_snapshot.json and used by create_from_snapshot()
    when the market is closed.

    Args:
        ma: MarketAnalyzer with broker connected (has_broker=True).
        tickers: Tickers to capture. Default: SPY, QQQ, IWM, GLD, TLT.

    Returns:
        Dict of captured data (also saved to disk).
    """
    if tickers is None:
        tickers = ["SPY", "QQQ", "IWM", "GLD", "TLT"]

    snapshot: dict = {
        "captured_at": datetime.now().isoformat(),
        "source": ma.quotes.source if hasattr(ma, "quotes") else "unknown",
        "tickers": {},
    }

    for ticker in tickers:
        try:
            # Get underlying price and technical indicators
            tech = ma.technicals.snapshot(ticker)
            price = tech.current_price
            atr_pct = tech.atr_pct
            rsi = tech.rsi.value

            # Get IV and metrics
            metrics = ma.quotes.get_metrics(ticker) if hasattr(ma, "quotes") else None
            iv_rank = None
            iv_pct = None
            if metrics:
                if hasattr(metrics, "iv_rank"):
                    iv_rank = metrics.iv_rank
                    iv_pct = metrics.iv_percentile
                elif isinstance(metrics, dict):
                    iv_rank = metrics.get("iv_rank") or metrics.get("ivRank")
                    iv_pct = metrics.get("iv_percentile") or metrics.get("ivPercentile")

            # Get vol surface front-month IV
            vol = ma.vol_surface.surface(ticker)
            front_iv = vol.front_iv if vol else 0.20

            # Get regime
            regime = ma.regime.detect(ticker)

            snapshot["tickers"][ticker] = {
                "price": round(price, 2),
                "iv": round(front_iv, 4),
                "iv_rank": round(iv_rank, 1) if iv_rank is not None else None,
                "iv_percentile": round(iv_pct, 1) if iv_pct is not None else None,
                "atr_pct": round(atr_pct, 2),
                "rsi": round(rsi, 1),
                "regime_id": regime.regime.value,
                "regime_confidence": round(regime.confidence, 2),
            }
        except Exception as e:
            snapshot["tickers"][ticker] = {"error": str(e)}

    # Save to disk
    SIM_SNAPSHOT_FILE.parent.mkdir(exist_ok=True)
    SIM_SNAPSHOT_FILE.write_text(json.dumps(snapshot, indent=2))

    return snapshot


def create_from_snapshot() -> SimulatedMarketData | None:
    """Create SimulatedMarketData from the last saved snapshot.

    Returns None if no snapshot exists.
    """
    if not SIM_SNAPSHOT_FILE.exists():
        return None

    try:
        data = json.loads(SIM_SNAPSHOT_FILE.read_text())
    except Exception:
        return None

    tickers: dict[str, dict] = {}
    for ticker, info in data.get("tickers", {}).items():
        if "error" in info:
            continue
        tickers[ticker] = {
            "price": info.get("price", 0),
            "iv": info.get("iv", 0.20),
            "iv_rank": info.get("iv_rank"),
            "atr_pct": info.get("atr_pct", 1.0),
        }

    if not tickers:
        return None

    return SimulatedMarketData(tickers)


def get_snapshot_info() -> dict | None:
    """Get info about the saved snapshot without loading full data."""
    if not SIM_SNAPSHOT_FILE.exists():
        return None

    try:
        data = json.loads(SIM_SNAPSHOT_FILE.read_text())
        captured = data.get("captured_at", "unknown")
        source = data.get("source", "unknown")
        tickers = list(data.get("tickers", {}).keys())

        # How old is it?
        age_hours = None
        try:
            captured_dt = datetime.fromisoformat(captured)
            age_hours = (datetime.now() - captured_dt).total_seconds() / 3600
        except Exception:
            pass

        return {
            "captured_at": captured,
            "age_hours": round(age_hours, 1) if age_hours is not None else None,
            "source": source,
            "tickers": tickers,
            "ticker_count": len(tickers),
        }
    except Exception:
        return None


# ── Preset scenarios ──────────────────────────────────────────────────────────


def create_calm_market() -> SimulatedMarketData:
    """R1-like calm market: normal IV, low vol."""
    return SimulatedMarketData({
        "SPY": {"price": 580.0, "iv": 0.15, "iv_rank": 25},
        "QQQ": {"price": 500.0, "iv": 0.18, "iv_rank": 30},
        "IWM": {"price": 245.0, "iv": 0.20, "iv_rank": 35},
        "GLD": {"price": 420.0, "iv": 0.16, "iv_rank": 20},
        "TLT": {"price": 90.0,  "iv": 0.12, "iv_rank": 30},
    })


def create_volatile_market() -> SimulatedMarketData:
    """R2-like volatile market: elevated IV, mean-reverting."""
    return SimulatedMarketData({
        "SPY": {"price": 550.0, "iv": 0.28, "iv_rank": 75},
        "QQQ": {"price": 460.0, "iv": 0.35, "iv_rank": 82},
        "IWM": {"price": 220.0, "iv": 0.32, "iv_rank": 80},
        "GLD": {"price": 440.0, "iv": 0.25, "iv_rank": 65},
        "TLT": {"price": 82.0,  "iv": 0.18, "iv_rank": 70},
    })


def create_crash_scenario() -> SimulatedMarketData:
    """R4-like crash: extreme IV, directional sell-off."""
    return SimulatedMarketData({
        "SPY": {"price": 480.0, "iv": 0.45, "iv_rank": 95},
        "QQQ": {"price": 380.0, "iv": 0.55, "iv_rank": 98},
        "IWM": {"price": 180.0, "iv": 0.50, "iv_rank": 96},
        "GLD": {"price": 460.0, "iv": 0.35, "iv_rank": 85},
        "TLT": {"price": 95.0,  "iv": 0.22, "iv_rank": 80},
    })


def create_india_market() -> SimulatedMarketData:
    """India market simulation (NSE instruments)."""
    return SimulatedMarketData(
        {
            "NIFTY":     {"price": 26_000.0, "iv": 0.14, "iv_rank": 35},
            "BANKNIFTY": {"price": 50_000.0, "iv": 0.18, "iv_rank": 45},
            "RELIANCE":  {"price":  2_800.0, "iv": 0.25, "iv_rank": 40},
            "TCS":       {"price":  3_500.0, "iv": 0.20, "iv_rank": 30},
        },
        account_nlv=5_000_000.0,
        account_cash=4_000_000.0,
        account_bp=3_500_000.0,
        currency="INR",
        timezone="Asia/Kolkata",
        lot_size_default=25,
    )


def create_ideal_income() -> SimulatedMarketData:
    """R1/R2 regime, elevated IV — ideal income trading scenario.

    Comprehensive US universe for weekend testing.
    """
    return SimulatedMarketData({
        # Major indices/ETFs
        "SPY":  {"price": 565.0, "iv": 0.26, "iv_rank": 55, "atr_pct": 1.1},
        "QQQ":  {"price": 480.0, "iv": 0.30, "iv_rank": 60, "atr_pct": 1.3},
        "IWM":  {"price": 210.0, "iv": 0.28, "iv_rank": 52, "atr_pct": 1.5},
        "GLD":  {"price": 295.0, "iv": 0.22, "iv_rank": 48, "atr_pct": 1.0},
        "TLT":  {"price": 86.0,  "iv": 0.18, "iv_rank": 45, "atr_pct": 0.8},
        "DIA":  {"price": 420.0, "iv": 0.20, "iv_rank": 42, "atr_pct": 1.0},
        # Mega-cap tech
        "AAPL": {"price": 230.0, "iv": 0.28, "iv_rank": 50, "atr_pct": 1.4},
        "MSFT": {"price": 420.0, "iv": 0.25, "iv_rank": 45, "atr_pct": 1.2},
        "AMZN": {"price": 200.0, "iv": 0.32, "iv_rank": 58, "atr_pct": 1.6},
        "NVDA": {"price": 130.0, "iv": 0.45, "iv_rank": 65, "atr_pct": 2.5},
        "TSLA": {"price": 275.0, "iv": 0.55, "iv_rank": 70, "atr_pct": 3.0},
        "META": {"price": 600.0, "iv": 0.35, "iv_rank": 55, "atr_pct": 1.8},
        "GOOGL":{"price": 170.0, "iv": 0.28, "iv_rank": 48, "atr_pct": 1.4},
        # Sector ETFs
        "XLF":  {"price": 48.0,  "iv": 0.22, "iv_rank": 40, "atr_pct": 1.2},
        "XLE":  {"price": 85.0,  "iv": 0.28, "iv_rank": 52, "atr_pct": 1.8},
        "XLK":  {"price": 220.0, "iv": 0.26, "iv_rank": 50, "atr_pct": 1.3},
    })


def create_post_crash_recovery() -> SimulatedMarketData:
    """R2 regime transitioning to R1, very elevated IV — post-crash recovery.

    IV rank 75-90%: premiums are 2-3× normal. This is where income traders
    make their year. Iron condors collect $3-5 on 5-wide wings.
    Use for: crash playbook Phase 2/3 testing, demo portfolio.
    """
    return SimulatedMarketData({
        "SPY": {"price": 520.0, "iv": 0.35, "iv_rank": 82, "atr_pct": 1.8},
        "QQQ": {"price": 430.0, "iv": 0.42, "iv_rank": 88, "atr_pct": 2.2},
        "IWM": {"price": 195.0, "iv": 0.38, "iv_rank": 85, "atr_pct": 2.0},
        "GLD": {"price": 450.0, "iv": 0.30, "iv_rank": 70, "atr_pct": 1.4},
        "TLT": {"price": 92.0,  "iv": 0.22, "iv_rank": 72, "atr_pct": 1.0},
    })


def create_wheel_opportunity() -> SimulatedMarketData:
    """Stocks at support with elevated IV — ideal for wheel strategy.

    Tickers at or near key support levels, IV elevated enough for
    meaningful CSP premiums. Use for: wheel strategy demo, CSP analysis.
    """
    return SimulatedMarketData({
        "SPY":  {"price": 545.0, "iv": 0.28, "iv_rank": 58, "atr_pct": 1.3},
        "AAPL": {"price": 210.0, "iv": 0.32, "iv_rank": 62, "atr_pct": 1.6},
        "MSFT": {"price": 390.0, "iv": 0.30, "iv_rank": 55, "atr_pct": 1.4},
        "AMD":  {"price": 145.0, "iv": 0.45, "iv_rank": 72, "atr_pct": 2.5},
        "IWM":  {"price": 200.0, "iv": 0.30, "iv_rank": 55, "atr_pct": 1.6},
    })


def create_india_trading() -> SimulatedMarketData:
    """India market — comprehensive F&O universe for weekend testing.

    Prices approximate to late March 2026. Covers indices + top F&O stocks.
    """
    return SimulatedMarketData(
        {
            # Indices
            "NIFTY":     {"price": 23_000.0, "iv": 0.18, "iv_rank": 45, "atr_pct": 2.1},
            "BANKNIFTY": {"price": 52_500.0, "iv": 0.22, "iv_rank": 55, "atr_pct": 2.7},
            "FINNIFTY":  {"price": 24_600.0, "iv": 0.20, "iv_rank": 50, "atr_pct": 2.0},
            "SENSEX":    {"price": 74_500.0, "iv": 0.16, "iv_rank": 40, "atr_pct": 1.8},
            "MIDCPNIFTY":{"price": 12_600.0, "iv": 0.24, "iv_rank": 48, "atr_pct": 2.2},
            # Top F&O stocks
            "RELIANCE":  {"price":  1_375.0, "iv": 0.28, "iv_rank": 48, "atr_pct": 2.2},
            "TCS":       {"price":  2_410.0, "iv": 0.22, "iv_rank": 35, "atr_pct": 2.5},
            "INFY":      {"price":  1_278.0, "iv": 0.26, "iv_rank": 42, "atr_pct": 2.8},
            "HDFCBANK":  {"price":    762.0, "iv": 0.24, "iv_rank": 40, "atr_pct": 3.5},
            "ICICIBANK": {"price":  1_380.0, "iv": 0.26, "iv_rank": 45, "atr_pct": 2.0},
            "SBIN":      {"price":  1_042.0, "iv": 0.30, "iv_rank": 52, "atr_pct": 2.5},
            "BHARTIARTL":{"price":  1_750.0, "iv": 0.24, "iv_rank": 38, "atr_pct": 1.8},
            "ITC":       {"price":    430.0, "iv": 0.20, "iv_rank": 30, "atr_pct": 1.5},
            "BAJFINANCE":{"price":  8_800.0, "iv": 0.32, "iv_rank": 55, "atr_pct": 2.0},
            "AXISBANK":  {"price":  1_125.0, "iv": 0.28, "iv_rank": 48, "atr_pct": 2.2},
            "KOTAKBANK": {"price":  1_950.0, "iv": 0.22, "iv_rank": 35, "atr_pct": 1.8},
            "LT":        {"price":  3_400.0, "iv": 0.24, "iv_rank": 40, "atr_pct": 1.6},
            "MARUTI":    {"price": 11_500.0, "iv": 0.22, "iv_rank": 38, "atr_pct": 1.5},
            "SUNPHARMA": {"price":  1_700.0, "iv": 0.26, "iv_rank": 42, "atr_pct": 1.8},
            "TITAN":     {"price":  3_200.0, "iv": 0.28, "iv_rank": 45, "atr_pct": 2.0},
            "HINDUNILVR":{"price":  2_250.0, "iv": 0.20, "iv_rank": 30, "atr_pct": 1.4},
            "WIPRO":     {"price":    280.0, "iv": 0.24, "iv_rank": 38, "atr_pct": 2.0},
        },
        account_nlv=5_000_000.0,
        account_cash=4_000_000.0,
        account_bp=3_500_000.0,
        currency="INR",
        timezone="Asia/Kolkata",
        lot_size_default=25,
    )
