"""Historical Correlation & Beta Calculator.

Computes actual factor loadings from real OHLCV data instead of
static guesses. Uses rolling returns to calculate:
- Pairwise correlation matrix across all tickers
- Factor betas (how much each ticker moves per 1% factor move)
- Regime-conditional correlations (correlations change in crashes)

Usage::

    from income_desk.scenarios.correlation import compute_live_factor_loadings

    # Compute from real data
    loadings = compute_live_factor_loadings(
        data_service, tickers=["RELIANCE", "TCS", "NIFTY"],
        factor_proxies={"equity": "NIFTY", "commodity": "GLD"},
    )
    # loadings["RELIANCE"].commodity = 0.38 (from real returns, not guessed)
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from income_desk.scenarios.factors import FactorLoading

logger = logging.getLogger(__name__)

# Default factor proxies (tickers that represent each factor)
US_FACTOR_PROXIES = {
    "equity": "SPY",
    "rates": "TLT",
    "volatility": "SPY",   # inverse — we negate returns
    "commodity": "GLD",
    "tech": "QQQ",
    "currency": "SPY",     # placeholder — DXY not in yfinance easily
}

INDIA_FACTOR_PROXIES = {
    "equity": "NIFTY",
    "rates": "NIFTY",      # no bond ETF — use inverse NIFTY as proxy
    "volatility": "NIFTY", # inverse
    "commodity": "NIFTY",  # limited — no MCX in yfinance
    "tech": "INFY",        # IT sector proxy
    "currency": "NIFTY",   # INR moves inversely with NIFTY (FII flows)
}


def compute_correlation_matrix(
    data_service,
    tickers: list[str],
    lookback_days: int = 252,
    min_periods: int = 60,
) -> pd.DataFrame:
    """Compute pairwise correlation matrix from daily returns.

    Args:
        data_service: DataService for OHLCV fetching.
        tickers: List of tickers to correlate.
        lookback_days: Historical window.
        min_periods: Minimum overlapping days required.

    Returns:
        DataFrame with correlation matrix (tickers × tickers).
    """
    from income_desk.registry import MarketRegistry
    reg = MarketRegistry()

    returns_dict: dict[str, pd.Series] = {}
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days + 30)

    for ticker in tickers:
        try:
            df = data_service.get_ohlcv(ticker)
            if df is not None and len(df) > min_periods:
                daily_returns = df["Close"].pct_change().dropna()
                returns_dict[ticker] = daily_returns
        except Exception as e:
            logger.debug("OHLCV fetch failed for %s: %s", ticker, e)

    if len(returns_dict) < 2:
        return pd.DataFrame()

    returns_df = pd.DataFrame(returns_dict)
    return returns_df.corr(min_periods=min_periods)


def compute_live_factor_loadings(
    data_service,
    tickers: list[str],
    market: str = "India",
    lookback_days: int = 252,
) -> dict[str, FactorLoading]:
    """Compute actual factor betas from historical returns.

    Runs OLS regression of each ticker's returns against factor proxy returns
    to get real loadings instead of static guesses.

    Args:
        data_service: DataService for OHLCV.
        tickers: Tickers to compute loadings for.
        market: "India" or "US" — determines factor proxies.
        lookback_days: Historical window.

    Returns:
        Dict of ticker -> FactorLoading with real betas.
    """
    proxies = INDIA_FACTOR_PROXIES if market == "India" else US_FACTOR_PROXIES

    # Fetch all returns (tickers + proxies)
    all_tickers = list(set(tickers) | set(proxies.values()))
    returns: dict[str, pd.Series] = {}

    for t in all_tickers:
        try:
            df = data_service.get_ohlcv(t)
            if df is not None and len(df) > 60:
                returns[t] = df["Close"].pct_change().dropna()
        except Exception:
            pass

    if not returns:
        return {}

    # Build factor return series
    factor_returns: dict[str, pd.Series] = {}
    for factor_name, proxy_ticker in proxies.items():
        if proxy_ticker in returns:
            series = returns[proxy_ticker]
            # Volatility and rates are inverse factors
            if factor_name == "volatility":
                series = -series  # high equity returns = low vol
            elif factor_name == "rates" and market == "India":
                series = -series * 0.3  # rough inverse proxy
            elif factor_name == "currency" and market == "India":
                series = -series * 0.5  # INR weakens when NIFTY falls
            factor_returns[factor_name] = series

    if not factor_returns:
        return {}

    # Align all series to common dates
    factor_df = pd.DataFrame(factor_returns).dropna()

    # Compute betas via OLS for each ticker
    loadings: dict[str, FactorLoading] = {}

    for ticker in tickers:
        if ticker not in returns:
            continue

        ticker_ret = returns[ticker]
        # Align dates
        aligned = pd.concat([ticker_ret.rename("y"), factor_df], axis=1, join="inner").dropna()

        if len(aligned) < 60:
            continue

        y = aligned["y"].values
        X = aligned[list(factor_returns.keys())].values

        # OLS: y = X @ beta + epsilon
        # beta = (X'X)^-1 X'y
        try:
            XtX = X.T @ X
            Xty = X.T @ y
            betas = np.linalg.solve(XtX, Xty)
        except np.linalg.LinAlgError:
            continue

        beta_dict = dict(zip(factor_returns.keys(), betas))

        loadings[ticker] = FactorLoading(
            equity=round(beta_dict.get("equity", 1.0), 3),
            rates=round(beta_dict.get("rates", 0.0), 3),
            volatility=round(beta_dict.get("volatility", 0.0), 3),
            commodity=round(beta_dict.get("commodity", 0.0), 3),
            tech=round(beta_dict.get("tech", 0.0), 3),
            currency=round(beta_dict.get("currency", 0.0), 3),
        )

    return loadings


def compute_tail_correlations(
    data_service,
    tickers: list[str],
    lookback_days: int = 504,
    tail_percentile: float = 5.0,
) -> pd.DataFrame:
    """Compute correlations during tail events (crashes).

    In normal markets, correlations are moderate. During crashes,
    correlations spike toward 1.0 ("all correlations go to 1").
    This computes correlations only on days when the market is in
    the bottom 5th percentile of returns.

    Args:
        data_service: DataService.
        tickers: Tickers to correlate.
        lookback_days: Historical window (2 years for enough tail events).
        tail_percentile: What counts as a "tail" day (5 = bottom 5%).

    Returns:
        Correlation matrix during tail events only.
    """
    returns_dict: dict[str, pd.Series] = {}

    for ticker in tickers:
        try:
            df = data_service.get_ohlcv(ticker)
            if df is not None and len(df) > 100:
                returns_dict[ticker] = df["Close"].pct_change().dropna()
        except Exception:
            pass

    if len(returns_dict) < 2:
        return pd.DataFrame()

    returns_df = pd.DataFrame(returns_dict).dropna()

    # Identify tail days: when average return is in bottom percentile
    avg_return = returns_df.mean(axis=1)
    threshold = np.percentile(avg_return, tail_percentile)
    tail_mask = avg_return <= threshold

    tail_returns = returns_df[tail_mask]

    if len(tail_returns) < 10:
        return pd.DataFrame()  # not enough tail events

    return tail_returns.corr()
