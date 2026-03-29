# Trading Activity Retrospection — eTrading ↔ ID Contract

**Purpose:** eTrading provides structured trade activity data. ID performs independent retrospection, scoring, and feedback. eTrading consumes feedback to improve AI/ML learning.

**Polling:** ID reads `etrading_retrospection_input.json` from a shared location. ID writes `id_retrospection_feedback.json` back. ID can request input updates by writing `id_retrospection_request.json`.

**Shared location:** `~/.income_desk/retrospection/`

---

## 1. Timeframes

| Timeframe | Scope | When Generated |
|-----------|-------|---------------|
| `daily` | Today's activity (decisions, trades, marks, exits) | EOD 4:15 PM ET / 3:45 PM IST |
| `weekly` | Mon–Fri aggregated | Friday EOD |
| `monthly` | Full calendar month | Last trading day |

---

## 2. eTrading Input Format (`etrading_retrospection_input.json`)

eTrading writes this file after each timeframe period ends. ID polls for it.

```json
{
  "version": "1.0",
  "generated_at": "2026-03-24T16:15:00-04:00",
  "timeframe": "daily",
  "period": {
    "start": "2026-03-24",
    "end": "2026-03-24",
    "market_hours": {"US": {"open": "09:30", "close": "16:00"}, "India": {"open": "09:15", "close": "15:30"}}
  },

  "decisions": [
    {
      "id": "dec-uuid",
      "ticker": "XLF",
      "strategy": "iron_condor",
      "score": 0.6985,
      "gate_result": "PASS",
      "response": "approved",
      "regime_at_entry": "R2",
      "pop_at_entry": 0.68,
      "ev_at_entry": 45.0,
      "income_entry_score": 0.72,
      "desk_key": "desk_mav_medium",
      "presented_at": "2026-03-24T10:30:00",
      "trade_id": "trade-uuid-if-booked",
      "rationale": "full JSON blob from decision log"
    }
  ],

  "trades_opened": [
    {
      "trade_id": "trade-uuid",
      "ticker": "XLF",
      "strategy_type": "iron_condor",
      "desk_key": "desk_mav_medium",
      "market": "US",
      "entry_price": 1.85,
      "entry_underlying_price": 48.50,
      "opened_at": "2026-03-24T10:35:00",
      "legs": [
        {
          "symbol": ".XLF260501P47",
          "action": "STO",
          "quantity": -2,
          "entry_price": 0.95,
          "strike": 47,
          "expiration": "2026-05-01",
          "option_type": "put",
          "entry_delta": -0.30,
          "entry_theta": 0.05,
          "entry_iv": 0.28
        }
      ],
      "entry_analytics": {
        "pop_at_entry": 0.68,
        "ev_at_entry": 45.0,
        "regime_at_entry": "R2",
        "income_yield_roc": 0.018,
        "breakeven_low": 46.15,
        "breakeven_high": 50.85,
        "max_profit": 185.0,
        "max_loss": 315.0,
        "trade_quality": "good",
        "trade_quality_score": 0.72,
        "gate_scale_factor": 0.85,
        "data_gaps": []
      },
      "decision_lineage": {
        "gates": [
          {"gate": "verdict", "passed": true},
          {"gate": "score", "value": 0.70, "threshold": 0.35, "passed": true},
          {"gate": "portfolio_filter", "passed": true},
          {"gate": "pop", "value": 0.68, "threshold": 0.45, "passed": true},
          {"gate": "ev", "value": 45.0, "threshold": 0, "passed": true}
        ],
        "market_context": {
          "regime_id": 2,
          "vix": 18.5,
          "spy_rsi": 52.0,
          "black_swan_level": "NORMAL"
        }
      },
      "position_size": {
        "contracts": 2,
        "kelly_fraction": 0.03,
        "capital_at_risk": 630.0,
        "capital_at_risk_pct": 1.26
      }
    }
  ],

  "trades_closed": [
    {
      "trade_id": "trade-uuid",
      "ticker": "SPY",
      "strategy_type": "iron_condor",
      "desk_key": "desk_mav_medium",
      "market": "US",
      "entry_price": 1.85,
      "exit_price": 0.50,
      "total_pnl": 135.0,
      "pnl_pct": 72.97,
      "holding_days": 12,
      "exit_reason": "profit_target",
      "exit_at": "2026-03-24T14:30:00",
      "entry_regime": "R1",
      "exit_regime": "R1",
      "max_pnl_during_hold": 165.0,
      "min_pnl_during_hold": -45.0,
      "pnl_journey": [
        {"ts": "2026-03-13T10:00", "pnl_pct": -5.0, "delta": -2.1, "dte": 48},
        {"ts": "2026-03-24T14:30", "pnl_pct": 72.97, "delta": -0.5, "dte": 37}
      ]
    }
  ],

  "trades_open_snapshot": [
    {
      "trade_id": "trade-uuid",
      "ticker": "META",
      "strategy_type": "iron_condor",
      "desk_key": "desk_leaps",
      "market": "US",
      "entry_price": 62.12,
      "current_pnl": 20.32,
      "current_pnl_pct": 0.33,
      "dte_remaining": 37,
      "health_status": "exit_triggered",
      "current_delta": -2.17,
      "current_theta": 86.10,
      "underlying_price_at_entry": 560.0,
      "underlying_price_now": 565.0,
      "legs": [
        {
          "symbol": ".META260430P520",
          "quantity": -1,
          "entry_price": 16.48,
          "current_price": 13.97,
          "current_delta": -0.25
        }
      ]
    }
  ],

  "mark_to_market_events": [
    {
      "timestamp": "2026-03-24T10:30:00",
      "trades_marked": 8,
      "trades_failed": 0,
      "total_portfolio_pnl": -3982.24,
      "pnl_change_since_last_mark": 125.50
    }
  ],

  "exit_signals": [
    {
      "trade_id": "trade-uuid",
      "ticker": "SPY",
      "signal_type": "profit_target",
      "severity": "URGENT",
      "message": "Credit decayed 50% — lock in gain",
      "triggered_at": "2026-03-24T14:00:00",
      "action_taken": "closed"
    }
  ],

  "risk_snapshots": [
    {
      "timestamp": "2026-03-24T10:30:00",
      "desk_key": "desk_mav_medium",
      "portfolio_delta": -12.5,
      "portfolio_theta": 245.0,
      "portfolio_vega": -180.0,
      "var_1d_95": 850.0,
      "capital_deployed_pct": 35.0,
      "positions_open": 5,
      "max_positions": 8,
      "drawdown_pct": 2.1,
      "can_open_new": true
    }
  ],

  "system_health": {
    "broker_connected": true,
    "broker_name": "tastytrade",
    "data_trust_score": 0.82,
    "unresolved_errors": 0,
    "regression_pass_rate": 92.0,
    "regression_total_checks": 220,
    "stale_positions_count": 0
  },

  "bandit_state": {
    "total_cells": 44,
    "cells_from_trades": 2,
    "cells_from_priors": 42,
    "top_strategies_by_regime": {
      "R1": ["ratio_spread", "zero_dte", "calendar"],
      "R2": ["iron_butterfly", "mean_reversion", "calendar"],
      "R3": ["diagonal", "leap", "momentum"],
      "R4": ["breakout", "earnings", "momentum"]
    }
  },

  "id_feedback_blockers": [
    {
      "type": "missing_trade_spec",
      "ticker": "GLD",
      "strategy": "leap",
      "message": "GO verdict but no TradeSpec/legs"
    }
  ]
}
```

---

## 3. ID Feedback Format (`id_retrospection_feedback.json`)

ID writes this after analyzing the input.

```json
{
  "version": "1.0",
  "analyzed_at": "2026-03-24T16:30:00",
  "timeframe": "daily",
  "period": {"start": "2026-03-24", "end": "2026-03-24"},

  "overall_grade": "B",
  "overall_score": 72,
  "summary": "3 trades opened, 1 closed. Win rate 100% (1/1). PnL accuracy verified. Gate discipline strong but 2 missed opportunities.",

  "decision_audit": {
    "total_decisions": 43,
    "approved": 3,
    "rejected": 40,
    "approval_rate_pct": 6.98,
    "avg_approved_score": 0.65,
    "avg_rejected_score": 0.18,
    "score_separation": "GOOD",
    "gate_consistency": {
      "score_gate_correct": 40,
      "score_gate_wrong": 0,
      "portfolio_filter_correct": 5,
      "missed_opportunities": [
        {
          "ticker": "XLE",
          "strategy": "iron_condor",
          "score": 0.42,
          "reason_rejected": "portfolio_full",
          "id_assessment": "Would have been profitable. Score threshold correct but portfolio capacity limited profitable entry.",
          "recommendation": "Consider increasing desk_medium max_positions from 8 to 10 for R1/R2 regimes"
        }
      ]
    }
  },

  "trade_audit": [
    {
      "trade_id": "trade-uuid",
      "ticker": "XLF",
      "id_entry_grade": "B+",
      "id_entry_score": 78,
      "stored_quality_score": 0.72,
      "score_match": true,
      "pnl_verified": true,
      "pnl_stored": 135.0,
      "pnl_computed": 135.0,
      "entry_timing_grade": "A",
      "strike_placement_grade": "B",
      "sizing_grade": "A",
      "issues": [],
      "improvements": [
        "Short put at 47 was 1 strike too close to support at 47.50. Consider 46.50 for wider buffer."
      ]
    }
  ],

  "risk_audit": {
    "portfolio_delta_assessment": "Within limits — net delta -12.5 vs max 500",
    "theta_harvest_efficiency": "Good — $245/day on $50K deployed",
    "var_vs_actual": {
      "var_predicted": 850.0,
      "actual_daily_pnl_change": 125.50,
      "var_breach": false
    },
    "concentration_risk": "WARN: 3/5 positions in XLF sector",
    "drawdown_status": "OK: 2.1% vs 10% halt threshold"
  },

  "pnl_verification": {
    "trades_checked": 8,
    "all_match": true,
    "mismatches": [],
    "convention_issues": []
  },

  "bandit_feedback": {
    "regime_strategy_alignment": "GOOD — R2 selecting iron_condor/mean_reversion (correct)",
    "exploration_vs_exploitation": "Healthy — 42 prior cells provide exploration, 2 trade cells exploit",
    "recommended_adjustments": [
      "R4 breakout selection needs more data — only 0 trades in R4. Consider paper-trading R4 momentum to build history."
    ]
  },

  "system_health_feedback": {
    "data_trust": "82% — acceptable for live trading",
    "regression_trend": "Improving: 82% → 89% → 92% over session",
    "error_handling": "22 issues found, 19 fixed. 2 CRITICAL crashes eliminated.",
    "blocker_response": [
      {
        "blocker": "GLD/leap missing TradeSpec",
        "id_status": "Acknowledged — LEAPs assessor needs leg construction for GLD. Fix ETA: next release.",
        "workaround": "None — GLD LEAPs will remain blocked until fix."
      }
    ]
  },

  "learning_recommendations": {
    "ml_updates": [
      "Update bandit R2_iron_condor: +1 win (XLF closed at profit_target)",
      "Seed R4_momentum with 3 paper trades from simulation scenarios"
    ],
    "gate_tuning": [
      "Consider lowering MIN_SCORE_THRESHOLD from 0.35 to 0.30 for R1 regime (low vol, high POP)",
      "Add time-of-day gate: avoid entries after 3:00 PM ET (reduced theta decay benefit)"
    ],
    "desk_management": [
      "desk_mav_medium at 20 positions — well above max_positions. Review and close stale whatif trades.",
      "desk_maya_income has capital but 0 trades in R4 — correct behavior, but will need R1/R2 shift to deploy"
    ]
  }
}
```

---

## 4. ID Request Format (`id_retrospection_request.json`)

ID writes this when it needs additional data from eTrading.

```json
{
  "version": "1.0",
  "requested_at": "2026-03-24T16:35:00",
  "requests": [
    {
      "request_id": "req-001",
      "type": "trade_detail",
      "trade_id": "trade-uuid",
      "fields_needed": ["full_pnl_journey", "all_leg_greeks_history", "exit_plan_json"],
      "reason": "Need leg-level Greeks history to compute PnL attribution accuracy"
    },
    {
      "request_id": "req-002",
      "type": "decision_context",
      "decision_id": "dec-uuid",
      "fields_needed": ["full_research_snapshot_at_entry", "vol_surface_at_entry"],
      "reason": "Need vol surface to verify strike placement was optimal"
    },
    {
      "request_id": "req-003",
      "type": "desk_history",
      "desk_key": "desk_mav_medium",
      "period": "2026-03-18 to 2026-03-24",
      "fields_needed": ["daily_pnl", "positions_opened", "positions_closed", "capital_utilization"],
      "reason": "Need desk performance trend to assess capacity recommendation"
    },
    {
      "request_id": "req-004",
      "type": "update_input",
      "message": "Please re-run retrospection with these corrections:",
      "corrections": {
        "trades_opened[0].entry_analytics.pop_at_entry": "Recalculate — stored value 0.68 doesn't match ID's 0.72 for this structure"
      }
    }
  ]
}
```

---

## 5. eTrading Implementation

### File Locations
- **Input:** `~/.income_desk/retrospection/etrading_retrospection_input.json`
- **Feedback:** `~/.income_desk/retrospection/id_retrospection_feedback.json`
- **Requests:** `~/.income_desk/retrospection/id_retrospection_request.json`
- **Archive:** `~/.income_desk/retrospection/archive/{date}_{timeframe}_input.json`

### eTrading Responsibilities
1. **Generate input** at EOD (daily), Friday EOD (weekly), month-end (monthly)
2. **Poll for requests** every 5 minutes during market hours
3. **Fulfill requests** by querying DB and writing updated input
4. **Consume feedback** → update bandit state, tune gates, log recommendations
5. **Archive** all inputs/feedback for audit trail

### Generation Service
```python
# trading_cotrader/services/retrospection_service.py
class RetrospectionService:
    def generate_input(self, timeframe: str = 'daily') -> dict: ...
    def poll_for_requests(self) -> list[dict]: ...
    def fulfill_request(self, request: dict) -> dict: ...
    def consume_feedback(self, feedback: dict) -> dict: ...
```

### Scheduler Integration
```python
# In scheduler.py — add to existing APScheduler jobs
# EOD: generate daily retrospection input
scheduler.add_job(retrospection.generate_input, 'cron', hour=16, minute=15, args=['daily'])
# Friday: generate weekly
scheduler.add_job(retrospection.generate_input, 'cron', day_of_week='fri', hour=16, minute=30, args=['weekly'])
# Poll for ID requests every 5 min during market hours
scheduler.add_job(retrospection.poll_for_requests, 'interval', minutes=5)
```

---

## 6. ID Responsibilities

1. **Poll for input** — watch for new `etrading_retrospection_input.json`
2. **Analyze independently** — recalculate PnL, re-audit decisions, verify gate consistency
3. **Write feedback** — `id_retrospection_feedback.json` with grades, issues, recommendations
4. **Request data** — write `id_retrospection_request.json` if more data needed
5. **Track trends** — compare daily → weekly → monthly for improvement trajectory

### ID Analysis Modules Needed
- `retrospect_decisions()` — re-run audit_decision on all decisions, compare with stored scores
- `retrospect_pnl()` — re-compute PnL via compute_trade_pnl, verify accuracy
- `retrospect_risk()` — validate risk limits were respected, concentration OK
- `retrospect_bandits()` — assess strategy selection quality, recommend tuning
- `retrospect_exits()` — verify exit timing, was TP/SL optimal?
- `retrospect_entries()` — verify strike placement, DTE selection, sizing

---

## 7. Learning Loop (eTrading Side)

When eTrading consumes ID feedback, it:

1. **Updates bandit state** — `ml_learning_service.update_single_bandit()` for recommended adjustments
2. **Tunes gate thresholds** — adjusts `MIN_SCORE_THRESHOLD`, `MIN_POP`, `MAX_PROPOSALS_PER_CYCLE` based on ID recommendations
3. **Updates desk config** — adjusts `max_positions`, `capital_allocation` per ID feedback
4. **Logs to DecisionLogORM** — records that a retrospection-driven change was made (decision_type='retrospection_tuning')
5. **Emits trade event** — `event_type='retrospection_applied'` for observability

Over time: daily feedback → weekly trends → monthly calibration → the system becomes intelligent.
