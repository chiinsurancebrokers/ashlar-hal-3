from __future__ import annotations

from pydantic import BaseModel, Field
from backend.app.evidence.catalogue import load_carrier_table, verified_benefit, catalogue_checklist


class CataloguePlan(BaseModel):
    plan_key: str
    insurer: str
    product_code: str
    product_name: str
    product_family: str
    match_status: str = "not_assessed"
    eligibility_status: str = "requires_carrier_confirmation"
    eligibility_checks: list[str] = Field(default_factory=list)
    matched_requirements: list[str] = Field(default_factory=list)
    unmatched_requirements: list[str] = Field(default_factory=list)
    unconfirmed_requirements: list[str] = Field(default_factory=list)
    card_why: str = ""
    premium: None = None
    base_premium: None = None
    currency: str = "EUR"
    rate_version: str = "quotation_required"
    pricing_status: str = "quotation_required"
    eligible: None = None
    deductible: None = None
    card_deductible: str = "Not specified"
    coverage_area_label: str = "Not specified"
    card_annual_limit: str = "Not specified"
    evidence_confidence: float = 1.0
    benefit_checklist: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def catalogue_plan(row: dict) -> CataloguePlan:
    carrier, code = row["carrier"], row["product_code"]
    table = load_carrier_table(carrier) or {}
    maximum = verified_benefit(carrier, code, "overall_maximum")
    warnings = [row["pricing_note"],
                "Benefit comparison only, in EUR. No premium or acceptance is confirmed.",
                "Brochure summary; individual schedule, underwriting, options and full policy terms govern cover."]
    if table.get("eligibility_note"):
        warnings.append(table["eligibility_note"])
    return CataloguePlan(
        plan_key=row["plan_key"], insurer=row["carrier_name"], product_code=code,
        product_name=row["plan_name"], product_family=row["product_family"],
        card_annual_limit=maximum["values"][code] if maximum else "Not specified",
        benefit_checklist=catalogue_checklist(carrier, code), warnings=warnings,
    )
