from backend.app.cases.models import AshlarCase, CaseClient
from backend.app.schemas.applicant import Applicant


def test_case_wraps_existing_applicant_model():
    applicant = Applicant(age=51, residence_country="Greece", coverage_area="area2")
    case = AshlarCase(
        client=CaseClient(display_name="Test Client"),
        applicant=applicant,
    )

    assert case.applicant.age == 51
    assert case.applicant.residence_country == "Greece"
    assert case.status.value == "discovery"
    assert case.case_id


def test_case_has_independent_mutable_collections():
    first = AshlarCase(client=CaseClient(display_name="First"))
    second = AshlarCase(client=CaseClient(display_name="Second"))

    first.tags.append("hnwi")

    assert first.tags == ["hnwi"]
    assert second.tags == []
