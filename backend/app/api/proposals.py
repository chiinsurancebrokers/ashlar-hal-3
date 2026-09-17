from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac
import re
import secrets
import threading
from typing import Any, Annotated

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.app.cases.models import AshlarCase, CaseStatus
from backend.app.core.config import get_settings
from backend.app.proposals.engine import ProposalGenerationBlocked, generate_case_proposal
from backend.app.proposals.report_schema import ClientReportValidationError

router = APIRouter(prefix="/proposals", tags=["proposals"])

_NO_STORE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}


class ProposalGenerateRequest(BaseModel):
    """Broker/internal proposal-generation contract.

    `results` must be the output of Ashlar's server-side document analysis, not
    unverified plan facts entered by a public client. This endpoint is therefore
    fail-closed behind the existing HAL admin password until the persistent
    Case/Analysis registry is wired to the public client journey.
    """

    case: AshlarCase
    results: list[dict[str, Any]] = Field(min_length=1, max_length=10)
    language: str | None = Field(default=None, max_length=20)
    strict_narrative: bool = False


@dataclass(slots=True)
class _StoredProposal:
    case_id: str
    client_name: str
    report: dict[str, Any]
    pdf_bytes: bytes
    pptx_bytes: bytes
    created_at: datetime
    expires_at: datetime


class _ProposalArtifactStore:
    """Small process-local store for generated files.

    This deliberately does not write client proposals to disk. Download IDs are
    high-entropy opaque tokens, results expire quickly, and responses are marked
    no-store. A durable authenticated object store can replace this interface
    when account/auth infrastructure is introduced.
    """

    def __init__(self, *, ttl_minutes: int = 30, max_items: int = 32):
        self.ttl = timedelta(minutes=ttl_minutes)
        self.max_items = max_items
        self._items: dict[str, _StoredProposal] = {}
        self._lock = threading.Lock()

    def _prune_locked(self, now: datetime) -> None:
        expired = [key for key, item in self._items.items() if item.expires_at <= now]
        for key in expired:
            self._items.pop(key, None)
        if len(self._items) >= self.max_items:
            oldest = sorted(self._items.items(), key=lambda pair: pair[1].created_at)
            for key, _ in oldest[: max(1, len(self._items) - self.max_items + 1)]:
                self._items.pop(key, None)

    def put(self, *, case: AshlarCase, report: dict, pdf_bytes: bytes, pptx_bytes: bytes) -> tuple[str, datetime]:
        now = datetime.now(timezone.utc)
        token = secrets.token_urlsafe(24)
        expires = now + self.ttl
        item = _StoredProposal(
            case_id=str(case.case_id),
            client_name=case.client.display_name or "Client",
            report=report,
            pdf_bytes=pdf_bytes,
            pptx_bytes=pptx_bytes,
            created_at=now,
            expires_at=expires,
        )
        with self._lock:
            self._prune_locked(now)
            self._items[token] = item
        return token, expires

    def get(self, token: str) -> _StoredProposal | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._prune_locked(now)
            return self._items.get(token)


_STORE = _ProposalArtifactStore()


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


@router.post("/generate", name="generate_ashlar_proposal")
async def generate_proposal(
    req: ProposalGenerateRequest,
    request: Request,
    x_admin_password: Annotated[str | None, Header(alias="X-Admin-Password")] = None,
):
    # IMPORTANT: Until Case/Analysis persistence is server-owned, never trust a
    # browser to self-assert verified insurer facts. This keeps the current
    # integration broker/internal-only rather than violating HAL's evidence model.
    _require_broker_access(x_admin_password)

    case = req.case.model_copy(deep=True)
    try:
        bundle = await run_in_threadpool(
            generate_case_proposal,
            case=case,
            results=req.results,
            language=req.language,
            strict_narrative=req.strict_narrative,
        )
    except ProposalGenerationBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ClientReportValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Proposal Studio failed: {str(exc)[:240]}") from exc

    case.status = CaseStatus.PROPOSAL
    case.touch()
    token, expires = _STORE.put(
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


@router.get("/{proposal_id}", name="get_ashlar_proposal")
async def get_proposal(proposal_id: str):
    item = _STORE.get(proposal_id)
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
    item = _STORE.get(proposal_id)
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
    item = _STORE.get(proposal_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Proposal not found or download window expired.")
    name = _safe_filename(item.client_name)
    return _download_response(
        item.pptx_bytes,
        filename=f"Ashlar-Proposal-{name}.pptx",
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
