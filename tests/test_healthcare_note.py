import asyncio

from backend.app.core.config import get_settings
from backend.app.services import family_live_orchestrator as live
from backend.app.services.healthcare_context import healthcare_note


def test_greece_note_uses_verified_oecd_figures_in_both_languages():
    en, el = healthcare_note("Greece"), healthcare_note("Ελλάδα", greek=True)
    for figure in ("27%", "64%", "12.1%", "3.4%", "39.1%", "24.9%", "63%", "89%"):
        assert figure in en
    for figure in ("27%", "64%", "12,1%", "3,4%", "39,1%", "24,9%", "63%", "89%"):
        assert figure in el
    assert "OECD, Health at a Glance 2025" in en and "ΟΟΣΑ, Health at a Glance 2025" in el
    assert "safety net" in en and "δίχτυ ασφαλείας" in el


def test_no_note_without_curated_profile():
    assert healthcare_note("Spain") == ""
    assert healthcare_note(None) == ""


def _run(messages, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()

    async def go():
        state, result = {"pending_question": "name"}, None
        for m in messages:
            result = await live.chat_turn(m, state, [])
            state = result["state"]
        return result
    try:
        return asyncio.run(go())
    finally:
        get_settings.cache_clear()


NEEDS = ["€0 deductible", "Include outpatient cover", "No", "No dental needed",
         "No mental health cover needed", "Yes, wellness is important", "No optical cover needed",
         "Yes, evacuation is important", "No fixed budget"]
START = ["chris", "51", "male", "greece", "Same as residence", "greek", "Europe only"]


def test_individual_shortlist_includes_country_note(monkeypatch):
    result = _run(START + ["no"] + NEEDS, monkeypatch)
    assert result["quotes"]
    assert "A word on healthcare in Greece" in result["reply"]
    assert result["healthcare_note"] in result["reply"]


def test_household_shortlist_includes_country_note(monkeypatch):
    result = _run(START + ["yes", "spouse", "45", "female", "no", "no"] + NEEDS, monkeypatch)
    assert result["ai_status"] == "verified_household_shortlist"
    assert "Household total" in result["reply"]
    assert result["reply"].index("Household total") < result["reply"].index("A word on healthcare in Greece")
