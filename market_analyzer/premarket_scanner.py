"""Pre-market unusual activity scanner — detect high-volume gap moves before open.

Scans a universe of tickers for unusual pre-market activity:
1. Gap up/down from previous close (price dislocation)
2. Volume spike vs average (institutional activity)
3. Earnings/news catalyst detection
4. Strategy recommendation based on gap type + regime

Data source: yfinance .info fields (regularMarketPrice, previousClose,
preMarketPrice, preMarketVolume, averageDailyVolume10Day)

Trading strategies for unusual moves:
- Gap & Go: momentum continuation if gap holds (R3/R4)
- Gap Fade: mean reversion if gap overextended (R1/R2)
- ORB Setup: wait for Opening Range, then trade breakout
- Options IV Crush: if earnings-driven gap, sell premium post-gap

All pure computation — eTrading fetches pre-market data, MA identifies opportunities.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel


class GapDirection(StrEnum):
    GAP_UP = "gap_up"
    GAP_DOWN = "gap_down"
    FLAT = "flat"


class GapStrategy(StrEnum):
    GAP_AND_GO = "gap_and_go"         # Momentum continuation
    GAP_FADE = "gap_fade"             # Mean reversion back toward close
    ORB_BREAKOUT = "orb_breakout"     # Wait for ORB, trade the breakout
    IV_CRUSH_SELL = "iv_crush_sell"   # Post-earnings IV crush — sell premium
    AVOID = "avoid"                   # Too risky or no edge
    WATCH = "watch"                   # Monitor but don't act yet


class PremarketAlert(BaseModel):
    """A single stock showing unusual pre-market activity."""

    ticker: str
    name: str
    previous_close: float
    premarket_price: float
    gap_pct: float                     # (premarket - close) / close × 100
    gap_direction: GapDirection
    gap_size: str                      # "small" (0.5-1.5%), "medium" (1.5-3%), "large" (3-5%), "extreme" (>5%)

    # Volume
    premarket_volume: int | None
    avg_daily_volume: int | None
    volume_ratio: float | None         # premarket_vol / (avg_daily / 6.5hrs × premarket_hours)
    volume_unusual: bool

    # Context
    has_earnings: bool                 # Earnings announced (catalyst)
    sector: str
    market_cap_category: str

    # Strategy
    recommended_strategy: GapStrategy
    strategy_rationale: str
    entry_approach: str                # "at_open", "wait_15min", "wait_for_orb", "sell_premium"
    stop_loss_approach: str            # Where to put stop
    target_approach: str               # Where to take profit

    # Risk
    risk_level: str                    # "low", "medium", "high", "extreme"
    commentary: list[str]


class PremarketScanResult(BaseModel):
    """Results of pre-market scan across a universe."""

    as_of_date: date
    market: str
    total_scanned: int
    alerts: list[PremarketAlert]
    gap_ups: int
    gap_downs: int
    extreme_moves: int                 # >5% gap
    summary: str
    commentary: list[str]


def _classify_gap(gap_pct: float) -> str:
    """Classify gap magnitude."""
    abs_gap = abs(gap_pct)
    if abs_gap > 5.0:
        return "extreme"
    elif abs_gap > 3.0:
        return "large"
    elif abs_gap > 1.5:
        return "medium"
    elif abs_gap > 0.5:
        return "small"
    return "flat"


def _select_strategy(
    gap_pct: float,
    gap_size: str,
    has_earnings: bool,
    regime_id: int,
    volume_unusual: bool,
) -> tuple[GapStrategy, str, str, str, str]:
    """Select trading strategy based on gap characteristics + regime.

    Returns: (strategy, rationale, entry, stop, target)
    """
    abs_gap = abs(gap_pct)
    direction = "up" if gap_pct > 0 else "down"

    # Earnings gap — different playbook
    if has_earnings:
        if abs_gap > 5:
            return (
                GapStrategy.IV_CRUSH_SELL,
                f"Earnings gap {gap_pct:+.1f}% — IV will crush. Sell premium on the move.",
                "sell_premium_at_open — iron condor or strangle around new price level",
                "Wing width defines max loss (defined risk)",
                "50% of premium collected (theta decay accelerated post-earnings)",
            )
        elif abs_gap > 2:
            return (
                GapStrategy.WATCH,
                f"Moderate earnings gap {gap_pct:+.1f}% — wait for price to settle first 30min",
                "wait_30min — let the initial volatility pass",
                "Below/above opening range low/high",
                "Previous support/resistance levels",
            )
        else:
            return (
                GapStrategy.AVOID,
                f"Small earnings gap {gap_pct:+.1f}% — no clear edge",
                "none",
                "none",
                "none",
            )

    # Non-earnings gap
    if gap_size == "extreme":
        if regime_id in (3, 4):
            return (
                GapStrategy.GAP_AND_GO,
                f"Extreme gap {gap_pct:+.1f}% in trending regime — momentum likely continues",
                f"{'buy' if direction == 'up' else 'sell'} at open if first 5min candle holds gap direction",
                f"Below/above first 5-minute candle {'low' if direction == 'up' else 'high'}",
                "2× the gap size as initial target, then trail",
            )
        else:
            return (
                GapStrategy.GAP_FADE,
                f"Extreme gap {gap_pct:+.1f}% in MR regime — overextended, likely to fade",
                "wait_15min — enter fade if gap starts filling",
                "Beyond the pre-market extreme (if gap expands, you're wrong)",
                "50% gap fill as first target, previous close as second",
            )

    elif gap_size in ("large", "medium"):
        if volume_unusual and regime_id in (3, 4):
            return (
                GapStrategy.GAP_AND_GO,
                f"Gap {gap_pct:+.1f}% with unusual volume in trending regime — institutional move",
                f"{'buy' if direction == 'up' else 'sell'} on first pullback to VWAP after open",
                "Below VWAP (if buying) or above VWAP (if selling)",
                "Gap extension: 1.5× the gap size",
            )
        elif regime_id in (1, 2):
            return (
                GapStrategy.GAP_FADE,
                f"Gap {gap_pct:+.1f}% in mean-reverting regime — expect gap fill",
                "wait_for_reversal_candle — enter when first 15min candle reverses",
                "Beyond pre-market high/low",
                "50-75% gap fill",
            )
        else:
            return (
                GapStrategy.ORB_BREAKOUT,
                f"Gap {gap_pct:+.1f}% — wait for ORB to confirm direction",
                "wait_for_orb — enter on ORB breakout (15-30min range)",
                "Opposite side of opening range",
                "ORB extension targets (T1 = range width, T2 = 2× range width)",
            )

    elif gap_size == "small":
        if volume_unusual:
            return (
                GapStrategy.ORB_BREAKOUT,
                f"Small gap but unusual volume — something brewing. Wait for ORB.",
                "wait_for_orb",
                "Opposite side of opening range",
                "ORB targets",
            )
        else:
            return (
                GapStrategy.AVOID,
                f"Small gap {gap_pct:+.1f}% without volume — no edge",
                "none",
                "none",
                "none",
            )

    return (GapStrategy.WATCH, "Monitor", "wait", "none", "none")


def scan_premarket(
    ticker_data: list[dict],
    regime_id: int = 1,
    min_gap_pct: float = 0.5,
    market: str = "US",
) -> PremarketScanResult:
    """Scan universe for pre-market unusual activity.

    Args:
        ticker_data: List of dicts from yfinance .info:
            {ticker, name, previousClose, preMarketPrice, preMarketVolume,
             averageDailyVolume10Day, sector, marketCap, hasEarnings}
        regime_id: Current market regime (affects strategy selection)
        min_gap_pct: Minimum gap size to report (default 0.5%)
        market: "US" or "INDIA"

    eTrading fetches the data (yf.Ticker(t).info for each ticker),
    MA analyzes and returns opportunities.
    """
    today = date.today()
    alerts: list[PremarketAlert] = []

    for data in ticker_data:
        ticker = data.get("ticker", "")
        prev_close = data.get("previousClose") or data.get("regularMarketPreviousClose", 0)
        premarket = data.get("preMarketPrice") or data.get("regularMarketPrice", 0)

        if not prev_close or not premarket or prev_close <= 0:
            continue

        gap_pct = (premarket - prev_close) / prev_close * 100
        if abs(gap_pct) < min_gap_pct:
            continue

        gap_dir = GapDirection.GAP_UP if gap_pct > 0.5 else GapDirection.GAP_DOWN if gap_pct < -0.5 else GapDirection.FLAT
        gap_size = _classify_gap(gap_pct)

        # Volume
        pm_vol = data.get("preMarketVolume")
        avg_vol = data.get("averageDailyVolume10Day") or data.get("averageVolume", 0)
        vol_ratio = None
        vol_unusual = False
        if pm_vol and avg_vol and avg_vol > 0:
            # Pre-market is ~2 hours of a 6.5 hour day
            expected_pm_vol = avg_vol * (2 / 6.5)
            vol_ratio = pm_vol / expected_pm_vol if expected_pm_vol > 0 else 0
            vol_unusual = vol_ratio > 2.0  # 2× normal pre-market volume

        has_earnings = data.get("hasEarnings", False)
        sector = data.get("sector", "unknown")

        mcap = data.get("marketCap", 0)
        if mcap and mcap > 200e9:
            cap_cat = "mega"
        elif mcap and mcap > 10e9:
            cap_cat = "large"
        elif mcap and mcap > 2e9:
            cap_cat = "mid"
        else:
            cap_cat = "small"

        # Strategy selection
        strategy, rationale, entry, stop, target = _select_strategy(
            gap_pct, gap_size, has_earnings, regime_id, vol_unusual,
        )

        # Risk level
        if abs(gap_pct) > 7:
            risk = "extreme"
        elif abs(gap_pct) > 4:
            risk = "high"
        elif abs(gap_pct) > 2:
            risk = "medium"
        else:
            risk = "low"

        # Commentary
        commentary = [f"{ticker}: {gap_pct:+.1f}% gap {'up' if gap_pct > 0 else 'down'} ({gap_size})"]
        if vol_unusual:
            commentary.append(f"UNUSUAL VOLUME: {vol_ratio:.1f}× normal pre-market volume")
        if has_earnings:
            commentary.append("EARNINGS CATALYST — gap is earnings-driven")
        commentary.append(f"Strategy: {strategy.value} — {rationale}")

        name = data.get("name") or data.get("shortName", ticker)

        alerts.append(PremarketAlert(
            ticker=ticker,
            name=name,
            previous_close=round(prev_close, 2),
            premarket_price=round(premarket, 2),
            gap_pct=round(gap_pct, 2),
            gap_direction=gap_dir,
            gap_size=gap_size,
            premarket_volume=pm_vol,
            avg_daily_volume=avg_vol,
            volume_ratio=round(vol_ratio, 2) if vol_ratio else None,
            volume_unusual=vol_unusual,
            has_earnings=has_earnings,
            sector=sector,
            market_cap_category=cap_cat,
            recommended_strategy=strategy,
            strategy_rationale=rationale,
            entry_approach=entry,
            stop_loss_approach=stop,
            target_approach=target,
            risk_level=risk,
            commentary=commentary,
        ))

    # Sort by absolute gap size (biggest movers first)
    alerts.sort(key=lambda a: abs(a.gap_pct), reverse=True)

    gap_ups = sum(1 for a in alerts if a.gap_direction == GapDirection.GAP_UP)
    gap_downs = sum(1 for a in alerts if a.gap_direction == GapDirection.GAP_DOWN)
    extreme = sum(1 for a in alerts if a.gap_size == "extreme")
    actionable = [a for a in alerts if a.recommended_strategy not in (GapStrategy.AVOID, GapStrategy.WATCH)]

    commentary = [
        f"Pre-market scan: {len(ticker_data)} tickers, {len(alerts)} with significant gaps",
        f"Gap ups: {gap_ups} | Gap downs: {gap_downs} | Extreme (>5%): {extreme}",
        f"Actionable: {len(actionable)} trades",
    ]
    if actionable:
        best = actionable[0]
        commentary.append(f"Top move: {best.ticker} {best.gap_pct:+.1f}% → {best.recommended_strategy.value}")

    return PremarketScanResult(
        as_of_date=today,
        market=market,
        total_scanned=len(ticker_data),
        alerts=alerts,
        gap_ups=gap_ups,
        gap_downs=gap_downs,
        extreme_moves=extreme,
        summary=f"{len(alerts)} gaps ({gap_ups}↑ {gap_downs}↓) | {len(actionable)} actionable | {extreme} extreme",
        commentary=commentary,
    )


def fetch_premarket_data(tickers: list[str]) -> list[dict]:
    """Fetch pre-market data from yfinance for a list of tickers.

    Convenience function for standalone/CLI use.
    eTrading may use its own data feed instead.
    """
    import yfinance as yf

    results = []
    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).info
            results.append({
                "ticker": ticker,
                "name": info.get("shortName", ticker),
                "previousClose": info.get("previousClose") or info.get("regularMarketPreviousClose"),
                "preMarketPrice": info.get("preMarketPrice"),
                "regularMarketPrice": info.get("regularMarketPrice"),
                "preMarketVolume": info.get("preMarketVolume"),
                "averageDailyVolume10Day": info.get("averageDailyVolume10Day"),
                "averageVolume": info.get("averageVolume"),
                "sector": info.get("sector", ""),
                "marketCap": info.get("marketCap"),
                "hasEarnings": False,  # Would need earnings calendar check
            })
        except Exception:
            continue

    return results
