"""Deterministic, standard-library MVP for The General Manager's Co-Pilot."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any


STAGES = ("KNITTING", "ASSEMBLY", "WASHING", "PACKING")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DEMO_DATA_DIR = PROJECT_ROOT / "demo_data"
DEFAULT_DB_PATH = BACKEND_DIR / ".copilot.sqlite3"
DEFAULT_CONFIG_PATH = BACKEND_DIR / "rules_config.json"
ORDER_STATUSES = ("COMPLETE", "IN_PROGRESS")
ORDER_COLUMNS = (
    "order_id", "customer", "product", "category", "pieces", "order_date",
    "due_date", "status", "current_stage", "last_activity_date",
    "completed_date", "days_late",
)
PRODUCTION_COLUMNS = ("date", "stage", "pieces_completed")
WORKSHOP_COLUMNS = (
    "workshop_id", "name", "capacity_pieces_per_day", "pickup_lead_days",
    "defect_rate", "cost_per_piece", "makes", "status", "max_batch_pieces",
    "current_queue_days", "notes",
)
PIPELINE_REMAINING = {
    "KNITTING": STAGES,
    "ASSEMBLY": STAGES[1:],
    "WASHING": STAGES[2:],
    "PACKING": STAGES[3:],
}
PRODUCT_CATEGORIES = {
    "cardigan": "TOPS",
    "crewneck sweater": "TOPS",
    "hoodie": "TOPS",
    "polo shirt": "TOPS",
    "vest": "TOPS",
    "beanie": "ACCESSORIES",
    "scarf": "ACCESSORIES",
}


def canonical_product(name: str) -> str:
    """Map a user-typed product name ("Hoodies", "scarves") to its catalogue key; unknown names pass through."""
    text = " ".join(name.split()).casefold()
    candidates = [text]
    if text.endswith("ves"):
        candidates.append(text[:-3] + "f")
    if text.endswith("es"):
        candidates.append(text[:-2])
    if text.endswith("s"):
        candidates.append(text[:-1])
    return next((item for item in candidates if item in PRODUCT_CATEGORIES), text)
CLAIM_RE = re.compile(r"^CLM-\d{8}-(RISK|NORM|DISC|FEAS|RETR|ACTN)-\d{3,}-[a-f0-9]{8}$")


class CoreError(Exception):
    def __init__(self, code: str, message: str, field_name: str | None = None):
        super().__init__(message)
        self.code = code
        self.field_name = field_name


@dataclass
class ReadContext:
    datasets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    versions: dict[str, str] = field(default_factory=dict)
    snapshot_bytes: dict[str, bytes] = field(default_factory=dict)
    loaded_at: str = ""


def iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso_date(value: Any, field_name: str) -> date:
    if not isinstance(value, str):
        raise CoreError("INVALID_DATE", f"{field_name} must be YYYY-MM-DD", field_name)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise CoreError("INVALID_DATE", f"{field_name} must be a real YYYY-MM-DD date", field_name) from exc
    if parsed.isoformat() != value:
        raise CoreError("INVALID_DATE", f"{field_name} must use YYYY-MM-DD", field_name)
    return parsed


def is_strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def json_ready(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return value


def working_days(start: date, end: date) -> int:
    """Count Monday-Saturday in an inclusive interval; Sunday is closed."""
    if end < start:
        return 0
    count = 0
    cursor = start
    while cursor <= end:
        count += cursor.weekday() != 6
        cursor += timedelta(days=1)
    return count


def add_working_days(start: date, amount: int) -> date:
    cursor = start
    remaining = amount
    while remaining:
        cursor += timedelta(days=1)
        if cursor.weekday() != 6:
            remaining -= 1
    return cursor


class CopilotCore:
    def __init__(
        self,
        data_dir: str | Path = DEFAULT_DATA_DIR,
        db_path: str | Path = DEFAULT_DB_PATH,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.db_path = str(db_path)
        self.config_path = Path(config_path)
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CoreError("CONFIG_READ_ERROR", "Cannot read rules_config.json") from exc
        self.config = config
        self.assumptions = config["assumptions"]
        self.as_of_date = parse_iso_date(config["as_of_date"], "as_of_date")
        self.rule_version = config["rule_version"]
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._initialize_store()

    def close(self) -> None:
        self.conn.close()

    def _initialize_store(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS claim_records (
                claim_id TEXT PRIMARY KEY,
                claim_key TEXT NOT NULL UNIQUE,
                claim_date TEXT NOT NULL,
                source_code TEXT NOT NULL,
                sequence_no INTEGER NOT NULL,
                record_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS claim_snapshots (
                file_name TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                content BLOB NOT NULL,
                PRIMARY KEY (file_name, sha256)
            );
            CREATE TABLE IF NOT EXISTS claim_snapshot_refs (
                claim_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                PRIMARY KEY (claim_id, file_name),
                FOREIGN KEY (claim_id) REFERENCES claim_records(claim_id)
            );
            CREATE TABLE IF NOT EXISTS action_records (
                token TEXT PRIMARY KEY,
                requester TEXT NOT NULL,
                action_type TEXT NOT NULL,
                target TEXT NOT NULL,
                preview_json TEXT NOT NULL,
                claim_ids_json TEXT NOT NULL,
                status TEXT NOT NULL,
                prepared_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS action_effects (
                token TEXT PRIMARY KEY,
                action_type TEXT NOT NULL,
                target TEXT NOT NULL,
                effect_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (token) REFERENCES action_records(token)
            );
            CREATE TABLE IF NOT EXISTS brief_runs (
                run_id TEXT PRIMARY KEY,
                as_of_date TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                status TEXT NOT NULL,
                rule_version TEXT NOT NULL,
                data_versions_json TEXT NOT NULL,
                row_counts_json TEXT NOT NULL,
                failure_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS reminders (
                reminder_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                note TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                status TEXT NOT NULL,
                source TEXT NOT NULL,
                action_token TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reminders_status_time ON reminders(status, remind_at);
            """
        )
        self.conn.commit()

    def new_context(self) -> ReadContext:
        return ReadContext(loaded_at=iso_utc())

    def _raw_table(
        self, context: ReadContext, filename: str, required_columns: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        if filename in context.datasets:
            return context.datasets[filename]
        path = self.data_dir / filename
        try:
            content = path.read_bytes()
            confirmed_content = path.read_bytes()
            if confirmed_content != content:
                content = confirmed_content
                if path.read_bytes() != content:
                    raise CoreError("DATA_CHANGED_DURING_READ", f"Data file changed while being read: {filename}")
            text = content.decode("utf-8-sig")
        except CoreError:
            raise
        except FileNotFoundError as exc:
            raise CoreError("DATA_FILE_NOT_FOUND", f"Required data file is missing: {filename}") from exc
        except (OSError, UnicodeDecodeError) as exc:
            raise CoreError("DATA_READ_ERROR", f"Cannot read data file: {filename}") from exc
        reader = csv.DictReader(io.StringIO(text, newline=""))
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)):
            raise CoreError("DATA_VALIDATION_ERROR", f"Duplicate columns in {filename}")
        missing = sorted(set(required_columns) - set(headers))
        if missing:
            raise CoreError("DATA_VALIDATION_ERROR", f"Missing columns in {filename}: {', '.join(missing)}")
        rows = []
        for row_number, row in enumerate(reader, start=1):
            if None in row:
                raise CoreError("DATA_VALIDATION_ERROR", f"Extra values in {filename} record {row_number}")
            missing_values = [column for column in required_columns if row.get(column) is None]
            if missing_values:
                raise CoreError("DATA_VALIDATION_ERROR", f"Missing values in {filename} record {row_number}: {', '.join(missing_values)}")
            row["_source"] = {
                "file_name": filename,
                "file_sha256": hashlib.sha256(content).hexdigest(),
                "data_row_number": row_number,
                "csv_line_start": reader.line_num,
                "csv_line_end": reader.line_num,
            }
            rows.append(row)
        context.datasets[filename] = rows
        context.versions[filename] = hashlib.sha256(content).hexdigest()
        context.snapshot_bytes[filename] = content
        return rows

    def load_orders(self, context: ReadContext) -> list[dict[str, Any]]:
        if "orders.csv" in context.datasets:
            return context.datasets["orders.csv"]
        rows = self._raw_table(context, "orders.csv", ORDER_COLUMNS)
        seen: set[str] = set()
        parsed_rows = []
        for row in rows:
            record = dict(row)
            order_id = record["order_id"]
            if not re.fullmatch(r"ORD-[0-9]{3,}", order_id) or order_id in seen:
                raise CoreError("DATA_VALIDATION_ERROR", f"Invalid or duplicate order_id: {order_id}")
            seen.add(order_id)
            if not record["customer"].strip() or not record["product"].strip():
                raise CoreError("DATA_VALIDATION_ERROR", f"Missing entity value for {order_id}")
            if record["category"] not in ("TOPS", "ACCESSORIES"):
                raise CoreError("DATA_VALIDATION_ERROR", f"Invalid category for {order_id}")
            if record["status"] not in ORDER_STATUSES:
                raise CoreError("DATA_VALIDATION_ERROR", f"Invalid order status for {order_id}")
            if record["current_stage"] not in (*STAGES, "COMPLETE"):
                raise CoreError("DATA_VALIDATION_ERROR", f"Invalid current_stage for {order_id}")
            try:
                pieces = int(record["pieces"])
                if str(pieces) != record["pieces"] or pieces <= 0:
                    raise ValueError
                order_date = parse_iso_date(record["order_date"], "order_date")
                due_date = parse_iso_date(record["due_date"], "due_date")
                activity_date = parse_iso_date(record["last_activity_date"], "last_activity_date")
                completed_date = parse_iso_date(record["completed_date"], "completed_date") if record["completed_date"] else None
                days_late = int(record["days_late"]) if record["days_late"] else None
                if days_late is not None and str(days_late) != record["days_late"]:
                    raise ValueError
            except (ValueError, CoreError) as exc:
                raise CoreError("DATA_VALIDATION_ERROR", f"Invalid numeric/date field for {order_id}") from exc
            if due_date < order_date or activity_date < order_date or activity_date > self.as_of_date:
                raise CoreError("DATA_VALIDATION_ERROR", f"Inconsistent dates for {order_id}")
            if record["status"] == "COMPLETE":
                if record["current_stage"] != "COMPLETE" or completed_date is None or days_late is None:
                    raise CoreError("DATA_VALIDATION_ERROR", f"Completed order fields inconsistent for {order_id}")
                if completed_date < order_date or completed_date > self.as_of_date:
                    raise CoreError("DATA_VALIDATION_ERROR", f"Invalid completed_date for {order_id}")
                if days_late != (completed_date - due_date).days or activity_date < completed_date:
                    raise CoreError("DATA_VALIDATION_ERROR", f"Completion fields inconsistent for {order_id}")
            elif record["current_stage"] == "COMPLETE" or completed_date is not None or days_late is not None:
                raise CoreError("DATA_VALIDATION_ERROR", f"In-progress order fields inconsistent for {order_id}")
            record.update({
                "pieces": pieces,
                "order_date": order_date,
                "due_date": due_date,
                "last_activity_date": activity_date,
                "completed_date": completed_date,
                "days_late": days_late,
            })
            parsed_rows.append(record)
        context.datasets["orders.csv"] = parsed_rows
        return parsed_rows

    def load_production(self, context: ReadContext) -> list[dict[str, Any]]:
        if "production_log.csv" in context.datasets:
            return context.datasets["production_log.csv"]
        rows = self._raw_table(context, "production_log.csv", PRODUCTION_COLUMNS)
        seen: set[tuple[date, str]] = set()
        parsed_rows = []
        for row in rows:
            try:
                record_date = parse_iso_date(row["date"], "date")
                amount = int(row["pieces_completed"])
                if str(amount) != row["pieces_completed"] or amount < 0:
                    raise ValueError
            except (ValueError, CoreError) as exc:
                raise CoreError("DATA_VALIDATION_ERROR", "Invalid production date or pieces_completed") from exc
            stage = row["stage"]
            if stage not in STAGES:
                raise CoreError("DATA_VALIDATION_ERROR", f"Invalid production stage: {stage}")
            key = (record_date, stage)
            if key in seen:
                raise CoreError("DATA_VALIDATION_ERROR", f"Duplicate production key: {record_date}/{stage}")
            seen.add(key)
            parsed_rows.append({"date": record_date, "stage": stage, "pieces_completed": amount, "_source": row["_source"]})
        context.datasets["production_log.csv"] = parsed_rows
        return parsed_rows

    def load_workshops(self, context: ReadContext) -> list[dict[str, Any]]:
        if "workshops.csv" in context.datasets:
            return context.datasets["workshops.csv"]
        rows = self._raw_table(context, "workshops.csv", WORKSHOP_COLUMNS)
        seen: set[str] = set()
        parsed_rows = []
        for row in rows:
            try:
                workshop_id = row["workshop_id"]
                if not re.fullmatch(r"W[1-9][0-9]*", workshop_id) or workshop_id in seen:
                    raise ValueError
                seen.add(workshop_id)
                capacity = int(row["capacity_pieces_per_day"])
                pickup_days = int(row["pickup_lead_days"])
                defect_rate = float(row["defect_rate"])
                cost = float(row["cost_per_piece"])
                queue_days = float(row["current_queue_days"])
                max_batch = int(row["max_batch_pieces"]) if row["max_batch_pieces"] else None
                if not all(math.isfinite(value) for value in (defect_rate, cost, queue_days)):
                    raise ValueError
                if capacity <= 0 or pickup_days < 0 or not 0 <= defect_rate <= 1 or cost < 0 or queue_days < 0:
                    raise ValueError
                if max_batch is not None and max_batch <= 0:
                    raise ValueError
                if row["status"] not in ("ACTIVE", "SUSPENDED"):
                    raise ValueError
                if row["makes"] not in ("TOPS", "ACCESSORIES", "TOPS+ACCESSORIES"):
                    raise ValueError
            except ValueError as exc:
                raise CoreError("DATA_VALIDATION_ERROR", f"Invalid workshop record: {row.get('workshop_id', '?')}") from exc
            parsed_rows.append({
                **row, "capacity_pieces_per_day": capacity, "pickup_lead_days": pickup_days,
                "defect_rate": defect_rate, "cost_per_piece": cost, "current_queue_days": queue_days,
                "max_batch_pieces": max_batch, "_source": row["_source"],
            })
        context.datasets["workshops.csv"] = parsed_rows
        return parsed_rows

    def _source_row(self, row: dict[str, Any]) -> dict[str, Any]:
        result = json_ready(row)
        if "_source" in result:
            source = result.pop("_source")
            result["_source"] = source
        return result

    def _error(self, tool: str, exc: CoreError, normalized_input: dict[str, Any]) -> dict[str, Any]:
        invalid_codes = {
            "INVALID_DATE", "INVALID_DATE_RANGE", "INVALID_ENUM", "INVALID_INPUT",
            "INVALID_PAGINATION", "RANGE_TOO_LARGE", "UNSUPPORTED_ARGUMENT",
            "CONFLICTING_FILTERS",
        }
        result_status = "INVALID_INPUT" if exc.code in invalid_codes else exc.code if exc.code == "INSUFFICIENT_INFORMATION" else "ERROR"
        return {
            "schema_version": "copilot_core.v1", "tool_name": tool,
            "result_status": result_status,
            "business_as_of_date": self.as_of_date.isoformat(), "generated_at": iso_utc(),
            "data_versions": {}, "normalized_input": json_ready(normalized_input),
            "summary": str(exc), "data": None, "requires_clarification": False,
            "evidence": None, "claim_refs": [], "warnings": [],
            "error": {"code": exc.code, "message": str(exc), "field": exc.field_name, "retryable": False},
        }

    def _claim(
        self, tool: str, source_code: str, normalized_input: dict[str, Any],
        status: str, summary: str, data: Any, evidence: dict[str, Any], context: ReadContext,
    ) -> str:
        key_material = {
            "tool": tool, "input": json_ready(normalized_input), "status": status,
            "versions": context.versions, "rule_version": self._rule_version(tool),
        }
        claim_key = hashlib.sha256(json.dumps(key_material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        hash8 = claim_key[:8]
        claim_date = self.as_of_date.strftime("%Y%m%d")
        with self.conn:
            existing = self.conn.execute("SELECT claim_id FROM claim_records WHERE claim_key=?", (claim_key,)).fetchone()
            if existing:
                return existing["claim_id"]
            self.conn.execute("BEGIN IMMEDIATE")
            sequence = self.conn.execute(
                "SELECT COALESCE(MAX(sequence_no),0)+1 AS next_seq FROM claim_records WHERE claim_date=? AND source_code=?",
                (claim_date, source_code),
            ).fetchone()["next_seq"]
            claim_id = f"CLM-{claim_date}-{source_code}-{sequence:03d}-{hash8}"
            source_refs = []
            for filename, version in context.versions.items():
                source_refs.append({
                    "table": filename, "file": filename,
                    "row_ids": [row.get("_source", {}).get("data_row_number") for row in evidence.get("source_rows", [])
                                if row.get("_source", {}).get("file_name") == filename],
                    "filter": evidence.get("normalized_input", {}), "snapshot_version": version,
                })
            steps = evidence.get("calculations", [])
            if len(steps) < 2:
                steps = [
                    {"step_name": "select_source_rows", "formula": "Apply normalized inputs to the versioned source rows", "inputs": normalized_input, "output": len(evidence.get("source_rows", []))},
                    {"step_name": "produce_result", "formula": "Apply deterministic tool rule", "inputs": len(evidence.get("source_rows", [])), "output": data},
                ]
            record = {
                "claim_id": claim_id, "claim_text": summary, "generated_by": f"{tool}@mvp-v1",
                "rule_version": self._rule_version(tool), "generated_at": iso_utc(),
                "as_of_date": self.as_of_date.isoformat(), "inputs": json_ready(normalized_input),
                "normalized_input": json_ready(normalized_input), "source_refs": source_refs,
                "calculation_steps": json_ready(steps), "output_value": json_ready(data),
                "expires_hint": "Re-verify after any source snapshot changes.",
                "tool_name": tool, "result_status": status, "evidence": json_ready(evidence),
            }
            self.conn.execute(
                "INSERT INTO claim_records VALUES (?, ?, ?, ?, ?, ?)",
                (claim_id, claim_key, claim_date, source_code, sequence, json.dumps(record, sort_keys=True)),
            )
            for filename, version in context.versions.items():
                self.conn.execute(
                    "INSERT OR IGNORE INTO claim_snapshots VALUES (?, ?, ?)",
                    (filename, version, context.snapshot_bytes[filename]),
                )
                self.conn.execute("INSERT INTO claim_snapshot_refs VALUES (?, ?, ?)", (claim_id, filename, version))
            return claim_id

    def _rule_version(self, tool: str) -> str:
        return self.config.get("module_rule_versions", {}).get(tool, self.rule_version)

    def _finish(
        self, tool: str, source_code: str, status: str, normalized_input: dict[str, Any],
        data: Any, summary: str, context: ReadContext, source_rows: list[dict[str, Any]],
        calculations: list[dict[str, Any]], coverage: dict[str, Any] | None = None,
        requires_clarification: bool = False, register_claim: bool = True,
    ) -> dict[str, Any]:
        evidence = {
            "evidence_version": "copilot_evidence.v1", "rule_version": self._rule_version(tool),
            "normalized_input": json_ready(normalized_input),
            "source_snapshots": {name: {"sha256": digest} for name, digest in context.versions.items()},
            "source_rows": [self._source_row(row) for row in source_rows],
            "calculations": json_ready(calculations), "coverage": json_ready(coverage or {}),
        }
        result = {
            "schema_version": "copilot_core.v1", "tool_name": tool, "result_status": status,
            "business_as_of_date": self.as_of_date.isoformat(), "generated_at": iso_utc(),
            "data_versions": context.versions, "normalized_input": json_ready(normalized_input),
            "summary": summary, "data": json_ready(data), "requires_clarification": requires_clarification,
            "evidence": evidence, "claim_refs": [], "warnings": [], "error": None,
        }
        if register_claim:
            claim_id = self._claim(tool, source_code, normalized_input, status, summary, data, evidence, context)
            result["claim_refs"] = [{"claim_id": claim_id, "metric_path": "/data"}]
        return result

    def search_orders(self, context: ReadContext | None = None, _register: bool = True, **params: Any) -> dict[str, Any]:
        tool = "search_orders"
        allowed = {"order_id", "customer", "product", "category", "status", "current_stage", "order_date_from", "order_date_to", "due_date_from", "due_date_to", "match_mode", "intent", "limit", "offset"}
        try:
            extra = set(params) - allowed
            if extra:
                raise CoreError("UNSUPPORTED_ARGUMENT", f"Unsupported argument(s): {', '.join(sorted(extra))}")
            normalized = {"order_id": params.get("order_id"), "customer": params.get("customer"), "product": params.get("product"),
                          "category": params.get("category"), "status": params.get("status"), "current_stage": params.get("current_stage"),
                          "order_date_from": params.get("order_date_from"), "order_date_to": params.get("order_date_to"),
                          "due_date_from": params.get("due_date_from"), "due_date_to": params.get("due_date_to"),
                          "match_mode": params.get("match_mode", "EXACT"), "intent": params.get("intent", "LIST"),
                          "limit": params.get("limit", 20), "offset": params.get("offset", 0)}
            if normalized["match_mode"] not in ("EXACT", "CONTAINS") or normalized["intent"] not in ("LIST", "SINGLE", "SUMMARY"):
                raise CoreError("INVALID_ENUM", "match_mode or intent is invalid")
            if not is_strict_int(normalized["limit"]) or not 1 <= normalized["limit"] <= 100 or not is_strict_int(normalized["offset"]) or normalized["offset"] < 0:
                raise CoreError("INVALID_PAGINATION", "limit must be 1..100 and offset must be non-negative")
            if normalized["intent"] in ("SINGLE", "SUMMARY") and normalized["offset"] != 0:
                raise CoreError("INVALID_PAGINATION", "SINGLE and SUMMARY require offset=0")
            if normalized["order_id"] is not None:
                normalized["order_id"] = str(normalized["order_id"]).strip().upper()
                if not re.fullmatch(r"ORD-[0-9]{3,}", normalized["order_id"]):
                    raise CoreError("INVALID_INPUT", "order_id must match ORD- followed by at least three digits", "order_id")
            for name in ("customer", "product"):
                if normalized[name] is not None:
                    normalized[name] = str(normalized[name]).strip()
                    if not normalized[name]:
                        raise CoreError("INVALID_INPUT", f"{name} cannot be blank", name)
            for name, allowed_values in (("category", ("TOPS", "ACCESSORIES")), ("status", ORDER_STATUSES), ("current_stage", (*STAGES, "COMPLETE"))):
                if normalized[name] is not None:
                    normalized[name] = str(normalized[name]).upper()
                    if normalized[name] not in allowed_values:
                        raise CoreError("INVALID_ENUM", f"Invalid {name}: {normalized[name]}", name)
            for name in ("order_date_from", "order_date_to", "due_date_from", "due_date_to"):
                if normalized[name] is not None:
                    normalized[name] = parse_iso_date(normalized[name], name)
            for prefix in ("order_date", "due_date"):
                lower, upper = normalized[f"{prefix}_from"], normalized[f"{prefix}_to"]
                if lower and upper and lower > upper:
                    raise CoreError("INVALID_DATE_RANGE", f"{prefix}_from must not be after {prefix}_to")
            if normalized["status"] == "COMPLETE" and normalized["current_stage"] in STAGES:
                raise CoreError("CONFLICTING_FILTERS", "COMPLETE status conflicts with an in-progress stage")
            context = context or self.new_context()
            records = self.load_orders(context)
            matches = []
            for row in records:
                checks = [
                    normalized["order_id"] is None or row["order_id"] == normalized["order_id"],
                    normalized["customer"] is None or (normalized["customer"].casefold() in row["customer"].casefold() if normalized["match_mode"] == "CONTAINS" else normalized["customer"].casefold() == row["customer"].casefold()),
                    normalized["product"] is None or (normalized["product"].casefold() in row["product"].casefold() if normalized["match_mode"] == "CONTAINS" else normalized["product"].casefold() == row["product"].casefold()),
                    normalized["category"] is None or row["category"] == normalized["category"],
                    normalized["status"] is None or row["status"] == normalized["status"],
                    normalized["current_stage"] is None or row["current_stage"] == normalized["current_stage"],
                    normalized["order_date_from"] is None or row["order_date"] >= normalized["order_date_from"],
                    normalized["order_date_to"] is None or row["order_date"] <= normalized["order_date_to"],
                    normalized["due_date_from"] is None or row["due_date"] >= normalized["due_date_from"],
                    normalized["due_date_to"] is None or row["due_date"] <= normalized["due_date_to"],
                ]
                if all(checks):
                    matches.append(row)
            matches.sort(key=lambda row: (row["due_date"], row["order_id"]))
            count = len(matches)
            total_pieces = sum(row["pieces"] for row in matches)
            clarification = None
            status = "OK" if count else "NO_MATCH"
            if normalized["intent"] == "SINGLE" and count > 1:
                status = "NEEDS_CLARIFICATION"
                clarification = {"reason": "MULTIPLE_ORDER_MATCHES", "candidate_order_ids": [r["order_id"] for r in matches[:normalized["limit"]]],
                                 "candidates_truncated": count > normalized["limit"], "suggested_fields": ["order_id", "product", "due_date"],
                                 "question": "Which matching order do you mean?"}
                page = matches[:normalized["limit"]]
            elif normalized["intent"] == "SUMMARY":
                page = []
            else:
                page = matches[normalized["offset"]:normalized["offset"] + normalized["limit"]]
            data = {"match_count": count, "matched_total_pieces": total_pieces,
                    "orders": [{key: json_ready(value) for key, value in row.items() if key != "_source"} | {"_source": row["_source"]} for row in page],
                    "pagination": {"limit": None if normalized["intent"] == "SUMMARY" else normalized["limit"],
                                   "offset": normalized["offset"], "returned_count": len(page),
                                   "has_more": False if normalized["intent"] == "SUMMARY" else normalized["offset"] + len(page) < count},
                    "clarification": clarification}
            selected_rows = matches if normalized["intent"] == "SUMMARY" or not count else matches
            calculations = [
                {"step_name": "filter_rows", "formula": "AND(all normalized filters)", "inputs": normalized, "output": count},
                {"step_name": "aggregate_then_page", "formula": "count(matches), sum(pieces), then sort/page", "inputs": [r["order_id"] for r in matches], "output": {"match_count": count, "matched_total_pieces": total_pieces}},
            ]
            summary = f"Matched {count} order(s), {total_pieces} pieces." if status != "NEEDS_CLARIFICATION" else f"{count} orders match; clarification is required."
            return self._finish(tool, "RETR", status, normalized, data, summary, context, selected_rows, calculations,
                                coverage={"matched_order_ids": [r["order_id"] for r in matches]}, requires_clarification=status == "NEEDS_CLARIFICATION", register_claim=_register)
        except CoreError as exc:
            return self._error(tool, exc, params)

    def get_production_output(
        self, start_date: str, end_date: str, stages: list[str] | None = None,
        include_closed_days: bool = False, context: ReadContext | None = None, _register: bool = True,
        **unsupported: Any,
    ) -> dict[str, Any]:
        tool = "get_production_output"
        raw_input = {"start_date": start_date, "end_date": end_date, "stages": stages, "include_closed_days": include_closed_days, **unsupported}
        try:
            if unsupported:
                raise CoreError("UNSUPPORTED_ARGUMENT", f"Unsupported argument(s): {', '.join(sorted(unsupported))}")
            start = parse_iso_date(start_date, "start_date")
            end = parse_iso_date(end_date, "end_date")
            if end < start:
                raise CoreError("INVALID_DATE_RANGE", "start_date must not be after end_date")
            calendar_days = (end - start).days + 1
            if calendar_days > self.assumptions["max_production_range_days"]:
                raise CoreError("RANGE_TOO_LARGE", "Requested production range exceeds configured maximum")
            if type(include_closed_days) is not bool:
                raise CoreError("INVALID_INPUT", "include_closed_days must be a boolean")
            requested_stages = list(STAGES) if stages is None else stages
            if not isinstance(requested_stages, list) or not requested_stages or len(requested_stages) != len(set(requested_stages)):
                raise CoreError("INVALID_INPUT", "stages must be a non-empty list without duplicates")
            requested_stages = [str(stage).upper() for stage in requested_stages]
            if any(stage not in STAGES for stage in requested_stages):
                raise CoreError("INVALID_ENUM", "Only the four production stages are valid")
            requested_stages.sort(key=STAGES.index)
            normalized = {"start_date": start, "end_date": end, "stages": requested_stages, "include_closed_days": include_closed_days}
            context = context or self.new_context()
            records = self.load_production(context)
            requested_days = [start + timedelta(days=offset) for offset in range(calendar_days)]
            expected_operating = sum(day.weekday() != 6 for day in requested_days)
            expected_closed = calendar_days - expected_operating
            keyed = {(row["date"], row["stage"]): row for row in records}
            missing = [{"date": day.isoformat(), "stage": stage} for day in requested_days for stage in requested_stages if (day, stage) not in keyed]
            summaries, displayed, evidence_rows = [], [], []
            for stage in requested_stages:
                stage_rows = [keyed[(day, stage)] for day in requested_days if (day, stage) in keyed]
                evidence_rows.extend(stage_rows)
                operating_rows = [row for row in stage_rows if row["date"].weekday() != 6]
                stage_missing = any(item["stage"] == stage for item in missing)
                stage_complete = not stage_missing
                total = sum(row["pieces_completed"] for row in stage_rows) if stage_rows else None
                operating_total = sum(row["pieces_completed"] for row in operating_rows) if stage_rows else None
                avg = operating_total / expected_operating if stage_complete and expected_operating > 0 else None
                summaries.append({
                    "stage": stage, "coverage_status": "COMPLETE" if stage_complete else ("PARTIAL" if stage_rows else "NONE"),
                    "observed_days": len(stage_rows), "observed_operating_days": len(operating_rows),
                    "observed_closed_days": len(stage_rows) - len(operating_rows), "total_pieces": total,
                    "operating_total_pieces": operating_total,
                    "totals_scope": "REQUESTED_RANGE" if stage_complete else "OBSERVED_ONLY",
                    "average_per_operating_day": avg,
                    "average_reason": "DEFINED" if avg is not None else ("NO_OPERATING_DAYS" if stage_complete and expected_operating == 0 else ("NO_OBSERVATIONS" if not stage_rows else "INCOMPLETE_COVERAGE")),
                })
                displayed.extend(row for row in stage_rows if include_closed_days or row["date"].weekday() != 6)
            displayed.sort(key=lambda row: (row["date"], STAGES.index(row["stage"])))
            all_missing = bool(missing)
            any_observations = bool(evidence_rows)
            status = "NO_DATA" if not any_observations else ("PARTIAL_DATA" if all_missing else "OK")
            available_dates = [row["date"] for row in records]
            data = {
                "requested_range": {"start_date": start, "end_date": end},
                "available_range": {"start_date": min(available_dates).isoformat() if available_dates else None, "end_date": max(available_dates).isoformat() if available_dates else None},
                "coverage_status": "NONE" if not any_observations else ("PARTIAL" if all_missing else "COMPLETE"),
                "requested_calendar_days": calendar_days, "expected_operating_days": expected_operating,
                "expected_closed_days": expected_closed, "missing_keys": missing,
                "daily_output": [{"date": row["date"].isoformat(), "stage": row["stage"], "pieces_completed": row["pieces_completed"],
                                  "is_closed_day": row["date"].weekday() == 6, "_source": row["_source"]} for row in displayed],
                "stage_summaries": summaries,
            }
            calculations = [{"step_name": "measure_coverage", "formula": "expected date-stage keys minus observed keys", "inputs": {"days": calendar_days, "stages": requested_stages}, "output": len(missing)},
                            {"step_name": "sum_and_average", "formula": "sum(observed rows); mean = operating total / expected operating days only when complete", "inputs": [self._source_row(row) for row in evidence_rows], "output": summaries}]
            summary = f"Production coverage {data['coverage_status'].lower()} for {calendar_days} calendar day(s)."
            return self._finish(tool, "RETR", status, normalized, data, summary, context, evidence_rows, calculations,
                                coverage={"missing_keys": missing, "expected_operating_days": expected_operating}, register_claim=_register)
        except CoreError as exc:
            return self._error(tool, exc, raw_input)

    def assess_order_risk(
        self, order_id: str, context: ReadContext | None = None, _register: bool = True
    ) -> dict[str, Any]:
        tool = "assess_order_risk"
        normalized = {"order_id": str(order_id).strip().upper()}
        try:
            context = context or self.new_context()
            orders = self.load_orders(context)
            row = next((item for item in orders if item["order_id"] == normalized["order_id"]), None)
            if row is None:
                return self._finish(tool, "RISK", "NOT_FOUND", normalized, None, f"Order {normalized['order_id']} was not found.", context, [],
                                    [{"step_name": "lookup_order", "formula": "exact order_id lookup", "inputs": normalized, "output": 0},
                                     {"step_name": "assess_risk", "formula": "no source order; no judgment", "inputs": [], "output": None}], register_claim=_register)
            factors = []
            rules = []
            days_to_due = (row["due_date"] - self.as_of_date).days
            inactive_days = working_days(row["last_activity_date"] + timedelta(days=1), self.as_of_date)
            if row["status"] == "COMPLETE":
                level = "LOW"
                factors.append({"rule_id": "ORDER_COMPLETE", "value": row["days_late"], "unit": "calendar_days_late", "meaning": "Order is complete; this is historical lateness, not current delivery risk."})
                rules.append("ORDER_COMPLETE")
            else:
                if days_to_due < 0:
                    rules.append("ORDER_OVERDUE")
                    factors.append({"rule_id": "ORDER_OVERDUE", "days_past_due": -days_to_due})
                    level = "CRITICAL"
                else:
                    level = "LOW"
                if 0 <= days_to_due <= self.assumptions["deadline_window_calendar_days"]:
                    rules.append("DEADLINE_APPROACHING")
                    factors.append({"rule_id": "DEADLINE_APPROACHING", "days_to_due": days_to_due})
                    if level != "CRITICAL":
                        level = "HIGH"
                if inactive_days >= self.assumptions["stagnation_working_days"]:
                    rules.append("ORDER_STAGNANT")
                    factors.append({"rule_id": "ORDER_STAGNANT", "inactive_working_days": inactive_days})
                    if level == "LOW":
                        level = "MEDIUM"
                    if days_to_due <= self.assumptions["deadline_window_calendar_days"]:
                        level = "HIGH" if level != "CRITICAL" else level
            data = {"order_id": row["order_id"], "risk_level": level, "risk_factors": factors,
                    "rules_triggered": rules, "confidence": "HIGH", "data_quality": "COMPLETE",
                    "days_to_due": days_to_due,
                    # Days since a completed order's last activity are not a production stall; omit them.
                    "inactive_working_days": None if row["status"] == "COMPLETE" else inactive_days,
                    "warnings": [self.config["assumption_notice"]]}
            summary = f"{row['order_id']} current risk: {level}; triggered rules: {', '.join(rules) if rules else 'none'}."
            calculations = [
                {"step_name": "derive_dates", "formula": "due_date - business_as_of_date; count Monday-Saturday since last activity", "inputs": {"due_date": row["due_date"], "last_activity_date": row["last_activity_date"]}, "output": {"days_to_due": days_to_due, "inactive_working_days": inactive_days}},
                {"step_name": "apply_risk_rules", "formula": "configured deterministic rule boundaries", "inputs": self.assumptions, "output": {"risk_level": level, "rules_triggered": rules}},
            ]
            return self._finish(tool, "RISK", "OK", normalized, data, summary, context, [row], calculations, register_claim=_register)
        except CoreError as exc:
            return self._error(tool, exc, normalized)

    def assess_output_normality(
        self, target_date: str, stage: str, context: ReadContext | None = None, _register: bool = True
    ) -> dict[str, Any]:
        tool = "assess_output_normality"
        normalized = {"target_date": target_date, "stage": str(stage).upper()}
        try:
            target = parse_iso_date(target_date, "target_date")
            stage = normalized["stage"]
            if stage not in STAGES:
                raise CoreError("INVALID_ENUM", "stage must be a production stage")
            context = context or self.new_context()
            rows = self.load_production(context)
            target_row = next((row for row in rows if row["date"] == target and row["stage"] == stage), None)
            if target_row is None:
                data = {"stage": stage, "target_date": target.isoformat(), "status": "INSUFFICIENT_DATA", "reason_code": "MISSING_PRODUCTION_RECORD", "actual_output": None, "baseline": None, "deviation_fraction": None, "sample_count": 0}
                status = "INSUFFICIENT_DATA"
                evidence_rows = []
                calculations = [
                    {"step_name": "lookup_target", "formula": "exact (date, stage) lookup", "inputs": normalized, "output": 0},
                    {"step_name": "classify_missing", "formula": "missing is not equivalent to zero", "inputs": 0, "output": data},
                ]
            else:
                baseline_rows = [row for row in rows if row["stage"] == stage and row["date"] < target and row["date"].weekday() == target.weekday()]
                baseline_rows.sort(key=lambda row: row["date"], reverse=True)
                baseline_rows = baseline_rows[:self.assumptions["normality_lookback_same_weekday"]]
                baseline = median([row["pieces_completed"] for row in baseline_rows]) if baseline_rows else None
                actual = target_row["pieces_completed"]
                deviation = (baseline - actual) / baseline if baseline is not None and baseline > 0 else None
                if target.weekday() == 6:
                    state = "ABNORMAL" if actual > 0 else "CLOSED_DAY"
                    reason = "NONZERO_CLOSED_DAY" if actual > 0 else "SCHEDULED_CLOSURE"
                elif len(baseline_rows) < self.assumptions["normality_min_samples"] or baseline is None:
                    state, reason = "INSUFFICIENT_DATA", "INSUFFICIENT_HISTORY"
                elif deviation is not None and deviation >= self.assumptions["output_drop_fraction"] and baseline - actual >= self.assumptions["output_drop_min_pieces"]:
                    state, reason = "ABNORMAL", "OUTPUT_BELOW_NORMAL"
                else:
                    state, reason = "NORMAL", "WITHIN_CONFIGURED_RANGE"
                status = "OK" if state != "INSUFFICIENT_DATA" else state
                data = {"stage": stage, "target_date": target.isoformat(), "status": state, "reason_code": reason,
                        "actual_output": actual, "baseline": baseline, "baseline_method": "median of recent same-weekday observations",
                        "baseline_dates": [row["date"].isoformat() for row in baseline_rows],
                        "deviation_fraction": deviation, "sample_count": len(baseline_rows),
                        "warnings": [self.config["assumption_notice"]]}
                evidence_rows = [*baseline_rows, target_row]
                calculations = [
                    {"step_name": "same_weekday_baseline", "formula": "median(last configured same-weekday observations)", "inputs": [self._source_row(row) for row in baseline_rows], "output": baseline},
                    {"step_name": "compare_output", "formula": "(baseline - actual) / baseline >= configured drop fraction", "inputs": {"actual": actual, "baseline": baseline, "threshold": self.assumptions["output_drop_fraction"]}, "output": {"deviation_fraction": deviation, "status": state, "reason_code": reason}},
                ]
            summary = f"{stage} output on {target.isoformat()}: {data['status']} ({data['reason_code']})."
            return self._finish(tool, "NORM", status, normalized, data, summary, context, evidence_rows, calculations,
                                coverage={"target_record_present": target_row is not None, "baseline_samples": data.get("sample_count", 0)}, register_claim=_register)
        except CoreError as exc:
            return self._error(tool, exc, normalized)

    def estimate_order_feasibility(
        self, product: str, category: str, pieces: int, requested_due_date: str,
        allow_outsourcing: bool = True, safety_buffer_pct: float | None = None,
        lookback_working_days: int | None = None, context: ReadContext | None = None,
        _register: bool = True,
    ) -> dict[str, Any]:
        tool = "estimate_order_feasibility"
        normalized = {"product": product, "category": category, "pieces": pieces,
                      "requested_due_date": requested_due_date, "as_of_date": self.as_of_date.isoformat(),
                      "allow_outsourcing": allow_outsourcing,
                      "safety_buffer_pct": self.assumptions["feasibility_safety_buffer_pct"] if safety_buffer_pct is None else safety_buffer_pct,
                      "lookback_working_days": self.assumptions["feasibility_lookback_working_days"] if lookback_working_days is None else lookback_working_days}
        try:
            if not isinstance(product, str) or not product.strip():
                raise CoreError("INVALID_INPUT", "product is required", "product")
            normalized["product"] = canonical_product(product)
            normalized["category"] = str(category).upper()
            if PRODUCT_CATEGORIES.get(normalized["product"]) != normalized["category"]:
                raise CoreError("INVALID_INPUT", "product/category is unsupported or inconsistent. Supported products: "
                                + ", ".join(f"{name} ({cat})" for name, cat in PRODUCT_CATEGORIES.items()))
            if not is_strict_int(pieces) or pieces <= 0:
                raise CoreError("INVALID_INPUT", "pieces must be a positive integer", "pieces")
            due = parse_iso_date(requested_due_date, "requested_due_date")
            if due <= self.as_of_date:
                raise CoreError("INVALID_INPUT", "requested_due_date must be after as_of_date", "requested_due_date")
            if type(allow_outsourcing) is not bool:
                raise CoreError("INVALID_INPUT", "allow_outsourcing must be boolean")
            buffer = normalized["safety_buffer_pct"]
            lookback = normalized["lookback_working_days"]
            if isinstance(buffer, bool) or not isinstance(buffer, (int, float)) or not 0 <= buffer < 1:
                raise CoreError("INVALID_INPUT", "safety_buffer_pct must be in [0, 1)")
            if not is_strict_int(lookback) or lookback < 1:
                raise CoreError("INVALID_INPUT", "lookback_working_days must be a positive integer")
            normalized["requested_due_date"] = due
            context = context or self.new_context()
            orders = self.load_orders(context)
            logs = self.load_production(context)
            workshops = self.load_workshops(context) if allow_outsourcing else []
            available_days = working_days(self.as_of_date + timedelta(days=1), due)
            existing = [row for row in orders if row["status"] == "IN_PROGRESS"]
            capacity_by_stage, load_by_stage, available_by_stage, durations = {}, {}, {}, {}
            deficit_by_stage = {}
            relevant_rows: list[dict[str, Any]] = []
            operating_dates = sorted({row["date"] for row in logs if row["date"] <= self.as_of_date and row["date"].weekday() != 6}, reverse=True)[:lookback]
            for stage in STAGES:
                samples = [row for row in logs if row["stage"] == stage and row["date"] in operating_dates]
                if len(samples) < self.assumptions["feasibility_min_history"]:
                    raise CoreError("INSUFFICIENT_INFORMATION", f"Not enough recent production history for {stage}")
                raw_capacity = median([row["pieces_completed"] for row in samples])
                usable = raw_capacity * (1 - buffer)
                if usable <= 0:
                    raise CoreError("INSUFFICIENT_INFORMATION", f"No positive usable capacity for {stage}")
                stage_load = sum(row["pieces"] for row in existing if row["current_stage"] in PIPELINE_REMAINING and stage in PIPELINE_REMAINING[row["current_stage"]])
                capacity_by_stage[stage] = {"raw_median_pieces_per_day": raw_capacity, "usable_pieces_per_day": usable, "sample_count": len(samples), "sample_dates": sorted({row["date"].isoformat() for row in samples})}
                load_by_stage[stage] = stage_load
                available_by_stage[stage] = max(0.0, usable * available_days - stage_load)
                deficit_by_stage[stage] = max(0.0, stage_load - usable * available_days)
                durations[stage] = math.ceil((stage_load + pieces) / usable)
                relevant_rows.extend(samples)
            earliest_days = max(durations.values())
            latest_days = sum(durations.values())
            earliest = add_working_days(self.as_of_date, earliest_days)
            latest = add_working_days(self.as_of_date, latest_days)
            internal_slack = working_days(latest + timedelta(days=1), due)
            bottleneck = max(STAGES, key=lambda stage: (load_by_stage[stage] + pieces) / max(capacity_by_stage[stage]["usable_pieces_per_day"] * available_days, 1e-9))
            internal_class = "LIKELY_FEASIBLE" if internal_slack >= 2 else ("NOT_FEASIBLE" if latest > due else "HIGH_RISK")
            workshop_scenarios = []
            excluded = []
            for shop in workshops:
                reasons = []
                shop_categories = shop["makes"].split("+")
                if shop["status"] != "ACTIVE":
                    reasons.append("SUSPENDED")
                if normalized["category"] not in shop_categories:
                    reasons.append("CATEGORY_NOT_SUPPORTED")
                if shop["max_batch_pieces"] is not None and pieces > shop["max_batch_pieces"]:
                    reasons.append("BATCH_LIMIT_EXCEEDED")
                if reasons:
                    excluded.append({"workshop_id": shop["workshop_id"], "reason_codes": reasons, "_source": shop["_source"]})
                    continue
                processing = math.ceil(pieces / shop["capacity_pieces_per_day"])
                duration = shop["current_queue_days"] + shop["pickup_lead_days"] + processing
                completion = add_working_days(self.as_of_date, math.ceil(duration))
                slack = working_days(completion + timedelta(days=1), due)
                workshop_scenarios.append({
                    "workshop_id": shop["workshop_id"], "estimated_working_days": duration,
                    "estimated_completion_date": completion.isoformat(), "slack_working_days": slack,
                    "estimated_cost": round(pieces * shop["cost_per_piece"], 2),
                    "cost_currency": None, "defect_rate": shop["defect_rate"],
                    "classification": "LIKELY_FEASIBLE" if slack >= 2 else ("NOT_FEASIBLE" if completion > due else "HIGH_RISK"),
                    "assumptions": ["Queue, pickup lead and processing duration are treated as working-day equivalents.", "Defect rework time is not modeled."],
                    "_source": shop["_source"],
                })
            outsourcing_feasible = any(item["classification"] == "LIKELY_FEASIBLE" for item in workshop_scenarios)
            if internal_class == "LIKELY_FEASIBLE":
                classification = "LIKELY_FEASIBLE"
            elif outsourcing_feasible:
                classification = "FEASIBLE_WITH_OUTSOURCING"
            elif internal_class == "NOT_FEASIBLE" and all(item["classification"] == "NOT_FEASIBLE" for item in workshop_scenarios):
                classification = "NOT_FEASIBLE"
            else:
                classification = "HIGH_RISK"
            all_source_rows = relevant_rows + existing + workshops
            data = {
                "classification": classification,
                "recommendation": "Estimate only; confirm actual production and workshop capacity before committing.",
                "requested_due_date": due.isoformat(), "available_working_days": available_days,
                "estimated_completion_range": {"earliest": earliest.isoformat(), "latest": latest.isoformat()},
                "bottleneck_stage": bottleneck,
                "internal_scenario": {"classification": internal_class, "estimated_working_days": latest_days,
                                      "capacity_by_stage": capacity_by_stage, "estimated_existing_load_by_stage": load_by_stage,
                                      "remaining_capacity_by_stage": available_by_stage, "capacity_deficit_by_stage": deficit_by_stage,
                                      "estimated_stage_days_including_proposed_order": durations},
                "workshop_scenarios": workshop_scenarios, "excluded_workshops": excluded,
                "assumptions": [self.config["assumption_notice"], "Full order quantity is assumed to remain at each current and later stage for existing orders."],
                "limitations": ["Factory-wide output does not provide an order-level production schedule.", "This result is not a delivery guarantee."],
                "confidence": "LOW" if internal_slack < 2 else "MEDIUM", "reason_codes": ["BOTTLENECK_" + bottleneck],
                "rule_version": "feasibility-v1",
            }
            calculations = [
                {"step_name": "estimate_stage_capacity", "formula": "median(recent working-day output) * (1 - safety buffer)", "inputs": capacity_by_stage, "output": {stage: capacity_by_stage[stage]["usable_pieces_per_day"] for stage in STAGES}},
                {"step_name": "estimate_completion", "formula": "ceil((existing full-order load + proposed pieces) / usable stage capacity); sequential conservative duration", "inputs": {"existing_load": load_by_stage, "proposed_pieces": pieces}, "output": {"stage_days": durations, "completion_range": data["estimated_completion_range"], "classification": classification}},
            ]
            return self._finish(tool, "FEAS", "OK", normalized, data, f"Feasibility estimate: {classification}.", context, all_source_rows, calculations,
                                coverage={"production_sample_dates": sorted({r["date"].isoformat() for r in relevant_rows}), "existing_orders": len(existing)}, register_claim=_register)
        except CoreError as exc:
            return self._error(tool, exc, normalized)

    def discover_operational_issues(
        self, as_of_date: str | None = None, lookback_days: int = 28, max_findings: int = 5,
        context: ReadContext | None = None, _register: bool = True,
    ) -> dict[str, Any]:
        tool = "discover_operational_issues"
        normalized = {"as_of_date": as_of_date or self.as_of_date.isoformat(), "lookback_days": lookback_days, "max_findings": max_findings, "rule_version": "discovery-v1"}
        try:
            run_date = parse_iso_date(normalized["as_of_date"], "as_of_date")
            if not is_strict_int(lookback_days) or lookback_days < 1 or not is_strict_int(max_findings) or not 1 <= max_findings <= 5:
                raise CoreError("INVALID_INPUT", "lookback_days must be positive and max_findings must be 1..5")
            context = context or self.new_context()
            orders = self.load_orders(context)
            logs = self.load_production(context)
            target_day = run_date - timedelta(days=1)
            # lookback_days counts back from the day before target_day, so with 28 days the window still
            # holds four earlier same-weekday days and matches assess_output_normality's baseline.
            baseline_start = target_day - timedelta(days=lookback_days)
            normality_context = ReadContext(
                datasets={"production_log.csv": [row for row in logs if baseline_start <= row["date"] <= target_day]},
                versions=dict(context.versions), snapshot_bytes=dict(context.snapshot_bytes), loaded_at=context.loaded_at,
            )
            findings: list[dict[str, Any]] = []
            risk_by_order: dict[str, dict[str, Any]] = {}
            for stage in STAGES:
                result = self.assess_output_normality(target_day.isoformat(), stage, context=normality_context, _register=True)
                data = result.get("data") or {}
                if data.get("status") == "ABNORMAL":
                    actual = data.get("actual_output") or 0
                    baseline = data.get("baseline") or 0
                    amount = max(0, round(baseline - actual))
                    consecutive_zero = False
                    if actual == 0:
                        previous_day = target_day - timedelta(days=1)
                        while previous_day.weekday() == 6:
                            previous_day -= timedelta(days=1)
                        previous_row = next((row for row in logs if row["date"] == previous_day and row["stage"] == stage), None)
                        consecutive_zero = previous_row is not None and previous_row["pieces_completed"] == 0
                        if not consecutive_zero:
                            findings.append({"finding_id": f"{run_date.isoformat()}-{stage}-ZERO-OBSERVE", "category": "stage_zero_output_observation",
                                             "priority": 0, "summary": f"{stage} recorded zero output on one operating day; a second consecutive zero is required for an alert.",
                                             "evidence": data, "recommended_next_step": "Check the next operating-day record before escalating.",
                                             "claim_id": result.get("claim_refs", [{}])[0].get("claim_id"),
                                             "_impact": 0, "_anomaly": 0, "_spread": 1, "_urgency": 10})
                            continue
                    findings.append({"finding_id": f"{run_date.isoformat()}-{stage}-OUTPUT", "category": "stage_output_drop",
                                     "priority": 0, "summary": f"{stage} output was {actual} vs same-weekday median {baseline}.",
                                     "evidence": data, "recommended_next_step": "Verify the stage's records and operating conditions.",
                                     "claim_id": result.get("claim_refs", [{}])[0].get("claim_id"),
                                     "_impact": amount, "_anomaly": min(100.0, (data.get("deviation_fraction") or 0) * 100), "_spread": 1, "_urgency": 50})
                elif data.get("status") == "INSUFFICIENT_DATA":
                    findings.append({"finding_id": f"{run_date.isoformat()}-{stage}-DATA", "category": "data_quality_observation",
                                     "priority": 0, "summary": f"{stage} output cannot be assessed: {data.get('reason_code')}.",
                                     "evidence": data, "recommended_next_step": "Confirm the production record and baseline coverage.",
                                     "claim_id": result.get("claim_refs", [{}])[0].get("claim_id"),
                                     "_impact": 0, "_anomaly": 0, "_spread": 1, "_urgency": 10})
            for order in orders:
                if order["status"] != "IN_PROGRESS":
                    continue
                result = self.assess_order_risk(order["order_id"], context=context, _register=True)
                risk = result.get("data") or {}
                risk_by_order[order["order_id"]] = {"result": result, "risk": risk, "order": order}
                if risk.get("risk_level") in ("HIGH", "CRITICAL"):
                    findings.append({"finding_id": f"{run_date.isoformat()}-{order['order_id']}-RISK", "category": "order_delivery_risk",
                                     "priority": 0, "summary": f"{order['order_id']} is {risk['risk_level'].lower()} risk; due {order['due_date'].isoformat()}.",
                                     "evidence": risk, "recommended_next_step": "Review the current stage and confirm the next operational step.",
                                     "claim_id": result.get("claim_refs", [{}])[0].get("claim_id"),
                                     "_impact": order["pieces"], "_anomaly": 75 if "ORDER_STAGNANT" in risk.get("rules_triggered", []) else 50,
                                     "_spread": 1, "_urgency": 100 if risk["risk_level"] == "CRITICAL" else 80,
                                     "_customer": order["customer"]})
            by_customer: dict[str, list[dict[str, Any]]] = {}
            for item in risk_by_order.values():
                if item["risk"].get("risk_level") in ("HIGH", "CRITICAL"):
                    by_customer.setdefault(item["order"]["customer"], []).append(item)
            for customer, items in by_customer.items():
                if len(items) < 2:
                    continue
                finding_data = {"customer": customer, "affected_orders": [item["order"]["order_id"] for item in items], "order_count": len(items)}
                finding_result = self._finish(
                    "discover_operational_issues", "DISC", "OK", {**normalized, "customer_cluster": customer}, finding_data,
                    f"{len(items)} high-risk orders are associated with {customer}.", context,
                    [item["order"] for item in items],
                    [{"step_name": "group_risky_orders", "formula": "group high-risk in-progress orders by customer", "inputs": finding_data["affected_orders"], "output": len(items)},
                     {"step_name": "emit_customer_finding", "formula": "emit when at least two high-risk orders share a customer", "inputs": len(items), "output": finding_data}],
                    register_claim=True,
                )
                findings.append({"finding_id": f"{run_date.isoformat()}-{hashlib.sha1(customer.encode()).hexdigest()[:6]}-CLUSTER",
                                 "category": "customer_risk_cluster", "priority": 0,
                                 "summary": f"{len(items)} high-risk orders for {customer}.", "evidence": finding_data,
                                 "recommended_next_step": "Review the affected orders together with the account owner.",
                                 "claim_id": finding_result.get("claim_refs", [{}])[0].get("claim_id"),
                                 "_impact": sum(item["order"]["pieces"] for item in items), "_anomaly": 80,
                                 "_spread": len(items), "_urgency": 85})
            clustered_customers = {customer for customer, items in by_customer.items() if len(items) >= 2}
            findings = [finding for finding in findings
                        if not (finding["category"] == "order_delivery_risk" and finding.get("_customer") in clustered_customers)]
            scale = self.assumptions["impact_scale_pieces"]
            for finding in findings:
                impact = min(100.0, finding.pop("_impact") / scale * 100)
                anomaly = finding.pop("_anomaly")
                spread = min(100.0, finding.pop("_spread") * 50)
                urgency = finding.pop("_urgency")
                components = {"urgency": urgency, "impact": impact, "anomaly": anomaly, "spread": spread}
                finding["priority_components"] = components
                weights = self.config["priority_weights"]
                finding["priority"] = round(sum(components[name] * weights[name] for name in components), 2)
                finding["severity"] = "CRITICAL" if finding["priority"] >= self.assumptions["priority_critical"] else ("WARNING" if finding["priority"] >= self.assumptions["priority_warning"] else "INFO")
                finding.pop("_customer", None)
                finding["status"] = "OPEN"
                finding["as_of_date"] = run_date.isoformat()
            findings.sort(key=lambda item: (-item["priority"], item["finding_id"]))
            observation_threshold = self.assumptions["brief_min_priority"]
            observations = [item for item in findings if item["priority"] < observation_threshold]
            publishable = [item for item in findings if item["priority"] >= observation_threshold]
            top = publishable[:max_findings]
            run_id = f"RUN-{run_date.strftime('%Y%m%d')}-{datetime.now(timezone.utc).strftime('%H%M%S%f')}"
            data = {"run_id": run_id,
                    "as_of_date": run_date.isoformat(), "data_cutoff_time": context.loaded_at,
                    "rule_version": "discovery-v1", "data_quality": "INSUFFICIENT" if any(item["category"] == "data_quality_observation" for item in findings) else "COMPLETE",
                    "overview": {"finding_count": len(findings), "published_count": len(top), "observation_count": len(observations),
                                 "not_shown_count": len(publishable) - len(top),
                                 "counts_note": "finding_count = published_count + not_shown_count + observation_count; "
                                                "severity_counts covers the published findings only.",
                                 "severity_counts": {level: sum(item["severity"] == level for item in top) for level in ("CRITICAL", "WARNING", "INFO")}},
                    "findings": top, "observation_findings": observations,
                    # Findings above the publish threshold that did not fit in the top max_findings; listed so
                    # nothing important disappears silently when several findings share the same priority.
                    "not_shown_findings": [{"summary": item["summary"], "severity": item["severity"], "priority": item["priority"],
                                            "evidence": item.get("evidence"), "claim_id": item.get("claim_id")}
                                           for item in publishable[max_findings:]],
                    "data_max_dates": {"orders_last_activity": max((row["last_activity_date"] for row in orders), default=None),
                                       "production_log": max((row["date"] for row in logs), default=None)},
                    "assumptions": [self.config["assumption_notice"]]}
            all_rows = [*orders, *logs]
            calculations = [
                {"step_name": "collect_rule_findings", "formula": "run B risk and normality rules; aggregate customer clusters", "inputs": normalized, "output": len(findings)},
                {"step_name": "rank_and_limit", "formula": "configured weighted priority; publish at most max_findings", "inputs": {"weights": self.config["priority_weights"], "components": [item["priority_components"] for item in findings]}, "output": [item["finding_id"] for item in top]},
            ]
            result = self._finish(tool, "DISC", "OK", normalized, data, f"Brief contains {len(top)} prioritized finding(s)" + (f"; {len(publishable) - len(top)} more above the threshold not shown." if len(publishable) > len(top) else "."), context, all_rows, calculations,
                                  coverage={"orders": len(orders), "production_rows": len(logs), "target_output_date": target_day.isoformat()}, register_claim=_register)
            self._record_brief_run(data, context, "OK", None)
            return result
        except CoreError as exc:
            result = self._error(tool, exc, normalized)
            run_id = f"RUN-{self.as_of_date.strftime('%Y%m%d')}-{hashlib.sha1(iso_utc().encode()).hexdigest()[:8]}"
            self.conn.execute("INSERT INTO brief_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              (run_id, normalized["as_of_date"], iso_utc(), iso_utc(), result["result_status"],
                               "discovery-v1", "{}", "{}", str(exc)))
            self.conn.commit()
            return result

    def _record_brief_run(self, data: dict[str, Any], context: ReadContext, status: str, failure_reason: str | None) -> None:
        counts = {name: len(rows) for name, rows in context.datasets.items()}
        self.conn.execute("INSERT INTO brief_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (data["run_id"], data["as_of_date"], context.loaded_at, iso_utc(), status,
                           data["rule_version"], json.dumps(context.versions, sort_keys=True),
                           json.dumps(counts, sort_keys=True), failure_reason))
        self.conn.commit()

    def trace_claim(self, claim_id: str, verify: bool = False) -> dict[str, Any]:
        if not isinstance(claim_id, str) or not CLAIM_RE.fullmatch(claim_id):
            return {"status": "INVALID_FORMAT", "error": "claim_id format is invalid"}
        row = self.conn.execute("SELECT record_json FROM claim_records WHERE claim_id=?", (claim_id,)).fetchone()
        if row is None:
            return {"status": "NOT_FOUND", "claim_id": claim_id, "error": "Registered claim was not found."}
        record = json.loads(row["record_json"])
        missing = []
        changed = []
        for ref in record["source_refs"]:
            snapshot = self.conn.execute("SELECT content FROM claim_snapshots WHERE file_name=? AND sha256=?", (ref["file"], ref["snapshot_version"])).fetchone()
            if snapshot is None:
                missing.append(ref["file"])
                continue
            current_path = self.data_dir / ref["file"]
            try:
                current_hash = hashlib.sha256(current_path.read_bytes()).hexdigest()
                if current_hash != ref["snapshot_version"]:
                    changed.append(ref["file"])
            except OSError:
                changed.append(ref["file"])
        status = "SOURCE_UNAVAILABLE" if missing else "OK"
        verification = None
        if verify and not missing:
            try:
                current = self._recompute(record)
                old_value = record["output_value"]
                new_value = json_ready(current.get("data"))
                unchanged = current.get("result_status") == record["result_status"] and self._stable_value(new_value) == self._stable_value(old_value)
                status = "OK" if unchanged else "STALE"
                verification = {"result": "CONSISTENT" if unchanged else "DRIFTED", "old_value": old_value,
                                "new_value": new_value, "likely_cause": "Source data or tool behavior changed." if not unchanged else None,
                                "current_snapshot_changed": bool(changed)}
            except Exception as exc:  # Re-verification failure is visible to the caller.
                status = "SOURCE_UNAVAILABLE"
                verification = {"result": "UNAVAILABLE", "error": str(exc)}
        result = {key: record[key] for key in ("claim_text", "generated_by", "rule_version", "generated_at", "as_of_date", "source_refs", "calculation_steps")}
        result.update({"claim_id": claim_id, "filters_applied": record["normalized_input"], "status": status,
                       "source_rows": record["evidence"].get("source_rows", []),
                       "coverage": record["evidence"].get("coverage", {}),
                       "historical_snapshot_available": not missing, "changed_source_files": changed,
                       "missing_source_snapshots": missing})
        if verify:
            result["verification"] = verification
        return result

    def _stable_value(self, value: Any) -> Any:
        volatile_fields = {"generated_at", "data_cutoff_time", "run_id"}
        if isinstance(value, dict):
            return {key: self._stable_value(item) for key, item in value.items() if key not in volatile_fields}
        if isinstance(value, list):
            return [self._stable_value(item) for item in value]
        return value

    def _recompute(self, record: dict[str, Any]) -> dict[str, Any]:
        tool = record["tool_name"]
        values = dict(record["normalized_input"])
        if tool == "search_orders":
            return self.search_orders(_register=False, **values)
        if tool == "get_production_output":
            return self.get_production_output(_register=False, **values)
        if tool == "assess_order_risk":
            return self.assess_order_risk(values["order_id"], _register=False)
        if tool == "assess_output_normality":
            return self.assess_output_normality(values["target_date"], values["stage"], _register=False)
        if tool == "estimate_order_feasibility":
            values.pop("as_of_date", None)
            return self.estimate_order_feasibility(_register=False, **values)
        if tool == "discover_operational_issues":
            customer_cluster = values.pop("customer_cluster", None)
            values.pop("rule_version", None)
            if customer_cluster is not None:
                context = self.new_context()
                cluster_orders = []
                for order in self.load_orders(context):
                    if order["customer"] != customer_cluster or order["status"] != "IN_PROGRESS":
                        continue
                    risk_result = self.assess_order_risk(
                        order["order_id"], context=context, _register=False
                    )
                    risk = risk_result.get("data") or {}
                    if risk.get("risk_level") in ("HIGH", "CRITICAL"):
                        cluster_orders.append(order["order_id"])
                cluster_data = (
                    {
                        "customer": customer_cluster,
                        "affected_orders": cluster_orders,
                        "order_count": len(cluster_orders),
                    }
                    if len(cluster_orders) >= 2
                    else None
                )
                return {"result_status": "OK", "data": cluster_data}
            return self.discover_operational_issues(_register=False, **values)
        raise CoreError("UNSUPPORTED_RECOMPUTATION", f"No recomputation handler for {tool}")

    # ------------------------------------------------------------------ reminders
    # Reminders run on the real-world clock (they are follow-ups for the user), unlike the
    # business date, which is the frozen "today" of the data snapshot.

    @staticmethod
    def _parse_remind_at(value: Any, require_future: bool = True) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise CoreError("INVALID_INPUT", "remind_at is required", "remind_at")
        try:
            moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise CoreError("INVALID_INPUT", "remind_at must be an ISO date-time", "remind_at") from exc
        if moment.tzinfo is None:
            raise CoreError("INVALID_INPUT", "remind_at must include a timezone", "remind_at")
        if require_future and moment <= datetime.now(timezone.utc):
            raise CoreError("INVALID_INPUT", "remind_at must be in the future", "remind_at")
        return moment.astimezone(timezone.utc)

    def _resolve_order_id(self, order_id: Any) -> str:
        wanted = str(order_id or "").strip().upper()
        if not any(row["order_id"] == wanted for row in self.load_orders(self.new_context())):
            raise CoreError("TARGET_NOT_RESOLVED", f"Order {wanted or '(blank)'} was not found", "order_id")
        return wanted

    @staticmethod
    def _validate_note(note: Any) -> str:
        if not isinstance(note, str) or not note.strip():
            raise CoreError("INVALID_INPUT", "note is required", "note")
        if len(note.strip()) > 500:
            raise CoreError("INVALID_INPUT", "note exceeds 500 characters", "note")
        return note.strip()

    @staticmethod
    def _reminder_view(row: sqlite3.Row, now: datetime) -> dict[str, Any]:
        remind_at = datetime.fromisoformat(row["remind_at"])
        if row["status"] != "ACTIVE":
            due_state = row["status"]
        elif remind_at <= now:
            due_state = "OVERDUE"
        elif remind_at - now <= timedelta(hours=24):
            due_state = "DUE_SOON"
        else:
            due_state = "UPCOMING"
        return {key: row[key] for key in row.keys()} | {"due_state": due_state}

    def _insert_reminder(self, order_id: str, note: str, remind_at: datetime, source: str, action_token: str | None) -> dict[str, Any]:
        now = iso_utc()
        reminder_id = f"REM-{secrets.token_hex(4).upper()}"
        self.conn.execute("INSERT INTO reminders VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)",
                          (reminder_id, order_id, note, remind_at.isoformat(), source, action_token, now, now))
        return self.get_reminder(reminder_id)

    def get_reminder(self, reminder_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM reminders WHERE reminder_id=?", (reminder_id,)).fetchone()
        return self._reminder_view(row, datetime.now(timezone.utc)) if row else None

    def list_reminders(self, include_closed: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM reminders" + ("" if include_closed else " WHERE status='ACTIVE'") + " ORDER BY remind_at"
        now = datetime.now(timezone.utc)
        return [self._reminder_view(row, now) for row in self.conn.execute(query).fetchall()]

    def create_reminder(self, order_id: str, note: str, remind_at: str, requester: str = "web") -> dict[str, Any]:
        """Create a reminder directly (an explicit user form submission) and log it in the action ledger."""
        try:
            target = self._resolve_order_id(order_id)
            text = self._validate_note(note)
            moment = self._parse_remind_at(remind_at)
        except CoreError as exc:
            return {"status": "REFUSED", "error": {"code": exc.code, "message": str(exc)}}
        token = secrets.token_urlsafe(24)
        now = iso_utc()
        payload = {"remind_at": moment.isoformat(), "message": text}
        preview = {"action_type": "create_reminder", "target": target, "payload": payload, "claim_ids": []}
        self.conn.execute("INSERT INTO action_records VALUES (?, ?, 'create_reminder', ?, ?, '[]', 'CONFIRMED', ?, ?)",
                          (token, requester, target, json.dumps(preview, ensure_ascii=False, sort_keys=True), now, now))
        reminder = self._insert_reminder(target, text, moment, requester, token)
        effect = {"action_type": "create_reminder", "target": target, "payload": payload,
                  "mode": "reminder_saved", "reminder_id": reminder["reminder_id"], "external_message_sent": False}
        self.conn.execute("INSERT INTO action_effects VALUES (?, 'create_reminder', ?, ?, ?)",
                          (token, target, json.dumps(effect, ensure_ascii=False, sort_keys=True), now))
        self.conn.commit()
        return {"status": "CREATED", "reminder": reminder}

    def update_reminder(self, reminder_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM reminders WHERE reminder_id=?", (reminder_id,)).fetchone()
        if row is None:
            return {"status": "REFUSED", "error": {"code": "NOT_FOUND", "message": "Reminder was not found"}}
        try:
            fields: dict[str, Any] = {}
            if "status" in changes:
                if changes["status"] not in ("DONE", "CANCELLED", "ACTIVE"):
                    raise CoreError("INVALID_INPUT", "status must be ACTIVE, DONE or CANCELLED", "status")
                fields["status"] = changes["status"]
            edits_content = any(key in changes for key in ("order_id", "note", "remind_at"))
            if edits_content and row["status"] != "ACTIVE" and changes.get("status") != "ACTIVE":
                raise CoreError("INVALID_INPUT", "Only active reminders can be edited")
            if "order_id" in changes:
                fields["order_id"] = self._resolve_order_id(changes["order_id"])
            if "note" in changes:
                fields["note"] = self._validate_note(changes["note"])
            if "remind_at" in changes:
                fields["remind_at"] = self._parse_remind_at(changes["remind_at"]).isoformat()
        except CoreError as exc:
            return {"status": "REFUSED", "error": {"code": exc.code, "message": str(exc)}}
        if fields:
            assignments = ", ".join(f"{key}=?" for key in fields)
            self.conn.execute(f"UPDATE reminders SET {assignments}, updated_at=? WHERE reminder_id=?",
                              (*fields.values(), iso_utc(), reminder_id))
            self.conn.commit()
        return {"status": "UPDATED", "reminder": self.get_reminder(reminder_id)}

    def manage_action(
        self, operation: str, requester: str, action_type: str | None = None,
        target: str | None = None, payload: dict[str, Any] | None = None,
        claim_ids: list[str] | None = None, confirmation_token: str | None = None,
    ) -> dict[str, Any]:
        operation = operation.upper()
        if operation == "PREPARE":
            try:
                if action_type not in ("add_order_note", "create_reminder", "create_watch", "draft_chase_up_message"):
                    raise CoreError("INVALID_INPUT", "Unsupported action_type")
                if not isinstance(requester, str) or not requester.strip() or not isinstance(target, str) or not target.strip():
                    raise CoreError("INVALID_INPUT", "requester and a resolved target are required")
                context = self.new_context()
                order = next((row for row in self.load_orders(context) if row["order_id"] == target.strip().upper()), None)
                if order is None:
                    raise CoreError("TARGET_NOT_RESOLVED", "Target must be an existing, uniquely resolved order")
                payload = payload or {}
                if not isinstance(payload, dict):
                    raise CoreError("INVALID_INPUT", "payload must be a JSON object")
                required_payload = {
                    "add_order_note": ("note",), "create_reminder": ("remind_at", "message"),
                    "create_watch": ("tool_name", "condition", "message"), "draft_chase_up_message": ("message",),
                }[action_type]
                if any(not isinstance(payload.get(key), str) or not payload[key].strip() for key in required_payload):
                    raise CoreError("INVALID_INPUT", f"payload requires non-empty string fields: {', '.join(required_payload)}")
                if action_type == "add_order_note" and len(payload["note"]) > 500:
                    raise CoreError("INVALID_INPUT", "Order note exceeds 500 characters")
                if any(len(payload[key]) > 1000 for key in required_payload if key != "remind_at"):
                    raise CoreError("INVALID_INPUT", "Action text exceeds 1000 characters")
                if action_type == "create_reminder":
                    payload = {**payload, "remind_at": self._parse_remind_at(payload["remind_at"]).isoformat()}
                if action_type == "create_watch" and payload["tool_name"] not in ("search_orders", "get_production_output", "assess_order_risk", "assess_output_normality", "estimate_order_feasibility"):
                    raise CoreError("INVALID_INPUT", "Watch condition must reference a checkable tool")
                claim_ids = claim_ids or []
                if any(not CLAIM_RE.fullmatch(item) or self.conn.execute("SELECT 1 FROM claim_records WHERE claim_id=?", (item,)).fetchone() is None for item in claim_ids):
                    raise CoreError("INVALID_INPUT", "Every claim_id must be a registered claim")
                # Business numbers (pieces, days late, ...) need evidence. Schedule times, order IDs and
                # dates are identifiers, not claims, so they are ignored by this check.
                checked_text = " ".join(str(value) for key, value in payload.items() if key != "remind_at")
                checked_text = re.sub(r"\bORD-\d+\b|\b\d{4}-\d{2}-\d{2}(T[\d:.+\-Z]*)?\b", " ", checked_text)
                if re.search(r"\d", checked_text) and not claim_ids:
                    raise CoreError("CLAIM_REQUIRED", "Action content with numbers requires at least one claim_id")
                token = secrets.token_urlsafe(24)
                prepared_at = iso_utc()
                preview = {"action_type": action_type, "target": order["order_id"], "payload": payload, "claim_ids": claim_ids}
                self.conn.execute("INSERT INTO action_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                                  (token, requester.strip(), action_type, order["order_id"], json.dumps(preview, ensure_ascii=False, sort_keys=True),
                                   json.dumps(claim_ids), "PREPARED", prepared_at))
                self.conn.commit()
                return {"status": "PREPARED", "preview": preview, "confirmation_token": token, "prepared_at": prepared_at,
                        "side_effect_executed": False}
            except CoreError as exc:
                return {"status": "REFUSED", "error": {"code": exc.code, "message": str(exc)}}
        if operation in ("CONFIRM", "CANCEL"):
            if not confirmation_token:
                return {"status": "REFUSED", "error": {"code": "TOKEN_REQUIRED", "message": "confirmation_token is required"}}
            self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute("SELECT * FROM action_records WHERE token=?", (confirmation_token,)).fetchone()
            if row is None or row["status"] != "PREPARED":
                self.conn.rollback()
                return {"status": "REFUSED", "error": {"code": "TOKEN_INVALID", "message": "Token is missing, expired, or already used"}}
            completed_at = iso_utc()
            if operation == "CANCEL":
                self.conn.execute("UPDATE action_records SET status='CANCELLED', completed_at=? WHERE token=?", (completed_at, confirmation_token))
                self.conn.commit()
                return {"status": "CANCELLED", "side_effect_executed": False}
            preview = json.loads(row["preview_json"])
            effect = {"action_type": row["action_type"], "target": row["target"], "payload": preview["payload"],
                      "mode": "local_record_only", "external_message_sent": False}
            if row["action_type"] == "create_reminder":
                # Confirming a prepared reminder saves a real reminder, even if its time passed meanwhile.
                reminder = self._insert_reminder(row["target"], preview["payload"]["message"],
                                                 datetime.fromisoformat(preview["payload"]["remind_at"]),
                                                 row["requester"], confirmation_token)
                effect.update({"mode": "reminder_saved", "reminder_id": reminder["reminder_id"]})
            self.conn.execute("INSERT INTO action_effects VALUES (?, ?, ?, ?, ?)",
                              (confirmation_token, row["action_type"], row["target"], json.dumps(effect, ensure_ascii=False, sort_keys=True), completed_at))
            self.conn.execute("UPDATE action_records SET status='CONFIRMED', completed_at=? WHERE token=?", (completed_at, confirmation_token))
            self.conn.commit()
            return {"status": "CONFIRMED", "executed_preview": preview, "recorded_effect": effect,
                    "execution_mode": "reminder saved to the reminders list" if row["action_type"] == "create_reminder"
                    else "local action ledger only; watch scheduling and message delivery are not connected", "confirmed_at": completed_at}
        return {"status": "REFUSED", "error": {"code": "INVALID_OPERATION", "message": "operation must be PREPARE, CONFIRM, or CANCEL"}}

    def action_audit(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT a.*, e.effect_json FROM action_records a LEFT JOIN action_effects e ON e.token=a.token ORDER BY a.prepared_at").fetchall()
        return [{"requester": row["requester"], "action_type": row["action_type"], "target": row["target"],
                 "confirmation_token": row["token"],
                 "preview": json.loads(row["preview_json"]), "claim_ids": json.loads(row["claim_ids_json"]),
                 "status": row["status"], "prepared_at": row["prepared_at"], "completed_at": row["completed_at"],
                 "recorded_effect": json.loads(row["effect_json"]) if row["effect_json"] else None} for row in rows]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic General Manager Co-Pilot core")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Directory containing the three CSV files")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite evidence/action store")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Rule and assumption configuration")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="Run a read-only example with synthetic demo CSV files")
    orders = sub.add_parser("orders", help="Search orders")
    for arg in ("order-id", "customer", "product", "category", "status", "stage", "intent", "match-mode"):
        orders.add_argument("--" + arg)
    orders.add_argument("--limit", type=int, default=20)
    orders.add_argument("--offset", type=int, default=0)
    production = sub.add_parser("production", help="Query factory-wide stage production")
    production.add_argument("--start", required=True)
    production.add_argument("--end", required=True)
    production.add_argument("--stage", action="append", dest="stages")
    production.add_argument("--include-closed-days", action="store_true")
    risk = sub.add_parser("risk", help="Assess current risk for one existing order")
    risk.add_argument("--order-id", required=True)
    normality = sub.add_parser("normality", help="Assess output normality")
    normality.add_argument("--date", required=True)
    normality.add_argument("--stage", required=True)
    feasibility = sub.add_parser("feasibility", help="Estimate feasibility for a proposed order")
    feasibility.add_argument("--product", required=True)
    feasibility.add_argument("--category", required=True)
    feasibility.add_argument("--pieces", type=int, required=True)
    feasibility.add_argument("--due-date", required=True)
    feasibility.add_argument("--no-outsourcing", action="store_true")
    sub.add_parser("brief", help="Generate a deterministic Top 5 operations brief")
    trace = sub.add_parser("trace", help="Trace a registered claim")
    trace.add_argument("claim_id")
    trace.add_argument("--verify", action="store_true")
    action = sub.add_parser("action", help="Prepare, confirm or cancel a safe action")
    action.add_argument("operation", choices=("PREPARE", "CONFIRM", "CANCEL"))
    action.add_argument("--requester", default="manager")
    action.add_argument("--type", dest="action_type")
    action.add_argument("--target")
    action.add_argument("--payload", default="{}", help="Action payload as JSON object")
    action.add_argument("--payload-file", help="Read the action payload JSON object from a UTF-8 file")
    action.add_argument("--claims", default="", help="Comma-separated registered claim IDs")
    action.add_argument("--token")
    audit = sub.add_parser("action-audit", help="List local action audit records")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = DEFAULT_DEMO_DATA_DIR if args.command == "demo" else args.data_dir
    core = CopilotCore(data_dir, args.db, args.config)
    try:
        if args.command == "demo":
            outputs = {
                "mode": "SYNTHETIC_DEMO_ONLY",
                "order_summary": core.search_orders(intent="SUMMARY"),
                "assembly_normality": core.assess_output_normality("2026-03-31", "ASSEMBLY"),
                "brief": core.discover_operational_issues(),
            }
        elif args.command == "orders":
            mapping = {"order_id": "order_id", "customer": "customer", "product": "product", "category": "category", "status": "status", "stage": "current_stage", "intent": "intent", "match_mode": "match_mode", "limit": "limit", "offset": "offset"}
            outputs = core.search_orders(**{dest: getattr(args, source) for source, dest in mapping.items() if getattr(args, source) is not None})
        elif args.command == "production":
            outputs = core.get_production_output(args.start, args.end, args.stages, args.include_closed_days)
        elif args.command == "risk":
            outputs = core.assess_order_risk(args.order_id)
        elif args.command == "normality":
            outputs = core.assess_output_normality(args.date, args.stage)
        elif args.command == "feasibility":
            outputs = core.estimate_order_feasibility(args.product, args.category, args.pieces, args.due_date, not args.no_outsourcing)
        elif args.command == "brief":
            outputs = core.discover_operational_issues()
        elif args.command == "trace":
            outputs = core.trace_claim(args.claim_id, args.verify)
        elif args.command == "action":
            try:
                if args.payload_file and args.payload != "{}":
                    raise CoreError("INVALID_INPUT", "Use only one of --payload and --payload-file")
                payload_text = Path(args.payload_file).read_text(encoding="utf-8-sig") if args.payload_file else args.payload
                payload = json.loads(payload_text)
                if not isinstance(payload, dict):
                    raise CoreError("INVALID_INPUT", "Action payload must be a JSON object")
            except (OSError, json.JSONDecodeError, CoreError) as exc:
                message = str(exc)
                outputs = {"status": "REFUSED", "error": {"code": "INVALID_INPUT", "message": message}}
            else:
                outputs = core.manage_action(args.operation, args.requester, args.action_type, args.target, payload,
                                             [item for item in args.claims.split(",") if item], args.token)
        else:
            outputs = core.action_audit()
        print(json.dumps(json_ready(outputs), ensure_ascii=False, indent=2))
        return 0
    finally:
        core.close()


if __name__ == "__main__":
    raise SystemExit(main())