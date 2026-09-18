from __future__ import annotations

import inspect

from fastapi.testclient import TestClient

from backend.app.agents.contracts import (
    OrchestrationDecision,
    OrchestrationIntent,
    OrchestratorResult,
    SpecialistName,
    SpecialistResponse,
)
from backend.app.api import chat as chat_api
from backend.app.api.chat import ChatRequest, _legacy_chat_payload
from backend.app.main import app


client = TestClient(app)


def test_adviser_handle_is_the_public_orchestrator_front_door():
    response = client.post(
        "/api/v1/adviser/handle",
        json={"message": "How much would these plans cost?"},
    )

    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"
    body = response.json()
    assert body["decision"]["intent"] == "quote"
    assert body["decision"]["deterministic_engines"] == ["quote_engine"]
    assert body["decision"]["specialists"] == ["hal_adviser"]
    assert body["responses"][0]["specialist"] == "hal_adviser"
    assert "collecting missing quote inputs" in body["decision"]["reason"].lower()
    assert body.get("payload", {}).get("quotes") in (None, [])


def test_adviser_handle_rejects_privileged_browser_context_injection():
    response = client.post(
        "/api/v1/adviser/handle",
        json={
            "message": "Why do you recommend this?",
            "verified_facts": [{"key": "annual_limit", "value": 999999999}],
            "context": {"model_result": {"invented": True}},
        },
    )

    assert response.status_code == 422


def test_adviser_health_request_routes_only_to_health_navigator_without_hal_fallback():
    response = client.post(
        "/api/v1/adviser/handle",
        json={"message": "I have severe stomach pain."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["intent"] == "health"
    assert body["decision"]["specialists"] == ["health_navigator"]
    assert body["responses"][0]["specialist"] == "health_navigator"
    assert body["responses"][0]["status"] in {"handoff", "unavailable"}


def test_legacy_chat_endpoint_now_enters_ashlar_orchestrator_handle():
    source = inspect.getsource(chat_api.turn)

    assert "get_ashlar_orchestrator().handle(" in source
    assert "handle_legacy_chat" not in source



def test_legacy_chat_compound_workflow_exposes_final_specialist_and_downloads():
    req = ChatRequest(
        message="Compare these PDFs and prepare the proposal.",
        state={
            "_adviser_os_case_id": "11111111-1111-1111-1111-111111111111",
            "_adviser_os_case_token": "token",
            "_adviser_os_document_refs": ["doc-ref-1"],
        },
    )
    result = OrchestratorResult(
        decision=OrchestrationDecision(
            intent=OrchestrationIntent.PROPOSAL,
            specialists=[SpecialistName.DOCUMENT_ANALYST, SpecialistName.PROPOSAL_WRITER],
            deterministic_engines=["document_evidence_engine"],
            reason="Document evidence first, proposal second.",
        ),
        responses=[
            SpecialistResponse(
                specialist=SpecialistName.DOCUMENT_ANALYST,
                status="completed",
                reply="Documents analysed.",
            ),
            SpecialistResponse(
                specialist=SpecialistName.PROPOSAL_WRITER,
                status="completed",
                reply="Proposal ready.",
                payload={
                    "proposal_id": "proposal-1",
                    "expires_at": "2026-09-18T12:00:00+00:00",
                    "downloads": {
                        "pdf": "/api/v1/proposals/proposal-1/pdf",
                        "pptx": "/api/v1/proposals/proposal-1/pptx",
                    },
                },
            ),
        ],
    )

    payload = _legacy_chat_payload(req=req, result=result)

    assert payload["reply"] == "Proposal ready."
    assert payload["proposal_downloads"]["pdf"].endswith("/pdf")
    assert payload["state"]["_adviser_os_document_refs"] == ["doc-ref-1"]


def test_chat_state_document_refs_are_sanitised_and_bounded():
    refs = chat_api._document_refs_from_state({
        "_adviser_os_document_refs": ["abc", "abc", "", "def"],
    })

    assert refs == ["abc", "def"]
