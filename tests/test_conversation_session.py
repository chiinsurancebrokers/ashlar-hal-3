import pytest

from backend.app.services import conversation_session as sessions


def test_session_is_not_retained_without_explicit_consent(monkeypatch):
    def fail_rpc(*args, **kwargs):
        raise AssertionError("durable store must not be called without retention consent")
    monkeypatch.setattr(sessions, "_rpc", fail_rpc)
    session = sessions.create_session(consent_to_retain=False)
    assert session.consent_to_retain is False


def test_supabase_adapter_persists_resumes_and_deletes(monkeypatch):
    store = {}; messages = {}
    def fake_rpc(name, payload):
        if name == "hal_create_session":
            ref = payload["p_session_reference"]
            row = {"session_reference": ref, "consent_to_retain": True, "consent_to_transmit": payload["p_consent_to_transmit"], "created_at": "2026-10-03T16:00:00Z", "updated_at": "2026-10-03T16:00:00Z", "state_json": {}}
            store[ref] = row; messages[ref] = []; return row
        if name == "hal_save_turn":
            ref = payload["p_session_reference"]
            if ref not in store: raise KeyError("Session not found.")
            store[ref]["state_json"] = payload["p_state"]
            messages[ref].extend([{"role": "user", "content": payload["p_user_message"], "created_at": "2026-10-03T16:01:00Z"}, {"role": "assistant", "content": payload["p_assistant_message"], "created_at": "2026-10-03T16:01:01Z"}])
            return store[ref]
        if name == "hal_get_session":
            ref = payload["p_session_reference"]
            if ref not in store: return []
            return [{**store[ref], "transcript": messages[ref]}]
        if name == "hal_delete_session":
            ref = payload["p_session_reference"]; existed = ref in store; store.pop(ref, None); messages.pop(ref, None); return existed
        raise AssertionError(name)
    monkeypatch.setattr(sessions, "_rpc", fake_rpc)
    created = sessions.create_session(consent_to_retain=True, consent_to_transmit=False)
    state = {"applicant_name": "Test Applicant", "age": 42, "family_requested": True, "family_household_size": 4, "family_members": [{"member_id": "spouse", "relationship": "spouse", "age": 39, "sex": "female"}, {"member_id": "child-1", "relationship": "child", "age": 8, "sex": "unspecified"}, {"member_id": "child-2", "relationship": "child", "age": 5, "sex": "unspecified"}], "medical_notes": "must never be copied into the structured summary"}
    saved = sessions.save_turn(created.session_id, state=state, user_message="Family", assistant_message="Collected")
    assert saved.state["family_household_size"] == 4; assert len(saved.transcript) == 2
    summary = sessions.fact_find_summary(saved)
    assert summary["facts"]["family_household_size"] == 4
    assert len(summary["facts"]["household_members"]) == 3
    assert "medical_notes" not in summary["facts"]
    assert sessions.delete_session(created.session_id) is True
    with pytest.raises(KeyError): sessions.get_session(created.session_id)


def test_fact_find_keeps_member_maternity_but_drops_medical_free_text():
    session = sessions.ConversationSession(
        session_id="HALS-TEST",
        consent_to_retain=True,
        consent_to_transmit=True,
        created_at="2026-10-03T16:00:00Z",
        updated_at="2026-10-03T16:00:00Z",
        state={
            "family_requested": True,
            "household_members": [
                {"member_id": "primary", "relationship": "primary", "age": 40, "sex": "male", "requirements": {"maternity": False}},
                {"member_id": "spouse", "relationship": "spouse", "age": 35, "sex": "female", "requirements": {"maternity": True, "medical_notes": "private diagnosis"}, "medical_notes": "private diagnosis"},
                {"member_id": "child-1", "relationship": "child", "age": 8, "sex": "unspecified"},
                {"member_id": "child-2", "relationship": "child", "age": 5, "sex": "unspecified"},
            ],
            "medical_notes": "private family medical narrative",
            "transcript_dump": "must not leave session",
        },
    )
    facts = sessions.fact_find_summary(session)["facts"]
    assert facts["household_members"][1]["requirements"]["maternity"] is True
    assert "medical_notes" not in facts
    assert "medical_notes" not in facts["household_members"][1]
    assert "medical_notes" not in facts["household_members"][1]["requirements"]
    assert "transcript_dump" not in facts


def test_create_session_accepts_postgrest_one_row_list(monkeypatch):
    def fake_rpc(name, payload):
        assert name == "hal_create_session"
        return [{"session_reference": payload["p_session_reference"], "consent_to_retain": True, "consent_to_transmit": False, "created_at": "2026-10-03T16:00:00Z", "updated_at": "2026-10-03T16:00:00Z", "state_json": {}}]
    monkeypatch.setattr(sessions, "_rpc", fake_rpc)
    assert sessions.create_session(consent_to_retain=True).session_id.startswith("HALS-")
