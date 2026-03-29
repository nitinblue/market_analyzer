---
key: gold_crash_10
name: "Gold -10% Crash"
category: crash
severity: moderate
historical_analog: "2013 gold crash, 2022 rate hike gold sell-off"
expected_duration_days: 10
monte_carlo_paths: 1000
---

# Gold -10% Crash

## Narrative

Gold drops 10% in a sharp sell-off driven by rising real rates or a sudden strengthening of the US dollar. The move is amplified by CTA and momentum-following liquidation as gold breaks key technical levels. Commodity sector broadly weakens in sympathy, while equities may actually benefit slightly as higher real rates signal economic strength. The USD rallies as the mirror image of gold weakness. Mining stocks (GDX) fall 15-25% given their leveraged exposure to gold prices. The sell-off is fast (3-5 days of sharp losses) but the recovery is slow as the bull thesis needs to rebuild.

## Trigger Conditions

- 10Y real yield (TIPS) rises above 2.5%
- DXY breaks above 108 on strong US data
- Central bank gold buying pauses or reverses
- Gold breaks below 200-day moving average
- ETF outflows from GLD/IAU exceed $1B in a week

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| commodity  | -15%     | Gold and commodity sector sell-off     |
| rates      | -5%      | Rising yields pressure gold            |
| equity     | +2%      | Equities benefit from risk-on rotation |
| currency   | +5%      | USD strengthens as gold weakens        |

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | +0%    | No significant IV shift on gold crash  |
| skew_steepening | +3%    | Put skew on GLD/miners increases       |

## Cross-Asset Correlations

| Pair              | Normal | This Scenario | Why                        |
|-------------------|--------|---------------|----------------------------|
| GLD - SPY         | 0.05   | 0.15          | Both driven by rates       |
| GLD - TLT         | 0.25   | 0.40          | Both hurt by rising yields |
| GLD - GDX         | 0.85   | 0.92          | Miners amplify gold move   |
| GLD - DXY         | -0.40  | -0.60         | Inverse correlation strengthens |

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | +1% to +2%   | Minor positive for equity positions |
| Single-stock opts | Varies        | Mining stocks crushed, rest unaffected |
| Bonds / TLT       | -3% to -5%   | Bonds sell on higher real yields|
| Gold / GLD        | -10% to -15% | Direct hit on gold positions   |
| Cash              | 0%            | Consider buying gold dip if thesis intact |

## Trading Response

- **Immediate**: Close any short put positions on GLD or gold miners. If long gold (SGBs, GLD), assess whether the fundamental thesis has changed or this is a rates-driven move.
- **Day 1-3**: Do not catch the falling knife. Wait for technical stabilization (2-3 days of narrowing range). Gold crashes tend to have a second leg down after a dead cat bounce.
- **Day 5-10**: If gold stabilizes, sell put spreads on GLD at the new support level. Elevated miner IV offers good premium. Consider GLD put credit spreads 60 DTE.
- **Position sizing**: Normal sizing for equity positions. Reduce gold-related positions to 25% until trend stabilizes.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 2013-04-15 | Gold crash         | -13%     | 15 (VIX)      | 1800+           |
| 2022-09-01 | Rate hike sell-off | -8%      | 26 (VIX)      | 90              |
| 2020-08-07 | Post-COVID peak    | -6%      | 22 (VIX)      | 60              |
| 2016-10-04 | Post-Brexit unwind | -6%      | 14 (VIX)      | 120             |
