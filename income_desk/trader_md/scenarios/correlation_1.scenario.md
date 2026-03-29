---
key: correlation_1
name: "Correlation Spike (All Assets Down)"
category: crash
severity: extreme
historical_analog: "2020 March liquidity crisis, 2008 Lehman"
expected_duration_days: 5
monte_carlo_paths: 10000
---

# Correlation Spike (All Assets Down)

## Narrative

A liquidity crisis causes all asset classes to sell simultaneously — stocks, bonds, gold, crypto, everything. The normal diversification relationships break down completely as forced liquidation overwhelms all markets. Margin calls cascade through prime brokers, forcing even well-hedged portfolios to sell. The only asset that holds value is cash. VIX spikes to 60-80 territory as the market enters pure panic mode. This is the worst-case scenario for any portfolio — there is no hedge that works because the thing you hedged with is also selling. The crisis is typically triggered by a credit event (Lehman 2008, margin calls 2020) or a systemic failure that drains liquidity from all markets simultaneously.

## Trigger Conditions

- Bonds and stocks sell simultaneously for 3+ consecutive days
- VIX spikes above 50 while TLT also falls
- Credit spreads blow out (HY OAS +400bp)
- Money market funds see redemptions (breaking the buck)
- Major financial institution announces distress or failure
- Fed announces emergency lending facilities

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| equity     | -15%     | Broad liquidation selling              |
| rates      | -5%      | Bonds sell on liquidity panic          |
| volatility | +150%    | VIX triples on systemic fear           |
| commodity  | -10%     | Gold, oil, metals all liquidated       |
| tech       | -10%     | Tech sold for liquidity                |
| currency   | +10%     | USD cash hoarding, EM currencies crash |

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | +25%   | IV explodes across all assets          |
| skew_steepening | +20%   | Extreme put demand, no supply          |

## Cross-Asset Correlations

| Pair              | Normal | This Scenario | Why                        |
|-------------------|--------|---------------|----------------------------|
| SPY - TLT         | -0.30  | 0.60          | Both sell — correlation inverts |
| SPY - GLD         | 0.05   | 0.50          | Gold sells with stocks     |
| SPY - QQQ         | 0.85   | 0.98          | All equities perfectly correlated |
| TLT - GLD         | 0.25   | 0.50          | Both liquidated together   |
| SPY - BTC         | 0.30   | 0.90          | Crypto sells with everything|

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | -15%          | All positions at max loss       |
| Single-stock opts | -15% to -30%  | Liquidation hits everything     |
| Bonds / TLT       | -3% to -5%   | Bonds fail as hedge — they sell too |
| Gold / GLD        | -5% to -10%  | Gold liquidated for margin calls|
| Cash              | 0%            | Only safe asset — cash is king  |

## Trading Response

- **Immediate**: This is survival mode. Do NOT try to sell premium — spreads are absurdly wide and fills will be terrible. Assess account-level risk. If margin call is imminent, close positions to raise cash. Contact broker preemptively. R4 extreme — preservation only.
- **Day 1-3**: Wait for Fed/central bank intervention (liquidity facilities, repo operations). The crisis resolves when central banks step in. Do NOT buy the dip until intervention is confirmed.
- **Day 5-10**: After intervention, vol remains elevated for weeks. Begin with tiny defined-risk positions (put spreads at 3x normal width). VIX above 50 means enormous premium, but account should be at most 15-20% deployed.
- **Position sizing**: Absolute minimum. No more than 10% of account at risk. A 50K account should have at most $5K exposed. Survival is the only objective.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 2020-03-12 | COVID liquidity crisis | SPX -10%, TLT -5% | 75 (VIX) | 140         |
| 2008-10-10 | Lehman aftermath   | SPX -18% week | 80 (VIX)  | 350             |
| 2020-03-18 | Everything sells   | GLD -5%, TLT -4% | 82 (VIX) | 140           |
| 2008-11-20 | Credit crisis trough| SPX -52% peak-trough | 81 (VIX)| 350          |
