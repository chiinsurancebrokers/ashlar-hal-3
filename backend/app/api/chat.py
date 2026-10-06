import json
from typing import Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from backend.app.core.rate_limit import client_ip
from backend.app.discovery.flow import next_discovery_question
from backend.app.services import usage_guard
from backend.app.services.scope_guard import is_off_topic, off_topic_reply

from backend.app.services.family_live_orchestrator import chat_turn
from backend.app.services.corporate_group_agent import corporate_chat_turn, is_corporate_intent

router = APIRouter(prefix="/chat", tags=["chat"])


class Message(BaseModel):
    role: str = Field(max_length=20)
    content: str

    @field_validator("content", mode="before")
    @classmethod
    def _trim(cls, value: Any) -> Any:
        return str(value)[:4000] if value is not None else ""


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    state: dict[str, Any] = {}
    history: list[Message] = Field(default_factory=list)

    @field_validator("history", mode="before")
    @classmethod
    def _recent_history(cls, value: Any) -> Any:
        # Only the last turns are ever used; never reject a long conversation.
        return value[-12:] if isinstance(value, list) else value

    @field_validator("state")
    @classmethod
    def _limit_state(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, default=str)) > 30000:
            raise ValueError("State is too large.")
        return value


def _off_topic_turn(req: ChatRequest) -> dict[str, Any]:
    state = dict(req.state or {})
    greek = state.get("language") == "el"
    state["_off_topic"] = int(state.get("_off_topic") or 0) + 1
    reply = off_topic_reply(greek, state.get("applicant_name"))
    quick: list = []
    if state.get("pending_question") and not state.get("discovery_complete"):
        q = next_discovery_question(state, greek)
        if q:
            reply += " " + q["reply"]
            quick = q.get("quick_replies", [])
    return {"reply": reply, "state": state, "quotes": [], "excluded_plans": [], "ai_status": "off_topic",
            "journey": state.get("journey") or "undetermined", "lead_cta": {"show": False},
            "open_application_form": False, "quick_replies": quick}


@router.post("/turn")
async def turn(req: ChatRequest, request: Request):
    if is_off_topic(req.message):
        return _off_topic_turn(req)  # no AI call for obvious misuse
    calls = int((req.state or {}).get("_ai_calls") or 0)
    if int((req.state or {}).get("_off_topic") or 0) >= 3:
        calls = 10**6  # repeated misuse: this conversation continues without AI
    token = usage_guard.bind(client_ip(request), calls)
    try:
        if is_corporate_intent(req.message, req.state):
            result = corporate_chat_turn(req.message, req.state)
        else:
            result = await chat_turn(req.message, req.state, [m.model_dump() for m in req.history])
        used = usage_guard.conversation_calls()
        if isinstance(result, dict) and isinstance(result.get("state"), dict) and used is not None and used < 10**6:
            result["state"]["_ai_calls"] = used
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"HAL conversational service failed: {str(exc)[:180]}")
    finally:
        usage_guard.unbind(token)
