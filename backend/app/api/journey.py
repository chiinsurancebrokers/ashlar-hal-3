from __future__ import annotations

import hmac
import os
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.app.agents.orchestrator import get_ashlar_orchestrator
from backend.app.core.config import get_settings
from backend.app.workflows.service import WorkflowError


router = APIRouter(prefix="/journey", tags=["adviser-os-journey"])
_NO_STORE = {"Cache-Control": "no-store"}


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseTokenRequest(StrictRequest):
    case_token: str = Field(min_length=20, max_length=256)


class PlanSelectionRequest(CaseTokenRequest):
    plan_key: str = Field(min_length=1, max_length=200)
    selected_by: Literal["client", "broker"] = "client"
    note: str | None = Field(default=None, max_length=1000)


class ApplicationSectionRequest(CaseTokenRequest):
    section: str = Field(min_length=1, max_length=120)
    note: str = Field(min_length=1, max_length=4000)
    document_refs: list[str] = Field(default_factory=list, max_length=20)


class SubmissionRequest(CaseTokenRequest):
    external_reference: str = Field(min_length=1, max_length=200)


class PolicyIssueRequest(CaseTokenRequest):
    policy_number: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=120)
    start_date: date
    renewal_date: date
    document_refs: list[str] = Field(default_factory=list, max_length=20)


class PreauthorisationRequest(CaseTokenRequest):
    service_key: str = Field(min_length=1, max_length=160)
    provider_name: str | None = Field(default=None, max_length=200)
    facility_name: str | None = Field(default=None, max_length=200)
    planned_date: date | None = None
    document_refs: list[str] = Field(default_factory=list, max_length=20)


class ClaimOpenRequest(CaseTokenRequest):
    service_date: date | None = None
    amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    document_refs: list[str] = Field(default_factory=list, max_length=20)
    note: str | None = Field(default=None, max_length=1200)


def _workflow_error(exc: WorkflowError) -> HTTPException:
    if exc.code in {"case_unavailable", "case_expired"}:
        return HTTPException(status_code=404, detail=str(exc))
    if exc.code == "broker_authorisation_required":
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _require_broker_access(value: str | None) -> None:
    expected = get_settings().admin_password
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Broker-authorised lifecycle actions are disabled until ADMIN_PASSWORD is configured.",
        )
    if not value or not hmac.compare_digest(str(value), str(expected)):
        raise HTTPException(status_code=403, detail="Invalid broker credentials.")


def _portal_url() -> str:
    return os.getenv("CHI_PORTAL_URL", "https://portalchiinsurance.up.railway.app/login")


def _require_local_post_sale() -> None:
    if os.getenv("POST_SALE_SYSTEM_OF_RECORD", "chi_portal").casefold() != "ashlar":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "chi_portal_handoff",
                "message": "Issued policies, permanent documents, claims and renewals are managed in the CHI Insurance Portal.",
                "portal_url": _portal_url(),
            },
        )


def _json(payload: dict) -> JSONResponse:
    return JSONResponse(content=payload, headers=_NO_STORE)


@router.post("/{case_id}/select-plan")
def select_plan(case_id: UUID, req: PlanSelectionRequest, x_admin_password: Annotated[str | None, Header(alias="X-Admin-Password")] = None):
    if req.selected_by == "broker":
        _require_broker_access(x_admin_password)
    try:
        payload = get_ashlar_orchestrator().select_final_plan(
            case_id=case_id,
            case_token=req.case_token,
            plan_key=req.plan_key,
            selected_by=req.selected_by,
            note=req.note,
        )
    except WorkflowError as exc:
        raise _workflow_error(exc) from exc
    return _json(payload)


@router.post("/{case_id}/application/prepare")
def prepare_application(case_id: UUID, req: CaseTokenRequest):
    try:
        payload = get_ashlar_orchestrator().prepare_application_workflow(
            case_id=case_id,
            case_token=req.case_token,
        )
    except WorkflowError as exc:
        raise _workflow_error(exc) from exc
    return _json(payload)


@router.post("/{case_id}/application/sections/complete")
def complete_application_section(case_id: UUID, req: ApplicationSectionRequest, x_admin_password: Annotated[str | None, Header(alias="X-Admin-Password")] = None):
    if x_admin_password:
        _require_broker_access(x_admin_password)
    _validated_documents(case_id, req.case_token, req.document_refs)
    try:
        payload = get_ashlar_orchestrator().complete_application_section_workflow(
            case_id=case_id,
            case_token=req.case_token,
            section=req.section,
            note=req.note,
            document_refs=req.document_refs,
            broker_authorized=bool(x_admin_password),
        )
    except WorkflowError as exc:
        raise _workflow_error(exc) from exc
    return _json(payload)


@router.post("/{case_id}/application/submit")
def submit_application(case_id: UUID, req: SubmissionRequest, x_admin_password: Annotated[str | None, Header(alias="X-Admin-Password")] = None):
    _require_broker_access(x_admin_password)
    try:
        payload = get_ashlar_orchestrator().submit_application_workflow(
            case_id=case_id,
            case_token=req.case_token,
            broker_authorized=True,
            external_reference=req.external_reference,
        )
    except WorkflowError as exc:
        raise _workflow_error(exc) from exc
    return _json(payload)


@router.post("/{case_id}/policy/issue")
def issue_policy(
    case_id: UUID,
    req: PolicyIssueRequest,
    x_admin_password: Annotated[str | None, Header(alias="X-Admin-Password")] = None,
):
    _require_local_post_sale()
    _require_broker_access(x_admin_password)
    documents = _validated_documents(case_id, req.case_token, req.document_refs)
    if not any(d.role == "issued_policy" for d in documents):
        raise HTTPException(422, "Attach an issued policy schedule.")
    try:
        payload = get_ashlar_orchestrator().record_policy_issue(
            case_id=case_id,
            case_token=req.case_token,
            policy_number=req.policy_number,
            provider=req.provider,
            start_date=req.start_date,
            renewal_date=req.renewal_date,
            document_refs=req.document_refs,
            broker_authorized=True,
        )
    except WorkflowError as exc:
        raise _workflow_error(exc) from exc
    return _json(payload)


@router.get("/{case_id}/policy/wallet")
def policy_wallet(
    case_id: UUID,
    case_token: str = Query(min_length=20, max_length=256),
):
    _require_local_post_sale()
    try:
        payload = get_ashlar_orchestrator().policy_wallet(
            case_id=case_id,
            case_token=case_token,
        )
    except WorkflowError as exc:
        raise _workflow_error(exc) from exc
    return _json(payload)


@router.post("/{case_id}/preauthorisations")
def open_preauthorisation(case_id: UUID, req: PreauthorisationRequest):
    _require_local_post_sale()
    _validated_documents(case_id, req.case_token, req.document_refs)
    try:
        payload = get_ashlar_orchestrator().open_preauthorisation(
            case_id=case_id,
            case_token=req.case_token,
            service_key=req.service_key,
            provider_name=req.provider_name,
            facility_name=req.facility_name,
            planned_date=req.planned_date,
            document_refs=req.document_refs,
        )
    except WorkflowError as exc:
        raise _workflow_error(exc) from exc
    return _json(payload)


@router.post("/{case_id}/claims")
def open_claim(case_id: UUID, req: ClaimOpenRequest):
    _require_local_post_sale()
    _validated_documents(case_id, req.case_token, req.document_refs)
    try:
        payload = get_ashlar_orchestrator().open_claim(
            case_id=case_id,
            case_token=req.case_token,
            service_date=req.service_date,
            amount=req.amount,
            currency=req.currency,
            document_refs=req.document_refs,
            note=req.note,
        )
    except WorkflowError as exc:
        raise _workflow_error(exc) from exc
    return _json(payload)


@router.post("/{case_id}/renewal/start")
def start_renewal(case_id: UUID, req: CaseTokenRequest):
    _require_local_post_sale()
    try:
        payload = get_ashlar_orchestrator().start_renewal_workflow(
            case_id=case_id,
            case_token=req.case_token,
        )
    except WorkflowError as exc:
        raise _workflow_error(exc) from exc
    return _json(payload)

# Lifecycle evidence stays case-bound; privileged actions require both tokens.
from datetime import datetime, timezone
from dataclasses import asdict
from io import BytesIO
import json
import zipfile
from fastapi.responses import Response
from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.cases.fact_ledger import FactLedger
from backend.app.cases.models import Fact, FactSource, FactSourceType, FactStatus
from backend.app.documents.store import DOCUMENT_EVIDENCE_STORE
from backend.app.schemas.applicant import Applicant
from backend.app.rates.quote_engine import quote_shortlist


def _record(case_id, token):
    record = CASE_ANALYSIS_STORE.get(case_id, token)
    if record is None:
        raise HTTPException(404, "Case unavailable or unauthorised.")
    return record


def _validated_documents(case_id, token, refs):
    _record(case_id, token)
    items = [DOCUMENT_EVIDENCE_STORE.get(ref, case_id=case_id, case_token=token) for ref in refs]
    if any(item is None for item in items):
        raise HTTPException(422, "An evidence document is unavailable or belongs to another case.")
    return items


def _audit(case, action, **details):
    case.metadata.setdefault("lifecycle_audit", []).append({"action": action, "at": datetime.now(timezone.utc).isoformat(), **details})
    case.touch()


def _save(case, token):
    if CASE_ANALYSIS_STORE.save_case(case=case, access_token=token) is None:
        raise HTTPException(409, "Case changed or expired. Reload before retrying.")


@router.post("/{case_id}/workspace")
def workspace(case_id: UUID, req: CaseTokenRequest, x_admin_password: Annotated[str | None, Header(alias="X-Admin-Password")] = None):
    broker = bool(x_admin_password)
    if broker:
        _require_broker_access(x_admin_password)
    case = _record(case_id, req.case_token).case
    payload = {"case_id": str(case_id), "status": case.status.value, "selected_plan_key": case.selected_plan_key,
               "application": case.application, "blueprint": case.metadata.get("application_blueprint"), "policy": case.policy,
               "preauthorisations": case.preauthorisations, "claims": case.claims, "renewal": case.renewal,
               "applicant": case.applicant.model_dump(mode="json") if case.applicant else None,
               "audit": case.metadata.get("lifecycle_audit", []) if broker else [{"action": x["action"], "at": x["at"]} for x in case.metadata.get("lifecycle_audit", [])], "documents": [],
               "storage": __import__("backend.app.core.durable_store", fromlist=["storage_status"]).storage_status()}
    refs = case.metadata.get("document_refs", {})
    for doc in case.documents:
        if not broker and doc.metadata.get("role") in {"quotation", "brochure", "wording", "carrier_response"}:
            continue
        payload["documents"].append({**doc.model_dump(mode="json"), "refs": [ref for ref, identifier in refs.items() if identifier == str(doc.document_id)]})
    if broker:
        payload["conflicts"] = [dict(asdict(c), fact_ids=[str(f) for f in c.fact_ids]) for c in FactLedger(case.facts).conflicts()]
        payload["facts"] = [f.model_dump(mode="json") for f in case.facts]
    payload["health_navigation"] = {"mode": "external_handoff", "url": os.getenv("ASKLEPIOS_WEB_URL"), "automatic_clinical_transfer": False}
    payload["portal_handoff"] = {
        "mode": "authenticated_portal",
        "url": _portal_url(),
        "system_of_record": "chi_portal",
        "automatic_upload": False,
        "reason": "The CHI Portal owns issued policies, client documents, claims and renewals.",
    }
    payload["renewal_due_days"] = None
    return _json(payload)


class TransitionRequest(CaseTokenRequest):
    status: str = Field(min_length=1, max_length=40)
    external_reference: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=1200)
    document_refs: list[str] = Field(min_length=1, max_length=20)
    paid_amount: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")


_TRANSITIONS = {
    "claims": {"draft": {"submitted"}, "submitted": {"info_required", "approved", "partially_approved", "declined"}, "info_required": {"submitted"}, "approved": {"paid"}, "partially_approved": {"paid"}, "declined": set(), "paid": set()},
    "preauthorisations": {"draft": {"submitted"}, "submitted": {"pending", "approved", "partially_approved", "declined"}, "pending": {"approved", "partially_approved", "declined"}, "approved": set(), "partially_approved": set(), "declined": set()},
}


@router.post("/{case_id}/{kind}/{record_id}/transition")
def transition(case_id: UUID, kind: Literal["claims", "preauthorisations"], record_id: UUID, req: TransitionRequest, x_admin_password: Annotated[str | None, Header(alias="X-Admin-Password")] = None):
    _require_local_post_sale()
    _require_broker_access(x_admin_password)
    docs = _validated_documents(case_id, req.case_token, req.document_refs)
    case = _record(case_id, req.case_token).case
    id_key = "claim_id" if kind == "claims" else "request_id"
    item = next((x for x in getattr(case, kind) if x[id_key] == str(record_id)), None)
    if item is None:
        raise HTTPException(404, "Workflow record not found.")
    if req.status not in _TRANSITIONS[kind].get(item["status"], set()):
        raise HTTPException(409, "This status transition is not permitted.")
    if any(d.plan_key != item["plan_key"] for d in docs):
        raise HTTPException(422, "Evidence must refer to this workflow's plan.")
    if req.status in {"approved", "partially_approved", "declined", "paid", "pending", "info_required"} and not any(d.role == "carrier_response" for d in docs):
        raise HTTPException(422, "Attach the actual carrier response before recording this status.")
    if req.status == "paid" and (req.paid_amount is None or not req.currency):
        raise HTTPException(422, "Payment amount and currency are required.")
    event = {"from": item["status"], "to": req.status, "reference": req.external_reference, "note": req.note, "document_refs": req.document_refs, "at": datetime.now(timezone.utc).isoformat(), "recorded_by": "broker"}
    if req.status == "paid":
        event.update(paid_amount=req.paid_amount, currency=req.currency)
    item.setdefault("events", []).append(event)
    item["status"] = req.status
    item["updated_at"] = event["at"]
    item["document_refs"] = list(dict.fromkeys(item["document_refs"] + req.document_refs))
    _audit(case, kind + "." + req.status, record_id=str(record_id), reference=req.external_reference)
    _save(case, req.case_token)
    return _json({"record": item, "transmitted_by_ashlar": False})


class ResolveRequest(CaseTokenRequest):
    winning_fact_id: UUID
    note: str = Field(min_length=10, max_length=1000)


@router.post("/{case_id}/conflicts/resolve")
def resolve_conflict(case_id: UUID, req: ResolveRequest, x_admin_password: Annotated[str | None, Header(alias="X-Admin-Password")] = None):
    _require_broker_access(x_admin_password)
    record = _record(case_id, req.case_token)
    case = record.case
    ledger = FactLedger(case.facts)
    winner = next((f for f in case.facts if f.fact_id == req.winning_fact_id and f.status == FactStatus.VERIFIED), None)
    if winner is None:
        raise HTTPException(422, "Select an already verified, source-backed fact. Extraction alone is not verification.")
    try:
        ledger.resolve(subject=winner.subject, key=winner.key, winning_fact_id=winner.fact_id)
    except KeyError as exc:
        raise HTTPException(422, str(exc)) from exc
    case.facts = ledger.facts
    # Proposal analysis is a separate materialized view; never export a stale matrix.
    case.metadata["proposal_requires_reanalysis"] = True
    _audit(case, "conflict_resolved", fact_id=str(winner.fact_id), note=req.note)
    _save(case, req.case_token)
    return _json({"resolved_fact_id": str(winner.fact_id), "proposal_requires_reanalysis": True})


class IssuedTermRequest(CaseTokenRequest):
    document_ref: str = Field(min_length=20, max_length=256)
    key: str = Field(pattern=r"^(annual_limit|deductible_or_excess|area_of_cover|underwriting_basis|premium_amount|benefit\.[a-z0-9_]+)$")
    value: str = Field(min_length=1, max_length=2000)
    page: int = Field(ge=1)
    source_quote: str = Field(min_length=5, max_length=800)


@router.post("/{case_id}/policy/terms")
def reconcile_issued_term(case_id: UUID, req: IssuedTermRequest, x_admin_password: Annotated[str | None, Header(alias="X-Admin-Password")] = None):
    _require_local_post_sale()
    _require_broker_access(x_admin_password)
    document = _validated_documents(case_id, req.case_token, [req.document_ref])[0]
    case = _record(case_id, req.case_token).case
    if not case.policy or document.role not in {"issued_policy", "wording"} or document.plan_key != case.policy["plan_key"]:
        raise HTTPException(422, "Reconcile against the issued schedule or applicable wording for this policy.")
    if req.page > int(document.document.metadata.get("pages") or 1):
        raise HTTPException(422, "Page is outside the uploaded document.")
    source_text = document.extracted_text
    if document.document.filename.lower().endswith(".pdf") and document.original_bytes:
        import fitz
        with fitz.open(stream=document.original_bytes, filetype="pdf") as source_pdf:
            if req.page > len(source_pdf):
                raise HTTPException(422, "Source page is unavailable.")
            source_text = source_pdf[req.page - 1].get_text()
    if " ".join(req.source_quote.split()).casefold() not in " ".join(source_text.split()).casefold():
        raise HTTPException(422, "The source quotation was not found in the document text.")
    fact = Fact(subject="plan:" + case.policy["plan_key"], key=req.key, value=req.value, plan_key=case.policy["plan_key"], provider=case.policy["provider"], status=FactStatus.VERIFIED, source=FactSource(source_type=FactSourceType.POLICY_SCHEDULE if document.role == "issued_policy" else FactSourceType.POLICY_WORDING, document_id=document.document.document_id, page=req.page, quote=req.source_quote), note="Broker reconciled against issued policy " + case.policy["policy_number"])
    case.facts.append(fact)
    case.metadata.setdefault("issued_terms_fact_ids", {}).setdefault(case.policy["policy_id"], []).append(str(fact.fact_id))
    _audit(case, "issued_term_verified", fact_id=str(fact.fact_id), document_ref=req.document_ref)
    _save(case, req.case_token)
    return _json({"fact": fact.model_dump(mode="json")})


class RenewalIntakeRequest(CaseTokenRequest):
    applicant: Applicant
    confirmed_current: Literal[True]


@router.post("/{case_id}/renewal/refresh")
def refresh_renewal(case_id: UUID, req: RenewalIntakeRequest):
    _require_local_post_sale()
    case = _record(case_id, req.case_token).case
    if not case.renewal:
        raise HTTPException(422, "Start a renewal review first.")
    case.applicant = req.applicant
    case.metadata["renewal_intake_confirmed"] = datetime.now(timezone.utc).isoformat()
    quotes = [q.model_dump(mode="json") for q in quote_shortlist(req.applicant, get_settings())]
    case.metadata["renewal_quotes"] = quotes
    case.renewal["status"] = "quoted"
    _audit(case, "renewal_quotes_refreshed")
    _save(case, req.case_token)
    return _json({"quotes": quotes, "baseline": case.metadata.get("renewal_baseline"), "pricing_note": "Registry rates retain their own provenance. Carrier quotations and underwriting remain required."})


class PackRequest(CaseTokenRequest):
    document_refs: list[str] = Field(default_factory=list, max_length=20)


@router.post("/{case_id}/handoff-pack")
def handoff_pack(case_id: UUID, req: PackRequest, x_admin_password: Annotated[str | None, Header(alias="X-Admin-Password")] = None):
    _require_broker_access(x_admin_password)
    record = _record(case_id, req.case_token)
    docs = _validated_documents(case_id, req.case_token, req.document_refs)
    if any(not d.original_bytes for d in docs):
        raise HTTPException(422, "Re-upload older documents to include their original files.")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        manifest = {
            "case_id": str(case_id),
            "selected_plan_key": record.case.selected_plan_key,
            "application": record.case.application,
            "proposal": record.case.proposal,
            "document_count": len(docs),
            "destination": "chi_portal",
            "transmitted_by_ashlar": False,
        }
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for index, doc in enumerate(docs):
            suffix = ".pdf" if doc.document.filename.lower().endswith(".pdf") else ".txt"
            archive.writestr(f"documents/{index + 1}-{doc.document.document_id}{suffix}", doc.original_bytes)
    return Response(buffer.getvalue(), media_type="application/zip", headers={**_NO_STORE, "Content-Disposition": 'attachment; filename="ashlar-handoff.zip"'})


@router.post("/{case_id}/documents/{document_ref}/download")
def download_document(case_id: UUID, document_ref: str, req: CaseTokenRequest, x_admin_password: Annotated[str | None, Header(alias="X-Admin-Password")] = None):
    document = _validated_documents(case_id, req.case_token, [document_ref])[0]
    if document.role in {"quotation", "brochure", "wording", "carrier_response"}:
        _require_broker_access(x_admin_password)
    if not document.original_bytes:
        raise HTTPException(404, "Original file is unavailable; please re-upload.")
    return Response(document.original_bytes, media_type="application/octet-stream", headers={**_NO_STORE, "Content-Disposition": 'attachment; filename="policy-document"'})


@router.post("/{case_id}/policy/wallet")
def policy_wallet_private(case_id: UUID, req: CaseTokenRequest):
    _require_local_post_sale()
    return policy_wallet(case_id, req.case_token)


@router.post("/{case_id}/documents/{document_ref}/analyse")
def review_lifecycle_document(case_id: UUID, document_ref: str, req: CaseTokenRequest, x_admin_password: Annotated[str | None, Header(alias="X-Admin-Password")] = None):
    """Document analyst's deterministic extraction, never a coverage decision."""
    import re
    document = _validated_documents(case_id, req.case_token, [document_ref])[0]
    if document.role in {"quotation", "brochure", "wording", "carrier_response", "issued_policy"}:
        _require_broker_access(x_admin_password)
    if document.role not in {"application", "claim", "preauthorisation", "carrier_response", "issued_policy"}:
        raise HTTPException(422, "Use HAL's comparison document analyst for this document type.")
    amounts = list(dict.fromkeys(re.findall(r"\b(?:EUR|USD|GBP)\s*[\d.,]+\b", document.extracted_text, re.I)))[:30]
    dates = list(dict.fromkeys(re.findall(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/.-]\d{1,2}[/.-]\d{4}\b", document.extracted_text)))[:30]
    case = _record(case_id, req.case_token).case
    review = {"document_id": str(document.document.document_id), "document_ref": document_ref, "status": "extracted_unverified", "candidate_amounts": amounts, "candidate_dates": dates, "pages": document.document.metadata.get("pages"), "excerpt": document.extracted_text[:4000], "missing_checks": ["Confirm patient and policy identity", "Confirm service dates and itemised amounts", "Confirm authenticity and carrier response separately"], "coverage_decision": None}
    case.metadata.setdefault("lifecycle_document_analysis", {})[document_ref] = review
    _audit(case, "lifecycle_document_reviewed", document_ref=document_ref)
    _save(case, req.case_token)
    return _json(review)


@router.post("/{case_id}/comparison/reconcile")
def rebuild_verified_comparison(case_id: UUID, req: CaseTokenRequest, x_admin_password: Annotated[str | None, Header(alias="X-Admin-Password")] = None):
    """Rebuild the materialized proposal view after explicit ledger resolution."""
    from copy import deepcopy
    from backend.app.api.quotes import _benefit_field
    _require_broker_access(x_admin_password)
    record = _record(case_id, req.case_token)
    case, ledger = record.case, FactLedger(record.case.facts)
    selected_subjects = {"plan:" + key for key in case.selected_plan_keys}
    if any(c.subject in selected_subjects for c in ledger.conflicts()):
        raise HTTPException(409, "Resolve the remaining selected-plan conflicts first.")
    results = deepcopy(record.results)
    for result in results:
        key = result.get("plan_key")
        if key not in case.selected_plan_keys:
            continue
        subject = "plan:" + key
        current = {}
        for fact in case.facts:
            if fact.subject == subject:
                candidate = ledger.current(fact.key, subject)
                if candidate and candidate.status == FactStatus.VERIFIED:
                    current[fact.key] = candidate
        analysis = result.setdefault("analysis", {})
        for field in ("annual_limit", "deductible_or_excess", "area_of_cover"):
            analysis[field] = current[field].value if field in current else "Not specified"
        premium = current.get("premium_amount")
        analysis["premium"] = {"amount": premium.value if premium else None, "currency": premium.currency if premium else None, "frequency": current["premium_frequency"].value if "premium_frequency" in current else None}
        analysis["benefits"] = {}
        result["focused_rows"] = []
        analysis["source_evidence"] = []
        for field, fact in current.items():
            analysis["source_evidence"].append({"field": field, "value": fact.value, "document": fact.source.source_ref or str(fact.source.document_id or ""), "page": fact.source.page, "evidence": fact.source.quote, "fact_id": str(fact.fact_id)})
            if field.startswith("benefit."):
                code = field.removeprefix("benefit.")
                group = _benefit_field(code, code) or code
                detail = str(fact.value)
                analysis["benefits"][group] = (analysis["benefits"][group] + "; " + detail) if group in analysis["benefits"] else detail
                result["focused_rows"].append({"benefit_code": code, "benefit": code.replace("_", " "), "value": fact.value, "page": fact.source.page, "source": fact.source.source_ref})
        result["library_source"] = bool(result["focused_rows"])
        analysis["underwriting"] = {"basis": current["underwriting_basis"].value if "underwriting_basis" in current else "Not specified", "pre_existing_conditions": "Confirm from the carrier quotation and policy terms"}
        analysis["confidence"] = "high" if current else "low"
    case.metadata.pop("proposal_requires_reanalysis", None)
    _audit(case, "comparison_reconciled_from_verified_ledger")
    if CASE_ANALYSIS_STORE.save_analysis(case=case, results=results, access_token=req.case_token) is None:
        raise HTTPException(409, "Case changed during reconciliation. Reload and retry.")
    return _json({"results": results, "message": "Comparison rebuilt from verified ledger facts. Proposal quality checks still apply."})
