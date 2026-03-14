# MA Gap Tracker

**Goal:** MA enables a fully systematic trading system that makes money — and gets smarter over time.

**Boundary:** MA is stateless. eTrading passes context in, MA computes and returns. eTrading owns all state (outcomes, bandit params, drift history).

**Stats:** 1241 tests passing. 169 in test_systematic.py.

---

## Master Status

| # | Category | Gap | Status | Detail |
|---|----------|-----|--------|--------|
| G01 | Infrastructure | Deterministic adjustment decisions | **DONE** | `recommend_action()` → single action. Wired into health check + CLI. |
| G02 | Infrastructure | Execution quality validation | **DONE** | `validate_execution_quality()` checks spread/OI/volume. CLI `do_quality`. |
| G03 | Infrastructure | Entry time windows on TradeSpec | **DONE** | Assessors set windows: 0DTE=(09:45,14:00), income=(10:00,15:00), earnings=(10:00,14:30). |
| G04 | Infrastructure | Time-of-day urgency in exit monitoring | **DONE** | `time_of_day` param. 0DTE force-close after 15:00, tested escalation after 15:30. |
| G05 | Infrastructure | Overnight risk assessment | **DONE** | `assess_overnight_risk()`. Auto-invoked in `check_trade_health()` after 15:00. CLI `do_overnight`. |
| G06 | Infrastructure | Auto-select screening | **DONE** | `min_score=0.6` + `top_n` on `scan()`. `filtered_count` in output. |
| G07 | Intelligence | Performance feedback loop | **DONE** | `TradeOutcome` + `compute_performance_report()` + `calibrate_weights()`. CLI `do_performance`. |
| G08 | Intelligence | Debug/commentary mode | **DONE** | `debug=True` on `detect()`, `snapshot()`, `assess()`, `rank()`. Threads to assessors via ranking. |
| G09 | Intelligence | Data gap self-identification | **DONE** | `data_gaps` populated by 8 assessors + regime service. Propagated through ranking. |
| SQ1 | Signal Quality | IV rank integration in assessors | **DONE** | `iv_rank` param on IC (<15 stop), IFly (<20), earnings (<25), LEAP (>70). Data gaps when None. |
| SQ2 | Signal Quality | HMM model staleness & validation | **DONE** | `model_fit_date`, `model_age_days`, `regime_stability` on RegimeResult. Data gaps for stale/uncertain/churn. |
| SQ3 | Signal Quality | POP calibration from outcomes + IV | **DONE** | `iv_rank` on `estimate_pop()`. `calibrate_pop_factors()` from real win rates. `pop_accuracy` on report. |
| TA1 | Technicals | Fibonacci retracements/extensions | **DONE** | `FibonacciLevels` on TechnicalSnapshot. 5 levels, direction, current_price_level. |
| TA2 | Technicals | ADX (Average Directional Index) | **DONE** | `ADXData` on TechnicalSnapshot. ADX, +DI/-DI, is_trending/is_ranging. |
| TA3 | Technicals | Donchian channels | **DONE** | `DonchianChannels` on TechnicalSnapshot. 20-day high/low, proximity flags. |
| TA4 | Technicals | Keltner channels | **DONE** | `KeltnerChannels` on TechnicalSnapshot. EMA ± 2×ATR, squeeze detection. |
| TA5 | Technicals | Daily/weekly Pivot Points | **DONE** | `PivotPoints` on TechnicalSnapshot. PP, R1-R3, S1-S3. |
| TA6 | Technicals | Daily VWAP | **DONE** | `VWAPData` on TechnicalSnapshot. 20-day rolling VWAP, price_vs_vwap_pct. |
| SQ4 | Signal Quality | Mean reversion assessor overhaul | **DONE** | Fibonacci reversion target, ADX ranging/hard stop (>35), VWAP deviation, RSI-MACD divergence. 9 tests. |
| SQ5 | Signal Quality | Breakout volume confirmation | **DONE** | Donchian breakout confirmation, Keltner squeeze signal. 5 tests. |
| SQ6 | Signal Quality | Earnings implied move | **DONE** | Implied move from vol_surface front_iv vs historical ATR. Hard stop if ratio < 0.7x. |
| SQ7 | Signal Quality | Screening liquidity & correlation | **DONE** | ATR < 0.3% liquidity filter, regime+RSI correlation dedup. 3 tests. |
| SQ8 | Signal Quality | Momentum pullback quality | **DONE** | Fibonacci pullback depth, ADX trend strength, ADX < 15 hard stop. 6 tests. |
| SQ9 | Signal Quality | IV rank threaded through ranking | **DONE** | `iv_rank_map` param on `rank()`. Dispatches to 5 assessors. 2 tests. |
| SQ10 | Technicals | Pivot points wired into levels.py | **DONE** | 5 new LevelSource values. Weights: PP=0.8, R1/S1=0.7, R2/S2=0.5. 4 tests. |
| ML1 | Learning | Drift detection | **DONE** | `detect_drift(outcomes)` → `list[DriftAlert]`. WARNING at >15pp drop, CRITICAL at >25pp. 6 tests. |
| ML2 | Learning | Thompson Sampling strategy selection | **DONE** | `StrategyBandit` model, `build_bandits()`, `update_bandit()`, `select_strategies()`. Beta distribution per cell. 10 tests. |
| ML3 | Learning | Threshold optimization from outcomes | **DONE** | `optimize_thresholds(outcomes)` → `ThresholdConfig` with learned cutoffs. Sweeps unique values, maximizes win rate separation. 6 tests. |

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

## eTrading Integration Notes

| MA Feature | eTrading Action | When |
|-----------|----------------|------|
| SQ1 (IV rank on assessors) | Pass `iv_rank` from `ma.quotes.get_metrics()` to assessor calls | NOW |
| SQ2 (regime staleness) | Check `regime.data_gaps`, retrain if `model_age_days > 60` | NOW |
| SQ3 (POP calibration) | Pass `iv_rank` to `estimate_pop()`. Run `calibrate_pop_factors()` weekly | NOW |
| SQ9 (IV rank in ranking) | Build `iv_rank_map` from broker metrics, pass to `rank(iv_rank_map=...)` | NOW |
| G07 (performance) | Build pipeline: closed trades → `TradeOutcome` → `compute_performance_report()` | NOW |
| G08 (commentary) | Pass `debug=True`, store commentary in `decision_lineage` | NOW |
| G09 (data_gaps) | Read `data_gaps`, discount confidence for high-impact gaps | NOW |
| ML1 (drift) | Call `detect_drift()` daily. If critical → suspend strategy cell. If warning → reduce size. | After ML1 built |
| ML2 (bandits) | Store bandit params in DB. `update_bandit()` after every close. `select_strategies()` in daily plan. | After ML2 built |
| ML3 (thresholds) | Run `optimize_thresholds()` monthly. Store result. Pass as config override. | After ML3 built |

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
