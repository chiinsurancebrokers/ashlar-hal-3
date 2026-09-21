from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.proposals import router
from backend.app.cases.models import AshlarCase, CaseClient
from backend.app.core import config as config_module
from backend.app.schemas.applicant import Applicant

app = FastAPI()
app.include_router(router, prefix="/api/v1")
client = TestClient(app)


def result(provider="Carrier A", plan="Alpha"):
    return {
        "provider": provider,
        "target_plan": plan,
        "analysis": {
            "provider": provider,
            "plan_name": plan,
            "premium": {"amount": 5000, "currency": "EUR", "frequency": "annual"},
            "annual_limit": "EUR 1,000,000",
            "deductible_or_excess": "EUR 500",
            "area_of_cover": "Worldwide excluding USA",
            "underwriting": {"basis": "FMU", "pre_existing_conditions": "Subject to underwriting"},
            "benefits": {
                "inpatient": "Covered in full",
                "outpatient": "EUR 10,000",
                "cancer": "Covered in full",
                "chronic_conditions": "Covered subject to terms",
                "mental_health": "EUR 2,000",
                "evacuation_repatriation": "Covered",
            },
            "waiting_periods": [],
            "optional_benefits": [],
            "critical_limitations": [],
            "confidence": "high",
        },
    }


def request_payload():
    case = AshlarCase(
        client=CaseClient(display_name="Jane Example", preferred_language="en"),
        applicant=Applicant(age=45, residence_country="Greece", outpatient_required=True),
    )
    return {"case": case.model_dump(mode="json"), "results": [result()]}


def _enable_broker(monkeypatch):
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("ADMIN_PASSWORD", "test-secret")
    config_module.get_settings.cache_clear()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return {"X-Admin-Password": "test-secret"}


def test_generate_fails_closed_when_broker_auth_not_configured(monkeypatch):
    config_module.get_settings.cache_clear()
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    config_module.get_settings.cache_clear()
    response = client.post("/api/v1/proposals/generate", json=request_payload())
    assert response.status_code == 503


def test_generate_rejects_wrong_broker_password(monkeypatch):
    _enable_broker(monkeypatch)
    response = client.post(
        "/api/v1/proposals/generate",
        json=request_payload(),
        headers={"X-Admin-Password": "wrong"},
    )
    assert response.status_code == 403


def test_generate_then_download_pdf_and_pptx(monkeypatch):
    headers = _enable_broker(monkeypatch)
    response = client.post("/api/v1/proposals/generate", json=request_payload(), headers=headers)
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    body = response.json()
    assert body["status"] == "ready"
    assert body["case_status"] == "proposal"
    token = body["proposal_id"]
    assert token not in body["case_id"]
    assert body["downloads"]["pdf"].endswith(f"/api/v1/proposals/{token}/pdf")

    pdf = client.get(f"/api/v1/proposals/{token}/pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert "no-store" in pdf.headers["cache-control"]
    assert "Jane-Example" in pdf.headers["content-disposition"]

    pptx = client.get(f"/api/v1/proposals/{token}/pptx")
    assert pptx.status_code == 200
    assert pptx.content.startswith(b"PK")
    assert "no-store" in pptx.headers["cache-control"]


def test_unknown_proposal_token_returns_404():
    assert client.get("/api/v1/proposals/not-a-real-token/pdf").status_code == 404


def test_quality_gate_blocks_unsafe_proposal(monkeypatch):
    headers = _enable_broker(monkeypatch)
    payload = request_payload()
    payload["results"][0]["analysis"]["premium"] = {"amount": None}
    payload["results"][0]["analysis"]["annual_limit"] = None
    response = client.post("/api/v1/proposals/generate", json=payload, headers=headers)
    assert response.status_code == 422
    assert "quality gate" in response.json()["detail"].lower()
