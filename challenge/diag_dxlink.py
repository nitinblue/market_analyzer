"""DXLink diagnostic — test each layer independently."""

import asyncio
import logging
import os
import time
import sys

# Load eTrading .env for credentials
from pathlib import Path
env_path = Path(os.path.expanduser("~")) / "PythonProjects" / "eTrading" / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("diag")


def test_1_session():
    """Test: Can we create a TastyTrade session?"""
    print("\n=== TEST 1: Session Creation ===")
    from tastytrade import Session

    secret = os.getenv("TASTYTRADE_CLIENT_SECRET_LIVE", "")
    token = os.getenv("TASTYTRADE_REFRESH_TOKEN_LIVE", "")

    if not secret or not token:
        print("SKIP: No LIVE credentials in env")
        return None

    t0 = time.time()
    session = Session(secret, token, is_test=False)
    print(f"OK: Session created in {time.time()-t0:.1f}s")
    return session


def test_2_dxlink_connect(session):
    """Test: Can we open a DXLink streamer?"""
    print("\n=== TEST 2: DXLink Connection ===")
    from tastytrade.streamer import DXLinkStreamer

    async def _test():
        t0 = time.time()
        async with DXLinkStreamer(session) as streamer:
            elapsed = time.time() - t0
            print(f"OK: DXLink connected in {elapsed:.1f}s")
            return True

    try:
        result = asyncio.run(_test())
        return result
    except Exception as e:
        print(f"FAIL: {e}")
        return False


def test_3_equity_quote(session, ticker="SPY"):
    """Test: Can we get an equity quote via DXLink?"""
    print(f"\n=== TEST 3: Equity Quote ({ticker}) ===")
    from tastytrade.dxfeed import Quote as DXQuote
    from tastytrade.streamer import DXLinkStreamer

    async def _test():
        t0 = time.time()
        async with DXLinkStreamer(session) as streamer:
            connect_time = time.time() - t0
            print(f"  Connected in {connect_time:.1f}s")

            await streamer.subscribe(DXQuote, [ticker])
            print(f"  Subscribed to {ticker}")

            try:
                event = await asyncio.wait_for(
                    streamer.get_event(DXQuote), timeout=5.0
                )
                elapsed = time.time() - t0
                bid = float(event.bid_price or 0)
                ask = float(event.ask_price or 0)
                print(f"OK: {ticker} bid={bid} ask={ask} mid={round((bid+ask)/2, 2)} ({elapsed:.1f}s)")
                return True
            except asyncio.TimeoutError:
                print(f"FAIL: Timeout after 5s waiting for {ticker} quote")
                return False

    try:
        return asyncio.run(_test())
    except Exception as e:
        print(f"FAIL: {e}")
        return False


def test_4_option_quote(session, ticker="SPY"):
    """Test: Can we get option quotes via DXLink?"""
    print(f"\n=== TEST 4: Option Quote ({ticker}) ===")
    from tastytrade.instruments import Option
    from tastytrade.dxfeed import Quote as DXQuote
    from tastytrade.streamer import DXLinkStreamer

    # Get chain to find valid streamer symbols
    chain = Option.get_option_chain(session, ticker)
    if asyncio.iscoroutine(chain):
        chain = asyncio.run(chain)

    # Pick first expiration, first 3 options
    if not chain:
        print("FAIL: No option chain returned")
        return False

    first_exp = sorted(chain.keys())[0]
    options = chain[first_exp][:3]
    symbols = [o.streamer_symbol for o in options if o.streamer_symbol]

    if not symbols:
        print("FAIL: No streamer symbols found")
        return False

    print(f"  Symbols to test: {symbols}")

    async def _test():
        t0 = time.time()
        async with DXLinkStreamer(session) as streamer:
            connect_time = time.time() - t0
            print(f"  Connected in {connect_time:.1f}s")

            await streamer.subscribe(DXQuote, symbols)
            print(f"  Subscribed to {len(symbols)} option symbols")

            received = {}
            timeout = 5.0
            end = asyncio.get_event_loop().time() + timeout

            while len(received) < len(symbols) and asyncio.get_event_loop().time() < end:
                try:
                    event = await asyncio.wait_for(
                        streamer.get_event(DXQuote), timeout=2.0
                    )
                    sym = event.event_symbol
                    bid = float(event.bid_price or 0)
                    ask = float(event.ask_price or 0)
                    received[sym] = (bid, ask)
                    print(f"  Got: {sym} bid={bid} ask={ask}")
                except asyncio.TimeoutError:
                    continue

            elapsed = time.time() - t0
            print(f"OK: Got {len(received)}/{len(symbols)} option quotes in {elapsed:.1f}s")
            return len(received) > 0

    try:
        return asyncio.run(_test())
    except Exception as e:
        print(f"FAIL: {e}")
        return False


def test_5_option_greeks(session, ticker="SPY"):
    """Test: Can we get Greeks via DXLink?"""
    print(f"\n=== TEST 5: Option Greeks ({ticker}) ===")
    from tastytrade.instruments import Option
    from tastytrade.dxfeed import Greeks as DXGreeks
    from tastytrade.streamer import DXLinkStreamer

    chain = Option.get_option_chain(session, ticker)
    if asyncio.iscoroutine(chain):
        chain = asyncio.run(chain)

    if not chain:
        print("FAIL: No option chain")
        return False

    first_exp = sorted(chain.keys())[0]
    options = chain[first_exp][:3]
    symbols = [o.streamer_symbol for o in options if o.streamer_symbol]

    if not symbols:
        print("FAIL: No streamer symbols")
        return False

    print(f"  Symbols to test: {symbols}")

    async def _test():
        t0 = time.time()
        async with DXLinkStreamer(session) as streamer:
            connect_time = time.time() - t0
            print(f"  Connected in {connect_time:.1f}s")

            await streamer.subscribe(DXGreeks, symbols)
            print(f"  Subscribed to Greeks for {len(symbols)} symbols")

            received = {}
            timeout = 10.0
            end = asyncio.get_event_loop().time() + timeout

            while len(received) < len(symbols) and asyncio.get_event_loop().time() < end:
                try:
                    event = await asyncio.wait_for(
                        streamer.get_event(DXGreeks), timeout=2.0
                    )
                    sym = event.event_symbol
                    delta = float(event.delta or 0)
                    theta = float(event.theta or 0)
                    iv = float(event.volatility or 0) if hasattr(event, "volatility") else None
                    received[sym] = (delta, theta, iv)
                    print(f"  Got: {sym} delta={delta:.4f} theta={theta:.4f} iv={iv}")
                except asyncio.TimeoutError:
                    continue

            elapsed = time.time() - t0
            print(f"OK: Got {len(received)}/{len(symbols)} Greeks in {elapsed:.1f}s")
            return len(received) > 0

    try:
        return asyncio.run(_test())
    except Exception as e:
        print(f"FAIL: {e}")
        return False


def test_6_repeated_connections(session, n=5):
    """Test: Performance of opening N sequential DXLink connections."""
    print(f"\n=== TEST 6: {n} Sequential DXLink Connections ===")
    from tastytrade.dxfeed import Quote as DXQuote
    from tastytrade.streamer import DXLinkStreamer

    times = []

    for i in range(n):
        async def _test():
            t0 = time.time()
            async with DXLinkStreamer(session) as streamer:
                await streamer.subscribe(DXQuote, ["SPY"])
                event = await asyncio.wait_for(
                    streamer.get_event(DXQuote), timeout=5.0
                )
                elapsed = time.time() - t0
                return elapsed

        try:
            t = asyncio.run(_test())
            times.append(t)
            print(f"  Connection {i+1}: {t:.1f}s")
        except Exception as e:
            print(f"  Connection {i+1}: FAIL ({e})")

    if times:
        print(f"Avg: {sum(times)/len(times):.1f}s, Total: {sum(times):.1f}s")


def test_7_single_connection_multiple_subs(session):
    """Test: One DXLink connection, multiple subscriptions."""
    print(f"\n=== TEST 7: Single Connection, Multiple Subscriptions ===")
    from tastytrade.instruments import Option
    from tastytrade.dxfeed import Quote as DXQuote, Greeks as DXGreeks
    from tastytrade.streamer import DXLinkStreamer

    chain = Option.get_option_chain(session, "SPY")
    if asyncio.iscoroutine(chain):
        chain = asyncio.run(chain)

    first_exp = sorted(chain.keys())[0]
    symbols = [o.streamer_symbol for o in chain[first_exp][:5] if o.streamer_symbol]

    async def _test():
        t0 = time.time()
        async with DXLinkStreamer(session) as streamer:
            connect_time = time.time() - t0
            print(f"  Connected in {connect_time:.1f}s")

            # Subscribe to both quotes AND Greeks on same connection
            await streamer.subscribe(DXQuote, symbols)
            await streamer.subscribe(DXGreeks, symbols)
            print(f"  Subscribed to quotes+Greeks for {len(symbols)} symbols")

            quotes_got = set()
            greeks_got = set()
            timeout = 10.0
            end = asyncio.get_event_loop().time() + timeout

            while asyncio.get_event_loop().time() < end:
                try:
                    # Try quotes
                    event = await asyncio.wait_for(
                        streamer.get_event(DXQuote), timeout=1.0
                    )
                    quotes_got.add(event.event_symbol)
                except asyncio.TimeoutError:
                    pass

                try:
                    event = await asyncio.wait_for(
                        streamer.get_event(DXGreeks), timeout=1.0
                    )
                    greeks_got.add(event.event_symbol)
                except asyncio.TimeoutError:
                    pass

                if len(quotes_got) >= len(symbols) and len(greeks_got) >= len(symbols):
                    break

            elapsed = time.time() - t0
            print(f"OK: {len(quotes_got)} quotes, {len(greeks_got)} Greeks in {elapsed:.1f}s")

    try:
        asyncio.run(_test())
    except Exception as e:
        print(f"FAIL: {e}")


if __name__ == "__main__":
    # Run only specified tests, or all
    tests_to_run = set(sys.argv[1:]) if len(sys.argv) > 1 else {"1", "2", "3", "4", "5", "6", "7"}

    session = None
    if "1" in tests_to_run or any(t in tests_to_run for t in "234567"):
        session = test_1_session()
        if not session:
            print("\nABORT: No session — can't run remaining tests")
            sys.exit(1)

    if "2" in tests_to_run:
        test_2_dxlink_connect(session)

    if "3" in tests_to_run:
        test_3_equity_quote(session)

    if "4" in tests_to_run:
        test_4_option_quote(session)

    if "5" in tests_to_run:
        test_5_option_greeks(session)

    if "6" in tests_to_run:
        test_6_repeated_connections(session)

    if "7" in tests_to_run:
        test_7_single_connection_multiple_subs(session)

    print("\n=== DONE ===")
