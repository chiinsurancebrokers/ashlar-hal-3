from __future__ import annotations

import hmac
import re
from typing import Any, Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from backend.app.agents.contracts import SpecialistName
from backend.app.agents.orchestrator import get_ashlar_orchestrator
from backend.app.agents.orchestrator_admin import (
    OrchestratorProposalError,
    generate_admin_proposal_bundle,
)
from backend.app.cases.intelligence import build_case_intelligence
from backend.app.cases.models import AshlarCase, CaseStatus
from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.core.config import get_settings
from backend.app.proposals.artifacts import PROPOSAL_ARTIFACT_STORE

router = APIRouter(prefix="/proposals", tags=["proposals"])

_NO_STORE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}


class ProposalGenerateRequest(BaseModel):
    """Broker/internal proposal-generation contract.

    `results` must be the output of Ashlar's server-side document analysis, not
    unverified plan facts entered by a public client.
    """

    case: AshlarCase
    results: list[dict[str, Any]] = Field(min_length=1, max_length=10)
    language: str | None = Field(default=None, max_length=20)
    strict_narrative: bool = False


class ProposalPrepareRequest(BaseModel):
    """Public-safe contract for a comparison already stored by HAL.

    No plan facts are accepted here. The case and analysis are loaded from the
    server-owned registry created by /quotes/compare.
    """

    case_id: UUID
    case_token: str = Field(min_length=20, max_length=200)
    language: str | None = Field(default=None, max_length=20)
    strict_narrative: bool = False


def _require_broker_access(value: str | None) -> None:
    settings = get_settings()
    expected = settings.admin_password
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Proposal generation is not enabled until ADMIN_PASSWORD is configured.",
        )
    if not value or not hmac.compare_digest(str(value), str(expected)):
        raise HTTPException(status_code=403, detail="Invalid broker credentials.")


def _safe_filename(value: str, fallback: str = "ashlar-proposal") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return text[:80] or fallback


def _download_response(data: bytes, *, filename: str, media_type: str) -> Response:
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            **_NO_STORE,
        },
    )


async def _generate_bundle(
    *,
    case: AshlarCase,
    results: list[dict],
    language: str | None,
    strict_narrative: bool,
):
    """Broker-only generation through the orchestrator layer.

    Even internal tooling does not import or invoke proposal_writer directly.
    The orchestrator owns the specialist and the internal gateway performs the
    explicit delegation.
    """
    try:
        return await generate_admin_proposal_bundle(
            get_ashlar_orchestrator(),
            case=case,
            results=results,
            language=language,
            strict_narrative=strict_narrative,
        )
    except OrchestratorProposalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _ready_response(*, request: Request, case: AshlarCase, bundle) -> JSONResponse:
    """Build the response for broker-only manual generation."""
    case.status = CaseStatus.PROPOSAL
    case.touch()
    token, expires = PROPOSAL_ARTIFACT_STORE.put(
        case=case,
        report=bundle.report,
        pdf_bytes=bundle.pdf_bytes,
        pptx_bytes=bundle.pptx_bytes,
    )
    payload = {
        "status": "ready",
        "proposal_id": token,
        "case_id": str(case.case_id),
        "quality": bundle.quality,
        "report": bundle.report,
        "recommendation": case.recommendation,
        "proposal": case.proposal,
        "case_status": case.status.value,
        "expires_at": expires.isoformat(),
        "downloads": {
            "pdf": str(request.url_for("download_proposal_pdf", proposal_id=token)),
            "pptx": str(request.url_for("download_proposal_pptx", proposal_id=token)),
        },
    }
    return JSONResponse(content=jsonable_encoder(payload), headers=_NO_STORE)


def _orchestrated_ready_response(
    *,
    request: Request,
    case_id: UUID,
    case_token: str,
    proposal_response,
) -> JSONResponse:
    """Preserve the proposal API contract over AshlarOrchestrator output."""
    payload = proposal_response.payload or {}
    proposal_id = str(payload.get("proposal_id") or "").strip()
    if not proposal_id:
        raise HTTPException(status_code=502, detail="Proposal writer completed without an artifact reference.")

    artifact = PROPOSAL_ARTIFACT_STORE.get(proposal_id)
    saved = CASE_ANALYSIS_STORE.get(case_id, case_token)
    if artifact is None or saved is None:
        raise HTTPException(
            status_code=409,
            detail="The proposal or active case expired while the response was being prepared.",
        )

    case = saved.case
    body = {
        "status": "ready",
        "proposal_id": proposal_id,
        "case_id": str(case.case_id),
        "quality": payload.get("quality") or {},
        "report": artifact.report,
        "recommendation": case.recommendation,
        "proposal": case.proposal,
        "case_status": case.status.value,
        "case_intelligence": build_case_intelligence(case),
        "expires_at": artifact.expires_at.isoformat(),
        "downloads": {
            "pdf": str(request.url_for("download_proposal_pdf", proposal_id=proposal_id)),
            "pptx": str(request.url_for("download_proposal_pptx", proposal_id=proposal_id)),
        },
    }
    return JSONResponse(content=jsonable_encoder(body), headers=_NO_STORE)


@router.post("/prepare", name="prepare_stored_case_proposal")
async def prepare_stored_case_proposal(req: ProposalPrepareRequest, request: Request):
    # Validate the opaque case/token pair before orchestration so the dedicated
    # endpoint preserves its historical 404 contract.
    if CASE_ANALYSIS_STORE.get(req.case_id, req.case_token) is None:
        raise HTTPException(status_code=404, detail="Case not found, expired, or access token is invalid.")

    result = await get_ashlar_orchestrator().handle(
        case_id=req.case_id,
        message="Create the proposal.",
        context={
            "case_token": req.case_token,
            "language": req.language,
            "strict_narrative": req.strict_narrative,
        },
    )
    proposal_response = next(
        (
            response
            for response in reversed(result.responses)
            if response.specialist == SpecialistName.PROPOSAL_WRITER
        ),
        None,
    )
    if proposal_response is None:
        raise HTTPException(status_code=502, detail="Ashlar Orchestrator did not return a proposal specialist result.")
    if proposal_response.status == "blocked":
        raise HTTPException(status_code=422, detail=proposal_response.reply or "Proposal generation is blocked.")
    if proposal_response.status == "needs_input":
        raise HTTPException(status_code=422, detail=proposal_response.reply or "More case information is required.")
    if proposal_response.status == "unavailable":
        raise HTTPException(status_code=409, detail=proposal_response.reply or "Proposal generation is unavailable.")
    if proposal_response.status != "completed":
        raise HTTPException(status_code=502, detail=proposal_response.reply or "Proposal generation did not complete.")

    return _orchestrated_ready_response(
        request=request,
        case_id=req.case_id,
        case_token=req.case_token,
        proposal_response=proposal_response,
    )


@router.post("/generate", name="generate_ashlar_proposal")
async def generate_proposal(
    req: ProposalGenerateRequest,
    request: Request,
    x_admin_password: Annotated[str | None, Header(alias="X-Admin-Password")] = None,
):
    # Internal/manual bridge retained for broker workflows and document testing.
    # It still enters the orchestrator layer instead of importing a specialist.
    _require_broker_access(x_admin_password)

    case = req.case.model_copy(deep=True)
    bundle = await _generate_bundle(
        case=case,
        results=req.results,
        language=req.language,
        strict_narrative=req.strict_narrative,
    )
    return _ready_response(request=request, case=case, bundle=bundle)


@router.get("/{proposal_id}", name="get_ashlar_proposal")
async def get_proposal(proposal_id: str):
    item = PROPOSAL_ARTIFACT_STORE.get(proposal_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Proposal not found or download window expired.")
    payload = {
        "status": "ready",
        "proposal_id": proposal_id,
        "case_id": item.case_id,
        "report": item.report,
        "expires_at": item.expires_at.isoformat(),
    }
    return JSONResponse(content=jsonable_encoder(payload), headers=_NO_STORE)


@router.get("/{proposal_id}/pdf", name="download_proposal_pdf")
async def download_pdf(proposal_id: str):
    item = PROPOSAL_ARTIFACT_STORE.get(proposal_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Proposal not found or download window expired.")
    name = _safe_filename(item.client_name)
    return _download_response(
        item.pdf_bytes,
        filename=f"Ashlar-Proposal-{name}.pdf",
        media_type="application/pdf",
    )


@router.get("/{proposal_id}/pptx", name="download_proposal_pptx")
async def download_pptx(proposal_id: str):
    item = PROPOSAL_ARTIFACT_STORE.get(proposal_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Proposal not found or download window expired.")
    name = _safe_filename(item.client_name)
    return _download_response(
        item.pptx_bytes,
        filename=f"Ashlar-Proposal-{name}.pptx",
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
