from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.agents.orchestrator import get_ashlar_orchestrator
from backend.app.schemas.applicant import Applicant


router = APIRouter(prefix="/adviser", tags=["adviser-os"])


class AdviserMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class AdviserHandleRequest(BaseModel):
    """Public Adviser OS contract.

    The browser can provide declared applicant/conversation context and opaque
    access references. It cannot post arbitrary verified insurer facts,
    document-analysis model output or Proposal Studio evidence into the
    orchestrator.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: UUID | None = None
    case_token: str | None = Field(default=None, max_length=256)
    message: str = Field(min_length=1, max_length=4000)
    state: dict[str, Any] = Field(default_factory=dict)
    history: list[AdviserMessage] = Field(default_factory=list, max_length=100)
    language: Literal["en", "el"] | None = None
    applicant: Applicant | None = None
    benefit_key: str | None = Field(default=None, max_length=120)
    plan_key: str | None = Field(default=None, max_length=160)
    document_refs: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("document_refs")
    @classmethod
    def validate_document_refs(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = str(raw or "").strip()
            if not value or len(value) > 256:
                raise ValueError("document_refs must contain non-empty opaque references up to 256 characters")
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result


@router.post("/handle")
async def handle(req: AdviserHandleRequest):
    history = [item.model_dump() for item in req.history]
    context: dict[str, Any] = {
        "state": dict(req.state),
        "history": history,
        # Asklepios receives only its own narrow history field through the
        # health adapter; insurance-only context is filtered there again.
        "health_history": history,
    }
    if req.case_token:
        context["case_token"] = req.case_token
    if req.language:
        context["language"] = req.language
    if req.applicant is not None:
        context["applicant"] = req.applicant
    if req.benefit_key:
        context["benefit_key"] = req.benefit_key
    if req.plan_key:
        context["plan_key"] = req.plan_key
    if req.document_refs:
        # Only opaque references created by /documents/upload cross the public
        # boundary. Raw carrier text/model output cannot be injected here.
        context["document_refs"] = list(req.document_refs)

    try:
        result = await get_ashlar_orchestrator().handle(
            case_id=req.case_id,
            message=req.message,
            context=context,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Ashlar Orchestrator failed: {str(exc)[:180]}",
        ) from exc

    return JSONResponse(
        content=result.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )
