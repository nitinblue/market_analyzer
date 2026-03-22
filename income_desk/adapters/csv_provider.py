"""CSV file data provider — load OHLCV from local files.

Usage:
    from income_desk.adapters.csv_provider import CSVProvider
    from income_desk import MarketAnalyzer, DataService

    ds = DataService()
    ds._registry.register_priority(CSVProvider("/path/to/data/"))
    ma = MarketAnalyzer(data_service=ds)

    # Now ma.regime.detect("SPY") reads from /path/to/data/SPY.csv
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from income_desk.data.providers.base import DataProvider
from income_desk.models.data import DataRequest, DataType, ProviderType


class CSVProvider(DataProvider):
    """Read OHLCV data from CSV files. One file per ticker.

    Expected CSV format::

        Date,Open,High,Low,Close,Volume
        2024-01-02,472.65,473.50,471.00,472.00,50000000

    File naming: ``{data_dir}/{TICKER}.csv`` (e.g., /data/SPY.csv)

    Column names are normalised automatically — any reasonable variant of
    open/high/low/close/volume is accepted (case-insensitive, common
    abbreviations like ``o``, ``h``, ``l``, ``c``, ``vol`` all work).
    """

    def __init__(self, data_dir: str | Path) -> None:
        self._dir = Path(data_dir)

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.CSV

    @property
    def supported_data_types(self) -> list[DataType]:
        return [DataType.OHLCV]

    def fetch(self, request: DataRequest) -> pd.DataFrame:
        path = self._dir / f"{request.ticker}.csv"
        if not path.exists():
            from income_desk.data.exceptions import DataFetchError
            raise DataFetchError(
                "csv", request.ticker, f"File not found: {path}"
            )

        df = pd.read_csv(path, index_col=0, parse_dates=True)

        # Normalise column names to Open/High/Low/Close/Volume
        col_map: dict[str, str] = {}
        for col in df.columns:
            lower = col.lower().strip()
            if lower in ("open", "o"):
                col_map[col] = "Open"
            elif lower in ("high", "h"):
                col_map[col] = "High"
            elif lower in ("low", "l"):
                col_map[col] = "Low"
            elif lower in ("close", "c", "adj close", "adj_close"):
                col_map[col] = "Close"
            elif lower in ("volume", "vol", "v"):
                col_map[col] = "Volume"
        df = df.rename(columns=col_map)

        # Filter by date range when requested
        if request.start_date:
            df = df[df.index >= pd.Timestamp(request.start_date)]
        if request.end_date:
            df = df[df.index <= pd.Timestamp(request.end_date)]

        return df

    def validate_ticker(self, ticker: str) -> bool:
        return (self._dir / f"{ticker}.csv").exists()
