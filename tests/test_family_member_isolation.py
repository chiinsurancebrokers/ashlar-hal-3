"""Regression for staging 2026-10-04: Chris 51/M + spouse 51/F + daughter 25/F
with maternity. The AI intake turned the daughter's maternity "yes" into the
primary applicant's maternity, so Chris was placed on Premium with maternity.
A 25-year-old was also accepted as a child dependant."""
import asyncio

import pytest

from backend.app.core.config import get_settings
from backend.app.discovery.family_flow import apply_family_answer, next_family_question
from backend.app.services import family_live_orchestrator as live
from backend.app.services import orchestrator


@pytest.fixture
def hostile_ai_intake(monkeypatch):
    """Simulate an AI intake that wrongly copies family answers to the primary."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    base = get_settings()
    with_key = base.model_copy(update={"anthropic_api_key": "test-key"})
    monkeypatch.setattr(orchestrator, "get_settings", lambda: with_key)

    async def bad_intake(message, state, history, greek):
        updates = {}
        pending = state.get("pending_question")
        if pending == "family_maternity" and message.lower() == "yes":
            updates["maternity_required"] = True
        if pending == "family_age":
            updates["age"] = int(message)
        if pending == "family_sex":
            updates["sex"] = message
        return {"acknowledgement": "Noted.", "applicant_updates": updates}

    real_elig, real_verify = orchestrator.assess_eligibility, orchestrator.verify_shortlist

    async def elig(applicant, greek=False, settings=None):
        return await real_elig(applicant, greek=greek, settings=base)

    async def verify(*args, **kwargs):
        kwargs["settings"] = base
        return await real_verify(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "intake_analysis", bad_intake)
    monkeypatch.setattr(orchestrator, "assess_eligibility", elig)
    monkeypatch.setattr(orchestrator, "verify_shortlist", verify)
    yield
    get_settings.cache_clear()


def _run(messages):
    async def go():
        state, result = {"pending_question": "name"}, None
        for m in messages:
            result = await live.chat_turn(m, state, [])
            state = result["state"]
        return result
    return asyncio.run(go())


BASE = ["chris", "51", "male", "greece", "Same as residence", "greek", "Europe only", "yes",
        "spouse", "51", "female", "yes"]
TAIL = ["€0 deductible", "Include outpatient cover", "No", "No dental needed",
        "No mental health cover needed", "Yes, wellness is important", "No optical cover needed",
        "Yes, evacuation is important", "No fixed budget"]


def test_family_answers_never_change_the_primary_applicant(hostile_ai_intake):
    result = _run(BASE + ["child", "24", "female", "yes", "no"] + TAIL)
    state = result["state"]
    assert state["age"] == 51 and state["sex"] == "male"
    assert not state.get("maternity_required")
    assert result["ai_status"] == "verified_household_shortlist"
    breakdown = {b["member_id"]: b for b in result["household_breakdown"]}
    assert breakdown["primary"]["maternity"] is False
    assert breakdown["member-2"]["maternity"] is True
    assert "Chris (51): Morgan Price Premium (includes maternity)" not in result["reply"]
    # Primary goes to the cheapest plan meeting HIS needs, not the maternity tier.
    assert breakdown["primary"]["product_name"] != "Morgan Price Premium"


def test_child_aged_25_is_not_accepted_as_dependant(hostile_ai_intake):
    result = _run(BASE + ["child", "25"])
    state = result["state"]
    assert [m["relationship"] for m in state["household_members"]] == ["spouse"]
    assert state["pending_question"] == "family_add_another"
    assert "25 or over" in result["reply"]
    assert not result["reply"].startswith("Noted.")  # no contradictory AI ack
    assert state["age"] == 51


@pytest.mark.parametrize("age,accepted", [(24, True), (25, False), (30, False)])
def test_child_age_limit(age, accepted):
    state = {"pending_question": "family_age", "household_member_index": 0,
             "household_members": [{"member_id": "member-1", "relationship": "child"}]}
    out = apply_family_answer(str(age), state)
    state.update(out)
    assert (len(state["household_members"]) == 1) is accepted
    if not accepted:
        q = next_family_question({**state, "family_answered": True, "family_requested": True})
        assert q["key"] == "family_add_another"


def test_spouse_age_is_not_limited():
    state = {"pending_question": "family_age", "household_member_index": 0,
             "household_members": [{"member_id": "member-1", "relationship": "spouse"}]}
    out = apply_family_answer("51", state)
    assert out["household_members"][0]["age"] == 51
