"""Portfolio Health — crash sentinel, regime distribution, risk budget."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel
from income_desk.workflow._types import TickerRegime, WorkflowMeta

class HealthRequest(BaseModel):
    tickers: list[str]
    capital: float = 5_000_000
    total_risk_deployed: float = 0.0
    market: str = "India"

class HealthResponse(BaseModel):
    meta: WorkflowMeta
    sentinel_signal: str  # GREEN/YELLOW/ORANGE/RED/BLUE
    regime_distribution: dict[str, int]  # {R1: 2, R2: 1, R4: 3}
    regimes: dict[str, TickerRegime]
    risk_pct: float
    risk_budget_remaining: float
    data_trust: str
    is_safe_to_trade: bool

def check_portfolio_health(request: HealthRequest, ma: "object") -> HealthResponse:
    """Check portfolio-level health: sentinel, regimes, risk."""
    from income_desk.features.crash_sentinel import assess_crash_sentinel
    from income_desk.features.data_trust import compute_trust_report

    timestamp = datetime.now()
    warnings = []
    _LABELS = {1: "R1 Low-Vol MR", 2: "R2 High-Vol MR", 3: "R3 Low-Vol Trend", 4: "R4 High-Vol Trend"}

    regimes = {}
    regime_counts = {"R1": 0, "R2": 0, "R3": 0, "R4": 0}
    regime_results = {}
    iv_ranks = {}

    for ticker in request.tickers:
        try:
            r = ma.regime.detect(ticker)
            rid = r.regime if isinstance(r.regime, int) else r.regime.value
            regimes[ticker] = TickerRegime(
                ticker=ticker, regime_id=rid, regime_label=_LABELS.get(rid, f"R{rid}"),
                confidence=r.confidence, tradeable=rid in (1, 2, 3),
            )
            regime_counts[f"R{rid}"] = regime_counts.get(f"R{rid}", 0) + 1
            regime_results[ticker] = {"regime_id": rid, "confidence": r.confidence, "r4_prob": 0.05}
            iv_ranks[ticker] = 50.0
        except Exception as e:
            warnings.append(f"{ticker}: {e}")

    sentinel = assess_crash_sentinel(regime_results=regime_results, iv_ranks=iv_ranks)
    signal = str(sentinel.signal.value).upper() if hasattr(sentinel.signal, 'value') else str(sentinel.signal).upper()

    has_broker = ma.market_data is not None
    trust = compute_trust_report(
        mode="standalone", has_broker=has_broker, has_iv_rank=has_broker,
        has_vol_surface=False, entry_credit_source="broker" if has_broker else "estimate",
        regime_confidence=0.9,
    )
    trust_str = f"{trust.overall_level} ({trust.data_quality.trust_score:.0%})" if hasattr(trust, 'data_quality') else "unknown"

    risk_pct = request.total_risk_deployed / request.capital if request.capital > 0 else 0
    safe = signal in ("GREEN", "YELLOW") and risk_pct < 0.30

    return HealthResponse(
        meta=WorkflowMeta(as_of=timestamp, market=request.market, data_source="calculation", warnings=warnings),
        sentinel_signal=signal, regime_distribution=regime_counts,
        regimes=regimes, risk_pct=risk_pct,
        risk_budget_remaining=request.capital * 0.30 - request.total_risk_deployed,
        data_trust=trust_str, is_safe_to_trade=safe,
    )
