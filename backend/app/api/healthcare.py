from fastapi import APIRouter, Query

from backend.app.services.healthcare_context import healthcare_context

router = APIRouter(prefix="/healthcare", tags=["healthcare"])


@router.get("/context")
def context(
    country: str = Query(min_length=2, max_length=80),
    language: str = Query(default="en", pattern="^(en|el)$"),
):
    return healthcare_context(country, language)
