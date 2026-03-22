"""Shared async-to-sync bridge for all TastyTrade broker operations.

Uses a single persistent event loop to avoid the ``Event loop is closed``
error that occurs when mixing ``asyncio.run()`` calls with the tastytrade
SDK's httpx AsyncClient. Every async call in session.py, market_data.py,
metrics.py, and account.py should go through ``run_sync()`` instead of
``asyncio.run()``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading

logger = logging.getLogger(__name__)

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()
_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def run_sync(coro, timeout: float = 30):
    """Run an async coroutine from sync context using a persistent event loop.

    Safe to call multiple times — the same event loop is reused across calls,
    preventing the httpx ``Event loop is closed`` error that occurs with
    repeated ``asyncio.run()`` calls.
    """
    global _loop

    # If already inside an async context (e.g. FastAPI), run in thread pool
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        future = _thread_pool.submit(asyncio.run, coro)
        return future.result(timeout=timeout)

    # Standalone: reuse persistent loop
    with _lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
        try:
            return _loop.run_until_complete(
                asyncio.wait_for(coro, timeout=timeout)
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"Async operation timed out after {timeout}s")
        except Exception:
            coro.close()
            raise
