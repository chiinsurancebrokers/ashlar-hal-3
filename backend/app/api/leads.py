from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from backend.app.services.leads import send_lead, send_comparison_email

router = APIRouter(prefix="/leads", tags=["leads"])


class LeadRequest(BaseModel):
    insurance_interest: str = Field(max_length=80)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    phone: str = Field(default="", max_length=60)
    residence_country: str = Field(default="", max_length=100)
    age: str = Field(default="", max_length=10)
    coverage_area: str = Field(default="", max_length=120)
    family_members: str = Field(default="", max_length=120)
    budget: str = Field(default="", max_length=80)
    message: str = Field(default="", max_length=2500)
    applicant_state: dict = Field(default_factory=dict)
    plan_keys: list[str] = Field(default_factory=list, max_length=4)
    consent: bool
    website: str = Field(default="", max_length=200)  # honeypot


@router.post("")
async def create_lead(req: LeadRequest):
    if req.website.strip():
        return {"status": "accepted", "reference": "HAL-SPAM-FILTERED"}
    if not req.consent:
        raise HTTPException(status_code=400, detail="Consent is required before sending the enquiry.")
    try:
        return await send_lead(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Lead delivery failed: {str(exc)[:180]}") from exc


class ComparisonRequest(BaseModel):
    name: str = Field(default="", max_length=120)
    email: EmailStr
    applicant_state: dict = Field(default_factory=dict)
    plan_keys: list[str] = Field(min_length=1, max_length=10)


@router.post("/comparison")
async def send_comparison(req: ComparisonRequest):
    """Note: this endpoint NEVER accepts a premium/price from the client.
    It recomputes the shortlist server-side from applicant_state and only
    emails plans that are currently genuinely eligible — see
    services/leads.py::_verified_plans_for and its tests."""
    try:
        return await send_comparison_email(req.name, req.email, req.applicant_state, req.plan_keys)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Comparison delivery failed: {str(exc)[:180]}") from exc
