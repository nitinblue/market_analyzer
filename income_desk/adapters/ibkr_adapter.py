"""Interactive Brokers adapter skeleton — implement with ib_insync.

This is a TEMPLATE. Users need to:

1. ``pip install ib_insync``
2. Have TWS or IB Gateway running
3. Fill in the ``get_option_chain``, ``get_quotes``, ``get_greeks`` methods

Usage::

    from income_desk.adapters.ibkr_adapter import IBKRMarketData
    from income_desk import MarketAnalyzer, DataService

    md = IBKRMarketData(host="127.0.0.1", port=7497, client_id=1)
    ma = MarketAnalyzer(data_service=DataService(), market_data=md)
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from income_desk.broker.base import MarketDataProvider
from income_desk.models.quotes import OptionQuote

if TYPE_CHECKING:
    from income_desk.models.opportunity import LegSpec


class IBKRMarketData(MarketDataProvider):
    """Interactive Brokers market data via ib_insync.

    **TEMPLATE** — fill in with your IB connection.

    Requirements:
    - ``pip install ib_insync``
    - TWS or IB Gateway running (default: localhost:7497 for paper, 7496 for live)

    Common ports:
    - TWS paper trading: 7497
    - TWS live trading:  7496
    - IB Gateway paper:  4002
    - IB Gateway live:   4001
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 1,
    ) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._ib = None  # ib_insync.IB instance (lazy connect)

    @property
    def provider_name(self) -> str:
        return "ibkr"

    # ------------------------------------------------------------------
    # MarketDataProvider interface — implement these three methods
    # ------------------------------------------------------------------

    def get_option_chain(
        self, ticker: str, expiration: date | None = None
    ) -> list[OptionQuote]:
        """Fetch full option chain from IBKR.

        Implementation sketch using ib_insync::

            from ib_insync import Stock, Option
            underlying = Stock(ticker, "SMART", "USD")
            chains = self._ib.reqSecDefOptParams(
                ticker, "", underlying.secType, underlying.conId
            )
            for chain in chains:
                for exp in chain.expirations:
                    for strike in chain.strikes:
                        contract = Option(ticker, exp, strike, "C", "SMART")
                        self._ib.qualifyContracts(contract)
                        self._ib.reqMktData(contract)
        """
        self._connect()
        raise NotImplementedError(
            "IBKR adapter is a template. Implement get_option_chain() "
            "using ib_insync. See: https://ib-insync.readthedocs.io/"
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

            from ib_insync import Option
            results = []
            for leg in legs:
                exp_str = leg.expiration.strftime("%Y%m%d")
                contract = Option(ticker, exp_str, leg.strike,
                                  leg.option_type[0].upper(), "SMART")
                self._ib.qualifyContracts(contract)
                ticker_data = self._ib.reqMktData(contract, "", False, False)
                self._ib.sleep(0.1)
                results.append(OptionQuote(...))
            return results
        """
        self._connect()
        raise NotImplementedError(
            "IBKR adapter is a template. Implement get_quotes() "
            "using ib_insync."
        )

    def get_greeks(self, legs: list[LegSpec]) -> dict[str, dict]:
        """Fetch Greeks for specific option legs.

        IBKR provides Greeks via ``reqMktData`` with generic tick types.
        """
        self._connect()
        raise NotImplementedError(
            "IBKR adapter is a template. Implement get_greeks() "
            "using ib_insync."
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
        """Lazily connect to TWS / IB Gateway."""
        if self._ib is not None:
            return
        try:
            from ib_insync import IB  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "ib_insync is not installed. Run: pip install ib_insync"
            ) from exc
        try:
            self._ib = IB()
            self._ib.connect(self._host, self._port, self._client_id)
        except Exception as exc:
            self._ib = None
            raise ConnectionError(
                f"IBKR connection failed ({self._host}:{self._port}): {exc}"
            ) from exc

    def disconnect(self) -> None:
        """Disconnect from TWS / IB Gateway."""
        if self._ib is not None:
            try:
                self._ib.disconnect()
            finally:
                self._ib = None
