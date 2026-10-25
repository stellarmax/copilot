"""Strict, read-only Agent tools mapped to deterministic core methods."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.copilot import CopilotCore


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchOrdersArguments(ToolArguments):
    order_id: str | None = None
    customer: str | None = None
    product: str | None = None
    category: Literal["TOPS", "ACCESSORIES"] | None = None
    status: Literal["COMPLETE", "IN_PROGRESS"] | None = None
    current_stage: Literal["KNITTING", "ASSEMBLY", "WASHING", "PACKING", "COMPLETE"] | None = None
    due_date_from: date | None = None
    due_date_to: date | None = None
    match_mode: Literal["EXACT", "CONTAINS"] = "EXACT"
    intent: Literal["LIST", "SINGLE", "SUMMARY"] = "LIST"
    limit: int = Field(default=10, ge=1, le=20)
    offset: int = Field(default=0, ge=0)


class ProductionArguments(ToolArguments):
    start_date: date
    end_date: date
    stages: list[Literal["KNITTING", "ASSEMBLY", "WASHING", "PACKING"]] | None = None
    include_closed_days: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> "ProductionArguments":
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if (self.end_date - self.start_date).days > 31:
            raise ValueError("Chat production queries are limited to 32 calendar days")
        return self


class RiskArguments(ToolArguments):
    order_id: str = Field(min_length=1, max_length=32)


class NormalityArguments(ToolArguments):
    target_date: date
    stage: Literal["KNITTING", "ASSEMBLY", "WASHING", "PACKING"]


class FeasibilityArguments(ToolArguments):
    product: str = Field(min_length=1, max_length=80)
    category: Literal["TOPS", "ACCESSORIES"]
    pieces: int = Field(gt=0, le=100000)
    requested_due_date: date
    allow_outsourcing: bool = True


class BriefArguments(ToolArguments):
    as_of_date: date | None = None
    lookback_days: int = Field(default=28, ge=1, le=90)
    max_findings: int = Field(default=5, ge=1, le=5)


class PrepareActionArguments(ToolArguments):
    action_type: Literal["add_order_note", "create_reminder", "draft_chase_up_message"]
    order_id: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=1000)
    remind_at: str | None = Field(default=None, max_length=64)
    claim_ids: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_reminder_time(self) -> "PrepareActionArguments":
        if (self.action_type == "create_reminder") != (self.remind_at is not None):
            raise ValueError("remind_at is required for create_reminder and only allowed there")
        return self


class TraceArguments(ToolArguments):
    claim_id: str = Field(min_length=1, max_length=80)
    verify: bool = False


TOOL_MODELS: dict[str, type[ToolArguments]] = {
    "search_orders": SearchOrdersArguments,
    "get_production_output": ProductionArguments,
    "assess_order_risk": RiskArguments,
    "assess_output_normality": NormalityArguments,
    "estimate_order_feasibility": FeasibilityArguments,
    "discover_operational_issues": BriefArguments,
    "trace_claim": TraceArguments,
    "prepare_action": PrepareActionArguments,
}

TOOL_DESCRIPTIONS = {
    "search_orders": "Search the existing order register. Use SINGLE when the user means one order; ambiguity must be clarified.",
    "get_production_output": "Query factory-wide production by date range and optional stages. Missing rows are not zero.",
    "assess_order_risk": "Assess deterministic delivery risk for one existing order ID.",
    "assess_output_normality": "Compare one stage and date with the configured same-weekday baseline.",
    "estimate_order_feasibility": "Estimate a proposed order using product, category, pieces, and due date. Supported products: "
                                  "Cardigan, Crewneck sweater, Hoodie, Polo shirt, Vest (TOPS); Beanie, Scarf (ACCESSORIES). "
                                  "This is not a delivery guarantee.",
    "discover_operational_issues": "Generate the deterministic operations brief for a business date.",
    "trace_claim": "Retrieve or re-verify an existing registered claim using its exact claim ID.",
    "prepare_action": "PREPARE (never execute) an action for one existing order: add_order_note (text = the note), "
                      "create_reminder (text = what to remember, remind_at = ISO 8601 date-time with timezone offset), or "
                      "draft_chase_up_message (text = the draft; it is never sent). The user sees a preview card and "
                      "decides with Confirm or Cancel. Text containing business numbers (pieces, days late) needs the "
                      "claim_ids of the tool results those numbers came from.",
}


OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": TOOL_DESCRIPTIONS[name],
            "parameters": model.model_json_schema(),
        },
    }
    for name, model in TOOL_MODELS.items()
]


def execute_tool(core: CopilotCore, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    model = TOOL_MODELS.get(name)
    if model is None:
        raise ValueError("This tool is not allowed.")
    values = model.model_validate(arguments).model_dump(mode="json", exclude_none=True)
    if name == "search_orders":
        return core.search_orders(**values)
    if name == "get_production_output":
        return core.get_production_output(
            values["start_date"],
            values["end_date"],
            values.get("stages"),
            values.get("include_closed_days", False),
        )
    if name == "assess_order_risk":
        return core.assess_order_risk(values["order_id"])
    if name == "assess_output_normality":
        return core.assess_output_normality(values["target_date"], values["stage"])
    if name == "estimate_order_feasibility":
        return core.estimate_order_feasibility(
            values["product"],
            values["category"],
            values["pieces"],
            values["requested_due_date"],
            values.get("allow_outsourcing", True),
        )
    if name == "discover_operational_issues":
        return core.discover_operational_issues(**values)
    if name == "trace_claim":
        return core.trace_claim(values["claim_id"], verify=values.get("verify", False))
    if name == "prepare_action":
        text = values["text"]
        payload = {"add_order_note": {"note": text},
                   "create_reminder": {"remind_at": values.get("remind_at"), "message": text},
                   "draft_chase_up_message": {"message": text}}[values["action_type"]]
        return core.manage_action("PREPARE", "assistant", values["action_type"], values["order_id"],
                                  payload, values.get("claim_ids", []))
    raise ValueError("This tool is not allowed.")


def trim_evidence(value: Any, _top: bool = True) -> Any:
    """Remove raw source rows before model context; retain business results and claims.

    Only the tool envelope's top-level "evidence" bundle is raw provenance. A nested "evidence"
    field (for example a brief finding's affected orders) is business content and is kept.
    """
    if isinstance(value, dict):
        dropped = {"evidence", "source_rows", "_source"} if _top else {"source_rows", "_source"}
        return {key: trim_evidence(item, False) for key, item in value.items() if key not in dropped}
    if isinstance(value, list):
        return [trim_evidence(item, False) for item in value[:100]]
    return value


def claim_ids_from_result(result: dict[str, Any]) -> list[str]:
    claim_ids: set[str] = {
        item["claim_id"]
        for item in result.get("claim_refs", [])
        if isinstance(item, dict) and isinstance(item.get("claim_id"), str)
    }
    data = result.get("data")
    if isinstance(data, dict):
        for key in ("findings", "observation_findings"):
            for finding in data.get(key, []):
                if isinstance(finding, dict) and isinstance(finding.get("claim_id"), str):
                    claim_ids.add(finding["claim_id"])
    return sorted(claim_ids)