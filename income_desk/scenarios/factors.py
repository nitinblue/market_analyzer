"""Factor Model — maps tickers to macro factors with statistical loadings.

Six macro factors drive all asset returns:
  1. EQUITY    — broad equity market (SPY / NIFTY)
  2. RATES     — interest rates / bonds (TLT / India 10Y)
  3. VOLATILITY — implied vol regime (VIX / India VIX)
  4. COMMODITY  — commodities / gold (GLD / MCX)
  5. TECH       — tech sector premium (QQQ / NIFTY IT)
  6. CURRENCY   — USD strength / INR (DXY / USDINR)

Each ticker has a loading (beta) on each factor.  When a scenario
shocks a factor by X%, each ticker moves by loading * X% plus a
correlated idiosyncratic component.

IV response: vol increases ~2x on down moves, ~0.5x on up moves
(leverage effect / fear premium).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Factor(str, Enum):
    EQUITY = "equity"
    RATES = "rates"
    VOLATILITY = "volatility"
    COMMODITY = "commodity"
    TECH = "tech"
    CURRENCY = "currency"


@dataclass
class FactorLoading:
    """How much a ticker moves per 1% move in each factor."""
    equity: float = 1.0      # beta to broad market
    rates: float = 0.0       # sensitivity to rate moves
    volatility: float = 0.0  # sensitivity to VIX
    commodity: float = 0.0   # sensitivity to commodity prices
    tech: float = 0.0        # tech sector loading
    currency: float = 0.0    # sensitivity to USD/INR

    def as_dict(self) -> dict[str, float]:
        return {
            "equity": self.equity,
            "rates": self.rates,
            "volatility": self.volatility,
            "commodity": self.commodity,
            "tech": self.tech,
            "currency": self.currency,
        }


# ── Factor loadings for all supported tickers ──────────────────────────

# US Equities & ETFs
_US_LOADINGS: dict[str, FactorLoading] = {
    # Indices / ETFs
    "SPY":   FactorLoading(equity=1.00, rates=-0.15, volatility=-0.30, commodity=0.05, tech=0.35, currency=0.10),
    "QQQ":   FactorLoading(equity=1.15, rates=-0.20, volatility=-0.35, commodity=0.00, tech=0.80, currency=0.05),
    "IWM":   FactorLoading(equity=1.20, rates=-0.25, volatility=-0.40, commodity=0.10, tech=0.15, currency=0.15),
    "DIA":   FactorLoading(equity=0.95, rates=-0.10, volatility=-0.25, commodity=0.08, tech=0.20, currency=0.10),
    "GLD":   FactorLoading(equity=-0.15, rates=-0.40, volatility=0.30, commodity=0.90, tech=0.00, currency=-0.50),
    "TLT":   FactorLoading(equity=-0.30, rates=1.00, volatility=0.15, commodity=-0.10, tech=-0.05, currency=0.20),
    # Mega-cap tech
    "AAPL":  FactorLoading(equity=1.10, rates=-0.15, volatility=-0.30, commodity=0.00, tech=0.70, currency=0.15),
    "MSFT":  FactorLoading(equity=1.05, rates=-0.10, volatility=-0.25, commodity=0.00, tech=0.75, currency=0.10),
    "AMZN":  FactorLoading(equity=1.20, rates=-0.20, volatility=-0.35, commodity=0.00, tech=0.65, currency=0.10),
    "NVDA":  FactorLoading(equity=1.50, rates=-0.15, volatility=-0.45, commodity=0.00, tech=0.90, currency=0.05),
    "TSLA":  FactorLoading(equity=1.60, rates=-0.10, volatility=-0.50, commodity=0.05, tech=0.60, currency=0.05),
    "META":  FactorLoading(equity=1.30, rates=-0.15, volatility=-0.40, commodity=0.00, tech=0.75, currency=0.10),
    "GOOGL": FactorLoading(equity=1.10, rates=-0.10, volatility=-0.30, commodity=0.00, tech=0.70, currency=0.10),
    # Sector ETFs
    "XLF":   FactorLoading(equity=1.10, rates=0.30, volatility=-0.35, commodity=0.05, tech=0.00, currency=0.10),
    "XLE":   FactorLoading(equity=0.80, rates=0.10, volatility=-0.20, commodity=0.70, tech=0.00, currency=0.15),
    "XLK":   FactorLoading(equity=1.10, rates=-0.15, volatility=-0.30, commodity=0.00, tech=0.85, currency=0.10),
}

# India Instruments
_INDIA_LOADINGS: dict[str, FactorLoading] = {
    # Indices
    "NIFTY":     FactorLoading(equity=1.00, rates=-0.10, volatility=-0.30, commodity=0.05, tech=0.25, currency=-0.40),
    "BANKNIFTY": FactorLoading(equity=1.15, rates=0.25, volatility=-0.35, commodity=0.00, tech=0.00, currency=-0.35),
    "FINNIFTY":  FactorLoading(equity=1.10, rates=0.30, volatility=-0.30, commodity=0.00, tech=0.00, currency=-0.30),
    "SENSEX":    FactorLoading(equity=0.95, rates=-0.08, volatility=-0.28, commodity=0.05, tech=0.20, currency=-0.40),
    "MIDCPNIFTY":FactorLoading(equity=1.25, rates=-0.15, volatility=-0.40, commodity=0.10, tech=0.15, currency=-0.45),
    # Large-cap stocks
    "RELIANCE":  FactorLoading(equity=0.85, rates=-0.05, volatility=-0.20, commodity=0.40, tech=0.15, currency=-0.30),
    "TCS":       FactorLoading(equity=0.70, rates=-0.05, volatility=-0.15, commodity=0.00, tech=0.80, currency=0.30),
    "INFY":      FactorLoading(equity=0.75, rates=-0.05, volatility=-0.18, commodity=0.00, tech=0.85, currency=0.35),
    "HDFCBANK":  FactorLoading(equity=1.05, rates=0.35, volatility=-0.30, commodity=0.00, tech=0.00, currency=-0.25),
    "ICICIBANK": FactorLoading(equity=1.10, rates=0.30, volatility=-0.32, commodity=0.00, tech=0.00, currency=-0.25),
    "SBIN":      FactorLoading(equity=1.25, rates=0.25, volatility=-0.38, commodity=0.00, tech=0.00, currency=-0.30),
    "BHARTIARTL":FactorLoading(equity=0.60, rates=-0.05, volatility=-0.15, commodity=0.00, tech=0.20, currency=-0.20),
    "ITC":       FactorLoading(equity=0.50, rates=0.05, volatility=-0.10, commodity=0.15, tech=0.00, currency=-0.15),
    "BAJFINANCE":FactorLoading(equity=1.30, rates=0.20, volatility=-0.40, commodity=0.00, tech=0.00, currency=-0.30),
    "AXISBANK":  FactorLoading(equity=1.15, rates=0.28, volatility=-0.35, commodity=0.00, tech=0.00, currency=-0.25),
    "KOTAKBANK": FactorLoading(equity=1.00, rates=0.30, volatility=-0.28, commodity=0.00, tech=0.00, currency=-0.20),
    "LT":        FactorLoading(equity=1.00, rates=-0.10, volatility=-0.25, commodity=0.15, tech=0.10, currency=-0.25),
    "MARUTI":    FactorLoading(equity=0.90, rates=-0.10, volatility=-0.22, commodity=-0.15, tech=0.00, currency=-0.30),
    "SUNPHARMA": FactorLoading(equity=0.55, rates=0.00, volatility=-0.12, commodity=0.05, tech=0.00, currency=0.25),
    "TITAN":     FactorLoading(equity=0.85, rates=-0.05, volatility=-0.20, commodity=0.30, tech=0.00, currency=-0.20),
    "HINDUNILVR":FactorLoading(equity=0.45, rates=0.05, volatility=-0.08, commodity=0.10, tech=0.00, currency=-0.10),
    "WIPRO":     FactorLoading(equity=0.70, rates=-0.05, volatility=-0.15, commodity=0.00, tech=0.75, currency=0.30),
}

ALL_LOADINGS = {**_US_LOADINGS, **_INDIA_LOADINGS}


class FactorModel:
    """Factor-based return model for scenario stress testing."""

    def __init__(self, loadings: dict[str, FactorLoading] | None = None) -> None:
        self._loadings = loadings or dict(ALL_LOADINGS)

    def get_loading(self, ticker: str) -> FactorLoading:
        """Get factor loading for a ticker. Returns market-beta=1.0 default if unknown."""
        return self._loadings.get(ticker.upper(), FactorLoading())

    def compute_return(
        self,
        ticker: str,
        factor_shocks: dict[str, float],
    ) -> float:
        """Compute expected return for a ticker given factor shocks.

        Args:
            ticker: Instrument ticker.
            factor_shocks: Dict of factor_name -> shock_pct (e.g. {"equity": -0.10} = 10% drop).

        Returns:
            Expected return as decimal (e.g. -0.08 = 8% decline).
        """
        loading = self.get_loading(ticker)
        ld = loading.as_dict()
        total_return = 0.0
        for factor_name, shock in factor_shocks.items():
            beta = ld.get(factor_name, 0.0)
            total_return += beta * shock
        return total_return

    def compute_iv_response(
        self,
        ticker: str,
        base_iv: float,
        price_return: float,
        vol_shock: float = 0.0,
    ) -> float:
        """Compute stressed IV given price move and vol shock.

        The leverage effect: vol spikes ~2x on down moves, compresses on up moves.
        Additional vol_shock from the scenario (e.g. VIX spike) adds on top.

        Args:
            ticker: Instrument.
            base_iv: Current IV (decimal, e.g. 0.25).
            price_return: Price change (decimal, e.g. -0.05 = 5% drop).
            vol_shock: Direct vol factor shock (decimal).

        Returns:
            Stressed IV (decimal).
        """
        loading = self.get_loading(ticker)

        # Leverage effect: vol increases ~2x the magnitude of down moves
        # Empirical: IV change ≈ -2.5 × equity_return for negative moves
        if price_return < 0:
            leverage_iv_change = -2.5 * price_return * abs(loading.volatility)
        else:
            # Vol compresses on up moves, but less dramatically
            leverage_iv_change = -0.8 * price_return * abs(loading.volatility)

        # Direct vol shock (e.g. VIX +50%)
        direct_iv_change = vol_shock * abs(loading.volatility) * base_iv

        stressed_iv = base_iv + leverage_iv_change + direct_iv_change

        # Floor IV at 5%, cap at 150%
        return max(0.05, min(1.50, stressed_iv))

    def supported_tickers(self) -> list[str]:
        """All tickers with factor loadings."""
        return sorted(self._loadings.keys())
