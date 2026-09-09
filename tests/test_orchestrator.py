import pytest

from backend.app.services.orchestrator import chat_turn


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
async def test_travel_intent_is_isolated_and_clearly_labelled_as_pending():
    state: dict = {}
    r = await chat_turn("I need travel insurance for a single trip", state, [])
    assert r["journey"] == "travel"
    assert r["ai_status"] == "travel_not_yet_implemented"


@pytest.mark.asyncio
async def test_local_review_without_openai_key_uses_deterministic_fallback():
    state: dict = {}
    r = await chat_turn("Do you have local insurance?", state, [])
    assert r["journey"] == "local_review"
    assert r["ai_status"] == "local_review_playbook"
    assert len(r["reply"]) > 0
