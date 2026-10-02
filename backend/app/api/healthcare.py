from fastapi import APIRouter, Query

from backend.app.services.healthcare_context_agent import assess_healthcare_context

router = APIRouter(prefix="/healthcare", tags=["healthcare"])


@router.get("/context")
def context(
    country: str = Query(min_length=2, max_length=80),
    language: str = Query(default="en", pattern="^(en|el)$"),
):
    return assess_healthcare_context(country, language).model_dump(mode="json")
