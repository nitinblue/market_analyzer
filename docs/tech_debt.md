# Tech Debt Register

> From code review 2026-03-30. Root cause of 30-day debugging loop.

## P0 — Must Fix Before Live Trading

| ID | Issue | File:Line | Impact |
|----|-------|-----------|--------|
| TD-01 | POP computed BEFORE final entry_credit (liquidity filter overwrites after) | rank_opportunities.py:228 vs 350,388 | POP/credit inconsistent — capital risk |
| TD-02 | Silent fallback to current_price=100.0, atr_pct=1.0 when technicals fail | rank_opportunities.py:141-153 | NIFTY sized at 100 instead of 24000 — 240x wrong |
| TD-03 | `wing_width_points or 5.0` in 20+ locations — US default for India | trade_lifecycle.py:771, rank_opportunities.py:265, +18 more | India max_loss 10x underestimated |
| TD-04 | entry_credit assigned 6 times in rank_opportunities.py | rank_opportunities.py:174,203,219,221,350,388 | No single source of truth — root cause of all repricing bugs |
| TD-05 | `lot_size = ts.lot_size or 100` — US default for India | rank_opportunities.py:134 | Wrong margin, wrong P&L for India |

## P1 — Fix Before India Go-Live

| ID | Issue | File:Line | Impact |
|----|-------|-----------|--------|
| TD-06 | Hardcoded sleep(3.5) in ranking loop | rank_opportunities.py:337,375 | 35-70s wall time for 10 tickers |
| TD-07 | price_trade.py is disconnected third repricing layer | price_trade.py:66-67,92 | Different credit than ranking — confusing |
| TD-08 | Liquidity filter skipped for chain-repriced trades (no OI/spread check) | rank_opportunities.py:332-334 | Illiquid trades pass as "verified" |
| TD-09 | validate_trade builds dummy IC with India-invalid strikes | validate_trade.py:42-68 | NIFTY strikes rounded to 10 instead of 50 |
| TD-10 | _compute_breakevens doesn't handle India lot-based units | trade_lifecycle.py:151-191 | Breakeven wrong if entry_price units inconsistent |
| TD-11 | Dhan lot sizes duplicated (market_data.py AND registry.py) | dhan/market_data.py:89-142 | Drift when NSE updates quarterly |
| TD-12 | liquidity_filter always returns fill_quality="good" | liquidity_filter.py:316,424 | Bypasses real fill quality assessment |

## P2 — Nice to Have

| ID | Issue | File:Line | Impact |
|----|-------|-----------|--------|
| TD-13 | rank_opportunities is 430-line monolith | rank_opportunities.py | Untestable, bugs hide |
| TD-14 | No credit_source provenance on TradeProposal | _types.py | Can't tell real vs estimated |
| TD-15 | _fetch_iv_rank_map swallows all exceptions | trader.py:84-96 | Silent IV degradation |
| TD-16 | Dhan _resolve_scrip_code falls through to int(ticker) | dhan/market_data.py:254-272 | Typos silently resolve |
| TD-17 | Currency defaults to "USD" on TradeProposal | _types.py:46 | India trades show USD |

## Architectural Root Cause

**entry_credit is computed 6 times across 3 files. POP uses credit from step 2, sizing uses credit from step 2, but step 4 (liquidity filter) overwrites both. The final TradeProposal carries step-4 credit with step-2 POP and step-2 sizing.**

Fix: **Single-pass pipeline** — reprice once, compute all derived values from that single result, never overwrite.
