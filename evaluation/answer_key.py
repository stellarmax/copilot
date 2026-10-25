"""Independent answer key for the evaluation set.

Reads the course CSV files with the standard library only and recomputes every expected
fact from the documented business rules. It deliberately imports nothing from backend/, so the
system under test never grades itself.

    .venv\\Scripts\\python.exe -m evaluation.answer_key        # writes evaluation/answer_key.json
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = Path(__file__).resolve().parent / "answer_key.json"

# Documented in data/data_dictionary.md and backend/rules_config.json (team assumptions).
AS_OF = date(2026, 4, 1)
DEADLINE_WINDOW_DAYS = 7          # due within 0..7 calendar days -> deadline approaching
STAGNATION_WORKING_DAYS = 5       # >= 5 Mon-Sat days without activity -> stagnant
NORMALITY_LOOKBACK = 4            # last 4 same-weekday observations
OUTPUT_DROP_FRACTION = 0.35       # >= 35% below the median -> abnormal


def read(name: str) -> list[dict[str, str]]:
    with open(DATA / name, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def d(text: str) -> date:
    return date.fromisoformat(text)


def working_days(start: date, end: date) -> int:
    """Monday-Saturday days in the inclusive range."""
    return sum((start + timedelta(days=i)).weekday() != 6 for i in range((end - start).days + 1)) if end >= start else 0


def risk_level(order: dict[str, str]) -> tuple[str, int, int]:
    if order["status"] == "COMPLETE":
        return "LOW", 0, 0
    days_to_due = (d(order["due_date"]) - AS_OF).days
    inactive = working_days(d(order["last_activity_date"]) + timedelta(days=1), AS_OF)
    if days_to_due < 0:
        level = "CRITICAL"
    elif days_to_due <= DEADLINE_WINDOW_DAYS:
        level = "HIGH"
    else:
        level = "LOW"
    if inactive >= STAGNATION_WORKING_DAYS and level == "LOW":
        level = "MEDIUM"
    return level, days_to_due, inactive


def main() -> dict:
    orders = read("orders.csv")
    log = read("production_log.csv")
    output = {(r["date"], r["stage"]): int(r["pieces_completed"]) for r in log}

    def stage_total(stage: str, start: str, end: str) -> int:
        return sum(v for (day, s), v in output.items() if s == stage and start <= day <= end)

    def normality(day: str, stage: str) -> dict:
        target = d(day)
        history = sorted(
            (dt for (dt, s) in output if s == stage and d(dt) < target and d(dt).weekday() == target.weekday()),
            reverse=True,
        )[:NORMALITY_LOOKBACK]
        baseline = median(output[(dt, stage)] for dt in history)
        actual = output[(day, stage)]
        drop = (baseline - actual) / baseline
        return {"actual": actual, "baseline": baseline, "baseline_dates": history,
                "drop_fraction": round(drop, 4), "status": "ABNORMAL" if drop >= OUTPUT_DROP_FRACTION else "NORMAL"}

    in_progress = [o for o in orders if o["status"] == "IN_PROGRESS"]
    by_id = {o["order_id"]: o for o in orders}

    def customer(name: str, active_only: bool = False) -> list[dict[str, str]]:
        return [o for o in (in_progress if active_only else orders) if o["customer"] == name]

    def ids_by_due(rows: list[dict[str, str]]) -> list[str]:
        return [o["order_id"] for o in sorted(rows, key=lambda o: (o["due_date"], o["order_id"]))]

    high_by_customer: dict[str, list[str]] = defaultdict(list)
    for o in in_progress:
        if risk_level(o)[0] in ("HIGH", "CRITICAL"):
            high_by_customer[o["customer"]].append(o["order_id"])
    clusters = {c: ids for c, ids in high_by_customer.items() if len(ids) >= 2}

    trendcart_active = customer("TrendCart", True)
    northwind_active = customer("Northwind Apparel", True)
    due_week = [o for o in in_progress if "2026-04-01" <= o["due_date"] <= "2026-04-07"]
    ord058 = by_id["ORD-058"]
    knit_0330 = normality("2026-03-30", "KNITTING")

    facts = {
        "_meta": {
            "as_of_date": AS_OF.isoformat(),
            "data_sha256": {n: hashlib.sha256((DATA / n).read_bytes()).hexdigest()
                            for n in ("orders.csv", "production_log.csv", "workshops.csv")},
            "method": "Standard-library recomputation from data/*.csv; imports nothing from backend/.",
        },
        # Orders
        "in_progress_count": len(in_progress),
        "in_progress_pieces": sum(int(o["pieces"]) for o in in_progress),
        "trendcart_count": len(customer("TrendCart")),
        "trendcart_pieces": sum(int(o["pieces"]) for o in customer("TrendCart")),
        "trendcart_active_count": len(trendcart_active),
        "trendcart_active_pieces": sum(int(o["pieces"]) for o in trendcart_active),
        "trendcart_active_ids": ids_by_due(trendcart_active),
        "northwind_active_count": len(northwind_active),
        "northwind_active_pieces": sum(int(o["pieces"]) for o in northwind_active),
        "maple_active_ids": ids_by_due(customer("Maple & Co", True)),
        "cotton_club_active_ids": ids_by_due(customer("Cotton Club", True)),
        "ord058_status": ord058["status"],
        "ord058_pieces": int(ord058["pieces"]),
        "ord058_days_late": int(ord058["days_late"]),
        "due_apr1_7_ids": ids_by_due(due_week),
        # Production (factory-wide, per stage)
        "assembly_0331": output[("2026-03-31", "ASSEMBLY")],
        "stages_0331": {s: output[("2026-03-31", s)] for s in ("KNITTING", "ASSEMBLY", "WASHING", "PACKING")},
        "assembly_week_0323_0329": stage_total("ASSEMBLY", "2026-03-23", "2026-03-29"),
        "assembly_week_avg": round(stage_total("ASSEMBLY", "2026-03-23", "2026-03-29") / 6, 4),
        "knitting_march": stage_total("KNITTING", "2026-03-01", "2026-03-31"),
        "packing_0328": output[("2026-03-28", "PACKING")],
        "washing_0316_0321": stage_total("WASHING", "2026-03-16", "2026-03-21"),
        "assembly_0329_sunday": output[("2026-03-29", "ASSEMBLY")],
        # Judgement
        "ord029_risk": risk_level(by_id["ORD-029"])[0],
        "ord029_days_to_due": risk_level(by_id["ORD-029"])[1],
        "ord108_risk": risk_level(by_id["ORD-108"])[0],
        "ord108_days_to_due": risk_level(by_id["ORD-108"])[1],
        "assembly_0331_normality": normality("2026-03-31", "ASSEMBLY"),
        "knitting_0330_normality": knit_0330,
        # Brief: customers with >= 2 high-risk in-progress orders
        "brief_cluster_customers": sorted(clusters),
        "brief_clusters": clusters,
    }
    return facts


if __name__ == "__main__":
    facts = main()
    OUT.write_text(json.dumps(facts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(facts, indent=2, ensure_ascii=False))
