from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.cases.models import AshlarCase
from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.main import app


client = TestClient(app)


def _active_case():
    case = AshlarCase(selected_plan_keys=["generic:test_silver"])
    return CASE_ANALYSIS_STORE.put(case=case, results=[])


def test_server_owned_document_upload_then_orchestrator_analysis():
    record = _active_case()
    secret_phrase = "PRIVATE-CARRIER-EVIDENCE-MARKER"
    response = client.post(
        "/api/v1/documents/upload",
        data={
            "case_id": str(record.case.case_id),
            "case_token": record.access_token,
            "provider_label": "Generic Carrier",
            "target_plan": "Test Silver",
            "plan_key": "generic:test_silver",
            "role": "quotation",
        },
        files={
            "file": (
                "test-silver-quote.txt",
                f"Test Silver applicant quotation. Annual premium EUR 1,200. Deductible EUR 500. Area of cover Europe. Annual limit EUR 1,000,000. {secret_phrase}".encode(),
                "text/plain",
            )
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers.get("cache-control") == "no-store"
    uploaded = response.json()
    assert uploaded["document_ref"]
    assert "extracted_text" not in uploaded
    assert "focused_table_context" not in uploaded
    assert secret_phrase not in response.text

    analysis = client.post(
        "/api/v1/adviser/handle",
        json={
            "case_id": str(record.case.case_id),
            "case_token": record.access_token,
            "message": "Compare these PDFs.",
            "document_refs": [uploaded["document_ref"]],
        },
    )

    assert analysis.status_code == 200, analysis.text
    body = analysis.json()
    assert body["decision"]["intent"] == "document"
    specialist = body["responses"][0]
    assert specialist["specialist"] == "document_analyst"
    assert specialist["status"] == "completed"
    assert "envelope" not in specialist["payload"]["analyses"][0]
    assert "analysis_prompt" not in analysis.text
    assert secret_phrase not in analysis.text
    synthesis = specialist["payload"]["model_synthesis"]
    assert synthesis["advisory_only"] is True
    assert synthesis["authoritative_facts_source"] == "fact_ledger"

    intelligence = body["payload"]["case_intelligence"]
    assert intelligence["document_count"] == 1
    assert intelligence["fact_count"] >= 2
    assert intelligence["plan_count_with_evidence"] >= 1


def test_document_upload_is_bound_to_active_case_token():
    record = _active_case()
    response = client.post(
        "/api/v1/documents/upload",
        data={
            "case_id": str(record.case.case_id),
            "case_token": "wrong-token",
            "provider_label": "Generic Carrier",
            "target_plan": "Test Silver",
            "role": "quotation",
        },
        files={"file": ("quote.txt", b"A valid quotation document with enough readable text.", "text/plain")},
    )
    assert response.status_code == 404


def test_adviser_api_never_accepts_raw_document_evidence_from_browser():
    record = _active_case()
    response = client.post(
        "/api/v1/adviser/handle",
        json={
            "case_id": str(record.case.case_id),
            "case_token": record.access_token,
            "message": "Compare these PDFs.",
            "quotation_text": "Browser says this is verified carrier evidence.",
        },
    )
    assert response.status_code == 422
