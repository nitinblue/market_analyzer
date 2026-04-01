"""Chain context — available strikes, expiries, lot size from broker."""
from __future__ import annotations
from datetime import date
from pydantic import BaseModel


class AvailableStrike(BaseModel):
    """A strike that exists in the broker chain with real quotes."""
    strike: float
    option_type: str  # "put" or "call"
    bid: float
    ask: float
    mid: float
    iv: float | None = None
    delta: float | None = None
    open_interest: int = 0
    volume: int = 0


class ChainContext(BaseModel):
    """Everything the assessor needs to pick strikes from what actually exists."""
    ticker: str
    expiration: date
    lot_size: int
    underlying_price: float
    put_strikes: list[AvailableStrike]   # sorted by strike ascending, bid > 0
    call_strikes: list[AvailableStrike]  # sorted by strike ascending, bid > 0

    def nearest_put(self, target: float) -> AvailableStrike | None:
        if not self.put_strikes:
            return None
        return min(self.put_strikes, key=lambda s: abs(s.strike - target))

    def nearest_call(self, target: float) -> AvailableStrike | None:
        if not self.call_strikes:
            return None
        return min(self.call_strikes, key=lambda s: abs(s.strike - target))

    def puts_between(self, low: float, high: float) -> list[AvailableStrike]:
        return [s for s in self.put_strikes if low <= s.strike <= high]

    def calls_between(self, low: float, high: float) -> list[AvailableStrike]:
        return [s for s in self.call_strikes if low <= s.strike <= high]

    def put_below(self, target: float, n: int = 1) -> list[AvailableStrike]:
        """Return n put strikes below target, sorted descending (nearest first)."""
        below = [s for s in self.put_strikes if s.strike < target]
        return sorted(below, key=lambda s: s.strike, reverse=True)[:n]

    def call_above(self, target: float, n: int = 1) -> list[AvailableStrike]:
        """Return n call strikes above target, sorted ascending (nearest first)."""
        above = [s for s in self.call_strikes if s.strike > target]
        return sorted(above, key=lambda s: s.strike)[:n]
