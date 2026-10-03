from __future__ import annotations
from copy import deepcopy
import httpx
from backend.app.core.config import get_settings


async def prefill_proposal_studio(session_reference: str, facts: dict, contact: dict) -> dict:
    settings = get_settings()
    if not settings.proposal_studio_api_url or not settings.proposal_studio_api_key:
        return {"status": "not_configured", "session_reference": session_reference}
    payload = {
        "external_reference": session_reference,
        "source": "hal",
        "fact_find": deepcopy(facts),
        "contact": {key: str(contact.get(key) or "") for key in ("first_name", "last_name", "email", "phone")},
    }
    try:
        async with httpx.AsyncClient(timeout=settings.proposal_studio_timeout_seconds) as client:
            response = await client.post(
                settings.proposal_studio_api_url.rstrip("/") + "/api/v1/hal/prefill",
                headers={"X-HAL-Bridge-Key": settings.proposal_studio_api_key, "Idempotency-Key": session_reference},
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise RuntimeError("Proposal Studio handoff is temporarily unavailable.") from exc
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f"Proposal Studio rejected HAL handoff ({response.status_code}).")
    body = response.json() if response.content else {}
    return {
        "status": "prefilled",
        "session_reference": session_reference,
        "case_reference": body.get("case_reference") or session_reference,
        "case_id": body.get("case_id"),
    }
