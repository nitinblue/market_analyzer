---
name: daily_india_income
description: Daily income trading workflow for India market
broker: dhan_live
universe: india_fno
risk_profile: moderate
---

# Daily India Income Trading

## Phase 1: Market Assessment

### Step: Market Pulse
workflow: check_portfolio_health
inputs:
  tickers: $universe
  capital: $capital
  market: India
outputs:
  pulse: $result.sentinel_signal
  safe: $result.is_safe_to_trade
  regimes: $result.regimes
gate:
  - pulse != "RED"
  - safe == True
on_fail: HALT "Market pulse {pulse} — trading halted"

### Step: Market Snapshot
workflow: snapshot_market
inputs:
  tickers: $universe
  include_regime: true
  market: India
outputs:
  snapshots: $result.tickers
  iv_rank_map: $result.tickers.*.iv_rank

### Step: Daily Plan
workflow: generate_daily_plan
inputs:
  tickers: $universe
  capital: $capital
  market: India
  iv_rank_map: $phase1.iv_rank_map
outputs:
  plan_trades: $result.proposed_trades
  plan_summary: $result.summary

## Phase 2: Scanning

### Step: Scan Universe
workflow: scan_universe
inputs:
  tickers: $universe
  market: India
  min_score: 0.3
  top_n: 20
outputs:
  candidates: $result.candidates

### Step: Rank Opportunities
workflow: rank_opportunities
inputs:
  tickers: $universe
  capital: $capital
  market: India
  iv_rank_map: $phase1.iv_rank_map
  min_pop: $risk.min_pop
  max_trades: $risk.max_positions
outputs:
  proposals: $result.trades
  blocked: $result.blocked
gate:
  - len(proposals) > 0
on_fail: SKIP "No tradeable opportunities found"

## Phase 3: Trade Entry

### Step: Validate Top Trade
workflow: validate_trade
inputs:
  ticker: $phase2.proposals[0].ticker
  entry_credit: $phase2.proposals[0].entry_credit
  regime_id: 1
  atr_pct: 1.0
  current_price: 0
gate:
  - is_ready == True
on_fail: SKIP "Validation failed: {failed_gates}"

### Step: Size Position
workflow: size_position
inputs:
  pop_pct: $phase2.proposals[0].pop_pct
  max_profit: $phase2.proposals[0].max_profit
  max_loss: $phase2.proposals[0].max_risk
  capital: $capital
  risk_per_contract: $phase2.proposals[0].max_risk
  regime_id: 1
gate:
  - risk_pct_of_capital < $risk.max_risk_per_trade_pct
on_fail: BLOCK "Risk {risk_pct_of_capital}% exceeds limit"

### Step: Price Trade
workflow: price_trade
inputs:
  ticker: $phase2.proposals[0].ticker
  legs: $phase2.proposals[0].legs
  market: India
requires: live_broker
on_simulated: WARN "Simulated quotes — not tradeable"

## Phase 4: Monitoring

requires_positions: true

### Step: Monitor Positions
workflow: monitor_positions
inputs:
  positions: $positions
  market: India
gate:
  - critical_count == 0
on_fail: ALERT "Critical: {critical_count} positions need action"

### Step: Overnight Risk
workflow: assess_overnight_risk
inputs:
  positions: $positions
  market: India
gate:
  - close_before_close_count == 0
on_fail: ALERT "Close before EOD: {close_before_close_count} positions"

### Step: Expiry Check
workflow: check_expiry_day
inputs:
  positions: $positions
  market: India

## Phase 5: Risk & Reporting

### Step: Stress Test
workflow: stress_test_portfolio
inputs:
  positions: $positions
  capital: $capital
  market: India
gate:
  - risk_score != "critical"
on_fail: ALERT "Portfolio stress: {risk_score}"

### Step: Daily Report
workflow: generate_daily_report
inputs:
  trades_today: []
  positions_open: 0
  capital: $capital
  market: India
