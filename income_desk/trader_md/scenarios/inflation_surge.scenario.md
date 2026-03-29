---
key: inflation_surge
name: "Inflation Surge (CPI +2%)"
category: macro
severity: moderate
historical_analog: "2022 June CPI shock"
expected_duration_days: 10
monte_carlo_paths: 1000
---

# Inflation Surge (CPI +2%)

## Narrative

A surprise inflation print comes in 200bp above expectations, shocking markets that had been pricing in disinflation. The immediate reaction is a violent sell-off in bonds and growth stocks as the market reprices the Fed path — more hikes, higher for longer. Commodities rally as inflation hedges are bid. Energy and materials outperform while tech and consumer discretionary are crushed. The VIX spikes moderately as the inflation surprise isn't a systemic crisis but a fundamental repricing. The dollar may strengthen initially on expected rate hikes but could weaken later if inflation is seen as uncontrollable. The market takes 1-2 weeks to digest the new reality.

## Trigger Conditions

- CPI YoY prints 2%+ above consensus
- Core CPI accelerates for 3+ consecutive months
- Wage growth accelerates sharply (ECI or AHE surprise)
- Commodity prices surge alongside sticky services inflation
- Fed rhetoric shifts hawkish after the print

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| rates      | -10%     | Bond prices crash on inflation surprise|
| equity     | -5%      | Equity repricing on higher rate path   |
| commodity  | +15%     | Commodities rally as inflation hedge   |
| tech       | -8%      | Growth hammered by higher discount rates|
| volatility | +20%     | Uncertainty on policy path increases   |

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | +5%    | Moderate vol expansion                 |
| skew_steepening | +4%    | Downside protection demand rises       |

## Cross-Asset Correlations

| Pair              | Normal | This Scenario | Why                        |
|-------------------|--------|---------------|----------------------------|
| SPY - TLT         | -0.30  | 0.30          | Stocks and bonds sell together |
| SPY - GLD         | 0.05   | -0.15         | Gold rallies, stocks sell   |
| QQQ - XLE         | 0.55   | -0.20         | Tech sells, energy rallies  |
| TLT - GLD         | 0.25   | -0.30         | Bonds crash, gold rallies   |

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | -5%           | Short puts tested moderately    |
| Single-stock opts | -8% to +10%   | Sector rotation — energy up, tech down |
| Bonds / TLT       | -5% to -8%    | Bond positions lose             |
| Gold / GLD        | +5% to +8%    | Gold rallies as inflation hedge |
| Cash              | 0%            | Purchasing power declining      |

## Trading Response

- **Immediate**: Close any long bond positions. Reduce tech short put exposure. Energy/commodity short puts are safe — they benefit from inflation. This is R2 for tech, R3 for commodities.
- **Day 1-3**: Sell premium on tech names where IV has spiked. QQQ put spreads at wider widths. Consider XLE or XOM bull put spreads as energy benefits from inflation.
- **Day 5-10**: Watch next inflation print and Fed communication. If hawkish pivot confirmed, expect continued tech pressure. Rebuild positions gradually with inflation-adjusted thesis.
- **Position sizing**: Normal for commodity/energy. Reduce tech to 50% until inflation path clarifies.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 2022-06-10 | CPI 9.1% shock     | SPX -6%  | 34 (VIX)      | 15              |
| 2022-02-10 | CPI 7.5% surprise  | SPX -3%  | 28 (VIX)      | 7               |
| 2021-10-13 | CPI 6.2% surprise  | SPX -1%  | 20 (VIX)      | 3               |
| 2021-06-10 | CPI 5.4% surprise  | SPX -1%  | 18 (VIX)      | 5               |
