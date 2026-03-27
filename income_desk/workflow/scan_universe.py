"""Scan Universe — screen tickers against regime + technical filters."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel
from income_desk.workflow._types import TickerRegime, WorkflowMeta

class ScanRequest(BaseModel):
    tickers: list[str]
    market: str = "India"
    min_score: float = 0.3
    top_n: int = 20

class ScanCandidate(BaseModel):
    ticker: str
    score: float
    screen: str  # "income", "breakout", "momentum", "mean_reversion"
    regime_id: int
    regime_label: str
    rationale: str = ""

class ScanResponse(BaseModel):
    meta: WorkflowMeta
    candidates: list[ScanCandidate]
    regimes: dict[str, TickerRegime]
    total_scanned: int
    total_passed: int

def scan_universe(request: ScanRequest, ma: "object") -> ScanResponse:
    """Screen tickers for trading candidates."""
    timestamp = datetime.now()
    _LABELS = {1: "R1 Low-Vol MR", 2: "R2 High-Vol MR", 3: "R3 Low-Vol Trend", 4: "R4 High-Vol Trend"}
    warnings = []

    regimes = {}
    for ticker in request.tickers:
        try:
            r = ma.regime.detect(ticker)
            rid = r.regime if isinstance(r.regime, int) else r.regime.value
            regimes[ticker] = TickerRegime(
                ticker=ticker, regime_id=rid, regime_label=_LABELS.get(rid, f"R{rid}"),
                confidence=r.confidence, tradeable=rid in (1, 2, 3),
            )
        except Exception as e:
            warnings.append(f"{ticker}: regime detection failed: {e}")

    tradeable = [t for t, r in regimes.items() if r.tradeable]
    candidates = []

    if tradeable:
        try:
            result = ma.screening.scan(tradeable, min_score=request.min_score, top_n=request.top_n)
            for c in result.candidates:
                rid = regimes.get(c.ticker, TickerRegime(ticker=c.ticker, regime_id=0, regime_label="?", confidence=0, tradeable=True)).regime_id
                candidates.append(ScanCandidate(
                    ticker=c.ticker, score=c.score, screen=c.screen if hasattr(c, 'screen') else "unknown",
                    regime_id=rid, regime_label=_LABELS.get(rid, f"R{rid}"),
                    rationale=c.reason if hasattr(c, 'reason') else "",
                ))
        except Exception as e:
            warnings.append(f"Screening failed: {e}")

    return ScanResponse(
        meta=WorkflowMeta(as_of=timestamp, market=request.market, data_source="yfinance", warnings=warnings),
        candidates=candidates, regimes=regimes,
        total_scanned=len(request.tickers), total_passed=len(candidates),
    )
