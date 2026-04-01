# Chain-First Trading Pipeline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trade specs only contain strikes and expiries that exist in the broker chain with real bid/ask. No guessing.

**Architecture:** Invert the current flow. Today: assessor picks strikes from ATR → pricing service tries to find them → often fails. New: fetch chain first → pass available strikes to assessor → assessor picks from what exists.

**Tech Stack:** Python, Dhan broker API, existing income_desk models

---

## Current Problem

The trade pipeline has a fundamental design flaw:

```
TODAY (broken):
  Assessor → picks strikes from ATR math (no chain) → builds TradeSpec
  PricingService → tries to match in broker chain → "Missing strikes" / snaps to wrong strike
  
CORRECT:
  Broker → fetch chain (strikes, expiries, bid/ask, OI) → pass to assessor
  Assessor → picks ONLY from available strikes → builds TradeSpec with real data
  PricingService → just looks up what's already validated → always succeeds
```

## What This Fixes

1. "Missing strikes in liquid chain" — eliminated (only available strikes used)
2. Strike snapping to wrong strike — eliminated (no snapping needed)
3. Lot size mismatch — eliminated (lot_size from chain, not registry)
4. Entry credit mismatch — eliminated (credit computed from chain bid/ask at selection time)
5. Wing width wrong — eliminated (computed from actual strikes chosen)
6. Non-existent expiries — eliminated (expiry from chain)

## File Structure

```
income_desk/
  models/
    chain.py                    # NEW: ChainContext model (available strikes, expiry, lot_size)
  opportunity/
    option_plays/
      _chain_context.py         # NEW: Build ChainContext from broker chain
      _trade_spec_helpers.py    # MODIFY: Accept ChainContext, pick from available strikes
      iron_condor.py            # MODIFY: Pass ChainContext to _compute_trade_spec
      iron_butterfly.py         # MODIFY: Same
      credit_spread.py          # MODIFY: Same (if exists, or within IC assessor)
      ratio_spread.py           # MODIFY: Same
  service/
    ranking.py                  # MODIFY: Fetch chain per ticker, pass to assessors
  workflow/
    pricing_service.py          # MODIFY: Exact match only (no snapping), use chain lot_size
    rank_opportunities.py       # MODIFY: Use lot_size from chain, not registry
```

---

### Task 1: ChainContext Model

**Files:**
- Create: `income_desk/models/chain.py`
- Test: `tests/test_chain_context.py`

- [ ] **Step 1: Write the model**

```python
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
        """Find put strike nearest to target price."""
        if not self.put_strikes:
            return None
        return min(self.put_strikes, key=lambda s: abs(s.strike - target))

    def nearest_call(self, target: float) -> AvailableStrike | None:
        """Find call strike nearest to target price."""
        if not self.call_strikes:
            return None
        return min(self.call_strikes, key=lambda s: abs(s.strike - target))

    def puts_between(self, low: float, high: float) -> list[AvailableStrike]:
        """Put strikes in range [low, high]."""
        return [s for s in self.put_strikes if low <= s.strike <= high]

    def calls_between(self, low: float, high: float) -> list[AvailableStrike]:
        """Call strikes in range [low, high]."""
        return [s for s in self.call_strikes if low <= s.strike <= high]
```

- [ ] **Step 2: Write test**

```python
def test_chain_context_nearest():
    ctx = ChainContext(ticker="RELIANCE", expiration=date(2026, 4, 28), lot_size=250,
                       underlying_price=1370,
                       put_strikes=[AvailableStrike(strike=1340, option_type="put", bid=24, ask=25, mid=24.5),
                                    AvailableStrike(strike=1350, option_type="put", bid=27, ask=28, mid=27.5)],
                       call_strikes=[])
    assert ctx.nearest_put(1345).strike == 1340  # nearer to 1340
    assert ctx.nearest_put(1346).strike == 1350  # nearer to 1350
```

- [ ] **Step 3: Run test, verify pass**
- [ ] **Step 4: Commit**

---

### Task 2: Build ChainContext from Dhan

**Files:**
- Create: `income_desk/opportunity/option_plays/_chain_context.py`
- Test: `tests/test_chain_context_builder.py`

- [ ] **Step 1: Write builder**

```python
"""Build ChainContext from broker option chain."""
from __future__ import annotations
from income_desk.models.chain import AvailableStrike, ChainContext

MIN_OI = 50  # Minimum open interest to consider a strike liquid


def build_chain_context(
    ticker: str,
    chain: list,  # list[OptionQuote] from broker
    underlying_price: float,
) -> ChainContext | None:
    """Build ChainContext from broker chain, filtering to liquid strikes only.
    
    Returns None if chain is empty or has no liquid strikes.
    """
    if not chain:
        return None

    # Get expiration and lot_size from first quote
    expiration = chain[0].expiration
    lot_size = chain[0].lot_size or 1

    put_strikes = []
    call_strikes = []

    for q in chain:
        # Skip strikes with no market
        if not q.bid or q.bid <= 0 or not q.ask or q.ask <= 0:
            continue
        # Skip illiquid strikes
        if q.open_interest is not None and q.open_interest < MIN_OI:
            continue

        strike = AvailableStrike(
            strike=q.strike,
            option_type=q.option_type,
            bid=q.bid,
            ask=q.ask,
            mid=(q.bid + q.ask) / 2,
            iv=q.implied_volatility,
            delta=q.delta,
            open_interest=q.open_interest or 0,
            volume=q.volume or 0,
        )

        if q.option_type == "put":
            put_strikes.append(strike)
        else:
            call_strikes.append(strike)

    if not put_strikes and not call_strikes:
        return None

    put_strikes.sort(key=lambda s: s.strike)
    call_strikes.sort(key=lambda s: s.strike)

    return ChainContext(
        ticker=ticker,
        expiration=expiration,
        lot_size=lot_size,
        underlying_price=underlying_price,
        put_strikes=put_strikes,
        call_strikes=call_strikes,
    )
```

- [ ] **Step 2: Write test with mock chain data**
- [ ] **Step 3: Run test, verify pass**
- [ ] **Step 4: Commit**

---

### Task 3: Modify _trade_spec_helpers to Use ChainContext

**Files:**
- Modify: `income_desk/opportunity/option_plays/_trade_spec_helpers.py`
- Test: `tests/test_trade_spec_chain.py`

The key change: `build_iron_condor_legs()` and similar functions accept a `ChainContext` and pick strikes from what's available instead of computing from ATR.

- [ ] **Step 1: Add chain-aware strike picker**

New function `pick_ic_strikes_from_chain(chain: ChainContext, regime_id: int, atr: float)` that:
- Computes target short strike distance from ATR (same logic as today)
- Finds nearest AVAILABLE put/call strikes to those targets
- Picks long strikes as the next available strike beyond the short
- Returns actual strikes with their bid/ask/IV/delta
- Returns None if not enough liquid strikes exist

- [ ] **Step 2: Add chain-aware `build_trade_spec_from_chain()`**

New function that builds a TradeSpec using only chain-validated strikes. Sets:
- `lot_size` from chain (not registry)
- `wing_width_points` from actual strike gaps
- `currency`, `settlement`, `exercise_style` from registry
- `atm_iv_at_expiry` from chain IV on each leg

- [ ] **Step 3: Write tests with mock ChainContext**
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 4: Modify Assessors to Use ChainContext

**Files:**
- Modify: `income_desk/opportunity/option_plays/iron_condor.py`
- Modify: `income_desk/opportunity/option_plays/iron_butterfly.py`
- Modify: `income_desk/opportunity/option_plays/ratio_spread.py`
- Modify: `income_desk/opportunity/option_plays/credit_spread.py` (if separate)

- [ ] **Step 1: Add `chain: ChainContext | None = None` parameter to each assess function**

- [ ] **Step 2: In `_compute_trade_spec()`, prefer chain when available**

```python
def _compute_trade_spec(ticker, technicals, regime, vol_surface, chain=None):
    if chain is not None:
        return build_trade_spec_from_chain(chain, regime, technicals)
    # Existing ATR-based fallback (for simulated/offline mode)
    return build_single_expiry_trade_spec(...)
```

- [ ] **Step 3: Pass chain through from assess function to _compute_trade_spec**
- [ ] **Step 4: Run existing tests, verify no regression**
- [ ] **Step 5: Commit**

---

### Task 5: Modify Ranking Service to Fetch Chain Per Ticker

**Files:**
- Modify: `income_desk/service/ranking.py`

- [ ] **Step 1: Before the per-ticker assessment loop, fetch chain**

```python
# In the per-ticker loop:
chain_ctx = None
if self.market_data is not None:
    try:
        raw_chain = self.market_data.get_option_chain(ticker)
        price = self.market_data.get_underlying_price(ticker)
        if raw_chain and price:
            chain_ctx = build_chain_context(ticker, raw_chain, price)
    except Exception:
        pass

# Pass to each assessor:
result = assess_fn(ticker, chain=chain_ctx, **kwargs)
```

- [ ] **Step 2: Run existing tests**
- [ ] **Step 3: Commit**

---

### Task 6: Simplify PricingService — Exact Match Only

**Files:**
- Modify: `income_desk/workflow/pricing_service.py`

Since trade specs now only contain chain-validated strikes, the pricing service should:
- Remove strike snapping logic (no longer needed)
- Use exact match only — if a strike doesn't match, it's a bug
- Use lot_size from chain (already on the trade_spec)
- Compute entry_credit as sell_at_bid - buy_at_ask (not mid)

- [ ] **Step 1: Remove snapping, change credit to bid/ask**
- [ ] **Step 2: Run tests**
- [ ] **Step 3: Commit**

---

### Task 7: Integrate Dhan margin_calculator

**Files:**
- Modify: `income_desk/broker/dhan/account.py`
- Test: `tests/test_broker_dhan.py`

Dhan has `margin_calculator(security_id, exchange_segment, transaction_type, quantity, product_type, price)`. Wire it so the trader shows real margin.

- [ ] **Step 1: Add `get_margin_estimate(ticker, legs)` method to DhanAccount**
- [ ] **Step 2: Call it from trader.py for each GO trade**
- [ ] **Step 3: Show actual margin in trade summary table**
- [ ] **Step 4: Commit**

---

### Task 8: Fix Account NLV=0

**Files:**
- Modify: `income_desk/broker/dhan/account.py`

- [ ] **Step 1: Add debug logging to get_fund_limits response**
- [ ] **Step 2: Test with live Dhan connection, print raw response**
- [ ] **Step 3: Fix parsing if needed**
- [ ] **Step 4: Commit**

---

### Task 9: End-to-End Verification

**Files:**
- Modify: `scripts/trace_reliance.py`

- [ ] **Step 1: Run trader against live India market**
- [ ] **Step 2: For each GO trade, hand-verify every number from the leg quotes**
- [ ] **Step 3: Confirm: no strike exists outside broker chain, no hardcoded lot_size/margin, all credit from bid/ask**
- [ ] **Step 4: Document results**

---

## Execution Order

Tasks 1-3 are foundational (model, builder, helpers). Task 4 wires it into assessors. Task 5 connects it to the ranking service. Task 6 simplifies pricing. Tasks 7-8 are independent fixes. Task 9 is verification.

Dependencies: 1 → 2 → 3 → 4 → 5 → 6 → 9. Tasks 7 and 8 can run in parallel with anything.
