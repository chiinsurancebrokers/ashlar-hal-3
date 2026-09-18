from fastapi.testclient import TestClient

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
