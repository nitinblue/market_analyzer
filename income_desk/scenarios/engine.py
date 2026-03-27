"""Scenario Engine — apply macro scenarios to baseline market data.

Takes real/simulated market data as baseline, applies factor-based shocks
with correlations and IV response, produces a NEW SimulatedMarketData
with stressed prices, IV, and Greeks.

For eTrading: the flow is identical to normal — you get a MarketDataProvider
back. The only difference is the prices/IV/Greeks are stressed.

    baseline_ma = MarketAnalyzer(...)          # normal
    stressed_sim = apply_scenario(baseline.market_data, "sp500_down_10")
    stressed_ma = MarketAnalyzer(..., market_data=stressed_sim)  # stressed
    plan = generate_daily_plan(request, stressed_ma)              # same API
"""
from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from income_desk.adapters.simulated import SimulatedMarketData
from income_desk.scenarios.definitions import SCENARIOS, ScenarioDef
from income_desk.scenarios.factors import FactorModel

logger = logging.getLogger(__name__)


@dataclass
class ScenarioResult:
    """Result of applying a scenario to baseline data."""
    scenario_name: str
    scenario_description: str
    severity: str
    baseline_tickers: int
    stressed_tickers: int
    # Per-ticker impact
    ticker_impacts: dict[str, TickerImpact]
    # Portfolio-level summary
    portfolio_return_pct: float     # weighted average return
    max_loss_ticker: str
    max_loss_pct: float
    max_gain_ticker: str
    max_gain_pct: float
    avg_iv_change: float            # average IV change (absolute)
    # Monte Carlo (if run)
    mc_5th_percentile: float | None = None
    mc_95th_percentile: float | None = None
    mc_median: float | None = None
    mc_paths: int = 0
    # Metadata
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class TickerImpact:
    """Impact on a single ticker from a scenario."""
    ticker: str
    base_price: float
    stressed_price: float
    return_pct: float
    base_iv: float
    stressed_iv: float
    iv_change: float                # absolute change
    factor_contribution: dict[str, float]  # which factors drove this move
    # Monte Carlo confidence interval
    mc_p5_price: float | None = None
    mc_p95_price: float | None = None


class ScenarioEngine:
    """Apply macro scenarios to market data using factor model + Monte Carlo.

    The engine:
    1. Computes expected return per ticker from factor loadings × shocks
    2. Adjusts IV using leverage effect + direct vol shock
    3. Runs Monte Carlo with correlated noise for confidence intervals
    4. Produces a new SimulatedMarketData with stressed params
    """

    def __init__(self, factor_model: FactorModel | None = None) -> None:
        self.factor_model = factor_model or FactorModel()

    # ── Correlation matrix for Monte Carlo ──────────────────────────

    # Simplified factor correlation matrix (6×6)
    # Rows/cols: equity, rates, volatility, commodity, tech, currency
    _FACTOR_CORR = np.array([
        [ 1.00, -0.30, -0.70,  0.15,  0.85,  0.10],  # equity
        [-0.30,  1.00,  0.20, -0.10, -0.25,  0.20],  # rates
        [-0.70,  0.20,  1.00, -0.05, -0.60, -0.05],  # volatility
        [ 0.15, -0.10, -0.05,  1.00,  0.10, -0.30],  # commodity
        [ 0.85, -0.25, -0.60,  0.10,  1.00,  0.05],  # tech
        [ 0.10,  0.20, -0.05, -0.30,  0.05,  1.00],  # currency
    ])

    _FACTOR_NAMES = ["equity", "rates", "volatility", "commodity", "tech", "currency"]

    def apply(
        self,
        baseline: SimulatedMarketData,
        scenario: ScenarioDef,
        run_monte_carlo: bool = True,
        seed: int | None = None,
    ) -> tuple[SimulatedMarketData, ScenarioResult]:
        """Apply a scenario to baseline data.

        Args:
            baseline: Current market data (real or simulated).
            scenario: Scenario definition with factor shocks.
            run_monte_carlo: Run MC simulation for confidence intervals.
            seed: Random seed for reproducibility.

        Returns:
            (stressed_sim, result) — new SimulatedMarketData + analysis report.
        """
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

        tickers = baseline.supported_tickers() if hasattr(baseline, 'supported_tickers') else list(baseline._tickers.keys())
        stressed_params: dict[str, dict] = {}
        impacts: dict[str, TickerImpact] = {}

        for ticker in tickers:
            info = baseline._tickers.get(ticker, {})
            base_price = info.get("price", 100.0)
            base_iv = info.get("iv", 0.20)
            base_iv_rank = info.get("iv_rank", 50.0)
            base_atr_pct = info.get("atr_pct", 1.0)

            # --- Factor-based return ---
            expected_return = self.factor_model.compute_return(ticker, scenario.factor_shocks)

            # Factor contribution breakdown
            loading = self.factor_model.get_loading(ticker)
            ld = loading.as_dict()
            factor_contrib = {}
            for fn, shock in scenario.factor_shocks.items():
                beta = ld.get(fn, 0.0)
                factor_contrib[fn] = round(beta * shock * 100, 2)  # contribution in %

            # Stressed price
            stressed_price = round(base_price * (1 + expected_return), 2)
            stressed_price = max(stressed_price, base_price * 0.01)  # floor at 1% of base

            # --- IV response ---
            stressed_iv = self.factor_model.compute_iv_response(
                ticker, base_iv, expected_return,
                vol_shock=scenario.factor_shocks.get("volatility", 0.0),
            )
            stressed_iv += scenario.iv_regime_shift
            stressed_iv = max(0.05, min(1.50, stressed_iv))

            # IV rank: spike toward 90+ in crashes, compress in rallies
            if expected_return < -0.05:
                stressed_iv_rank = min(98, base_iv_rank + abs(expected_return) * 300)
            elif expected_return > 0.05:
                stressed_iv_rank = max(5, base_iv_rank - expected_return * 200)
            else:
                stressed_iv_rank = base_iv_rank + scenario.factor_shocks.get("volatility", 0) * 30

            # ATR: increases with vol
            vol_mult = 1 + scenario.factor_shocks.get("volatility", 0) * 0.5
            stressed_atr = base_atr_pct * max(0.5, vol_mult)

            stressed_params[ticker] = {
                "price": stressed_price,
                "iv": round(stressed_iv, 4),
                "iv_rank": round(min(100, max(0, stressed_iv_rank)), 1),
                "atr_pct": round(stressed_atr, 2),
                "beta": info.get("beta", 1.0),
                "liquidity": info.get("liquidity", 4.0),
            }

            impact = TickerImpact(
                ticker=ticker,
                base_price=base_price,
                stressed_price=stressed_price,
                return_pct=round(expected_return * 100, 2),
                base_iv=base_iv,
                stressed_iv=round(stressed_iv, 4),
                iv_change=round(stressed_iv - base_iv, 4),
                factor_contribution=factor_contrib,
            )
            impacts[ticker] = impact

        # --- Monte Carlo for confidence intervals ---
        if run_monte_carlo and scenario.monte_carlo_paths > 0:
            self._run_monte_carlo(baseline, scenario, tickers, impacts)

        # --- Build stressed SimulatedMarketData ---
        stressed_sim = SimulatedMarketData(
            stressed_params,
            account_nlv=baseline._account_nlv,
            account_cash=baseline._account_cash,
            account_bp=baseline._account_bp,
            currency=baseline._currency,
            timezone=baseline._timezone,
            lot_size_default=baseline._lot_size_default,
        )

        # --- Build result summary ---
        returns = [imp.return_pct for imp in impacts.values()]
        iv_changes = [imp.iv_change for imp in impacts.values()]
        worst = min(impacts.values(), key=lambda i: i.return_pct)
        best = max(impacts.values(), key=lambda i: i.return_pct)

        result = ScenarioResult(
            scenario_name=scenario.name,
            scenario_description=scenario.description,
            severity=scenario.severity,
            baseline_tickers=len(tickers),
            stressed_tickers=len(stressed_params),
            ticker_impacts=impacts,
            portfolio_return_pct=round(sum(returns) / len(returns), 2) if returns else 0,
            max_loss_ticker=worst.ticker,
            max_loss_pct=worst.return_pct,
            max_gain_ticker=best.ticker,
            max_gain_pct=best.return_pct,
            avg_iv_change=round(sum(iv_changes) / len(iv_changes), 4) if iv_changes else 0,
        )

        return stressed_sim, result

    def _run_monte_carlo(
        self,
        baseline: SimulatedMarketData,
        scenario: ScenarioDef,
        tickers: list[str],
        impacts: dict[str, TickerImpact],
    ) -> None:
        """Run Monte Carlo simulation with correlated factor shocks."""
        n_paths = scenario.monte_carlo_paths
        n_factors = len(self._FACTOR_NAMES)

        # Cholesky decomposition of correlation matrix
        try:
            L = np.linalg.cholesky(self._FACTOR_CORR)
        except np.linalg.LinAlgError:
            # If correlation matrix is not PD, use diagonal
            L = np.eye(n_factors)

        # Generate correlated random shocks
        # Each path: 6 correlated random factor perturbations around the scenario shocks
        Z = np.random.standard_normal((n_paths, n_factors))
        correlated_Z = Z @ L.T  # Apply correlation structure

        # Scale noise: ~20% of the shock magnitude as dispersion
        base_shocks = np.array([scenario.factor_shocks.get(f, 0.0) for f in self._FACTOR_NAMES])
        noise_scale = np.maximum(np.abs(base_shocks) * 0.3, 0.01)

        for ticker in tickers:
            loading = self.factor_model.get_loading(ticker)
            ld = loading.as_dict()
            betas = np.array([ld.get(f, 0.0) for f in self._FACTOR_NAMES])

            base_price = baseline._tickers.get(ticker, {}).get("price", 100.0)

            # Each path: perturbed return = betas · (base_shocks + noise)
            perturbed_shocks = base_shocks + correlated_Z * noise_scale
            path_returns = perturbed_shocks @ betas  # (n_paths,)
            path_prices = base_price * (1 + path_returns)

            impacts[ticker].mc_p5_price = round(float(np.percentile(path_prices, 5)), 2)
            impacts[ticker].mc_p95_price = round(float(np.percentile(path_prices, 95)), 2)


def apply_scenario(
    baseline: SimulatedMarketData,
    scenario_key: str,
    run_monte_carlo: bool = True,
    seed: int | None = 42,
) -> tuple[SimulatedMarketData, ScenarioResult]:
    """Convenience: apply a named scenario to baseline market data.

    Args:
        baseline: Current market data (from create_india_trading(), etc.)
        scenario_key: Key from SCENARIOS dict (e.g. "sp500_down_10").
        run_monte_carlo: Run MC for confidence intervals.
        seed: Random seed (42 for reproducibility, None for random).

    Returns:
        (stressed_sim, result) — use stressed_sim as market_data for workflows.

    Example::

        from income_desk.scenarios import apply_scenario
        from income_desk.adapters.simulated import create_india_trading

        baseline = create_india_trading()
        stressed, result = apply_scenario(baseline, "nifty_down_10")

        # Print impact
        for t, imp in result.ticker_impacts.items():
            print(f"{t}: {imp.return_pct:+.1f}% IV: {imp.base_iv:.0%} -> {imp.stressed_iv:.0%}")

        # Use with workflows (same API as normal)
        ma = MarketAnalyzer(data_service=DataService(), market_data=stressed, ...)
        plan = generate_daily_plan(request, ma)
    """
    if scenario_key not in SCENARIOS:
        available = ", ".join(sorted(SCENARIOS.keys()))
        raise ValueError(f"Unknown scenario: {scenario_key!r}. Available: {available}")

    engine = ScenarioEngine()
    return engine.apply(baseline, SCENARIOS[scenario_key], run_monte_carlo=run_monte_carlo, seed=seed)
