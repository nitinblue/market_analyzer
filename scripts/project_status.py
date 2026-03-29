#!/usr/bin/env python3
"""Project status — executive dashboard for income_desk.

Usage:
    python scripts/project_status.py              # Executive summary + attention items
    python scripts/project_status.py --items      # Show all active items
    python scripts/project_status.py --stale      # Show only stale/aging items
    python scripts/project_status.py --docs       # Show document inventory
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, date
from pathlib import Path

from tabulate import tabulate

PROJECT_ROOT = Path(__file__).parent.parent

# Auto-discover memory dir: look for */memory/ with MEMORY.md inside
MEMORY_DIR = None
for d in sorted(PROJECT_ROOT.iterdir()):
    if d.is_dir() and (d / "memory" / "MEMORY.md").exists():
        MEMORY_DIR = d / "memory"
        break
if MEMORY_DIR is None:
    MEMORY_DIR = PROJECT_ROOT / "memory"  # fallback

DOCS_DIR = PROJECT_ROOT / "docs"

STALENESS_DAYS = {"FRESH": 3, "AGING": 7}


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

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
                items.append({
                    "key": cols[0],
                    "item": cols[1][:50],
                    "added": cols[2].strip(),
                    "last_actioned": cols[3].strip(),
                    "age_days": (date.today() - added).days if added else 999,
                    "health": _age_to_staleness((date.today() - actioned).days if actioned else 999),
                    "status": cols[4],
                    "assignee": cols[5] if len(cols) > 5 else "",
                    "next_action": cols[6][:40] if len(cols) > 6 else "",
                    "blockers": cols[7] if len(cols) > 7 else "",
                    "delivered_to": cols[8] if len(cols) > 8 else "",
                })
        elif in_table and not line.startswith("|"):
            in_table = False

    active = [i for i in items if i["status"] not in ("CLOSED",)]
    if not active:
        staleness = "DRAINED"
    elif any(i["health"] == "STALE" for i in active):
        staleness = "STALE"
    elif any(i["health"] == "AGING" for i in active):
        staleness = "AGING"
    else:
        staleness = "FRESH"
    return {"path": path.name, "type": "INTAKE", "staleness": staleness, "items": items}


def parse_living(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"Last (?:reviewed|updated):\s*(\d{4}-\d{2}-\d{2})", text)
    reviewed = _parse_date(match.group(1)) if match else None
    age = (date.today() - reviewed).days if reviewed else 999
    return {"path": path.name, "type": "LIVING", "staleness": _age_to_staleness(age),
            "reviewed": match.group(1) if match else "unknown", "age_days": age, "items": []}


def parse_info(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"Last updated:\s*(\d{4}-\d{2}-\d{2})", text)
    return {"path": path.name, "type": "INFO", "updated": match.group(1) if match else "unknown", "items": []}


def parse_objectives() -> dict:
    """Parse objectives_info.md for readiness checklist and blockers."""
    obj_file = MEMORY_DIR / "objectives_info.md"
    result = {"us_pass": 0, "india_pass": 0, "checks": 0, "blockers": [], "checklist": []}
    if not obj_file.exists():
        return result

    text = obj_file.read_text(encoding="utf-8")
    in_checklist = False
    for line in text.splitlines():
        if "| # |" in line and "Check" in line:
            in_checklist = True
            continue
        if in_checklist and line.startswith("|---"):
            continue
        if in_checklist and line.startswith("|"):
            cols = [c.strip() for c in line.split("|") if c.strip()]
            if len(cols) >= 4:
                result["checks"] += 1
                if "PASS" in cols[2]:
                    result["us_pass"] += 1
                if "PASS" in cols[3]:
                    result["india_pass"] += 1
                result["checklist"].append({
                    "check": cols[1][:45], "us": cols[2], "india": cols[3],
                })
        elif in_checklist and not line.startswith("|"):
            in_checklist = False

    in_blockers = False
    for line in text.splitlines():
        if "| Blocker |" in line:
            in_blockers = True
            continue
        if in_blockers and line.startswith("|---"):
            continue
        if in_blockers and line.startswith("|"):
            cols = [c.strip() for c in line.split("|") if c.strip()]
            if len(cols) >= 4 and cols[3] == "OPEN":
                result["blockers"].append({"blocker": cols[0][:40], "blocks": cols[1], "key": cols[2]})
        elif in_blockers and not line.startswith("|"):
            in_blockers = False
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Project status dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
switches:
  --items       All active intake items with next actions
  --stale       Only stale/aging items (need immediate attention)
  --blockers    All blockers mapped to objectives
  --objectives  Go-live checklist detail (per-check status)
  --pipeline    Pipeline breakdown by intake category
  --docs        Document inventory (all files with types)
  --focus       Just the recommended focus item
  --all         Everything at once
""",
    )
    parser.add_argument("--items", action="store_true", help="All active items")
    parser.add_argument("--stale", action="store_true", help="Stale/aging items only")
    parser.add_argument("--blockers", action="store_true", help="All blockers to objectives")
    parser.add_argument("--objectives", action="store_true", help="Go-live checklist detail")
    parser.add_argument("--pipeline", action="store_true", help="Pipeline by category")
    parser.add_argument("--docs", action="store_true", help="Document inventory")
    parser.add_argument("--focus", action="store_true", help="Recommended focus only")
    parser.add_argument("--all", action="store_true", help="Show everything")
    args = parser.parse_args()
    if args.all:
        args.items = args.blockers = args.objectives = args.pipeline = args.docs = True

    # ── Collect data ──

    intake_docs = []
    if MEMORY_DIR.exists():
        for p in sorted(MEMORY_DIR.glob("*_intake.md")):
            intake_docs.append(parse_intake(p))

    all_items = [i for d in intake_docs for i in d["items"] if i["status"] != "CLOSED"]
    closed_count = sum(1 for d in intake_docs for i in d["items"] if i["status"] == "CLOSED")
    stale_items = [i for i in all_items if i["health"] == "STALE"]
    aging_items = [i for i in all_items if i["health"] == "AGING"]

    obj = parse_objectives()
    us_pct = (obj["us_pass"] / obj["checks"] * 100) if obj["checks"] > 0 else 0
    india_pct = (obj["india_pass"] / obj["checks"] * 100) if obj["checks"] > 0 else 0
    blockers = obj["blockers"]
    go_live_blockers = [b for b in blockers if "OBJ-1" in b["blocks"] or "OBJ-2" in b["blocks"]]

    # ── Skin in the Game ──

    skin = 0
    skin += (us_pct + india_pct) / 2 * 0.4                                    # readiness (40 pts)
    skin += max(0, 20 - len(stale_items) * 5)                                 # no stale (20 pts)
    if obj["checks"] > 0:                                                       # blockers resolved (20 pts)
        skin += ((obj["checks"] - len(blockers)) / obj["checks"]) * 20
    if len(all_items) + closed_count > 0:                                       # closed ratio (20 pts)
        skin += (closed_count / (len(all_items) + closed_count)) * 20
    skin = min(skin, 100)
    skin_label = "STRONG" if skin >= 80 else "MODERATE" if skin >= 50 else "WEAK" if skin >= 25 else "NONE"

    # ── Going in Circles? ──
    # If >20 items exist but 0 closed and readiness < 30% — that's churn
    circles = len(all_items) > 15 and closed_count == 0 and (us_pct + india_pct) / 2 < 30

    # ── Convergence ──
    # Simple: items closed / total ever created
    convergence = (closed_count / (len(all_items) + closed_count) * 100) if (len(all_items) + closed_count) > 0 else 0

    # ======================================================================
    # OUTPUT
    # ======================================================================

    print(f"\n{'=' * 80}")
    print(f"  PROJECT STATUS -- income_desk -- {date.today()}")
    print(f"{'=' * 80}")

    # ── Section 1: KPIs (always first, always visible) ──

    print()
    kpi_rows = [
        ["Skin in the Game", f"{skin:.0f}/100 ({skin_label})", "Is Claude driving toward objectives?"],
        ["Go-Live US", f"{us_pct:.0f}% ({obj['us_pass']}/{obj['checks']})", f"{len([b for b in blockers if 'OBJ-1' in b['blocks']])} blockers"],
        ["Go-Live India", f"{india_pct:.0f}% ({obj['india_pass']}/{obj['checks']})", f"{len([b for b in blockers if 'OBJ-2' in b['blocks']])} blockers"],
        ["Convergence", f"{convergence:.0f}%", f"{closed_count} closed / {len(all_items) + closed_count} total"],
        ["Going in Circles?", "YES -- technical churn, no objective progress" if circles else "No", f"{len(all_items)} open, {closed_count} closed"],
    ]
    print(tabulate(kpi_rows, headers=["KPI", "Value", "Detail"], tablefmt="grid"))

    # ── Focus (always shown unless --focus suppresses other sections) ──

    if not args.focus:
        print()

    if go_live_blockers:
        top = go_live_blockers[0]
        print(f"  >> FOCUS: {top['key']} -- {top['blocker']}")
        print(f"     Blocks: {top['blocks']}")
        for item in all_items:
            if item["key"] == top["key"]:
                print(f"     Next:   {item.get('next_action', 'TBD')}")
                break
    else:
        print(f"  >> No go-live blockers -- focus on features")

    if args.focus:
        print()
        return

    # ── Stale/Aging (always shown in default view) ──

    if stale_items or aging_items:
        print()
        attention = stale_items + aging_items
        att_rows = [
            [i["key"], i["item"][:35], f"{i['age_days']}d", i["health"], i["status"],
             i.get("assignee", "")[:8], i.get("next_action", "")[:30]]
            for i in attention
        ]
        title = "STALE ITEMS (Claude's failure)" if stale_items else "AGING ITEMS"
        print(f"  {title}")
        print(tabulate(att_rows,
                        headers=["Key", "Item", "Age", "Health", "Status", "Owner", "Next Action"],
                        tablefmt="grid"))

    # ── Blockers (default view shows count, --blockers shows full table) ──

    if args.blockers and blockers:
        print()
        print(f"  BLOCKERS TO OBJECTIVES ({len(blockers)} open)")
        blocker_rows = []
        for b in blockers:
            # Find next action from intake items
            next_act = ""
            for item in all_items:
                if item["key"] == b["key"]:
                    next_act = item.get("next_action", "")[:30]
                    break
            blocker_rows.append([b["key"], b["blocker"], b["blocks"], next_act])
        print(tabulate(blocker_rows,
                        headers=["Key", "Blocker", "Blocks", "Next Action"],
                        tablefmt="grid"))

    # ── Objectives detail (--objectives) ──

    if args.objectives and obj["checklist"]:
        print()
        print(f"  GO-LIVE CHECKLIST")
        check_rows = [
            [f"{i+1}", c["check"], c["us"], c["india"]]
            for i, c in enumerate(obj["checklist"])
        ]
        print(tabulate(check_rows,
                        headers=["#", "Check", "US", "India"],
                        tablefmt="grid"))

    # ── Pipeline by category (--pipeline) ──

    if args.pipeline:
        print()
        print(f"  PIPELINE BY CATEGORY")
        cat_rows = []
        for d in intake_docs:
            active = [i for i in d["items"] if i["status"] != "CLOSED"]
            if active:
                n_open = sum(1 for i in active if i["status"] == "OPEN")
                n_ip = sum(1 for i in active if i["status"] == "IN_PROGRESS")
                n_blk = sum(1 for i in active if i["status"] == "BLOCKED")
                oldest = max((i["age_days"] for i in active), default=0)
                cat_rows.append([
                    d["path"].replace("_intake.md", ""),
                    len(active), n_open, n_ip, n_blk,
                    f"{oldest}d", d["staleness"],
                ])
        print(tabulate(cat_rows,
                        headers=["Category", "Total", "Open", "InProg", "Blocked", "Oldest", "Health"],
                        tablefmt="grid"))

    # ── All items (--items or --stale) ──

    if args.items or args.stale:
        if args.stale:
            show = [i for i in all_items if i["health"] in ("STALE", "AGING")]
            title = "STALE & AGING ITEMS"
        else:
            show = all_items
            title = "ALL ACTIVE ITEMS"

        if show:
            print()
            print(f"  {title}")
            rows = [
                [i["key"], i["item"][:35], f"{i['age_days']}d", i["health"], i["status"],
                 i.get("assignee", "")[:8], i.get("next_action", "")[:30],
                 i.get("blockers", "")[:15] if i.get("blockers", "") not in ("", "-", "\u2014") else ""]
                for i in show
            ]
            print(tabulate(rows,
                            headers=["Key", "Item", "Age", "Health", "Status", "Owner", "Next Action", "Blockers"],
                            tablefmt="grid"))

    # ── Document inventory (--docs) ──

    if args.docs:
        print()
        living_docs = [parse_living(p) for p in sorted(DOCS_DIR.glob("*_living.md"))] if DOCS_DIR.exists() else []
        info_docs = [parse_info(p) for p in sorted(MEMORY_DIR.glob("*_info.md"))] if MEMORY_DIR.exists() else []
        doc_rows = []
        for d in intake_docs:
            total = len(d["items"])
            active = len([i for i in d["items"] if i["status"] != "CLOSED"])
            doc_rows.append([d["path"], "INTAKE", d["staleness"], total, active, ""])
        for d in living_docs:
            doc_rows.append([d["path"], "LIVING", d["staleness"], "", "", f"reviewed {d['age_days']}d ago"])
        for d in info_docs:
            doc_rows.append([d["path"], "INFO", "", "", "", f"updated {d['updated']}"])
        print("  DOCUMENT INVENTORY")
        print(tabulate(doc_rows, headers=["File", "Type", "Staleness", "Total", "Active", "Notes"], tablefmt="grid"))

    # ── Pipeline summary (always at bottom) ──

    n_open = sum(1 for i in all_items if i["status"] == "OPEN")
    n_ip = sum(1 for i in all_items if i["status"] == "IN_PROGRESS")
    n_blocked = sum(1 for i in all_items if i["status"] == "BLOCKED")
    living_count = len(list(DOCS_DIR.glob("*_living.md"))) if DOCS_DIR.exists() else 0
    info_count = len(list(MEMORY_DIR.glob("*_info.md"))) if MEMORY_DIR.exists() else 0

    print()
    print(f"  {'-' * 60}")
    print(f"  Pipeline:   {n_open} open | {n_ip} in progress | {n_blocked} blocked | {closed_count} closed")
    print(f"  Staleness:  {len(all_items) - len(stale_items) - len(aging_items)} fresh | {len(aging_items)} aging | {len(stale_items)} stale")
    print(f"  Documents:  {len(intake_docs)} intake | {living_count} living | {info_count} info")
    print()


if __name__ == "__main__":
    main()
