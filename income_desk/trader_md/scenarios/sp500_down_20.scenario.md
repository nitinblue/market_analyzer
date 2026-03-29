---
key: sp500_down_20
name: "S&P 500 -20% Bear Market"
category: crash
severity: severe
historical_analog: "2020 COVID crash, 2022 bear market"
expected_duration_days: 30
monte_carlo_paths: 5000
---

# S&P 500 -20% Bear Market

## Narrative

A full bear market decline of 20% that unfolds over weeks to months. This is a regime change — not a dip to buy but a fundamental repricing of risk assets. Everything sells except treasuries. VIX sustains above 40, dealer gamma turns deeply negative amplifying moves in both directions, and liquidity deteriorates across all markets. Credit markets seize up, margin calls cascade through the system, and systematic strategies (risk parity, vol targeting) are forced to de-lever. The decline features violent bear market rallies (5-8% in days) that trap buyers before resuming lower. Recovery takes months, not weeks.

## Trigger Conditions

- SPX breaks below 200-day moving average on massive volume
- VIX sustains above 35 for multiple sessions
- Credit spreads blow out (HY OAS +200bp)
- Fed or major central bank signals policy error
- Recession indicators trigger (yield curve inversion, ISM < 45)
- Multiple consecutive weeks of equity fund outflows

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| equity     | -20%     | Full bear market decline               |
| rates      | +10%     | Massive flight to safety               |
| volatility | +100%    | VIX doubles and sustains above 40      |
| commodity  | -5%      | Demand destruction hits commodities    |
| tech       | -10%     | Growth hammered as multiples compress  |
| currency   | +5%      | USD strengthens on safe-haven flows    |

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | +20%   | Sustained elevated IV across all tenors|
| skew_steepening | +15%   | Deep OTM puts extremely expensive      |

## Cross-Asset Correlations

| Pair              | Normal | This Scenario | Why                        |
|-------------------|--------|---------------|----------------------------|
| SPY - QQQ         | 0.85   | 0.95          | All equities sell together  |
| SPY - TLT         | -0.30  | -0.65         | Treasuries are the only haven|
| SPY - GLD         | 0.05   | -0.20         | Gold bid on fear            |
| SPY - IWM         | 0.80   | 0.95          | Small caps decimated        |
| QQQ - TLT         | -0.25  | -0.60         | Growth/bond divergence extreme|

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | -20%          | All short put positions breached, max loss likely |
| Single-stock opts | -20% to -35%  | High-beta stocks destroyed      |
| Bonds / TLT       | +8% to +12%   | Strong treasury rally           |
| Gold / GLD        | +5% to +8%    | Safe-haven rally                |
| Cash              | 0%            | Capital preservation paramount  |

## Trading Response

- **Immediate**: Close all short premium positions. Go to cash or net long vol. This is R4 — survival mode. Do not try to sell premium into a bear market.
- **Day 1-3**: Hedge remaining positions with long puts or put debit spreads. Reduce position count to essential holdings only. Consider long VIX call spreads as portfolio insurance.
- **Day 5-10**: Only risk-defined strategies with small size. If selling premium, use 90+ DTE, deep OTM (2+ standard deviations), and accept lower premium for safety. Watch for VIX term structure inversion as a signal of peak panic.
- **Position sizing**: Reduce to 25% of normal size. Preserve capital for the recovery. A 50K account should have no more than 12-15K at risk total.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 2020-03-23 | COVID crash bottom  | -34%     | 82            | 140             |
| 2022-10-12 | 2022 bear bottom   | -25%     | 33            | 290             |
| 2018-12-24 | Q4 2018 low        | -20%     | 36            | 60              |
| 2011-10-03 | Euro crisis low    | -19%     | 43            | 120             |
