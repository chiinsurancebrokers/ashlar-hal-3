from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class SessionEvent(BaseModel):
    role: str
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationSession(BaseModel):
    session_id: str
    consent_to_retain: bool = False
    consent_to_transmit: bool = False
    created_at: datetime
    updated_at: datetime
    state: dict[str, Any] = Field(default_factory=dict)
    transcript: list[SessionEvent] = Field(default_factory=list)


# Deliberately process-local for the first safe rollout.  This prevents us from
# pretending persistence exists across deploys before an approved durable store
# and retention policy are configured.  The API exposes the same contract so a
# durable adapter can replace this implementation without changing the client.
_sessions: dict[str, ConversationSession] = {}
_lock = RLock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_session(*, consent_to_retain: bool = False, consent_to_transmit: bool = False) -> ConversationSession:
    now = _now()
    session = ConversationSession(
        session_id=f"HALS-{uuid4().hex[:16].upper()}",
        consent_to_retain=consent_to_retain,
        consent_to_transmit=consent_to_transmit,
        created_at=now,
        updated_at=now,
    )
    if consent_to_retain:
        with _lock:
            _sessions[session.session_id] = session
    return deepcopy(session)


def save_turn(session_id: str, *, state: dict[str, Any], user_message: str, assistant_message: str) -> ConversationSession:
    with _lock:
        session = _sessions.get(session_id)
        if session is None or not session.consent_to_retain:
            raise KeyError("Session is not retained or does not exist.")
        session.state = deepcopy(state)
        session.transcript.extend([
            SessionEvent(role="user", content=user_message[:4000]),
            SessionEvent(role="assistant", content=assistant_message[:8000]),
        ])
        session.updated_at = _now()
        return deepcopy(session)


def get_session(session_id: str) -> ConversationSession:
    with _lock:
        session = _sessions.get(session_id)
        if session is None:
            raise KeyError("Session not found.")
        return deepcopy(session)


def delete_session(session_id: str) -> bool:
    with _lock:
        return _sessions.pop(session_id, None) is not None


def fact_find_summary(session: ConversationSession) -> dict[str, Any]:
    """Return deterministic structured state; never summarize medical free text."""
    state = session.state or {}
    allowed = (
        "applicant_name", "age", "sex", "residence_country", "nationality",
        "primary_healthcare_country", "coverage_area", "budget_annual",
        "family_requested", "family_members", "family_household_size",
        "family_maternity_member_ids", "deductible", "inpatient", "outpatient",
        "dental", "optical", "maternity", "mental_health", "evacuation",
        "wellness", "pending_question",
    )
    return {
        "session_reference": session.session_id,
        "review_required": True,
        "generated_at": _now().isoformat(),
        "facts": {key: deepcopy(state[key]) for key in allowed if key in state},
    }
