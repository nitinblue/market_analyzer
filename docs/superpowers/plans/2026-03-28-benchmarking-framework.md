# Benchmarking Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a framework to measure whether income_desk's predictions (regime labels, POP estimates, rank scores) are accurate over time. Runs after-the-fact, never in the critical trading path.

**Architecture:** income_desk provides pure-function calibration APIs. eTrading captures predictions at entry, records outcomes at exit, and feeds data back. Benchmarking runs as a batch job (daily EOD or weekly) — never during trading hours.

**Tech Stack:** Python 3.12, Pydantic models, existing `TradeOutcome` + `calibrate_weights()` infrastructure

**Spec:** `docs/superpowers/specs/2026-03-28-workflow-harness-design.md` (Trust Verification section)

---

## Separation of Concerns

| Responsibility | Owner | When |
|---------------|-------|------|
| Capture prediction at trade entry (regime, POP, score, IV rank) | eTrading | At order fill |
| Record outcome at trade exit (P&L, win/loss, holding period) | eTrading | At close/expire |
| Store prediction+outcome pairs | eTrading | Database |
| Provide calibration APIs (pure functions) | income_desk | On demand |
| Run batch analysis & produce reports | Either | EOD / weekly |

**Critical: benchmarking is NEVER in the trading path.** It's after-the-fact analysis that runs on historical data.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `income_desk/benchmarking/__init__.py` | Package exports |
| `income_desk/benchmarking/models.py` | `PredictionRecord`, `OutcomeRecord`, `CalibrationReport` Pydantic models |
| `income_desk/benchmarking/calibration.py` | Pure functions: POP calibration, regime accuracy, score correlation |
| `income_desk/benchmarking/report.py` | Generate human-readable calibration reports |

---

### Task 1: Benchmarking Models

**Files:**
- Create: `income_desk/benchmarking/__init__.py`
- Create: `income_desk/benchmarking/models.py`
- Test: `tests/test_benchmarking_models.py`

- [ ] **Step 1: Write test for PredictionRecord model**

```python
# tests/test_benchmarking_models.py
from income_desk.benchmarking.models import PredictionRecord, OutcomeRecord

def test_prediction_record():
    pred = PredictionRecord(
        trade_id="T-001", ticker="SPY", timestamp="2026-03-28T10:00:00",
        regime_id=1, regime_confidence=0.85,
        pop_pct=0.70, composite_score=82.3,
        iv_rank=43.0, entry_credit=1.45,
        structure="iron_condor",
    )
    assert pred.regime_id == 1
    assert pred.pop_pct == 0.70

def test_outcome_record():
    out = OutcomeRecord(
        trade_id="T-001", ticker="SPY",
        entry_timestamp="2026-03-28T10:00:00",
        exit_timestamp="2026-04-10T14:00:00",
        pnl=95.0, is_win=True,
        holding_days=13,
        regime_at_exit=1, regime_persisted=True,
    )
    assert out.is_win is True
```

- [ ] **Step 2: Run test — verify it fails**
- [ ] **Step 3: Implement models**

```python
# income_desk/benchmarking/models.py
from pydantic import BaseModel

class PredictionRecord(BaseModel):
    """What income_desk predicted at trade entry. eTrading captures and stores this."""
    trade_id: str
    ticker: str
    timestamp: str
    regime_id: int
    regime_confidence: float
    pop_pct: float | None = None
    composite_score: float | None = None
    iv_rank: float | None = None
    entry_credit: float | None = None
    structure: str = ""
    market: str = "US"

class OutcomeRecord(BaseModel):
    """Actual trade outcome. eTrading records this at exit."""
    trade_id: str
    ticker: str
    entry_timestamp: str
    exit_timestamp: str
    pnl: float
    is_win: bool
    holding_days: int
    regime_at_exit: int | None = None
    regime_persisted: bool | None = None  # did regime stay the same entry→exit?
    exit_reason: str = ""  # "profit_target", "stop_loss", "expiry", "manual"

class CalibrationReport(BaseModel):
    """Output of calibration analysis."""
    period: str  # "2026-03" or "2026-Q1"
    total_trades: int
    # POP calibration
    pop_buckets: list[dict] = []  # [{predicted: 0.70, actual_win_rate: 0.65, count: 23}]
    pop_rmse: float | None = None
    # Regime accuracy
    regime_persistence_rate: float | None = None  # % of trades where regime didn't change
    regime_accuracy_by_id: dict[int, dict] = {}  # {1: {count: 50, correct: 42, accuracy: 0.84}}
    # Score correlation
    score_win_correlation: float | None = None  # Pearson r between score and win
    avg_score_winners: float | None = None
    avg_score_losers: float | None = None
    # Overall
    win_rate: float | None = None
    avg_pnl: float | None = None
    summary: str = ""
```

- [ ] **Step 4: Run test — verify it passes**
- [ ] **Step 5: Commit**

---

### Task 2: Calibration Functions

**Files:**
- Create: `income_desk/benchmarking/calibration.py`
- Test: `tests/test_benchmarking_calibration.py`

- [ ] **Step 1: Write tests for calibration functions**

```python
def test_pop_calibration():
    """POP estimate of 70% should win ~70% of the time."""
    from income_desk.benchmarking.calibration import calibrate_pop
    predictions = [
        PredictionRecord(trade_id=f"T-{i}", ticker="SPY", timestamp="", regime_id=1,
                         regime_confidence=0.8, pop_pct=0.70)
        for i in range(100)
    ]
    outcomes = [
        OutcomeRecord(trade_id=f"T-{i}", ticker="SPY", entry_timestamp="",
                      exit_timestamp="", pnl=50 if i < 70 else -150,
                      is_win=i < 70, holding_days=14)
        for i in range(100)
    ]
    report = calibrate_pop(predictions, outcomes)
    assert len(report) > 0  # has buckets

def test_regime_accuracy():
    from income_desk.benchmarking.calibration import regime_accuracy
    # ... test that regime persistence is calculated correctly

def test_score_correlation():
    from income_desk.benchmarking.calibration import score_vs_outcome
    # ... test Pearson correlation between score and win rate
```

- [ ] **Step 2: Implement calibration.py**

Pure functions:
- `calibrate_pop(predictions, outcomes) -> list[dict]` — bucket by POP range, compute actual win rate per bucket
- `regime_accuracy(predictions, outcomes) -> dict` — did regime persist? accuracy by regime ID
- `score_vs_outcome(predictions, outcomes) -> dict` — correlation between composite_score and is_win
- `generate_calibration_report(predictions, outcomes, period) -> CalibrationReport` — full report

- [ ] **Step 3: Run tests**
- [ ] **Step 4: Commit**

---

### Task 3: Calibration Report Generator

**Files:**
- Create: `income_desk/benchmarking/report.py`

- [ ] **Step 1: Implement report generation**

```python
def format_calibration_report(report: CalibrationReport) -> str:
    """Format CalibrationReport as human-readable text with tables."""
```

- [ ] **Step 2: Add CLI command for benchmarking**

Add `benchmark` command to `cli/interactive.py`:
```
analyzer-cli> benchmark --period=2026-03
```

- [ ] **Step 3: Commit**

---

### Task 4: eTrading Collaboration Note

**Files:**
- Create: `.collab/FEEDBACK_benchmarking_integration.md`

- [ ] **Step 1: Write collaboration note**

Document exactly what eTrading needs to capture and send back.

- [ ] **Step 2: Commit**
