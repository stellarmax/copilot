"""FastAPI wrapper around the deterministic Co-Pilot core."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from datetime import date
from http import HTTPStatus
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from backend.copilot import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_DATA_DIR,
    DEFAULT_DB_PATH,
    PROJECT_ROOT,
    CopilotCore,
)
from backend.app.agent.security import CredentialEncryptionError
from backend.app.agent.provider import PROVIDER_CATALOG
from backend.app.agent.service import AgentService, AgentTurnError
from backend.app.agent.store import AgentStore
from backend.app.auth import (
    LoginThrottle,
    SessionMiddleware,
    check_invite,
    clear_session_cookie,
    current_user,
    set_session_cookie,
)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FeasibilityRequest(StrictRequest):
    product: str = Field(min_length=1)
    category: Literal["TOPS", "ACCESSORIES"]
    pieces: int = Field(gt=0)
    requested_due_date: date
    allow_outsourcing: bool = True


class BriefRequest(StrictRequest):
    as_of_date: date | None = None
    lookback_days: int = Field(default=28, ge=1)
    max_findings: int = Field(default=5, ge=1, le=5)


class ActionPrepareRequest(StrictRequest):
    action_type: Literal[
        "add_order_note",
        "create_reminder",
        "create_watch",
        "draft_chase_up_message",
    ]
    target: str = Field(min_length=1)
    payload: dict[str, Any]
    claim_ids: list[str] = Field(default_factory=list)
    requester: str = Field(default="manager", min_length=1)


class AISettingsRequest(StrictRequest):
    provider: Literal["chatgpt", "claude", "gemini", "deepseek"]
    model: str = Field(min_length=1, max_length=120)
    api_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_model_for_provider(self) -> "AISettingsRequest":
        allowed = {item["id"] for item in PROVIDER_CATALOG[self.provider]["models"]}
        if self.model not in allowed:
            raise ValueError("Choose a model from the selected provider's supported model list.")
        return self


class ReminderCreateRequest(StrictRequest):
    order_id: str = Field(min_length=1, max_length=32)
    note: str = Field(min_length=1, max_length=500)
    remind_at: str = Field(min_length=1, max_length=64)


class ReminderUpdateRequest(StrictRequest):
    order_id: str | None = Field(default=None, min_length=1, max_length=32)
    note: str | None = Field(default=None, min_length=1, max_length=500)
    remind_at: str | None = Field(default=None, min_length=1, max_length=64)
    status: Literal["ACTIVE", "DONE", "CANCELLED"] | None = None


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(StrictRequest):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=60)
    invite_code: str | None = Field(default=None, max_length=200)


class LoginRequest(StrictRequest):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class ConversationCreateRequest(StrictRequest):
    title: str = Field(default="New conversation", min_length=1, max_length=100)


class ChatTurnRequest(StrictRequest):
    message: str = Field(min_length=1, max_length=2000)


class ChatMemoryPreferenceRequest(StrictRequest):
    enabled: bool


class ChatMemoryCreateRequest(StrictRequest):
    content: str = Field(min_length=1, max_length=500)


def _configured_path(value: str | None, default: Path) -> Path:
    if not value:
        return default
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _reject_unknown_query(request: Request, allowed: set[str]) -> None:
    unexpected = set(request.query_params.keys()) - allowed
    if unexpected:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail={"error": "Unsupported query parameter(s)", "parameters": sorted(unexpected)},
        )


def _tool_result(result: dict[str, Any]) -> dict[str, Any]:
    result_status = result.get("result_status")
    if result_status == "INVALID_INPUT":
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail=result)
    if result_status == "NOT_FOUND":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result)
    if result_status == "ERROR":
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=result)
    return result


def _action_result(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") != "REFUSED":
        return result
    code = (result.get("error") or {}).get("code")
    code_to_status = {
        "TARGET_NOT_RESOLVED": status.HTTP_404_NOT_FOUND,
        "NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "TOKEN_INVALID": status.HTTP_409_CONFLICT,
        "INVALID_INPUT": HTTPStatus.UNPROCESSABLE_ENTITY,
        "CLAIM_REQUIRED": HTTPStatus.UNPROCESSABLE_ENTITY,
        "TOKEN_REQUIRED": HTTPStatus.UNPROCESSABLE_ENTITY,
    }
    raise HTTPException(status_code=code_to_status.get(code, status.HTTP_400_BAD_REQUEST), detail=result)


def get_core(request: Request) -> Iterator[CopilotCore]:
    core = CopilotCore(
        data_dir=request.app.state.data_dir,
        db_path=request.app.state.db_path,
        config_path=request.app.state.config_path,
    )
    try:
        yield core
    finally:
        core.close()


def get_agent_store(request: Request) -> Iterator[AgentStore]:
    store = AgentStore(request.app.state.db_path)
    try:
        yield store
    finally:
        store.close()


def create_app(
    data_dir: str | Path | None = None,
    db_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> FastAPI:
    app = FastAPI(
        title="General Manager Co-Pilot API",
        version="1.0.0",
        description="HTTP API for deterministic, evidence-backed operations tools.",
    )
    app.state.data_dir = _configured_path(
        str(data_dir) if data_dir is not None else os.getenv("COPILOT_DATA_DIR"), DEFAULT_DATA_DIR
    )
    app.state.db_path = _configured_path(
        str(db_path) if db_path is not None else os.getenv("COPILOT_DB_PATH"), DEFAULT_DB_PATH
    )
    app.state.config_path = _configured_path(
        str(config_path) if config_path is not None else os.getenv("COPILOT_CONFIG_PATH"), DEFAULT_CONFIG_PATH
    )

    app.state.login_throttle = LoginThrottle()
    app.add_middleware(SessionMiddleware)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/orders", tags=["orders"])
    def search_orders(
        request: Request,
        order_id: str | None = None,
        customer: str | None = None,
        product: str | None = None,
        category: str | None = None,
        order_status: str | None = Query(default=None, alias="status"),
        stage: str | None = None,
        order_date_from: date | None = None,
        order_date_to: date | None = None,
        due_date_from: date | None = None,
        due_date_to: date | None = None,
        intent: Literal["LIST", "SINGLE", "SUMMARY"] = "LIST",
        match_mode: Literal["EXACT", "CONTAINS"] = "EXACT",
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        core: CopilotCore = Depends(get_core),
    ) -> dict[str, Any]:
        _reject_unknown_query(
            request,
            {
                "order_id", "customer", "product", "category", "status", "stage",
                "order_date_from", "order_date_to", "due_date_from", "due_date_to",
                "intent", "match_mode", "limit", "offset",
            },
        )
        result = core.search_orders(
            order_id=order_id,
            customer=customer,
            product=product,
            category=category,
            status=order_status,
            current_stage=stage,
            order_date_from=order_date_from.isoformat() if order_date_from else None,
            order_date_to=order_date_to.isoformat() if order_date_to else None,
            due_date_from=due_date_from.isoformat() if due_date_from else None,
            due_date_to=due_date_to.isoformat() if due_date_to else None,
            intent=intent,
            match_mode=match_mode,
            limit=limit,
            offset=offset,
        )
        return _tool_result(result)

    @app.get("/api/v1/production", tags=["production"])
    def production_output(
        request: Request,
        start: date,
        end: date,
        stage: list[str] | None = Query(default=None),
        include_closed_days: bool = False,
        core: CopilotCore = Depends(get_core),
    ) -> dict[str, Any]:
        _reject_unknown_query(request, {"start", "end", "stage", "include_closed_days"})
        return _tool_result(
            core.get_production_output(
                start.isoformat(), end.isoformat(), stage, include_closed_days
            )
        )

    @app.get("/api/v1/orders/{order_id}/risk", tags=["orders"])
    def order_risk(
        order_id: str, request: Request, core: CopilotCore = Depends(get_core)
    ) -> dict[str, Any]:
        _reject_unknown_query(request, set())
        return _tool_result(core.assess_order_risk(order_id))

    @app.get("/api/v1/production/normality", tags=["production"])
    def output_normality(
        request: Request,
        target_date: date = Query(alias="date"),
        stage: str = Query(min_length=1),
        core: CopilotCore = Depends(get_core),
    ) -> dict[str, Any]:
        _reject_unknown_query(request, {"date", "stage"})
        return _tool_result(core.assess_output_normality(target_date.isoformat(), stage))

    @app.post("/api/v1/feasibility", tags=["planning"])
    def feasibility(
        payload: FeasibilityRequest, core: CopilotCore = Depends(get_core)
    ) -> dict[str, Any]:
        return _tool_result(
            core.estimate_order_feasibility(
                payload.product,
                payload.category,
                payload.pieces,
                payload.requested_due_date.isoformat(),
                payload.allow_outsourcing,
            )
        )

    @app.post("/api/v1/brief", tags=["brief"])
    def generate_brief(
        payload: BriefRequest | None = None,
        core: CopilotCore = Depends(get_core),
    ) -> dict[str, Any]:
        payload = payload or BriefRequest()
        return _tool_result(
            core.discover_operational_issues(
                as_of_date=payload.as_of_date.isoformat() if payload.as_of_date else None,
                lookback_days=payload.lookback_days,
                max_findings=payload.max_findings,
            )
        )

    @app.get("/api/v1/claims/{claim_id}", tags=["evidence"])
    def trace_claim(claim_id: str, core: CopilotCore = Depends(get_core)) -> dict[str, Any]:
        result = core.trace_claim(claim_id)
        if result.get("status") == "INVALID_FORMAT":
            raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail=result)
        if result.get("status") == "NOT_FOUND":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result)
        return result

    @app.post("/api/v1/claims/{claim_id}/verify", tags=["evidence"])
    def verify_claim(claim_id: str, core: CopilotCore = Depends(get_core)) -> dict[str, Any]:
        result = core.trace_claim(claim_id, verify=True)
        if result.get("status") == "INVALID_FORMAT":
            raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail=result)
        if result.get("status") == "NOT_FOUND":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result)
        return result

    # ------------------------------------------------------------------ accounts
    @app.post("/api/v1/auth/register", tags=["auth"])
    def register(payload: RegisterRequest, request: Request, response: Response,
                 store: AgentStore = Depends(get_agent_store)) -> dict[str, str]:
        check_invite(request, payload.invite_code)
        email = payload.email.strip().lower()
        if not EMAIL_RE.match(email):
            raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="Enter a valid e-mail address.")
        if store.find_user_by_email(email):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this e-mail already exists.")
        user = store.create_user(email, payload.password, payload.display_name.strip() or email.split("@")[0])
        set_session_cookie(response, request, store.create_session(user["user_id"]))
        return user

    @app.post("/api/v1/auth/login", tags=["auth"])
    def login(payload: LoginRequest, request: Request, response: Response,
              store: AgentStore = Depends(get_agent_store)) -> dict[str, str]:
        email = payload.email.strip().lower()
        throttle: LoginThrottle = request.app.state.login_throttle
        throttle.check(email, request)
        user = store.authenticate(email, payload.password)
        if user is None:
            throttle.record_failure(email, request)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="E-mail or password is incorrect.")
        throttle.reset(email, request)
        set_session_cookie(response, request, store.create_session(user["user_id"]))
        return user

    @app.post("/api/v1/auth/logout", tags=["auth"])
    def logout(request: Request, response: Response, store: AgentStore = Depends(get_agent_store)) -> dict[str, bool]:
        store.delete_session(request.cookies.get("copilot_session"))
        clear_session_cookie(response)
        return {"signed_out": True}

    @app.get("/api/v1/auth/me", tags=["auth"])
    def me(request: Request) -> dict[str, str]:
        return current_user(request)

    # ------------------------------------------------------------------ per-user actions and reminders
    @app.post("/api/v1/actions", tags=["actions"])
    def prepare_action(
        payload: ActionPrepareRequest, user: dict = Depends(current_user), core: CopilotCore = Depends(get_core)
    ) -> dict[str, Any]:
        return _action_result(
            core.manage_action("PREPARE", payload.requester, payload.action_type, payload.target,
                               payload.payload, payload.claim_ids, owner_id=user["user_id"])
        )

    @app.post("/api/v1/actions/{token}/confirm", tags=["actions"])
    def confirm_action(token: str, user: dict = Depends(current_user), core: CopilotCore = Depends(get_core)) -> dict[str, Any]:
        return _action_result(core.manage_action("CONFIRM", "api", confirmation_token=token, owner_id=user["user_id"]))

    @app.post("/api/v1/actions/{token}/cancel", tags=["actions"])
    def cancel_action(token: str, user: dict = Depends(current_user), core: CopilotCore = Depends(get_core)) -> dict[str, Any]:
        return _action_result(core.manage_action("CANCEL", "api", confirmation_token=token, owner_id=user["user_id"]))

    @app.get("/api/v1/actions", tags=["actions"])
    def action_audit(
        request: Request, user: dict = Depends(current_user), core: CopilotCore = Depends(get_core)
    ) -> list[dict[str, Any]]:
        _reject_unknown_query(request, set())
        return core.action_audit(user["user_id"])

    @app.get("/api/v1/reminders", tags=["reminders"])
    def list_reminders(
        request: Request, include_closed: bool = False, user: dict = Depends(current_user),
        core: CopilotCore = Depends(get_core),
    ) -> list[dict[str, Any]]:
        _reject_unknown_query(request, {"include_closed"})
        return core.list_reminders(include_closed, user["user_id"])

    @app.post("/api/v1/reminders", tags=["reminders"])
    def create_reminder(payload: ReminderCreateRequest, user: dict = Depends(current_user),
                        core: CopilotCore = Depends(get_core)) -> dict[str, Any]:
        return _action_result(core.create_reminder(payload.order_id, payload.note, payload.remind_at, owner_id=user["user_id"]))

    @app.patch("/api/v1/reminders/{reminder_id}", tags=["reminders"])
    def update_reminder(
        reminder_id: str, payload: ReminderUpdateRequest, user: dict = Depends(current_user),
        core: CopilotCore = Depends(get_core),
    ) -> dict[str, Any]:
        return _action_result(core.update_reminder(reminder_id, payload.model_dump(exclude_none=True), user["user_id"]))

    # ------------------------------------------------------------------ per-user AI settings and memory
    @app.get("/api/v1/settings/ai", tags=["ai-settings"])
    def get_ai_settings(user: dict = Depends(current_user), store: AgentStore = Depends(get_agent_store)) -> dict[str, Any]:
        return store.get_ai_settings(user["user_id"])

    @app.get("/api/v1/settings/ai/catalog", tags=["ai-settings"])
    def get_ai_provider_catalog() -> dict[str, Any]:
        return {
            "providers": [
                {
                    "id": provider_id,
                    "label": config["label"],
                    "models": [{"id": item["id"], "label": item["label"]} for item in config["models"]],
                }
                for provider_id, config in PROVIDER_CATALOG.items()
            ]
        }

    @app.put("/api/v1/settings/ai", tags=["ai-settings"])
    def put_ai_settings(
        payload: AISettingsRequest, user: dict = Depends(current_user), store: AgentStore = Depends(get_agent_store)
    ) -> dict[str, Any]:
        api_key = payload.api_key.get_secret_value() if payload.api_key is not None else None
        current = store.get_ai_settings(user["user_id"])
        if api_key is None and current["has_api_key"] and current["provider"] != payload.provider:
            # A saved key belongs to its provider; never send one provider's key to another.
            label = PROVIDER_CATALOG[payload.provider]["label"]
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Enter an API key for {label}. The saved key belongs to a different provider.",
            )
        try:
            base_url = PROVIDER_CATALOG[payload.provider]["base_url"]
            return store.save_ai_settings(user["user_id"], payload.provider, base_url, payload.model, api_key)
        except CredentialEncryptionError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    @app.post("/api/v1/settings/ai/test", tags=["ai-settings"])
    async def test_ai_connection(user: dict = Depends(current_user), store: AgentStore = Depends(get_agent_store)) -> dict[str, str]:
        try:
            await AgentService(store, None, user["user_id"]).test_connection()  # type: ignore[arg-type]
        except AgentTurnError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return {"status": "ok", "message": "AI provider connection succeeded."}

    @app.delete("/api/v1/settings/ai/credential", tags=["ai-settings"])
    def delete_ai_credential(user: dict = Depends(current_user), store: AgentStore = Depends(get_agent_store)) -> dict[str, Any]:
        store.clear_api_key(user["user_id"])
        return store.get_ai_settings(user["user_id"])

    @app.get("/api/v1/settings/chat-memory", tags=["chat-settings"])
    def get_chat_memory_settings(user: dict = Depends(current_user), store: AgentStore = Depends(get_agent_store)) -> dict[str, bool]:
        return {"enabled": store.memory_enabled(user["user_id"])}

    @app.put("/api/v1/settings/chat-memory", tags=["chat-settings"])
    def put_chat_memory_settings(
        payload: ChatMemoryPreferenceRequest, user: dict = Depends(current_user), store: AgentStore = Depends(get_agent_store)
    ) -> dict[str, bool]:
        return {"enabled": store.set_memory_enabled(payload.enabled, user["user_id"])}

    @app.get("/api/v1/chat/memories", tags=["chat-memory"])
    def list_chat_memories(user: dict = Depends(current_user), store: AgentStore = Depends(get_agent_store)) -> list[dict[str, str]]:
        return store.list_memories(user["user_id"])

    @app.post("/api/v1/chat/memories", tags=["chat-memory"])
    def create_chat_memory(
        payload: ChatMemoryCreateRequest, user: dict = Depends(current_user), store: AgentStore = Depends(get_agent_store)
    ) -> dict[str, str]:
        if not store.memory_enabled(user["user_id"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Enable optional chat memory before saving a memory.",
            )
        return store.add_memory(payload.content, user["user_id"])

    @app.delete("/api/v1/chat/memories/{memory_id}", tags=["chat-memory"])
    def delete_chat_memory(memory_id: str, user: dict = Depends(current_user), store: AgentStore = Depends(get_agent_store)) -> dict[str, bool]:
        return {"deleted": store.delete_memory(memory_id, user["user_id"])}

    @app.delete("/api/v1/chat/memories", tags=["chat-memory"])
    def clear_chat_memories(user: dict = Depends(current_user), store: AgentStore = Depends(get_agent_store)) -> dict[str, int]:
        return {"deleted_count": store.clear_memories(user["user_id"])}

    # ------------------------------------------------------------------ per-user chat
    @app.post("/api/v1/chat/conversations", tags=["chat"])
    def create_chat_conversation(
        payload: ConversationCreateRequest, user: dict = Depends(current_user), store: AgentStore = Depends(get_agent_store)
    ) -> dict[str, str]:
        return store.create_conversation(payload.title, user["user_id"])

    @app.get("/api/v1/chat/conversations", tags=["chat"])
    def list_chat_conversations(user: dict = Depends(current_user), store: AgentStore = Depends(get_agent_store)) -> list[dict[str, Any]]:
        return store.list_conversations(user["user_id"])

    @app.get("/api/v1/chat/conversations/{conversation_id}", tags=["chat"])
    def get_chat_conversation(
        conversation_id: str, user: dict = Depends(current_user), store: AgentStore = Depends(get_agent_store)
    ) -> dict[str, Any]:
        conversation = store.get_conversation(conversation_id, user["user_id"])
        if conversation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation was not found.")
        return conversation

    @app.delete("/api/v1/chat/conversations/{conversation_id}", tags=["chat"])
    def delete_chat_conversation(
        conversation_id: str, user: dict = Depends(current_user), store: AgentStore = Depends(get_agent_store)
    ) -> dict[str, bool]:
        return {"deleted": store.delete_conversation(conversation_id, user["user_id"])}

    @app.post("/api/v1/chat/conversations/{conversation_id}/turns", tags=["chat"])
    async def chat_turn(
        conversation_id: str,
        payload: ChatTurnRequest,
        user: dict = Depends(current_user),
        core: CopilotCore = Depends(get_core),
        store: AgentStore = Depends(get_agent_store),
    ) -> dict[str, Any]:
        try:
            return await AgentService(store, core, user["user_id"]).run_turn(conversation_id, payload.message)
        except AgentTurnError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return app


app = create_app()