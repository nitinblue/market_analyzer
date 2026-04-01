"""Price Trade — get live quotes and compute entry price for a TradeSpec."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel
from income_desk.workflow._types import WorkflowMeta

class PriceRequest(BaseModel):
    ticker: str
    legs: list[dict]  # [{strike, option_type, action, expiration}]
    market: str = "India"

class LegQuote(BaseModel):
    strike: float
    option_type: str
    action: str
    bid: float = 0.0
    ask: float = 0.0
    mid: float = 0.0
    iv: float | None = None
    delta: float | None = None

class PriceResponse(BaseModel):
    meta: WorkflowMeta
    ticker: str
    underlying_price: float | None = None
    leg_quotes: list[LegQuote]
    net_credit: float  # positive = credit received
    net_debit: float   # positive = debit paid
    max_entry_price: float | None = None
    avg_spread_pct: float = 0.0
    fill_quality: str = "unknown"  # "tight", "acceptable", "wide"

def price_trade(request: PriceRequest, ma: "object") -> PriceResponse:
    """Get live quotes for trade legs and compute entry price."""
    timestamp = datetime.now()
    warnings = []
    leg_quotes = []
    net_credit = 0.0
    net_debit = 0.0
    spreads = []

    underlying_price = None
    if ma.market_data is not None:
        try:
            underlying_price = ma.market_data.get_underlying_price(request.ticker)
        except Exception:
            pass

    if ma.market_data is not None:
        try:
            chain = ma.market_data.get_option_chain(request.ticker)
            for leg in request.legs:
                strike = leg.get("strike", 0)
                opt_type = leg.get("option_type", "call")
                action = leg.get("action", "BTO")

                matched = None
                for q in chain:
                    if q.strike == strike and q.option_type == opt_type:
                        matched = q
                        break

                if matched:
                    bid = getattr(matched, 'bid', 0) or 0
                    ask = getattr(matched, 'ask', 0) or 0
                    mid = (bid + ask) / 2 if (bid + ask) > 0 else 0

                    lq = LegQuote(
                        strike=strike, option_type=opt_type, action=action,
                        bid=bid, ask=ask, mid=mid,
                        iv=getattr(matched, 'implied_volatility', None),
                        delta=getattr(matched, 'delta', None),
                    )
                    leg_quotes.append(lq)

                    if action in ("STO", "sell"):
                        net_credit += bid  # sell at bid (what you actually receive)
                    else:
                        net_debit += ask  # buy at ask (what you actually pay)

                    if mid > 0:
                        spreads.append((ask - bid) / mid)
                else:
                    leg_quotes.append(LegQuote(strike=strike, option_type=opt_type, action=action))
                    warnings.append(f"No quote for {request.ticker} {strike} {opt_type}")
        except Exception as e:
            warnings.append(f"Chain fetch failed: {e}")

    avg_spread = sum(spreads) / len(spreads) if spreads else 0
    fill_quality = "tight" if avg_spread < 0.02 else "acceptable" if avg_spread < 0.05 else "wide"
    net = net_credit - net_debit
    max_entry = round(abs(net) * 0.80, 2) if net != 0 else None

    return PriceResponse(
        meta=WorkflowMeta(as_of=timestamp, market=request.market, data_source="broker", warnings=warnings),
        ticker=request.ticker, underlying_price=underlying_price,
        leg_quotes=leg_quotes, net_credit=round(net, 2), net_debit=round(max(-net, 0), 2),
        max_entry_price=max_entry, avg_spread_pct=round(avg_spread, 4), fill_quality=fill_quality,
    )
