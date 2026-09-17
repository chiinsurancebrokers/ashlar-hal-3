from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_server_owned_case_can_prepare_and_download_real_proposal():
    applicant = {
        "age": 51,
        "residence_country": "Greece",
        "coverage_area": "area1",
        "outpatient_required": True,
        "applicant_name": "Proposal Flow Test",
    }
    preview = client.post("/api/v1/quotes/preview", json=applicant)
    assert preview.status_code == 200
    shortlist = preview.json()["shortlist"]
    assert len(shortlist) >= 2
    plan_keys = [item["plan_key"] for item in shortlist[:2]]

    comparison = client.post(
        "/api/v1/quotes/compare",
        json={"applicant_state": applicant, "plan_keys": plan_keys, "language": "en"},
    )
    assert comparison.status_code == 200
    compare_data = comparison.json()
    assert compare_data["proposal_available"] is True

    prepared = client.post(
        "/api/v1/proposals/prepare",
        json={
            "case_id": compare_data["case_id"],
            "case_token": compare_data["case_token"],
            "language": "en",
        },
    )
    assert prepared.status_code == 200, prepared.text
    data = prepared.json()
    assert data["status"] == "ready"
    assert data["case_status"] == "proposal"

    pdf = client.get(data["downloads"]["pdf"])
    pptx = client.get(data["downloads"]["pptx"])
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert pdf.headers["cache-control"].startswith("no-store")
    assert pptx.status_code == 200
    assert pptx.content.startswith(b"PK")
    assert pptx.headers["cache-control"].startswith("no-store")
