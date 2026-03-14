"""Models for calculation transparency — commentary and data gap identification."""

from __future__ import annotations

from pydantic import BaseModel


class DataGap(BaseModel):
    """A known gap in the analysis — where data is missing or assumptions are used."""

    field: str           # Which output field is affected
    reason: str          # Why it's a gap (e.g., "broker not connected")
    impact: str          # How this affects the output (e.g., "POP may be off by 10-15%")
    affects: str = ""    # What this impacts (e.g., "POP estimate", "entry timing")
