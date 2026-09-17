from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_chat_create_proposal_routes_through_orchestrator_and_returns_real_files():
    applicant = {
        "age": 51,
        "residence_country": "Greece",
        "coverage_area": "area1",
        "outpatient_required": True,
        "applicant_name": "Orchestrator Proposal Test",
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

    state = dict(applicant)
    state["_adviser_os_case_id"] = compare_data["case_id"]
    state["_adviser_os_case_token"] = compare_data["case_token"]

    chat = client.post(
        "/api/v1/chat/turn",
        json={"message": "Create the proposal.", "state": state, "history": []},
    )
    assert chat.status_code == 200, chat.text
    data = chat.json()

    assert data["_adviser_os"]["decision"]["intent"] == "proposal"
    assert data["_adviser_os"]["decision"]["specialists"] == ["proposal_writer"]
    assert data["_adviser_os"]["responses"][0]["specialist"] == "proposal_writer"
    assert data["_adviser_os"]["responses"][0]["status"] == "completed"
    assert data["proposal_downloads"]["pdf"].endswith("/pdf")
    assert data["proposal_downloads"]["pptx"].endswith("/pptx")

    pdf = client.get(data["proposal_downloads"]["pdf"])
    pptx = client.get(data["proposal_downloads"]["pptx"])
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert pdf.headers["cache-control"].startswith("no-store")
    assert pptx.status_code == 200
    assert pptx.content.startswith(b"PK")
    assert pptx.headers["cache-control"].startswith("no-store")
