import pytest

from backend.app.services.orchestrator import chat_turn
from backend.app.services import orchestrator as orchestrator_module
from backend.app.core.config import get_settings


@pytest.mark.asyncio
async def test_claude_intake_is_skipped_right_after_the_name_answer(monkeypatch):
    # Regression: calling Claude's intake layer here produced a redundant
    # "Thanks, Chris. Nice to meet you, Chris." double name-mention. A name
    # reply needs no LLM understanding — deterministic parsing is enough.
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "fake-key-for-test")
    calls = {"n": 0}

    async def fake_intake_analysis(*args, **kwargs):
        calls["n"] += 1
        return {"applicant_updates": {}, "acknowledgement": "Thanks, Chris."}

    monkeypatch.setattr(orchestrator_module, "intake_analysis", fake_intake_analysis)

    r1 = await chat_turn("Chris", {"pending_question": "name"}, [])
    assert calls["n"] == 0, "intake_analysis must not be called for the turn right after the name question"
    assert r1["reply"] == "Nice to meet you, Chris. How old are you?"

    r2 = await chat_turn("Greece", r1["state"], [])
    assert calls["n"] == 1, "intake_analysis should run normally on later turns"


@pytest.mark.asyncio
async def test_shortlist_reply_always_explains_why_the_top_plan_was_chosen():
    state: dict = {
        "name_asked": True, "age": 51, "residence_country": "Greece", "coverage_area": "area2", "maternity_required": True,
        "discovery_complete": True, "pending_question": None, "deductible_answered": True,
        "outpatient_answered": True, "chronic_answered": True, "maternity_answered": True,
        "dental_answered": True, "mental_health_answered": True, "wellness_answered": True,
        "optical_answered": True, "evacuation_answered": True, "budget_answered": True,
    }
    r = await chat_turn("continue", state, [])
    assert r["ai_status"] == "deterministic_shortlist"
    assert "top pick" in r["reply"].lower()
    assert "excluded" in r["reply"].lower()  # maternity exclusions must be mentioned, not just hidden in a link


@pytest.mark.asyncio
async def test_shortlist_reply_invites_further_conversation_instead_of_ending_abruptly():
    # Regression: the conversation just stopped dead after the shortlist,
    # with no natural next step offered.
    state: dict = {
        "name_asked": True, "age": 51, "residence_country": "Greece", "coverage_area": "area1",
        "discovery_complete": True, "pending_question": None, "deductible_answered": True,
        "outpatient_answered": True, "chronic_answered": True, "maternity_answered": True,
        "dental_answered": True, "mental_health_answered": True, "wellness_answered": True,
        "optical_answered": True, "evacuation_answered": True, "budget_answered": True,
    }
    r = await chat_turn("continue", state, [])
    assert r["ai_status"] == "deterministic_shortlist"
    assert "?" in r["followup_message"], "must offer an inviting follow-up question as its own message, not end abruptly"
    assert "?" not in r["reply"].rstrip("."), "the follow-up question must be its own separate message, not merged into the shortlist paragraph"


@pytest.mark.asyncio
async def test_full_guided_flow_reaches_shortlist_without_claude_configured():
    state: dict = {}
    history: list = []

    async def turn(msg):
        nonlocal state
        r = await chat_turn(msg, state, history)
        state = r["state"]
        return r

    r = await turn("I'm looking for international health insurance")
    assert r["ai_status"] == "guided_discovery"
    assert r["state"]["pending_question"] == "name"

    r = await turn("Christos")
    r = await turn("51")
    r = await turn("Greece")
    r = await turn("Worldwide excluding USA")
    r = await turn("skip")   # deductible
    r = await turn("include outpatient")
    r = await turn("no")     # chronic
    r = await turn("Dental and yearly check-ups")  # one bundled extras question
    final = await turn("skip")  # budget

    assert final["ai_status"] == "deterministic_shortlist"
    assert isinstance(final["quotes"], list)
    assert final["state"]["discovery_complete"] is True


@pytest.mark.asyncio
async def test_journey_switch_from_ipmi_to_local_wipes_state():
    state: dict = {"journey": "ipmi", "age": 51, "coverage_area": "area3", "outpatient_required": True}
    r = await chat_turn("actually I want local insurance", state, [])
    assert r["journey"] == "local_review"
    assert "outpatient_required" not in r["state"] or r["state"].get("outpatient_required") is not True


@pytest.mark.asyncio
async def test_hnwi_signal_sets_client_segment():
    state: dict = {}
    r = await chat_turn("Budget is secondary, I want the best hospitals available", state, [])
    assert r["state"].get("client_segment") == "hnwi"


@pytest.mark.asyncio
async def test_travel_intent_starts_guided_travel_discovery():
    state: dict = {}
    r = await chat_turn("I need travel insurance for a single trip", state, [])
    assert r["journey"] == "travel"
    assert r["ai_status"] == "travel_guided_discovery"


@pytest.mark.asyncio
async def test_language_stays_greek_after_a_purely_numeric_answer():
    state: dict = {}
    history: list = []

    async def turn(msg):
        nonlocal state
        r = await chat_turn(msg, state, history)
        state = r["state"]
        return r

    r = await turn("Γεια, θέλω διεθνή ασφάλιση υγείας")
    assert state["language"] == "el"
    assert any(ch in r["reply"] for ch in "άέήίόύώ") or "χρον" in r["reply"].lower()

    r2 = await turn("51")  # no Greek characters at all — must NOT flip language back
    assert state["language"] == "el"
    assert any(ch in r2["reply"] for ch in "άέήίόύώ") or "χώρα" in r2["reply"].lower() or "μένετε" in r2["reply"].lower()


@pytest.mark.asyncio
async def test_language_switches_back_on_clear_latin_text():
    state: dict = {}
    r = await chat_turn("Γεια σου", state, [])
    state = r["state"]
    assert state["language"] == "el"
    r2 = await chat_turn("actually let's continue in English please", state, [])
    assert r2["state"]["language"] == "en"


@pytest.mark.asyncio
async def test_full_travel_flow_reaches_tier_recommendation():
    state: dict = {}
    history: list = []

    async def turn(msg):
        nonlocal state
        r = await chat_turn(msg, state, history)
        state = r["state"]
        return r

    await turn("I need travel insurance")
    await turn("single trip")
    await turn("Italy")
    await turn("45")
    final = await turn("balanced")

    assert final["ai_status"] == "travel_recommendation"
    assert final["travel_recommendation"]["tier"] == "gold"
    assert final["travel_recommendation"]["current_terms_confirmed"] is False


@pytest.mark.asyncio
async def test_travel_garbage_voice_input_never_becomes_a_destination():
    state: dict = {}
    history: list = []

    async def turn(msg):
        nonlocal state
        r = await chat_turn(msg, state, history)
        state = r["state"]
        return r

    await turn("I need travel insurance")
    await turn("single trip")
    r = await turn(">>>>>>>>")
    assert r["ai_status"] == "travel_guided_discovery"
    assert state.get("travel_destination") is None  # still not set — the flow must ask again, never accept noise


@pytest.mark.asyncio
async def test_relocation_language_triggers_ipmi_note_once():
    state: dict = {}
    history: list = []

    async def turn(msg):
        nonlocal state
        r = await chat_turn(msg, state, history)
        state = r["state"]
        return r

    await turn("I need travel insurance")
    await turn("single trip")
    r = await turn("I'm moving to Berlin permanently")
    assert "international health insurance" in r["reply"].lower() or "ipmi" in r["reply"].lower()
    assert state["travel_long_stay_warning_shown"] is True


@pytest.mark.asyncio
async def test_local_review_without_claude_key_uses_deterministic_fallback():
    state: dict = {}
    r = await chat_turn("Do you have local insurance?", state, [])
    assert r["journey"] == "local_review"
    assert r["ai_status"] == "local_review_playbook"
    assert len(r["reply"]) > 0
