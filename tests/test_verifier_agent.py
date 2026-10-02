import pytest

from backend.app.services.verifier_agent import deterministic_verify


def _quote(**overrides):
    q = {
        "plan_key": "morgan_price:standard_plus",
        "product_name": "Standard Plus",
        "insurer": "Morgan Price",
        "eligible": True,
        "premium": 2694.72,
        "currency": "EUR",
        "coverage_area_label": "Europe",
        "evidence_confidence": 1.0,
        "matched_requirements": [],
        "unmatched_requirements": [],
        "benefit_checklist": [],
    }
    q.update(overrides)
    return q


def test_blocks_europe_request_when_quote_is_worldwide_area():
    state = {"coverage_area": "area1"}
    result = deterministic_verify(
        state,
        [_quote(coverage_area_label="Worldwide excluding USA, Singapore, Hong Kong & China")],
    )
    assert result.verdict == "BLOCK"
    assert any(i.issue_type == "pricing_geography_mismatch" for i in result.issues)


def test_blocks_required_outpatient_when_plan_evidence_marks_not_covered():
    state = {"coverage_area": "area1", "outpatient_required": True}
    result = deterministic_verify(
        state,
        [_quote(
            benefit_checklist=[
                {"field": "outpatient_required", "label": "Out-patient cover", "covered": False}
            ]
        )],
    )
    assert result.verdict == "BLOCK"
    assert any(i.issue_type == "must_have_not_covered" for i in result.issues)


def test_warns_when_greek_journey_returns_english_explanation():
    state = {"coverage_area": "area1"}
    result = deterministic_verify(
        state,
        [_quote()],
        rendered_reply="Here is your shortlisted plan with the verified annual premium and benefits.",
        expected_greek=True,
    )
    assert result.verdict == "WARN"
    assert any(i.issue_type == "language_drift" for i in result.issues)


def test_blocks_contradictory_current_policy_benefit_rows():
    state = {"coverage_area": "area1"}
    current_policy = {
        "benefit_rows": [
            {"benefit_code": "outpatient", "status": "confirmed"},
            {"benefit_code": "outpatient", "status": "not_covered"},
        ]
    }
    result = deterministic_verify(
        state,
        [_quote()],
        current_policy=current_policy,
    )
    assert result.verdict == "BLOCK"
    assert any(i.issue_type == "current_policy_evidence_contradiction" for i in result.issues)


def test_passes_consistent_verified_quote():
    state = {"coverage_area": "area1", "outpatient_required": True}
    result = deterministic_verify(
        state,
        [_quote(
            matched_requirements=["Out-patient cover"],
            benefit_checklist=[
                {"field": "outpatient_required", "label": "Out-patient cover", "covered": True}
            ],
        )],
    )
    assert result.verdict == "PASS"
    assert result.issues == []
