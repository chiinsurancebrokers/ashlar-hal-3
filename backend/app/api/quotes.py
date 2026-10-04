from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
import httpx

from backend.app.core.config import get_settings
from backend.app.schemas.applicant import Applicant
from backend.app.rates.quote_engine import quote_shortlist, quote_exclusions, quote_current
from backend.app.evidence.compare_matrix import build_comparison_matrix, matrix_to_dict
from backend.app.evidence.carrier_profile import carrier_profile
from backend.app.services.adviser import comparison_conclusion, explain_plan
from backend.app.services.current_policy_token import create_current_policy_token
from backend.app.services.policy_analyst_agent import analyze_current_policy

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
    """Secure proxy to Proposal Studio plus an evidence-locked policy audit."""
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

    policy_audit = analyze_current_policy(body)
    return {
        "current_policy": body,
        "policy_analysis": policy_audit.model_dump(mode="json"),
        "current_policy_token": create_current_policy_token(body),
    }


class ExplainPlanRequest(BaseModel):
    applicant_state: dict = Field(default_factory=dict)
    plan_key: str
    # For a household card: which members the card covers. Premiums are
    # recomputed server-side for each member — never taken from the browser.
    household_member_ids: list[str] = Field(default_factory=list, max_length=12)
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

    greek = req.language == "el"
    household_lines: list[str] | None = None
    if req.household_member_ids:
        quote, household_lines = _household_plan_quote(req, settings, greek)
    else:
        current = quote_current(applicant, settings)
        quote = next((q for q in current if q.plan_key == req.plan_key), None)
    if quote is None:
        raise HTTPException(status_code=404, detail="That plan is not currently eligible for this applicant.")

    answer = await explain_plan(quote, req.question, greek=greek, household_lines=household_lines)
    docs = [d["url"] for d in quote.plan_documents] or quote.source_documents
    return {
        "plan_key": quote.plan_key,
        "product_name": quote.product_name,
        "insurer": quote.insurer,
        "premium": quote.premium,
        "household_lines": household_lines or [],
        "answer": answer,
        "source_documents": docs,
        "verified_facts": quote.verified_facts,
    }


def _household_plan_quote(req: ExplainPlanRequest, settings, greek: bool):
    """Recompute this plan's premium for exactly the household members the
    card covers, using the same deterministic member states as the family
    composition. Returns (quote with household total, per-member lines)."""
    from backend.app.services.household_quote_service import household_member_states
    from backend.app.services.family_live_orchestrator import _member_labels

    wanted = list(dict.fromkeys(req.household_member_ids))
    states = dict(household_member_states(req.applicant_state))
    labels = _member_labels(req.applicant_state, greek)
    base, total, lines = None, 0.0, []
    for member_id in wanted:
        member_state = states.get(member_id)
        if member_state is None:
            return None, None
        fields = {k: v for k, v in member_state.items() if k in Applicant.model_fields}
        try:
            member_applicant = Applicant(**fields)
        except Exception:
            return None, None
        member_quote = next((q for q in quote_current(member_applicant, settings) if q.plan_key == req.plan_key), None)
        if member_quote is None:
            return None, None
        base = base or member_quote
        total += member_quote.premium
        lines.append(f"{labels.get(member_id, member_id)}: {member_quote.currency} {member_quote.premium:,.2f}")
    if base is None:
        return None, None
    quote = base.model_copy(update={"premium": round(total, 2), "family_size": len(wanted)})
    return quote, lines


class CompareRequest(BaseModel):
    applicant_state: dict = Field(default_factory=dict)
    plan_keys: list[str] = Field(min_length=1, max_length=4)
    language: str = Field(default="en", pattern="^(en|el)$")
    has_current_policy: bool = False


@router.post("/compare")
async def compare(req: CompareRequest):
    """Detailed benefit-by-benefit comparison using server-recomputed eligible plans."""
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
