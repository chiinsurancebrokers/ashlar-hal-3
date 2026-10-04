import re
import pytest

from backend.app.discovery.legacy_flow import apply_discovery_answer


@pytest.mark.parametrize("answer,country", [
    ("greek", "Greece"), ("Greece", "Greece"), ("ελλάδα", "Greece"), ("I live in greece", "Greece"),
    ("british", "United Kingdom"), ("german", "Germany"), ("Τουρκία", "Türkiye"), ("turkey", "Türkiye"),
    ("portuguese", "Portugal"), ("Κύπρο", "Cyprus"),
])
def test_residence_accepts_names_demonyms_and_greek(answer, country):
    out = apply_discovery_answer(answer, {"pending_question": "residence"})
    assert out["residence_country"] == country


@pytest.mark.parametrize("answer,country", [("greek", "Greece"), ("portugal", "Portugal"), ("τουρκία", "Türkiye")])
def test_main_healthcare_country_accepts_demonyms(answer, country):
    out = apply_discovery_answer(answer, {"pending_question": "primary_healthcare_country", "residence_country": "Greece"})
    assert out["primary_healthcare_country"] == country


def test_personal_family_quote_has_no_plan_followup(monkeypatch):
    import asyncio
    from backend.app.services import family_live_orchestrator as live

    state = {"journey": "ipmi", "family_requested": True, "household_complete": True, "discovery_complete": True,
             "age": 51, "coverage_area": "area1",
             "household_members": [{"member_id": "member-1", "relationship": "spouse", "age": 45, "sex": "female"}]}

    async def fake_base(message, st, history):
        return {"state": state, "journey": "ipmi", "ai_status": "verified_shortlist", "reply": "x",
                "followup_message": "Want me to walk you through any of these plans?", "quotes": [{"premium": 1}]}

    class Elig:
        verdict = "PASS"
        def model_dump(self, mode="json"):
            return {"verdict": "PASS"}

    async def elig(*a, **k):
        return Elig()

    monkeypatch.setattr(live, "base_chat_turn", fake_base)
    monkeypatch.setattr(live, "assess_eligibility", elig)
    monkeypatch.setattr(live, "quote_shortlist", lambda applicant, settings: [])
    result = asyncio.run(live.chat_turn("No fixed budget", state, []))
    assert result["ai_status"] == "personal_family_quotation_required"
    assert result["followup_message"] == ""


@pytest.mark.parametrize("value", ["Portugal", "Türkiye", "United Arab Emirates", "South Korea", "Czechia",
                                   "North Macedonia", "Hong Kong", "Saudi Arabia"])
def test_every_dropdown_value_is_stored_as_given(value):
    for pending, field in (("residence", "residence_country"), ("primary_healthcare_country", "primary_healthcare_country"),
                           ("nationality", "nationality")):
        out = apply_discovery_answer(value, {"pending_question": pending, "residence_country": "Greece"})
        assert out[field] == value, (pending, value, out)


def test_dropdown_country_does_not_switch_greek_conversation_to_english():
    from backend.app.services.orchestrator import _resolve_language
    state = {"language": "el", "pending_question": "residence"}
    assert _resolve_language("Portugal", state) is True
    assert state["language"] == "el"


def test_frontend_has_country_dropdown_for_country_questions():
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "COUNTRY_KEYS=['residence','primary_healthcare_country','nationality']" in html
    values = set(re.findall(r'\["([^"]+)","[^"]+"\]', html.split("const COUNTRY_OPTIONS_ALL=")[1].split(";")[0]))
    assert {"Greece", "Cyprus", "Türkiye", "Portugal", "United Kingdom"} <= values
