# income_desk -- Architecture

> Type: LIVING | Last reviewed: 2026-03-29
> How the system is built. Read time: 10 minutes.

---

## Overview

income_desk is a stateless Python library that detects per-instrument market regimes using Hidden Markov Models, generates ranked options trade recommendations, and provides every analytical building block needed for systematic income trading. It serves as the canonical data + analysis layer for the trading ecosystem -- consumed by eTrading (execution platform), CLI (exploration), and trader_md (markdown-driven trading). The library never stores positions, fills, or session state; callers own all persistence.

---

## Component Diagram

```
income_desk/
|
|-- Engine Layer (core analytics)
|   |-- workflow/          15 workflow APIs (scan, rank, validate, size, monitor, stress...)
|   |-- service/           Service orchestrators (regime, technicals, quotes, levels, macro)
|   |-- scenarios/         18 stress test scenarios (.scenario.md) + parser + runner
|   |-- broker/            6 broker integrations (tastytrade, alpaca, ibkr, schwab, zerodha, dhan)
|   |-- adapters/          CSV import (7 broker formats), dict, simulation data
|   |-- models/            Pydantic models (TradeSpec, RegimeResult, RankedEntry, etc.)
|   |-- features/          Pure function modules (entry, exit, sizing, audit, trust, risk)
|   |-- hmm/               HMM 4-state regime detection
|   |-- opportunity/       Trade assessors (iron condor, vertical, calendar, LEAP, earnings...)
|   |-- validation/        10-check profitability gate + 3-check adversarial suite
|
|-- Trading Paths (two ways to run the engine)
|   |-- trader/            Python path: interactive harness, daily runners (US + India)
|   |-- trader_md/         MD path: parser, runner, 7 format specs, workflow/universe/risk files
|
|-- Supporting
|   |-- benchmarking/      Calibration APIs (POP accuracy, regime accuracy, score-vs-outcome)
|   |-- cli/               67+ commands via interactive REPL (analyzer-cli entry point)
|   |-- data/              DataService, ParquetCache, ProviderRegistry, yfinance provider
|   |-- config/            Settings, RegimeConfig, cache config
|
|-- Domain Modules
|   |-- hedging/           10 modules (direct, proxy, futures, portfolio, monitoring, comparison)
|   |-- macro/             Bond market, credit spreads, dollar strength, inflation, dashboard
|   |-- fundamentals/      Stock analysis (value, growth, dividend, quality, turnaround)
|   |-- scenarios/         Stress testing (18 scenarios, suite runner, portfolio impact)
|   |-- backoffice/        Ops reporting, margin, capital utilization, PnL rollup
|   |-- regression/        Regression test framework (8 domains, 93%+ GREEN)
```

---

## Data Flow: Scan to Execution

```
1. SCAN        ma.workflow.scan_universe(tickers)
               |-- regime.detect(ticker) for each  --> RegimeResult (R1-R4)
               |-- technicals.snapshot(ticker)      --> RSI, ATR, Bollinger, MACD
               |-- opportunity assessors            --> TradeSpec candidates
               v
2. RANK        ma.workflow.rank_opportunities(candidates)
               |-- score each TradeSpec (EV, POP, regime fit, IV rank)
               |-- sort by composite score
               v
3. VALIDATE    ma.workflow.validate_trade(spec)
               |-- 10-check daily suite (commission, fill, margin, POP, EV, entry, exit)
               |-- 3-check adversarial suite (gamma stress, vega shock, breakeven)
               |-- gate framework: BLOCK / SCALE / WARN (17 gates, 3 tiers)
               v
4. SIZE        ma.workflow.size_position(spec, account)
               |-- Kelly criterion sizing
               |-- portfolio filter (max positions, concentration, correlation)
               |-- margin check (cash vs portfolio margin)
               v
5. PRICE       ma.workflow.check_execution_quality(spec, quotes)
               |-- spread width, OI, volume checks
               |-- entry time window enforcement
               v
               TradeSpec ready for broker submission (eTrading handles execution)
```

---

## Broker Abstraction

All broker integrations implement a common set of ABCs defined in `broker/base.py`:

| ABC | Purpose | Required Methods |
|-----|---------|-----------------|
| `MarketDataProvider` | Live quotes, Greeks, intraday bars | `get_option_chain`, `get_quotes`, `get_greeks` |
| `MarketMetricsProvider` | IV rank, beta, liquidity | `get_metrics` |
| `AccountProvider` | Balance, buying power | `get_balance` |
| `WatchlistProvider` | Broker-managed ticker lists | `get_watchlist`, `list_watchlists` |
| `BrokerSession` | Auth lifecycle | `connect`, `disconnect`, `is_connected` |

Six implementations: TastyTrade (DXLink streaming), Alpaca, IBKR, Schwab, Zerodha (Kite REST), Dhan. All are optional -- the library degrades gracefully without any broker connected.

**Data tiers:** Free (yfinance OHLCV, chain structure) -> Broker (real-time quotes, Greeks, IV rank) -> Economic (FRED macro indicators).

---

## Regime Detection

The HMM 4-state model is the core invariant. No trade recommendation is made without a regime label.

| Regime | Name | Character | Primary Strategy |
|--------|------|-----------|-----------------|
| R1 | Low-Vol Mean Reverting | Calm, range-bound | Iron condors, strangles (theta) |
| R2 | High-Vol Mean Reverting | Choppy, wide swings | Wider wings, defined risk |
| R3 | Low-Vol Trending | Quiet trend | Directional spreads |
| R4 | High-Vol Trending | Crisis or breakout | Risk-defined only, long vega |

Detection is per-instrument (SPY can be R1 while GLD is R3). Features: log returns, realized vol, ATR, trend strength, volume anomaly. Model trains on 2 years of OHLCV via `hmmlearn`. Results include state probabilities and confidence.

---

## MD Format (trader_md/)

Seven file types define a complete trading operation in human-readable markdown:

| Format | Purpose | Example |
|--------|---------|---------|
| `.workflow.md` | Trading phases, steps, gates | `us_daily_income.workflow.md` |
| `.scenario.md` | Stress test definitions | `market_crash_severe.scenario.md` |
| `.universe.md` | Ticker lists with metadata | `sp500_liquid.universe.md` |
| `.risk.md` | Risk profile parameters | `moderate.risk.md` |
| `.broker.md` | Broker connection config | `tastytrade_paper.broker.md` |
| `.gate.md` | Custom validation gates | `income_quality.gate.md` |
| `.binding.md` | Variable bindings for workflows | `us_default.binding.md` |

The parser (`trader_md/parser.py`) reads YAML frontmatter + structured sections. The runner (`trader_md/runner.py`) resolves bindings, evaluates gates, and calls workflow APIs. No Python knowledge required to define or modify trading strategies.

---

## Key Design Decisions

1. **Stateless library.** income_desk computes and returns. No positions, fills, or P&L history stored. Callers (eTrading, CLI) own all state.

2. **No module-level mutable state.** All caches, connections, and config are injectable via constructor. Each `MarketAnalyzer` instance is fully isolated.

3. **Additive changes only.** New files preferred over moving existing ones. Backward compatibility is non-negotiable.

4. **Provider failures are not silent.** Typed exceptions (`DataFetchError`, `InvalidTickerError`, `CacheError`) distinguish "no data exists" from "fetch failed." Callers can handle each case explicitly.

5. **No Black-Scholes pricing.** All option prices come from broker via DXLink streamer. If no broker is connected, the value is `None`. Never invented.

6. **Cache before fetch, never serve stale silently.** Parquet cache with 18-hour staleness. Delta-fetch for OHLCV. If cache is stale and fetch fails, raise -- don't silently serve old data.

7. **`rank()` output is NOT safe to execute directly.** It ranks on market merit only. eTrading must call `filter_trades_with_portfolio()` and `evaluate_trade_gates()` before any execution.

8. **Same-ticker hedging only.** No beta-weighted index hedging. SPY position hedged with SPY puts, not VIX calls.

9. **Per-instrument regime.** No global "market regime." Each ticker gets its own HMM state.

10. **Two trading paths, one engine.** `trader/` (Python) and `trader_md/` (markdown) both call the same workflow APIs. Different interfaces, identical analytics.
