"""Simulated market data — works when markets are closed.

Generates realistic option chains with bid/ask/Greeks from seed parameters.
Use for: weekend development, eTrading integration testing, demo portfolio, education.
NOT for: real trading decisions. Trust: UNRELIABLE.

Usage::

    from market_analyzer.adapters.simulated import SimulatedMarketData, SimulatedMetrics
    from market_analyzer import MarketAnalyzer, DataService

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

import math
from datetime import date, time, timedelta
from typing import TYPE_CHECKING

from market_analyzer.broker.base import MarketDataProvider, MarketMetricsProvider
from market_analyzer.models.quotes import AccountBalance, MarketMetrics, OptionQuote

if TYPE_CHECKING:
    from market_analyzer.models.opportunity import LegSpec


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
    ) -> None:
        self._tickers = {k.upper(): v for k, v in tickers.items()}
        self._account_nlv = account_nlv
        self._account_cash = account_cash
        self._account_bp = account_bp

    # ── MarketDataProvider identity ──────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return "simulated"

    @property
    def currency(self) -> str:
        return "USD"

    @property
    def timezone(self) -> str:
        return "US/Eastern"

    @property
    def lot_size_default(self) -> int:
        return 100

    @property
    def market_hours(self) -> tuple:
        return (time(9, 30), time(16, 0))

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
        dtes = [7, 21, 35, 60]

        for dte in dtes:
            exp = today + timedelta(days=dte)
            if expiration and exp != expiration:
                continue

            strike_step = _get_strike_step(price)
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

    def get_greeks(self, legs: list[LegSpec]) -> dict[str, dict]:
        """Return Greeks keyed by ``"{strike}{type[0].upper()}"``."""
        quotes = self.get_quotes(legs)
        result: dict[str, dict] = {}
        for leg, q in zip(legs, quotes):
            if q is not None:
                key = f"{leg.strike}{leg.option_type[0].upper()}"
                result[key] = {
                    "delta": q.delta,
                    "gamma": q.gamma,
                    "theta": q.theta,
                    "vega": q.vega,
                }
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


def _get_strike_step(price: float) -> float:
    """Return realistic strike interval for a given price level."""
    if price < 50:
        return 1.0
    if price < 200:
        return 2.5
    if price < 500:
        return 5.0
    return 10.0


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
    time_value = underlying_price * iv * time_factor * proximity * 0.4

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
    )


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
    return SimulatedMarketData({
        "NIFTY":     {"price": 26_000.0, "iv": 0.14, "iv_rank": 35},
        "BANKNIFTY": {"price": 50_000.0, "iv": 0.18, "iv_rank": 45},
        "RELIANCE":  {"price":  2_800.0, "iv": 0.25, "iv_rank": 40},
        "TCS":       {"price":  3_500.0, "iv": 0.20, "iv_rank": 30},
    })
