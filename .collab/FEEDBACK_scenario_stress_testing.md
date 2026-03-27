# FEEDBACK: Scenario Stress Testing Engine — 18 Macro Scenarios

**From:** income-desk
**To:** eTrading
**Date:** 2026-03-27
**Status:** SHIPPED

## What It Does

Takes baseline market data, applies macro scenario shocks using a factor model with correlations, produces stressed `SimulatedMarketData` that works with all 15 workflows. eTrading flow is identical — just swap the market_data provider.

## Quick Start

```python
from income_desk.scenarios import apply_scenario
from income_desk.adapters.simulated import create_india_trading, SimulatedMetrics

# 1. Get baseline
baseline = create_india_trading()

# 2. Apply scenario — produces new SimulatedMarketData
stressed, result = apply_scenario(baseline, "nifty_down_10")

# 3. Use stressed data with any workflow (same API)
from income_desk import MarketAnalyzer, DataService
ma = MarketAnalyzer(data_service=DataService(), market_data=stressed, market_metrics=SimulatedMetrics(stressed))
plan = generate_daily_plan(DailyPlanRequest(...), ma)

# 4. Inspect impact
for ticker, impact in result.ticker_impacts.items():
    print(f"{ticker}: {impact.return_pct:+.1f}% | IV: {impact.base_iv:.0%} -> {impact.stressed_iv:.0%}")
    print(f"  MC 5th: {impact.mc_p5_price:,.0f}  MC 95th: {impact.mc_p95_price:,.0f}")
```

## Available Scenarios (18)

| Key | Name | Severity | Category |
|-----|------|----------|----------|
| `sp500_down_5` | S&P 500 -5% Correction | mild | crash |
| `sp500_down_10` | S&P 500 -10% Correction | moderate | crash |
| `sp500_down_20` | S&P 500 -20% Bear Market | severe | crash |
| `black_monday` | Black Monday (-30% Flash Crash) | extreme | crash |
| `nifty_down_10` | NIFTY -10% + INR Depreciation | moderate | crash |
| `rbi_rate_hike` | RBI Surprise Rate Hike | mild | macro |
| `fii_selloff` | FII Mass Selling | moderate | crash |
| `gold_crash_10` | Gold -10% Crash | moderate | crash |
| `commodity_meltup` | Commodity Super-Cycle Meltup | moderate | rally |
| `rates_shock_up` | 10Y Yield +100bp Spike | moderate | macro |
| `rates_collapse` | Rate Collapse / Flight to Safety | moderate | macro |
| `inflation_surge` | Inflation Surge (CPI +2%) | moderate | macro |
| `deflation_scare` | Deflation Scare | mild | macro |
| `tech_rotation` | Tech-to-Value Rotation | moderate | rotation |
| `risk_on_rally` | Risk-On Rally (+8%) | moderate | rally |
| `india_budget_rally` | India Budget Rally | mild | rally |
| `correlation_1` | Correlation Spike (All Assets Down) | extreme | crash |
| `geopolitical_shock` | Geopolitical Shock | severe | macro |

## Integration with portfolio_greeks workflow

Run stressed scenario, then check portfolio Greeks impact:

```python
# Step 1: stress the market
stressed, result = apply_scenario(baseline, "sp500_down_20")

# Step 2: re-price portfolio Greeks under stress
ma_stressed = MarketAnalyzer(data_service=DataService(), market_data=stressed, ...)
greeks = aggregate_portfolio_greeks(PortfolioGreeksRequest(legs=my_legs), ma_stressed)

# Step 3: compare stressed Greeks vs baseline Greeks
# -> see if portfolio is protected or exposed
```

## Factor Model (6 factors, 38 tickers)

Each ticker has loadings on: equity, rates, volatility, commodity, tech, currency.
Scenarios shock factors, loadings determine per-ticker impact. Correlation matrix ensures realistic co-movement (equity-tech corr=0.85, equity-vol corr=-0.70).

Monte Carlo with Cholesky decomposition provides 5th/95th percentile confidence intervals.
