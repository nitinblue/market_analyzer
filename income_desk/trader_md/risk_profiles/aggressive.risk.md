---
name: aggressive
description: Aggressive risk profile - maximize premium capture
max_risk_per_trade_pct: 5.0
max_portfolio_risk_pct: 40.0
max_positions: 12
min_pop: 0.40
min_dte: 3
max_dte: 60
min_iv_rank: 15
max_spread_pct: 0.08
profit_target_pct: 0.40
stop_loss_pct: 3.0
exit_dte: 3
r1_allowed: true
r2_allowed: true
r3_allowed: true
r4_allowed: false
---

# Aggressive Risk Profile

Trade R1, R2, and R3. Larger positions, tighter profit targets.
Includes directional plays in trending regimes. Never trade R4.
