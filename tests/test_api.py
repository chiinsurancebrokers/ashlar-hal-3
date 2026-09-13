from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_homepage_never_cached_by_browser():
    r = client.get("/")
    assert r.status_code == 200
    assert "no-store" in r.headers.get("cache-control", "")


def test_health_endpoint():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["family_pricing"] == "active"


def test_quotes_preview_real_data():
    r = client.post("/api/v1/quotes/preview", json={"age": 40, "residence_country": "Greece", "coverage_area": "area1"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["shortlist"]) > 0
    assert any(q["insurer"].startswith("Morgan Price") for q in body["shortlist"])


def test_quotes_preview_maternity_hard_exclusion_over_http():
    r = client.post("/api/v1/quotes/preview", json={
        "age": 51, "residence_country": "Greece", "coverage_area": "area2", "maternity_required": True,
    })
    assert r.status_code == 200
    body = r.json()
    codes = {q["product_code"] for q in body["shortlist"] if q["insurer"].startswith("Morgan Price")}
    assert "standard" not in codes
    assert "premium" in codes or "elite" in codes
    excluded_codes = {e["plan_key"].split(":")[1] for e in body["exclusions"] if "morgan_price" in e["plan_key"]}
    assert "standard" in excluded_codes


def test_chat_turn_first_message_asks_age():
    r = client.post("/api/v1/chat/turn", json={"message": "Hi, I need international health insurance", "state": {}, "history": []})
    assert r.status_code == 200
    body = r.json()
    assert body["ai_status"] == "guided_discovery"
    assert body["state"]["pending_question"] == "name"


def test_lead_requires_consent():
    r = client.post("/api/v1/leads", json={
        "insurance_interest": "IPMI", "first_name": "Chris", "last_name": "T",
        "email": "chris@example.com", "consent": False,
    })
    assert r.status_code == 400


def test_lead_honeypot_silently_accepted():
    r = client.post("/api/v1/leads", json={
        "insurance_interest": "IPMI", "first_name": "Bot", "last_name": "T",
        "email": "bot@example.com", "consent": True, "website": "http://spam.example",
    })
    assert r.status_code == 200
    assert r.json()["reference"] == "HAL-SPAM-FILTERED"


def test_lead_invalid_email_rejected_by_schema():
    r = client.post("/api/v1/leads", json={
        "insurance_interest": "IPMI", "first_name": "Chris", "last_name": "T",
        "email": "not-an-email", "consent": True,
    })
    assert r.status_code == 422


def test_comparison_rejects_forged_plan_key():
    r = client.post("/api/v1/leads/comparison", json={
        "name": "Chris", "email": "chris@example.com",
        "applicant_state": {"age": 40, "residence_country": "Greece", "coverage_area": "area1"},
        "plan_keys": ["fantasy_carrier:free_plan"],
    })
    assert r.status_code == 400


def test_quotes_compare_returns_detailed_matrix_and_conclusion():
    r = client.post("/api/v1/quotes/compare", json={
        "applicant_state": {"age": 40, "residence_country": "Greece", "coverage_area": "area1"},
        "plan_keys": ["morgan_price:standard", "morgan_price:premium"],
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["plans"]) == 2
    assert len(body["matrix"]["rows"]) > 10
    assert body["conclusion"]
    assert body["unsupported_note"] is None


def test_quotes_compare_rejects_single_plan():
    r = client.post("/api/v1/quotes/compare", json={
        "applicant_state": {"age": 40, "residence_country": "Greece", "coverage_area": "area1"},
        "plan_keys": ["morgan_price:standard"],
    })
    assert r.status_code == 422  # min_length=2 on plan_keys


def test_speak_returns_503_when_elevenlabs_not_configured():
    r = client.post("/api/v1/speak", json={"text": "Hello", "language": "en"})
    assert r.status_code == 503
    assert "ELEVENLABS_API_KEY" in r.json()["detail"]


def test_transcribe_returns_400_for_empty_audio():
    r = client.post("/api/v1/transcribe", files={"file": ("audio.webm", b"", "audio/webm")})
    assert r.status_code == 400


def test_rate_limit_kicks_in_after_threshold():
    for _ in range(20):
        client.post("/api/v1/chat/turn", json={"message": "hello", "state": {}, "history": []})
    r = client.post("/api/v1/chat/turn", json={"message": "hello", "state": {}, "history": []})
    assert r.status_code == 429
