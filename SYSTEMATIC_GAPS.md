# MA Gap Tracker

**Goal:** MA enables a fully systematic trading system that makes money — and gets smarter over time.

**Boundary:** MA is stateless. eTrading passes context in, MA computes and returns. eTrading owns all state (outcomes, bandit params, drift history).

**Stats:** 1241 tests passing. 169 in test_systematic.py.

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
