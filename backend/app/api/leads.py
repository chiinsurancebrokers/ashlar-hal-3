import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator

from backend.app.services.lead_store import mark_delivery, store_lead
from backend.app.services.leads import send_lead, send_comparison_email, send_lead_ack

router = APIRouter(prefix="/leads", tags=["leads"])
log = logging.getLogger("hal.leads")

# Shown to the client only when the request could be neither saved nor emailed.
UNAVAILABLE_DETAIL = ("We could not send your request just now. Please try again in a few minutes "
                      "or email info@ashlarassurance.com.")
COMPARISON_PENDING_DETAIL = ("We could not email your comparison just now. An Ashlar adviser has your "
                             "request and will send it to you shortly.")


def new_lead_reference() -> str:
    return f"HAL-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"


async def _store(kind: str, reference: str, payload: dict[str, Any]) -> bool:
    """Save the lead before any email goes out. Returns False (and logs) on failure."""
    try:
        await store_lead(kind, reference, payload)
        return True
    except Exception as exc:
        log.error("%s %s: NOT STORED in hal_leads: %s", kind, reference, exc)
        return False


class LeadRequest(BaseModel):
    insurance_interest: str = Field(max_length=80)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    phone: str = Field(default="", max_length=60)
    residence_country: str = Field(default="", max_length=100)
    age: str = Field(default="", max_length=10)
    date_of_birth: str = Field(default="", max_length=10)
    coverage_area: str = Field(default="", max_length=120)
    family_members: str = Field(default="", max_length=120)
    budget: str = Field(default="", max_length=80)
    message: str = Field(default="", max_length=2500)
    consent: bool
    website: str = Field(default="", max_length=200)  # honeypot
    # What HAL collected and showed on screen (needs, household, prices).
    hal_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("hal_context")
    @classmethod
    def _limit_context(cls, value: dict[str, Any]) -> dict[str, Any]:
        import json
        if len(json.dumps(value, default=str)) > 20000:
            raise ValueError("HAL context is too large.")
        return value


@router.post("")
async def create_lead(req: LeadRequest):
    if req.website.strip():
        return {"status": "accepted", "reference": "HAL-SPAM-FILTERED"}
    if not req.consent:
        raise HTTPException(status_code=400, detail="Consent is required before sending the enquiry.")
    payload = req.model_dump()
    reference = new_lead_reference()
    # 1. Save first: a broken mail key must never lose a prospect.
    stored = await _store("proposal", reference, payload)
    # 2. Then email the adviser.
    try:
        result = await send_lead(payload, reference=reference)
    except Exception as exc:
        log.error("proposal %s: adviser email FAILED (stored=%s): %s", reference, stored, exc)
        if not stored:
            raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from exc
        await mark_delivery(reference, sent=False, error=str(exc))
        result = {"status": "received", "reference": reference, "delivered": False}
    else:
        if stored:
            await mark_delivery(reference, sent=True, transport=result.get("transport"))
        result["delivered"] = True
    result["stored"] = stored
    # Confirmation to the client (best effort: the enquiry itself is already with Ashlar).
    try:
        await send_lead_ack(payload, str(result.get("reference") or reference))
        result["ack_sent"] = True
    except Exception as exc:
        log.warning("proposal %s: client confirmation email failed: %s", reference, exc)
        result["ack_sent"] = False
    # An adviser now has the enquiry: the "any questions?" check-in is no
    # longer needed (the expiry reminder stays).
    saved_ref = str((req.hal_context or {}).get("saved_quote_reference") or "").strip().upper()
    if saved_ref:
        try:
            from backend.app.services.followups import cancel_followups
            from backend.app.services.saved_quotes import REFERENCE_RE
            if REFERENCE_RE.match(saved_ref):
                cancel_followups(saved_ref, f"proposal requested ({result.get('reference')})", kinds=("checkin",))
        except Exception:
            pass
    return result



class ComparisonRequest(BaseModel):
    name: str = Field(default="", max_length=120)
    email: EmailStr
    applicant_state: dict = Field(default_factory=dict)
    plan_keys: list[str] = Field(min_length=1, max_length=10)
    current_policy_token: str | None = Field(default=None, max_length=50000)


@router.post("/comparison")
async def send_comparison(req: ComparisonRequest):
    """Note: this endpoint NEVER accepts a premium/price from the client.
    It recomputes the shortlist server-side from applicant_state and only
    emails plans that are currently genuinely eligible — see
    services/leads.py::_verified_plans_for and its tests."""
    reference = new_lead_reference()
    stored = await _store("comparison", reference, {
        **req.model_dump(exclude={"current_policy_token"}),
        "current_policy_included": bool(req.current_policy_token),
    })
    try:
        result = await send_comparison_email(
            req.name, req.email, req.applicant_state, req.plan_keys,
            current_policy_token=req.current_policy_token,
        )
    except ValueError as exc:
        if stored:
            await mark_delivery(reference, sent=False, error=f"rejected: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.error("comparison %s: email FAILED (stored=%s): %s", reference, stored, exc)
        if stored:
            await mark_delivery(reference, sent=False, error=str(exc))
        raise HTTPException(status_code=503,
                            detail=COMPARISON_PENDING_DETAIL if stored else UNAVAILABLE_DETAIL) from exc
    if stored:
        await mark_delivery(reference, sent=True, transport=result.get("transport"))
    return {**result, "reference": reference, "stored": stored}
