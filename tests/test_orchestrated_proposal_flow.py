import asyncio
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from backend.app.core.config import get_settings

@pytest.fixture(autouse=True)
def broker_config(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "upload-test-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


from backend.app.agents.orchestrator import get_ashlar_orchestrator
from backend.app.main import app


client = TestClient(app)


def _upload_quote(compare_data, plan):
    response = client.post(
        "/api/v1/documents/upload",
        headers={"X-Admin-Password": "upload-test-secret"},
        data={
            "case_id": compare_data["case_id"],
            "case_token": compare_data["case_token"],
            "provider_label": plan["insurer"],
            "target_plan": plan["product_name"],
            "plan_key": plan["plan_key"],
            "role": "quotation",
        },
        files={
            "file": (
                f'{plan["product_code"]}-quotation.txt',
                (
                    f'{plan["product_name"]} applicant quotation. '
                    f'Annual premium EUR {plan["premium"]}. '
                    'Area of cover Europe.'
                ).encode(),
                "text/plain",
            )
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["document_ref"]


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
    selected = shortlist[:2]
    plan_keys = [item["plan_key"] for item in selected]

    comparison = client.post(
        "/api/v1/quotes/compare",
        json={"applicant_state": applicant, "plan_keys": plan_keys, "language": "en"},
    )
    assert comparison.status_code == 200
    compare_data = comparison.json()
    assert compare_data["proposal_available"] is False

    document_refs = [_upload_quote(compare_data, plan) for plan in selected]

    state = dict(applicant)
    state["_adviser_os_case_id"] = compare_data["case_id"]
    state["_adviser_os_case_token"] = compare_data["case_token"]
    state["_adviser_os_document_refs"] = document_refs

    # Exercise the complete compound orchestration:
    # documents -> conflict/readiness checks -> proposal_writer -> artifacts.
    result = asyncio.run(
        get_ashlar_orchestrator().handle(
            case_id=UUID(compare_data["case_id"]),
            message="Compare these carrier quotations and create the proposal.",
            context={
                "broker_authorized": True,
                "state": state,
                "case_token": compare_data["case_token"],
                "document_refs": document_refs,
                "language": "en",
            },
        )
    )

    assert result.decision.intent.value == "proposal"
    assert [item.value for item in result.decision.specialists] == [
        "document_analyst",
        "proposal_writer",
    ]
    assert result.responses[0].specialist.value == "document_analyst"
    assert result.responses[0].status == "completed"
    primary = result.responses[-1]
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
