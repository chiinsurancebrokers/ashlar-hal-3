import asyncio

from backend.app.core.config import get_settings
from backend.app.services import family_live_orchestrator as live
from backend.app.services.country_health_agent import deterministic_note


def test_greece_gap_note_uses_official_figures_in_both_languages():
    en, el = deterministic_note("Greece"), deterministic_note("Ελλάδα", greek=True)
    for figure in ("73%", "36%", "12.1%", "3.4%", "39.1%", "24.9%", "37%", "11%", "38%", "22%", "100%", "68%"):
        assert figure in en
    for figure in ("73%", "36%", "12,1%", "3,4%", "39,1%", "24,9%", "37%", "11%", "100%"):
        assert figure in el
    assert "OECD, Health at a Glance 2025" in en and "ΟΟΣΑ, Health at a Glance 2025" in el


def test_gap_framing_never_states_covered_or_satisfied_share():
    for text in (deterministic_note("Greece"), deterministic_note("Greece", True)):
        for positive in ("27%", "63%", "64%", "89%", "60.9%", "60,9%", "62%"):
            assert positive not in text


def test_only_worse_than_oecd_gaps_are_shown():
    turkey = deterministic_note("Turkey")
    assert "59%" in turkey and "36%" in turkey       # not satisfied, worse than OECD
    assert "1.2%" not in turkey                      # unmet needs better than OECD: omitted


def test_country_names_resolve_in_english_and_greek():
    assert "Türkiye" in deterministic_note("Τουρκία")
    assert "Πορτογαλία" in deterministic_note("Πορτογαλία", True)
    assert deterministic_note("Cyprus") == ""         # not an OECD country in the report
    assert deterministic_note(None) == ""


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


def test_individual_shortlist_includes_country_note(monkeypatch):
    result = _run(["chris", "51", "male", "greece", "Same as residence", "greek", "Europe only", "no"] + NEEDS, monkeypatch)
    assert result["quotes"]
    assert "A word on healthcare in Greece" in result["reply"]


def test_note_follows_country_where_applicant_lives(monkeypatch):
    result = _run(["chris", "51", "male", "greece", "portugal", "greek", "Europe only", "no"] + NEEDS, monkeypatch)
    assert result["state"]["primary_healthcare_country"] == "Portugal"
    assert "A word on healthcare in Portugal" in result["reply"]


def test_household_shortlist_includes_country_note(monkeypatch):
    result = _run(["chris", "51", "male", "greece", "Same as residence", "greek", "Europe only",
                   "yes", "spouse", "45", "female", "no", "no"] + NEEDS, monkeypatch)
    assert result["ai_status"] == "verified_household_shortlist"
    assert result["reply"].index("Household total") < result["reply"].index("A word on healthcare in Greece")
