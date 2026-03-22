# eTrading Change Request for income_desk
# Date: 2026-03-14 | From: eTrading (Session 41)
# Status: OPEN — Review and implement

## Context

eTrading is integrating MA's new capabilities (trade_lifecycle, TradeSpec factory, adjustment, intraday) to build a fully systematic trading system. See `ETRADING_INTEGRATION.md` for the full plan (26 gaps, 8 phases).

**Architecture principle:** MA is a stateless library. eTrading owns broker connections, passes pre-authenticated sessions via `connect_from_sessions()`. MA receives provider objects, never connects or authenticates.

---

## CR-1: eTrading Will Route ALL Market Data Through MA

### Current Problem
eTrading's `tastytrade_adapter.py` (~1000 lines) makes direct DXLink/broker calls for quotes, Greeks, IV metrics — duplicating what MA already provides via `OptionQuoteService`, `MarketDataProvider`, and `MarketMetricsProvider`.

This creates tight broker coupling. Adding a second broker (Schwab, IBKR) requires rewriting eTrading's adapter, mark-to-market, and trade booking.

### Decision
eTrading will stop calling broker APIs for market data. All market data flows through the `MarketAnalyzer` instance that eTrading already creates.

**eTrading will call MA for:**
| Need | MA API | Replaces (eTrading direct call) |
|------|--------|---------------------------------|
| Option quotes (bid/ask) | `ma.quotes.get_leg_quotes(legs)` | `adapter.get_quotes(symbols)` |
| Option Greeks | `ma.quotes.get_leg_quotes(legs, include_greeks=True)` | `adapter._fetch_greeks_via_dxlink(symbols)` |
| Option chain | `ma.quotes.get_chain(ticker)` | `adapter.get_option_chain(ticker)` |
| IV rank, beta, liquidity | `ma.quotes.get_metrics(ticker)` | `adapter.get_market_metrics(symbols)` |
| Account balance / BP | `ma.account_provider.get_balance()` | `adapter.get_account_balance()` |
| Ticker watchlists | `watchlist_provider.get_watchlist(name)` | hardcoded YAML |

**eTrading will keep direct broker calls ONLY for:**
| Need | Why | Method |
|------|-----|--------|
| Read positions | Portfolio state, not market data | `tastytrade SDK: account.get_positions()` |
| Place/cancel orders | Execution, not analysis | `tastytrade SDK: account.place_order()` |
| Order status/history | Execution tracking | `tastytrade SDK: account.get_orders()` |

### Impact on MA
**None.** MA already provides all these APIs. No code changes needed in MA.

The only ask: ensure `OptionQuoteService.get_leg_quotes()` works reliably for the mark-to-market use case (10-50 legs, every 30 min). The TTL cache (60s) and circuit breaker are already in place — eTrading will rely on them.

---

## CR-2: Confirm Object Contracts for Integration

eTrading's TradeSpec Bridge (`services/tradespec_bridge.py`, G1 DONE) converts `TradeORM + LegORM` → `TradeSpec` via `from_dxlink_symbols()`. This TradeSpec is then passed to all MA trade_lifecycle APIs.

### Contracts eTrading Depends On (please don't break)

| Function | Input Contract | Output Contract | eTrading Usage |
|----------|---------------|-----------------|----------------|
| `from_dxlink_symbols(symbols, actions, price, ...)` | DXLink symbols like `.GLD260417P455`, actions like `STO`/`BTO` | `TradeSpec` with auto-detected structure_type, order_side, wing_width | Reconstructing TradeSpec from DB for monitoring |
| `monitor_exit_conditions(...)` | trade_id, ticker, structure_type, order_side, entry_price, current_mid_price, contracts, dte_remaining, regime_id, profit_target_pct, stop_loss_pct, exit_dte, entry_regime_id, **time_of_day** | `ExitMonitorResult` with should_close, signals, pnl_pct, summary, commentary | Replacing eTrading's homegrown exit monitor |
| `check_trade_health(...)` | trade_id, trade_spec, entry_price, contracts, current_mid_price, dte_remaining, regime, technicals | `TradeHealthCheck` with status (healthy/tested/breached/exit_triggered), overall_action (hold/close/adjust/roll) | Health status tracking per position |
| `recommend_action(trade_spec, regime, technicals, position_status)` | TradeSpec + RegimeResult + TechnicalSnapshot + PositionStatus | `AdjustmentDecision` — single deterministic action | Adjustment pipeline (no menus) |
| `validate_execution_quality(trade_spec, quotes)` | TradeSpec + list of OptionQuote | `ExecutionQuality` with GO/WIDE_SPREAD/ILLIQUID/NO_QUOTE | New Maverick gate for liquidity |
| `assess_overnight_risk(trade_spec, regime, technicals, dte)` | TradeSpec + RegimeResult + TechnicalSnapshot + int | `OvernightRisk` with risk_level, reasons | EOD risk check |
| `estimate_pop(spec, entry_price, regime_id, atr_pct, current_price)` | TradeSpec + regime + technicals data | `POPEstimate` with pop_pct, expected_value | Maverick POP gate |
| `check_income_entry(iv_rank, iv_percentile, dte, rsi, atr_pct, regime_id, has_earnings)` | Scalar market conditions | `IncomeEntryCheck` with confirmed, score, conditions | Maverick income entry gate |
| `compute_income_yield(spec, entry_credit, contracts)` | TradeSpec + fill price | `IncomeYield` with ROC, annualized, breakevens | Stored at entry |
| `compute_breakevens(spec, entry_price)` | TradeSpec + fill price | `Breakevens` with low, high | Stored at entry |
| `filter_trades_by_account(ranked, available_bp, allowed_structures, max_risk)` | RankedEntry list + account params | `FilteredTrades` with affordable, filtered_out | Pre-gate filter |
| `spec.position_size(capital, risk_pct, max_contracts)` | Capital + risk params | `int` (contracts) | Position sizing |

### Request
If any of these signatures or return types change, please update `ETRADING_INTEGRATION.md` so we stay in sync. Breaking changes to these APIs will break eTrading's bridge and monitoring pipeline.

---

## CR-3: Awaiting MA Phase 2 (Intelligence)

eTrading has gaps that are blocked on MA's remaining work:

| eTrading Gap | Needs MA Gap | What eTrading Needs | Priority |
|---|---|---|---|
| G24 (Performance Feedback) | MA-G07 | `TradeOutcome` model + `compute_strategy_performance()` + `calibrate_weights()`. eTrading stores closed trade outcomes — MA computes performance metrics and recalibrates strategy weights. Pure functions, eTrading passes data in. | HIGH |
| G25 (Learning Mode) | MA-G08 | `commentary: list[str]` on RegimeResult, TechnicalSnapshot, RankedEntry, OpportunityResult. Populated when `debug=True` is passed to analysis calls. eTrading stores commentary in `decision_lineage` JSON for "explain this trade" feature. | HIGH |
| G26 (Data Gap Awareness) | MA-G09 | `data_gaps: list[DataGap]` on RankedEntry, PlanTrade, OpportunityResult. Each assessor flags where analysis is weak. eTrading uses this to discount confidence and surface gaps in UI. | MEDIUM |

### TradeOutcome Model (for MA-G07)

eTrading already captures this data in `TradeEventORM`. Here's what we can provide to MA:

```python
# eTrading will build this from closed trades and pass to MA
class TradeOutcome:
    trade_id: str
    ticker: str
    structure_type: str          # iron_condor, credit_spread, etc.
    order_side: str              # credit, debit
    regime_at_entry: int         # R1-R4
    regime_at_exit: int          # R1-R4
    iv_rank_at_entry: float      # 0-100
    dte_at_entry: int
    dte_at_exit: int
    entry_price: float           # net credit/debit
    exit_price: float
    contracts: int
    realized_pnl: float          # dollars
    pnl_pct: float               # % of max risk
    outcome: str                 # WIN / LOSS
    exit_reason: str             # profit_target, stop_loss, dte_exit, regime_change, manual
    days_held: int
    max_favorable_excursion: float   # best P&L during hold (if tracked)
    max_adverse_excursion: float     # worst P&L during hold (if tracked)
```

**Please define the canonical `TradeOutcome` model in MA** and we'll conform to it. The key requirement: MA's `calibrate_weights()` must be a pure function — eTrading passes outcomes, MA returns adjusted weights. No state in MA.

---

## CR-4: Commentary Format (for MA-G08)

For the learning mode / decision lineage feature, eTrading needs structured commentary from MA.

### Proposed Format

```python
# On every MA result model that supports debug=True:
commentary: list[str] = []   # Empty when debug=False, populated when debug=True

# Example: RegimeResult with debug=True
RegimeResult(
    regime=RegimeID.R1,
    confidence=0.82,
    commentary=[
        "HMM fitted on 252 trading days of GLD daily returns",
        "State means: R1=0.04%, R2=0.08%, R3=-0.12%, R4=-0.25%",
        "Current state probabilities: R1=0.82, R2=0.15, R3=0.02, R4=0.01",
        "R1 selected: highest posterior probability (0.82 > 0.5 threshold)",
        "Confidence: 0.82 (R1 probability) — HIGH",
        "Trend: bullish (3-day return positive, above SMA-20)",
    ]
)
```

### How eTrading Will Use It
- Pass `debug=True` to all MA calls during scan/propose
- Collect commentary from each service (regime, technicals, ranking, opportunity)
- Store in `TradeORM.decision_lineage` JSON as:
  ```json
  {
    "gates": [...],
    "commentary": {
      "regime": ["HMM fitted on 252 days...", ...],
      "technicals": ["RSI 48 — neutral...", ...],
      "ranking": ["Score 0.78 — breakdown: ...", ...],
      "opportunity": ["Iron condor selected because...", ...]
    }
  }
  ```
- API endpoint `GET /trades/{id}/explain` returns this full lineage
- Frontend renders it as an expandable decision tree

### Request
Please add `debug: bool = False` parameter to these MA service methods:
- `ma.regime.detect(ticker, debug=False)`
- `ma.technicals.snapshot(ticker, debug=False)`
- `ma.ranking.rank(tickers, debug=False)`
- `ma.opportunity.assess_*(ticker, debug=False)`
- `ma.context.assess(debug=False)`

And add `commentary: list[str]` field to: `RegimeResult`, `TechnicalSnapshot`, `TradeRankingResult`, `RankedEntry`, `MarketContext`, and all opportunity result models.

---

## CR-5: Data Gap Model (for MA-G09)

### Proposed Model

```python
class DataGap:
    field: str          # "iv_rank", "earnings_date", "option_chain", etc.
    reason: str         # "broker not connected", "yfinance timeout", "no data for ticker"
    impact: str         # "low" / "medium" / "high"
    affects: str        # "POP estimate", "entry timing", "position sizing"
```

### Where eTrading Needs It
- `RankedEntry.data_gaps` — before booking, know what's missing
- `PlanTrade.data_gaps` — daily plan quality assessment
- `ExitMonitorResult.data_gaps` — know if exit decision is degraded
- `TradeHealthCheck.data_gaps` — know if health assessment is degraded

eTrading will use `data_gaps` to:
1. Reduce confidence score in Maverick gates (high-impact gap → lower confidence)
2. Display warning badges in frontend
3. Log in decision_lineage for post-mortem

---

## Summary: What eTrading Needs from MA

| # | What | Priority | MA Gap | Status |
|---|------|----------|--------|--------|
| CR-1 | No changes needed — MA already provides all market data APIs | — | — | N/A |
| CR-2 | Don't break listed API contracts | CRITICAL | — | Ongoing |
| CR-3 | TradeOutcome + calibrate_weights() | HIGH | MA-G07 | **DONE** (2026-03-14) |
| CR-4 | commentary + debug=True on all services | HIGH | MA-G08 | **DONE** (2026-03-14) |
| CR-5 | data_gaps on RankedEntry, PlanTrade, ExitMonitorResult | MEDIUM | MA-G09 | **DONE** (2026-03-14) |

**All CRs complete.** Implementation details:

**CR-3:** `TradeOutcome` extended with `structure_type`, `order_side`, `iv_rank_at_entry`, `dte_at_entry`, `dte_at_exit`, `max_favorable_excursion`, `max_adverse_excursion` (all optional). `StrategyPerformance` has `avg_dte_at_entry` and `avg_iv_rank_at_entry`. `calibrate_weights()` is a pure function — eTrading passes outcomes, MA returns weight adjustments.

**CR-4:** `debug=True` wired to `regime.detect()`, `technicals.snapshot()`, `context.assess()`, `ranking.rank()`. Each populates `commentary: list[str]` with step-by-step reasoning. `TechnicalSnapshot` and `MarketContext` models now have `commentary` + `data_gaps` fields.

**CR-5:** `DataGap` has new `affects` field. `data_gaps: list[DataGap]` added to `ExitMonitorResult` and `TradeHealthCheck`. All fields default to `[]` for backward compat.
