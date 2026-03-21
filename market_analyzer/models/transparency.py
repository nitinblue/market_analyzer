"""Models for calculation transparency — commentary and data gap identification."""

from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel


class DataGap(BaseModel):
    """A known gap in the analysis — where data is missing or assumptions are used."""

    field: str           # Which output field is affected
    reason: str          # Why it's a gap (e.g., "broker not connected")
    impact: str          # How this affects the output (e.g., "POP may be off by 10-15%")
    affects: str = ""    # What this impacts (e.g., "POP estimate", "entry timing")


class DataSource(StrEnum):
    """Where data came from."""
    BROKER_LIVE = "broker_live"          # Real-time DXLink/broker API
    BROKER_CACHED = "broker_cached"      # Broker data but cached (may be stale)
    YFINANCE_LIVE = "yfinance_live"      # Fresh yfinance fetch
    YFINANCE_CACHED = "yfinance_cached"  # Cached yfinance data
    COMPUTED = "computed"                # Derived from other data (POP, regime, etc.)
    ESTIMATED = "estimated"              # Heuristic/approximation (no real data)
    NONE = "none"                        # Data unavailable


class TrustLevel(StrEnum):
    """Trust classification."""
    HIGH = "high"              # 0.80-1.00: broker live data, fresh
    MEDIUM = "medium"          # 0.50-0.79: computed from good inputs, or cached
    LOW = "low"                # 0.20-0.49: estimated, stale, or degraded
    UNRELIABLE = "unreliable"  # 0.00-0.19: missing critical inputs


class DegradedField(BaseModel):
    """A specific field that is degraded or estimated."""
    field: str
    source: DataSource
    reason: str


class DataTrust(BaseModel):
    """Trust factor for any MA output. Attach to every response."""
    trust_score: float          # 0.0-1.0
    trust_level: TrustLevel     # Classification
    primary_source: DataSource  # Main data source used
    degraded_fields: list[DegradedField] = []
    summary: str                # Human-readable summary

    @classmethod
    def from_score(
        cls,
        score: float,
        source: DataSource,
        degraded: list[DegradedField] | None = None,
    ) -> "DataTrust":
        """Build a DataTrust from a raw score and optional degraded field list."""
        score = max(0.0, min(1.0, score))
        if score >= 0.80:
            level = TrustLevel.HIGH
        elif score >= 0.50:
            level = TrustLevel.MEDIUM
        elif score >= 0.20:
            level = TrustLevel.LOW
        else:
            level = TrustLevel.UNRELIABLE

        degraded = degraded or []
        if degraded:
            summary = (
                f"{level.value} trust ({score:.0%}): {len(degraded)} field(s) degraded"
                f" — {', '.join(d.field for d in degraded[:3])}"
            )
        else:
            summary = f"{level.value} trust ({score:.0%}): {source.value}"

        return cls(
            trust_score=round(score, 2),
            trust_level=level,
            primary_source=source,
            degraded_fields=degraded,
            summary=summary,
        )


class ContextGap(BaseModel):
    """An optional input that was NOT provided by the caller."""
    parameter: str    # Parameter name (e.g., "levels", "iv_rank")
    impact: str       # What's degraded without it (e.g., "strike proximity check skipped")
    importance: str   # "critical", "important", "helpful"


class TrustReport(BaseModel):
    """Complete 2-dimensional trust assessment."""
    # Dimension 1: Data Quality
    data_quality: DataTrust

    # Dimension 2: Context Quality
    context_score: float            # 0-1
    context_level: TrustLevel       # HIGH/MEDIUM/LOW/UNRELIABLE
    context_gaps: list[ContextGap]  # What wasn't provided

    # Combined
    overall_trust: float    # min(data_quality.trust_score, context_score)
    overall_level: TrustLevel
    summary: str

    @property
    def is_actionable(self) -> bool:
        """Can the caller trust this enough to act on it?"""
        return self.overall_trust >= 0.50
