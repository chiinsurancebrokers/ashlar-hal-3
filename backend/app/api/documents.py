from __future__ import annotations

import os
import hmac
from pathlib import Path
import tempfile
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Header
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from backend.app.core.config import get_settings
from backend.app.cases.models import CaseDocument
from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.documents.brochure_tables import extract_target_plan_from_pdf
from backend.app.documents.extraction import extract_document
from backend.app.documents.store import DOCUMENT_EVIDENCE_STORE


router = APIRouter(prefix="/documents", tags=["adviser-os-documents"])

_MAX_UPLOAD_BYTES = 15 * 1024 * 1024
_ALLOWED_SUFFIXES = {".pdf", ".txt", ".html", ".htm"}
_ROLE_TO_TYPE = {
    "quotation": "quotation",
    "brochure": "brochure",
    "wording": "policy_wording",
    "existing_policy": "existing_policy",
    "issued_policy": "policy_schedule",
    "application": "application",
    "claim": "claim_document",
    "preauthorisation": "preauthorisation",
    "carrier_response": "carrier_response",
}


def _clean_label(value: str, *, name: str, max_length: int) -> str:
    cleaned = " ".join(str(value or "").split()).strip()
    if not cleaned or len(cleaned) > max_length:
        raise HTTPException(status_code=422, detail=f"{name} is required and must be at most {max_length} characters.")
    return cleaned


@router.post("/upload")
async def upload_carrier_document(
    case_id: UUID = Form(...),
    case_token: str = Form(...),
    provider_label: str = Form(...),
    target_plan: str = Form(...),
    role: Literal["quotation", "brochure", "wording", "existing_policy", "issued_policy", "application", "claim", "preauthorisation", "carrier_response"] = Form(...),
    plan_key: str | None = Form(default=None),
    file: UploadFile = File(...),
    x_admin_password: str | None = Header(default=None, alias="X-Admin-Password"),
):
    """Extract a carrier document server-side and return only an opaque ref.

    The public browser never sends extracted carrier text or model output back
    into the evidence engine. The opaque reference is bound to the active case
    and its access token and expires with the short-lived document store.
    """

    if not case_token or len(case_token) > 256:
        raise HTTPException(status_code=404, detail="Active case not found.")
    record = CASE_ANALYSIS_STORE.get(case_id, case_token)
    if record is None:
        raise HTTPException(status_code=404, detail="Active case not found or expired.")

    if role in {"issued_policy", "claim", "preauthorisation", "carrier_response"} and os.getenv("POST_SALE_SYSTEM_OF_RECORD", "chi_portal").casefold() != "ashlar":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "chi_portal_handoff",
                "message": "Post-sale documents are stored in the CHI Insurance Portal.",
                "portal_url": os.getenv("CHI_PORTAL_URL", "https://portalchiinsurance.up.railway.app/login"),
            },
        )

    if role not in {"existing_policy", "application", "claim", "preauthorisation"}:
        expected = get_settings().admin_password
        if not expected:
            raise HTTPException(status_code=503, detail="Broker document uploads require ADMIN_PASSWORD configuration.")
        if not x_admin_password or not hmac.compare_digest(x_admin_password, expected):
            raise HTTPException(status_code=403, detail="Broker credentials are required for new carrier documents.")

    provider = _clean_label(provider_label, name="provider_label", max_length=120)
    target = _clean_label(target_plan, name="target_plan", max_length=200)
    resolved_plan_key = _clean_label(plan_key, name="plan_key", max_length=200) if plan_key else None
    selected_plan_keys = [str(value) for value in record.case.selected_plan_keys if str(value)]
    if role == "existing_policy":
        # A client's current policy is a baseline for comparison, not one of
        # the shortlisted replacement plans.
        resolved_plan_key = "existing_policy"
    elif role in {"claim", "preauthorisation", "carrier_response"} and record.case.policy:
        resolved_plan_key = record.case.policy["plan_key"]
    else:
        if resolved_plan_key is None:
            if len(selected_plan_keys) == 1:
                resolved_plan_key = selected_plan_keys[0]
            elif selected_plan_keys:
                raise HTTPException(status_code=422, detail="plan_key is required when the case contains multiple selected plans.")
        if resolved_plan_key and selected_plan_keys and resolved_plan_key not in selected_plan_keys:
            raise HTTPException(status_code=422, detail="The document plan_key is not selected in the active case.")

    # When the case already has a server-built comparison, plan identity comes
    # from that record rather than browser labels.
    matching_result = next((
        item for item in record.results
        if str(item.get("plan_key") or "") == str(resolved_plan_key or "")
    ), None)
    if matching_result is not None:
        provider = _clean_label(matching_result.get("provider"), name="provider_label", max_length=120)
        target = _clean_label(matching_result.get("target_plan"), name="target_plan", max_length=200)

    filename = Path(file.filename or "carrier-document").name
    suffix = Path(filename).suffix.casefold()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="Supported document types are PDF, TXT and HTML.")

    payload = await file.read(_MAX_UPLOAD_BYTES + 1)
    if not payload:
        raise HTTPException(status_code=422, detail="The uploaded document is empty.")
    if len(payload) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Carrier documents are limited to 15 MB each.")

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(payload)
            temp_path = tmp.name

        extraction = await run_in_threadpool(extract_document, temp_path, filename)
        if not extraction.ok:
            raise HTTPException(status_code=422, detail=extraction.error or "Document extraction failed.")

        focused_context = ""
        isolated_rows = 0
        if role == "brochure" and suffix == ".pdf":
            isolated = await run_in_threadpool(extract_target_plan_from_pdf, temp_path, target)
            focused_context = isolated.to_prompt_context() if isolated.rows else ""
            isolated_rows = len(isolated.rows)

        case = record.case.model_copy(deep=True)
        existing = next((
            doc for doc in case.documents
            if doc.sha256 == extraction.content_hash
            and doc.plan_key == resolved_plan_key
            and str(doc.metadata.get("role") or "") == role
        ), None)
        document = existing or CaseDocument(
            filename=filename,
            document_type=_ROLE_TO_TYPE[role],
            provider=provider,
            plan_key=resolved_plan_key,
            sha256=extraction.content_hash,
            metadata={
                "role": role,
                "target_plan": target,
                "pages": extraction.pages,
                "target_plan_isolated": bool(focused_context),
                "isolated_table_rows": isolated_rows,
            },
        )
        if existing is None:
            case.documents.append(document)
            case.touch()
            if CASE_ANALYSIS_STORE.save_case(case=case, access_token=case_token) is None:
                raise HTTPException(status_code=409, detail="The case expired while the document was being uploaded.")

        stored = DOCUMENT_EVIDENCE_STORE.put(
            case_id=case_id,
            case_token=case_token,
            document=document,
            provider_label=provider,
            target_plan=target,
            role=role,
            extracted_text=extraction.text,
            focused_table_context=focused_context,
            plan_key=resolved_plan_key,
            original_bytes=payload,
        )
        latest = CASE_ANALYSIS_STORE.get(case_id, case_token)
        if latest is None:
            raise HTTPException(409, "Case unavailable after upload.")
        latest.case.metadata.setdefault("document_refs", {})[stored.document_ref] = str(document.document_id)
        if CASE_ANALYSIS_STORE.save_case(case=latest.case, access_token=case_token) is None:
            raise HTTPException(409, "Case changed during upload; retry.")
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        await file.close()

    return JSONResponse(
        content={
            "case_id": str(case_id),
            "document_ref": stored.document_ref,
            "document_id": str(document.document_id),
            "filename": document.filename,
            "role": role,
            "provider": provider,
            "target_plan": target,
            "plan_key": resolved_plan_key,
            "comparison_role": "current_policy" if role == "existing_policy" else "candidate_plan",
            "pages": extraction.pages,
            "target_plan_isolated": bool(focused_context),
            "isolated_table_rows": isolated_rows,
        },
        headers={"Cache-Control": "no-store"},
    )


__all__ = ["router"]
