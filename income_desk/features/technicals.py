"""Technical indicator computation from OHLCV DataFrames."""

from __future__ import annotations

import numpy as np
import pandas as pd

from income_desk.config import TechnicalsSettings, get_settings
from income_desk.features.patterns.smart_money import (  # noqa: F401
    compute_fair_value_gaps,
    compute_order_blocks,
    compute_smart_money,
    generate_smart_money_signals as _generate_smart_money_signals,
)
from income_desk.features.patterns.vcp import (  # noqa: F401
    compute_vcp,
    generate_vcp_signals as _generate_vcp_signals,
)
from income_desk.features.patterns.candles import (  # noqa: F401
    compute_candlestick_patterns,
    generate_candlestick_signals as _generate_candlestick_signals,
)
from income_desk.models.technicals import (
    ADXData,
    BollingerBands,
    DonchianChannels,
    FibonacciLevels,
    KeltnerChannels,
    MACDData,
    MarketPhase,
    MovingAverages,
    PhaseIndicator,
    PivotPoints,
    RSIData,
    SignalDirection,
    SignalStrength,
    StochasticData,
    SupportResistance,
    TechnicalSignal,
    TechnicalSnapshot,
    VWAPData,
)


def compute_sma(close: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return close.rolling(window).mean()


def compute_ema(close: pd.Series, span: int) -> pd.Series:
    """Exponential moving average."""
    return close.ewm(span=span, adjust=False).mean()


def compute_rsi(close: pd.Series, period: int) -> pd.Series:
    """RSI using Wilder's smoothing method."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # When avg_loss is 0 (all gains), RSI = 100
    rsi = rsi.fillna(100.0)
    return rsi


def compute_bollinger(
    close: pd.Series, window: int, num_std: float
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands: (upper, middle, lower)."""
    middle = close.rolling(window).mean()
    std = close.rolling(window).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def compute_macd(
    close: pd.Series, fast: int, slow: int, signal: int
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD: (macd_line, signal_line, histogram)."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_vwma(close: pd.Series, volume: pd.Series, window: int) -> pd.Series:
    """Volume-weighted moving average."""
    return (close * volume).rolling(window).sum() / volume.rolling(window).sum()


def compute_atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int
) -> pd.Series:
    """Average True Range."""
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def compute_stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series, k_period: int, d_period: int
) -> tuple[pd.Series, pd.Series]:
    """Stochastic oscillator: (%K, %D)."""
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    denom = highest_high - lowest_low
    k = 100.0 * (close - lowest_low) / denom.replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k, d


def _detect_macd_crossover(
    macd_line: pd.Series, signal_line: pd.Series
) -> tuple[bool, bool]:
    """Detect MACD crossover on the most recent bar.

    Returns (is_bullish_crossover, is_bearish_crossover).
    """
    if len(macd_line) < 2:
        return False, False
    prev_diff = macd_line.iloc[-2] - signal_line.iloc[-2]
    curr_diff = macd_line.iloc[-1] - signal_line.iloc[-1]
    bullish = bool(prev_diff <= 0 and curr_diff > 0)
    bearish = bool(prev_diff >= 0 and curr_diff < 0)
    return bullish, bearish


def _detect_golden_death_cross(
    sma50: pd.Series, sma200: pd.Series
) -> tuple[bool, bool]:
    """Detect golden cross / death cross on most recent bar.

    Returns (is_golden_cross, is_death_cross).
    """
    if len(sma50) < 2:
        return False, False
    prev_diff = sma50.iloc[-2] - sma200.iloc[-2]
    curr_diff = sma50.iloc[-1] - sma200.iloc[-1]
    golden = bool(prev_diff <= 0 and curr_diff > 0)
    death = bool(prev_diff >= 0 and curr_diff < 0)
    return golden, death


def _generate_signals(
    price: float,
    rsi_val: float,
    macd_bullish: bool,
    macd_bearish: bool,
    golden_cross: bool,
    death_cross: bool,
    bb_upper: float,
    bb_lower: float,
    stoch_k: float,
    sma_200: float,
    vwma_val: float,
    settings: TechnicalsSettings,
) -> list[TechnicalSignal]:
    """Generate technical signals from current indicator values."""
    signals: list[TechnicalSignal] = []

    # RSI signals
    if rsi_val < settings.rsi_oversold:
        strength = SignalStrength.STRONG if rsi_val < 20 else SignalStrength.MODERATE
        signals.append(TechnicalSignal(
            name="RSI Oversold",
            direction=SignalDirection.BULLISH,
            strength=strength,
            description=f"RSI at {rsi_val:.1f} — below {settings.rsi_oversold:.0f} oversold threshold",
        ))
    elif rsi_val > settings.rsi_overbought:
        strength = SignalStrength.STRONG if rsi_val > 80 else SignalStrength.MODERATE
        signals.append(TechnicalSignal(
            name="RSI Overbought",
            direction=SignalDirection.BEARISH,
            strength=strength,
            description=f"RSI at {rsi_val:.1f} — above {settings.rsi_overbought:.0f} overbought threshold",
        ))

    # MACD crossover
    if macd_bullish:
        signals.append(TechnicalSignal(
            name="MACD Bullish Crossover",
            direction=SignalDirection.BULLISH,
            strength=SignalStrength.MODERATE,
            description="MACD line crossed above signal line",
        ))
    if macd_bearish:
        signals.append(TechnicalSignal(
            name="MACD Bearish Crossover",
            direction=SignalDirection.BEARISH,
            strength=SignalStrength.MODERATE,
            description="MACD line crossed below signal line",
        ))

    # Golden / Death cross
    if golden_cross:
        signals.append(TechnicalSignal(
            name="Golden Cross",
            direction=SignalDirection.BULLISH,
            strength=SignalStrength.STRONG,
            description="SMA(50) crossed above SMA(200)",
        ))
    if death_cross:
        signals.append(TechnicalSignal(
            name="Death Cross",
            direction=SignalDirection.BEARISH,
            strength=SignalStrength.STRONG,
            description="SMA(50) crossed below SMA(200)",
        ))

    # Bollinger Band signals
    if price < bb_lower:
        signals.append(TechnicalSignal(
            name="Below Lower Bollinger",
            direction=SignalDirection.BULLISH,
            strength=SignalStrength.MODERATE,
            description=f"Price ({price:.2f}) below lower Bollinger Band ({bb_lower:.2f})",
        ))
    elif price > bb_upper:
        signals.append(TechnicalSignal(
            name="Above Upper Bollinger",
            direction=SignalDirection.BEARISH,
            strength=SignalStrength.MODERATE,
            description=f"Price ({price:.2f}) above upper Bollinger Band ({bb_upper:.2f})",
        ))

    # Stochastic signals
    if stoch_k < settings.stochastic_oversold:
        signals.append(TechnicalSignal(
            name="Stochastic Oversold",
            direction=SignalDirection.BULLISH,
            strength=SignalStrength.MODERATE,
            description=f"Stochastic %K at {stoch_k:.1f} — below {settings.stochastic_oversold:.0f}",
        ))
    elif stoch_k > settings.stochastic_overbought:
        signals.append(TechnicalSignal(
            name="Stochastic Overbought",
            direction=SignalDirection.BEARISH,
            strength=SignalStrength.MODERATE,
            description=f"Stochastic %K at {stoch_k:.1f} — above {settings.stochastic_overbought:.0f}",
        ))

    # Trend context: price vs SMA(200)
    if not np.isnan(sma_200):
        if price > sma_200:
            signals.append(TechnicalSignal(
                name="Above 200 SMA",
                direction=SignalDirection.BULLISH,
                strength=SignalStrength.WEAK,
                description=f"Price above 200-day SMA ({sma_200:.2f})",
            ))
        else:
            signals.append(TechnicalSignal(
                name="Below 200 SMA",
                direction=SignalDirection.BEARISH,
                strength=SignalStrength.WEAK,
                description=f"Price below 200-day SMA ({sma_200:.2f})",
            ))

    # Price vs VWMA
    if not np.isnan(vwma_val):
        if price > vwma_val:
            signals.append(TechnicalSignal(
                name="Above VWMA",
                direction=SignalDirection.BULLISH,
                strength=SignalStrength.WEAK,
                description=f"Price above VWMA(20) ({vwma_val:.2f})",
            ))
        else:
            signals.append(TechnicalSignal(
                name="Below VWMA",
                direction=SignalDirection.BEARISH,
                strength=SignalStrength.WEAK,
                description=f"Price below VWMA(20) ({vwma_val:.2f})",
            ))

    return signals


# --- Pattern functions moved to features/patterns/ ---
# compute_vcp -> features.patterns.vcp
# compute_order_blocks, compute_fair_value_gaps, compute_smart_money -> features.patterns.smart_money
# compute_orb -> features.patterns.orb


def _generate_phase_signals(phase: PhaseIndicator) -> list[TechnicalSignal]:
    """Generate TechnicalSignal entries for the detected market phase."""
    signals: list[TechnicalSignal] = []

    if phase.phase == MarketPhase.MARKUP:
        signals.append(TechnicalSignal(
            name="Phase: Markup",
            direction=SignalDirection.BULLISH,
            strength=SignalStrength.STRONG if phase.confidence >= 0.65 else SignalStrength.MODERATE,
            description=phase.description,
        ))
    elif phase.phase == MarketPhase.MARKDOWN:
        signals.append(TechnicalSignal(
            name="Phase: Markdown",
            direction=SignalDirection.BEARISH,
            strength=SignalStrength.STRONG if phase.confidence >= 0.65 else SignalStrength.MODERATE,
            description=phase.description,
        ))
    elif phase.phase == MarketPhase.ACCUMULATION:
        signals.append(TechnicalSignal(
            name="Phase: Accumulation",
            direction=SignalDirection.BULLISH,
            strength=SignalStrength.WEAK,
            description=phase.description,
        ))
    elif phase.phase == MarketPhase.DISTRIBUTION:
        signals.append(TechnicalSignal(
            name="Phase: Distribution",
            direction=SignalDirection.BEARISH,
            strength=SignalStrength.WEAK,
            description=phase.description,
        ))

    return signals


def compute_phase_indicator(
    ohlcv: pd.DataFrame,
    price_vs_sma_50: float,
) -> PhaseIndicator:
    """Classify market phase from price structure alone (no HMM required).

    Uses swing patterns, volume trend, range compression, and price vs SMA
    to determine Accumulation / Markup / Distribution / Markdown.

    This is a lightweight indicator. For regime-aware Wyckoff phase detection,
    use PhaseDetector from phases/detector.py via RegimeService.detect_phase().
    """
    from income_desk.phases.price_structure import compute_price_structure
    from income_desk.config import get_settings

    settings = get_settings().phases
    ps = compute_price_structure(ohlcv, settings)

    # Classification logic (mirrors phases/detector.py fallback paths)
    # Trending: HH+HL = Markup, LH+LL = Markdown
    # Range-bound: HL+compression+declining vol = Accumulation, LH+expansion = Distribution
    # Fallback: price vs SMA

    phase: MarketPhase
    description: str
    confidence = 0.50

    if ps.higher_highs and ps.higher_lows:
        phase = MarketPhase.MARKUP
        description = "Higher highs and higher lows — uptrend in progress."
        confidence = 0.70
        if ps.volume_trend == "rising":
            confidence += 0.10
            description += " Volume confirming."
    elif ps.lower_highs and ps.lower_lows:
        phase = MarketPhase.MARKDOWN
        description = "Lower highs and lower lows — downtrend in progress."
        confidence = 0.70
        if ps.volume_trend == "rising":
            confidence += 0.10
            description += " Panic volume."
    elif ps.higher_lows and not ps.higher_highs:
        # Higher lows without higher highs = base building
        phase = MarketPhase.ACCUMULATION
        description = "Higher lows forming — potential accumulation base."
        confidence = 0.55
        if ps.range_compression > 0.2:
            confidence += 0.10
            description += " Range compressing."
        if ps.volume_trend == "declining":
            confidence += 0.10
            description += " Volume drying up (supply exhaustion)."
    elif ps.lower_highs and not ps.lower_lows:
        # Lower highs without lower lows = topping
        phase = MarketPhase.DISTRIBUTION
        description = "Lower highs forming — potential distribution top."
        confidence = 0.55
        if ps.range_compression < -0.2:
            confidence += 0.05
            description += " Range expanding."
        if ps.volume_trend == "rising":
            confidence += 0.10
            description += " Rising volume on declines."
    else:
        # No clear swing pattern — use price vs SMA + range compression
        if price_vs_sma_50 < -2.0:
            phase = MarketPhase.ACCUMULATION
            description = f"Price {price_vs_sma_50:.1f}% below SMA(50) — possible accumulation."
            confidence = 0.40
        elif price_vs_sma_50 > 2.0:
            if ps.range_compression > 0.2:
                phase = MarketPhase.MARKUP
                description = f"Price {price_vs_sma_50:.1f}% above SMA(50), range tightening."
                confidence = 0.45
            else:
                phase = MarketPhase.DISTRIBUTION
                description = f"Price {price_vs_sma_50:.1f}% above SMA(50) — possible distribution."
                confidence = 0.40
        else:
            # Near SMA — use range compression as tiebreaker
            if ps.range_compression > 0.2:
                phase = MarketPhase.ACCUMULATION
                description = "Range compressing near SMA — possible base building."
                confidence = 0.35
            else:
                phase = MarketPhase.DISTRIBUTION
                description = "No clear directional pattern — consolidation/distribution."
                confidence = 0.30

    confidence = max(0.10, min(0.95, confidence))

    return PhaseIndicator(
        phase=phase,
        confidence=round(confidence, 2),
        description=description,
        higher_highs=ps.higher_highs,
        higher_lows=ps.higher_lows,
        lower_highs=ps.lower_highs,
        lower_lows=ps.lower_lows,
        range_compression=round(ps.range_compression, 3),
        volume_trend=ps.volume_trend,
        price_vs_sma_50_pct=round(price_vs_sma_50, 2),
    )


def compute_fibonacci(
    high: pd.Series, low: pd.Series, close: pd.Series, lookback: int = 60
) -> FibonacciLevels:
    """Compute Fibonacci retracement levels from the most significant swing in lookback period."""
    recent_high = high.tail(lookback)
    recent_low = low.tail(lookback)
    swing_high = float(recent_high.max())
    swing_low = float(recent_low.min())
    swing_high_idx = recent_high.idxmax()
    swing_low_idx = recent_low.idxmin()
    price = float(close.iloc[-1])

    # Direction: if high came after low, it's an upswing (retrace down from high)
    # If low came after high, it's a downswing (retrace up from low)
    diff = swing_high - swing_low
    if swing_high_idx > swing_low_idx:
        direction = "up"  # upswing — fib levels are retracement from high toward low
        level_236 = swing_high - 0.236 * diff
        level_382 = swing_high - 0.382 * diff
        level_500 = swing_high - 0.500 * diff
        level_618 = swing_high - 0.618 * diff
        level_786 = swing_high - 0.786 * diff
    else:
        direction = "down"  # downswing — fib levels are retracement from low toward high
        level_236 = swing_low + 0.236 * diff
        level_382 = swing_low + 0.382 * diff
        level_500 = swing_low + 0.500 * diff
        level_618 = swing_low + 0.618 * diff
        level_786 = swing_low + 0.786 * diff

    # Determine where current price sits relative to fib levels
    if direction == "up":
        # Levels descend from high to low
        if price > level_236:
            current_level = "above_236"
        elif price > level_382:
            current_level = "between_236_382"
        elif price > level_500:
            current_level = "between_382_500"
        elif price > level_618:
            current_level = "between_500_618"
        elif price > level_786:
            current_level = "between_618_786"
        else:
            current_level = "below_786"
    else:
        # Levels ascend from low to high
        if price < level_236:
            current_level = "below_236"
        elif price < level_382:
            current_level = "between_236_382"
        elif price < level_500:
            current_level = "between_382_500"
        elif price < level_618:
            current_level = "between_500_618"
        elif price < level_786:
            current_level = "between_618_786"
        else:
            current_level = "above_786"

    return FibonacciLevels(
        swing_high=swing_high,
        swing_low=swing_low,
        direction=direction,
        level_236=round(level_236, 2),
        level_382=round(level_382, 2),
        level_500=round(level_500, 2),
        level_618=round(level_618, 2),
        level_786=round(level_786, 2),
        current_price_level=current_level,
    )


def compute_adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> ADXData:
    """Average Directional Index with +DI/-DI."""
    # +DM = high - prev_high (if positive and > -DM)
    # -DM = prev_low - low (if positive and > +DM)
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    # True Range
    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)

    # Smoothed (Wilder's)
    atr = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    plus_di_series = (
        100
        * plus_dm.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        / atr
    )
    minus_di_series = (
        100
        * minus_dm.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        / atr
    )

    # DX and ADX
    dx = (
        100
        * (plus_di_series - minus_di_series).abs()
        / (plus_di_series + minus_di_series).replace(0, np.nan)
    )
    adx_series = dx.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    adx_val = (
        float(adx_series.iloc[-1]) if not pd.isna(adx_series.iloc[-1]) else 0.0
    )
    plus_di_val = (
        float(plus_di_series.iloc[-1])
        if not pd.isna(plus_di_series.iloc[-1])
        else 0.0
    )
    minus_di_val = (
        float(minus_di_series.iloc[-1])
        if not pd.isna(minus_di_series.iloc[-1])
        else 0.0
    )

    if plus_di_val > minus_di_val:
        direction = "bullish"
    elif minus_di_val > plus_di_val:
        direction = "bearish"
    else:
        direction = "neutral"

    return ADXData(
        adx=round(adx_val, 2),
        plus_di=round(plus_di_val, 2),
        minus_di=round(minus_di_val, 2),
        is_trending=adx_val > 25,
        is_ranging=adx_val < 20,
        trend_direction=direction,
    )


def compute_donchian(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20
) -> DonchianChannels:
    """Donchian Channels — N-period high/low breakout levels."""
    upper = float(high.rolling(period).max().iloc[-1])
    lower = float(low.rolling(period).min().iloc[-1])
    middle = (upper + lower) / 2
    width_pct = (upper - lower) / middle * 100 if middle > 0 else 0.0
    price = float(close.iloc[-1])
    is_at_upper = price >= upper * 0.995
    is_at_lower = price <= lower * 1.005
    return DonchianChannels(
        upper=round(upper, 2),
        lower=round(lower, 2),
        middle=round(middle, 2),
        width_pct=round(width_pct, 2),
        is_at_upper=is_at_upper,
        is_at_lower=is_at_lower,
    )


def compute_keltner(
    close: pd.Series, high: pd.Series, low: pd.Series,
    ema_period: int = 20, atr_period: int = 14, multiplier: float = 2.0,
    bb_upper: float = 0, bb_lower: float = 0,
) -> KeltnerChannels:
    """Keltner Channels with Bollinger squeeze detection."""
    ema = close.ewm(span=ema_period, adjust=False).mean()
    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(atr_period).mean()

    ema_val = float(ema.iloc[-1])
    atr_val = float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else 0
    upper = ema_val + multiplier * atr_val
    lower = ema_val - multiplier * atr_val
    middle = ema_val
    width_pct = (upper - lower) / middle * 100 if middle > 0 else 0

    # Squeeze: BB inside Keltner = volatility compression about to expand
    squeeze = bb_upper < upper and bb_lower > lower if bb_upper > 0 else False

    return KeltnerChannels(
        upper=round(upper, 2),
        middle=round(middle, 2),
        lower=round(lower, 2),
        width_pct=round(width_pct, 2),
        squeeze=squeeze,
    )


def compute_pivot_points(
    high: pd.Series, low: pd.Series, close: pd.Series,
) -> PivotPoints:
    """Classic pivot points from prior day's H/L/C."""
    # Use the second-to-last bar as "prior period" (last bar is current)
    if len(high) < 2:
        h = float(high.iloc[-1])
        l = float(low.iloc[-1])
        c = float(close.iloc[-1])
    else:
        h = float(high.iloc[-2])
        l = float(low.iloc[-2])
        c = float(close.iloc[-2])

    pp = (h + l + c) / 3
    r1 = 2 * pp - l
    r2 = pp + (h - l)
    r3 = h + 2 * (pp - l)
    s1 = 2 * pp - h
    s2 = pp - (h - l)
    s3 = l - 2 * (h - pp)

    return PivotPoints(
        pp=round(pp, 2),
        r1=round(r1, 2),
        r2=round(r2, 2),
        r3=round(r3, 2),
        s1=round(s1, 2),
        s2=round(s2, 2),
        s3=round(s3, 2),
        period="daily",
    )


def compute_daily_vwap(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series,
    lookback: int = 20,
) -> VWAPData:
    """Rolling VWAP over lookback period (daily bars — not intraday VWAP)."""
    typical_price = (high + low + close) / 3
    cumulative_tp_vol = (typical_price * volume).rolling(lookback).sum()
    cumulative_vol = volume.rolling(lookback).sum()
    vwap_series = cumulative_tp_vol / cumulative_vol.replace(0, np.nan)

    vwap_val = float(vwap_series.iloc[-1]) if not pd.isna(vwap_series.iloc[-1]) else float(close.iloc[-1])
    price = float(close.iloc[-1])
    pct = (price - vwap_val) / vwap_val * 100 if vwap_val > 0 else 0.0

    return VWAPData(
        vwap=round(vwap_val, 2),
        price_vs_vwap_pct=round(pct, 2),
        is_above_vwap=price > vwap_val,
    )


def compute_technicals(
    ohlcv: pd.DataFrame,
    ticker: str,
    settings: TechnicalsSettings | None = None,
) -> TechnicalSnapshot:
    """Compute full technical snapshot from OHLCV DataFrame.

    Args:
        ohlcv: DataFrame with Open, High, Low, Close, Volume and DatetimeIndex.
        ticker: Instrument ticker symbol.
        settings: Optional settings override. Uses global config if None.

    Returns:
        TechnicalSnapshot with all indicators and signals.

    Raises:
        ValueError: If required columns are missing or DataFrame is empty.
    """
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(ohlcv.columns)
    if missing:
        raise ValueError(f"OHLCV DataFrame missing columns: {missing}")
    if ohlcv.empty:
        raise ValueError("OHLCV DataFrame is empty")

    if settings is None:
        settings = get_settings().technicals

    close = ohlcv["Close"]
    high = ohlcv["High"]
    low = ohlcv["Low"]
    volume = ohlcv["Volume"]
    price = float(close.iloc[-1])

    # Moving averages
    sma_20 = compute_sma(close, 20)
    sma_50 = compute_sma(close, 50)
    sma_200 = compute_sma(close, 200)
    ema_9 = compute_ema(close, 9)
    ema_21 = compute_ema(close, 21)

    def _pct_vs(ma: pd.Series) -> float:
        val = ma.iloc[-1]
        if pd.isna(val) or val == 0:
            return 0.0
        return float((price - val) / val * 100)

    ma = MovingAverages(
        sma_20=float(sma_20.iloc[-1]) if not pd.isna(sma_20.iloc[-1]) else 0.0,
        sma_50=float(sma_50.iloc[-1]) if not pd.isna(sma_50.iloc[-1]) else 0.0,
        sma_200=float(sma_200.iloc[-1]) if not pd.isna(sma_200.iloc[-1]) else 0.0,
        ema_9=float(ema_9.iloc[-1]) if not pd.isna(ema_9.iloc[-1]) else 0.0,
        ema_21=float(ema_21.iloc[-1]) if not pd.isna(ema_21.iloc[-1]) else 0.0,
        price_vs_sma_20_pct=_pct_vs(sma_20),
        price_vs_sma_50_pct=_pct_vs(sma_50),
        price_vs_sma_200_pct=_pct_vs(sma_200),
    )

    # RSI
    rsi_series = compute_rsi(close, settings.rsi_period)
    rsi_val = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else 50.0
    rsi = RSIData(
        value=rsi_val,
        is_overbought=rsi_val > settings.rsi_overbought,
        is_oversold=rsi_val < settings.rsi_oversold,
    )

    # Bollinger Bands
    bb_upper, bb_middle, bb_lower = compute_bollinger(
        close, settings.bollinger_window, settings.bollinger_std
    )
    bb_upper_val = float(bb_upper.iloc[-1]) if not pd.isna(bb_upper.iloc[-1]) else price
    bb_middle_val = float(bb_middle.iloc[-1]) if not pd.isna(bb_middle.iloc[-1]) else price
    bb_lower_val = float(bb_lower.iloc[-1]) if not pd.isna(bb_lower.iloc[-1]) else price
    bb_bw = bb_upper_val - bb_lower_val
    bb_range = bb_upper_val - bb_lower_val
    pct_b = (price - bb_lower_val) / bb_range if bb_range != 0 else 0.5
    bollinger = BollingerBands(
        upper=bb_upper_val,
        middle=bb_middle_val,
        lower=bb_lower_val,
        bandwidth=bb_bw / bb_middle_val if bb_middle_val != 0 else 0.0,
        percent_b=pct_b,
    )

    # MACD
    macd_line, signal_line, histogram = compute_macd(
        close, settings.macd_fast, settings.macd_slow, settings.macd_signal
    )
    macd_bullish, macd_bearish = _detect_macd_crossover(macd_line, signal_line)
    macd_data = MACDData(
        macd_line=float(macd_line.iloc[-1]) if not pd.isna(macd_line.iloc[-1]) else 0.0,
        signal_line=float(signal_line.iloc[-1]) if not pd.isna(signal_line.iloc[-1]) else 0.0,
        histogram=float(histogram.iloc[-1]) if not pd.isna(histogram.iloc[-1]) else 0.0,
        is_bullish_crossover=macd_bullish,
        is_bearish_crossover=macd_bearish,
    )

    # Stochastic
    stoch_k, stoch_d = compute_stochastic(
        high, low, close, settings.stochastic_k, settings.stochastic_d
    )
    stoch_k_val = float(stoch_k.iloc[-1]) if not pd.isna(stoch_k.iloc[-1]) else 50.0
    stoch_d_val = float(stoch_d.iloc[-1]) if not pd.isna(stoch_d.iloc[-1]) else 50.0
    stochastic = StochasticData(
        k=stoch_k_val,
        d=stoch_d_val,
        is_overbought=stoch_k_val > settings.stochastic_overbought,
        is_oversold=stoch_k_val < settings.stochastic_oversold,
    )

    # ATR
    atr_series = compute_atr(high, low, close, settings.atr_period)
    atr_val = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else 0.0
    atr_pct = atr_val / price * 100 if price != 0 else 0.0

    # VWMA
    vwma_series = compute_vwma(close, volume, settings.vwma_window)
    vwma_val = float(vwma_series.iloc[-1]) if not pd.isna(vwma_series.iloc[-1]) else price

    # Support / Resistance (reuse swing detection from phases)
    from income_desk.phases.price_structure import detect_swing_highs, detect_swing_lows
    from income_desk.config import PhaseSettings

    phase_settings = get_settings().phases
    swing_highs = detect_swing_highs(high, phase_settings.swing_lookback, phase_settings.swing_threshold_pct)
    swing_lows = detect_swing_lows(low, phase_settings.swing_lookback, phase_settings.swing_threshold_pct)

    # Support = nearest swing low BELOW current price (search backward)
    support_price = next(
        (s.price for s in reversed(swing_lows) if s.price < price), None
    )
    # Resistance = nearest swing high ABOVE current price (search backward)
    resistance_price = next(
        (s.price for s in reversed(swing_highs) if s.price > price), None
    )

    sr = SupportResistance(
        support=support_price,
        resistance=resistance_price,
        price_vs_support_pct=(
            (price - support_price) / support_price * 100
            if support_price is not None and support_price != 0
            else None
        ),
        price_vs_resistance_pct=(
            (price - resistance_price) / resistance_price * 100
            if resistance_price is not None and resistance_price != 0
            else None
        ),
    )

    # Golden/Death cross
    golden_cross, death_cross = _detect_golden_death_cross(sma_50, sma_200)

    # Generate signals
    sma_200_val = float(sma_200.iloc[-1]) if not pd.isna(sma_200.iloc[-1]) else float("nan")
    signals = _generate_signals(
        price=price,
        rsi_val=rsi_val,
        macd_bullish=macd_bullish,
        macd_bearish=macd_bearish,
        golden_cross=golden_cross,
        death_cross=death_cross,
        bb_upper=bb_upper_val,
        bb_lower=bb_lower_val,
        stoch_k=stoch_k_val,
        sma_200=sma_200_val,
        vwma_val=vwma_val,
        settings=settings,
    )

    # VCP detection (from features.patterns.vcp)
    sma_50_val = float(sma_50.iloc[-1]) if not pd.isna(sma_50.iloc[-1]) else float("nan")
    vcp = compute_vcp(ohlcv, price, sma_50_val, sma_200_val, volume, settings)
    signals.extend(_generate_vcp_signals(vcp))

    # Phase indicator (price-structure-only, no HMM required)
    phase_indicator = compute_phase_indicator(ohlcv, _pct_vs(sma_50))

    # Phase signal
    signals.extend(_generate_phase_signals(phase_indicator))

    # Smart Money Concepts (from features.patterns.smart_money)
    smart_money = compute_smart_money(ohlcv, price, atr_series, settings)
    signals.extend(_generate_smart_money_signals(smart_money))

    # Candlestick patterns (from features.patterns.candles)
    candle_summary = compute_candlestick_patterns(ohlcv, settings)
    signals.extend(_generate_candlestick_signals(candle_summary))

    # Fibonacci retracement levels
    fibonacci = compute_fibonacci(high, low, close)

    # ADX (Average Directional Index)
    adx_data = compute_adx(high, low, close)

    # Donchian Channels
    donchian = compute_donchian(high, low, close)

    # Keltner Channels (uses BB values for squeeze detection)
    keltner = compute_keltner(close, high, low, bb_upper=bb_upper_val, bb_lower=bb_lower_val)

    # Pivot Points (classic floor trader pivots from prior day)
    pivot_data = compute_pivot_points(high, low, close)

    # Daily VWAP (rolling volume-weighted average price)
    vwap_data = compute_daily_vwap(high, low, close, volume)

    as_of = ohlcv.index[-1]
    as_of_date = as_of.date() if hasattr(as_of, "date") else as_of

    return TechnicalSnapshot(
        ticker=ticker,
        as_of_date=as_of_date,
        current_price=price,
        atr=atr_val,
        atr_pct=atr_pct,
        vwma_20=vwma_val,
        moving_averages=ma,
        rsi=rsi,
        bollinger=bollinger,
        macd=macd_data,
        stochastic=stochastic,
        support_resistance=sr,
        phase=phase_indicator,
        vcp=vcp,
        smart_money=smart_money,
        candlestick_patterns=candle_summary,
        fibonacci=fibonacci,
        adx=adx_data,
        donchian=donchian,
        keltner=keltner,
        pivot_points=pivot_data,
        daily_vwap=vwap_data,
        signals=signals,
    )
