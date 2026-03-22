# Changelog

All notable changes to income_desk will be documented in this file.

## [1.0.0] - 2026-03-22

### Breaking Changes
- **Module renamed**: `market_analyzer` → `income_desk`. All imports change: `from income_desk import ...`
- **User config directory**: `~/.market_analyzer/` → `~/.income_desk/`
- See `ETRADING_MIGRATION.md` for migration steps

### Added
- **Desk Management**: 6 APIs — capital allocation by asset class (Options/Stocks/Metals/Futures) → risk type (defined/undefined) → desks
- **Demo Portfolio**: `--demo` flag, `trade`/`portfolio`/`close_trade` commands, simulated $100K trading
- **Trader Runners**: `Trader-US.py` and `Trader-IND.py` — end-to-end simulation scripts
- **CSV Trade Import**: Import positions from thinkorswim, TastyTrade, Schwab, IBKR, Fidelity, Webull, or generic CSV
- **Multi-Account Consolidation**: Cross-broker portfolio view from CSV imports
- **Simulated Market Data**: 8 presets (calm, volatile, crash, income, recovery, wheel, india, india_trading) + snapshot refresh
- **Assignment Workflows**: CSP/wheel analysis, covered call, assignment handling, assignment risk warning
- **Cash vs Margin Analytics**: Structure-based margin buffers, regime-adjusted BP
- **Interest Rate Risk**: Per-ticker + portfolio rate sensitivity assessment
- **4 New Brokers**: Alpaca (free tier), IBKR, Schwab/thinkorswim, Dhan (India)
- **Setup Wizard**: `--setup` for guided broker connection
- **BYOD Adapters**: CSVProvider, DictQuoteProvider, IBKR/Schwab skeletons
- **Fitness-for-Purpose**: Every output classified as fit for live_execution/paper_trading/screening/research/education
- **Open Source Infrastructure**: README, CONTRIBUTING, LICENSE (MIT), CI, issue templates, SECURITY, CODE_OF_CONDUCT
- **Published to PyPI**: `pip install income-desk`

---

## [0.3.0] - 2026-03-21

### Added
- **Validation Framework**: 10-check daily profitability gate + 3-check adversarial stress
- **Entry-Level Intelligence**: 6 functions (strike proximity, skew selection, entry scoring, limit pricing, pullback alerts, IV rank quality)
- **Exit Intelligence**: Regime-contingent stops, trailing profit targets, theta decay curve comparison
- **Position Sizing**: Kelly criterion + correlation adjustment + margin-regime interaction
- **DTE Optimizer**: Vol surface theta proxy for optimal expiration selection
- **Decision Audit**: 4-level trade report card (leg/trade/portfolio/risk)
- **Crash Sentinel**: GREEN/YELLOW/ORANGE/RED/BLUE market health monitoring
- **Data Trust Framework**: 2-dimensional trust scoring (data quality + context quality)
- **Position Stress Monitoring**: Ongoing adversarial checks on open positions
- **Monitoring Actions**: Concrete closing TradeSpec on exit triggers
- **Strategy Switching**: CONVERT_TO_DIAGONAL on regime change
- **India Fixes**: Registry-based strike intervals, fallback legs for NIFTY/BANKNIFTY

### Fixed
- POP estimator max_loss computation
- Credit estimation without broker
- Adversarial stress graceful degradation on invalid params
- Momentum override prevents falling knife entries

## [0.2.0] - 2026-03-12

### Added
- Trade lifecycle APIs (10 pure functions)
- Universe scanner with 4 presets
- TradeSpec factory with DXLink conversion
- 32→67 CLI commands

## [0.1.0] - 2026-02-23

### Added
- Initial release: regime detection, technical analysis, opportunity assessment
- 11 option play assessors
- 4 setup assessors
- Ranking engine with 11 strategy types
- TastyTrade broker integration
