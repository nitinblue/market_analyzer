---
key: sp500_down_10
name: "S&P 500 -10% Correction"
category: crash
severity: moderate
historical_analog: "2022 Q1 correction, 2018 Q4 sell-off"
expected_duration_days: 15
monte_carlo_paths: 1000
---

# S&P 500 -10% Correction

## Narrative

A sharp 10% correction that shakes out weak hands and triggers systematic selling (CTAs, vol-target funds). Flight to safety is pronounced — bonds rally meaningfully, gold catches a bid, and volatility doubles from baseline. This is more than a positioning unwind; there is typically a fundamental catalyst (policy mistake, earnings disappointment, credit stress). The correction unfolds over 2-3 weeks with multiple failed bounces before stabilizing. Options markets see significant put buying and dealer hedging flows that amplify the downside.

## Trigger Conditions

- SPX drops 3%+ on two consecutive sessions
- VIX breaks above 30 and stays elevated
- Credit spreads widen (HY OAS +50bp)
- Market breadth collapses — fewer than 20% of components above 50-day MA
- Margin calls trigger forced selling in leveraged strategies

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| equity     | -10%     | Broad market sell-off                  |
| rates      | +5%      | Strong flight to safety into treasuries|
| volatility | +60%     | Vol doubles from baseline              |
| commodity  | +5%      | Gold/safe-haven bid                    |
| tech       | -5%      | Growth underperforms on higher vol     |

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | +10%   | Significant vol expansion              |
| skew_steepening | +8%    | OTM put skew richens sharply           |

## Cross-Asset Correlations

| Pair              | Normal | This Scenario | Why                        |
|-------------------|--------|---------------|----------------------------|
| SPY - QQQ         | 0.85   | 0.92          | Correlation rises in sell-offs|
| SPY - TLT         | -0.30  | -0.55         | Strong bond rally           |
| SPY - GLD         | 0.05   | -0.15         | Gold becomes safe haven     |
| QQQ - IWM         | 0.75   | 0.88          | Small caps sell harder      |

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | -10%          | Short put spreads breached, need adjustment |
| Single-stock opts | -10% to -15%  | High-beta names down 1.5x index|
| Bonds / TLT       | +5%           | Meaningful rally in long bonds |
| Gold / GLD        | +3%           | Safe-haven bid lifts gold      |
| Cash              | 0%            | Deploy into elevated premiums  |

## Trading Response

- **Immediate**: Close or roll any short puts that are breached. Reduce overall delta exposure. This is R4 territory — protect capital first.
- **Day 1-3**: Do NOT sell premium yet — wait for vol to stabilize. If VIX is still rising, stand aside. Consider long put hedges on concentrated positions.
- **Day 5-10**: Once VIX peaks and starts mean-reverting, begin selling elevated premium with wider wings. Put spreads at 2x normal width, 60+ DTE. This is the transition from R4 to R2.
- **Position sizing**: Reduce to 50-75% of normal size. Account drawdown demands smaller positions until recovery is confirmed.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 2022-01-04 | Q1 2022 correction | -13%     | 36            | 40              |
| 2018-12-24 | Q4 2018 sell-off   | -10%     | 36            | 25              |
| 2020-02-27 | COVID first wave   | -12%     | 40            | 30              |
| 2015-08-24 | China devaluation  | -11%     | 40            | 20              |
