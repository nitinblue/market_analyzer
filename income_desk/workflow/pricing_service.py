"""PricingService — single source of truth for option trade repricing.

Fetches chain ONCE per ticker. Reprices all structures. Returns immutable result.
No downstream code should overwrite entry_credit after this.
"""

from pydantic import BaseModel


class LegDetail(BaseModel):
    """Per-leg pricing from the broker chain."""

    strike: float
    option_type: str  # "call" | "put"
    action: str  # "sell" | "buy"
    bid: float
    ask: float
    mid: float
    iv: float | None = None
    delta: float | None = None
    open_interest: int = 0
    volume: int = 0


class RepricedTrade(BaseModel):
    """Immutable repricing result. Created once, never modified.

    This is the single source of truth for entry_credit.
    No downstream code may overwrite it.
    """

    model_config = {"frozen": True}

    ticker: str
    structure: str
    entry_credit: float  # Net credit (positive) or debit (negative)
    credit_source: str  # "chain" | "estimated" | "blocked"
    wing_width: float
    lot_size: int
    current_price: float
    atr_pct: float
    regime_id: int
    expiry: str | None = None
    legs_found: bool  # All legs matched in liquid chain
    liquidity_ok: bool  # OI and spread checks passed
    block_reason: str | None = None
    leg_details: list[LegDetail] = []
