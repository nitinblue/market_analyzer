# Benchmarking Integration — What eTrading Needs To Do

**Date:** 2026-03-28
**From:** income_desk
**Priority:** Medium (not blocking go-live, but critical for continuous improvement)

---

## Overview

income_desk is building a benchmarking framework to measure prediction accuracy over time. This runs **after-the-fact only** — never in the trading path. eTrading's role: capture predictions at entry, record outcomes at exit, feed data back.

## What eTrading Must Capture

### At Trade Entry (order fill)

When eTrading fills a trade that was recommended by income_desk, capture a `PredictionRecord`:

```python
from income_desk.benchmarking.models import PredictionRecord

prediction = PredictionRecord(
    trade_id="your-trade-id",
    ticker="SPY",
    timestamp="2026-03-28T10:15:00",  # fill timestamp
    regime_id=1,                       # from rank/daily_plan response
    regime_confidence=0.85,            # from rank/daily_plan response
    pop_pct=0.70,                      # from TradeProposal.pop_pct
    composite_score=82.3,              # from TradeProposal.composite_score
    iv_rank=43.0,                      # from IV rank at entry
    entry_credit=1.45,                 # actual fill credit
    structure="iron_condor",           # from TradeProposal.structure
    market="US",
)
```

**Where to get these values:**
- `regime_id`, `regime_confidence` → from `RankResponse.regime_summary[ticker]`
- `pop_pct`, `composite_score`, `structure` → from `TradeProposal` in `RankResponse.trades`
- `iv_rank` → from `SnapshotResponse.tickers[ticker].iv_rank` or `iv_rank_map`
- `entry_credit` → actual fill price from broker

### At Trade Exit (close/expire/adjust)

Record an `OutcomeRecord`:

```python
from income_desk.benchmarking.models import OutcomeRecord

outcome = OutcomeRecord(
    trade_id="your-trade-id",         # same as prediction
    ticker="SPY",
    entry_timestamp="2026-03-28T10:15:00",
    exit_timestamp="2026-04-10T14:00:00",
    pnl=95.0,                         # realized P&L
    is_win=True,                       # pnl > 0
    holding_days=13,
    regime_at_exit=1,                  # re-detect regime at exit (optional)
    regime_persisted=True,             # same regime entry→exit? (optional)
    exit_reason="profit_target",       # "profit_target", "stop_loss", "expiry", "manual", "adjustment"
)
```

### Storage

Store prediction+outcome pairs in your database. Schema suggestion:

```sql
CREATE TABLE trade_predictions (
    trade_id TEXT PRIMARY KEY,
    ticker TEXT,
    timestamp TIMESTAMP,
    regime_id INT,
    regime_confidence REAL,
    pop_pct REAL,
    composite_score REAL,
    iv_rank REAL,
    entry_credit REAL,
    structure TEXT,
    market TEXT
);

CREATE TABLE trade_outcomes (
    trade_id TEXT PRIMARY KEY REFERENCES trade_predictions(trade_id),
    entry_timestamp TIMESTAMP,
    exit_timestamp TIMESTAMP,
    pnl REAL,
    is_win BOOLEAN,
    holding_days INT,
    regime_at_exit INT,
    regime_persisted BOOLEAN,
    exit_reason TEXT
);
```

## How to Run Calibration

eTrading calls income_desk calibration APIs with batched data (EOD or weekly):

```python
from income_desk.benchmarking.calibration import generate_calibration_report

# Fetch from your database
predictions = [PredictionRecord(...) for row in db.query("SELECT * FROM trade_predictions WHERE ...")]
outcomes = [OutcomeRecord(...) for row in db.query("SELECT * FROM trade_outcomes WHERE ...")]

report = generate_calibration_report(predictions, outcomes, period="2026-03")

# report.pop_buckets → [{predicted: 0.70, actual_win_rate: 0.65, count: 23}, ...]
# report.regime_persistence_rate → 0.82
# report.score_win_correlation → 0.41
# report.summary → human-readable text
```

## What This Measures

| Metric | Question | Healthy Range |
|--------|----------|--------------|
| POP calibration | Are 70% POP trades winning ~70%? | RMSE < 0.10 |
| Regime persistence | Does regime stay stable during trade? | > 75% |
| Regime accuracy | Did R1 mean-revert? Did R3 trend? | > 70% per regime |
| Score correlation | Do higher scores produce more wins? | r > 0.3 |

## Timing

- **When to capture predictions:** At order fill (synchronous, fast — just copy fields from the TradeProposal)
- **When to record outcomes:** At trade close (synchronous, fast)
- **When to run calibration:** EOD batch or weekly cron. NOT during trading hours. No latency impact.

## Timeline

This is NOT blocking go-live. Build the capture mechanism whenever convenient. Calibration becomes meaningful after ~50 trades minimum.

---

**Questions?** File a `REQUEST_benchmarking_*.md` in this channel.
