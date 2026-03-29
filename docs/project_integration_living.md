# Integration Guide

> Type: LIVING | Last reviewed: 2026-03-29

How to integrate with income_desk as a library. APIs, broker connections, boundaries, collaboration protocol.

---

## 1. API Surface — Workflow APIs

All workflows follow the same pattern: `function(request, ma) -> response`. Import from `income_desk.workflow`.

| # | Function | Request | Response | Purpose |
|---|----------|---------|----------|---------|
| 1 | `generate_daily_plan` | `DailyPlanRequest` | `DailyPlanResponse` | Pre-market trading plan |
| 2 | `snapshot_market` | `SnapshotRequest` | `MarketSnapshot` | Market state snapshot |
| 3 | `scan_universe` | `ScanRequest` | `ScanResponse` | Screen tickers for opportunities |
| 4 | `rank_opportunities` | `RankRequest` | `RankResponse` | Rank and score trade candidates |
| 5 | `validate_trade` | `ValidateRequest` | `ValidateResponse` | Gate check before execution |
| 6 | `size_position` | `SizeRequest` | `SizeResponse` | Position sizing for account |
| 7 | `price_trade` | `PriceRequest` | `PriceResponse` | Optimal entry price |
| 8 | `monitor_positions` | `MonitorRequest` | `MonitorResponse` | Health check open positions |
| 9 | `adjust_position` | `AdjustRequest` | `AdjustResponse` | Adjustment recommendation |
| 10 | `assess_overnight_risk` | `OvernightRiskRequest` | `OvernightRiskResponse` | Overnight gap risk |
| 11 | `aggregate_portfolio_greeks` | `PortfolioGreeksRequest` | `PortfolioGreeksResponse` | Net portfolio Greeks |
| 12 | `check_portfolio_health` | `HealthRequest` | `HealthResponse` | Portfolio-level risk check |
| 13 | `check_expiry_day` | `ExpiryDayRequest` | `ExpiryDayResponse` | Expiry day actions |
| 14 | `stress_test_portfolio` | `StressTestRequest` | `StressTestResponse` | Scenario stress testing |
| 15 | `run_benchmark` | `BenchmarkRequest` | `BenchmarkResponse` | Performance benchmarking |
| 16 | `generate_daily_report` | `DailyReportRequest` | `DailyReportResponse` | EOD summary report |

### Shared Types

From `income_desk.workflow`: `WorkflowMeta`, `TickerRegime`, `TickerSnapshot`, `TradeProposal`, `BlockedTrade`, `OpenPosition`, `PositionStatus`.

### Direct Service APIs

For lower-level access (not recommended for integrators):

```python
from income_desk import MarketAnalyzer, DataService
ma = MarketAnalyzer(data_service=DataService())

ma.regime.detect('SPY')           # Regime detection
ma.ranking.rank(['SPY', 'GLD'])   # Trade ranking
ma.screening.scan(tickers)        # Screening
ma.levels.analyze('SPY')          # Support/resistance
ma.plan.generate()                # Daily plan
```

---

## 2. Broker Integrations

### Supported Brokers

| Broker | Market | SDK | Connect Function | SaaS Variant |
|--------|--------|-----|-----------------|--------------|
| TastyTrade | US | `tastytrade` | `connect_tastytrade()` | `connect_from_sessions()` |
| Alpaca | US | `alpaca-py` | `connect_alpaca(api_key, secret)` | `connect_alpaca_from_session()` |
| IBKR | US/Global | `ib_insync` | `connect_ibkr(host, port)` | `connect_ibkr_from_session()` |
| Schwab | US | `schwab-py` | `connect_schwab(app_key, secret, token_path)` | `connect_schwab_from_session()` |
| Zerodha | India | `kiteconnect` | `connect_zerodha(api_key, access_token)` | `connect_zerodha_from_session()` |
| Dhan | India | `dhanhq` | `connect_dhan(client_id, access_token)` | `connect_dhan_from_session()` |

All brokers return the same 4-tuple: `(market_data, market_metrics, account, watchlist)`.

### Connection Patterns

**Standalone** (CLI, scripts):
```python
from income_desk.broker.tastytrade import connect_tastytrade
md, mm, acct, wl = connect_tastytrade(is_paper=True)
ma = MarketAnalyzer(data_service=DataService(), market_data=md, market_metrics=mm)
```

**Embedded** (SaaS/eTrading — caller manages auth):
```python
from income_desk.broker.tastytrade import connect_from_sessions
md, mm, acct, wl = connect_from_sessions(sdk_session, data_session)
```

### Market Data Sources

| Source | Provides | Trust Level |
|--------|----------|------------|
| Broker (DXLink) | Live quotes, Greeks, IV | HIGH — real-time |
| yfinance | Historical OHLCV, chain structure | MEDIUM — delayed |
| No broker | Regime, technicals, screening (no Greeks) | LOW — no options data |

---

## 3. Library Boundaries

### income_desk does (stateless computation)

- Regime detection, technical analysis, screening
- Trade ranking, scoring, opportunity assessment
- Position sizing, risk metrics, portfolio Greeks
- Adjustment recommendations, exit signals
- Performance analytics (given outcomes)

### Caller/eTrading does (stateful orchestration)

- Authentication, session management, token refresh
- Order execution, fill tracking, position storage
- P&L history, trade outcome persistence
- Tenant isolation, user management (SaaS)
- Risk enforcement gates (E01-E10)

### The critical boundary

**`rank()` output is NOT safe to execute directly.** It ranks on market merit only -- no position awareness. Before execution, the caller MUST:

1. `filter_trades_with_portfolio()` -- check concentration, correlation
2. `validate_trade()` -- gate check (EV, quality score, liquidity)
3. `size_position()` -- fit to account size
4. `validate_execution_quality()` -- spread/OI check

---

## 4. Collaboration Protocol

### `.collab/` Channel

Cross-repo communication between eTrading and income_desk.

| Direction | File Pattern | Purpose |
|-----------|-------------|---------|
| eTrading -> ID | `REQUEST_<topic>.md` | Feature requests, integration specs |
| ID -> eTrading | `FEEDBACK_<topic>.md` | API changes, recommendations |
| Shared | `CONTRACT_<topic>.md` | Agreed interfaces both repos depend on |

### Retrospection Contract

eTrading writes `etrading_retrospection_input.json` to `~/.income_desk/retrospection/`. income_desk reads it, performs analysis, writes `id_retrospection_feedback.json` back. Supports daily, weekly, monthly timeframes.

---

## 5. Integration Checklist

For any system consuming income_desk:

### Setup
- [ ] `pip install income_desk` (or `pip install -e ".[dev]"` from source)
- [ ] Python 3.12 (hmmlearn requires it)
- [ ] Set broker env vars (`TASTYTRADE_USER`, `DHAN_TOKEN`, etc.)

### Connect Broker
- [ ] Call `connect_*()` for your broker -> get 4-tuple
- [ ] Pass `market_data` and `market_metrics` to `MarketAnalyzer`
- [ ] Without broker: regime/technicals work, options pricing returns `None`

### Daily Trading Flow
- [ ] Pre-market: `generate_daily_plan()` + `snapshot_market()`
- [ ] Scan: `scan_universe()` -> `rank_opportunities()`
- [ ] Entry: `validate_trade()` -> `size_position()` -> `price_trade()`
- [ ] Monitor: `monitor_positions()` loop (every 1-5 min)
- [ ] Adjust: `adjust_position()` when health degrades
- [ ] EOD: `assess_overnight_risk()` + `generate_daily_report()`

### Gates Before Execution (caller owns these)
- [ ] E01: Position count limit
- [ ] E02: Per-ticker concentration
- [ ] E03: Strategy concentration
- [ ] E04: Sector concentration
- [ ] E05: Correlation check
- [ ] E06: Portfolio VaR limit
- [ ] E07: Greeks limits (delta, theta, vega)
- [ ] E08: Margin utilization < 80%
- [ ] E09: Drawdown circuit breaker
- [ ] E10: Macro regime gate

### India Market Differences
- No multi-leg orders -- execute legs individually with rollback
- Lot sizes vary per instrument (read `TradeSpec.lot_size`)
- Currency in INR (`TradeSpec.currency`)
- Dhan tokens expire daily -- refresh before 9:15 IST
