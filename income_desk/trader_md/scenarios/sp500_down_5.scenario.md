---
key: sp500_down_5
name: "S&P 500 -5% Correction"
category: crash
severity: mild
historical_analog: "Typical quarterly pullback"
expected_duration_days: 5
monte_carlo_paths: 1000
---

# S&P 500 -5% Correction

## Narrative

A routine 5% pullback in the S&P 500, the kind that occurs 2-3 times per year on average. Tech and growth names lead the decline as momentum unwinds, while defensive sectors and bonds see modest inflows. Implied volatility spikes but remains below panic levels (VIX typically reaches 22-28 range). The correction is driven by positioning unwinds rather than fundamental deterioration, making it a mean-reverting event that typically resolves within a week. Options markets reprice quickly, creating opportunities for premium sellers once the initial vol spike stabilizes.

## Trigger Conditions

- SPX drops 2-3% in a single session on elevated volume
- VIX spikes above 20 from sub-15 levels
- Breadth deteriorates — fewer than 30% of S&P components above 20-day MA
- No fundamental catalyst (earnings intact, no macro shock)

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| equity     | -5%      | Broad market pullback                  |
| rates      | +2%      | Flight to safety pushes bond prices up |
| volatility | +30%     | Fear premium expands                   |
| tech       | -3%      | Growth/momentum leads downside         |

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | +5%    | Moderate vol expansion on pullback     |
| skew_steepening | +3%    | Puts bid up more than calls            |

## Cross-Asset Correlations

| Pair              | Normal | This Scenario | Why                        |
|-------------------|--------|---------------|----------------------------|
| SPY - QQQ         | 0.85   | 0.90          | Tech sells with market     |
| SPY - TLT         | -0.30  | -0.45         | Bonds rally as equities dip|
| SPY - GLD         | 0.05   | 0.10          | Mild safe-haven bid        |
| QQQ - TLT         | -0.25  | -0.40         | Growth-bond divergence     |

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | -5%           | Short put spreads tested, not breached |
| Single-stock opts | -5% to -8%    | Beta-weighted singles drop more |
| Bonds / TLT       | +2%           | Long bond positions gain        |
| Gold / GLD        | +1%           | Mild safe-haven bid             |
| Cash              | 0%            | Opportunity to deploy           |

## Trading Response

- **Immediate**: Close any naked short puts near the money. Let defined-risk positions ride if within max loss tolerance.
- **Day 1-3**: Sell elevated premium — put spreads on quality names at support. This is R2 territory (high-vol mean reverting), ideal for wider credit spreads with elevated premium.
- **Day 5-10**: As vol normalizes, transition back to R1 strategies (iron condors, strangles). Take profits on vol-selling positions opened during the spike.
- **Position sizing**: Standard sizing. No account-level risk adjustments needed for a 5% correction.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 2023-10-27 | Q3 2023 correction | -5.8%    | 23            | 12              |
| 2022-01-24 | Jan 2022 dip       | -5.5%    | 28            | 5               |
| 2020-09-03 | Sep 2020 pullback  | -6.0%    | 26            | 10              |
| 2019-05-01 | Trade war fears    | -4.8%    | 21            | 8               |
