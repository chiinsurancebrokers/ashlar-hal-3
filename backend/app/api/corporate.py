from __future__ import annotations

import base64
import csv
import io
import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import EmailStr, TypeAdapter, ValidationError

from backend.app.core.config import get_settings
from backend.app.services.corporate_group_agent import group_fact_find_summary, mhd_option_unlocked

router = APIRouter(prefix="/corporate", tags=["corporate-group"])

MAX_CENSUS_BYTES = 5 * 1024 * 1024
ALLOWED_CENSUS_TYPES = {".csv", ".xlsx"}
SENSITIVE_HEADER_TERMS = {
    "diagnosis", "diagnoses", "medical history", "condition", "conditions", "medication",
    "treatment", "claim", "claims", "disability", "symptom", "symptoms", "icd",
}


def _validate_census(filename: str, content: bytes) -> None:
    lower = (filename or "").lower()
    if not any(lower.endswith(ext) for ext in ALLOWED_CENSUS_TYPES):
        raise HTTPException(status_code=400, detail="Census file must be CSV or XLSX.")
    if not content or len(content) > MAX_CENSUS_BYTES:
        raise HTTPException(status_code=400, detail="Census file must be non-empty and no larger than 5 MB.")
    if lower.endswith(".csv"):
        try:
            text = content.decode("utf-8-sig")
            headers = next(csv.reader(io.StringIO(text)), [])
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Census CSV could not be read.") from exc
        normalized = {h.strip().lower() for h in headers}
        flagged = sorted(h for h in normalized if any(term in h for term in SENSITIVE_HEADER_TERMS))
        if flagged:
            raise HTTPException(
                status_code=400,
                detail="Please remove medical/clinical columns from the census before upload: " + ", ".join(flagged[:8]),
            )


async def _send_group_enquiry(*, email: str, name: str, company: str, state: dict, census_name: str | None, census: bytes | None) -> dict:
    settings = get_settings()
    if not settings.resend_api_key or not settings.resend_from_email:
        raise RuntimeError("Resend delivery is not configured.")
    if not settings.gmail_lead_recipient:
        raise RuntimeError("Lead recipient is not configured.")

    employee_count = int(state.get("employee_count") or 0)
    # Server-side enforcement: a browser cannot forge MHD availability.
    if state.get("mhd_requested") and not mhd_option_unlocked(employee_count):
        state = {**state, "mhd_requested": False, "mhd_option_unlocked": False}

    reference = f"HAL-GROUP-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"
    summary = group_fact_find_summary(state)
    subject = f"New HAL Group Enquiry — {company or name} — {reference}"[:240]
    text = (
        f"New Ashlar Corporate / Group enquiry\n\nReference: {reference}\nContact: {name}\n"
        f"Email: {email}\nCompany: {company}\n\nGroup Fact Find Summary\n{summary}\n\n"
        "Census handling note: census files are requested for administrative quoting data only; medical/clinical data should not be included."
    )
    payload = {
        "from": f"{settings.resend_from_name} <{settings.resend_from_email}>" if settings.resend_from_name else settings.resend_from_email,
        "to": [settings.gmail_lead_recipient],
        "subject": subject,
        "text": text,
        "reply_to": [settings.resend_reply_to or email],
    }
    if census_name and census:
        payload["attachments"] = [{"filename": census_name, "content": base64.b64encode(census).decode("ascii")}]

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}", "Content-Type": "application/json"},
            json=payload,
        )
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f"Resend API returned {response.status_code}: {(response.text or '')[:300]}")
    return {"status": "sent", "reference": reference, "transport": "resend", "message_id": response.json().get("id")}


@router.post("/enquiry")
async def corporate_enquiry(
    contact_name: str = Form(..., min_length=1, max_length=160),
    email: str = Form(..., max_length=254),
    company_name: str = Form("", max_length=160),
    fact_find_json: str = Form(..., max_length=20000),
    consent: bool = Form(...),
    no_medical_data_confirmed: bool = Form(...),
    census: UploadFile | None = File(default=None),
):
    if not consent:
        raise HTTPException(status_code=400, detail="Consent is required before sending the enquiry.")
    if census is not None and not no_medical_data_confirmed:
        raise HTTPException(status_code=400, detail="Confirm that the census contains no medical or clinical information before upload.")
    try:
        validated_email = str(TypeAdapter(EmailStr).validate_python(email))
        state = json.loads(fact_find_json)
        if not isinstance(state, dict):
            raise ValueError("fact_find_json must be an object")
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid group enquiry data.") from exc

    content = None
    filename = None
    if census is not None:
        filename = (census.filename or "census").split("/")[-1].split("\\")[-1][:180]
        content = await census.read(MAX_CENSUS_BYTES + 1)
        _validate_census(filename, content)

    try:
        return await _send_group_enquiry(
            email=validated_email, name=contact_name.strip(), company=company_name.strip(),
            state=state, census_name=filename, census=content,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
