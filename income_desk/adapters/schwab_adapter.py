"""Charles Schwab adapter skeleton — implement with schwab-py.

This is a TEMPLATE. Users need to:

1. ``pip install schwab-py``
2. Complete OAuth2 flow (first time) to obtain a token
3. Fill in the ``get_option_chain``, ``get_quotes``, ``get_greeks`` methods

Schwab acquired TD Ameritrade and replaced thinkorswim's API.
The ``schwab-py`` library is the community-maintained successor to
``td-ameritrade-python-api``.

Usage::

    from income_desk.adapters.schwab_adapter import SchwabMarketData
    from income_desk import MarketAnalyzer, DataService

    md = SchwabMarketData(
        api_key="YOUR_API_KEY",
        app_secret="YOUR_APP_SECRET",
        token_path="/path/to/token.json",
    )
    ma = MarketAnalyzer(data_service=DataService(), market_data=md)

OAuth2 first-time setup::

    import schwab
    schwab.auth.easy_client(
        api_key="YOUR_API_KEY",
        app_secret="YOUR_APP_SECRET",
        callback_url="https://127.0.0.1",
        token_path="/path/to/token.json",
    )
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from income_desk.broker.base import MarketDataProvider
from income_desk.models.quotes import OptionQuote

if TYPE_CHECKING:
    from income_desk.models.opportunity import LegSpec


class SchwabMarketData(MarketDataProvider):
    """Charles Schwab market data via schwab-py.

    **TEMPLATE** — fill in with your Schwab connection.

    Requirements:
    - ``pip install schwab-py``
    - API key + app secret from https://developer.schwab.com/
    - OAuth2 token file (generated on first run via ``schwab.auth.easy_client``)
    """

    def __init__(
        self,
        api_key: str,
        app_secret: str,
        token_path: str,
        callback_url: str = "https://127.0.0.1",
    ) -> None:
        self._api_key = api_key
        self._app_secret = app_secret
        self._token_path = token_path
        self._callback_url = callback_url
        self._client = None  # schwab.Client instance (lazy connect)

    @property
    def provider_name(self) -> str:
        return "schwab"

    # ------------------------------------------------------------------
    # MarketDataProvider interface — implement these three methods
    # ------------------------------------------------------------------

    def get_option_chain(
        self, ticker: str, expiration: date | None = None
    ) -> list[OptionQuote]:
        """Fetch full option chain from Schwab.

        Implementation sketch using schwab-py::

            resp = self._client.get_option_chain(
                ticker,
                from_date=expiration,
                to_date=expiration,
                option_type=schwab.Client.Options.Type.ALL,
            )
            data = resp.json()
            # data["callExpDateMap"] and data["putExpDateMap"]
            # key format: "YYYY-MM-DD:DTE"
            # value: list of strike dicts with bid/ask/delta/etc.
        """
        self._connect()
        raise NotImplementedError(
            "Schwab adapter is a template. Implement get_option_chain() "
            "using schwab-py. See: https://schwab-py.readthedocs.io/"
        )

    def get_quotes(
        self,
        legs: list[LegSpec],
        *,
        ticker: str = "",
        include_greeks: bool = True,
    ) -> list[OptionQuote]:
        """Fetch quotes for specific option legs.

        Implementation sketch::

            # Build OCC symbols: SPY  260424C00580000
            symbols = [self._to_occ(ticker, leg) for leg in legs]
            resp = self._client.get_quotes(symbols)
            data = resp.json()
            # Each key is an OCC symbol; value has bid/ask/mark/Greeks
        """
        self._connect()
        raise NotImplementedError(
            "Schwab adapter is a template. Implement get_quotes() "
            "using schwab-py."
        )

    def get_greeks(self, legs: list[LegSpec]) -> dict[str, dict]:
        """Fetch Greeks for specific option legs.

        Schwab quote responses include ``delta``, ``gamma``, ``theta``,
        ``vega`` directly in the quote object.
        """
        self._connect()
        raise NotImplementedError(
            "Schwab adapter is a template. Implement get_greeks() "
            "using schwab-py."
        )

    # ------------------------------------------------------------------
    # Market properties for US equities (override if needed)
    # ------------------------------------------------------------------

    @property
    def currency(self) -> str:
        return "USD"

    @property
    def timezone(self) -> str:
        return "US/Eastern"

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        """Lazily connect to Schwab API using stored token."""
        if self._client is not None:
            return
        try:
            import schwab  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "schwab-py is not installed. Run: pip install schwab-py"
            ) from exc
        try:
            self._client = schwab.auth.client_from_token_file(
                self._token_path,
                api_key=self._api_key,
                app_secret=self._app_secret,
            )
        except Exception as exc:
            self._client = None
            raise ConnectionError(
                f"Schwab authentication failed: {exc}. "
                "Run schwab.auth.easy_client() to generate a token file."
            ) from exc

    @staticmethod
    def _to_occ(ticker: str, leg) -> str:
        """Convert a LegSpec to an OCC option symbol.

        OCC format: ``SPY   260424C00580000``
        (6-char padded ticker, YYMMDD, C/P, 8-digit strike * 1000)
        """
        exp = leg.expiration
        padded = ticker.ljust(6)
        yymmdd = exp.strftime("%y%m%d")
        cp = "C" if leg.option_type == "call" else "P"
        strike_int = int(leg.strike * 1000)
        return f"{padded}{yymmdd}{cp}{strike_int:08d}"
