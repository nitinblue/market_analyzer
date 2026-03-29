from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Gate:
    expression: str          # 'pulse != "RED"'
    on_fail: str             # "HALT", "SKIP", "BLOCK", "ALERT", "WARN"
    message: str = ""        # "Market pulse {pulse} — trading halted"


@dataclass
class Step:
    name: str                # "Market Pulse"
    workflow: str            # "check_portfolio_health"
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    gates: list[Gate] = field(default_factory=list)
    requires: str | None = None
    on_simulated: str | None = None


@dataclass
class Phase:
    name: str                # "Market Assessment"
    number: int
    steps: list[Step] = field(default_factory=list)
    requires_positions: bool = False


@dataclass
class BrokerProfile:
    name: str                # "tastytrade_live"
    broker_type: str         # "tastytrade", "dhan", "simulated"
    mode: str = "live"
    market: str = "US"
    currency: str = "USD"
    credentials_source: str = ".env.trading"
    fallback: str = "simulated"


@dataclass
class UniverseSpec:
    name: str
    market: str = "US"
    description: str = ""
    tickers: list[str] = field(default_factory=list)


@dataclass
class RiskProfile:
    name: str
    max_risk_per_trade_pct: float = 3.0
    max_portfolio_risk_pct: float = 30.0
    max_positions: int = 8
    min_pop: float = 0.50
    min_dte: int = 7
    max_dte: int = 45
    min_iv_rank: float = 20.0
    max_spread_pct: float = 0.05
    profit_target_pct: float = 0.50
    stop_loss_pct: float = 2.0
    exit_dte: int = 5
    regime_rules: dict[str, bool] = field(default_factory=lambda: {
        "r1": True, "r2": True, "r3": False, "r4": False,
    })


@dataclass
class WorkflowPlan:
    name: str
    description: str = ""
    broker_ref: str = "simulated"
    universe_ref: str = ""
    risk_ref: str = "moderate"
    phases: list[Phase] = field(default_factory=list)
    # Resolved at runtime by resolve_references()
    broker: BrokerProfile | None = None
    universe: UniverseSpec | None = None
    risk: RiskProfile | None = None
