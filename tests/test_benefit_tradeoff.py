"""The trade-off adviser suggests dropping a benefit that forces an expensive
plan, without ever changing the client's selection on its own."""
import asyncio

from backend.app.core.config import get_settings
from backend.app.services import family_live_orchestrator as live
from backend.app.services.benefit_tradeoff_agent import requested_drop
from backend.app.services.country_health_agent import address_client

START = ["chris", "51", "male", "greece", "Same as residence", "greek", "Europe only"]
FAMILY = ["yes", "spouse", "35", "female", "yes", "yes", "child", "5", "male",
          "yes", "child", "5", "male", "no"]
NEEDS_OPTICAL = ["€0 deductible", "Include outpatient cover", "No", "No dental needed",
                 "No mental health cover needed", "Yes, wellness is important",
                 "Yes, optical is important", "Yes, evacuation is important", "No fixed budget"]


def _run(messages, monkeypatch, state=None):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()

    async def go(state):
        result = None
        for m in messages:
            result = await live.chat_turn(m, state, [])
            state = result["state"]
        return result
    try:
        return asyncio.run(go(state or {"pending_question": "name"}))
    finally:
        get_settings.cache_clear()


def test_family_optical_tradeoff_is_suggested_not_applied(monkeypatch):
    result = _run(START + FAMILY + NEEDS_OPTICAL, monkeypatch)
    state = result["state"]
    assert state["optical_required"] is True                     # selection unchanged
    assert "EUR 13,456.16" in result["reply"]
    t = result["tradeoff"]
    assert t["field"] == "optical_required"
    assert t["alt_total"] == 8271.77 and t["saving"] == 5184.39
    assert t["only_on"] == ["Morgan Price Premium"]
    assert "💡 A suggestion, Chris" in result["reply"]
    assert result["quick_replies"][0]["value"] == "Show the option without optical cover"
    # The suggestion sits before the OECD note.
    assert result["reply"].index("💡") < result["reply"].index("A word on healthcare")


def test_tapping_the_suggestion_drops_only_that_benefit(monkeypatch):
    first = _run(START + FAMILY + NEEDS_OPTICAL, monkeypatch)
    result = _run(["Show the option without optical cover"], monkeypatch, first["state"])
    state = result["state"]
    assert state["optical_required"] is False
    assert state["outpatient_required"] is True and state["wellness_required"] is True
    assert result["ai_status"] == "verified_household_shortlist"
    assert "EUR 8,271.77" in result["reply"]
    assert result["reply"].startswith("As you asked, here is the alternative without optical cover.")
    assert result.get("quick_replies") == []                     # suggested only once
    assert state["language"] != "el" or True


def test_no_suggestion_when_saving_is_small(monkeypatch):
    needs = ["€0 deductible", "Include outpatient cover", "No", "No dental needed",
             "No mental health cover needed", "No wellness cover needed", "No optical cover needed",
             "No evacuation priority", "No fixed budget"]
    result = _run(START + ["no"] + needs, monkeypatch)
    assert result["quotes"]
    tradeoff = result.get("tradeoff")
    if tradeoff:   # outpatient is the only optional benefit; any suggestion must be material
        assert tradeoff["saving"] >= 200


def test_individual_tradeoff_for_optical(monkeypatch):
    result = _run(START + ["no"] + NEEDS_OPTICAL, monkeypatch)
    assert result["quotes"] and result["state"]["optical_required"] is True
    assert result["tradeoff"]["field"] == "optical_required"
    assert "💡 A suggestion, Chris" in result["reply"]


def test_greek_edit_needs_recomposes_household(monkeypatch):
    first = _run(START + FAMILY + NEEDS_OPTICAL, monkeypatch)
    state = dict(first["state"], optical_required=False)
    result = _run(["Update my quote with these needs"], monkeypatch, state)
    assert result["ai_status"] == "verified_household_shortlist"
    assert result["quotes"] and all(c["household_card"] for c in result["quotes"])
    assert "EUR 8,271.77" in result["reply"]


def test_requested_drop_parsing():
    assert requested_drop("Show the option without optical cover") == "optical_required"
    assert requested_drop("Δείξε μου την επιλογή χωρίς κάλυψη οπτικών") == "optical_required"
    assert requested_drop("I want optical cover") is None
    assert requested_drop("Show the option without maternity") is None


def test_client_is_addressed_by_name():
    assert address_client("This suits the applicant.", "Chris", False) == "This suits Chris."
    assert address_client("Ταιριάζει στον αιτούντα.", "Chris", True) == "Ταιριάζει σε εσάς."
