import asyncio

import pytest

from backend.app.core.config import get_settings
from backend.app.services import country_health_agent as agent
from backend.app.services.healthcare_context import healthcare_note

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
    assert all(isinstance(f["page"], int) and f["page"] > 0 for f in evidence["facts"])


def test_ai_note_with_official_figures_is_used(monkeypatch, with_key):
    text = ("In Greece, public and compulsory schemes cover 0% of dental care costs (OECD 32%) and only 62% of "
            "outpatient care (OECD 78%), and households pay more than one-third of all healthcare costs out of pocket. "
            "Only 27% of residents are satisfied with the availability of quality care (OECD 64%). "
            "The public system covers everyone for core services, and international cover can help with the rest. "
            "Source: OECD, Health at a Glance 2025.")
    note, seen = _note(monkeypatch, text)
    assert note == text
    assert "dental care" in seen["instructions"] and "outpatient care" in seen["instructions"]
    assert "[p.109]" in seen["instructions"]


@pytest.mark.parametrize("bad", [
    "Only 22% of residents are satisfied. Source: OECD, Health at a Glance 2025.",          # invented figure
    "Waiting times average 180 days in Greece. Source: OECD, Health at a Glance 2025.",    # invented claim with number
    "Only 27% of residents are satisfied with healthcare in Greece (OECD 64%).",            # missing source
])
def test_ai_note_with_unsupported_content_falls_back(monkeypatch, with_key, bad):
    note, _ = _note(monkeypatch, bad)
    assert note == healthcare_note("Greece")


def test_greek_decimal_comma_is_accepted(monkeypatch, with_key):
    text = ("Το 12,1% των κατοίκων αναφέρει ανικανοποίητες ανάγκες (ΟΟΣΑ 3,4%) και το 39,1% των δαπανών δεν "
            "καλύπτεται από δημόσια σχήματα. Πηγή: ΟΟΣΑ, Health at a Glance 2025.")
    note, _ = _note(monkeypatch, text, greek=True)
    assert note == text


def test_ai_failure_falls_back(monkeypatch, with_key):
    async def boom(**kwargs):
        raise RuntimeError("down")
    monkeypatch.setattr(agent, "claude_response", boom)
    assert asyncio.run(agent.country_health_note(STATE, False)) == healthcare_note("Greece")


def test_no_key_uses_deterministic_note(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    assert asyncio.run(agent.country_health_note(STATE, True)) == healthcare_note("Greece", True)
    get_settings.cache_clear()
