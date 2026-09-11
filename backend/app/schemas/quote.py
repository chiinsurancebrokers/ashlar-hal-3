from __future__ import annotations
from datetime import date, timedelta
from pydantic import BaseModel


class QuoteResult(BaseModel):
    insurer: str
    product_code: str
    product_name: str
    eligible: bool

    # Pricing
    base_premium: float          # per primary applicant, before deductible/family adjustments
    premium: float                # final annual premium actually shown to the client
    currency: str
    rate_version: str
    deductible: float | None = None
    deductible_note: str | None = None   # explains whether/how the deductible affected price

    # Family pricing
    family_size: int = 1
    per_member_premiums: list[float] = []
    family_discount_applied: bool = False

    coverage_area_label: str
    official_rate: bool

    # Evidence gate
    evidence_status: str
    evidence_confidence: float
    requirements_score: float | None
    matched_requirements: list[str] = []
    unmatched_requirements: list[str] = []
    verified_facts: list[str] = []
    source_documents: list[str] = []
    reasons: list[str] = []
    warnings: list[str] = []

    # Quote validity
    quoted_on: date
    valid_until: date

    # Client-facing shortlist metadata (populated by matching layer)
    plan_key: str | None = None
    card_badge: str | None = None
    card_coverage: str | None = None
    card_annual_limit: str | None = None
    card_deductible: str | None = None
    card_evacuation: str | None = None
    card_why: str | None = None
    client_note: str | None = None
    fit_badges: list[str] = []
    must_have_checks: list[str] = []
    benefit_checklist: list[dict] = []
    recommended: bool = False
    recommendation_rank: int | None = None

    @staticmethod
    def validity_window(quoted_on: date, validity_days: int) -> date:
        return quoted_on + timedelta(days=validity_days)
