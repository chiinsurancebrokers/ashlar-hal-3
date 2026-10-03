from backend.app.services.verifier_agent import deterministic_verify


def test_unknown_must_have_evidence_does_not_block_shortlist():
    state = {"coverage_area": "area1", "evacuation_required": True}
    quote = {
        "plan_key": "test-plan",
        "product_name": "Test Plan",
        "eligible": True,
        "premium": 1000,
        "coverage_area_label": "Europe",
        "evidence_confidence": 0.0,
        "benefit_checklist": [],
        "matched_requirements": [],
        "unmatched_requirements": [],
    }
    decision = deterministic_verify(state, [quote])
    assert decision.verdict == "PASS"


def test_explicitly_uncovered_must_have_still_blocks():
    state = {"coverage_area": "area1", "evacuation_required": True}
    quote = {
        "plan_key": "test-plan",
        "product_name": "Test Plan",
        "eligible": True,
        "premium": 1000,
        "coverage_area_label": "Europe",
        "evidence_confidence": 1.0,
        "benefit_checklist": [{"field": "evacuation_required", "covered": False}],
        "matched_requirements": [],
        "unmatched_requirements": ["Medical evacuation"],
    }
    decision = deterministic_verify(state, [quote])
    assert decision.verdict == "BLOCK"
    assert any(i.issue_type == "must_have_not_covered" for i in decision.issues)
