"""Models for calculation transparency — commentary and data gap identification."""

from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, computed_field


class FitnessCategory(StrEnum):
    """What this data is suitable for."""
    LIVE_EXECUTION = "live_execution"            # Real money trades
    PAPER_TRADING = "paper_trading"              # Simulated execution
    POSITION_MONITORING = "position_monitoring"  # Watching open positions
    RISK_ASSESSMENT = "risk_assessment"          # Portfolio-level risk
    SCREENING = "screening"                      # Finding trade candidates
    RESEARCH = "research"                        # What-if, regime study
    EDUCATION = "education"                      # Learning mechanics
    CALIBRATION = "calibration"                  # Recording outcomes, tuning
    ALERTING = "alerting"                        # Setting future alerts
    JOURNALING = "journaling"                    # Documenting decisions


class CalculationMode(StrEnum):
    """Controls what level of context MA expects and how missing inputs affect trust."""
    FULL = "full"              # Default: portfolio + position + risk aware
    STANDALONE = "standalone"  # Single trade analysis, no portfolio context expected


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

    @computed_field
    @property
    def fit_for(self) -> list[str]:
        """What this data is suitable for, based on trust score.

        Returns string values (not enums) for clean serialization via MCP/eTrading.
        """
        result: list[FitnessCategory] = [
            FitnessCategory.EDUCATION,
            FitnessCategory.JOURNALING,
        ]  # Always included

        if self.overall_trust >= 0.20:
            result.append(FitnessCategory.RESEARCH)
        if self.overall_trust >= 0.30:
            result.append(FitnessCategory.SCREENING)
        if self.overall_trust >= 0.50:
            result.extend([FitnessCategory.ALERTING, FitnessCategory.CALIBRATION])
        if self.overall_trust >= 0.60:
            result.append(FitnessCategory.PAPER_TRADING)
        if self.overall_trust >= 0.70:
            result.extend([FitnessCategory.POSITION_MONITORING, FitnessCategory.RISK_ASSESSMENT])
        if self.overall_trust >= 0.80:
            result.append(FitnessCategory.LIVE_EXECUTION)

        return [c.value for c in result]

    @computed_field
    @property
    def fit_for_summary(self) -> str:
        """One-line summary of fitness: what it IS and is NOT suitable for."""
        cat_values = set(self.fit_for)
        cats = {FitnessCategory(v) for v in cat_values}

        if FitnessCategory.LIVE_EXECUTION in cats:
            return "Fit for ALL purposes including live execution"

        fit_str = ", ".join(list(cat_values)[:4])  # Top 4

        all_cats = list(FitnessCategory)
        not_fit_important = [
            c.value for c in all_cats
            if c not in cats and c.value in (
                "live_execution", "position_monitoring", "risk_assessment"
            )
        ]

        if not_fit_important:
            return f"Fit for: {fit_str}. NOT fit for: {', '.join(not_fit_important)}"
        return f"Fit for: {fit_str}"
