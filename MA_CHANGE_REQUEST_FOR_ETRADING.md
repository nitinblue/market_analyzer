# MA Change Request for eTrading Platform
# Date: 2026-03-15 | From: market_analyzer
# Status: OPEN — eTrading must implement

## Context

MA is stateless. Every function is pure computation — accepts data, returns results. But for the system to be **truly robust**, eTrading must pass the right data at the right time.

**CRITICAL WARNING: `rank()` output is NOT safe to execute directly.**

`rank()` scores trades on market merit only — regime alignment, IV rank, technicals. It has ZERO knowledge of open positions, portfolio concentration, or risk limits. eTrading MUST run the following pipeline before any trade reaches execution:

```
rank()                          → Market merit scoring (no position awareness)
   ↓
filter_trades_with_portfolio()  → Position limits, ticker/sector concentration, risk budget
   ↓
evaluate_trade_gates()          → BLOCK/SCALE/WARN classification (17 gates)
   ↓
validate_execution_quality()    → Bid-ask spread, OI, volume check
   ↓
ONLY THEN → submit order
```

Skipping any step = risk of uncontrolled position accumulation, concentration, or poor fills.

---

## CR-E1: Position-Aware Trading (CRITICAL)

### Problem
MA ranks and recommends trades without knowing what positions are already open. This leads to:
- Recommending IC on SPY when you already have one open
- Exceeding per-ticker concentration limits
- Breaking portfolio-level risk budgets
- Adding correlated positions (5 tech ICs = same bet)

### What eTrading Must Pass to MA

MA already accepts position data in several functions — eTrading must populate it:

```python
# ═══ BEFORE calling rank() or plan.generate() ═══

# 1. Build position summary from open trades
open_positions = [
    {"ticker": "SPY", "structure_type": "iron_condor", "direction": "neutral",
     "net_delta": 0.03, "dte_remaining": 25, "current_pnl_pct": 0.15,
     "max_loss": 420, "buying_power_used": 500},
    {"ticker": "GLD", "structure_type": "credit_spread", "direction": "bullish",
     "net_delta": -0.15, "dte_remaining": 18, "current_pnl_pct": -0.05,
     "max_loss": 300, "buying_power_used": 300},
]

# 2. Compute available resources
account_balance = acct.get_balance()
total_bp = account_balance.derivative_buying_power
bp_used = sum(p["buying_power_used"] for p in open_positions)
available_bp = total_bp - bp_used

# 3. Build risk limits
risk_limits = {
    "max_positions": 5,
    "max_per_ticker": 2,
    "max_sector_concentration_pct": 0.40,
    "max_portfolio_risk_pct": 0.25,
    "max_single_trade_risk_pct": 0.05,
    "allowed_structures": ["iron_condor", "credit_spread", "calendar", "debit_spread"],
}

# 4. Build concentration map
ticker_count = {}
sector_risk = {}
for p in open_positions:
    ticker_count[p["ticker"]] = ticker_count.get(p["ticker"], 0) + 1
    sector = registry.get_instrument(p["ticker"]).sector
    sector_risk[sector] = sector_risk.get(sector, 0) + p["max_loss"]

# 5. Call MA with position context
ranking = ma.ranking.rank(tickers, iv_rank_map=iv_ranks)

# 6. Filter AFTER ranking — eTrading enforces limits
filtered = filter_trades_by_account(
    ranked_entries=ranking.top_trades,
    available_buying_power=available_bp,  # NOT total BP — subtract used
    allowed_structures=risk_limits["allowed_structures"],
    max_risk_per_trade=account_balance.net_liquidating_value * risk_limits["max_single_trade_risk_pct"],
)

# 7. Apply position-level filters (eTrading logic — NOT in MA)
final_trades = []
for trade in filtered.affordable:
    spec = trade.trade_spec
    if spec is None:
        continue

    # Per-ticker limit
    current_count = ticker_count.get(spec.ticker, 0)
    if current_count >= risk_limits["max_per_ticker"]:
        continue  # Already at max for this ticker

    # Total positions limit
    if len(open_positions) + len(final_trades) >= risk_limits["max_positions"]:
        break  # Portfolio full

    # Sector concentration
    sector = registry.get_instrument(spec.ticker).sector
    sector_total = sector_risk.get(sector, 0) + (spec.wing_width_points or 5) * spec.lot_size
    if sector_total / account_balance.net_liquidating_value > risk_limits["max_sector_concentration_pct"]:
        continue  # Sector too concentrated

    # Portfolio risk budget
    total_risk = sum(p["max_loss"] for p in open_positions) + (spec.wing_width_points or 5) * spec.lot_size
    if total_risk / account_balance.net_liquidating_value > risk_limits["max_portfolio_risk_pct"]:
        continue  # Portfolio risk exceeded

    final_trades.append(trade)
    ticker_count[spec.ticker] = current_count + 1
    sector_risk[sector] = sector_total
```

### Why This Is eTrading's Job (Not MA's)
- MA is **stateless** — it doesn't know what's in your portfolio
- Risk limits are **per-user/per-desk** — different users have different limits
- Portfolio state is **real-time** — changes with every fill, every market move
- Concentration logic needs **position database** — MA has no DB

### What MA Provides (already built)
- `filter_trades_by_account()` — BP and structure filtering
- `ma.registry.get_instrument()` — sector, lot_size, asset_type for concentration checks
- `validate_execution_quality()` — liquidity gate before entry
- `assess_hedge()` — per-position hedge recommendation
- `assess_overnight_risk()` — per-position overnight risk
- `check_trade_health()` — per-position monitoring
- `recommend_action()` — per-position adjustment decision

---

## CR-E2: Every MA Function and Its Required Inputs

### Real-Time Data (eTrading must provide on every call)

| MA Function | What eTrading Passes | Source |
|------------|---------------------|--------|
| `monitor_exit_conditions()` | `current_mid_price` | Broker mark_price or DXLink quote |
| `check_trade_health()` | `current_mid_price`, `time_of_day` | Broker + system clock |
| `recommend_action()` | `regime` (fresh), `technicals` (fresh) | `ma.regime.detect()` + `ma.technicals.snapshot()` |
| `assess_hedge()` | `position_type`, `position_value`, `regime`, `technicals` | Portfolio DB + MA services |
| `assess_overnight_risk()` | `dte_remaining`, `regime_id`, `position_status` | Portfolio DB + MA regime |
| `validate_execution_quality()` | `quotes: list[OptionQuote]` | `ma.quotes.get_leg_quotes()` or broker REST |

### Cached Data (eTrading refreshes periodically)

| MA Function | What eTrading Passes | Refresh Frequency |
|------------|---------------------|-------------------|
| `rank(iv_rank_map=)` | `{ticker: iv_rank}` | Every scan cycle (from `mm.get_metrics()`) |
| `estimate_pop(iv_rank=)` | `iv_rank: float` | Same |
| `assess_iron_condor(iv_rank=)` | `iv_rank: float` | Same |
| `generate_research_report(data=)` | `{ticker: OHLCV DataFrame}` for 22 assets | Daily pre-market |
| `compute_macro_dashboard()` | OHLCV for TNX, TLT, HYG, UUP, TIP | Daily pre-market |
| `analyze_cross_market()` | OHLCV for US + India tickers | Daily pre-market |

### Trade Close Data (eTrading builds on every trade close)

| MA Function | What eTrading Passes | Source |
|------------|---------------------|--------|
| `update_bandit(bandit, won)` | `StrategyBandit` + `bool` | Portfolio DB (trade closed) |
| `detect_drift(outcomes)` | `list[TradeOutcome]` | Trade outcome DB |
| `calibrate_weights(outcomes)` | Same | Same |
| `calibrate_pop_factors(outcomes)` | Same | Same |
| `compute_performance_report(outcomes)` | Same | Same |
| `compute_sharpe(outcomes)` | Same | Same |
| `compute_drawdown(outcomes)` | Same | Same |
| `optimize_thresholds(outcomes)` | Same | Monthly batch |

### Static Config (eTrading passes once at startup)

| MA Function | What eTrading Passes | Source |
|------------|---------------------|--------|
| `MarketAnalyzer(market_data=, market_metrics=, account_provider=)` | Broker providers | `connect_tastytrade()` or `connect_zerodha()` |
| `MarketAnalyzer(market=)` | `"US"` or `"India"` | Desk config |
| `compute_economic_snapshot(fred_api_key=)` | FRED API key | Platform config |
| `convert_amount(rates=)` | `dict[str, CurrencyPair]` | FX rate feed |

---

## CR-E3: Data eTrading Must Capture at Trade Entry

These fields are needed later for `TradeOutcome` construction when the trade closes:

| Field | Source | When |
|-------|--------|------|
| `regime_at_entry` | `ma.regime.detect(ticker).regime` | At entry |
| `iv_rank_at_entry` | `ma.quotes.get_metrics(ticker).iv_rank` | At entry |
| `composite_score_at_entry` | `RankedEntry.composite_score` | At ranking |
| `dte_at_entry` | `TradeSpec.target_dte` | At entry |
| `entry_price` | Broker fill price | At fill |
| `contracts` | From `spec.position_size()` or user override | At entry |
| `structure_type` | `TradeSpec.structure_type` | At entry |
| `order_side` | `TradeSpec.order_side` | At entry |
| `decision_lineage` | `debug=True` commentary from MA services | At entry |

---

## CR-E4: Daily Workflow — What eTrading Calls and When

### Pre-Market (before 9:15 IST / 9:30 ET)

```python
# 1. Macro research (daily email + dashboard)
data = fetch_ohlcv_for_all_research_assets()
report = generate_research_report(data, "daily", fred_key, spy_pe)
store_report(report)
if report.regime.regime in ("deflationary", "stagflation"):
    send_alert("Macro regime: {report.regime.regime} — reduce activity")

# 2. Cross-market (India desk)
cm = analyze_cross_market("SPY", "NIFTY", us_ohlcv, india_ohlcv, us_regime, india_regime)
if cm.signals:
    send_india_desk_alert(cm.signals)

# 3. Drift detection
outcomes = load_outcomes(days=180)
alerts = detect_drift(outcomes)
for alert in alerts:
    if alert.severity == "critical":
        suspend_strategy(alert.regime_id, alert.strategy_type)

# 4. Regime staleness check
for ticker in active_tickers:
    regime = ma.regime.detect(ticker)
    if regime.model_age_days and regime.model_age_days > 60:
        ma.regime.fit(ticker)  # Retrain
```

### Market Open (scan + rank)

```python
# 5. Get IV rank for all tickers
iv_rank_map = {}
for ticker in scan_tickers:
    metrics = ma.quotes.get_metrics(ticker)
    if metrics:
        iv_rank_map[ticker] = metrics.iv_rank

# 6. Rank with position awareness
ranking = ma.ranking.rank(scan_tickers, iv_rank_map=iv_rank_map, debug=True)

# 7. Filter by account + position limits
filtered = filter_trades_by_account(ranking.top_trades, available_bp, ...)
final = apply_position_limits(filtered, open_positions, risk_limits)  # eTrading logic

# 8. Validate execution quality
for trade in final:
    quotes = ma.quotes.get_leg_quotes(trade.trade_spec.legs, trade.trade_spec.ticker)
    quality = validate_execution_quality(trade.trade_spec, quotes)
    if not quality.tradeable:
        skip(trade)
```

### During Day (monitoring loop — every 30 min or on price alerts)

```python
# 9. For each open position
for position in open_positions:
    spec = reconstruct_trade_spec(position)  # from_dxlink_symbols()
    current_price = get_mark_price(position)  # From broker REST
    regime = ma.regime.detect(position.ticker)
    tech = ma.technicals.snapshot(position.ticker)

    health = check_trade_health(
        trade_id=position.id, trade_spec=spec,
        entry_price=position.entry_price, contracts=position.contracts,
        current_mid_price=current_price, dte_remaining=position.dte,
        regime=regime, technicals=tech,
        time_of_day=datetime.now().time(),
    )

    if health.overall_action == "close":
        submit_close_order(spec)
    elif health.overall_action == "adjust":
        decision = ma.adjustment.recommend_action(spec, regime, tech)
        execute_adjustment(decision)
```

### End of Day (15:00-15:30 IST / 15:30-16:00 ET)

```python
# 10. Overnight risk for all positions
for position in open_positions:
    risk = assess_overnight_risk(
        trade_id=position.id, ticker=position.ticker,
        structure_type=position.structure_type, order_side=position.order_side,
        dte_remaining=position.dte, regime_id=current_regime.regime,
        position_status=position.status,
        has_earnings_tomorrow=check_earnings(position.ticker),
    )
    if risk.risk_level == "close_before_close":
        submit_close_order(position)
```

### On Trade Close (every close event)

```python
# 11. Build TradeOutcome
outcome = TradeOutcome(
    trade_id=trade.id, ticker=trade.ticker,
    strategy_type=trade.structure_type,
    regime_at_entry=trade.regime_at_entry,
    regime_at_exit=current_regime.regime,
    entry_date=trade.entry_date, exit_date=date.today(),
    entry_price=trade.entry_price, exit_price=fill_price,
    pnl_dollars=realized_pnl, pnl_pct=realized_pnl / max_risk,
    holding_days=(date.today() - trade.entry_date).days,
    exit_reason=reason, composite_score_at_entry=trade.composite_score,
    contracts=trade.contracts,
    structure_type=trade.structure_type, order_side=trade.order_side,
    iv_rank_at_entry=trade.iv_rank_at_entry,
    dte_at_entry=trade.dte_at_entry, dte_at_exit=dte_remaining,
)
save_outcome(outcome)

# 12. Update bandit
bandit = load_bandit(f"R{outcome.regime_at_entry}_{outcome.strategy_type}")
updated = update_bandit(bandit, won=(outcome.pnl_pct > 0))
save_bandit(updated)
```

### Weekly

```python
# 13. Calibration
outcomes = load_all_outcomes()
calibration = calibrate_weights(outcomes)
pop_factors = calibrate_pop_factors(outcomes)
report = compute_performance_report(outcomes)
sharpe = compute_sharpe(outcomes)
drawdown = compute_drawdown(outcomes)
```

### Monthly

```python
# 14. Threshold optimization
optimized = optimize_thresholds(outcomes)
save_threshold_config(optimized)
```

---

## CR-E5: Risk Limits — eTrading Configuration

eTrading must implement and enforce these limits (MA provides the data but doesn't enforce):

```yaml
# Per-desk risk configuration
risk_limits:
  # Position limits
  max_positions: 5              # Max open positions at once
  max_per_ticker: 2             # Max positions on same underlying
  max_new_positions_daily: 3    # Max new trades per day (TRADE day)
  max_new_positions_light: 1    # Max new trades on TRADE_LIGHT day

  # Capital limits
  max_single_trade_risk_pct: 0.05   # 5% of account per trade
  max_portfolio_risk_pct: 0.25      # 25% total risk deployed
  min_buying_power_reserve_pct: 0.20 # Keep 20% BP in cash

  # Concentration limits
  max_sector_concentration_pct: 0.40  # 40% in one sector
  max_correlation_overlap: 0.85       # Don't add if correlation > 85%

  # Strategy limits
  max_undefined_risk_positions: 0     # No naked shorts (small accounts)
  allowed_structures:
    - iron_condor
    - iron_butterfly
    - credit_spread
    - debit_spread
    - calendar
    - equity_long  # India stocks

  # Quality gates
  min_trade_quality_score: 0.50   # From POPEstimate.trade_quality_score
  min_pop: 0.45                   # Minimum POP
  min_execution_quality: "go"     # From validate_execution_quality()

  # Macro gates
  halt_on_regime: ["deflationary"]  # No trading in deflationary regime
  reduce_on_regime: ["risk_off", "stagflation"]  # 50% size

  # Sector mapping
  ticker_sectors:
    SPY: index
    QQQ: tech
    GLD: commodity
    NIFTY: index
    RELIANCE: energy
    TCS: tech
    HDFCBANK: finance
```

### eTrading Enforcement Flow

```
1. Macro gate    → report.regime in halt_on_regime? → STOP
2. Day verdict   → plan.day_verdict == NO_TRADE? → STOP
3. Position cap  → len(open_positions) >= max_positions? → STOP
4. Rank trades   → MA ranks by market merit
5. BP filter     → available_bp >= trade risk? (MA's filter_trades_by_account)
6. Ticker limit  → ticker_count[ticker] < max_per_ticker? (eTrading)
7. Sector limit  → sector_risk[sector] / NLV < max_sector_pct? (eTrading)
8. Portfolio risk → total_risk / NLV < max_portfolio_risk_pct? (eTrading)
9. Quality gate  → trade_quality_score >= min_trade_quality_score? (MA's POPEstimate)
10. Execution    → validate_execution_quality == GO? (MA)
11. Entry window → within spec.entry_window_start/end? (eTrading)
12. Submit order → eTrading places order
```

Steps 1-5, 9-10 use MA APIs. Steps 6-8, 11-12 are eTrading enforcement logic.

---

## CR-E6: Feedback Contract — The 3 Things MA Needs

MA is stateless and computes everything from market data on its own. But to LEARN and IMPROVE, MA needs exactly 3 data feeds from eTrading:

### F1: Trade Outcomes (CRITICAL — enables entire learning stack)

```python
# On every trade close, eTrading builds and stores:
outcome = TradeOutcome(
    trade_id=trade.id, ticker=trade.ticker,
    strategy_type=trade.structure_type,
    regime_at_entry=trade.regime_at_entry,   # Stored at entry
    regime_at_exit=current_regime.regime,
    entry_date=trade.entry_date, exit_date=date.today(),
    entry_price=trade.entry_price, exit_price=fill_price,
    pnl_dollars=realized_pnl, pnl_pct=realized_pnl / max_risk,
    holding_days=(date.today() - trade.entry_date).days,
    exit_reason=reason,
    composite_score_at_entry=trade.composite_score,
    iv_rank_at_entry=trade.iv_rank_at_entry, dte_at_entry=trade.dte_at_entry,
)

# Weekly: pass all outcomes to MA
outcomes = load_all_outcomes_from_db()
calibration = calibrate_weights(outcomes)        # New strategy alignment weights
pop_factors = calibrate_pop_factors(outcomes)    # New regime move factors
alerts = detect_drift(outcomes)                  # Strategy cells to suspend
thresholds = optimize_thresholds(outcomes)       # Learned IV/POP cutoffs
report = compute_performance_report(outcomes)    # Sharpe, drawdown, win rate
```

**Without outcomes, MA cannot:** calibrate weights, detect drift, optimize thresholds, compute Sharpe/drawdown, or improve POP estimates. The learning stack returns empty results.

### F2: Rejected Trade Outcomes (HIGH — enables gate learning)

```python
# On every gate rejection, eTrading stores:
rejected = RejectedTrade(
    rejected_date=date.today(), ticker=ticker,
    strategy_type=strategy, composite_score=score,
    gate_blocked_by=gate_report.blocked_by,
    gate_report=gate_report,
)

# Monthly: eTrading adds hypothetical P&L (what would have happened?)
# Check mark_price at T+30 days, compute would_have_won
rejected.hypothetical_pnl_pct = compute_hypothetical_pnl(rejected)
rejected.would_have_won = rejected.hypothetical_pnl_pct > 0

# Pass to MA:
effectiveness = analyze_gate_effectiveness(gate_history, shadow_outcomes, actual_outcomes)
# If gates too tight → loosen. If gates too loose → tighten.
```

**Without rejection data, MA cannot:** tell if gates are leaving money on the table.

### F3: Peak NLV (MEDIUM — enables drawdown circuit breaker)

```python
# eTrading tracks and stores the highest account value:
peak_nlv = max(stored_peak_nlv, current_nlv)

# Pass to MA on every risk check:
dashboard = compute_risk_dashboard(positions, account_nlv, peak_nlv=peak_nlv, ...)
# dashboard.drawdown.is_triggered = True if (peak - current) / peak > threshold
```

**Without peak_nlv, MA cannot:** compute drawdown accurately (it's stateless, can't remember).

---

## Summary

| CR | What | Priority | Owner |
|----|------|----------|-------|
| CR-E1 | Position-aware filtering (ticker/sector/portfolio limits) | **CRITICAL** | eTrading |
| CR-E2 | Pass correct data to every MA function | **CRITICAL** | eTrading |
| CR-E3 | Capture entry-time data for TradeOutcome | **HIGH** | eTrading |
| CR-E4 | Daily workflow orchestration | **HIGH** | eTrading |
| CR-E5 | Risk limits configuration + enforcement | **CRITICAL** | eTrading |
| CR-E6 | Feedback: trade outcomes + rejected trades + peak NLV | **CRITICAL** | eTrading |

**MA provides all the computation. eTrading provides 3 feedback streams and MA gets smarter over time.**
