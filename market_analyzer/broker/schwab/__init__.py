"""Charles Schwab broker integration — optional sub-package.

Requires ``schwab-py`` SDK: ``pip install 'market-analyzer[schwab]'``

Schwab acquired TD Ameritrade. The schwab-py library is the
community-maintained successor to ``td-ameritrade-python-api``.

First-time OAuth setup::

    import schwab
    schwab.auth.easy_client(
        api_key="YOUR_APP_KEY",
        app_secret="YOUR_APP_SECRET",
        callback_url="https://127.0.0.1",
        token_path=str(Path.home() / ".market_analyzer" / "schwab_token.json"),
    )

Usage::

    from market_analyzer.broker.schwab import connect_schwab

    market_data, metrics, account, _ = connect_schwab()
    ma = MarketAnalyzer(data_service=DataService(),
                        market_data=market_data, market_metrics=metrics,
                        account_provider=account)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_analyzer.broker.schwab.account import SchwabAccount
    from market_analyzer.broker.schwab.market_data import SchwabMarketData
    from market_analyzer.broker.schwab.metrics import SchwabMetrics

logger = logging.getLogger(__name__)


def connect_schwab(
    app_key: str | None = None,
    app_secret: str | None = None,
    token_path: str | None = None,
    callback_url: str = "https://127.0.0.1",
) -> tuple[SchwabMarketData | None, SchwabMetrics | None, SchwabAccount | None, None]:
    """Connect to Charles Schwab API.

    Credentials resolved in order:
    1. Explicit arguments
    2. Environment variables ``SCHWAB_APP_KEY`` / ``SCHWAB_APP_SECRET``
    3. ``~/.market_analyzer/broker.yaml`` under the ``schwab`` key

    Token file resolved in order:
    1. Explicit ``token_path`` argument
    2. ``~/.market_analyzer/schwab_token.json``

    First-time use requires OAuth2 flow. Run::

        import schwab
        schwab.auth.easy_client(app_key, app_secret, callback_url, token_path)

    Args:
        app_key: Schwab app key (from developer.schwab.com).
        app_secret: Schwab app secret.
        token_path: Path to OAuth2 token JSON file.
        callback_url: OAuth2 callback URL registered with Schwab.

    Returns:
        4-tuple ``(MarketDataProvider, MarketMetricsProvider, AccountProvider, None)``.

    Raises:
        ImportError: If ``schwab-py`` is not installed.
        ValueError: If credentials are missing.
        ConnectionError: If authentication fails.
    """
    try:
        import schwab  # type: ignore[import]  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "schwab-py is not installed. Run: pip install 'market-analyzer[schwab]'"
        ) from exc

    import schwab as _schwab
    from market_analyzer.broker.schwab.account import SchwabAccount
    from market_analyzer.broker.schwab.market_data import SchwabMarketData
    from market_analyzer.broker.schwab.metrics import SchwabMetrics

    key, secret = _resolve_credentials(app_key, app_secret)

    if not key or not secret:
        raise ValueError(
            "Schwab app_key and app_secret required.\n"
            "Register at: https://developer.schwab.com/\n"
            "Then set SCHWAB_APP_KEY and SCHWAB_APP_SECRET environment variables."
        )

    tok = token_path or os.environ.get(
        "SCHWAB_TOKEN_PATH",
        str(Path.home() / ".market_analyzer" / "schwab_token.json"),
    )

    try:
        client = _schwab.auth.client_from_token_file(tok, key, secret)
    except FileNotFoundError as exc:
        raise ConnectionError(
            f"Schwab token file not found: {tok}\n"
            "Run the OAuth setup first:\n"
            "  import schwab\n"
            f"  schwab.auth.easy_client('{key}', '<secret>', '{callback_url}', '{tok}')"
        ) from exc
    except Exception as exc:
        raise ConnectionError(
            f"Schwab authentication failed: {exc}\n"
            "Token may be expired. Re-run the OAuth setup."
        ) from exc

    return (
        SchwabMarketData(client),
        SchwabMetrics(client),
        SchwabAccount(client),
        None,  # No watchlist provider
    )


def _resolve_credentials(
    app_key: str | None,
    app_secret: str | None,
) -> tuple[str, str]:
    """Resolve Schwab credentials from args, env vars, or config file."""
    key = app_key or os.environ.get("SCHWAB_APP_KEY", "")
    secret = app_secret or os.environ.get("SCHWAB_APP_SECRET", "")

    if key and secret:
        return key, secret

    # Try broker.yaml
    config_path = Path.home() / ".market_analyzer" / "broker.yaml"
    if config_path.exists():
        try:
            import yaml
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
            schwab_cfg = cfg.get("schwab", {})
            key = key or schwab_cfg.get("app_key", "")
            secret = secret or schwab_cfg.get("app_secret", "")
        except Exception:
            pass

    return key, secret
