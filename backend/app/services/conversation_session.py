from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field

from backend.app.core.config import get_settings


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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _config() -> tuple[str, str]:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("Durable HAL session persistence is not configured.")
    return settings.supabase_url.rstrip("/"), settings.supabase_service_role_key


def _rpc(name: str, payload: dict[str, Any]) -> Any:
    url, key = _config()
    try:
        response = httpx.post(
            f"{url}/rest/v1/rpc/{name}",
            headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError("HAL session store is temporarily unavailable.") from exc
    if response.status_code == 404 or response.status_code == 406:
        raise KeyError("Session not found.")
    if response.status_code >= 400:
        detail = response.text.lower()
        if "does not exist" in detail or "not retained" in detail or "p0002" in detail:
            raise KeyError("Session is not retained or does not exist.")
        raise RuntimeError(f"HAL session store rejected the request ({response.status_code}).")
    return response.json() if response.content else None


def _from_row(row: dict[str, Any]) -> ConversationSession:
    transcript = row.get("transcript") or []
    return ConversationSession(
        session_id=row["session_reference"],
        consent_to_retain=bool(row.get("consent_to_retain")),
        consent_to_transmit=bool(row.get("consent_to_transmit")),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        state=row.get("state_json") or {},
        transcript=[SessionEvent.model_validate(event) for event in transcript],
    )


def create_session(*, consent_to_retain: bool = False, consent_to_transmit: bool = False) -> ConversationSession:
    now = _now()
    session_id = f"HALS-{uuid4().hex[:16].upper()}"
    if not consent_to_retain:
        return ConversationSession(
            session_id=session_id,
            consent_to_retain=False,
            consent_to_transmit=consent_to_transmit,
            created_at=now,
            updated_at=now,
        )
    row = _rpc("hal_create_session", {
        "p_session_reference": session_id,
        "p_consent_to_retain": True,
        "p_consent_to_transmit": consent_to_transmit,
    })
    # PostgREST may serialize a composite result as an object or a one-row list.
    if isinstance(row, list):
        if not row:
            raise RuntimeError("HAL session store returned no created session.")
        row = row[0]
    return _from_row(row)


def save_turn(session_id: str, *, state: dict[str, Any], user_message: str, assistant_message: str) -> ConversationSession:
    _rpc("hal_save_turn", {
        "p_session_reference": session_id,
        "p_state": deepcopy(state),
        "p_user_message": user_message[:4000],
        "p_assistant_message": assistant_message[:8000],
    })
    return get_session(session_id)


def get_session(session_id: str) -> ConversationSession:
    rows = _rpc("hal_get_session", {"p_session_reference": session_id})
    if not rows:
        raise KeyError("Session not found.")
    if isinstance(rows, dict):
        return _from_row(rows)
    return _from_row(rows[0])


def delete_session(session_id: str) -> bool:
    return bool(_rpc("hal_delete_session", {"p_session_reference": session_id}))


# Only deterministic, application-relevant structured facts may leave the
# retained HAL session through the Fact Find/handoff path. Medical free text,
# transcript content and unknown future state fields are intentionally excluded.
_FACT_FIND_ALLOWED = (
    "applicant_name", "age", "sex", "residence_country", "nationality",
    "primary_healthcare_country", "coverage_area", "budget_annual",
    "family_requested", "family_household_size", "deductible", "inpatient",
    "outpatient", "dental", "optical", "maternity", "mental_health",
    "evacuation", "wellness", "selected_plan_keys", "household_quote",
)
_MEMBER_ALLOWED = ("member_id", "relationship", "age", "sex")
_REQUIREMENT_ALLOWED = (
    "maternity", "outpatient", "dental", "optical", "mental_health",
    "evacuation", "wellness", "deductible", "coverage_area",
)


def _sanitized_members(state: dict[str, Any]) -> list[dict[str, Any]]:
    raw_members = state.get("household_members") or state.get("family_members") or []
    result: list[dict[str, Any]] = []
    for raw in raw_members:
        if not isinstance(raw, dict):
            continue
        member = {key: deepcopy(raw[key]) for key in _MEMBER_ALLOWED if key in raw}
        requirements = raw.get("requirements")
        if isinstance(requirements, dict):
            safe_requirements = {
                key: deepcopy(requirements[key]) for key in _REQUIREMENT_ALLOWED if key in requirements
            }
            if safe_requirements:
                member["requirements"] = safe_requirements
        # Some discovery states keep member-specific requirements flattened.
        for key in _REQUIREMENT_ALLOWED:
            if key in raw and key not in member:
                member[key] = deepcopy(raw[key])
        if member:
            result.append(member)
    return result


def fact_find_summary(session: ConversationSession) -> dict[str, Any]:
    """Build a deterministic review payload with no transcript/medical free text."""
    state = session.state or {}
    facts = {key: deepcopy(state[key]) for key in _FACT_FIND_ALLOWED if key in state}
    members = _sanitized_members(state)
    if members:
        facts["household_members"] = members
    return {
        "session_reference": session.session_id,
        "review_required": True,
        "generated_at": _now().isoformat(),
        "facts": facts,
    }
