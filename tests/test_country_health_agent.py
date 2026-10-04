import asyncio

import pytest

from backend.app.core.config import get_settings
from backend.app.services import country_health_agent as agent

STATE = {"residence_country": "Greece", "primary_healthcare_country": "Greece",
         "outpatient_required": True, "dental_required": True}


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _note(monkeypatch, ai_text, greek=False):
    seen = {}

    async def fake(**kwargs):
        seen.update(kwargs)
        return ai_text
    monkeypatch.setattr(agent, "claude_response", fake)
    return asyncio.run(agent.country_health_note(STATE, greek)), seen


def test_every_fact_has_an_oecd_page():
    evidence = agent.load_oecd_evidence("Greece")
    assert evidence and len(evidence["facts"]) >= 15
    assert len(list(agent.EVIDENCE_DIR.glob("*.json"))) == 38
    assert all(isinstance(f["page"], int) and f["page"] > 0 for f in evidence["facts"])


def test_ai_note_with_official_figures_is_used(monkeypatch, with_key):
    text = ("In Greece, 100% of dental care costs are not covered by public schemes (OECD 68%) and neither is 38% of "
            "outpatient care (OECD 22%), and households bear more than one-third of all healthcare costs directly. "
            "73% of residents are not satisfied with the availability of quality care (OECD 36%). "
            "The public system covers everyone for core services, and international cover can help with the rest. "
            "Source: OECD, Health at a Glance 2025.")
    note, seen = _note(monkeypatch, text)
    assert note == text
    assert "dental care" in seen["instructions"] and "outpatient care" in seen["instructions"]
    assert "[p.109]" in seen["instructions"]


@pytest.mark.parametrize("bad", [
    "Only 47.5% of residents are satisfied. Source: OECD, Health at a Glance 2025.",          # invented figure
    "Public schemes cover 63% of hospital costs. Source: OECD, Health at a Glance 2025.",    # covered share (not gap)
    "Waiting times average 180 days in Greece. Source: OECD, Health at a Glance 2025.",    # invented claim with number
    "Only 27% of residents are satisfied with healthcare in Greece (OECD 64%).",            # missing source
])
def test_ai_note_with_unsupported_content_falls_back(monkeypatch, with_key, bad):
    note, _ = _note(monkeypatch, bad)
    assert note == agent.deterministic_note("Greece")


def test_greek_decimal_comma_is_accepted(monkeypatch, with_key):
    text = ("Το 12,1% των κατοίκων αναφέρει ανικανοποίητες ανάγκες (ΟΟΣΑ 3,4%) και το 39,1% των δαπανών δεν "
            "καλύπτεται από δημόσια σχήματα. Πηγή: ΟΟΣΑ, Health at a Glance 2025.")
    note, _ = _note(monkeypatch, text, greek=True)
    assert note == text


def test_ai_failure_falls_back(monkeypatch, with_key):
    async def boom(**kwargs):
        raise RuntimeError("down")
    monkeypatch.setattr(agent, "claude_response", boom)
    assert asyncio.run(agent.country_health_note(STATE, False)) == agent.deterministic_note("Greece")


def test_no_key_uses_deterministic_note(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    assert asyncio.run(agent.country_health_note(STATE, True)) == agent.deterministic_note("Greece", True)
    get_settings.cache_clear()


def test_turkey_prompt_uses_turkey_evidence(monkeypatch, with_key):
    seen = {}

    async def fake(**kwargs):
        seen.update(kwargs)
        return "59% are not satisfied (OECD 36%). Source: OECD, Health at a Glance 2025."
    monkeypatch.setattr(agent, "claude_response", fake)
    note = asyncio.run(agent.country_health_note({"residence_country": "Τουρκία"}, False))
    assert "Türkiye" in seen["instructions"] and "Greece" not in seen["instructions"].split("Hard rules")[0].split("official OECD data")[0]
    assert note.startswith("59%")


def test_decimal_marks_follow_language():
    assert agent.fix_decimals("39,1% of spending", False) == "39.1% of spending"
    assert agent.fix_decimals("το 39.1% των δαπανών", True) == "το 39,1% των δαπανών"
    assert agent.fix_decimals("EUR 13,456.16", False) == "EUR 13,456.16"


def test_prompt_knows_client_already_lives_there(monkeypatch, with_key):
    seen = {}

    async def fake(**kwargs):
        seen.update(kwargs)
        return "73% are not satisfied (OECD 36%). Source: OECD, Health at a Glance 2025."
    monkeypatch.setattr(agent, "claude_response", fake)
    asyncio.run(agent.country_health_note({"residence_country": "Greece", "primary_healthcare_country": "Greece"}, False))
    assert "ALREADY LIVES in Greece" in seen["instructions"]
    asyncio.run(agent.country_health_note({"residence_country": "Cyprus", "primary_healthcare_country": "Greece"}, False))
    assert "will spend most of the year in Greece" in seen["instructions"]
