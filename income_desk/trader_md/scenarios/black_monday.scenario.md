---
key: black_monday
name: "Black Monday (-30% Flash Crash)"
category: crash
severity: extreme
historical_analog: "1987 Black Monday, 2020 March 16"
expected_duration_days: 1
monte_carlo_paths: 10000
---

# Black Monday (-30% Flash Crash)

## Narrative

An extreme single-day crash of 30% — the kind that happens once a generation. Circuit breakers are triggered multiple times. All correlations go to 1 as forced liquidation overwhelms all asset classes simultaneously. Market makers widen spreads to absurd levels or pull quotes entirely. Options markets become effectively untradeable as bid-ask spreads blow out to dollars. Margin calls cascade through prime brokers, forcing liquidation of even well-positioned portfolios. The event is typically triggered by a combination of systemic leverage, a fundamental shock, and mechanical feedback loops (portfolio insurance in 1987, dealer gamma hedging in modern markets).

## Trigger Conditions

- Overnight futures limit down before cash open
- Circuit breakers (Level 1 at -7%) triggered within first hour
- Multiple market halts in a single session
- Broker platforms experience outages from order volume
- VIX spikes above 60 intraday
- Global contagion — all major indices selling simultaneously

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| equity     | -30%     | Extreme single-day crash               |
| rates      | +15%     | Panic flight to treasuries             |
| volatility | +200%    | VIX triples or more                    |
| commodity  | -10%     | Liquidation selling hits everything    |
| tech       | -15%     | Leveraged tech positions unwound       |
| currency   | +10%     | USD panic bid, EM currencies crash     |

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | +35%   | IV explodes across all strikes/tenors  |
| skew_steepening | +25%   | OTM puts become effectively unpriceable|

## Cross-Asset Correlations

| Pair              | Normal | This Scenario | Why                        |
|-------------------|--------|---------------|----------------------------|
| SPY - QQQ         | 0.85   | 0.98          | Everything sells together   |
| SPY - TLT         | -0.30  | -0.70         | Maximum flight to safety    |
| SPY - GLD         | 0.05   | -0.10         | Gold bid but also liquidated|
| SPY - IWM         | 0.80   | 0.98          | No diversification benefit  |
| QQQ - ARKK        | 0.75   | 0.99          | Speculative growth destroyed|

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | -30%          | All short positions max loss. Account survival at stake |
| Single-stock opts | -30% to -50%  | Many stocks halted, options untradeable |
| Bonds / TLT       | +10% to +15%  | Treasury rally is enormous     |
| Gold / GLD        | -3% to +5%    | Mixed — liquidation vs haven   |
| Cash              | 0%            | Only true safe asset           |

## Trading Response

- **Immediate**: Do NOT trade during the crash. Spreads are too wide, fills will be terrible. Assess account survival — are any positions at risk of assignment or margin call? Contact broker if margin is at risk.
- **Day 1-3**: Assess damage. Close any remaining short positions at market open if they are recoverable. Do NOT average down. Wait for circuit breakers to reset and orderly trading to resume. This is R4 extreme — capital preservation is the only objective.
- **Day 5-10**: After the initial shock, vol will remain elevated for weeks. Begin small defined-risk premium selling (iron condors, put spreads) at 2-3x normal width. VIX above 50 means enormous premium available, but size must be tiny (10-20% of normal).
- **Position sizing**: Maximum 10-15% of account at risk. Any single position should be less than 2% of account. Survival first, profits later.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 1987-10-19 | Black Monday       | -22.6%   | N/A (est. 150)| 400             |
| 2020-03-16 | COVID Monday       | -12.0%   | 82            | 140             |
| 2010-05-06 | Flash Crash        | -9.2%    | 40            | 3               |
| 2020-03-12 | COVID Thursday     | -9.5%    | 75            | 140             |
