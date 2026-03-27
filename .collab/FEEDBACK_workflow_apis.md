# FEEDBACK: Workflow APIs — 15 High-Level Trading Operations

**From:** income-desk
**To:** eTrading
**Date:** 2026-03-27
**Status:** SHIPPED

## Summary

15 workflow APIs in `income_desk.workflow`. Each is one function call with Pydantic request/response. All rate limiting, caching, and orchestration handled internally.

## Quick Start

```python
from income_desk import MarketAnalyzer, DataService
from income_desk.broker.dhan import connect_dhan

# Setup (once per session)
md, mm, acct, wl = connect_dhan()
ma = MarketAnalyzer(data_service=DataService(), market_data=md, market_metrics=mm)

# Pre-market: What should I trade today?
from income_desk.workflow import generate_daily_plan, DailyPlanRequest
plan = generate_daily_plan(
    DailyPlanRequest(tickers=["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "INFY"], capital=5_000_000, market="India"),
    ma,
)
# plan.proposed_trades = [TradeProposal(rank=1, ticker="TCS", structure="iron_condor", ...)]

# Live data: batch refresh
from income_desk.workflow import snapshot_market, SnapshotRequest
snap = snapshot_market(SnapshotRequest(tickers=portfolio_tickers, include_chains=True), ma)
# snap.tickers["NIFTY"].price = 23003.85, .regime_id = 4, .atr_pct = 2.07

# Portfolio risk by underlying
from income_desk.workflow import aggregate_portfolio_greeks, PortfolioGreeksRequest
from income_desk.workflow.portfolio_greeks import PositionLeg
greeks = aggregate_portfolio_greeks(PortfolioGreeksRequest(legs=all_legs), ma)
# greeks.by_underlying["NIFTY"].net_delta = +0.0, .net_theta = +200/day
```

## All 15 Workflows

### Pre-Market
| Function | Request | Response | Purpose |
|----------|---------|----------|---------|
| `generate_daily_plan()` | `DailyPlanRequest` | `DailyPlanResponse` | Full plan: health check + rank + validate + size |
| `snapshot_market()` | `SnapshotRequest` | `MarketSnapshot` | Batch prices, IV, regime for all tickers |

### Scanning & Selection
| Function | Request | Response | Purpose |
|----------|---------|----------|---------|
| `scan_universe()` | `ScanRequest` | `ScanResponse` | Screen tickers against regime + technical filters |
| `rank_opportunities()` | `RankRequest` | `RankResponse` | Rank, POP, size trade proposals |

### Trade Entry
| Function | Request | Response | Purpose |
|----------|---------|----------|---------|
| `validate_trade()` | `ValidateRequest` | `ValidateResponse` | 10-check validation gate |
| `size_position()` | `SizeRequest` | `SizeResponse` | Kelly sizing with lot-size |
| `price_trade()` | `PriceRequest` | `PriceResponse` | Live quotes + entry price |

### Position Management
| Function | Request | Response | Purpose |
|----------|---------|----------|---------|
| `monitor_positions()` | `MonitorRequest` | `MonitorResponse` | Exit signals, theta, P&L |
| `adjust_position()` | `AdjustRequest` | `AdjustResponse` | Adjustment recommendation |
| `assess_overnight_risk()` | `OvernightRiskRequest` | `OvernightRiskResponse` | EOD risk for held positions |

### Portfolio Risk
| Function | Request | Response | Purpose |
|----------|---------|----------|---------|
| `aggregate_portfolio_greeks()` | `PortfolioGreeksRequest` | `PortfolioGreeksResponse` | Delta/gamma/theta/vega by underlying |
| `check_portfolio_health()` | `HealthRequest` | `HealthResponse` | Sentinel, regime distribution, risk budget |

### Expiry & Calendar
| Function | Request | Response | Purpose |
|----------|---------|----------|---------|
| `check_expiry_day()` | `ExpiryDayRequest` | `ExpiryDayResponse` | Expiry-day urgency, close-before-close |

### Reporting
| Function | Request | Response | Purpose |
|----------|---------|----------|---------|
| `generate_daily_report()` | `DailyReportRequest` | `DailyReportResponse` | EOD summary with P&L |

## Key Integration Notes

1. **All workflows accept a pre-built `MarketAnalyzer`** — create once, reuse for all calls
2. **`market_data` and `market_metrics` are now stored on MarketAnalyzer** as public attributes
3. **`snapshot_market()` with `include_chains=True`** throttles Dhan at 3.5s per ticker
4. **`generate_daily_plan()`** returns `is_safe_to_trade=False` if sentinel is RED — eTrading should respect this
5. **`aggregate_portfolio_greeks()`** needs per-leg Greeks from broker — eTrading extracts these from Dhan chain
6. **All responses include `WorkflowMeta`** with `as_of`, `market`, `data_source`, `warnings`
