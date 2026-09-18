from __future__ import annotations

import hmac
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


def _json(payload: dict) -> JSONResponse:
    return JSONResponse(content=payload, headers=_NO_STORE)


@router.post("/{case_id}/select-plan")
def select_plan(case_id: UUID, req: PlanSelectionRequest):
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
def complete_application_section(case_id: UUID, req: ApplicationSectionRequest):
    try:
        payload = get_ashlar_orchestrator().complete_application_section_workflow(
            case_id=case_id,
            case_token=req.case_token,
            section=req.section,
        )
    except WorkflowError as exc:
        raise _workflow_error(exc) from exc
    return _json(payload)


@router.post("/{case_id}/application/submit")
def submit_application(case_id: UUID, req: CaseTokenRequest):
    try:
        payload = get_ashlar_orchestrator().submit_application_workflow(
            case_id=case_id,
            case_token=req.case_token,
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
    _require_broker_access(x_admin_password)
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
    try:
        payload = get_ashlar_orchestrator().start_renewal_workflow(
            case_id=case_id,
            case_token=req.case_token,
        )
    except WorkflowError as exc:
        raise _workflow_error(exc) from exc
    return _json(payload)
