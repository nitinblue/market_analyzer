# Live Test Run: India Market — 2026-03-29

> Broker: Dhan | Market: India | All 16 workflows passed (status OK)
> **BUT: "OK" means the workflow ran without crashing, NOT that the output is correct.**

## Summary

| Phase | Workflow | Status | Data Quality |
|-------|----------|--------|--------------|
| 1-PreMarket | market_context | OK | GOOD — environment cautious, trading allowed, macro events correct |
| 1-PreMarket | check_portfolio_health | OK | GOOD — regimes detected, R4/R2 split looks right |
| 1-PreMarket | generate_daily_plan | OK | ISSUE — runs too early, should be last step |
| 1-PreMarket | snapshot_market | OK | GOOD — prices, IVR, ATR%, RSI all populated from Dhan |
| 2-Scanning | scan_universe | OK | BUG — TCS appears twice (duplicate), only 2/7 passed |
| 2-Scanning | rank_opportunities | OK | BAD — runs on all 7 tickers not scan output. POP 1%, credits nonsensical |
| 3-Entry | validate_trade | OK | BAD — passes ALL gates on garbage (current_price=0, wrong regime) |
| 3-Entry | size_position | OK | CORRECT — returns 0 contracts (right answer for bad input) |
| 3-Entry | price_trade | OK | MIXED — real quotes from Dhan but strikes too narrow (5pt on 1000 stock) |
| 4-Monitoring | monitor_positions | OK | DEMO — no real positions, rationale empty |
| 4-Monitoring | adjust_position | OK | DEMO — hold with no rationale |
| 4-Monitoring | assess_overnight_risk | OK | DEMO — all low risk, rationale empty |
| 5-PortfolioRisk | aggregate_portfolio_greeks | OK | DEMO — fake Greeks (all 20% IV) |
| 5-PortfolioRisk | stress_test_portfolio | OK | DEMO — PnL% values absurd (-1260%) |
| 6-Calendar | check_expiry_day | OK | DEMO — rationale empty |
| 7-Reporting | generate_daily_report | OK | STALE — no real trades to report |

## Bugs Found

| Key | Bug | Severity | Root Cause |
|-----|-----|----------|------------|
| BUG-002 | ICICIBANK/SBIN 404 on yfinance (needs .NS suffix) | P0 | India ticker mapping missing |
| BUG-003 | POP 1% for all ranked trades | P0 | Missing option chain data (from BUG-002) |
| BUG-004 | Credits INR 0.15-0.63 for ICs — untradeable | P0 | Bad strike selection + missing data |
| BUG-005 | Validate passes ALL gates on garbage input (price=0) | P1 | Gates don't check data quality |
| BUG-006 | Sizer returns 0 contracts on impossible inputs | P1 | Upstream garbage, no input validation |
| BUG-007 | Wing width 5 points on INR 1000 stock, IV 0.5% | P1 | US defaults used for India, Dhan IV format |

## Feedback Captured

| Key | Feedback |
|-----|----------|
| FB-005 | daily_plan should be last step, not step 2 |
| FB-006 | Cryptic labels ("sentinel") — need plain trader language |
| FB-007 | Market context must come before health check (FIXED) |
| FB-008 | Scan duplicates (TCS 2x) |
| FB-009 | Scan output not wired to rank input |

## Noise in Output

- FRED PCRATIOPCE + EQUITPC: both 400 errors with full tracebacks (should be suppressed)
- NIFTY/BANKNIFTY chain price mismatch warnings (3x each)
- yfinance 404 errors: 11x ICICIBANK + 11x SBIN (retry flood)

## What Worked

- Dhan broker connection
- Market context (environment, macro events, intermarket)
- Regime detection (R4/R2 split correct)
- Market snapshot (prices, IVR, ATR%, RSI from live data)
- Price trade (real bid/ask quotes from Dhan, underlying price correct)

## Priority Fix Order

1. BUG-002 — India ticker .NS mapping (unblocks BUG-003, BUG-004)
2. FB-009 — Wire scan → rank pipeline
3. BUG-005 — Gate data quality checks
4. BUG-007 — India-specific wing width + IV format
5. FB-005 — Reorder daily_plan to last
6. Suppress FRED/yfinance error flood
