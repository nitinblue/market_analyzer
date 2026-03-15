# MA Gap Tracker

**Goal:** MA enables a fully systematic trading system that makes money — and gets smarter over time.

**Boundary:** MA is stateless. eTrading passes context in, MA computes and returns. eTrading owns all state (outcomes, bandit params, drift history).

**Stats:** 1331 tests passing. 259 in test_systematic.py.

---

## Master Status

| # | Category | Gap | MA Status | eTrading Integration |
|---|----------|-----|-----------|---------------------|
| G01 | Infrastructure | Deterministic adjustment | **DONE** | Call `recommend_action()` or `check_trade_health()` — returns single action, no menu. |
| G02 | Infrastructure | Execution quality validation | **DONE** | Call `validate_execution_quality(spec, quotes)` before order submission. Block if not GO. |
| G03 | Infrastructure | Entry time windows | **DONE** | Read `spec.entry_window_start/end`. Only submit orders within window. |
| G04 | Infrastructure | Time-of-day urgency | **DONE** | Pass `time_of_day=datetime.now().time()` to `monitor_exit_conditions()` and `check_trade_health()`. |
| G05 | Infrastructure | Overnight risk | **DONE** | Auto-invoked in `check_trade_health()` after 15:00. Read `health.overnight_risk`. |
| G06 | Infrastructure | Auto-select screening | **DONE** | `scan(tickers, min_score=0.6, top_n=10)` — low-quality candidates auto-filtered. |
| G07 | Intelligence | Performance feedback | **DONE** | **Build pipeline:** closed trades → `TradeOutcome` → `compute_performance_report()`. Store outcomes in DB. Run weekly. |
| G08 | Intelligence | Debug/commentary | **DONE** | Pass `debug=True` to `detect()`, `snapshot()`, `assess()`, `rank()`. Store `result.commentary` in `decision_lineage` JSON. |
| G09 | Intelligence | Data gap identification | **DONE** | Read `result.data_gaps` on every RankedEntry/PlanTrade. Discount confidence for high-impact gaps. Surface in UI. |
| SQ1 | Signal Quality | IV rank in assessors | **DONE** | **Pass `iv_rank`** from `ma.quotes.get_metrics(ticker)` to `assess_iron_condor(iv_rank=)`, `assess_leap(iv_rank=)`, etc. Without it → DataGap flagged. |
| SQ2 | Signal Quality | HMM staleness | **DONE** | Check `regime.model_age_days`. If > 60 → call `ma.regime.fit(ticker)` to retrain. Check `regime.data_gaps` for stale/uncertain warnings. |
| SQ3 | Signal Quality | POP with IV + calibration | **DONE** | Pass `iv_rank=` to `estimate_pop()`. Run `calibrate_pop_factors(outcomes)` weekly → store calibrated factors. |
| TA1-TA6 | Technicals | Fibonacci, ADX, Donchian, Keltner, Pivots, VWAP | **DONE** | No action — flows through existing `TechnicalSnapshot`. Available as `tech.fibonacci`, `tech.adx`, `tech.donchian`, `tech.keltner`, `tech.pivot_points`, `tech.daily_vwap`. |
| SQ4-SQ8 | Signal Quality | MR overhaul, breakout, earnings, screening, momentum | **DONE** | No action — assessor improvements are internal. Better signals, same API. |
| SQ9 | Signal Quality | IV rank in ranking | **DONE** | **Build `iv_rank_map`** from broker metrics per ticker. Pass to `rank(iv_rank_map={...})`. |
| SQ10 | Technicals | Pivots in levels | **DONE** | No action — pivot points auto-included in `ma.levels.analyze()` as S/R sources. |
| ML1 | Learning | Drift detection | **DONE** | **Schedule daily:** `detect_drift(outcomes)`. If CRITICAL → suspend strategy cell. If WARNING → halve position size. Store alerts. |
| ML2 | Learning | Thompson Sampling | **DONE** | **Store `StrategyBandit` per cell.** On close: `update_bandit(bandit, won)`. Daily: `select_strategies(bandits, regime)` → use in `rank(strategies=)`. |
| ML3 | Learning | Threshold optimization | **DONE** | **Schedule monthly:** `optimize_thresholds(outcomes)`. Store `ThresholdConfig`. Apply as Settings override to MA services. |
| CR6 | Multi-Market | Dhan + Zerodha broker stubs | **DONE** | Wire pre-authenticated sessions via `connect_dhan_from_session()` / `connect_zerodha_from_session()`. INR, Asia/Kolkata, lot_size=25. |
| CR7 | Multi-Market | Currency + timezone + lot_size | **DONE** | Pass correct `lot_size` per instrument from `MarketRegistry`. All `* 100` → `* lot_size` in trade_lifecycle. |
| CR8 | Multi-Market | India strategy config | **DONE** | Config-driven via `IndiaStrategyDefaults`. No eTrading action needed. |
| CR9 | Multi-Market | India regime detection | **DONE** | Works out of box — `regime.detect("NIFTY")` via yfinance alias. No eTrading action. |
| CR10 | Multi-Market | Timezone-aware entry windows | **DONE** | Read `entry_window_timezone` from TradeSpec. Convert to local time in platform scheduler. |
| CR11 | Analytics | Sharpe, drawdown, regime perf | **DONE** | Call `compute_sharpe(outcomes)`, `compute_drawdown(outcomes)`, `compute_regime_performance(outcomes)`. Render in dashboard. |
| CR12 | Multi-Market | India ticker mapping | **DONE** | Auto-resolved — NIFTY/BANKNIFTY/FINNIFTY/SENSEX aliases in DataService. No eTrading action. |
| CR13 | Multi-Market | MarketRegistry static data | **DONE** | Call `ma.registry.get_instrument()` for lot sizes, `strategy_available()` for routing, `estimate_margin()` for sizing. |
| CR14 | SaaS | Cache isolation | **DONE** | Verified: OptionQuoteService cache is per-instance. Each MarketAnalyzer instance is isolated. |
| CR15 | SaaS | Lightweight init | **DONE** | Verified: MarketAnalyzer.__init__ only instantiates services. No data fetching, no network. Lazy. |
| CR16 | SaaS | Token expiry | **DONE** | `TokenExpiredError` exception. `is_token_valid()` on BrokerSession + MarketDataProvider (default True). 2 tests. |
| CR17 | SaaS | Rate limits | **DONE** | `rate_limit_per_second` + `supports_batch` on MarketDataProvider. Dhan=25, Zerodha=3. 3 tests. |
| H1 | Hedging | Currency conversion + portfolio exposure | **DONE** | `convert_amount()`, `compute_portfolio_exposure()`. CurrencyPair, PositionExposure, PortfolioExposure models. 6 tests. |
| H2 | Hedging | Same-ticker hedge assessment | **DONE** | `assess_hedge()` — regime-aware: R1=no hedge, R2=collar, R4=protective put/close. 5 position types. 8 tests. |
| H3 | Hedging | Currency hedge assessment | **DONE** | `assess_currency_exposure()` — FX risk %, recommendation at 10%/30% thresholds. 2 tests. |
| H4 | Hedging | Cross-market P&L decomposition | **DONE** | `compute_currency_pnl()` — trading P&L vs FX P&L breakdown. 4 tests. |
| H5 | Hedging | CLI commands | **DONE** | `hedge TICKER [TYPE]`, `currency AMOUNT FROM TO`, `exposure`. 44 total CLI commands. |

---

## eTrading Pickup List

Everything below is eTrading's responsibility. MA APIs are ready — eTrading must wire them.

### Immediate (Wire Now — APIs Ready)

| # | What eTrading Must Do | MA API | Priority |
|---|----------------------|--------|----------|
| E1 | Pass `iv_rank` to all assessor calls | `ma.quotes.get_metrics(ticker).iv_rank` → pass to `assess_*(iv_rank=)` | **HIGH** |
| E2 | Pass `iv_rank_map` to ranking | Build `{ticker: iv_rank}` dict → `rank(iv_rank_map=...)` | **HIGH** |
| E3 | Pass `time_of_day` to health check | `check_trade_health(..., time_of_day=datetime.now().time())` | **HIGH** |
| E4 | Pass `debug=True` and store commentary | `detect(debug=True)`, store `result.commentary` in decision_lineage JSON | **HIGH** |
| E5 | Read `data_gaps` and surface in UI | `result.data_gaps` on every RankedEntry/PlanTrade → discount confidence, show warnings | **HIGH** |
| E6 | Call `validate_execution_quality()` before orders | `validate_execution_quality(spec, quotes)` → block if not GO | **HIGH** |
| E7 | Respect `entry_window_start/end` on TradeSpec | Only submit orders within `spec.entry_window_start` to `spec.entry_window_end` | **MEDIUM** |
| E8 | Read `entry_window_timezone` for India trades | Convert window times to local timezone for scheduler | **MEDIUM** |
| E9 | Use `ma.registry` for lot sizes and strategy routing | `registry.get_instrument()` for lot_size, `strategy_available()` to skip LEAP in India | **HIGH** |
| E10 | Check `regime.model_age_days` and retrain | If > 60 → call `ma.regime.fit(ticker)` | **MEDIUM** |
| E11 | Pass `lot_size` correctly for India trades | TradeSpec.lot_size, monitor_exit_conditions(lot_size=) | **HIGH** |
| E12 | Call `assess_hedge()` for open positions | Daily or on regime change → show hedge recommendation | **MEDIUM** |
| E13 | Pass FX rates to `compute_currency_pnl()` | For cross-market P&L decomposition in dashboard | **MEDIUM** |

### Build Pipeline (Requires DB + Scheduling)

| # | What eTrading Must Build | MA API | Frequency |
|---|-------------------------|--------|-----------|
| E14 | TradeOutcome table + construction on close | `TradeOutcome` model — capture regime/IV/score at entry | On every close |
| E15 | Bandit params table + update on close | `update_bandit(bandit, won)` | On every close |
| E16 | Drift detection job | `detect_drift(outcomes)` → suspend/reduce | Daily pre-market |
| E17 | Bandit strategy selection in daily plan | `select_strategies(bandits, regime)` → pass to `rank(strategies=)` | Daily plan |
| E18 | Weight calibration job | `calibrate_weights(outcomes)` → apply overrides | Weekly |
| E19 | POP factor calibration job | `calibrate_pop_factors(outcomes)` → store | Weekly |
| E20 | Threshold optimization job | `optimize_thresholds(outcomes)` → apply as config | Monthly |
| E21 | Performance dashboard | `compute_performance_report()`, `compute_sharpe()`, `compute_drawdown()`, `compute_regime_performance()` | Monthly |

### SaaS Infrastructure

| # | What eTrading Must Handle | MA Provides | Notes |
|---|--------------------------|-------------|-------|
| E22 | Per-user MarketAnalyzer instance | Cache is per-instance (CR-14 verified) | Don't share instances across users |
| E23 | Token refresh for India brokers | `TokenExpiredError`, `is_token_valid()` | Dhan/Zerodha tokens expire daily |
| E24 | Rate limiting for India brokers | `rate_limit_per_second` on provider | Zerodha: 3/sec, Dhan: 25/sec |
| E25 | Broker connection UI per user | `connect_dhan_from_session()`, `connect_zerodha_from_session()` | Stubs ready, API impl pending |
| E26 | Currency-aware P&L display | `compute_currency_pnl()`, `compute_portfolio_exposure()` | MA decomposes, eTrading displays |
| E27 | Timezone-aware scheduling | `registry.get_market("INDIA").market_hours` | India 9:15-15:30 IST, US 9:30-16:00 ET |

---

## Learning Architecture (ML1-ML3)

### Principle: MA computes, eTrading stores

MA has NO state. All learning state (trade outcomes, bandit parameters, drift baselines) lives in eTrading. eTrading passes state to MA, MA returns updated state + decisions.

```
eTrading (stateful)                         MA (stateless, pure functions)
─────────────────                           ─────────────────────────────
Stores TradeOutcome records          ──→    detect_drift(outcomes) → list[DriftAlert]
Stores StrategyBandit params         ──→    select_strategies_bandit(bandits, regime) → ranked strategies
Stores optimized thresholds          ──→    optimize_thresholds(outcomes) → ThresholdConfig
Applies new thresholds to config     ←──    ThresholdConfig with learned cutoffs
Updates bandit alpha/beta            ←──    update_bandit(bandit, won) → updated bandit
```

### ML1: Drift Detection

**What:** Rolling win rate per (regime, strategy) cell. When a cell drops significantly from its historical baseline, flag it as a `DriftAlert`.

**API:**
```python
detect_drift(outcomes: list[TradeOutcome], window: int = 20, min_trades: int = 10) -> list[DriftAlert]
```

**Model:**
```python
class DriftAlert(BaseModel):
    regime_id: int
    strategy_type: StrategyType
    historical_win_rate: float  # Baseline from all outcomes
    recent_win_rate: float      # Last `window` trades
    recent_trades: int
    severity: str               # "warning" (>15% drop) or "critical" (>25% drop)
    recommendation: str         # "reduce allocation" or "suspend strategy"
```

**eTrading integration:**
- Call `detect_drift()` daily (or after every 5 closed trades)
- If any `DriftAlert.severity == "critical"` → remove that (regime, strategy) from allowed strategies
- If `"warning"` → reduce position size by 50% for that cell
- Display drift alerts in monitoring dashboard

### ML2: Thompson Sampling Bandits

**What:** Each (regime, strategy) cell has a Beta(alpha, beta) distribution representing win/loss history. When selecting strategies for a ticker in a given regime, sample from these distributions instead of using the static alignment matrix.

**API:**
```python
# Build initial bandits from trade history
build_bandits(outcomes: list[TradeOutcome]) -> dict[str, StrategyBandit]

# After each closed trade, update the relevant bandit
update_bandit(bandit: StrategyBandit, won: bool) -> StrategyBandit

# Select strategies — samples from distributions (exploration/exploitation)
select_strategies(
    bandits: dict[str, StrategyBandit],
    regime_id: int,
    available_strategies: list[StrategyType],
    n: int = 3,
) -> list[tuple[StrategyType, float]]  # (strategy, sampled_score)
```

**Model:**
```python
class StrategyBandit(BaseModel):
    regime_id: int
    strategy_type: StrategyType
    alpha: float = 1.0       # Prior + wins (Beta distribution param)
    beta_param: float = 1.0  # Prior + losses
    total_trades: int = 0
    last_updated: date | None = None

    @property
    def expected_win_rate(self) -> float:
        return self.alpha / (self.alpha + self.beta_param)

    @property
    def uncertainty(self) -> float:
        """Higher = less data = more exploration."""
        total = self.alpha + self.beta_param
        return 1.0 / (total + 1)
```

**How it replaces the static matrix:**
- Currently: `REGIME_STRATEGY_ALIGNMENT[(1, IRON_CONDOR)] = 1.0` (hard-coded)
- With bandits: sample from `Beta(15, 3)` for R1+IC → ~0.83 (data says IC wins 83% in R1)
- Undersampled cells (e.g., R3+calendar, only 2 trades) → high variance → gets explored
- Proven losers (e.g., R4+IC, 2 wins out of 20) → `Beta(3, 19)` → rarely selected

**eTrading integration:**
- Store `dict[str, StrategyBandit]` in DB (key = "R1_iron_condor")
- On every closed trade: `bandit = update_bandit(bandit, won=trade.pnl > 0)`
- When generating daily plan: `strategies = select_strategies(bandits, regime.regime, available)`
- Pass selected strategies to `rank(tickers, strategies=strategies)`

### ML3: Threshold Optimization

**What:** Learn optimal values for hard-coded thresholds from trade outcomes.

**Thresholds to optimize:**
```
IC IV rank hard stop: currently < 15 → learn optimal cutoff
IFly IV rank hard stop: currently < 20
Earnings IV rank hard stop: currently < 25
LEAP IV rank hard stop: currently > 70
POP minimum gate: currently 50%
Ranking score minimum: currently 0.60
Credit/width minimum: currently 10%
ADX trend hard stop: currently > 35
ADX no-trend hard stop: currently < 15
```

**API:**
```python
optimize_thresholds(
    outcomes: list[TradeOutcome],
    current_thresholds: ThresholdConfig,
    min_trades_per_bucket: int = 15,
) -> ThresholdConfig

class ThresholdConfig(BaseModel):
    ic_iv_rank_min: float = 15.0
    ifly_iv_rank_min: float = 20.0
    earnings_iv_rank_min: float = 25.0
    leap_iv_rank_max: float = 70.0
    pop_min: float = 0.50
    score_min: float = 0.60
    credit_width_min: float = 0.10
    adx_trend_max: float = 35.0
    adx_notrend_min: float = 15.0
```

**Method:** For each threshold, bucket outcomes by whether they were above/below the threshold at entry. Compare win rates. If trades below the current cutoff actually win more often than expected, lower the threshold (and vice versa). Clamp changes to ±20% of current value per iteration.

**eTrading integration:**
- Run `optimize_thresholds()` monthly (or after 50 closed trades)
- Store `ThresholdConfig` in DB
- Pass to MA services via config override (eTrading constructs `Settings` with optimized values)

---

## Platform Requirements (eTrading SaaS)

MA exposes all APIs. Platform provides infrastructure (DB, scheduling, UI). All MA CLI commands are already exposed in platform.

### Data Pipeline: Platform Must Build

| What to Store | DB Table/Model | Source | Used By |
|--------------|----------------|--------|---------|
| Trade outcomes | `TradeOutcomeORM` | Closed trades from broker fills | `detect_drift()`, `calibrate_weights()`, `calibrate_pop_factors()`, `optimize_thresholds()`, `build_bandits()`, `compute_performance_report()` |
| Bandit params | `StrategyBanditORM` | `build_bandits()` initial, `update_bandit()` on each close | `select_strategies()` in daily plan |
| Calibrated thresholds | `ThresholdConfigORM` | `optimize_thresholds()` output | Pass to MA as config override |
| Drift alerts | `DriftAlertORM` (or just log) | `detect_drift()` output | Strategy suspension rules, UI warnings |
| Calibrated weights | `WeightAdjustmentORM` | `calibrate_weights()` output | Override `REGIME_STRATEGY_ALIGNMENT` in ranking |
| POP factors | `PopFactorsORM` | `calibrate_pop_factors()` output | Future: pass to `estimate_pop()` as custom factors |
| Decision lineage | `TradeORM.decision_lineage` JSON | `debug=True` commentary from all MA services | "Explain this trade" API endpoint |

### Scheduling: Platform Must Implement

| Task | Frequency | MA API | Platform Action |
|------|-----------|--------|-----------------|
| **On every trade close** | Real-time | `update_bandit(bandit, won)` | Update bandit params in DB |
| **On every trade close** | Real-time | Append to `TradeOutcome` table | Store outcome for batch analysis |
| **Daily (pre-market)** | 1x/day | `detect_drift(outcomes)` | If CRITICAL → suspend strategy cell. If WARNING → halve position size. |
| **Daily (pre-market)** | 1x/day | `ma.regime.detect(ticker)` | Check `model_age_days`. If > 60 → call `ma.regime.fit(ticker)` |
| **Daily (plan generation)** | 1x/day | `select_strategies(bandits, regime)` | Use bandit-selected strategies instead of static list in `rank()` |
| **Weekly** | 1x/week | `calibrate_weights(outcomes)` | Compare vs current matrix. Apply if improvement > 5% |
| **Weekly** | 1x/week | `calibrate_pop_factors(outcomes)` | Store calibrated factors. Future: pass to `estimate_pop()` |
| **Monthly** | 1x/month | `optimize_thresholds(outcomes)` | Store new ThresholdConfig. Apply as config override. |
| **Monthly** | 1x/month | `compute_performance_report(outcomes)` | Dashboard display. Check `pop_accuracy` per regime. |

### Data Flow: TradeOutcome Construction

Platform builds `TradeOutcome` from its own DB when a trade closes:

```python
from market_analyzer import TradeOutcome, TradeExitReason

outcome = TradeOutcome(
    trade_id=trade_orm.id,
    ticker=trade_orm.ticker,
    strategy_type=trade_orm.structure_type,          # "iron_condor"
    regime_at_entry=trade_orm.regime_at_entry,       # From regime.detect() at entry time
    regime_at_exit=current_regime.regime,             # From regime.detect() at close time
    entry_date=trade_orm.entry_date,
    exit_date=date.today(),
    entry_price=trade_orm.entry_price,
    exit_price=fill_price,
    pnl_dollars=realized_pnl,
    pnl_pct=realized_pnl / (max_risk * 100),
    holding_days=(date.today() - trade_orm.entry_date).days,
    exit_reason=TradeExitReason(exit_reason),
    composite_score_at_entry=trade_orm.composite_score,
    contracts=trade_orm.contracts,
    # Extended fields (SaaS)
    structure_type=trade_orm.structure_type,
    order_side=trade_orm.order_side,
    iv_rank_at_entry=trade_orm.iv_rank_at_entry,     # Stored at entry time
    dte_at_entry=trade_orm.dte_at_entry,
    dte_at_exit=dte_remaining,
)
```

**Platform must capture at entry time** (store in TradeORM for later outcome construction):
- `regime_at_entry` — from `ma.regime.detect()`
- `iv_rank_at_entry` — from `ma.quotes.get_metrics()`
- `composite_score_at_entry` — from `RankedEntry.composite_score`
- `dte_at_entry` — from `TradeSpec.target_dte`

### Bandit Flow: Strategy Selection

```python
from market_analyzer import build_bandits, update_bandit, select_strategies

# STARTUP: build from historical outcomes
outcomes = load_all_outcomes_from_db()
bandits = build_bandits(outcomes)
save_bandits_to_db(bandits)

# DAILY PLAN: use bandits for strategy selection
bandits = load_bandits_from_db()
regime = ma.regime.detect(ticker)
selected = select_strategies(bandits, regime.regime, available_strategies, n=5)
# selected = [(StrategyType.IRON_CONDOR, 0.82), (StrategyType.CALENDAR, 0.71), ...]
# Pass selected strategies to rank():
ranking = ma.ranking.rank(tickers, strategies=[s for s, _ in selected])

# ON TRADE CLOSE: update bandit
bandit = load_bandit(f"R{regime_at_entry}_{structure_type}")
updated = update_bandit(bandit, won=(pnl > 0))
save_bandit(updated)
```

### Drift Flow: Strategy Suspension

```python
from market_analyzer import detect_drift

# DAILY PRE-MARKET
outcomes = load_recent_outcomes(days=180)
alerts = detect_drift(outcomes)

for alert in alerts:
    if alert.severity == "critical":
        suspend_strategy(alert.regime_id, alert.strategy_type)
        notify_user(f"Suspended {alert.strategy_type} in R{alert.regime_id}: "
                    f"win rate dropped from {alert.historical_win_rate:.0%} to {alert.recent_win_rate:.0%}")
    elif alert.severity == "warning":
        reduce_allocation(alert.regime_id, alert.strategy_type, factor=0.5)
```

### Threshold Flow: Config Override

```python
from market_analyzer import optimize_thresholds, ThresholdConfig

# MONTHLY
outcomes = load_all_outcomes_from_db()
current = load_threshold_config_from_db() or ThresholdConfig()
optimized = optimize_thresholds(outcomes, current)
save_threshold_config(optimized)

# APPLY: pass to MA as Settings override
# Platform constructs MarketAnalyzer with custom config that uses optimized thresholds
# e.g., IronCondorSettings.iv_rank_min = optimized.ic_iv_rank_min
```

---

## History

| Date | Work | Tests | Total |
|------|------|-------|-------|
| 2026-03-14 | G01-G05: Core systematic loop | +37 | 1109 |
| 2026-03-14 | G06-G09: Screening & intelligence | +24 | 1133 |
| 2026-03-14 | eTrading CRs (CR-3, CR-4, CR-5) | +13 | 1146 |
| 2026-03-14 | P1-P5: Wire pending (entry_window, data_gaps, debug, overnight, CLI) | +0 | 1146 |
| 2026-03-14 | SQ1-SQ3: IV integration, HMM staleness, POP calibration | +21 | 1167 |
| 2026-03-14 | TA1-TA6: Fibonacci, ADX, Donchian, Keltner, Pivots, VWAP | +23 | 1190 |
| 2026-03-14 | Refreshed challenge/trader.py — full 9-step systematic flow | +0 | 1190 |
| 2026-03-14 | SQ4-SQ10: Assessor overhauls, screening filters, IV ranking, pivot levels | +29 | 1219 |
| 2026-03-14 | ML1-ML3: Drift detection, Thompson Sampling bandits, threshold optimization | +22 | 1241 |
| 2026-03-14 | CR6-CR13: Multi-broker stubs, currency/timezone/lot_size, India data, MarketRegistry, analytics | +64 | 1305 |
| 2026-03-14 | H1-H5 + CR14-17: Currency, hedging, SaaS isolation, token expiry, rate limits | +26 | 1331 |
