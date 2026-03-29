# Technical References

> Type: INFO | Last updated: 2026-03-29

## Workflow APIs (16 total)
All in `income_desk/workflow/`. Each takes a Pydantic request + MarketAnalyzer, returns Pydantic response.

| API | Module | Purpose |
|-----|--------|---------|
| check_portfolio_health | portfolio_health | Market pulse (sentinel), regime distribution |
| generate_daily_plan | daily_plan | Full trading plan for the day |
| snapshot_market | market_snapshot | Batch ticker snapshots (price, regime, IV) |
| scan_universe | scan_universe | Screen tickers against regime + technical filters |
| rank_opportunities | rank_opportunities | Score, rank, size trade proposals |
| validate_trade | validate_trade | 10-check validation gate |
| size_position | size_position | Kelly criterion position sizing |
| price_trade | price_trade | Live leg quotes, entry price |
| monitor_positions | monitor_positions | Exit condition checks |
| adjust_position | adjust_position | Adjustment recommendations |
| assess_overnight_risk | overnight_risk | EOD risk assessment |
| aggregate_portfolio_greeks | portfolio_greeks | Net delta/gamma/theta/vega |
| check_expiry_day | expiry_day | Expiry day logic (India/US) |
| stress_test_portfolio | stress_test | 18 macro scenario stress test |
| generate_daily_report | daily_report | EOD summary |
| run_benchmark | benchmarking | POP/regime/score calibration |

## Harness
- Location: `income_desk/trader/trader.py`
- Run: `python -m income_desk.trader --all --market=US`
- Purpose: daily pre-market checks, go-live validation, developer onboarding
- 7 phases, 15 workflows, pass/fail summary

## Trader MD
- Location: `income_desk/trader_md/`
- Run: `python -m income_desk.trader_md run workflows/daily_us.workflow.md`
- 5 file types: .workflow.md, .scenario.md, .broker.md, .universe.md, .risk.md
- CLI: run, validate, dry-run, --set key=value, --report path.md

## Dhan Broker
- Auth: DHAN_CLIENT_ID + DHAN_ACCESS_TOKEN in .env
- Rate limits: 25 req/s general, 1 per 3s for option_chain
- IV convention: Dhan returns percentage (e.g. 22.5), convert to decimal (0.225)
- Known issues: no intraday for indices, pre-market bid/ask = 0, 805 errors at scale

## PyPI
- Package: `income-desk`, current version: 1.1.1
- Next: 2.0.0 with trader_md
- CI: GitHub Actions, secret: PYPI_PUBLISH
- Publish: on GitHub release creation
