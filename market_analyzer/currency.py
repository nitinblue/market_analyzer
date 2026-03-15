"""Currency conversion and cross-market exposure analysis.

Pure functions — eTrading provides exchange rates, MA computes exposure,
P&L decomposition, and currency risk assessment. No live FX fetching.
"""

from __future__ import annotations
from datetime import date
from pydantic import BaseModel


class CurrencyPair(BaseModel):
    """Exchange rate between two currencies."""
    base: str       # "USD"
    quote: str      # "INR"
    rate: float     # 1 USD = 83.5 INR (base/quote)
    as_of: date


class PositionExposure(BaseModel):
    """A single position's exposure in its local currency."""
    ticker: str
    market: str          # "US", "INDIA"
    currency: str        # "USD", "INR"
    notional_value: float  # Position value in local currency
    unrealized_pnl: float  # Current P&L in local currency


class PortfolioExposure(BaseModel):
    """Cross-market portfolio exposure in a common base currency."""
    base_currency: str
    by_currency: dict[str, float]       # {"USD": 45000, "INR": 3750000} in local
    converted: dict[str, float]          # {"USD": 45000, "INR": 44910} in base currency
    total_exposure: float                # Sum in base currency
    currency_risk_pct: float             # % of portfolio in non-base currencies
    largest_foreign_exposure: str | None  # Which currency has most risk
    summary: str


class CurrencyPnL(BaseModel):
    """P&L impact from currency movement on a position."""
    ticker: str
    local_currency: str
    base_currency: str
    trading_pnl_local: float      # P&L from the trade itself (in local currency)
    trading_pnl_base: float       # Trading P&L converted to base at current rate
    currency_pnl_base: float      # P&L from FX movement alone (in base currency)
    total_pnl_base: float         # trading_pnl_base + currency_pnl_base
    fx_rate_at_entry: float
    fx_rate_current: float
    fx_change_pct: float          # How much FX moved (positive = base strengthened)
    summary: str


class CurrencyHedgeAssessment(BaseModel):
    """Assessment of currency risk for a cross-market portfolio."""
    base_currency: str
    foreign_currencies: list[str]
    total_foreign_exposure_base: float   # In base currency
    portfolio_pct_foreign: float          # % of total in foreign currencies
    risk_per_1pct_fx_move: float          # $ impact of 1% FX move
    recommendation: str                   # "natural hedge sufficient", "consider hedging", "hedge recommended"
    hedge_cost_estimate: str              # "~0.3-0.5% per quarter via futures"
    details: list[str]


def convert_amount(
    amount: float,
    from_currency: str,
    to_currency: str,
    rates: dict[str, CurrencyPair],
) -> float:
    """Convert amount between currencies using provided rates.

    Looks for direct pair (from/to) or inverse (to/from).
    Raises KeyError if no rate found.

    Convention: rate = "1 base = X quote" (e.g., USD/INR rate=83.5 means 1 USD = 83.5 INR).
    To convert USD to INR: amount * rate.
    To convert INR to USD: amount / rate.
    """
    if from_currency == to_currency:
        return amount

    for pair in rates.values():
        if pair.base == from_currency and pair.quote == to_currency:
            # from=USD, to=INR: amount * rate (1 USD = 83.5 INR)
            return amount * pair.rate
        if pair.base == to_currency and pair.quote == from_currency:
            # from=INR, to=USD: amount / rate
            return amount / pair.rate

    raise KeyError(f"No exchange rate found for {from_currency}/{to_currency}")


def compute_portfolio_exposure(
    positions: list[PositionExposure],
    rates: dict[str, CurrencyPair],
    base_currency: str = "USD",
) -> PortfolioExposure:
    """Aggregate cross-market positions into base currency exposure."""
    by_currency: dict[str, float] = {}
    converted: dict[str, float] = {}

    for pos in positions:
        by_currency[pos.currency] = by_currency.get(pos.currency, 0) + pos.notional_value

    total = 0.0
    for ccy, amount in by_currency.items():
        if ccy == base_currency:
            converted[ccy] = amount
        else:
            try:
                converted[ccy] = convert_amount(amount, ccy, base_currency, rates)
            except KeyError:
                converted[ccy] = 0.0  # Can't convert — flag as gap
        total += converted[ccy]

    foreign = sum(v for k, v in converted.items() if k != base_currency)
    risk_pct = foreign / total if total > 0 else 0

    largest = None
    if foreign > 0:
        foreign_ccys = {k: v for k, v in converted.items() if k != base_currency}
        if foreign_ccys:
            largest = max(foreign_ccys, key=foreign_ccys.get)

    summary = f"Total: {base_currency} {total:,.0f} | Foreign: {risk_pct:.0%}"

    return PortfolioExposure(
        base_currency=base_currency,
        by_currency=by_currency,
        converted=converted,
        total_exposure=round(total, 2),
        currency_risk_pct=round(risk_pct, 4),
        largest_foreign_exposure=largest,
        summary=summary,
    )


def compute_currency_pnl(
    ticker: str,
    trading_pnl_local: float,    # P&L in local currency
    position_value_local: float,  # Original position value in local currency
    local_currency: str,
    base_currency: str,
    fx_rate_at_entry: float,     # e.g., 83.0 (1 USD = 83 INR at entry)
    fx_rate_current: float,      # e.g., 84.5 (1 USD = 84.5 INR now)
) -> CurrencyPnL:
    """Decompose P&L into trading P&L and currency P&L.

    For USD-based investor with INR position:
    - INR weakens (rate goes up): INR position worth less in USD
    - INR strengthens (rate goes down): INR position worth more in USD
    """
    if local_currency == base_currency:
        return CurrencyPnL(
            ticker=ticker, local_currency=local_currency, base_currency=base_currency,
            trading_pnl_local=trading_pnl_local, trading_pnl_base=trading_pnl_local,
            currency_pnl_base=0.0, total_pnl_base=trading_pnl_local,
            fx_rate_at_entry=1.0, fx_rate_current=1.0, fx_change_pct=0.0,
            summary=f"{ticker}: {base_currency} {trading_pnl_local:+,.0f} (no FX impact)",
        )

    # Convert trading P&L to base at current rate
    # Convention: rate = 1 base = X local (e.g., 1 USD = 83.5 INR)
    trading_pnl_base = trading_pnl_local / fx_rate_current

    # Currency P&L: what the position was worth at entry rate vs current rate
    # Position value in base at entry: position_value_local / fx_rate_at_entry
    # Position value in base now: position_value_local / fx_rate_current
    # FX P&L = difference
    value_at_entry_base = position_value_local / fx_rate_at_entry
    value_now_base = position_value_local / fx_rate_current
    currency_pnl = value_now_base - value_at_entry_base

    total = trading_pnl_base + currency_pnl
    fx_change = (fx_rate_current - fx_rate_at_entry) / fx_rate_at_entry * 100

    return CurrencyPnL(
        ticker=ticker, local_currency=local_currency, base_currency=base_currency,
        trading_pnl_local=round(trading_pnl_local, 2),
        trading_pnl_base=round(trading_pnl_base, 2),
        currency_pnl_base=round(currency_pnl, 2),
        total_pnl_base=round(total, 2),
        fx_rate_at_entry=fx_rate_at_entry, fx_rate_current=fx_rate_current,
        fx_change_pct=round(fx_change, 2),
        summary=f"{ticker}: trade {base_currency} {trading_pnl_base:+,.0f} + FX {base_currency} {currency_pnl:+,.0f} = {base_currency} {total:+,.0f} (FX {fx_change:+.1f}%)",
    )


def assess_currency_exposure(
    positions: list[PositionExposure],
    rates: dict[str, CurrencyPair],
    base_currency: str = "USD",
) -> CurrencyHedgeAssessment:
    """Assess currency risk and recommend hedging action."""
    exposure = compute_portfolio_exposure(positions, rates, base_currency)

    foreign_ccys = [k for k in exposure.converted if k != base_currency and exposure.converted[k] > 0]
    foreign_total = sum(exposure.converted[k] for k in foreign_ccys)

    # Risk: 1% FX move impact
    risk_per_1pct = foreign_total * 0.01

    details = []
    for ccy in foreign_ccys:
        local_amt = exposure.by_currency.get(ccy, 0)
        base_amt = exposure.converted.get(ccy, 0)
        details.append(f"{ccy}: {local_amt:,.0f} local = {base_currency} {base_amt:,.0f} ({base_amt/exposure.total_exposure*100:.0f}% of portfolio)")

    # Recommendation
    if exposure.currency_risk_pct < 0.10:
        rec = "natural hedge sufficient — foreign exposure < 10% of portfolio"
        cost = "n/a"
    elif exposure.currency_risk_pct < 0.30:
        rec = "consider hedging — foreign exposure is 10-30% of portfolio"
        cost = "~0.3-0.5% per quarter via currency futures or forwards"
    else:
        rec = "hedge recommended — foreign exposure > 30% of portfolio"
        cost = "~0.3-0.5% per quarter via currency futures; consider natural hedge (INR income vs INR expenses)"

    return CurrencyHedgeAssessment(
        base_currency=base_currency,
        foreign_currencies=foreign_ccys,
        total_foreign_exposure_base=round(foreign_total, 2),
        portfolio_pct_foreign=round(exposure.currency_risk_pct, 4),
        risk_per_1pct_fx_move=round(risk_per_1pct, 2),
        recommendation=rec,
        hedge_cost_estimate=cost,
        details=details,
    )
