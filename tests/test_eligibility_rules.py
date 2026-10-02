from backend.app.schemas.applicant import Applicant
from backend.app.evidence.eligibility_rules import evaluate_profile, evaluate_plan_eligibility, load_eligibility_rules


def test_greek_local_profile_accepts_greek_national_abroad():
    applicant = Applicant(age=40, residence_country='Germany', nationality='Greece')
    d = evaluate_profile(applicant, 'greek_local_resident_or_national')
    assert d.status == 'eligible'


def test_greek_local_profile_accepts_non_greek_permanent_resident_in_greece():
    applicant = Applicant(age=40, residence_country='Greece', nationality='Germany')
    d = evaluate_profile(applicant, 'greek_local_resident_or_national')
    assert d.status == 'eligible'


def test_greek_local_profile_rejects_when_neither_condition_matches():
    applicant = Applicant(age=40, residence_country='Germany', nationality='France')
    d = evaluate_profile(applicant, 'greek_local_resident_or_national')
    assert d.status == 'ineligible'


def test_april_myhealth_profile_requires_residence_different_from_nationality():
    expat = Applicant(age=40, residence_country='Greece', nationality='France')
    local = Applicant(age=40, residence_country='Greece', nationality='Greece')
    assert evaluate_profile(expat, 'april_myhealth_expat').status == 'eligible'
    assert evaluate_profile(local, 'april_myhealth_expat').status == 'ineligible'


def test_missing_nationality_is_unknown_for_myhealth_not_silently_ineligible():
    applicant = Applicant(age=40, residence_country='Greece')
    assert evaluate_profile(applicant, 'april_myhealth_expat').status == 'unknown'


def test_future_examples_do_not_activate_rules_on_current_catalogue():
    applicant = Applicant(age=40, residence_country='Greece', nationality='Greece')
    assert load_eligibility_rules()['plan_profiles'] == {}
    assert evaluate_plan_eligibility(applicant, 'april', 'essential').status == 'eligible'
