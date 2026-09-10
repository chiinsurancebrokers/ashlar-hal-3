from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.core.config import get_settings
from backend.app.schemas.applicant import Applicant
from backend.app.rates.quote_engine import quote_shortlist, quote_exclusions, quote_current
from backend.app.evidence.compare_matrix import build_comparison_matrix, matrix_to_dict
from backend.app.evidence.carrier_profile import carrier_profile
from backend.app.services.adviser import comparison_conclusion

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


class CompareRequest(BaseModel):
    applicant_state: dict = Field(default_factory=dict)
    plan_keys: list[str] = Field(min_length=2, max_length=4)


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
    if len(selected) < 2:
        raise HTTPException(status_code=400, detail="At least 2 currently eligible plan_keys are required to compare.")

    plans_for_matrix = [
        {"plan_key": q.plan_key, "carrier": q.plan_key.split(":")[0], "product_code": q.product_code,
         "insurer": q.insurer, "product_name": q.product_name}
        for q in selected
    ]
    matrix = build_comparison_matrix(plans_for_matrix)
    matrix_dict = matrix_to_dict(matrix)

    # Note: language detection from applicant_state isn't wired yet, so this
    # always returns an English conclusion for now — matches the current
    # /quotes/preview endpoint too. Extending both to respect a language
    # preference is a straightforward follow-up.
    conclusion = await comparison_conclusion(matrix_dict["rows"], matrix_dict["plan_labels"], greek=False)

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
