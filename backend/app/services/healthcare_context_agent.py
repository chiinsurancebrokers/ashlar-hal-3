from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from backend.app.services.healthcare_context import healthcare_context


class HealthcareContextDecision(BaseModel):
    available: bool
    country: str
    context: dict[str, Any]
    evidence_quality: str
    cautions: list[str] = Field(default_factory=list)


def assess_healthcare_context(country: str, language: str = "en") -> HealthcareContextDecision:
    """Return curated healthcare-system context without inventing country facts."""
    context = healthcare_context(country, language)
    if not context.get("available"):
        return HealthcareContextDecision(
            available=False, country=country, context=context, evidence_quality="unavailable",
            cautions=["No curated country evidence is loaded; no healthcare-system claim should be inferred."],
        )
    sources = context.get("sources") or []
    metrics = context.get("metrics") or []
    cautions: list[str] = []
    if not sources:
        cautions.append("Curated context has no source links and should not be used for comparative claims.")
    if not metrics:
        cautions.append("Curated context has no structured metrics.")
    quality = "curated_with_sources" if sources else "curated_without_sources"
    return HealthcareContextDecision(
        available=True, country=str(context.get("country") or country), context=context,
        evidence_quality=quality, cautions=cautions,
    )
