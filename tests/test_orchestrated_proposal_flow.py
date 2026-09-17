import asyncio
from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.agents.orchestrator import get_ashlar_orchestrator
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

    # Exercise the orchestration core directly here. /chat/turn is separately
    # covered by test_adviser_api; using it again in this long end-to-end test
    # would make the test depend on process-global rate-limiter state created by
    # earlier API tests.
    result = asyncio.run(
        get_ashlar_orchestrator().handle(
            case_id=UUID(compare_data["case_id"]),
            message="Create the proposal.",
            context={
                "state": state,
                "case_token": compare_data["case_token"],
                "language": "en",
            },
        )
    )

    assert result.decision.intent.value == "proposal"
    assert [item.value for item in result.decision.specialists] == ["proposal_writer"]
    primary = result.responses[0]
    assert primary.specialist.value == "proposal_writer"
    assert primary.status == "completed"
    downloads = primary.payload["downloads"]
    assert downloads["pdf"].endswith("/pdf")
    assert downloads["pptx"].endswith("/pptx")

    pdf = client.get(downloads["pdf"])
    pptx = client.get(downloads["pptx"])
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert pdf.headers["cache-control"].startswith("no-store")
    assert pptx.status_code == 200
    assert pptx.content.startswith(b"PK")
    assert pptx.headers["cache-control"].startswith("no-store")
