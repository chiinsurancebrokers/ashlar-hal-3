"""
Regression tests: each of these encodes a real recommendation failure that
was caught and fixed. They must never be deleted or weakened — if a future
change breaks one, that is exactly the "build fails before deployment"
safety net the self-improving-HAL design calls for.
"""
from backend.app.schemas.applicant import Applicant
from backend.app.matching.engine import evaluate_requirements


# REGRESSION #1 — 2026-audit finding.
# Age 51, Area 2, routine maternity = MUST HAVE.
# Standard / Standard Plus / Comprehensive do NOT cover routine maternity on
# Morgan Price 2026 and must be HARD-excluded from the shortlist — not shown
# with a low match score, not shown at all as a recommended option.
# Premium and Elite DO cover it and must be eligible.
def test_regression_maternity_hard_excludes_lower_tiers():
    applicant = Applicant(age=51, residence_country="Greece", coverage_area="area2", maternity_required=True)

    must_fail = ["standard", "standard_plus", "comprehensive"]
    must_pass = ["premium", "elite"]

    for code in must_fail:
        outcome = evaluate_requirements(applicant, "morgan_price", code)
        assert outcome.eligible is False, f"{code} must be excluded when maternity is a MUST HAVE"
        assert outcome.requirements_score == 0.0
        assert "Routine maternity" in outcome.unmatched

    for code in must_pass:
        outcome = evaluate_requirements(applicant, "morgan_price", code)
        assert outcome.eligible is True, f"{code} must remain eligible — it covers routine maternity"
        assert outcome.requirements_score == 1.0
        assert "Routine maternity" in outcome.matched


# REGRESSION #2 — a 0% match on a MUST-HAVE must never be shown as "still a
# recommendation with a low score". eligible must be a hard boolean.
def test_regression_zero_score_means_not_eligible_not_low_score():
    applicant = Applicant(age=40, residence_country="Greece", coverage_area="area1", maternity_required=True)
    outcome = evaluate_requirements(applicant, "morgan_price", "standard")
    assert outcome.eligible is False
    assert outcome.requirements_score == 0.0


# REGRESSION #3 — plans from carriers we hold no verified benefit-level
# evidence for must never be HARD-excluded on a must-have (we simply don't
# know), but must also never be silently promoted above a verified match.
def test_regression_unverified_carrier_is_not_hard_excluded():
    applicant = Applicant(age=40, residence_country="Greece", coverage_area="area1", maternity_required=True)
    outcome = evaluate_requirements(applicant, "april", "international")
    assert outcome.eligible is True
    assert outcome.evidence_confidence == 0.0
    assert outcome.requirements_score is None
