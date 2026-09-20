from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.cases.models import AshlarCase, CaseStatus, FactSourceType, FactStatus
from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.main import app
from backend.app.schemas.applicant import Applicant


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



def test_compare_reuses_discovery_case_and_seeds_verified_quote_facts():
    applicant, plan_keys = _comparison_payload()
    market = CASE_ANALYSIS_STORE.put(
        case=AshlarCase(status=CaseStatus.MARKET_REVIEW),
        results=[],
    )

    response = client.post(
        "/api/v1/quotes/compare",
        json={
            "applicant_state": applicant,
            "plan_keys": plan_keys,
            "language": "en",
            "case_id": str(market.case.case_id),
            "case_token": market.access_token,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["case_id"] == str(market.case.case_id)
    assert data["case_token"] == market.access_token
    assert data["case_intelligence"]["journey"]["current_phase"] == "compare"
    assert data["case_intelligence"]["ready_for_proposal"] is False

    record = CASE_ANALYSIS_STORE.get(market.case.case_id, market.access_token)
    assert record is not None
    quote_facts = [
        fact for fact in record.case.facts
        if fact.source.source_type == FactSourceType.QUOTE_ENGINE
    ]
    assert quote_facts
    assert all(fact.status == FactStatus.VERIFIED for fact in quote_facts)
    assert {fact.plan_key for fact in quote_facts if fact.plan_key} == set(plan_keys)


def test_case_workspace_surfaces_journey_evidence_and_next_best_action():
    response = client.get("/static/adviser-os.js")

    assert response.status_code == 200
    source = response.text
    assert "adviserCaseWorkspace" in source
    assert "Evidence by plan" in source
    assert "HAL · next best action" in source
    assert "Discover" in source
    assert "Renew" in source



def test_adviser_os_frontend_exposes_final_plan_choice_and_application_workspace():
    response = client.get("/static/adviser-os.js")

    assert response.status_code == 200
    source = response.text
    assert "choose-final-plan-btn" in source
    assert "/select-plan" in source
    assert "prepareApplication" in source
    assert "/application/prepare" in source
    assert "Application workspace" in source


def test_application_workspace_renders_carrier_blueprint_and_safety_boundaries():
    response = client.get("/static/adviser-os.js")

    assert response.status_code == 200
    source = response.text
    assert "applicationBlueprint" in source
    assert "source_status" in source
    assert "adviser-application-warning" in source
    assert "Work on this" in source
    assert "do not infer declarations, medical answers or signatures" in source


def test_affirmative_after_discovery_continues_into_adviser_os_shortlist_workflow():
    applicant_payload, _ = _comparison_payload()
    applicant_payload["chronic_conditions_note"] = None
    market = CASE_ANALYSIS_STORE.put(
        case=AshlarCase(
            status=CaseStatus.MARKET_REVIEW,
            applicant=Applicant(**applicant_payload),
            needs_profile={"priorities": ["outpatient_required"]},
        ),
        results=[],
    )

    response = client.post(
        "/api/v1/chat/turn",
        json={
            "message": "Yes",
            "state": {
                **applicant_payload,
                "discovery_complete": True,
                "_adviser_os_case_id": str(market.case.case_id),
                "_adviser_os_case_token": market.access_token,
            },
            "history": [],
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert "choose 2–4 plans" in data["reply"].lower()
    assert len(data["quotes"]) >= 2
    assert data["_adviser_os"]["case_id"] == str(market.case.case_id)


def test_adviser_os_ui_exposes_evidence_pipeline_and_carrier_upload_from_compare():
    response = client.get("/static/adviser-os.js")

    assert response.status_code == 200
    source = response.text
    assert "Find plans" in source
    assert "Compare" in source
    assert "Ashlar Assessment" in source
    assert "Proposal" in source
    assert "attachEvidenceFromCompareBtn" in source
    assert "Broker evidence review" in source
    assert "brokerWorkspace ? '' : 'none'" in source
    assert "Shortlist comparison ready. Ashlar will verify any insurer-specific quotation" in source


def test_client_can_upload_existing_policy_as_separate_case_baseline():
    applicant, plan_keys = _comparison_payload()
    comparison = client.post(
        "/api/v1/quotes/compare",
        json={"applicant_state": applicant, "plan_keys": plan_keys, "language": "en"},
    )
    assert comparison.status_code == 200
    case = comparison.json()

    response = client.post(
        "/api/v1/documents/upload",
        data={
            "case_id": case["case_id"],
            "case_token": case["case_token"],
            "provider_label": "Bupa Global",
            "target_plan": "Lifeline Classic",
            "role": "existing_policy",
        },
        files={
            "file": (
                "current-policy.txt",
                b"Bupa Global Lifeline Classic. Annual limit EUR 2,000,000. Worldwide excluding USA.",
                "text/plain",
            )
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["role"] == "existing_policy"
    assert data["plan_key"] == "existing_policy"
    assert data["comparison_role"] == "current_policy"

    record = CASE_ANALYSIS_STORE.get(UUID(case["case_id"]), case["case_token"])
    assert record is not None
    current_docs = [doc for doc in record.case.documents if doc.plan_key == "existing_policy"]
    assert len(current_docs) == 1
    assert current_docs[0].metadata["role"] == "existing_policy"


def test_client_ui_exposes_current_policy_upload_and_provider_diverse_quotes():
    adviser = client.get("/static/adviser-os.js")
    home = client.get("/")

    assert adviser.status_code == 200
    assert "Upload your current policy" in adviser.text
    assert "existing_policy" in adviser.text
    assert "use it as the baseline when comparing my shortlisted alternatives" in adviser.text
    assert "brokerWorkspace ? '' : 'none'" in adviser.text

    assert home.status_code == 200
    assert "<th>Feature</th>" in home.text
    assert "Χαρακτηριστικό" not in home.text
    assert "function diversifyQuotes" in home.text


def test_existing_policy_baseline_survives_shortlist_refresh():
    applicant, plan_keys = _comparison_payload()
    first = client.post(
        "/api/v1/quotes/compare",
        json={"applicant_state": applicant, "plan_keys": plan_keys, "language": "en"},
    )
    assert first.status_code == 200
    case = first.json()

    uploaded = client.post(
        "/api/v1/documents/upload",
        data={
            "case_id": case["case_id"],
            "case_token": case["case_token"],
            "provider_label": "Bupa Global",
            "target_plan": "Lifeline Classic",
            "role": "existing_policy",
        },
        files={"file": ("current.txt", b"Bupa Global Lifeline Classic current policy.", "text/plain")},
    )
    assert uploaded.status_code == 200

    refreshed = client.post(
        "/api/v1/quotes/compare",
        json={
            "applicant_state": applicant,
            "plan_keys": plan_keys,
            "language": "en",
            "case_id": case["case_id"],
            "case_token": case["case_token"],
        },
    )
    assert refreshed.status_code == 200

    record = CASE_ANALYSIS_STORE.get(UUID(case["case_id"]), case["case_token"])
    assert record is not None
    assert any(doc.plan_key == "existing_policy" for doc in record.case.documents)
