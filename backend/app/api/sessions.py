from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from backend.app.services.conversation_session import (
    create_session, delete_session, fact_find_summary, get_session, save_turn,
)
from backend.app.services.fact_find_handoff import prepare_handoff, submit_handoff

router = APIRouter(prefix="/sessions", tags=["sessions"])


class SessionCreate(BaseModel):
    consent_to_retain: bool = False
    consent_to_transmit: bool = False


class SessionTurn(BaseModel):
    state: dict[str, Any] = Field(default_factory=dict)
    user_message: str = Field(min_length=1, max_length=4000)
    assistant_message: str = Field(default="", max_length=8000)


class HandoffSubmit(BaseModel):
    reviewed_facts: dict[str, Any] = Field(default_factory=dict)
    contact: dict[str, str] = Field(default_factory=dict)


@router.post("")
def start_session(req: SessionCreate):
    session = create_session(
        consent_to_retain=req.consent_to_retain,
        consent_to_transmit=req.consent_to_transmit,
    )
    return {
        "session_reference": session.session_id,
        "retained": session.consent_to_retain,
        "transmission_allowed": session.consent_to_transmit,
    }


@router.post("/{session_id}/turn")
def persist_turn(session_id: str, req: SessionTurn):
    try:
        session = save_turn(
            session_id, state=req.state,
            user_message=req.user_message,
            assistant_message=req.assistant_message,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"session_reference": session.session_id, "updated_at": session.updated_at}


@router.get("/{session_id}")
def resume_session(session_id: str):
    try:
        session = get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "session_reference": session.session_id,
        "state": session.state,
        "transcript": [event.model_dump(mode="json") for event in session.transcript],
        "updated_at": session.updated_at,
    }


@router.get("/{session_id}/summary")
def session_summary(session_id: str):
    try:
        session = get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return fact_find_summary(session)


@router.get("/{session_id}/handoff")
def handoff_preview(session_id: str):
    try:
        return prepare_handoff(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{session_id}/handoff")
async def handoff_submit(session_id: str, req: HandoffSubmit):
    try:
        return await submit_handoff(session_id, req.reviewed_facts, req.contact)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.delete("/{session_id}", status_code=204)
def erase_session(session_id: str):
    delete_session(session_id)
    return Response(status_code=204)
