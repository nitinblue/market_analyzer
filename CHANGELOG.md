# Changelog

All notable changes to market_analyzer will be documented in this file.

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
