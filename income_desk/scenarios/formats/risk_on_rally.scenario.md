---
key: risk_on_rally
name: "Risk-On Rally (+8%)"
category: rally
severity: moderate
historical_analog: "2023 Q4 Santa rally, 2024 AI boom"
expected_duration_days: 20
monte_carlo_paths: 1000
---

# Risk-On Rally (+8%)

## Narrative

A broad risk-on rally where equities surge 8% over 2-3 weeks. Volatility compresses as complacency returns, bonds sell off modestly as money rotates into risk assets, and everything correlated with growth goes up. The rally is driven by a catalyst — Fed pivot, strong earnings, AI enthusiasm, or geopolitical de-escalation. Implied volatility crushes to multi-month lows, making premium selling less attractive but existing short vol positions extremely profitable. The challenge for income traders is that compressing vol means new positions yield less premium, while existing short call wings on iron condors may be tested by the upside move.

## Trigger Conditions

- SPX rallies 2%+ on consecutive weeks with expanding breadth
- VIX drops below 13 and stays compressed
- Fund flows show aggressive equity buying (retail + institutional)
- Fed signals rate cuts or dovish pivot
- Earnings season beats expectations broadly

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| equity     | +8%      | Broad market rally                     |
| rates      | -3%      | Bonds sell modestly on risk-on         |
| volatility | -30%     | Vol compresses to lows                 |
| tech       | +5%      | Tech rallies with market               |
| commodity  | +3%      | Commodity bid on growth optimism       |

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | -5%    | IV crushes on complacency              |
| skew_steepening | -3%    | Put skew flattens as fear dissipates   |

## Cross-Asset Correlations

| Pair              | Normal | This Scenario | Why                        |
|-------------------|--------|---------------|----------------------------|
| SPY - QQQ         | 0.85   | 0.90          | Everything rallies together |
| SPY - TLT         | -0.30  | -0.15         | Mild negative correlation  |
| SPY - GLD         | 0.05   | 0.10          | Gold drifts higher too     |
| SPY - IWM         | 0.80   | 0.88          | Broad participation        |

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | +8%           | Short call wings threatened     |
| Single-stock opts | +5% to +15%   | High-beta names surge          |
| Bonds / TLT       | -2% to -3%    | Mild bond weakness             |
| Gold / GLD        | +1% to +2%    | Modest gold bid                |
| Cash              | 0%            | Cash drag during rally          |

## Trading Response

- **Immediate**: Roll up or close short call wings on iron condors. Let short puts expire worthless — they're deep OTM and decaying fast. Take profits on any directional long positions that have reached targets.
- **Day 1-3**: With VIX sub-13, new iron condors yield thin premium. Shift to put credit spreads only (bullish bias). Consider selling naked puts on quality names if account size permits. This is R1 (low-vol mean reverting) — classic theta environment, but positioned for continuation.
- **Day 5-10**: Watch for signs of exhaustion (VIX bottoming, breadth narrowing). As the rally matures, widen iron condor wings and extend DTE for more premium. Be ready for the inevitable vol pop when the rally stalls.
- **Position sizing**: Normal to slightly above normal. Low-vol rallies are the best environment for income strategies.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 2023-11-01 | Q4 2023 Santa rally| SPX +12% | 12 (VIX)      | N/A (continued) |
| 2024-02-01 | AI boom rally      | SPX +10% | 13 (VIX)      | N/A (continued) |
| 2019-10-01 | Q4 2019 rally      | SPX +9%  | 13 (VIX)      | N/A             |
| 2021-03-01 | Reopening rally    | SPX +8%  | 20 (VIX)      | N/A             |
