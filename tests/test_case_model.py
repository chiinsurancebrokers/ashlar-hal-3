from pydantic import ValidationError

from backend.app.cases.models import AshlarCase, CaseClient, CaseStatus
from backend.app.schemas.applicant import Applicant


def test_case_wraps_existing_hal_applicant_without_changing_quote_schema():
    applicant = Applicant(
        age=51,
        residence_country="Greece",
        coverage_area="area2",
        outpatient_required=True,
    )
    case = AshlarCase(
        client=CaseClient(display_name="Test Client", email="client@example.com"),
        applicant=applicant,
    )

    assert case.status == CaseStatus.DISCOVERY
    assert case.applicant is not None
    assert case.applicant.age == 51
    assert case.applicant.outpatient_required is True
    assert case.case_id is not None


def test_case_models_fail_closed_on_unknown_fields():
    try:
        AshlarCase(unknown_field="should-not-be-accepted")
        assert False, "unknown fields must not be silently accepted"
    except ValidationError:
        pass
