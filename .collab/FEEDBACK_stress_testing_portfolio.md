# FEEDBACK: Portfolio Stress Testing — 18 Scenario Risk Engine

**From:** income-desk
**To:** eTrading
**Date:** 2026-03-27
**Status:** SHIPPED

## What It Does

One workflow call runs ALL 18 macro scenarios against your live portfolio. Returns risk score, worst-case loss, per-scenario P&L, most vulnerable positions.

## Integration (one call)

```python
from income_desk.workflow import stress_test_portfolio, StressTestRequest
from income_desk.workflow._types import OpenPosition

# eTrading builds positions from DB
positions = [
    OpenPosition(trade_id="TCS-IC", ticker="TCS", structure_type="iron_condor",
                 order_side="credit", entry_price=3.0, current_mid_price=1.8,
                 contracts=5, lot_size=150, dte_remaining=3, regime_id=1),
    # ... all open positions
]

result = stress_test_portfolio(
    StressTestRequest(
        positions=positions,
        capital=5_000_000,
        market="India",
        risk_limit_pct=0.30,
    ),
    ma,
)
```

## What eTrading Gets Back

```python
result.risk_score               # "safe" / "caution" / "danger" / "critical"
result.worst_scenario           # "black_monday"
result.worst_scenario_pnl       # -8814
result.portfolio_at_risk        # 8814 (worst-case loss)
result.scenarios_breaching_limit  # ["black_monday"] if any breach 30%

# Per-scenario table (for Risk Dashboard):
for sr in result.scenario_results:
    sr.scenario_name            # "Black Monday (-30% Flash Crash)"
    sr.portfolio_pnl            # -8814
    sr.portfolio_pnl_pct        # -0.2%
    sr.breaches_limit           # True/False
    sr.worst_position           # "INFY"
    sr.position_impacts         # per-position detail

# Most vulnerable positions (for alerts):
result.most_vulnerable_positions
# [{"ticker": "INFY", "avg_scenario_loss": -970, "worst_scenario": "black_monday"}]
```

## Where to Wire in eTrading

| eTrading Component | How to Use |
|-------------------|-----------|
| **Risk Dashboard** | Table of 18 scenarios, color by severity, P&L per scenario |
| **Pre-trade gate** | Before approving trade: re-run with proposed trade added. Block if breaches limit. |
| **Daily risk report** | Run at EOD, store results, track risk_score trend |
| **Alert system** | If `risk_score == "danger"` or `"critical"` → notify trader |
| **Position sizing** | If adding a trade pushes worst-case past limit → reduce size |

## 18 Scenarios Available

**Crashes:** sp500_down_5/10/20, black_monday, nifty_down_10, fii_selloff
**Macro:** rbi_rate_hike, rates_shock_up, rates_collapse, inflation_surge, deflation_scare
**Commodity:** gold_crash_10, commodity_meltup, geopolitical_shock
**Rotation:** tech_rotation, risk_on_rally, india_budget_rally
**Tail:** correlation_1 (all assets down)

## Run Specific Scenarios Only

```python
# Run only crash scenarios (faster)
result = stress_test_portfolio(
    StressTestRequest(
        positions=positions,
        scenarios=["sp500_down_10", "nifty_down_10", "black_monday"],
    ),
    ma,
)
```

## Factor Model Details

6 macro factors (equity, rates, volatility, commodity, tech, currency) with 38 ticker loadings. Correlation matrix ensures realistic co-movement. IV response includes leverage effect (vol spikes on down moves).

Historical correlation calculator available: `compute_live_factor_loadings()` computes real betas from OHLCV data to replace static estimates.
