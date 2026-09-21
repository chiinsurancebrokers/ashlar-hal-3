from fastapi.testclient import TestClient

from backend.app.cases.models import AshlarCase, CaseStatus
from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.orchestrator_main import app


client = TestClient(app)


def test_dedicated_orchestrator_fastapi_health_declares_boundaries():
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "ashlar-orchestrator"
    assert body["specialists"] == [
        "hal_adviser",
        "document_analyst",
        "proposal_writer",
        "health_navigator",
    ]
    assert "quote_engine" in body["deterministic_engines"]
    assert body["case_store"] == "process_local"
    assert body["independent_deployment_ready"] is False


def test_dedicated_orchestrator_fastapi_uses_same_handle_contract():
    response = client.post(
        "/v1/handle",
        json={"message": "How much would these plans cost?"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["decision"]["intent"] == "quote"
    assert body["decision"]["deterministic_engines"] == ["quote_engine"]



def test_dedicated_orchestrator_fastapi_owns_lifecycle_actions():
    record = CASE_ANALYSIS_STORE.put(
        case=AshlarCase(
            status=CaseStatus.PROPOSAL,
            selected_plan_keys=["carrier:a", "carrier:b"],
        ),
        results=[],
    )

    response = client.post(
        f"/v1/journey/{record.case.case_id}/select-plan",
        json={
            "case_token": record.access_token,
            "plan_key": "carrier:a",
            "selected_by": "client",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "prepare_application"
    assert body["case_id"] == str(record.case.case_id)
    assert body["case_intelligence"]["journey"]["current_step"] == 13
