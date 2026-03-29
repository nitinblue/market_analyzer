# API Reference

**Moved to [README.md](README.md)** — the trading workflow tables now include an API column with exact Python function signatures for every capability.

The README organizes APIs by the 15-step trading lifecycle:

1. Portfolio setup → `recommend_desk_structure()`
2. Desk allocation → `compute_desk_risk_limits()`
3. Asset types → `ALL_OPTION_STRUCTURES`, `INCOME_STRUCTURES`
4. Risk profile → `compute_margin_buffer()`, `compute_margin_analysis()`
5. Universe → `MarketRegistry`, `WatchlistProvider`
6. Screening → `ma.screening.scan()`
7. Ranking → `ma.ranking.rank()`
8. Scenario trades → `assess_iron_condor()`, 11 assessors
9. Validation → `run_daily_checks()`, `estimate_pop()`, `filter_trades_with_portfolio()`
10. Execution → `TradeSpec`, `build_closing_trade_spec()`
11. Monitoring → `monitor_exit_conditions()`, `check_trade_health()`
12. Adjustments → `get_adjustment_recommendation()`, `handle_assignment()`
13. AI/ML learning → `calibrate_weights()`, `analyze_gate_effectiveness()`
14. Regression QA → `validate_snapshot()`, `capture_failure()`
15. Retrospection → `RetrospectionEngine`, `compose_trade_commentary()`
