"""Shared broker connection helper for all CLI entry points.

Detects which broker to use from ~/.income_desk/broker.yaml (broker_type field)
or tries in order: TastyTrade → Alpaca → Schwab → IBKR.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from income_desk.broker.base import (
        AccountProvider, MarketDataProvider, MarketMetricsProvider, WatchlistProvider,
    )


def _styled(text: str, style: str = "") -> str:
    """Basic ANSI styling."""
    codes = {
        "bold": "\033[1m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "red": "\033[31m",
        "cyan": "\033[36m",
        "dim": "\033[2m",
        "reset": "\033[0m",
    }
    if not sys.stdout.isatty():
        return text
    code = codes.get(style, "")
    return f"{code}{text}{codes['reset']}" if code else text


def _load_env() -> None:
    """Load .env files from standard locations."""
    try:
        from dotenv import load_dotenv
        ma_env = Path.home() / ".income_desk" / ".env"
        if ma_env.exists():
            load_dotenv(ma_env)
        load_dotenv()
    except ImportError:
        pass


def _read_broker_config() -> dict:
    """Read ~/.income_desk/broker.yaml, returning empty dict if absent."""
    config_path = Path.home() / ".income_desk" / "broker.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def connect_broker(
    is_paper: bool = False,
    broker_type: str | None = None,
) -> tuple[
    MarketDataProvider | None,
    MarketMetricsProvider | None,
    AccountProvider | None,
    WatchlistProvider | None,
]:
    """Connect to a broker. Returns (market_data, market_metrics, account, watchlist).

    Broker selection order:
    1. ``broker_type`` argument (explicit override)
    2. ``broker_type`` field in ``~/.income_desk/broker.yaml``
    3. Auto-detect: TastyTrade → Alpaca → Schwab → IBKR

    Returns (None, None, None, None) on any failure — caller continues without broker.
    """
    _load_env()

    # Determine which broker to try
    cfg = _read_broker_config()
    resolved_type = broker_type or cfg.get("broker_type", "").lower().strip()

    if resolved_type == "tastytrade" or (not resolved_type and _has_tastytrade_creds(cfg)):
        result = _connect_tastytrade(is_paper)
        if result[0] is not None:
            return result
        if resolved_type == "tastytrade":
            return result  # explicit broker requested; don't fall through

    if resolved_type == "alpaca" or (not resolved_type and _has_alpaca_creds(cfg)):
        result = _connect_alpaca(cfg, is_paper)
        if result[0] is not None:
            return result
        if resolved_type == "alpaca":
            return result

    if resolved_type == "schwab" or (not resolved_type and _has_schwab_creds(cfg)):
        result = _connect_schwab(cfg)
        if result[0] is not None:
            return result
        if resolved_type == "schwab":
            return result

    if resolved_type == "ibkr" or (not resolved_type and _has_ibkr_config(cfg)):
        result = _connect_ibkr(cfg)
        if result[0] is not None:
            return result
        if resolved_type == "ibkr":
            return result

    if resolved_type == "dhan" or (not resolved_type and _has_dhan_creds(cfg)):
        result = _connect_dhan(cfg)
        if result[0] is not None:
            return result
        if resolved_type == "dhan":
            return result

    # Final fallback — try TastyTrade anyway (original behavior)
    if not resolved_type:
        result = _connect_tastytrade(is_paper)
        if result[0] is not None:
            return result

    print(_styled("No broker configured — running without broker", "yellow"))
    return None, None, None, None


# ------------------------------------------------------------------
# Per-broker connection functions
# ------------------------------------------------------------------

def _connect_tastytrade(is_paper: bool):
    """Attempt TastyTrade connection."""
    try:
        from income_desk.broker.tastytrade.session import TastyTradeBrokerSession
        from income_desk.broker.tastytrade.market_data import TastyTradeMarketData
        from income_desk.broker.tastytrade.metrics import TastyTradeMetrics
        from income_desk.broker.tastytrade.account import TastyTradeAccount
        from income_desk.broker.tastytrade.watchlist import TastyTradeWatchlist

        session = TastyTradeBrokerSession(is_paper=is_paper)
        if session.connect():
            market_data = TastyTradeMarketData(session)
            market_metrics = TastyTradeMetrics(session)
            account = TastyTradeAccount(session)
            watchlist = TastyTradeWatchlist(session)
            print(_styled(
                f"Broker connected: TastyTrade {session.account.account_number}", "green",
            ))
            return market_data, market_metrics, account, watchlist
        else:
            print(_styled("TastyTrade connection failed", "yellow"))
            return None, None, None, None
    except ImportError:
        return None, None, None, None
    except Exception as e:
        print(_styled(f"TastyTrade unavailable: {e}", "yellow"))
        return None, None, None, None


def _connect_alpaca(cfg: dict, is_paper: bool):
    """Attempt Alpaca connection."""
    import os
    try:
        from income_desk.broker.alpaca import connect_alpaca

        alpaca_cfg = cfg.get("alpaca", {})
        key = alpaca_cfg.get("api_key") or os.environ.get("ALPACA_API_KEY", "")
        secret = alpaca_cfg.get("api_secret") or os.environ.get("ALPACA_API_SECRET", "")
        paper = is_paper or alpaca_cfg.get("paper", True)

        if not key or not secret:
            return None, None, None, None

        md, mm, acct, wl = connect_alpaca(key, secret, paper=paper)
        if acct is not None:
            bal = acct.get_balance()
            mode = "paper" if paper else "live"
            print(_styled(
                f"Broker connected: Alpaca ({mode}) ${bal.net_liquidating_value:,.0f}", "green",
            ))
        return md, mm, acct, wl
    except ImportError:
        return None, None, None, None
    except Exception as e:
        print(_styled(f"Alpaca unavailable: {e}", "yellow"))
        return None, None, None, None


def _connect_schwab(cfg: dict):
    """Attempt Schwab connection."""
    import os
    try:
        from income_desk.broker.schwab import connect_schwab

        schwab_cfg = cfg.get("schwab", {})
        key = schwab_cfg.get("app_key") or os.environ.get("SCHWAB_APP_KEY", "")
        secret = schwab_cfg.get("app_secret") or os.environ.get("SCHWAB_APP_SECRET", "")
        token = schwab_cfg.get("token_path") or os.environ.get(
            "SCHWAB_TOKEN_PATH",
            str(Path.home() / ".income_desk" / "schwab_token.json"),
        )
        callback = schwab_cfg.get("callback_url", "https://127.0.0.1")

        if not key or not secret:
            return None, None, None, None

        md, mm, acct, wl = connect_schwab(key, secret, token_path=token, callback_url=callback)
        if acct is not None:
            bal = acct.get_balance()
            print(_styled(
                f"Broker connected: Schwab ${bal.net_liquidating_value:,.0f}", "green",
            ))
        return md, mm, acct, wl
    except ImportError:
        return None, None, None, None
    except Exception as e:
        print(_styled(f"Schwab unavailable: {e}", "yellow"))
        return None, None, None, None


def _connect_dhan(cfg: dict):
    """Attempt Dhan connection."""
    import os
    try:
        from income_desk.broker.dhan import connect_dhan

        dhan_cfg = cfg.get("dhan", {})
        client_id = dhan_cfg.get("client_id") or os.environ.get("DHAN_CLIENT_ID", "")
        access_token = dhan_cfg.get("access_token") or os.environ.get("DHAN_ACCESS_TOKEN", "")

        if not client_id or not access_token:
            return None, None, None, None

        md, mm, acct, wl = connect_dhan(client_id, access_token)
        if acct is not None:
            try:
                bal = acct.get_balance()
                print(_styled(
                    f"Broker connected: Dhan {bal.account_number} ₹{bal.cash_balance:,.0f}", "green",
                ))
            except Exception:
                print(_styled("Broker connected: Dhan", "green"))
        return md, mm, acct, wl
    except ImportError:
        return None, None, None, None
    except Exception as e:
        print(_styled(f"Dhan unavailable: {e}", "yellow"))
        return None, None, None, None


def _connect_ibkr(cfg: dict):
    """Attempt IBKR connection."""
    try:
        from income_desk.broker.ibkr import connect_ibkr

        ibkr_cfg = cfg.get("ibkr", {})
        host = ibkr_cfg.get("host", "127.0.0.1")
        port = ibkr_cfg.get("port", 7497)
        client_id = ibkr_cfg.get("client_id", 1)

        md, mm, acct, wl = connect_ibkr(host=host, port=port, client_id=client_id)
        if acct is not None:
            bal = acct.get_balance()
            print(_styled(
                f"Broker connected: IBKR {bal.account_number} ${bal.net_liquidating_value:,.0f}", "green",
            ))
        return md, mm, acct, wl
    except ImportError:
        return None, None, None, None
    except Exception as e:
        print(_styled(f"IBKR unavailable: {e}", "yellow"))
        return None, None, None, None


# ------------------------------------------------------------------
# Credential presence checks (fast, no connection attempt)
# ------------------------------------------------------------------

def _has_tastytrade_creds(cfg: dict) -> bool:
    import os
    return bool(
        os.environ.get("TASTYTRADE_CLIENT_SECRET_LIVE")
        or os.environ.get("TASTYTRADE_CLIENT_SECRET_PAPER")
        or os.environ.get("TASTYTRADE_CLIENT_SECRET_DATA")
        or cfg.get("broker", {})
    )


def _has_alpaca_creds(cfg: dict) -> bool:
    import os
    return bool(
        (os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_API_SECRET"))
        or (cfg.get("alpaca", {}).get("api_key") and cfg.get("alpaca", {}).get("api_secret"))
    )


def _has_schwab_creds(cfg: dict) -> bool:
    import os
    return bool(
        (os.environ.get("SCHWAB_APP_KEY") and os.environ.get("SCHWAB_APP_SECRET"))
        or (cfg.get("schwab", {}).get("app_key") and cfg.get("schwab", {}).get("app_secret"))
    )


def _has_ibkr_config(cfg: dict) -> bool:
    return bool(cfg.get("ibkr"))


def _has_dhan_creds(cfg: dict) -> bool:
    import os
    return bool(
        (os.environ.get("DHAN_CLIENT_ID") and os.environ.get("DHAN_ACCESS_TOKEN"))
        or (cfg.get("dhan", {}).get("client_id") and cfg.get("dhan", {}).get("access_token"))
    )


def add_broker_args(parser) -> None:
    """Add standard --broker flag to an argparse parser."""
    parser.add_argument(
        "--broker",
        action="store_true",
        help="Connect to broker for live quotes/Greeks (auto-detects from broker.yaml)",
    )
    parser.add_argument(
        "--paper",
        action="store_true",
        help="Use paper trading account (with --broker)",
    )
    parser.add_argument(
        "--broker-type",
        dest="broker_type",
        default=None,
        choices=["tastytrade", "alpaca", "schwab", "ibkr", "zerodha", "dhan"],
        help="Force a specific broker (overrides broker.yaml broker_type)",
    )
