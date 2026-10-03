import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.conversation_session import create_session, get_session


client = TestClient(app)


def test_session_is_not_retained_without_explicit_consent():
    session = create_session(consent_to_retain=False)
    with pytest.raises(KeyError):
        get_session(session.session_id)


def test_session_resume_summary_and_delete_are_consent_gated():
    created = client.post("/api/v1/sessions", json={"consent_to_retain": True, "consent_to_transmit": False})
    assert created.status_code == 200
    ref = created.json()["session_reference"]
    assert created.json()["retained"] is True
    assert created.json()["transmission_allowed"] is False

    state = {
        "applicant_name": "Test Applicant",
        "age": 42,
        "family_requested": True,
        "family_household_size": 4,
        "family_members": [
            {"member_id": "spouse", "relationship": "spouse", "age": 39, "sex": "female"},
            {"member_id": "child-1", "relationship": "child", "age": 8, "sex": "unspecified"},
            {"member_id": "child-2", "relationship": "child", "age": 5, "sex": "unspecified"},
        ],
        "medical_notes": "must never be copied into the structured summary",
    }
    saved = client.post(f"/api/v1/sessions/{ref}/turn", json={
        "state": state,
        "user_message": "Please include my family.",
        "assistant_message": "I will collect each family member separately.",
    })
    assert saved.status_code == 200

    resumed = client.get(f"/api/v1/sessions/{ref}")
    assert resumed.status_code == 200
    assert resumed.json()["state"]["family_household_size"] == 4
    assert len(resumed.json()["transcript"]) == 2

    summary = client.get(f"/api/v1/sessions/{ref}/summary")
    assert summary.status_code == 200
    facts = summary.json()["facts"]
    assert facts["family_household_size"] == 4
    assert len(facts["family_members"]) == 3
    assert "medical_notes" not in facts
    assert summary.json()["review_required"] is True

    deleted = client.delete(f"/api/v1/sessions/{ref}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/sessions/{ref}").status_code == 404
