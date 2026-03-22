"""Maps (ticker, data_type) to the correct provider."""

from __future__ import annotations

from income_desk.data.exceptions import NoProviderError
from income_desk.data.providers.base import DataProvider
from income_desk.models.data import DataType


class ProviderRegistry:
    """Registry that resolves which provider handles a given (ticker, data_type).

    Resolution order:
    1. Providers registered with ``register_priority()`` are checked first
       (in registration order, ticker-validated first).
    2. Standard providers registered with ``register()`` are checked next.

    Within each group, if ``validate_ticker()`` returns True the provider is
    preferred over one that hasn't validated the ticker.
    """

    def __init__(self) -> None:
        self._providers: list[DataProvider] = []
        self._priority_providers: list[DataProvider] = []

    def register(self, provider: DataProvider) -> None:
        """Register a data provider (checked after priority providers)."""
        self._providers.append(provider)

    def register_priority(self, provider: DataProvider) -> None:
        """Register a data provider that is checked before standard providers.

        Use this for BYOD adapters (CSV, DataFrame, custom API) so they take
        precedence over the built-in yfinance provider for tickers they handle.
        """
        self._priority_providers.append(provider)

    def resolve(self, ticker: str, data_type: DataType) -> DataProvider:
        """Find the best provider for the given (ticker, data_type).

        Priority providers are checked first. Within each group, a provider
        that explicitly validates the ticker is preferred.
        """
        for group in (self._priority_providers, self._providers):
            # First pass: provider that supports the type AND validates ticker
            for provider in group:
                if data_type in provider.supported_data_types:
                    if provider.validate_ticker(ticker):
                        return provider
            # Second pass: provider that supports the type (no ticker check)
            for provider in group:
                if data_type in provider.supported_data_types:
                    return provider
        raise NoProviderError(data_type)
