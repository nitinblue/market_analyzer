"""TastyTrade session — auth from env vars (preferred) or YAML.

Env var convention (same as eTrading .env):
    TASTYTRADE_CLIENT_SECRET_LIVE / TASTYTRADE_REFRESH_TOKEN_LIVE
    TASTYTRADE_CLIENT_SECRET_PAPER / TASTYTRADE_REFRESH_TOKEN_PAPER
    TASTYTRADE_CLIENT_SECRET_DATA / TASTYTRADE_REFRESH_TOKEN_DATA  (DXLink)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

from market_analyzer.broker.base import BrokerSession

logger = logging.getLogger(__name__)


class TastyTradeBrokerSession(BrokerSession):
    """TastyTrade session — env vars first, YAML fallback.

    Env vars (preferred, same as eTrading .env)::

        TASTYTRADE_CLIENT_SECRET_LIVE / TASTYTRADE_REFRESH_TOKEN_LIVE
        TASTYTRADE_CLIENT_SECRET_PAPER / TASTYTRADE_REFRESH_TOKEN_PAPER
        TASTYTRADE_CLIENT_SECRET_DATA / TASTYTRADE_REFRESH_TOKEN_DATA

    YAML fallback (``tastytrade_broker.yaml``)::

        broker:
          live:
            client_secret: ${TASTYTRADE_CLIENT_SECRET_LIVE}
            refresh_token: ${TASTYTRADE_REFRESH_TOKEN_LIVE}
          data:
            client_secret: ${TASTYTRADE_CLIENT_SECRET_DATA}
            refresh_token: ${TASTYTRADE_REFRESH_TOKEN_DATA}
    """

    def __init__(
        self,
        config_path: str = "tastytrade_broker.yaml",
        is_paper: bool = False,
        account_number: str | None = None,
    ) -> None:
        self._config_path = config_path
        self._is_paper = is_paper
        self._account_number = account_number

        # SDK objects (set on connect)
        self._session = None       # trading session
        self._data_session = None  # DXLink session (always live)
        self._account = None
        self._accounts: dict = {}
        self._connected = False

        # Credentials (loaded lazily)
        self._client_secret: str = ""
        self._refresh_token: str = ""
        self._paper_client_secret: str = ""
        self._paper_refresh_token: str = ""
        self._data_client_secret: str = ""
        self._data_refresh_token: str = ""

    # -- BrokerSession ABC --

    def connect(self) -> bool:
        """Authenticate and establish session. Returns True on success."""
        try:
            from tastytrade import Account, Session
        except ImportError:
            logger.error("tastytrade SDK not installed — pip install tastytrade")
            return False

        try:
            self._load_credentials()

            mode = "PAPER" if self._is_paper else "LIVE"
            logger.info("Connecting to TastyTrade | %s", mode)

            # Try trading creds (LIVE or PAPER), then DATA as fallback
            cred_attempts = [
                (self._client_secret, self._refresh_token, self._is_paper, mode),
            ]
            if self._data_client_secret and self._data_refresh_token:
                cred_attempts.append(
                    (self._data_client_secret, self._data_refresh_token, False, "DATA"),
                )
            if self._paper_client_secret and self._paper_refresh_token:
                cred_attempts.append(
                    (self._paper_client_secret, self._paper_refresh_token, True, "PAPER"),
                )

            for secret, token, is_test, label in cred_attempts:
                try:
                    self._session = Session(secret, token, is_test=is_test)
                    result = Account.get(self._session)
                    if asyncio.iscoroutine(result):
                        accounts = asyncio.run(result)
                    else:
                        accounts = result
                    if not isinstance(accounts, list):
                        accounts = [accounts]
                    self._accounts = {a.account_number: a for a in accounts}
                    logger.info("Authenticated via %s credentials", label)
                    break
                except Exception as e:
                    logger.warning("%s credentials failed: %s", label, e)
                    self._session = None
                    continue
            else:
                raise RuntimeError("All credential sets failed")

            if self._account_number:
                if self._account_number not in self._accounts:
                    raise ValueError(f"Account {self._account_number} not found")
                self._account = self._accounts[self._account_number]
            else:
                self._account = next(iter(self._accounts.values()))

            # DXLink data session — use DATA creds if available, else same as trading
            data_secret = self._data_client_secret or self._client_secret
            data_token = self._data_refresh_token or self._refresh_token
            self._data_session = Session(data_secret, data_token, is_test=False)

            self._connected = True
            logger.info("Authenticated with TastyTrade (account %s)", self._account.account_number)
            return True

        except Exception:
            logger.exception("TastyTrade authentication failed")
            return False

    def disconnect(self) -> None:
        self._session = None
        self._data_session = None
        self._account = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def broker_name(self) -> str:
        return "tastytrade"

    # -- TastyTrade-specific (not in ABC) --

    @property
    def sdk_session(self):
        """Trading session (paper or live)."""
        if not self._session:
            raise RuntimeError("Not connected — call connect() first")
        return self._session

    @property
    def data_session(self):
        """DXLink session (always live, for market data streaming)."""
        if not self._data_session:
            raise RuntimeError("Not connected — call connect() first")
        return self._data_session

    @property
    def account(self):
        if not self._account:
            raise RuntimeError("Not connected — call connect() first")
        return self._account

    # -- Credential loading --

    def _load_credentials(self) -> None:
        """Load all available credentials from env vars (preferred) or YAML.

        Loads LIVE, PAPER, and DATA credential sets. connect() tries them
        in order until one works.
        """
        # Load all three credential sets from env
        live_s = os.getenv("TASTYTRADE_CLIENT_SECRET_LIVE", "")
        live_t = os.getenv("TASTYTRADE_REFRESH_TOKEN_LIVE", "")
        paper_s = os.getenv("TASTYTRADE_CLIENT_SECRET_PAPER", "")
        paper_t = os.getenv("TASTYTRADE_REFRESH_TOKEN_PAPER", "")
        data_s = os.getenv("TASTYTRADE_CLIENT_SECRET_DATA", "")
        data_t = os.getenv("TASTYTRADE_REFRESH_TOKEN_DATA", "")

        if live_s or paper_s or data_s:
            # Primary = requested mode (LIVE or PAPER)
            if self._is_paper:
                self._client_secret = paper_s
                self._refresh_token = paper_t
            else:
                self._client_secret = live_s
                self._refresh_token = live_t
            self._paper_client_secret = paper_s
            self._paper_refresh_token = paper_t
            self._data_client_secret = data_s
            self._data_refresh_token = data_t
            logger.info("Credentials loaded from env vars")
            return

        # Fallback: YAML file
        self._load_credentials_from_yaml()

    def _load_credentials_from_yaml(self) -> None:
        """Fallback: load credentials from YAML file."""
        import yaml

        cred_path = self._find_config_file()
        if not cred_path:
            raise FileNotFoundError(
                "TastyTrade credentials not found. Set env vars "
                "(TASTYTRADE_CLIENT_SECRET_LIVE, TASTYTRADE_REFRESH_TOKEN_LIVE, "
                "TASTYTRADE_CLIENT_SECRET_DATA, TASTYTRADE_REFRESH_TOKEN_DATA) "
                f"or create '{self._config_path}'."
            )

        with open(cred_path) as f:
            creds = yaml.safe_load(f)

        mode = "paper" if self._is_paper else "live"
        mode_creds = creds["broker"][mode]

        self._client_secret = _resolve_env(mode_creds["client_secret"])
        self._refresh_token = _resolve_env(mode_creds["refresh_token"])

        data_section = creds["broker"].get("data") or creds["broker"]["live"]
        self._data_client_secret = _resolve_env(data_section["client_secret"])
        self._data_refresh_token = _resolve_env(data_section["refresh_token"])

    def _find_config_file(self) -> Path | None:
        """Search common locations for the credential YAML."""
        candidates = [
            Path(self._config_path),
            Path.home() / ".market_analyzer" / self._config_path,
            Path(__file__).parent / self._config_path,
            Path(__file__).parent.parent / self._config_path,
            Path(__file__).parent.parent.parent / self._config_path,
        ]
        for p in candidates:
            if p.exists():
                return p
        return None


class ExternalBrokerSession(BrokerSession):
    """Wraps pre-authenticated SDK sessions provided by the caller.

    Used in SaaS mode: eTrading authenticates with the broker and passes
    the sessions here.  market_analyzer never touches credentials.
    """

    def __init__(self, sdk_session, data_session) -> None:
        self._sdk_session = sdk_session
        self._data_session = data_session

    def connect(self) -> bool:
        return True  # already connected

    def disconnect(self) -> None:
        pass  # caller owns the session lifecycle

    @property
    def is_connected(self) -> bool:
        return self._sdk_session is not None

    @property
    def broker_name(self) -> str:
        return "tastytrade"

    @property
    def sdk_session(self):
        return self._sdk_session

    @property
    def data_session(self):
        return self._data_session


def _resolve_env(value: str) -> str:
    """Resolve ``${ENV_VAR}`` or ``$ENV_VAR`` patterns in a credential value."""
    if not value:
        return value
    match = re.match(r"\$\{?([A-Z_][A-Z0-9_]*)\}?", value)
    if match:
        env_var = match.group(1)
        resolved = os.getenv(env_var)
        if not resolved:
            raise ValueError(f"Environment variable {env_var} not set")
        return resolved
    return value
