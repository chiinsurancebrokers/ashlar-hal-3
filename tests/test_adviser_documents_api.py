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



def test_document_upload_rejects_plan_not_selected_in_active_case():
    record = _active_case()
    response = client.post(
        "/api/v1/documents/upload",
        data={
            "case_id": str(record.case.case_id),
            "case_token": record.access_token,
            "provider_label": "Other Carrier",
            "target_plan": "Other Plan",
            "plan_key": "other:plan",
            "role": "quotation",
        },
        files={"file": ("quote.txt", b"Annual premium EUR 1,200.", "text/plain")},
    )

    assert response.status_code == 422
    assert "not selected" in response.json()["detail"].lower()


def test_document_analysis_updates_proposal_results_but_preserves_server_premium():
    case = AshlarCase(selected_plan_keys=["generic:test_silver"])
    record = CASE_ANALYSIS_STORE.put(
        case=case,
        results=[{
            "plan_key": "generic:test_silver",
            "provider": "Generic Carrier",
            "target_plan": "Test Silver",
            "focused_rows": [],
            "analysis": {
                "provider": "Generic Carrier",
                "plan_name": "Test Silver",
                "premium": {"amount": 999, "currency": "EUR", "frequency": "Annual"},
                "deductible_or_excess": "Not specified",
                "annual_limit": "Not specified",
                "area_of_cover": "Not specified",
                "underwriting": {
                    "basis": "Subject to carrier underwriting",
                    "pre_existing_conditions": "Subject to carrier underwriting and governing terms",
                },
                "benefits": {},
                "waiting_periods": [],
                "optional_benefits": [],
                "critical_limitations": [],
                "source_evidence": [],
                "confidence": "high",
            },
            "library_source": False,
        }],
    )

    upload = client.post(
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
                "quote.txt",
                b"Test Silver. Annual premium EUR 1,200. Deductible EUR 500. Area of cover Europe. Annual limit EUR 1,000,000.",
                "text/plain",
            )
        },
    )
    assert upload.status_code == 200, upload.text

    analysis = client.post(
        "/api/v1/adviser/handle",
        json={
            "case_id": str(record.case.case_id),
            "case_token": record.access_token,
            "message": "Compare this quotation.",
            "document_refs": [upload.json()["document_ref"]],
        },
    )
    assert analysis.status_code == 200, analysis.text

    saved = CASE_ANALYSIS_STORE.get(record.case.case_id, record.access_token)
    assert saved is not None
    assert len(saved.results) == 1
    enriched = saved.results[0]
    assert enriched["plan_key"] == "generic:test_silver"
    assert enriched["document_evidence_present"] is True
    assert enriched["analysis"]["premium"]["amount"] == 999
    assert "analysis_prompt" not in str(enriched)
