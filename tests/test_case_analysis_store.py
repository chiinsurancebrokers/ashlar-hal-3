from types import SimpleNamespace

from backend.app.api.quotes import CompareRequest, _server_case
from backend.app.cases.models import AshlarCase, CaseStatus
from backend.app.cases.store import ServerCaseAnalysisStore
from backend.app.schemas.applicant import Applicant


def test_server_case_analysis_store_requires_opaque_token_and_returns_copies():
    store = ServerCaseAnalysisStore(ttl_hours=1, max_items=4)
    case = AshlarCase(status=CaseStatus.COMPARISON)
    record = store.put(case=case, results=[{"target_plan": "Plan A", "analysis": {"plan_name": "Plan A"}}])

    assert len(record.access_token) >= 32
    assert store.get(case.case_id, "wrong-token") is None

    loaded = store.get(case.case_id, record.access_token)
    assert loaded is not None
    loaded.case.status = CaseStatus.PROPOSAL

    # Reading a case never mutates the server-owned copy without save_case().
    again = store.get(case.case_id, record.access_token)
    assert again is not None
    assert again.case.status == CaseStatus.COMPARISON


def test_server_comparison_case_strips_medical_free_text_before_storage():
    applicant = Applicant(
        age=51,
        residence_country="Greece",
        coverage_area="area1",
        chronic_conditions_disclosed=True,
        chronic_conditions_note="highly sensitive free-text medical details",
    )
    req = CompareRequest(
        applicant_state={"applicant_name": "Privacy Test"},
        plan_keys=["carrier:a", "carrier:b"],
        language="en",
    )
    selected = [SimpleNamespace(plan_key="carrier:a"), SimpleNamespace(plan_key="carrier:b")]

    case = _server_case(req, applicant, selected)

    assert case.applicant is not None
    assert case.applicant.chronic_conditions_disclosed is True
    assert case.applicant.chronic_conditions_note is None
    assert case.needs_profile["medical_disclosure_present"] is True
