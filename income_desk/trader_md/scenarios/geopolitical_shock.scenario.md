---
key: geopolitical_shock
name: "Geopolitical Shock"
category: macro
severity: severe
historical_analog: "2022 Russia-Ukraine, 2024 Middle East"
expected_duration_days: 10
monte_carlo_paths: 1000
---

# Geopolitical Shock

## Narrative

A major geopolitical event — war escalation, military confrontation, or terrorist attack — shocks markets. Oil and commodities spike on supply disruption fears, equities sell off on uncertainty, and safe havens (gold, treasuries) catch a strong bid. The initial reaction is violent and indiscriminate, with a gap down at open followed by high-volatility trading. The VIX spikes to 30-40 range. Defense stocks rally while travel, airlines, and consumer discretionary sell. The key question is duration — if the event is contained (single attack, limited military action), markets recover within days. If it escalates (full-scale war, trade embargo, sanctions), the repricing lasts weeks and creates a new regime.

## Trigger Conditions

- Military conflict between major powers or in critical region (Middle East, Taiwan Strait)
- Oil supply disruption (Strait of Hormuz, pipeline attack)
- Sanctions announced against major trading partner
- Nuclear or radiological threat escalation
- Major terrorist attack on Western financial center

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| equity     | -7%      | Risk-off selling                       |
| commodity  | +25%     | Oil/energy spike on supply fears       |
| rates      | +5%      | Flight to safety into treasuries       |
| volatility | +50%     | VIX spikes on geopolitical uncertainty  |
| currency   | -3%      | EM currencies weaken, USD/JPY bid      |

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | +8%    | Significant IV expansion across all assets |
| skew_steepening | +6%    | OTM puts heavily bid on tail risk fear |

## Cross-Asset Correlations

| Pair              | Normal | This Scenario | Why                        |
|-------------------|--------|---------------|----------------------------|
| SPY - GLD         | 0.05   | -0.40         | Gold surges, stocks sell   |
| SPY - TLT         | -0.30  | -0.55         | Strong flight to safety    |
| SPY - XLE         | 0.65   | -0.20         | Energy rallies, market sells |
| GLD - Oil         | 0.20   | 0.50          | Both spike on geopolitical risk |

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | -7%           | Short puts breached, need adjustment |
| Single-stock opts | -7% to +15%   | Defense up, airlines/travel crushed |
| Bonds / TLT       | +3% to +5%    | Safe-haven bid lifts bonds     |
| Gold / GLD        | +5% to +10%   | Strong geopolitical premium    |
| Cash              | 0%            | Wait for clarity before deploying |

## Trading Response

- **Immediate**: Close short puts on travel, airlines, consumer discretionary. Energy and defense short puts are safe. Assess whether the event is contained or escalating — the trading response depends entirely on this. R4 until clarity emerges.
- **Day 1-3**: If contained: sell premium on the vol spike. Put spreads on quality names at support. Gold and oil may give back gains quickly — consider call credit spreads on GLD/USO if containment is confirmed.
- **Day 5-10**: If escalating: shift to risk-defined only, small size. Long oil/gold via bull put spreads. Short equity via bear call spreads or long put debit spreads. R4 sustained — no naked premium selling.
- **Position sizing**: 50% of normal until situation clarity. Increase only after the geopolitical event is clearly contained or resolved.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 2022-02-24 | Russia invades Ukraine | SPX -3% | 37 (VIX)   | 30              |
| 2024-10-01 | Iran-Israel escalation| SPX -1% | 20 (VIX)    | 5               |
| 2001-09-11 | 9/11 attacks       | SPX -12% | 43 (VIX)     | 30              |
| 2003-03-20 | Iraq invasion      | SPX +2%  | 28 (VIX)     | N/A (rally)     |
