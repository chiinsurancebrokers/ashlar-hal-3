from datetime import date

from backend.app.services.adviser import (
    clean_applicant_updates, build_intake_instructions, build_explain_plan_instructions,
    build_local_review_instructions, _deterministic_plan_summary,
)
from backend.app.services.openai_client import build_request_body
from backend.app.schemas.quote import QuoteResult


def test_clean_applicant_updates_rejects_unknown_fields():
    out = clean_applicant_updates({"age": 40, "hack_field": "drop me", "premium": 1})
    assert out == {"age": 40}


def test_clean_applicant_updates_rejects_invalid_coverage_area():
    out = clean_applicant_updates({"coverage_area": "area9"})
    assert "coverage_area" not in out


def test_clean_applicant_updates_type_coerces_and_bounds_age():
    assert clean_applicant_updates({"age": "200"}) == {}
    assert clean_applicant_updates({"age": "45"}) == {"age": 45}


def test_intake_instructions_never_let_llm_calculate_premium_or_eligibility():
    instr = build_intake_instructions({}, greek=False)
    assert "Do not calculate premiums" in instr
    assert "Do not invent benefits" in instr


def _sample_quote() -> QuoteResult:
    return QuoteResult(
        insurer="Morgan Price (Europe) ApS", product_code="premium", product_name="Morgan Price Premium",
        eligible=True, base_premium=6868.77, premium=6868.77, currency="EUR",
        rate_version="v", coverage_area_label="Europe", official_rate=True,
        evidence_status="verified", evidence_confidence=1.0, requirements_score=1.0,
        matched_requirements=["Routine maternity"], unmatched_requirements=[],
        verified_facts=["Routine maternity: €7,500 (Table of Benefits p.4)."],
        quoted_on=date(2026, 1, 1), valid_until=date(2026, 1, 31),
    )


def test_explain_plan_instructions_restrict_to_verified_facts_only():
    q = _sample_quote()
    instr = build_explain_plan_instructions(q, greek=False)
    assert "Routine maternity: €7,500" in instr
    assert "Never state a benefit" in instr
    assert "6,868.77" in instr


def test_deterministic_fallback_never_needs_network():
    q = _sample_quote()
    text = _deterministic_plan_summary(q, greek=False)
    assert "6,868.77" in text
    assert "Morgan Price Premium" in text


def test_local_review_instructions_include_never_lose_the_prospect_principle():
    instr = build_local_review_instructions(greek=False)
    assert "opportunity" in instr.lower()


def test_request_body_always_disables_storage():
    body = build_request_body(instructions="x", message="hi", history=None, json_mode=False)
    assert body["store"] is False
