#!/usr/bin/env python3
"""Project status — scan intake and living docs for staleness.

Usage:
    python scripts/project_status.py
"""
from __future__ import annotations

import re
from datetime import datetime, date
from pathlib import Path

MEMORY_DIR = Path.home() / ".claude" / "projects" / "C--Users-nitin-PythonProjects-income-desk" / "memory"
DOCS_DIR = Path(__file__).parent.parent / "docs"

STALENESS_THRESHOLDS = {
    "FRESH": 3,
    "AGING": 7,
    # 8+ = STALE
}


def parse_tracked_doc(path: Path) -> dict:
    """Parse a _intake.md or _living.md file and extract items with staleness."""
    text = path.read_text(encoding="utf-8")

    # Extract header staleness
    header_match = re.search(r"Staleness:\s*(\w+)", text)
    header_staleness = header_match.group(1) if header_match else "UNKNOWN"

    # Parse active items table
    items = []
    in_table = False
    for line in text.splitlines():
        if "| Key |" in line or "| # |" in line:
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            cols = [c.strip() for c in line.split("|") if c.strip()]
            if len(cols) >= 5:
                key = cols[0]
                item_desc = cols[1]
                added = cols[2]
                last_actioned = cols[3]
                status = cols[4]
                delivered = cols[5] if len(cols) > 5 else "—"

                # Calculate age
                try:
                    action_date = datetime.strptime(last_actioned.strip(), "%Y-%m-%d").date()
                    age_days = (date.today() - action_date).days
                except (ValueError, TypeError):
                    age_days = 999

                if age_days <= STALENESS_THRESHOLDS["FRESH"]:
                    item_staleness = "FRESH"
                elif age_days <= STALENESS_THRESHOLDS["AGING"]:
                    item_staleness = "AGING"
                else:
                    item_staleness = "STALE"

                items.append({
                    "key": key,
                    "description": item_desc[:50],
                    "age_days": age_days,
                    "staleness": item_staleness,
                    "status": status,
                    "delivered": delivered,
                })
        elif in_table and not line.startswith("|"):
            in_table = False

    # Compute document staleness from worst item
    if not items:
        doc_staleness = "DRAINED"
    else:
        active = [i for i in items if i["status"] not in ("DELIVERED", "DRAINED")]
        if not active:
            doc_staleness = "DRAINED"
        elif any(i["staleness"] == "STALE" for i in active):
            doc_staleness = "STALE"
        elif any(i["staleness"] == "AGING" for i in active):
            doc_staleness = "AGING"
        else:
            doc_staleness = "FRESH"

    return {
        "path": path.name,
        "staleness": doc_staleness,
        "items": items,
        "total": len(items),
        "stale_count": sum(1 for i in items if i["staleness"] == "STALE"),
        "aging_count": sum(1 for i in items if i["staleness"] == "AGING"),
        "fresh_count": sum(1 for i in items if i["staleness"] == "FRESH"),
    }


def main():
    print("\n" + "=" * 60)
    print("  PROJECT STATUS")
    print("=" * 60)
    print(f"  Date: {date.today()}")
    print()

    # Find intake docs in memory dir
    intake_files = []
    if MEMORY_DIR.exists():
        intake_files.extend(MEMORY_DIR.glob("*_intake.md"))

    # Find living docs in docs dir
    living_files = []
    if DOCS_DIR.exists():
        living_files.extend(DOCS_DIR.glob("*_living.md"))

    all_files = sorted(set(intake_files)) + sorted(set(living_files))

    if not all_files:
        print("  No intake or living documents found.")
        return

    total_items = 0
    total_stale = 0
    total_aging = 0

    # Report intake docs
    if intake_files:
        print("  --- Intake Documents (memory) ---")
        print()
        for path in sorted(intake_files):
            doc = parse_tracked_doc(path)
            total_items += doc["total"]
            total_stale += doc["stale_count"]
            total_aging += doc["aging_count"]

            icon = {"FRESH": "OK", "AGING": "!!", "STALE": "XX", "DRAINED": "--"}
            staleness = doc["staleness"]

            print(f"  [{icon.get(staleness, '??')}] {doc['path']}: {staleness}")
            print(f"       Items: {doc['total']} (FRESH:{doc['fresh_count']} AGING:{doc['aging_count']} STALE:{doc['stale_count']})")

            for item in doc["items"]:
                if item["staleness"] in ("STALE", "AGING"):
                    print(f"       {item['key']}: {item['description']} ({item['age_days']}d old, {item['status']})")
            print()

    # Report living docs (freshness by header date, not row items)
    if living_files:
        print("  --- Living Documents (docs/) ---")
        print()
        for path in sorted(living_files):
            text = path.read_text(encoding="utf-8")
            # Get freshness from "Last reviewed" or "Last updated" header
            date_match = re.search(r"Last (?:reviewed|updated):\s*(\d{4}-\d{2}-\d{2})", text)
            if date_match:
                try:
                    reviewed = datetime.strptime(date_match.group(1), "%Y-%m-%d").date()
                    age = (date.today() - reviewed).days
                except ValueError:
                    age = 999
            else:
                age = 999

            if age <= STALENESS_THRESHOLDS["FRESH"]:
                staleness = "FRESH"
            elif age <= STALENESS_THRESHOLDS["AGING"]:
                staleness = "AGING"
            else:
                staleness = "STALE"

            icon = {"FRESH": "OK", "AGING": "!!", "STALE": "XX"}
            print(f"  [{icon.get(staleness, '??')}] {path.name}: {staleness} (reviewed {age}d ago)")
            if staleness == "STALE":
                print(f"       ** Needs refresh — last reviewed {date_match.group(1) if date_match else 'unknown'} **")

            for item in doc["items"]:
                if item["staleness"] in ("STALE", "AGING"):
                    print(f"       {item['key']}: {item['description']} ({item['age_days']}d old, {item['status']})")
            print()

    # Summary
    print("-" * 60)
    health = "HEALTHY" if total_stale == 0 else "NEEDS ATTENTION" if total_stale <= 2 else "UNHEALTHY"
    print(f"  Health: {health}")
    print(f"  Total items: {total_items} | Stale: {total_stale} | Aging: {total_aging}")
    print(f"  Intake docs: {len(intake_files)} | Living docs: {len(living_files)}")
    print()


if __name__ == "__main__":
    main()
