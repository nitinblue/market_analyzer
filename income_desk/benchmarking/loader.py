"""Load prediction and outcome data from files for benchmarking."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from income_desk.benchmarking.models import OutcomeRecord, PredictionRecord


def load_predictions(source: str, path: str) -> list[PredictionRecord]:
    """Load predictions from file.

    Args:
        source: "file" (only supported source for now)
        path: path to JSON or CSV file
    """
    p = Path(path)
    if not p.exists():
        return []

    if p.suffix == ".json":
        data = json.loads(p.read_text())
        if isinstance(data, list):
            return [PredictionRecord(**item) for item in data]
        return []

    if p.suffix == ".csv":
        records = []
        with open(p) as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Convert numeric fields
                for field in [
                    "regime_id",
                    "regime_confidence",
                    "pop_pct",
                    "composite_score",
                    "iv_rank",
                    "entry_credit",
                ]:
                    if field in row and row[field]:
                        try:
                            row[field] = float(row[field])
                            if field == "regime_id":
                                row[field] = int(row[field])
                        except ValueError:
                            pass
                records.append(PredictionRecord(**row))
        return records

    return []


def load_outcomes(source: str, path: str) -> list[OutcomeRecord]:
    """Load outcomes from file. Same format support as predictions."""
    p = Path(path)
    if not p.exists():
        return []

    if p.suffix == ".json":
        data = json.loads(p.read_text())
        if isinstance(data, list):
            return [OutcomeRecord(**item) for item in data]
        return []

    if p.suffix == ".csv":
        records = []
        with open(p) as f:
            reader = csv.DictReader(f)
            for row in reader:
                for field in ["pnl", "holding_days"]:
                    if field in row and row[field]:
                        try:
                            row[field] = float(row[field])
                            if field == "holding_days":
                                row[field] = int(row[field])
                        except ValueError:
                            pass
                if "is_win" in row:
                    row["is_win"] = row["is_win"].lower() in ("true", "1", "yes")
                if "regime_persisted" in row:
                    val = row["regime_persisted"]
                    row["regime_persisted"] = (
                        val.lower() in ("true", "1", "yes") if val else None
                    )
                if "regime_at_exit" in row and row["regime_at_exit"]:
                    try:
                        row["regime_at_exit"] = int(row["regime_at_exit"])
                    except ValueError:
                        row["regime_at_exit"] = None
                records.append(OutcomeRecord(**row))
        return records

    return []
