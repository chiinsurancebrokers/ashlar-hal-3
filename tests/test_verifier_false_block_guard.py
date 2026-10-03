from backend.app.services.verifier_agent import (
    VerificationDecision,
    VerificationIssue,
    _normalise_model_decision,
    deterministic_verify,
)


def test_no_fixed_budget_and_unknown_evacuation_evidence_do_not_block():
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
    assert deterministic_verify(state, [quote]).verdict == "PASS"


def test_model_uncertainty_cannot_override_deterministic_pass_to_block():
    decision = VerificationDecision(
        verdict="BLOCK",
        safe_action="block_and_review",
        model_used=True,
        model_status="ok",
        issues=[VerificationIssue(
            severity="block",
            issue_type="must_have_not_covered",
            field="evacuation_required",
            expected="covered",
            actual="unknown",
            evidence="Evacuation evidence is not loaded.",
            suggested_action="Block shortlist.",
        )],
    )
    guarded = _normalise_model_decision(decision, "Here is HAL's shortlist.")
    assert guarded.verdict == "WARN"
    assert guarded.safe_action == "allow_with_warning"
    assert guarded.issues[0].severity == "warn"


def test_explicit_deterministic_uncovered_must_have_still_blocks():
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
    assert deterministic_verify(state, [quote]).verdict == "BLOCK"
