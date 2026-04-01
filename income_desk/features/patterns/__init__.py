"""Price structure pattern detection — VCP, Order Blocks, FVGs, ORB.

Consolidated pattern computation functions extracted from technicals.py and orb.py.
All functions are pure — they accept DataFrames/series and return model instances.
"""

from income_desk.features.patterns.vcp import compute_vcp
from income_desk.features.patterns.smart_money import (
    compute_fair_value_gaps,
    compute_order_blocks,
    compute_smart_money,
)
from income_desk.features.patterns.orb import compute_orb
from income_desk.features.patterns.candles import (
    compute_candlestick_patterns,
    detect_candlestick_patterns,
    score_candlestick_patterns,
    generate_candlestick_signals,
)

__all__ = [
    "compute_vcp",
    "compute_order_blocks",
    "compute_fair_value_gaps",
    "compute_smart_money",
    "compute_orb",
    "compute_candlestick_patterns",
    "detect_candlestick_patterns",
    "score_candlestick_patterns",
    "generate_candlestick_signals",
]
