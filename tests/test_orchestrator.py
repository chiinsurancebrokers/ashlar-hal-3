import pytest

from backend.app.services.orchestrator import chat_turn


@pytest.mark.asyncio
async def test_shortlist_reply_always_explains_why_the_top_plan_was_chosen():
    state: dict = {
        "age": 51, "residence_country": "Greece", "coverage_area": "area2", "maternity_required": True,
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
async def test_full_guided_flow_reaches_shortlist_without_openai_configured():
    state: dict = {}
    history: list = []

    async def turn(msg):
        nonlocal state
        r = await chat_turn(msg, state, history)
        state = r["state"]
        return r

    r = await turn("I'm looking for international health insurance")
    assert r["ai_status"] == "guided_discovery"

    r = await turn("51")
    r = await turn("Greece")
    r = await turn("Worldwide excluding USA")
    r = await turn("skip")   # deductible
    r = await turn("include outpatient")
    r = await turn("no")     # chronic
    r = await turn("yes")    # maternity (age 51 -> not asked; but harmless if skipped by flow)
    r = await turn("skip")   # dental
    r = await turn("skip")   # mental health
    r = await turn("skip")   # wellness
    r = await turn("skip")   # optical
    r = await turn("skip")   # evacuation
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
async def test_local_review_without_openai_key_uses_deterministic_fallback():
    state: dict = {}
    r = await chat_turn("Do you have local insurance?", state, [])
    assert r["journey"] == "local_review"
    assert r["ai_status"] == "local_review_playbook"
    assert len(r["reply"]) > 0
