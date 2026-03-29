---
name: conservative
description: Conservative risk profile - capital preservation first
max_risk_per_trade_pct: 2.0
max_portfolio_risk_pct: 20.0
max_positions: 5
min_pop: 0.65
min_dte: 14
max_dte: 45
min_iv_rank: 25
max_spread_pct: 0.03
profit_target_pct: 0.50
stop_loss_pct: 1.5
exit_dte: 7
r1_allowed: true
r2_allowed: false
r3_allowed: false
r4_allowed: false
---

# Conservative Risk Profile

Trade only in R1 (low-vol mean reverting). Small positions, wide margins of safety.
Ideal for capital preservation and consistent small gains.
