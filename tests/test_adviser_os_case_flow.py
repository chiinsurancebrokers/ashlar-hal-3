from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.main import app


client = TestClient(app)


def _comparison_payload():
    applicant = {
        "age": 51,
        "residence_country": "Greece",
        "coverage_area": "area1",
        "outpatient_required": True,
        "chronic_conditions_disclosed": True,
        "chronic_conditions_note": "private medical free text must never enter proposal case storage",
        "applicant_name": "Case Flow Test",
    }
    preview = client.post("/api/v1/quotes/preview", json=applicant)
    assert preview.status_code == 200
    shortlist = preview.json()["shortlist"]
    assert len(shortlist) >= 2
    plan_keys = [item["plan_key"] for item in shortlist[:2]]
    return applicant, plan_keys


def test_homepage_loads_additive_adviser_os_bridge():
    response = client.get("/")
    assert response.status_code == 200
    assert '/static/adviser-os.js' in response.text
    assert response.headers["cache-control"].startswith("no-store")


def test_compare_creates_server_owned_case_and_strips_medical_free_text():
    applicant, plan_keys = _comparison_payload()
    response = client.post(
        "/api/v1/quotes/compare",
        json={"applicant_state": applicant, "plan_keys": plan_keys, "language": "en"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["case_id"]
    assert len(data["case_token"]) >= 32
    assert "proposal_quality" in data

    record = CASE_ANALYSIS_STORE.get(UUID(data["case_id"]), data["case_token"])
    assert record is not None
    assert record.case.applicant is not None
    assert record.case.applicant.chronic_conditions_disclosed is True
    assert record.case.applicant.chronic_conditions_note is None
    assert record.case.selected_plan_keys == plan_keys


def test_prepare_endpoint_rejects_invalid_case_token_without_accepting_plan_facts():
    applicant, plan_keys = _comparison_payload()
    comparison = client.post(
        "/api/v1/quotes/compare",
        json={"applicant_state": applicant, "plan_keys": plan_keys, "language": "en"},
    )
    assert comparison.status_code == 200
    data = comparison.json()

    response = client.post(
        "/api/v1/proposals/prepare",
        json={"case_id": data["case_id"], "case_token": "x" * 32, "language": "en"},
    )
    assert response.status_code == 404



def test_adviser_os_frontend_exposes_case_bound_document_attachment_flow():
    response = client.get("/static/adviser-os.js")

    assert response.status_code == 200
    source = response.text
    assert "attachCarrierDocumentBtn" in source
    assert "/documents/upload" in source
    assert "_adviser_os_document_refs" in source
    assert "provider_label" in source
    assert "target_plan" in source
    assert "plan_key" in source
