from types import SimpleNamespace

from backend.app.core.config import Settings
from backend.app.schemas.applicant import Applicant
from backend.app.services.orchestrator import _applicant_from_state
from backend.app.services.eligibility_agent import deterministic_eligibility_audit
from backend.app.rates.quote_engine import quote_current
from backend.app.evidence.eligibility_rules import EligibilityDecision


FAKE_RULES = {
    "profiles": {
        "april_myhealth_expat": {
            "description": "Residence must differ from nationality.",
            "operator": "all",
            "conditions": [
                {"field": "residence_country", "different_from_field": "nationality"}
            ],
        }
    },
    "plan_profiles": {
        "april:myhealth": "april_myhealth_expat",
    },
}


def _one_april_rate():
    return [
        SimpleNamespace(
            area="area1",
            carrier="april",
            product_code="myhealth",
        )
    ]


def test_primary_healthcare_country_is_carried_into_applicant():
    applicant = _applicant_from_state({
        "age": 51,
        "residence_country": "Greece",
        "nationality": "Greece",
        "primary_healthcare_country": "Greece",
        "coverage_area": "area1",
    })
    assert applicant is not None
    assert applicant.primary_healthcare_country == "Greece"


def test_eligibility_agent_blocks_only_candidate_when_expat_rule_fails(monkeypatch):
    import backend.app.evidence.eligibility_rules as rules
    import backend.app.services.eligibility_agent as agent

    monkeypatch.setattr(rules, "load_eligibility_rules", lambda: FAKE_RULES)
    monkeypatch.setattr(agent, "load_rates", _one_april_rate)

    applicant = Applicant(
        age=40,
        residence_country="Greece",
        nationality="Greece",
        primary_healthcare_country="Greece",
        coverage_area="area1",
    )
    result = deterministic_eligibility_audit(applicant)
    assert result.verdict == "BLOCK"
    assert result.plans[0].status == "ineligible"


def test_eligibility_agent_passes_expat_rule_when_residence_differs(monkeypatch):
    import backend.app.evidence.eligibility_rules as rules
    import backend.app.services.eligibility_agent as agent

    monkeypatch.setattr(rules, "load_eligibility_rules", lambda: FAKE_RULES)
    monkeypatch.setattr(agent, "load_rates", _one_april_rate)

    applicant = Applicant(
        age=40,
        residence_country="Greece",
        nationality="United Kingdom",
        primary_healthcare_country="Greece",
        coverage_area="area1",
    )
    result = deterministic_eligibility_audit(applicant)
    assert result.verdict == "PASS"
    assert result.plans[0].status == "eligible"


def test_eligibility_agent_requests_missing_nationality(monkeypatch):
    import backend.app.evidence.eligibility_rules as rules
    import backend.app.services.eligibility_agent as agent

    monkeypatch.setattr(rules, "load_eligibility_rules", lambda: FAKE_RULES)
    monkeypatch.setattr(agent, "load_rates", _one_april_rate)

    applicant = Applicant(
        age=40,
        residence_country="Greece",
        nationality=None,
        primary_healthcare_country="Greece",
        coverage_area="area1",
    )
    result = deterministic_eligibility_audit(applicant)
    assert result.verdict == "NEEDS_INFO"
    assert result.plans[0].status == "unknown"
    assert "nationality" in result.missing_fields


def test_quote_engine_hides_unknown_eligibility(monkeypatch):
    import backend.app.rates.quote_engine as quote_engine

    monkeypatch.setattr(
        quote_engine,
        "evaluate_plan_eligibility",
        lambda applicant, carrier, product_code: EligibilityDecision(
            "unknown", "test_profile", "More eligibility information is required."
        ),
    )
    applicant = Applicant(
        age=40,
        residence_country="Greece",
        nationality="Greece",
        primary_healthcare_country="Greece",
        coverage_area="area1",
    )
    assert quote_current(applicant, Settings()) == []
