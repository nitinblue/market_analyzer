---
key: india_budget_rally
name: "India Budget Rally"
category: rally
severity: mild
historical_analog: "2024 interim budget rally"
expected_duration_days: 10
monte_carlo_paths: 1000
---

# India Budget Rally

## Narrative

A pro-growth Union Budget triggers a sharp rally in Indian equities. Infrastructure, banking, and consumption sectors lead the advance as fiscal spending plans exceed expectations. FII sentiment turns positive and inflows resume after a period of selling. The rupee strengthens modestly on improved growth outlook, and India VIX compresses as uncertainty around fiscal policy resolves. BANKNIFTY outperforms NIFTY as bank credit growth expectations are revised higher. The rally is front-loaded (biggest moves on budget day and the following 2-3 sessions) before settling into a more gradual uptrend. Small and mid-cap stocks often rally even harder than the index on budget beneficiary themes.

## Trigger Conditions

- Budget announces higher-than-expected capex spending (infra, defense)
- No negative surprises on LTCG or STT (options taxation fears not realized)
- Fiscal deficit target maintained despite higher spending
- Tax relief for middle class boosts consumption narrative
- FM signals continued reform agenda

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| equity     | +5%      | Broad NIFTY rally on budget optimism   |
| rates      | -2%      | Bond yields ease on fiscal discipline  |
| volatility | -20%     | India VIX collapses post-event         |
| currency   | +3%      | INR strengthens on FII inflows         |

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | -3%    | IV crushes as uncertainty resolves     |
| skew_steepening | -2%    | Put demand evaporates                  |

## Cross-Asset Correlations

| Pair                  | Normal | This Scenario | Why                        |
|-----------------------|--------|---------------|----------------------------|
| NIFTY - BANKNIFTY     | 0.90   | 0.85          | Banks outperform modestly   |
| NIFTY - INR (inverse) | 0.40   | 0.50          | Both strengthen together    |
| NIFTY - Gold (INR)    | -0.05  | 0.05          | Gold flat in INR terms      |
| NIFTY - Mid-cap index | 0.80   | 0.90          | Mid-caps rally harder       |

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | +5%           | Short put positions profit from IV crush and rally |
| Single-stock opts | +5% to +12%   | Budget beneficiaries (infra, banks) surge |
| Bonds / Gilts     | +1% to +2%    | Mild bond rally on fiscal discipline |
| Gold / SGBs       | -1% to +1%    | Minimal gold impact            |
| Cash              | 0%            | Deploy into post-budget trades  |

## Trading Response

- **Immediate**: Let existing short puts expire profitably. Take profits on any pre-budget vol positions. Do NOT chase the rally with new long positions — the biggest move is already done.
- **Day 1-3**: Sell premium on budget beneficiary themes — BANKNIFTY put spreads, infra stock put spreads. IV crush means premium is thinner but win rate is high. This is R1 territory — low-vol, mean-reverting. Classic theta.
- **Day 5-10**: Look for budget theme laggards that haven't rallied yet. Sell puts on quality names that dipped pre-budget and are now recovering. Maintain bullish bias with put credit spreads.
- **Position sizing**: Normal to slightly above normal. Post-budget low-vol is favorable for income strategies.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 2024-02-01 | Interim budget     | NIFTY +2%| 14 (India VIX)| N/A (continued) |
| 2023-02-01 | Union Budget       | NIFTY +1%| 15 (India VIX)| N/A             |
| 2021-02-01 | Budget rally       | NIFTY +5%| 22 (India VIX)| N/A (continued) |
| 2020-02-01 | Pre-COVID budget   | NIFTY -2%| 17 (India VIX)| N/A (COVID hit) |
