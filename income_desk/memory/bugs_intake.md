# Bugs Intake

> Type: INTAKE | Last reviewed: 2026-04-01 | Staleness: FRESH

## Active Items

| Key | Item | Added | Last Actioned | Status | Assignee | Next Action | Blockers | Delivered To |
|-----|------|-------|---------------|--------|----------|-------------|----------|--------------|
| BUG-001 | BAC/GBTC equity 100x multiplier in regression | 2026-03-26 | 2026-04-01 | CLOSED | Claude | Fixed: build_equity_trade_spec now forces lot_size=1 for equity trades. Registry lot_size=100 is for options, not shares. Validator already catches this (pipeline_validation.py:116) | — | _trade_spec_helpers.py |
| BUG-002 | India tickers ICICIBANK/SBIN 404 on yfinance — yfinance needs .NS suffix (ICICIBANK.NS, SBIN.NS) but ranking is passing bare ticker | 2026-03-29 | 2026-03-29 | DELIVERED | Claude | Created `resolve_yfinance_ticker()` in yfinance provider — resolves India stocks via MarketRegistry (.NS suffix). Wired into all 6 yfinance call sites (fundamentals, capital_deployment, premarket_scanner, technical, regime_service, equity_research). Retry flood fixed via `limit_yfinance_retries()` capping at 1 retry (was 11). 8 new tests. | — | 2026-03-29 |
| BUG-003 | Ranked trades show POP 1% for all India trades — clearly wrong. SBIN IC with 0.55 score but 1% POP makes no sense. POP calculation broken for India market | 2026-03-29 | 2026-04-01 | CLOSED | Claude | Fixed: strangle/straddle POP was 0% (unlimited risk path broken), iv_30_day now wired through pipeline, chain-first pipeline provides real IV. Commits d18a63b, 7295609 | — | trade_lifecycle.py |
| BUG-004 | India credits nonsensical — SBIN IC credit INR 0.63 with max risk INR 152,925 (0.0004% return). ICICIBANK credit INR 0.15. These are not real tradeable numbers | 2026-03-29 | 2026-04-01 | CLOSED | Claude | Fixed by chain-first pipeline: credits now from real bid/ask via ChainBundle. Degenerate guards reject same-strike trades. Commit 8070e7d, cba7788 | — | chain pipeline |
| BUG-005 | Validate trade passes ALL gates on garbage data — SBIN with INR 0.63 credit, 0.0 current_price, DTE=1, regime_id=1 (actual is R2). Gates are rubber-stamping bad input instead of catching it. current_price=0 alone should FAIL. Detail column mostly empty | 2026-03-29 | 2026-04-01 | CLOSED | Claude | Fixed: TradeValidator (5440f52) validates structure, strikes, POP bounds, credit thresholds, DTE. Rejects same-strike, zero-credit, suspicious POP. Root cause (garbage input) also fixed by chain-first pipeline | — | trade_validator.py |
| BUG-006 | Sizer returns 0 contracts — pop_pct 0.9978 (99.78%) is nonsensical input from ranking, max_loss INR 152,925 exceeds capital INR 50,000, wing_width 5.0 is US default not India. Kelly correctly returns 0 because the numbers are garbage, but the workflow should have halted earlier | 2026-03-29 | 2026-04-01 | CLOSED | Claude | Root cause fixed: chain-first pipeline provides real strikes/credits, TradeValidator catches suspicious POP (>95% flagged), lot_size from chain not US default. Upstream garbage no longer reaches sizer | — | chain pipeline |
| BUG-007 | Price trade: SBIN IC wing width only 5 points (975/970/1020/1025) on a INR 1000 stock — too narrow. IV shows 0.5-0.6% which is wrong (should be ~20-30%). Net credit INR 0.53 for an IC is untradeable. Strikes are from fallback estimation (price*0.97/0.93), not from actual chain | 2026-03-29 | 2026-04-01 | CLOSED | Claude | Fixed by chain-first pipeline: strikes now from real broker chain via ChainContext. Degenerate guards reject same-strike wings. IV from broker legs. Commits 8070e7d, cba7788 | — | chain pipeline |
| BUG-008 | FRED PCRATIOPCE + EQUITPC both return 400 with full tracebacks during India harness run — US macro data fetched even for India market. Tracebacks flood output | 2026-03-29 | 2026-03-29 | DELIVERED | Claude | BlackSwanService now accepts `market` param; skips FRED entirely for non-US markets. FREDFetcher `exc_info=True` replaced with single-line warning. 3 new tests. | 2026-03-29 | 2026-03-29 |
| BUG-009 | NIFTY/BANKNIFTY chain last_price vs ticker_data mismatch warnings (3.8x and 28.3x ratio) printed 3x each — noisy but may indicate real data issue with Dhan chain prices | 2026-03-29 | 2026-03-29 | OPEN | Claude | Investigate: is chain last_price the option price vs underlying? If expected, suppress warning. If real bug, fix Dhan adapter | — | — |
| BUG-010 | Stress test PnL% values absurd: -1260% for Black Monday on demo positions. Breach column shows "no" for -1260% loss which is clearly a breach | 2026-03-29 | 2026-03-29 | OPEN | Claude | PnL% calculation uses wrong base (dividing by premium instead of capital?). Breach detection threshold broken | — | — |
| BUG-011 | Account NLV shows INR 0, BP N/A in harness banner — Dhan get_balance returning zero/null | 2026-03-29 | 2026-03-30 | DELIVERED | Claude | Fixed 3 bugs: 0.0 falsy in or-chain, NLV missing collateral/sodLimit, SDK failure not detected. 4 new tests. | — | dhan/account.py |

| BUG-012 | TastyTrade get_option_chain subscribes to EVERY strike via DXLink WebSocket — 1000+ subscriptions for QQQ. Takes 3+ minutes per ticker, harness times out. Dhan returns full chain in 1 API call (~1s) | 2026-03-30 | 2026-03-30 | OPEN | Claude | Use TastyTrade REST API for bulk chain data (not DXLink streaming), or limit to ATM +/- N strikes | — | — |

## Archive

| Key | Item | Delivered | Resolution |
|-----|------|-----------|------------|
| BUG-ARCH-001 | FRED EQUITPC series 404 | 2026-03-29 | Fallback to PCRATIOPCE |
| BUG-ARCH-002 | DXLink probe warnings flood output | 2026-03-29 | Suppressed during setup |
| BUG-ARCH-003 | Windows Unicode encoding errors | 2026-03-29 | ASCII fallback |
