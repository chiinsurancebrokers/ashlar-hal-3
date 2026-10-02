from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
import httpx

from backend.app.core.config import get_settings
from backend.app.schemas.applicant import Applicant
from backend.app.rates.quote_engine import quote_shortlist, quote_exclusions, quote_current
from backend.app.evidence.compare_matrix import build_comparison_matrix, matrix_to_dict
from backend.app.evidence.carrier_profile import carrier_profile
from backend.app.services.adviser import comparison_conclusion, explain_plan

router = APIRouter(prefix="/quotes", tags=["quotes"])


@router.post("/preview")
async def preview(applicant: Applicant):
    settings = get_settings()
    try:
        shortlist = quote_shortlist(applicant, settings)
        excluded = quote_exclusions(applicant, settings)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not compute a shortlist: {str(exc)[:180]}")
    return {
        "shortlist": [q.model_dump(mode="json") for q in shortlist],
        "quotes": [q.model_dump(mode="json") for q in shortlist],
        "exclusions": excluded,
    }



@router.post("/current-policy")
async def current_policy(file: UploadFile = File(...)):
    """Secure proxy to Proposal Studio for applicant current-policy analysis.

    The browser uploads only to HAL. HAL forwards the bytes server-to-server
    with the internal Proposal Studio key, then returns structured facts.
    """
    settings = get_settings()
    if not settings.proposal_studio_api_url or not settings.proposal_studio_api_key:
        raise HTTPException(status_code=503, detail="Current-policy analysis is not configured.")

    filename = (file.filename or "current-policy.pdf").strip()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Current policy file exceeds 20 MB.")

    url = settings.proposal_studio_api_url.rstrip("/") + "/api/v1/current-policy/analyze"
    headers = {"x-hal-bridge-key": settings.proposal_studio_api_key}
    files = {"file": (filename, content, file.content_type or "application/octet-stream")}
    try:
        async with httpx.AsyncClient(timeout=settings.proposal_studio_timeout_seconds) as client:
            response = await client.post(url, headers=headers, files=files)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Proposal Studio is temporarily unavailable.") from exc

    try:
        body = response.json()
    except Exception:
        body = {"detail": "Proposal Studio returned an invalid response."}
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=str(body.get("detail") or "Current policy could not be analyzed."))

    return {"current_policy": body}


class ExplainPlanRequest(BaseModel):
    applicant_state: dict = Field(default_factory=dict)
    plan_key: str
    question: str = "Tell me more about this plan."
    language: str = Field(default="en", pattern="^(en|el)$")


@router.post("/explain")
async def explain(req: ExplainPlanRequest):
    """Explain one currently eligible plan without rebuilding the shortlist."""
    settings = get_settings()
    try:
        fields = {k: v for k, v in req.applicant_state.items() if k in Applicant.model_fields}
        applicant = Applicant(**fields)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid applicant_state: {str(exc)[:180]}") from exc

    current = quote_current(applicant, settings)
    quote = next((q for q in current if q.plan_key == req.plan_key), None)
    if quote is None:
        raise HTTPException(status_code=404, detail="That plan is not currently eligible for this applicant.")

    answer = await explain_plan(quote, req.question, greek=(req.language == "el"))
    return {
        "plan_key": quote.plan_key,
        "product_name": quote.product_name,
        "insurer": quote.insurer,
        "answer": answer,
        "source_documents": quote.source_documents,
        "verified_facts": quote.verified_facts,
    }


class CompareRequest(BaseModel):
    applicant_state: dict = Field(default_factory=dict)
    plan_keys: list[str] = Field(min_length=1, max_length=4)
    language: str = Field(default="en", pattern="^(en|el)$")
    has_current_policy: bool = False


@router.post("/compare")
async def compare(req: CompareRequest):
    """Detailed benefit-by-benefit comparison, in the style of the Ashlar
    comparison PDFs. Like /leads/comparison, this NEVER trusts a plan's
    identity or premium from the client beyond its plan_key — everything is
    recomputed server-side against the real shortlist first."""
    settings = get_settings()
    try:
        fields = {k: v for k, v in req.applicant_state.items() if k in Applicant.model_fields}
        applicant = Applicant(**fields)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid applicant_state: {str(exc)[:180]}") from exc

    all_current = quote_current(applicant, settings)
    by_key = {q.plan_key: q for q in all_current if q.plan_key}
    selected = [by_key[k] for k in req.plan_keys if k in by_key]
    minimum = 1 if req.has_current_policy else 2
    if len(selected) < minimum:
        raise HTTPException(
            status_code=400,
            detail=("Select at least 1 eligible plan to compare with the current policy."
                    if req.has_current_policy else
                    "At least 2 currently eligible plan_keys are required to compare.")
        )

    plans_for_matrix = [
        {"plan_key": q.plan_key, "carrier": q.plan_key.split(":")[0], "product_code": q.product_code,
         "insurer": q.insurer, "product_name": q.product_name}
        for q in selected
    ]
    matrix = build_comparison_matrix(plans_for_matrix)
    matrix_dict = matrix_to_dict(matrix)

    conclusion = await comparison_conclusion(matrix_dict["rows"], matrix_dict["plan_labels"], greek=(req.language == "el"))

    carrier_meta = {q.plan_key: carrier_profile(q.plan_key.split(":")[0]) for q in selected}

    return {
        "plans": [q.model_dump(mode="json") for q in selected],
        "matrix": matrix_dict,
        "carrier_profiles": carrier_meta,
        "conclusion": conclusion,
        "unsupported_note": (
            f"No detailed Table of Benefits is loaded yet for: {', '.join(matrix.unsupported_plan_keys)}. "
            "These plans are included in the price comparison above but not in the row-by-row benefit table."
        ) if matrix.unsupported_plan_keys else None,
    }
