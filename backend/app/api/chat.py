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


def _document_refs_from_state(state: dict[str, Any]) -> list[str]:
    raw = state.get("_adviser_os_document_refs")
    if not isinstance(raw, list):
        return []
    refs: list[str] = []
    seen: set[str] = set()
    for value in raw[:12]:
        ref = str(value or "").strip()
        if not ref or len(ref) > 256 or ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    return refs


def _preserve_adviser_os_state(payload: dict[str, Any], request_state: dict[str, Any]) -> None:
    state = payload.get("state")
    if not isinstance(state, dict):
        state = dict(request_state)
        payload["state"] = state
    for key, value in request_state.items():
        if str(key).startswith("_adviser_os_"):
            state[key] = value


def _legacy_chat_payload(*, req: ChatRequest, result) -> dict[str, Any]:
    """Preserve the established HAL browser contract over Adviser OS."""
    if result.responses:
        primary = result.responses[-1]
        is_legacy_hal_payload = (
            primary.specialist == SpecialistName.HAL_ADVISER
            and isinstance(primary.payload, dict)
            and ("state" in primary.payload or "reply" in primary.payload)
        )
        if is_legacy_hal_payload:
            payload = dict(primary.payload)
            # SpecialistResponse.reply is the canonical conversational answer.
            # Preserve it when an Adviser OS continuation payload carries state
            # and workflow UI data but does not duplicate the reply field.
            payload.setdefault("reply", primary.reply or "")
        else:
            payload = {
                "reply": primary.reply or "I need a little more information to continue.",
                "state": dict(req.state),
                "quick_replies": [],
            }

        proposal_response = next(
            (
                response
                for response in reversed(result.responses)
                if response.specialist == SpecialistName.PROPOSAL_WRITER
            ),
            None,
        )
        if proposal_response is not None:
            downloads = proposal_response.payload.get("downloads") if proposal_response.payload else None
            if isinstance(downloads, dict) and downloads:
                payload["proposal_downloads"] = dict(downloads)
                payload["proposal_id"] = proposal_response.payload.get("proposal_id")
                payload["proposal_expires_at"] = proposal_response.payload.get("expires_at")
    else:
        payload = {
            "reply": "I have processed that request through the Ashlar Orchestrator.",
            "state": dict(req.state),
            "quick_replies": [],
        }

    _preserve_adviser_os_state(payload, req.state)
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
    document_refs = _document_refs_from_state(state)
    if document_refs:
        context["document_refs"] = document_refs

    try:
        result = await get_ashlar_orchestrator().handle(
            case_id=_case_id_from_state(state),
            message=req.message,
            context=context,
        )
        return _legacy_chat_payload(req=req, result=result)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"HAL conversational service failed: {str(exc)[:180]}")
