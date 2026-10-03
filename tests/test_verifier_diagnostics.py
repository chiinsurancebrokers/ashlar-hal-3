from backend.app.services.verifier_agent import VerificationDecision, VerificationIssue
from backend.app.services.verifier_diagnostics import verifier_diagnostic


def test_diagnostic_exposes_reason_without_evidence_or_pii():
    decision = VerificationDecision(verdict="BLOCK", safe_action="block_and_review", model_used=True, model_status="ok", issues=[VerificationIssue(severity="block", issue_type="unsupported_claim", field="evacuation_required", evidence="sensitive free text", suggested_action="review")])
    diagnostic = verifier_diagnostic(decision)
    assert diagnostic["verdict"] == "BLOCK"
    assert diagnostic["issues"] == [{"severity": "block", "issue_type": "unsupported_claim", "field": "evacuation_required"}]
    assert "sensitive free text" not in str(diagnostic)
