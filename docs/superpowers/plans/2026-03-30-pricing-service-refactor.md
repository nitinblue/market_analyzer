# PricingService Refactor — Single-Pass Ranking Pipeline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 6-layer repricing mess in rank_opportunities.py with a single-pass pipeline where entry_credit is computed exactly once and never overwritten.

**Architecture:** Extract a `PricingService` that fetches chain once per ticker, reprices all structures for that ticker, and returns an immutable `RepricedTrade` dataclass. The ranking function becomes a thin orchestrator: detect regimes → reprice → POP → size → filter → output. No variable assigned twice.

**Tech Stack:** Python 3.12, Pydantic, existing broker adapters (Dhan, TastyTrade)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `income_desk/workflow/pricing_service.py` | CREATE | Single source of truth for repricing. Fetches chain, matches legs, computes credit, checks liquidity. |
| `income_desk/workflow/rank_opportunities.py` | REWRITE | Thin orchestrator only. No repricing logic. No sleep calls. |
| `income_desk/workflow/_types.py` | MODIFY | Add `credit_source` field to TradeProposal |
| `tests/test_pricing_service.py` | CREATE | Unit tests for PricingService |
| `tests/test_rank_opportunities_refactor.py` | CREATE | Integration tests for new ranking flow |

**Not touched (intentionally):** `liquidity_filter.py` (deprecated — functionality absorbed into PricingService), `price_trade.py` (kept as standalone leg-level pricer for CLI), `trade_lifecycle.py` (POP stays here, DTE fix already done).

---

### Task 1: Create RepricedTrade dataclass

**Files:**
- Create: `income_desk/workflow/pricing_service.py`
- Test: `tests/test_pricing_service.py`

- [ ] **Step 1: Write failing test for RepricedTrade**

```python
# tests/test_pricing_service.py
from income_desk.workflow.pricing_service import RepricedTrade

def test_repriced_trade_immutable():
    t = RepricedTrade(
        ticker="NIFTY", structure="iron_condor",
        entry_credit=13.50, credit_source="chain",
        wing_width=50.0, lot_size=25, current_price=22500.0,
        atr_pct=2.06, regime_id=1, expiry="2026-03-30",
        legs_found=True, liquidity_ok=True,
    )
    assert t.entry_credit == 13.50
    assert t.credit_source == "chain"
```

- [ ] **Step 2: Run test to verify it fails**
Run: `.venv_312/Scripts/python -m pytest tests/test_pricing_service.py::test_repriced_trade_immutable -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Write RepricedTrade**

```python
# income_desk/workflow/pricing_service.py
"""PricingService — single source of truth for option trade repricing.

Fetches chain ONCE per ticker. Reprices all structures. Returns immutable result.
No downstream code should overwrite entry_credit after this.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


class RepricedTrade(BaseModel):
    """Immutable repricing result. Created once, never modified.

    All fields are typed and validated via Pydantic. This is the single
    source of truth for entry_credit — no downstream code may overwrite it.
    """
    model_config = {"frozen": True}

    ticker: str
    structure: str
    entry_credit: float          # Net credit (positive) or debit (negative)
    credit_source: str           # "chain" | "estimated" | "blocked"
    wing_width: float
    lot_size: int
    current_price: float
    atr_pct: float
    regime_id: int
    expiry: str | None = None
    legs_found: bool             # All legs matched in liquid chain
    liquidity_ok: bool           # OI and spread checks passed
    block_reason: str | None = None  # If blocked, why
    leg_details: list[LegDetail] = []  # Per-leg pricing breakdown


class LegDetail(BaseModel):
    """Per-leg pricing from the chain. All fields required."""
    strike: float
    option_type: str             # "call" | "put"
    action: str                  # "sell" | "buy"
    bid: float
    ask: float
    mid: float
    iv: float | None = None
    delta: float | None = None
    open_interest: int = 0
    volume: int = 0
```

- [ ] **Step 4: Run test, verify PASS**
- [ ] **Step 5: Commit**
```bash
git commit -m "feat: RepricedTrade dataclass — immutable pricing result"
```

---

### Task 2: Create reprice_trade() function

**Files:**
- Modify: `income_desk/workflow/pricing_service.py`
- Test: `tests/test_pricing_service.py`

- [ ] **Step 1: Write failing test**

```python
def test_reprice_from_chain():
    """Chain with all legs found → entry_credit from mids."""
    from income_desk.workflow.pricing_service import reprice_trade
    from unittest.mock import MagicMock

    # Mock chain with 4 quotes
    def make_quote(strike, opt_type, bid, ask):
        q = MagicMock()
        q.strike = strike
        q.option_type = opt_type
        q.bid = bid
        q.ask = ask
        q.mid = (bid + ask) / 2
        q.open_interest = 5000
        q.volume = 100
        return q

    chain = [
        make_quote(1320, "put", 10.0, 10.4),   # STO
        make_quote(1300, "put", 0.5, 0.7),      # BTO
        make_quote(1380, "call", 8.0, 8.4),     # STO
        make_quote(1400, "call", 0.3, 0.5),     # BTO
    ]

    # Mock trade_spec with matching legs
    ts = MagicMock()
    ts.structure_type = "iron_condor"
    ts.lot_size = 250
    ts.wing_width_points = 20.0
    ts.legs = []

    from income_desk.models.opportunity import LegAction
    for strike, opt_type, action in [
        (1320, "put", LegAction.SELL_TO_OPEN),
        (1300, "put", LegAction.BUY_TO_OPEN),
        (1380, "call", LegAction.SELL_TO_OPEN),
        (1400, "call", LegAction.BUY_TO_OPEN),
    ]:
        leg = MagicMock()
        leg.strike = strike
        leg.option_type = opt_type
        leg.action = action
        leg.expiration = date(2026, 3, 30)
        ts.legs.append(leg)

    result = reprice_trade(
        trade_spec=ts, chain=chain,
        ticker="RELIANCE", current_price=1350.0,
        atr_pct=2.37, regime_id=1,
    )

    assert result.legs_found is True
    assert result.credit_source == "chain"
    # credit = (10.2 + 8.2) - (0.6 + 0.4) = 17.4
    assert abs(result.entry_credit - 17.4) < 0.1
    assert result.wing_width == 20.0
    assert result.lot_size == 250


def test_reprice_missing_leg_blocks():
    """Chain missing a leg → blocked."""
    from income_desk.workflow.pricing_service import reprice_trade
    from unittest.mock import MagicMock

    chain = []  # Empty chain
    ts = MagicMock()
    ts.structure_type = "iron_condor"
    ts.lot_size = 250
    ts.wing_width_points = 20.0
    leg = MagicMock()
    leg.strike = 1320
    leg.option_type = "put"
    leg.action = MagicMock(value="STO")
    leg.expiration = date(2026, 3, 30)
    ts.legs = [leg]

    result = reprice_trade(
        trade_spec=ts, chain=chain,
        ticker="RELIANCE", current_price=1350.0,
        atr_pct=2.37, regime_id=1,
    )

    assert result.legs_found is False
    assert result.credit_source == "blocked"
    assert result.block_reason is not None


def test_reprice_no_price_blocks():
    """current_price=0 → blocked immediately."""
    from income_desk.workflow.pricing_service import reprice_trade
    from unittest.mock import MagicMock

    result = reprice_trade(
        trade_spec=MagicMock(legs=[], structure_type="ic", lot_size=25, wing_width_points=50),
        chain=[],
        ticker="NIFTY", current_price=0.0,
        atr_pct=2.0, regime_id=1,
    )

    assert result.credit_source == "blocked"
    assert "price" in result.block_reason.lower()


def test_reprice_illiquid_spread_blocks():
    """Wide bid-ask spread → liquidity_ok=False."""
    from income_desk.workflow.pricing_service import reprice_trade
    from unittest.mock import MagicMock

    def make_quote(strike, opt_type, bid, ask, oi=0):
        q = MagicMock()
        q.strike = strike
        q.option_type = opt_type
        q.bid = bid
        q.ask = ask
        q.mid = (bid + ask) / 2
        q.open_interest = oi
        q.volume = 0
        return q

    # Wide spread (bid=0.1, ask=5.0 = 4900% spread)
    chain = [make_quote(1320, "put", 0.1, 5.0, oi=0)]
    ts = MagicMock()
    ts.structure_type = "credit_spread"
    ts.lot_size = 250
    ts.wing_width_points = 20.0
    leg = MagicMock()
    leg.strike = 1320
    leg.option_type = "put"
    leg.action = MagicMock(value="STO")
    leg.expiration = date(2026, 3, 30)
    ts.legs = [leg]

    result = reprice_trade(
        trade_spec=ts, chain=chain,
        ticker="RELIANCE", current_price=1350.0,
        atr_pct=2.37, regime_id=1,
    )

    assert result.liquidity_ok is False
```

- [ ] **Step 2: Run tests, verify FAIL**

- [ ] **Step 3: Implement reprice_trade()**

```python
# Add to income_desk/workflow/pricing_service.py

MIN_OI = 100          # Minimum OI for a strike to be considered liquid
MAX_SPREAD_PCT = 0.30  # 30% max bid-ask spread

def reprice_trade(
    trade_spec,
    chain: list,
    ticker: str,
    current_price: float,
    atr_pct: float,
    regime_id: int,
) -> RepricedTrade:
    """Reprice a TradeSpec against a real option chain. Returns immutable result.

    This is the ONLY place entry_credit is computed. No downstream code
    should overwrite it.
    """
    st = trade_spec.structure_type or ""
    lot_size = trade_spec.lot_size or 25  # Conservative default
    wing_width = trade_spec.wing_width_points or 0.0
    expiry = str(trade_spec.legs[0].expiration) if trade_spec.legs else None

    # Block on missing price — no safe fallback exists (TD-02)
    if current_price <= 0:
        return RepricedTrade(
            ticker=ticker, structure=st, entry_credit=0.0,
            credit_source="blocked", wing_width=wing_width,
            lot_size=lot_size, current_price=0.0, atr_pct=atr_pct,
            regime_id=regime_id, expiry=expiry,
            legs_found=False, liquidity_ok=False,
            block_reason="current_price <= 0 — no market data",
        )

    if not chain or not trade_spec.legs:
        return RepricedTrade(
            ticker=ticker, structure=st, entry_credit=0.0,
            credit_source="blocked", wing_width=wing_width,
            lot_size=lot_size, current_price=current_price,
            atr_pct=atr_pct, regime_id=regime_id, expiry=expiry,
            legs_found=False, liquidity_ok=False,
            block_reason="No chain data or no legs",
        )

    # Build chain lookup — only liquid quotes
    chain_map = {
        (q.strike, q.option_type): q
        for q in chain if q.bid > 0 and q.ask > 0
    }

    # Match legs to chain
    leg_credits = []
    leg_details = []
    all_found = True
    liquidity_ok = True

    for leg in trade_spec.legs:
        key = (leg.strike, leg.option_type)
        q = chain_map.get(key)
        if not q:
            all_found = False
            leg_details.append((leg.strike, leg.option_type, "?", 0, 0, 0))
            continue

        action_str = getattr(leg.action, "value", str(leg.action)).lower()
        is_sell = action_str in ("sell", "sto", "short")
        contrib = q.mid if is_sell else -q.mid
        leg_credits.append(contrib)
        leg_details.append((
            leg.strike, leg.option_type,
            "sell" if is_sell else "buy",
            q.bid, q.ask, q.mid,
        ))

        # Liquidity check per leg
        if q.mid > 0:
            spread_pct = (q.ask - q.bid) / q.mid
            if spread_pct > MAX_SPREAD_PCT:
                liquidity_ok = False
        if getattr(q, "open_interest", 0) < MIN_OI:
            liquidity_ok = False

    if not all_found:
        return RepricedTrade(
            ticker=ticker, structure=st, entry_credit=0.0,
            credit_source="blocked", wing_width=wing_width,
            lot_size=lot_size, current_price=current_price,
            atr_pct=atr_pct, regime_id=regime_id, expiry=expiry,
            legs_found=False, liquidity_ok=False,
            block_reason=f"Missing strikes in liquid chain",
            leg_details=tuple(leg_details),
        )

    entry_credit = sum(leg_credits)

    # Compute wing width from actual legs if not on spec
    if wing_width <= 0 and len(trade_spec.legs) >= 2:
        strikes = sorted(set(l.strike for l in trade_spec.legs))
        if len(strikes) >= 2:
            wing_width = strikes[1] - strikes[0]

    return RepricedTrade(
        ticker=ticker, structure=st,
        entry_credit=round(entry_credit, 2),
        credit_source="chain",
        wing_width=wing_width, lot_size=lot_size,
        current_price=current_price, atr_pct=atr_pct,
        regime_id=regime_id, expiry=expiry,
        legs_found=True, liquidity_ok=liquidity_ok,
        leg_details=tuple(leg_details),
    )
```

- [ ] **Step 4: Run tests, verify all PASS**
- [ ] **Step 5: Commit**
```bash
git commit -m "feat: reprice_trade() — single source of truth for entry_credit"
```

---

### Task 3: Create batch_reprice() that fetches chain once per ticker

**Files:**
- Modify: `income_desk/workflow/pricing_service.py`
- Test: `tests/test_pricing_service.py`

- [ ] **Step 1: Write failing test**

```python
def test_batch_reprice_fetches_chain_once():
    """Two structures for same ticker → one chain fetch."""
    from income_desk.workflow.pricing_service import batch_reprice
    from unittest.mock import MagicMock, call

    md = MagicMock()
    md.get_option_chain.return_value = []  # Empty chain
    md.get_underlying_price.return_value = 1350.0

    ts1 = MagicMock(structure_type="ic", legs=[], lot_size=250, wing_width_points=20)
    ts2 = MagicMock(structure_type="cs", legs=[], lot_size=250, wing_width_points=15)

    entries = [
        {"ticker": "RELIANCE", "trade_spec": ts1, "regime_id": 1, "atr_pct": 2.37},
        {"ticker": "RELIANCE", "trade_spec": ts2, "regime_id": 1, "atr_pct": 2.37},
    ]

    results = batch_reprice(entries, md)

    # Chain fetched exactly once for RELIANCE
    assert md.get_option_chain.call_count == 1
    assert len(results) == 2
```

- [ ] **Step 2: Run, verify FAIL**

- [ ] **Step 3: Implement batch_reprice()**

```python
def batch_reprice(
    entries: list[dict],
    market_data,
    technicals_service=None,
) -> list[RepricedTrade]:
    """Reprice multiple trades, fetching chain once per ticker.

    Args:
        entries: list of {ticker, trade_spec, regime_id, atr_pct, current_price?}
        market_data: MarketDataProvider (Dhan, TastyTrade, etc.)
        technicals_service: Optional, for price/ATR lookup

    Returns:
        list of RepricedTrade (same order as entries)
    """
    import time

    # Group by ticker for efficient chain fetching
    chain_cache: dict[str, list] = {}
    price_cache: dict[str, float] = {}

    unique_tickers = list(dict.fromkeys(e["ticker"] for e in entries))

    for ticker in unique_tickers:
        # Fetch price
        price = 0.0
        if technicals_service:
            try:
                tech = technicals_service.snapshot(ticker)
                if tech:
                    price = tech.current_price or 0.0
            except Exception:
                pass
        if price <= 0 and market_data:
            try:
                price = market_data.get_underlying_price(ticker) or 0.0
            except Exception:
                pass
        price_cache[ticker] = price

        # Fetch chain (with rate limit awareness)
        if market_data:
            if chain_cache:  # Not first ticker
                time.sleep(4)  # Dhan rate limit
            try:
                chain_cache[ticker] = market_data.get_option_chain(ticker) or []
            except Exception:
                chain_cache[ticker] = []
        else:
            chain_cache[ticker] = []

    # Reprice each entry
    results = []
    for entry in entries:
        ticker = entry["ticker"]
        current_price = entry.get("current_price") or price_cache.get(ticker, 0.0)
        atr_pct = entry.get("atr_pct", 1.0)
        regime_id = entry.get("regime_id", 1)

        result = reprice_trade(
            trade_spec=entry["trade_spec"],
            chain=chain_cache.get(ticker, []),
            ticker=ticker,
            current_price=current_price,
            atr_pct=atr_pct,
            regime_id=regime_id,
        )
        results.append(result)

    return results
```

- [ ] **Step 4: Run tests, verify PASS**
- [ ] **Step 5: Commit**
```bash
git commit -m "feat: batch_reprice() — chain fetched once per ticker"
```

---

### Task 4: Add credit_source to TradeProposal (TD-14)

**Files:**
- Modify: `income_desk/workflow/_types.py`

- [ ] **Step 1: Add credit_source field**

```python
# In TradeProposal class, after entry_credit
credit_source: str = "unknown"  # "chain" | "estimated" | "blocked"
```

- [ ] **Step 2: Commit**
```bash
git commit -m "feat: TradeProposal.credit_source — provenance tracking (TD-14)"
```

---

### Task 5: Rewrite rank_opportunities as thin orchestrator

**Files:**
- Modify: `income_desk/workflow/rank_opportunities.py`
- Test: `tests/test_rank_opportunities_refactor.py`

This is the big task. The 430-line function becomes ~150 lines:

- [ ] **Step 1: Write integration test**

```python
def test_rank_single_pass_no_overwrite():
    """entry_credit is set once by PricingService, never overwritten."""
    # Uses mocked MarketAnalyzer with known chain data
    # Verify: TradeProposal.entry_credit == RepricedTrade.entry_credit
    # Verify: POP uses the same entry_credit
    pass  # Full test in implementation
```

- [ ] **Step 2: Rewrite rank_opportunities()**

New structure (pseudocode):
```python
def rank_opportunities(request, ma):
    # 1. Detect regimes (unchanged)
    regimes = detect_regimes(request.tickers, ma)
    tradeable = [t for t, r in regimes.items() if r.tradeable]

    # 2. Get ranked trade specs from assessors (unchanged)
    ranking = ma.ranking.rank(tradeable, ...)

    # 3. NEW: Batch reprice all trades at once
    entries = [
        {"ticker": e.ticker, "trade_spec": e.trade_spec,
         "regime_id": regimes[e.ticker].regime_id}
        for e in ranking.top_trades if e.trade_spec
    ]
    repriced = batch_reprice(entries, ma.market_data, ma.technicals)

    # 4. Single pass: POP → size → filter → output
    trades = []
    blocked = []
    for entry, rp in zip(ranking.top_trades, repriced):
        # 4a. Block if repricing failed
        if rp.block_reason:
            blocked.append(BlockedTrade(..., reason=rp.block_reason))
            continue

        # 4b. Block if illiquid
        if not rp.liquidity_ok:
            blocked.append(BlockedTrade(..., reason="Illiquid strikes"))
            continue

        # 4c. POP — uses rp.entry_credit (FINAL, never changes)
        pop = estimate_pop(ts, entry_price=rp.entry_credit, ...)

        # 4d. Size — uses rp.entry_credit
        contracts = compute_position_size(pop, rp.entry_credit * rp.lot_size, ...)

        # 4e. Build proposal (entry_credit set once from rp)
        trades.append(TradeProposal(
            entry_credit=rp.entry_credit,
            credit_source=rp.credit_source,
            ...
        ))

    return RankResponse(trades=trades, blocked=blocked, ...)
```

- [ ] **Step 3: Remove liquidity filter calls** (lines 332-393 deleted entirely)
- [ ] **Step 4: Remove sleep calls** (lines 337, 375 deleted)
- [ ] **Step 5: Remove `current_price = 100.0` fallback** (TD-02) — block instead
- [ ] **Step 6: Run full test suite**
Run: `.venv_312/Scripts/python -m pytest tests/ -m "not integration" -q`
- [ ] **Step 7: Commit**
```bash
git commit -m "refactor: rank_opportunities single-pass pipeline (TD-01,02,04,06)"
```

---

### Task 6: Fix wing_width and lot_size defaults (TD-03, TD-05)

**Files:**
- Modify: `income_desk/workflow/pricing_service.py`
- Modify: `income_desk/trade_lifecycle.py:771`

- [ ] **Step 1: In reprice_trade, derive lot_size from registry**

```python
# Replace: lot_size = trade_spec.lot_size or 25
from income_desk import MarketRegistry
reg = MarketRegistry()
inst = reg.get_instrument(ticker)
lot_size = inst.lot_size if inst and inst.lot_size else (trade_spec.lot_size or 25)
```

- [ ] **Step 2: In trade_lifecycle.py, block on wing_width=0 instead of defaulting to 5**

```python
# Replace: wing = trade_spec.wing_width_points or 5.0
wing = trade_spec.wing_width_points
if not wing or wing <= 0:
    return None  # Cannot compute EV without wing width
```

- [ ] **Step 3: Run tests, fix any failures from removed fallbacks**
- [ ] **Step 4: Commit**
```bash
git commit -m "fix: market-specific lot_size from registry, block on missing wing_width (TD-03,05)"
```

---

### Task 7: Update harness and daily_plan to use credit_source

**Files:**
- Modify: `income_desk/trader/trader.py`

- [ ] **Step 1: Show credit_source in ranked trades table**

Add column showing "chain" or "est" so trader knows data quality.

- [ ] **Step 2: Commit**
```bash
git commit -m "feat: show credit_source in harness output"
```

---

### Task 8: Run full India harness and verify

- [ ] **Step 1: Run harness**
```bash
.venv_312/Scripts/python -m income_desk.trader.trader --all --market=India
```

- [ ] **Step 2: Verify:**
- entry_credit assigned exactly once (no "using estimated credit" warnings)
- POP is 30-80% for income trades (not 0.8% or 99%)
- credit_source shows "chain" for all broker-connected trades
- No sleep(3.5) in output timing (should be faster)

- [ ] **Step 3: Run pricing regression**
```bash
.venv_312/Scripts/python scripts/pricing_regression.py --market India --rebuild --detail
```

- [ ] **Step 4: Update go_live_scoring.md with new evidence**
- [ ] **Step 5: Final commit**
```bash
git commit -m "verify: India harness passes with single-pass pricing pipeline"
```
