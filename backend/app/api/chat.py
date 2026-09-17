from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.agents.contracts import SpecialistName
from backend.app.agents.orchestrator import get_ashlar_orchestrator

router = APIRouter(prefix="/chat", tags=["chat"])


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    state: dict[str, Any] = {}
    history: list[Message] = []


def _case_id_from_state(state: dict[str, Any]) -> UUID | None:
    raw = state.get("_adviser_os_case_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


def _legacy_chat_payload(*, req: ChatRequest, result) -> dict[str, Any]:
    """Preserve the established HAL browser contract over Adviser OS.

    Normal discovery/advice still returns the exact legacy payload produced by
    ``hal_adviser``. Specialist routes return a minimal compatible chat payload
    so the current UI can display them without knowing specialist internals yet.
    """
    if result.responses:
        primary = result.responses[0]
        if primary.specialist == SpecialistName.HAL_ADVISER and primary.payload:
            payload = dict(primary.payload)
        else:
            payload = {
                "reply": primary.reply or "I need a little more information to continue.",
                "state": dict(req.state),
                "quick_replies": [],
            }
    else:
        payload = {
            "reply": "I have processed that request through the Ashlar Orchestrator.",
            "state": dict(req.state),
            "quick_replies": [],
        }

    payload["_adviser_os"] = result.model_dump(mode="json")
    return payload


@router.post("/turn")
async def turn(req: ChatRequest):
    history = [m.model_dump() for m in req.history]
    state = dict(req.state)
    case_token = str(state.get("_adviser_os_case_token") or "").strip()
    context: dict[str, Any] = {
        "state": state,
        "history": history,
        "health_history": history,
        "language": state.get("language") or "en",
    }
    if case_token:
        context["case_token"] = case_token

    try:
        result = await get_ashlar_orchestrator().handle(
            case_id=_case_id_from_state(state),
            message=req.message,
            context=context,
        )
        return _legacy_chat_payload(req=req, result=result)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"HAL conversational service failed: {str(exc)[:180]}")
