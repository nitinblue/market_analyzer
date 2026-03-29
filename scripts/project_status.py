#!/usr/bin/env python3
"""Project status — scan all managed documents and report health.

Usage:
    python scripts/project_status.py
    python scripts/project_status.py --items     # show all items
    python scripts/project_status.py --stale     # show only stale/aging items
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, date
from pathlib import Path

from tabulate import tabulate

MEMORY_DIR = Path.home() / ".claude" / "projects" / "C--Users-nitin-PythonProjects-income-desk" / "memory"
DOCS_DIR = Path(__file__).parent.parent / "docs"

STALENESS_DAYS = {"FRESH": 3, "AGING": 7}


def _age_to_staleness(age_days: int) -> str:
    if age_days <= STALENESS_DAYS["FRESH"]:
        return "FRESH"
    if age_days <= STALENESS_DAYS["AGING"]:
        return "AGING"
    return "STALE"


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def parse_intake(path: Path) -> dict:
    """Parse an _intake.md file."""
    text = path.read_text(encoding="utf-8")
    items = []
    in_table = False

    for line in text.splitlines():
        if "| Key |" in line:
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            cols = [c.strip() for c in line.split("|") if c.strip()]
            if len(cols) >= 5:
                added = _parse_date(cols[2])
                actioned = _parse_date(cols[3])
                age = (date.today() - actioned).days if actioned else 999
                # Handle both old (6-col) and new (9-col) formats
                items.append({
                    "key": cols[0],
                    "item": cols[1][:50],
                    "added": cols[2].strip(),
                    "last_actioned": cols[3].strip(),
                    "age_days": age,
                    "staleness": _age_to_staleness(age),
                    "status": cols[4],
                    "assignee": cols[5] if len(cols) > 5 else "",
                    "next_action": cols[6][:40] if len(cols) > 6 else "",
                    "blockers": cols[7] if len(cols) > 7 else "",
                    "delivered_to": cols[8] if len(cols) > 8 else (cols[5] if len(cols) == 6 else ""),
                })
        elif in_table and not line.startswith("|"):
            in_table = False

    active = [i for i in items if i["status"] not in ("DELIVERED",)]
    if not active:
        doc_staleness = "DRAINED"
    elif any(i["staleness"] == "STALE" for i in active):
        doc_staleness = "STALE"
    elif any(i["staleness"] == "AGING" for i in active):
        doc_staleness = "AGING"
    else:
        doc_staleness = "FRESH"

    return {"path": path.name, "type": "INTAKE", "staleness": doc_staleness, "items": items}


def parse_living(path: Path) -> dict:
    """Parse a _living.md file by header date."""
    text = path.read_text(encoding="utf-8")
    match = re.search(r"Last (?:reviewed|updated):\s*(\d{4}-\d{2}-\d{2})", text)
    reviewed = _parse_date(match.group(1)) if match else None
    age = (date.today() - reviewed).days if reviewed else 999
    return {
        "path": path.name,
        "type": "LIVING",
        "staleness": _age_to_staleness(age),
        "reviewed": match.group(1) if match else "unknown",
        "age_days": age,
        "items": [],
    }


def parse_info(path: Path) -> dict:
    """Parse an _info.md file by header date."""
    text = path.read_text(encoding="utf-8")
    match = re.search(r"Last updated:\s*(\d{4}-\d{2}-\d{2})", text)
    updated = match.group(1) if match else "unknown"
    return {"path": path.name, "type": "INFO", "updated": updated, "items": []}


def main():
    parser = argparse.ArgumentParser(description="Project status dashboard")
    parser.add_argument("--items", action="store_true", help="Show all intake items")
    parser.add_argument("--stale", action="store_true", help="Show only stale/aging items")
    args = parser.parse_args()

    print(f"\n{'=' * 80}")
    print(f"  PROJECT STATUS — {date.today()}")
    print(f"{'=' * 80}\n")

    # ── Collect all files ──

    intake_docs = []
    if MEMORY_DIR.exists():
        for p in sorted(MEMORY_DIR.glob("*_intake.md")):
            intake_docs.append(parse_intake(p))

    living_docs = []
    if DOCS_DIR.exists():
        for p in sorted(DOCS_DIR.glob("*_living.md")):
            living_docs.append(parse_living(p))

    info_docs = []
    if MEMORY_DIR.exists():
        for p in sorted(MEMORY_DIR.glob("*_info.md")):
            info_docs.append(parse_info(p))

    # ── Table 1: All Documents ──

    doc_rows = []
    for d in intake_docs:
        total = len(d["items"])
        active = len([i for i in d["items"] if i["status"] not in ("DELIVERED",)])
        doc_rows.append([d["path"], "INTAKE", d["staleness"], total, active, ""])
    for d in living_docs:
        doc_rows.append([d["path"], "LIVING", d["staleness"], "", "", f"reviewed {d['age_days']}d ago"])
    for d in info_docs:
        doc_rows.append([d["path"], "INFO", "", "", "", f"updated {d['updated']}"])

    print(tabulate(
        doc_rows,
        headers=["File", "Type", "Staleness", "Total", "Active", "Notes"],
        tablefmt="grid",
    ))
    print()

    # ── Table 2: Intake Items (all or stale only) ──

    all_items = []
    for d in intake_docs:
        for item in d["items"]:
            if item["status"] == "DELIVERED":
                continue
            all_items.append(item)

    if args.stale:
        show_items = [i for i in all_items if i["staleness"] in ("STALE", "AGING")]
        title = "STALE & AGING ITEMS"
    elif args.items:
        show_items = all_items
        title = "ALL ACTIVE ITEMS"
    else:
        show_items = [i for i in all_items if i["staleness"] in ("STALE", "AGING")]
        if not show_items:
            show_items = all_items[:10]  # show top 10 if nothing stale
        title = "ITEMS NEEDING ATTENTION" if any(i["staleness"] != "FRESH" for i in show_items) else "TOP ACTIVE ITEMS"

    if show_items:
        item_rows = [
            [
                i["key"],
                i["item"][:40],
                f"{i['age_days']}d",
                i["staleness"],
                i["status"],
                i.get("assignee", "")[:10],
                i.get("next_action", "")[:35],
                i.get("blockers", "")[:20] if i.get("blockers", "") not in ("", "-") else "",
            ]
            for i in show_items
        ]
        print(f"  {title}")
        print(tabulate(
            item_rows,
            headers=["Key", "Item", "Age", "Health", "Status", "Assignee", "Next Action", "Blockers"],
            tablefmt="grid",
        ))
        print()

    # ── Summary ──

    total_items = len(all_items)
    stale = sum(1 for i in all_items if i["staleness"] == "STALE")
    aging = sum(1 for i in all_items if i["staleness"] == "AGING")
    fresh = sum(1 for i in all_items if i["staleness"] == "FRESH")
    blocked = sum(1 for i in all_items if i["status"] == "BLOCKED")
    in_progress = sum(1 for i in all_items if i["status"] == "IN_PROGRESS")

    health = "HEALTHY" if stale == 0 else "NEEDS ATTENTION" if stale <= 2 else "UNHEALTHY"

    print(f"  {'-' * 40}")
    print(f"  Health:    {health}")
    print(f"  Items:     {total_items} active ({fresh} fresh, {aging} aging, {stale} stale)")
    print(f"  Pipeline:  {in_progress} in progress, {blocked} blocked")
    print(f"  Documents: {len(intake_docs)} intake, {len(living_docs)} living, {len(info_docs)} info")
    print()


if __name__ == "__main__":
    main()
