import json

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.corporate_group_agent import (
    MHD_MIN_EMPLOYEES,
    apply_corporate_answer,
    corporate_chat_turn,
    group_fact_find_summary,
    is_corporate_intent,
    mhd_option_unlocked,
    next_corporate_question,
)


def test_group_intent_routes_without_touching_individual_pricing():
    assert is_corporate_intent("I need group health insurance for my company")
    result = corporate_chat_turn("I need group health insurance for my company", {})
    assert result["journey"] == "corporate_group"
    assert result["quotes"] == []
    assert result["ai_status"] == "corporate_group_guided_discovery"


def test_mhd_unlocks_at_exactly_five_employees_not_four():
    assert MHD_MIN_EMPLOYEES == 5
    assert mhd_option_unlocked(4) is False
    assert mhd_option_unlocked(5) is True
    assert mhd_option_unlocked(20) is True


def test_employee_count_sets_server_side_mhd_capability():
    state = {"journey": "corporate_group", "corporate_pending_question": "employee_count"}
    assert apply_corporate_answer("4", state)["mhd_option_unlocked"] is False
    assert apply_corporate_answer("5", state)["mhd_option_unlocked"] is True


def test_mhd_question_only_appears_for_five_plus_and_preexisting_interest():
    base = {
        "organisation_type": "Company / SME", "company_country": "Greece", "employee_countries": "Greece",
        "coverage_area_label": "Europe", "group_benefits": ["inpatient"], "pre_existing_requested": True,
    }
    q4 = next_corporate_question({**base, "employee_count": 4})
    assert q4["key"] == "existing_scheme"
    q5 = next_corporate_question({**base, "employee_count": 5})
    assert q5["key"] == "mhd"
    assert "subject to insurer" in q5["reply"].lower()


def test_group_fact_find_never_claims_mhd_is_guaranteed():
    summary = group_fact_find_summary({"employee_count": 8, "mhd_requested": True, "group_benefits": ["inpatient"]})
    assert "subject to insurer approval" in summary
    assert "guaranteed" not in summary.lower()


def test_chat_api_corporate_path_returns_no_quotes():
    client = TestClient(app)
    response = client.post("/api/v1/chat/turn", json={"message": "We need group health insurance for our employees", "state": {}, "history": []})
    assert response.status_code == 200
    body = response.json()
    assert body["journey"] == "corporate_group"
    assert body["quotes"] == []
    assert body["quick_replies"]


def test_census_csv_with_medical_column_is_rejected_before_delivery():
    client = TestClient(app)
    state = {"employee_count": 8, "group_benefits": ["inpatient"], "mhd_requested": True}
    response = client.post(
        "/api/v1/corporate/enquiry",
        data={
            "contact_name": "Test Broker", "email": "test@example.com", "company_name": "Test Co",
            "fact_find_json": json.dumps(state), "consent": "true", "no_medical_data_confirmed": "true",
        },
        files={"census": ("census.csv", b"employee_id,age,diagnosis\n1,40,example\n", "text/csv")},
    )
    assert response.status_code == 400
    assert "medical/clinical" in response.json()["detail"].lower()


def test_census_requires_no_medical_data_confirmation():
    client = TestClient(app)
    response = client.post(
        "/api/v1/corporate/enquiry",
        data={
            "contact_name": "Test Broker", "email": "test@example.com", "company_name": "Test Co",
            "fact_find_json": json.dumps({"employee_count": 5}), "consent": "true", "no_medical_data_confirmed": "false",
        },
        files={"census": ("census.csv", b"employee_id,age\n1,40\n", "text/csv")},
    )
    assert response.status_code == 400
    assert "no medical or clinical" in response.json()["detail"].lower()
