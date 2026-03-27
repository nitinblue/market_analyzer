"""Shared types for workflow APIs."""
from __future__ import annotations
from datetime import date, datetime
from pydantic import BaseModel


class WorkflowMeta(BaseModel):
    """Metadata attached to every workflow response."""
    as_of: datetime
    market: str
    data_source: str  # "dhan", "simulated", "yfinance"
    warnings: list[str] = []


class TickerRegime(BaseModel):
    """Regime state for one ticker."""
    ticker: str
    regime_id: int  # 1-4
    regime_label: str  # "R1 Low-Vol MR", etc.
    confidence: float
    tradeable: bool  # False for R4


class TradeProposal(BaseModel):
    """A scored, sized trade recommendation."""
    rank: int
    ticker: str
    structure: str  # "iron_condor", "credit_spread", etc.
    direction: str  # "neutral", "bullish", "bearish"
    strategy_badge: str  # "IC neutral · defined"
    composite_score: float
    verdict: str  # "go", "caution", "no_go"
    pop_pct: float | None = None
    expected_value: float | None = None
    contracts: int | None = None
    max_risk: float | None = None
    max_profit: float | None = None
    entry_credit: float | None = None
    wing_width: float | None = None
    target_dte: int | None = None
    lot_size: int | None = None
    currency: str = "USD"
    rationale: str = ""
    data_gaps: list[str] = []


class BlockedTrade(BaseModel):
    """A trade that was rejected and why."""
    ticker: str
    structure: str = ""
    reason: str
    score: float = 0.0


class OpenPosition(BaseModel):
    """Input model for position monitoring workflows."""
    trade_id: str
    ticker: str
    structure_type: str  # "iron_condor", "credit_spread", etc.
    order_side: str  # "credit" or "debit"
    entry_price: float
    current_mid_price: float | None = None
    contracts: int = 1
    dte_remaining: int = 30
    regime_id: int = 1
    lot_size: int = 100
    profit_target_pct: float = 0.50
    stop_loss_pct: float = 2.0
    exit_dte: int = 5
    position_status: str = "safe"  # "safe", "tested", "breached"


class PositionStatus(BaseModel):
    """Output model for position monitoring."""
    trade_id: str
    ticker: str
    action: str  # "hold", "close", "adjust", "close_and_redeploy"
    urgency: str  # "low", "medium", "high", "critical"
    pnl: float = 0.0
    pnl_pct: float = 0.0
    days_held: int = 0
    profit_target: str = ""
    stop_level: str = ""
    theta_recommendation: str = ""
    rationale: str = ""


class TickerSnapshot(BaseModel):
    """Market data snapshot for one ticker."""
    ticker: str
    price: float | None = None
    regime_id: int | None = None
    regime_label: str = ""
    regime_confidence: float = 0.0
    iv_30d: float | None = None
    iv_rank: float | None = None
    atr_pct: float | None = None
    rsi: float | None = None
    chain_strikes: int = 0
    chain_liquid: int = 0
    has_greeks: bool = False
    has_iv: bool = False
