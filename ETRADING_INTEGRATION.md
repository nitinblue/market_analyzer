# market_analyzer Integration Guide for eTrading

**Date:** 2026-03-12 | **Package:** `market_analyzer` at `C:\Users\nitin\PythonProjects\market_analyzer`

---

## What's New

Three new modules added to `market_analyzer` for eTrading consumption:

| Module | Purpose |
|--------|---------|
| `trade_spec_factory` | Create TradeSpec objects from broker data (DXLink symbols, raw legs) |
| `trade_lifecycle` | Pure-function APIs for the full trade lifecycle (POP, yield, breakevens, exit monitoring, health checks) |
| `TradeSpec.strategy_symbol` / `strategy_badge` | Compact trade identification ("IC", "IC neutral · defined") |

Everything is importable from `market_analyzer` top-level.

---

## 1. DXLink Symbol <-> TradeSpec Conversion

**This is the bridge.** eTrading reads positions from broker as DXLink symbols. Convert them to TradeSpec for all analytics.

```python
from market_analyzer import from_dxlink_symbols, to_dxlink_symbols, parse_dxlink_symbol

# Broker position -> TradeSpec
spec = from_dxlink_symbols(
    symbols=[".GLD260417P455", ".GLD260417P450",
             ".GLD260417C480", ".GLD260417C485"],
    actions=["STO", "BTO", "STO", "BTO"],
    underlying_price=466.88,
    entry_price=0.72,        # from fill data
)
# Auto-detects: structure_type="iron_condor", order_side="credit", wing_width=5.0

# TradeSpec -> DXLink symbols (for streamer subscriptions)
symbols = to_dxlink_symbols(spec)  # ['.GLD260417P455', ...]

# Parse single symbol
parsed = parse_dxlink_symbol(".GLD260417P455")
# {'ticker': 'GLD', 'expiration': date(2026,4,17), 'option_type': 'put', 'strike': 455.0}
```

**Auto-detection** works for: iron_condor, iron_butterfly, iron_man, credit_spread, calendar, diagonal, straddle. Pass `structure_type=` explicitly to override.

**Also available:** `create_trade_spec()` from raw leg dicts, and builders: `build_iron_condor()`, `build_credit_spread()`, `build_debit_spread()`, `build_calendar()`.

---

## 2. Trade Lifecycle APIs

All functions are **pure computation** — no state, no broker calls, no data fetching. eTrading provides inputs, market_analyzer returns results.

### Pre-Trade Analysis

```python
from market_analyzer import (
    compute_income_yield,   # F5: ROC, annualized yield, credit/width
    compute_breakevens,     # F8: breakeven prices
    estimate_pop,           # F7: regime-based probability of profit
    check_income_entry,     # F10: is now the right time to sell premium?
    filter_trades_by_account,  # F4: remove trades exceeding account limits
    align_strikes_to_levels,   # F6: snap strikes to S/R levels
)

# Income Yield — after getting a fill
yield_info = compute_income_yield(spec, entry_credit=0.72, contracts=1)
# -> IncomeYield: credit_to_width_pct=0.144, return_on_capital_pct=0.168,
#    annualized_roc_pct=1.71, max_profit=72.0, max_loss=428.0,
#    breakeven_low=217.28, breakeven_high=225.72

# Breakevens — works for IC, credit spread, debit spread, straddle/strangle
be = compute_breakevens(spec, entry_price=0.72)
# -> Breakevens: low=217.28, high=225.72

# POP — regime-adjusted, NOT Black-Scholes
pop = estimate_pop(spec, entry_price=0.72, regime_id=1,
                   atr_pct=1.2, current_price=221.0)
# -> POPEstimate: pop_pct=0.59, expected_value=12.50, method="regime_historical"

# Income Entry Check — should I sell premium right now?
entry = check_income_entry(
    iv_rank=45.0, iv_percentile=50.0, dte=35,
    rsi=50.0, atr_pct=1.2, regime_id=1,
    has_earnings_within_dte=False,
)
# -> IncomeEntryCheck: confirmed=True, score=0.85, conditions=[...]

# Account Filter — remove trades exceeding $30K account limits
filtered = filter_trades_by_account(
    ranked_entries=ranking_result.top_trades,
    available_buying_power=24000.0,
    allowed_structures=["iron_condor", "credit_spread", "calendar"],
    max_risk_per_trade=1500.0,
)
# -> FilteredTrades: affordable=[...], filtered_out=[...]
```

### At Entry

```python
from market_analyzer import aggregate_greeks

# Greeks Aggregation — net portfolio Greeks from broker quotes
greeks = aggregate_greeks(spec, leg_quotes=broker_option_quotes, contracts=2)
# -> AggregatedGreeks: net_delta=0.03, net_gamma=0.00, net_theta=0.04,
#    net_vega=-0.10, daily_theta_dollars=8.00
```

### Position Monitoring

```python
from market_analyzer import monitor_exit_conditions, check_trade_health

# Exit Monitoring — check all exit rules against current state
result = monitor_exit_conditions(
    trade_id="GLD-IC-001", ticker="GLD",
    structure_type="iron_condor", order_side="credit",
    entry_price=0.72, current_mid_price=0.35,  # from broker
    contracts=1, dte_remaining=25, regime_id=1,
    profit_target_pct=0.50, stop_loss_pct=2.0, exit_dte=21,
    entry_regime_id=1,  # optional: detect regime changes
)
# -> ExitMonitorResult: should_close=True, pnl_pct=0.51,
#    summary="CLOSE: profit_target hit (51% >= 50%)",
#    signals=[ExitSignal(rule="profit_target", triggered=True, ...)]

# Trade Health — combined exit monitoring + adjustment recommendation
health = check_trade_health(
    trade_id="GLD-IC-001", trade_spec=spec,
    entry_price=0.72, contracts=1,
    current_mid_price=0.55, dte_remaining=30,
    regime=regime_result,         # from ma.regime.detect()
    technicals=technical_snapshot, # from ma.technicals.snapshot()
)
# -> TradeHealthCheck: status="healthy"|"warning"|"critical",
#    overall_action="hold"|"adjust"|"close",
#    exit_result=ExitMonitorResult, adjustment=AdjustmentAnalysis
```

### Adjustment Recommendation

```python
from market_analyzer import get_adjustment_recommendation

adj = get_adjustment_recommendation(
    trade_spec=spec,
    regime=regime_result,
    technicals=technical_snapshot,
    vol_surface=vol_surface,  # optional
)
# -> AdjustmentAnalysis: position_status, adjustments=[AdjustmentOption, ...]
```

---

## 3. TradeSpec Properties

Every TradeSpec now carries:

```python
spec.strategy_symbol    # "IC", "CS", "DS", "CAL", "IFly", "RS", ...
spec.strategy_badge     # "IC neutral · defined", "CS directional · defined"
spec.dxlink_symbols     # [".GLD260417P455", ...] for broker subscriptions
spec.streamer_symbols   # OCC-padded symbols
spec.leg_codes          # ["STO 1x GLD P455 4/17/26", ...]
spec.order_data         # Machine-readable dicts for order routing
spec.exit_summary       # "TP 50% | SL 2x credit | close <=21 DTE"
spec.position_size(capital=30000)  # Suggested contracts for account size
```

---

## 4. Existing APIs (unchanged, still available)

```python
from market_analyzer import MarketAnalyzer, DataService

ma = MarketAnalyzer(data_service=DataService(), market_data=..., market_metrics=...)

# All existing services work as before:
ma.regime.detect("GLD")           # RegimeResult
ma.technicals.snapshot("GLD")     # TechnicalSnapshot
ma.context.assess()               # MarketContext
ma.ranking.rank(tickers, skip_intraday=True)  # TradeRankingResult
ma.levels.analyze("GLD")          # LevelsAnalysis
ma.black_swan.alert()             # BlackSwanAlert
ma.quotes.get_chain("GLD")       # QuoteSnapshot (needs broker)
ma.quotes.get_leg_quotes(legs)    # list[OptionQuote] (needs broker)
ma.adjustment.analyze(spec, regime, technicals)  # AdjustmentAnalysis
```

---

## 5. Integration Workflow

```
eTrading Trading Loop:

1. DAILY SCAN
   ma.context.assess() -> safe to trade?
   ma.ranking.rank(tickers) -> ranked opportunities
   filter_trades_by_account() -> affordable ones

2. PRE-ENTRY (for each candidate)
   compute_income_yield(spec) -> capital efficiency
   estimate_pop(spec) -> probability of profit
   compute_breakevens(spec) -> profit zone
   check_income_entry() -> entry timing

3. AT ENTRY
   from_dxlink_symbols() -> TradeSpec from fill
   aggregate_greeks(spec, quotes) -> portfolio Greeks
   portfolio.book_trade(spec, price, contracts)

4. DAILY MONITORING (for each open position)
   from_dxlink_symbols() -> TradeSpec from position
   monitor_exit_conditions() -> close/hold/adjust?
   check_trade_health() -> full health + adjustment

5. AT EXIT
   portfolio.close_trade(id, exit_price, reason)
```

---

## 6. The `challenge/` Folder

**Reference only -- do NOT import from it.**

| File | What it is | Use as |
|------|-----------|--------|
| `challenge/trader.py` | End-to-end demo calling all APIs, scanning real markets, filtering by $30K constraints | **Code reference** for integration workflow (what to call, in what order) |
| `challenge/portfolio.py` | YAML-backed portfolio tracker (book/close/risk checks) | **Concept reference** -- eTrading has its own portfolio management |
| `challenge/models.py` | Demo models (TradeRecord, RiskLimits, PortfolioStatus) | **Concept reference** -- eTrading has its own models |

eTrading only imports from `market_analyzer.*`. The challenge folder shows the complete flow as working code.

---

## 7. Architecture: Who Decides What

**market_analyzer is the brain. eTrading is the hands.**

All computation, analysis, and decision-making lives in market_analyzer. eTrading is a workflow orchestrator -- it reads broker state, calls market_analyzer APIs, and executes orders. eTrading should NEVER compute POP, breakevens, regime, adjustments, or trade health itself.

```
eTrading (workflow + execution)          market_analyzer (computation + decisions)
====================================    ==========================================
Reads positions from broker         --> from_dxlink_symbols() creates TradeSpec
Reads account balance               --> filter_trades_by_account() checks affordability
Gets current mid price from DXLink  --> monitor_exit_conditions() says CLOSE or HOLD
Gets regime + technicals            --> check_trade_health() says healthy/warning/critical
Gets IV rank from broker            --> check_income_entry() says CONFIRMED or NOT
Gets option chain quotes            --> aggregate_greeks() computes net Greeks
Sends order to broker               <-- TradeSpec.order_data has exact leg specs
```

### Decision Flow

```
               market_analyzer DECIDES               eTrading EXECUTES
               ========================               ==================

SCAN:          "Is today safe to trade?"              Calls ma.context.assess()
               "What are the best trades?"            Calls ma.ranking.rank()
               "Can this account afford it?"          Calls filter_trades_by_account()

ANALYZE:       "What's the yield?"                    Calls compute_income_yield()
               "What's the POP?"                      Calls estimate_pop()
               "Where are breakevens?"                Calls compute_breakevens()
               "Is entry timing right?"               Calls check_income_entry()

ENTER:         "How many contracts?"                  Calls spec.position_size()
               "What are portfolio Greeks?"            Calls aggregate_greeks()
               -- eTrading sends order --              Uses spec.order_data

MONITOR:       "Should I close this?"                 Calls monitor_exit_conditions()
               "Is this position healthy?"             Calls check_trade_health()
               "What adjustment should I make?"        Calls get_adjustment_recommendation()

EXIT:          "Close at profit target"               eTrading sends closing order
               "Roll the tested side"                 Uses adjustment.legs for new order
```

### What eTrading Should NOT Do

- Do NOT compute POP, breakevens, or yield -- call market_analyzer
- Do NOT decide whether to trade based on regime -- call `check_income_entry()`
- Do NOT decide when to exit -- call `monitor_exit_conditions()`
- Do NOT decide adjustments -- call `get_adjustment_recommendation()`
- Do NOT compute Greeks aggregation -- call `aggregate_greeks()`
- Do NOT filter trades by account size -- call `filter_trades_by_account()`

eTrading's job: read broker state, pass it to market_analyzer, execute the decision.

---

## 8. CLI Commands (analyzer-cli)

market_analyzer ships an interactive REPL (`analyzer-cli`) that exposes **every** API. eTrading can use these as reference implementations. The CLI is NOT directly callable from eTrading — eTrading must import the Python APIs. The CLI shows what data each API needs and what it returns.

### CLI Command -> Python API Mapping

eTrading needs to wire its own UI/workflow to these APIs. Each CLI command below is a working reference for the plumbing.

| CLI Command | Python API | What eTrading Must Provide | What It Gets Back |
|------------|-----------|---------------------------|-------------------|
| `context` | `ma.context.assess()` | Nothing | MarketContext (environment, trading_allowed, black_swan) |
| `regime TICKER` | `ma.regime.detect(ticker)` | ticker | RegimeResult (regime_id, confidence, probabilities) |
| `technicals TICKER` | `ma.technicals.snapshot(ticker)` | ticker | TechnicalSnapshot (RSI, ATR, MACD, Bollinger, etc.) |
| `levels TICKER` | `ma.levels.analyze(ticker)` | ticker | LevelsAnalysis (support, resistance, stop, target) |
| `analyze TICKER` | `ma.instrument.analyze(ticker)` | ticker | InstrumentAnalysis (regime + phase + technicals + levels) |
| `screen TICKERS` | `ma.screening.scan(tickers)` | ticker list | ScreeningResult (candidates with scores) |
| `rank TICKERS [--account N]` | `ma.ranking.rank(tickers)` + `filter_trades_by_account()` | tickers, optional BP | TradeRankingResult + FilteredTrades |
| `plan [TICKERS]` | `ma.plan.generate(tickers)` | tickers (optional) | DailyTradingPlan (verdict, risk budget, trades by horizon) |
| `opportunity TICKER [play]` | `ma.opportunity.assess_*(ticker)` | ticker, play type | Opportunity result + TradeSpec + analytics |
| `setup TICKER [type]` | `ma.opportunity.assess_breakout/momentum/mr/orb(ticker)` | ticker, setup type | Setup result with TradeSpec |
| `strategy TICKER` | `ma.strategy.select(ticker, regime, technicals)` | ticker | StrategyParameters + PositionSize |
| `entry TICKER TYPE` | `ma.entry.confirm(ticker, trigger)` | ticker, trigger type | EntryConfirmation (confirmed, confidence, conditions) |
| `vol TICKER` | `ma.vol_surface.surface(ticker)` | ticker | VolatilitySurface (term structure, skew, calendar edge) |
| `quotes TICKER` | `ma.quotes.get_chain(ticker)` | ticker | QuoteSnapshot + MarketMetrics + aggregate Greeks |
| `adjust TICKER` | `ma.adjustment.analyze(spec, regime, tech)` | TradeSpec | AdjustmentAnalysis + exit signals |
| `yield TICKER CREDIT` | `compute_income_yield(spec, credit)` | TradeSpec, credit | IncomeYield (ROC, annualized, breakevens) |
| `pop TICKER PRICE` | `estimate_pop(spec, price, regime_id, atr_pct, price)` | TradeSpec, regime, technicals | POPEstimate (pop_pct, EV) |
| `income_entry TICKER` | `check_income_entry(iv_rank, dte, rsi, atr_pct, regime_id)` | metrics from broker | IncomeEntryCheck (confirmed, score, conditions) |
| `parse SYMBOLS ACTIONS` | `from_dxlink_symbols(symbols, actions, price)` | DXLink symbols, actions | TradeSpec (auto-detected structure) |
| `monitor TICKER ENTRY CUR DTE` | `monitor_exit_conditions(...)` | entry price, current mid, DTE | ExitMonitorResult (should_close, signals) |
| `health TICKER ENTRY CUR DTE` | `check_trade_health(...)` | TradeSpec, prices, regime, technicals | TradeHealthCheck (status, action, exit + adjust) |
| `greeks TICKER` | `aggregate_greeks(spec, leg_quotes)` | TradeSpec, broker leg quotes | AggregatedGreeks (net delta/gamma/theta/vega) |
| `size TICKER CAPITAL` | `spec.position_size(capital)` | TradeSpec, capital | Number of contracts |
| `balance` | `ma.account_provider.get_balance()` | broker connection | AccountBalance |
| `stress` | `ma.black_swan.alert()` | Nothing | BlackSwanAlert (level, score, indicators) |
| `macro` | `ma.macro.calendar()` | Nothing | MacroCalendar (events, FOMC, etc.) |
| `exit_plan TICKER PRICE` | `ma.exit.plan(ticker, strategy, ...)` | ticker, entry price | ExitPlan (targets, stops, adjustments) |
| `broker` | Connection status | broker connection | Capabilities, account info |

### eTrading Plumbing Required

eTrading does NOT get these CLI commands for free. It must:

1. **Initialize MarketAnalyzer** with broker connections:
```python
from market_analyzer import MarketAnalyzer, DataService
from market_analyzer.broker.tastytrade import connect_tastytrade

market_data, market_metrics, account_provider = connect_tastytrade()
ma = MarketAnalyzer(
    data_service=DataService(),
    market_data=market_data,
    market_metrics=market_metrics,
    account_provider=account_provider,
)
```

2. **Wire each workflow step** to the appropriate API calls. The CLI's `_show_trade_analytics()` method is a good template — it chains yield + breakevens + POP + entry check + S/R alignment + position sizing into one output for each TradeSpec.

3. **Provide broker data** that market_analyzer needs but doesn't fetch:
   - Current mid price for open positions (from DXLink `Quote`)
   - Leg quotes with Greeks (from `ma.quotes.get_leg_quotes(legs)`)
   - IV rank/percentile (from `ma.quotes.get_metrics(ticker)`)
   - Account balance/BP (from `ma.account_provider.get_balance()`)

4. **Own the state**: portfolio positions, trade history, fill data. market_analyzer is stateless.

5. **Convert broker positions to TradeSpec** using `from_dxlink_symbols()` — this is the critical bridge.

### Data Flow: eTrading -> market_analyzer -> eTrading

```
eTrading reads broker position:
  symbols = [".GLD260417P455", ".GLD260417P450", ...]
  actions = ["STO", "BTO", ...]
  fill_price = 0.72
  current_mid = 0.35

  |
  v

market_analyzer converts:
  spec = from_dxlink_symbols(symbols, actions, price, entry_price=fill_price)
  regime = ma.regime.detect("GLD")
  tech = ma.technicals.snapshot("GLD")

  |
  v

market_analyzer computes:
  yield_info = compute_income_yield(spec, fill_price)
  pop = estimate_pop(spec, fill_price, regime.regime, tech.atr_pct, tech.current_price)
  exit_check = monitor_exit_conditions(..., current_mid_price=current_mid)
  health = check_trade_health(..., current_mid_price=current_mid, regime=regime, technicals=tech)
  greeks = aggregate_greeks(spec, ma.quotes.get_leg_quotes(spec.legs))
  contracts = spec.position_size(capital=account_balance)

  |
  v

eTrading acts on results:
  if exit_check.should_close:
      send_closing_order(spec.order_data)
  elif health.adjustment_needed:
      send_adjustment_order(health.adjustment_options[0])
```

---

## 9. Watchlist Integration (NEW)

market_analyzer now supports pulling ticker universes from TastyTrade watchlists via the `WatchlistProvider` ABC.

### Setup

Create these watchlists in TastyTrade (via the app or API):

| Watchlist Name | Purpose | Suggested Tickers |
|---------------|---------|-------------------|
| `MA-Income` | Core income universe (~25) | SPY, QQQ, IWM, DIA, GLD, SLV, TLT, EFA, HYG, XLE, XLF, XLK, AAPL, MSFT, AMZN, GOOGL, META, NVDA, AMD, TSLA, JPM, BAC, XOM, UNH, HD |
| `MA-Sectors` | Sector rotation (~12) | XLF, XLE, XLK, XLV, XLI, XLP, XLU, XLY, XLRE, XLC, XLB, SMH |
| `MA-Macro` | Reference only (context) | SPY, TLT, GLD, HYG, VIX |

### Python API

```python
from market_analyzer.broker.tastytrade import connect_tastytrade

market_data, metrics, account, watchlist = connect_tastytrade()

# List all watchlists
names = watchlist.list_watchlists()  # ["[private] MA-Income", "[public] Popular ETFs", ...]

# Get tickers from a watchlist
tickers = watchlist.get_watchlist("MA-Income")  # ["SPY", "QQQ", "IWM", ...]

# Merge multiple watchlists (deduped)
all_tickers = watchlist.get_multiple_watchlists(["MA-Income", "MA-Sectors"])

# Use in screening (two-phase scan)
candidates = ma.screening.scan(tickers)         # Phase 1: fast screen
result = ma.ranking.rank(candidate_tickers)      # Phase 2: deep analysis
filtered = filter_trades_by_account(result.top_trades, available_buying_power=24000)
```

### CLI

```
analyzer-cli --broker
> watchlist                         # list all watchlists
> watchlist MA-Income               # show tickers in watchlist
> screen --watchlist MA-Income      # screen all tickers in watchlist
> rank --watchlist MA-Income --account 30000
> regime --watchlist MA-Sectors     # regime scan across sectors
```

### Two-Phase Scan Pattern

For large universes (40+ tickers), use a two-phase approach:

```python
# Phase 1: Fast screen (~2 min for 40 tickers)
tickers = watchlist.get_watchlist("MA-Income")
screen_result = ma.screening.scan(tickers)
candidates = [c.ticker for c in screen_result.candidates if c.score >= 0.5]

# Phase 2: Deep analysis (candidates only, ~1 min)
rank_result = ma.ranking.rank(candidates, skip_intraday=True)
filtered = filter_trades_by_account(rank_result.top_trades, available_buying_power=bp)

# Phase 3: Per-trade analytics
for entry in filtered.affordable:
    spec = entry.trade_spec
    yield_info = compute_income_yield(spec, spec.max_entry_price)
    pop = estimate_pop(spec, spec.max_entry_price, regime_id, atr_pct, price)
    entry_check = check_income_entry(iv_rank, iv_pctl, dte, rsi, atr_pct, regime_id)
```

---

## 10. Key Constraints (for eTrading developers)

- **No BS pricing.** All option prices come from broker (DXLink). Without broker, price fields are None.
- **Pure functions.** trade_lifecycle APIs have no state, no side effects. eTrading owns all state.
- **Regime required.** POP, entry checks, and health checks need regime_id. Always detect regime first.
- **TradeSpec is the contract.** Every API takes or returns TradeSpec. Use `from_dxlink_symbols()` to create them from broker data.
- **Position sizing is on TradeSpec.** Call `spec.position_size(capital=30000)` to get contract count for any account size.
- **Aggregate Greeks need broker quotes.** Call `ma.quotes.get_leg_quotes(spec.legs)` first, then `aggregate_greeks(spec, quotes)`.

---

## 10. Imports Cheat Sheet

```python
# TradeSpec creation
from market_analyzer import (
    create_trade_spec, build_iron_condor, build_credit_spread,
    build_debit_spread, build_calendar,
    from_dxlink_symbols, to_dxlink_symbols, parse_dxlink_symbol,
)

# Trade lifecycle (all pure functions)
from market_analyzer import (
    compute_income_yield, compute_breakevens, estimate_pop,
    check_income_entry, filter_trades_by_account, align_strikes_to_levels,
    aggregate_greeks, monitor_exit_conditions, check_trade_health,
    get_adjustment_recommendation,
)

# Models (for type hints)
from market_analyzer import (
    IncomeYield, Breakevens, POPEstimate, IncomeEntryCheck,
    FilteredTrades, AlignedStrikes, AggregatedGreeks,
    ExitMonitorResult, ExitSignal, TradeHealthCheck,
    TradeSpec, LegSpec, LegAction, StructureType, OrderSide,
)

# Broker connection
from market_analyzer.broker.tastytrade import connect_tastytrade
from market_analyzer import MarketAnalyzer, DataService

# Services (MarketAnalyzer facade)
ma = MarketAnalyzer(data_service=DataService(), market_data=md, market_metrics=mm, account_provider=ap)
ma.regime           # RegimeService
ma.technicals       # TechnicalService
ma.context          # MarketContextService
ma.ranking          # TradeRankingService
ma.plan             # TradingPlanService
ma.levels           # LevelsService
ma.black_swan       # BlackSwanService
ma.vol_surface      # VolSurfaceService
ma.opportunity      # OpportunityService
ma.adjustment       # AdjustmentService
ma.quotes           # OptionQuoteService
ma.instrument       # InstrumentAnalysisService
ma.screening        # ScreeningService
ma.entry            # EntryService
ma.strategy         # StrategyService
ma.exit             # ExitService
ma.macro            # MacroService
ma.account_provider # AccountProvider (broker)
```
