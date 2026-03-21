# Black Swan / Market Crash Playbook
## For a $30-40K Income Trader Using market_analyzer

> Written from the perspective of a systematic income trader who has lived through 2008, 2018 (Volmageddon), 2020 (COVID), and 2022 (rate shock). The biggest money in income trading is made in the 6 months AFTER a crash — not during it.

**Account:** $30-40K taxable + $200K IRA
**Philosophy:** Capital preservation during the storm, aggressive income deployment during the rebuild
**System:** market_analyzer (MA) with full broker connectivity

---

## Phase 0: Right Now — Pre-Crash Preparation (You Are Here)

### What MA tells you today (2026-03-20)

```
SPY: R2 (100%) — high-vol mean-reverting
QQQ: R4 (96%) — explosive bearish
IWM: R1 (99%) — but fragile
GLD: R1 (100%) — but -10% pullback, regime may be stale
```

QQQ R4 is the canary. When one major index goes R4 while others are R2, the system is warning you: contagion risk is elevated. QQQ led the last three major selloffs (2018, 2020, 2022).

### Preparation Checklist

**1. Reduce existing positions to zero or near-zero risk**

```python
# For each open position:
exit_result = monitor_exit_conditions(
    ..., regime_stop_multiplier=1.5,  # Tighten ALL stops to 1.5x
    ...
)
# If any position is at 25%+ profit → close and take the win
# If any position has DTE > 30 → close regardless of P&L
# You want ZERO exposure going into the crash
```

**Why:** Positions held through a crash face 5-10x normal adverse moves. A 5-wide IC that normally risks $300 can gap through both strikes overnight. Close everything that's working and eat the small loss on anything that isn't.

**2. Raise cash to maximum**
- Close all non-essential positions
- Target: 100% cash (or 90% cash + 10% in VIX calls as insurance)
- Your $32K should be sitting as cash, earning nothing, ready for deployment

**3. Set regime monitoring alerts**
```python
# Run daily:
for ticker in ['SPY', 'QQQ', 'IWM', 'TLT', 'GLD']:
    regime = ma.regime.detect(ticker)
    probs = regime.regime_probabilities
    # Watch for: R4 probability rising on SPY/IWM
    if probs[4] > 0.20:
        alert(f"{ticker} R4 probability {probs[4]:.0%} — contagion risk")
```

**4. Pre-compute your crash entry levels**

These are the price levels where you WANT to be ready to sell premium:

| Ticker | Current | -10% | -15% | -20% | -30% |
|--------|---------|------|------|------|------|
| SPY | $649 | $584 | $552 | $519 | $454 |
| QQQ | $582 | $524 | $495 | $466 | $407 |
| IWM | $242 | $218 | $206 | $194 | $169 |

These are your "get ready" levels. You don't trade AT these levels — you wait for stabilization.

---

## Phase 1: The Crash (Days 1-14)

### What happens to the system

```
Day 1-3: SPY drops 5-8%. VIX spikes from 20 to 35-40.
  MA regime: SPY → R4, QQQ → R4, IWM → R4
  All validation gates: BLOCKED (R4 = no income trades)
  Kelly: 0 contracts on everything
  Entry score: ENTER_NOW on everything (oversold) — BUT momentum override caps it

Day 4-7: Continued selling. VIX hits 45-60.
  MA regime: Still R4 across the board
  Validation: Still BLOCKED
  Your portfolio: 100% cash. Watching.

Day 7-14: Volatile, gap-up/gap-down daily.
  MA regime: Oscillating R4/R2 — this is the transition zone
  Validation: Some checks start passing (VIX elevated = rich premiums)
  Kelly: Starting to show small positive fractions
```

### Your job during the crash: DO NOTHING

```python
# Daily check:
ctx = ma.context.assess()
if not ctx.trading_allowed:
    print("Black swan active — NO TRADING")
    return

for ticker in watchlist:
    regime = ma.regime.detect(ticker)
    if regime.regime.value == 4:
        print(f"{ticker} R4 — waiting")
    elif regime.regime.value == 2:
        print(f"{ticker} transitioning to R2 — MONITORING")
        # This is the first signal that the crash is maturing
```

### What NOT to do

1. **DO NOT buy the dip.** Directional trades during R4 are gambling, not trading.
2. **DO NOT sell premium during peak VIX.** VIX at 60 means the market expects 4% daily moves. Your 5-wide IC will be breached in a single session.
3. **DO NOT hedge with VIX calls after VIX has already spiked.** The insurance is expensive after the house is on fire. If you didn't buy protection in Phase 0, it's too late.
4. **DO NOT average down on anything.** There is no position. You are 100% cash.

---

## Phase 2: The Stabilization (Weeks 2-6)

### The signal you're waiting for

```
Regime transitions: R4 → R2 on SPY/IWM (QQQ may lag)
VIX: Elevated (30-40) but no longer making new highs
Price action: Range-bound — gap-ups and gap-downs, but within a channel
Daily ATR: Still 2-3x normal but declining from peak
```

### What MA tells you

```python
regime = ma.regime.detect('SPY')
# regime.regime = R2 (high-vol mean-reverting)
# regime.confidence = 70-80% (not 100% — uncertainty is expected)
# regime.regime_probabilities = {1: 0.05, 2: 0.65, 3: 0.05, 4: 0.25}
# R4 probability still 25% — respect this

metrics = ma.quotes.get_metrics('SPY')
# iv_rank: 85-95% — premiums are EXTREME
# iv_percentile: 99% — you are in the top 1% of IV history
# This is where the money is made
```

### First trades: Defined risk, small, far OTM

**THIS is when income traders make their year.** VIX at 35 means option premiums are 2-3x normal. A 5-wide SPY IC that normally collects $1.20 now collects $3.00-$4.00.

```python
# Run the full pipeline
validate = run_daily_checks(
    ticker='SPY', trade_spec=ic_spec, entry_credit=3.50,
    regime_id=2, atr_pct=2.5, current_price=520.0,
    avg_bid_ask_spread_pct=1.5, dte=21,  # SHORTER DTE in R2
    rsi=35.0, iv_rank=90.0, ticker_type='etf',
    days_to_earnings=None, levels=levels,
)
# With $3.50 credit on 5-wide:
#   POP: ~70% (strikes are far OTM due to R2 1.5x ATR multiplier)
#   ROC: 40%+ annualized (insane — this is the post-crash dividend)
#   Commission drag: 1.5% (negligible on $350 credit)
#   Kelly: positive, recommends 1-2 contracts

# CRITICAL: Use regime-contingent stop
stop = compute_regime_stop(2)  # R2 = 3.0x credit
# $3.50 credit × 3.0x = $10.50 max loss per spread
# R2 swings are WIDE — a standard 2x stop will get you whipsawed
```

### Position sizing rules during recovery

```python
# Conservative half-Kelly with regime-aware margin
sizing = compute_position_size(
    pop_pct=0.70, max_profit=350, max_loss=150,
    capital=32000, risk_per_contract=500,
    wing_width=5.0, regime_id=2,
    exposure=PortfolioExposure(
        open_position_count=0, max_positions=3,  # REDUCED from 5
        current_risk_pct=0.0,
        max_risk_pct=0.15,  # REDUCED from 25% to 15%
        drawdown_pct=0.0,
        drawdown_halt_pct=0.05,  # TIGHTER circuit breaker: 5% not 10%
    ),
    safety_factor=0.25,  # QUARTER Kelly, not half
)
```

**Key changes from normal operations:**
- Max positions: 3 (not 5) — leave room for hedging
- Max risk: 15% of NLV (not 25%) — regime is still volatile
- Circuit breaker: 5% drawdown (not 10%) — tighter leash
- Kelly safety: 0.25 (quarter Kelly) not 0.50 (half Kelly)
- DTE: 21 (not 35) — shorter exposure to tail risk

### Which tickers first

```python
# Priority order for post-crash income deployment:
# 1. ETFs with highest IV rank in R2 (most premium to sell)
# 2. Uncorrelated to each other (GLD/TLT vs SPY/IWM)
# 3. R2 confidence > 75% (avoid R4-to-R2 false transitions)

# Check correlation before deploying second trade:
corr = compute_pairwise_correlation(spy_returns, gld_returns, lookback=30)
# If SPY/GLD correlation < 0.30: excellent diversification
# If SPY/IWM correlation > 0.80: treat as same position
```

---

## Phase 3: The Recovery (Months 2-6)

### The regime transition: R2 → R1

```
VIX declining from 35 → 25 → 18
Regime transitions: SPY R2 → R1, IWM R2 → R1
IV rank dropping: 90% → 60% → 40%
ATR normalizing: 2.5% → 1.5% → 1.0%
```

### This is when you scale up

```python
# As R1 confidence increases:
if regime.regime.value == 1 and regime.confidence >= 0.80:
    # Return to normal parameters
    exposure = PortfolioExposure(
        open_position_count=current_count,
        max_positions=5,          # Back to 5
        max_risk_pct=0.25,        # Back to 25%
        drawdown_halt_pct=0.10,   # Back to 10%
    )
    safety_factor = 0.50  # Back to half Kelly

# BUT: IV rank is still elevated (40-60%)
# This means premiums are STILL richer than normal
# The sweet spot: R1 regime + elevated IV rank = maximum income
```

### The math that makes your year

Normal R1 income trading:
- SPY 5-wide IC: $1.20 credit, 72% POP, $50 EV
- Monthly: ~$150-$200 from 2 ICs

Post-crash elevated IV in R1:
- SPY 5-wide IC: $2.00+ credit, 75% POP (strikes further OTM due to higher IV), $80 EV
- Monthly: ~$300-$400 from 3 ICs (more premium, higher confidence)

Over 6 months of elevated IV:
- Normal: ~$1,000 income
- Post-crash: ~$2,000-$2,400 income

**That's 2-3x the normal income from the SAME structures.** The crash didn't change what you trade — it changed how much you get paid for the same risk.

### DTE optimization becomes critical here

```python
# During IV normalization, the term structure is steep
# Front month IV is falling faster than back month
# DTE optimizer helps you pick the sweet spot

dte_rec = select_optimal_dte(vol_surface, regime_id=1, strategy='iron_condor')
# May recommend 28 DTE instead of 45 DTE because:
# - Front IV (28 DTE) is 25% while back IV (45 DTE) is 20%
# - Theta proxy is higher on the front month
# - Faster capital recycling during the recovery
```

### Strategy switching becomes relevant

```python
# If you entered ICs during R2 and regime transitions to R1:
# The adjustment service now suggests CONVERT_TO_DIAGONAL
# when regime changes favorably

decision = adj_service.recommend_action(
    trade_spec=existing_ic,
    regime=current_regime,  # R1
    technicals=technicals,
    entry_regime_id=2,  # Entered during R2
)
# If position is profitable: let it ride (R1 is friendly to ICs)
# If position is tested: convert to diagonal to capture trend
```

---

## Phase 4: Return to Normal (Month 6+)

### What normal looks like after a crash

```
VIX: 14-18 (back to baseline)
IV Rank: 20-40% across ETFs
Regime: R1 on most instruments
ATR: 0.8-1.2% on SPY
```

### Resume standard operations

```python
# Normal validation thresholds:
# POP >= 65%, ROC >= 10%, positive EV
# Kelly half (0.50 safety factor)
# Max 5 positions, 25% risk budget
# 10% drawdown circuit breaker
# Standard 2.0x stop (R1)
```

### Key lesson: The calibration loop

```python
# After the crash, feed ALL your outcomes into calibration
from market_analyzer import calibrate_weights, analyze_adjustment_effectiveness

# What did you learn?
# - Which R2 IC entries had the best POP accuracy?
# - Did 3.0x stops work in R2 (or should it be 2.5x)?
# - Was quarter Kelly too conservative (left money on table)?
# - Which adjustments worked during recovery?

effectiveness = analyze_adjustment_effectiveness(outcomes)
new_weights = calibrate_weights(outcomes)
```

---

## Decision Tree Summary

```
TODAY (pre-crash):
├── R4 on any major index? → REDUCE positions, raise cash
├── All R1/R2? → Normal income trading
└── Mixed R2/R4? → Tighten stops, stop new entries

DURING CRASH (R4 everywhere):
├── 100% cash
├── Daily regime monitoring
├── Set alerts at -10%/-15%/-20% levels
└── DO NOTHING until R4 → R2 transition

STABILIZATION (R4 → R2):
├── First trades: 21 DTE, quarter Kelly, 3 max positions
├── 15% max risk, 5% circuit breaker
├── Uncorrelated tickers only (GLD vs SPY, not SPY+QQQ)
├── 3.0x regime stop (R2)
└── Premiums are 2-3x normal — this is where you earn

RECOVERY (R2 → R1):
├── Scale to half Kelly, 5 positions, 25% risk
├── IV still elevated — premiums rich
├── DTE optimizer for front-month theta advantage
├── Strategy switching if regime changed on existing positions
└── 6 months of above-average income

NORMAL (R1 baseline):
├── Standard operations resume
├── Calibrate weights from crash outcomes
├── Feed adjustment effectiveness into learning loop
└── Prepare for next cycle
```

---

## Risk Rules — Non-Negotiable

1. **R4 = no income trades.** Not "small," not "careful" — NONE.
2. **100% cash before the crash hits.** Close at first R4 signal, not when you've already lost 10%.
3. **Quarter Kelly during stabilization.** Full Kelly is for calm markets. Post-crash volatility is non-Gaussian.
4. **Max 3 positions in R2.** Leave room for the market to surprise you.
5. **5% circuit breaker post-crash** (not 10%). Your account can't afford a 10% drawdown AND miss the recovery.
6. **Uncorrelated first.** GLD + TLT before SPY + IWM. Sell premium on what isn't crashing, not on what just crashed.
7. **21 DTE max in R2.** Shorter exposure = less time for the next leg down.
8. **3.0x stops in R2.** Mean-reversion swings are WIDE. A 2x stop gets whipsawed.
9. **Don't touch QQQ until R2 with 80%+ confidence.** Tech leads into crashes and is last to stabilize.
10. **The money is in the first 6 months of recovery.** Don't blow your capital during the crash and miss the opportunity.

---

## MA API Quick Reference for Crash Scenarios

| Phase | Key API | What to check |
|-------|---------|---------------|
| Pre-crash | `ma.regime.detect()` | R4 probability vector rising |
| Pre-crash | `ma.context.assess()` | `trading_allowed` goes False on black swan |
| During | `compute_regime_stop(4)` | 1.5x — tightest stop |
| During | `score_entry_level()` | Momentum override fires (MACD extreme) |
| Stabilization | `run_daily_checks(regime_id=2)` | IV rank 85%+ makes everything pass |
| Stabilization | `compute_position_size(safety_factor=0.25)` | Quarter Kelly |
| Recovery | `select_optimal_dte()` | Front-month theta advantage |
| Recovery | `audit_decision()` | Full 4-level before every trade |
| Normal | `calibrate_weights()` | Learn from crash outcomes |
