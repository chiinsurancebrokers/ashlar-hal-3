import pytest
from backend.app.services import fact_find_handoff as handoff
from backend.app.services.conversation_session import ConversationSession
from datetime import datetime, timezone


def _session(consent=True):
    now = datetime.now(timezone.utc)
    return ConversationSession(
        session_id="HALS-TEST123",
        consent_to_retain=True,
        consent_to_transmit=consent,
        created_at=now,
        updated_at=now,
        state={"age": 40},
    )


@pytest.mark.asyncio
async def test_handoff_keeps_reference_and_drops_medical_free_text(monkeypatch):
    monkeypatch.setattr(handoff, "get_session", lambda ref: _session(True))
    captured = {}

    async def fake_lead(payload, *, reference=None):
        captured["lead_reference"] = reference
        captured["facts"] = payload["fact_find"]
        return {"status": "sent", "reference": reference, "transport": "resend"}

    async def fake_proposal(reference, facts, contact):
        captured["proposal_reference"] = reference
        return {"status": "contract_unavailable", "session_reference": reference}

    monkeypatch.setattr(handoff, "send_lead", fake_lead)
    monkeypatch.setattr(handoff, "prefill_proposal_studio", fake_proposal)
    result = await handoff.submit_handoff(
        "HALS-TEST123",
        {
            "age": 40,
            "family_requested": True,
            "medical_notes": "sensitive free text",
            "household_members": [
                {"member_id": "spouse", "relationship": "spouse", "age": 35, "sex": "female", "requirements": {"maternity": True}, "medical_notes": "exclude"}
            ],
        },
        {"first_name": "Test", "last_name": "Client", "email": "client@example.com"},
    )
    assert result["session_reference"] == "HALS-TEST123"
    assert captured["lead_reference"] == "HALS-TEST123"
    assert captured["proposal_reference"] == "HALS-TEST123"
    assert "medical_notes" not in captured["facts"]
    assert captured["facts"]["household_members"][0]["requirements"]["maternity"] is True


@pytest.mark.asyncio
async def test_handoff_requires_transmission_consent(monkeypatch):
    monkeypatch.setattr(handoff, "get_session", lambda ref: _session(False))
    with pytest.raises(PermissionError):
        await handoff.submit_handoff("HALS-TEST123", {"age": 40}, {"email": "client@example.com"})
