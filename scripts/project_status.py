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
    """Parse an _intake.md file.

    Table columns (9): Key, Item, Added, Last Actioned, Status, Assignee,
    Next Action, Blockers, Delivered To.
    Status values: OPEN, IN_PROGRESS, BLOCKED, CLOSED.
    """
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
                age_days = (date.today() - added).days if added else 999
                health_days = (date.today() - actioned).days if actioned else 999
                items.append({
                    "key": cols[0],
                    "item": cols[1][:50],
                    "added": cols[2].strip(),
                    "last_actioned": cols[3].strip(),
                    "age_days": age_days,
                    "health": _age_to_staleness(health_days),
                    "status": cols[4],
                    "assignee": cols[5] if len(cols) > 5 else "",
                    "next_action": cols[6][:40] if len(cols) > 6 else "",
                    "blockers": cols[7] if len(cols) > 7 else "",
                    "delivered_to": cols[8] if len(cols) > 8 else (cols[5] if len(cols) == 6 else ""),
                })
        elif in_table and not line.startswith("|"):
            in_table = False

    active = [i for i in items if i["status"] not in ("CLOSED",)]
    if not active:
        doc_staleness = "DRAINED"
    elif any(i["health"] == "STALE" for i in active):
        doc_staleness = "STALE"
    elif any(i["health"] == "AGING" for i in active):
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
    print(f"  PROJECT STATUS -- {date.today()}")
    print(f"{'=' * 80}")

    # ── Session Briefing (always first) ──

    obj_file = MEMORY_DIR / "objectives_info.md"
    us_pct, india_pct, blockers, checks_total = 0, 0, [], 0

    if obj_file.exists():
        obj_text = obj_file.read_text(encoding="utf-8")
        us_pass, india_pass = 0, 0
        in_checklist = False
        for line in obj_text.splitlines():
            if "| # |" in line and "Check" in line:
                in_checklist = True
                continue
            if in_checklist and line.startswith("|---"):
                continue
            if in_checklist and line.startswith("|"):
                cols = [c.strip() for c in line.split("|") if c.strip()]
                if len(cols) >= 4:
                    checks_total += 1
                    if "PASS" in cols[2]:
                        us_pass += 1
                    if "PASS" in cols[3]:
                        india_pass += 1
            elif in_checklist and not line.startswith("|"):
                in_checklist = False

        us_pct = (us_pass / checks_total * 100) if checks_total > 0 else 0
        india_pct = (india_pass / checks_total * 100) if checks_total > 0 else 0

        in_blockers = False
        for line in obj_text.splitlines():
            if "| Blocker |" in line:
                in_blockers = True
                continue
            if in_blockers and line.startswith("|---"):
                continue
            if in_blockers and line.startswith("|"):
                cols = [c.strip() for c in line.split("|") if c.strip()]
                if len(cols) >= 4 and cols[3] == "OPEN":
                    blockers.append({"blocker": cols[0][:40], "blocks": cols[1], "key": cols[2]})
            elif in_blockers and not line.startswith("|"):
                in_blockers = False

    # Find all intake items early
    _all_intake_items = []
    if MEMORY_DIR.exists():
        for p in sorted(MEMORY_DIR.glob("*_intake.md")):
            d = parse_intake(p)
            for item in d["items"]:
                if item["status"] != "CLOSED":
                    _all_intake_items.append(item)

    stale_items = [i for i in _all_intake_items if i["health"] == "STALE"]
    aging_items = [i for i in _all_intake_items if i["health"] == "AGING"]
    total_active = len(_all_intake_items)
    closed_all = sum(1 for dd in (parse_intake(p) for p in sorted(MEMORY_DIR.glob("*_intake.md"))) for i in dd["items"] if i["status"] == "CLOSED") if MEMORY_DIR.exists() else 0

    # ── Skin in the Game Score ──
    # Measures: is Claude driving toward objectives or doing busywork?
    # Factors: readiness %, stale count (penalty), blocker resolution, closed items
    skin_score = 0
    skin_max = 100
    # Readiness progress (40 points max)
    skin_score += (us_pct + india_pct) / 2 * 0.4
    # No stale items (20 points max, lose 5 per stale)
    skin_score += max(0, 20 - len(stale_items) * 5)
    # Blocker resolution (20 points max)
    if checks_total > 0:
        total_blockers_possible = checks_total  # max theoretical blockers
        resolved = total_blockers_possible - len(blockers)
        skin_score += (resolved / total_blockers_possible) * 20
    # Closed items ratio (20 points max)
    if total_active + closed_all > 0:
        skin_score += (closed_all / (total_active + closed_all)) * 20

    skin_score = min(skin_score, skin_max)

    if skin_score >= 80:
        skin_label = "STRONG"
    elif skin_score >= 50:
        skin_label = "MODERATE"
    elif skin_score >= 25:
        skin_label = "WEAK"
    else:
        skin_label = "NONE"

    print()
    print(f"  SKIN IN THE GAME:  {skin_score:.0f}/100 ({skin_label})")
    print(f"  READINESS:         US {us_pct:.0f}%  |  India {india_pct:.0f}%  ({checks_total} checks)")
    print(f"  BLOCKERS:          {len(blockers)} open blockers to go-live")

    if stale_items:
        print(f"  STALE:             {len(stale_items)} items (Claude's failure -- action immediately)")
    elif aging_items:
        print(f"  AGING:             {len(aging_items)} items approaching stale")
    else:
        print(f"  HEALTH:            All items fresh")

    # Recommended focus: highest-priority blocker that blocks most objectives
    go_live_blockers = [b for b in blockers if "OBJ-1" in b["blocks"] or "OBJ-2" in b["blocks"]]
    if go_live_blockers:
        top = go_live_blockers[0]
        print(f"  FOCUS:      {top['key']} -- {top['blocker']} (blocks {top['blocks']})")

    print(f"\n{'-' * 80}\n")

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
        active = len([i for i in d["items"] if i["status"] not in ("CLOSED",)])
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
            if item["status"] == "CLOSED":
                continue
            all_items.append(item)

    if args.stale:
        show_items = [i for i in all_items if i["health"] in ("STALE", "AGING")]
        title = "STALE & AGING ITEMS"
    elif args.items:
        show_items = all_items
        title = "ALL ACTIVE ITEMS"
    else:
        show_items = [i for i in all_items if i["health"] in ("STALE", "AGING")]
        if not show_items:
            show_items = all_items[:10]  # show top 10 if nothing stale
        title = "ITEMS NEEDING ATTENTION" if any(i["health"] != "FRESH" for i in show_items) else "TOP ACTIVE ITEMS"

    if show_items:
        item_rows = [
            [
                i["key"],
                i["item"][:40],
                f"{i['age_days']}d",
                i["health"],
                i["status"],
                i.get("assignee", "")[:10],
                i.get("next_action", "")[:35],
                i.get("blockers", "")[:20] if i.get("blockers", "") not in ("", "-", "\u2014") else "",
            ]
            for i in show_items
        ]
        print(f"  {title}")
        print(tabulate(
            item_rows,
            headers=["Key", "Item", "Age(d)", "Health", "Status", "Assignee", "Next Action", "Blockers"],
            tablefmt="grid",
        ))
        print()

    # ── Business Objectives ──

    if blockers:
        print(f"  BUSINESS OBJECTIVES")
        print(tabulate(
            [
                ["OBJ-1", "Go live US", f"{us_pct:.0f}%", f"{us_pass}/{checks_total} checks", "P0"],
                ["OBJ-2", "Go live India", f"{india_pct:.0f}%", f"{india_pass}/{checks_total} checks", "P0"],
            ],
            headers=["ID", "Objective", "Readiness", "Progress", "Priority"],
            tablefmt="grid",
        ))
        print()

        print(f"  KEY BLOCKERS")
        blocker_rows = [[b["key"], b["blocker"], b["blocks"]] for b in blockers]
        print(tabulate(
            blocker_rows,
            headers=["Key", "Blocker", "Blocks"],
            tablefmt="grid",
        ))
        print()

    # ── Summary ──

    total_items = len(all_items)
    stale = sum(1 for i in all_items if i["health"] == "STALE")
    aging = sum(1 for i in all_items if i["health"] == "AGING")
    fresh = sum(1 for i in all_items if i["health"] == "FRESH")
    n_open = sum(1 for i in all_items if i["status"] == "OPEN")
    in_progress = sum(1 for i in all_items if i["status"] == "IN_PROGRESS")
    blocked = sum(1 for i in all_items if i["status"] == "BLOCKED")
    n_closed = sum(1 for d in intake_docs for i in d["items"] if i["status"] == "CLOSED")

    health = "HEALTHY" if stale == 0 else "NEEDS ATTENTION" if stale <= 2 else "UNHEALTHY"

    print(f"  {'-' * 40}")
    print(f"  Health:    {health}")
    print(f"  Items:     {n_open} open, {in_progress} in progress, {blocked} blocked, {n_closed} closed")
    print(f"  Staleness: {fresh} fresh, {aging} aging, {stale} stale")
    print(f"  Documents: {len(intake_docs)} intake, {len(living_docs)} living, {len(info_docs)} info")
    print()


if __name__ == "__main__":
    main()
