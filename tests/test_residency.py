"""Visa / residence-permit routing."""
import pytest

from backend.app.discovery import legacy_flow as lf
from backend.app.services.residency_agent import add_residency_note, mentions_residency_purpose


@pytest.mark.parametrize("text", ["I need insurance for my D7 visa", "for my AIMA appointment", "residence permit in Portugal",
                                  "golden visa", "Χρειάζομαι ασφάλιση για άδεια διαμονής", "για τη χρυσή βίζα"])
def test_detects_visa_language(text):
    assert mentions_residency_purpose(text)


@pytest.mark.parametrize("text", ["I live in Portugal", "hospital only", "worldwide cover"])
def test_ignores_other_text(text):
    assert not mentions_residency_purpose(text)


BASE = {"name_asked": True, "age": 40, "residence_country": "Portugal", "primary_healthcare_country_answered": True,
        "nationality_answered": True}


def test_asks_only_when_nationality_differs():
    q = lf.next_discovery_question({**BASE, "nationality": "United Kingdom"})
    assert q["key"] == "residency_purpose"
    assert lf.next_discovery_question({**BASE, "residence_country": "Greece", "nationality": "Greece"})["key"] == "coverage_area"
    assert lf.next_discovery_question({**BASE})["key"] == "coverage_area"   # nationality skipped


@pytest.mark.parametrize("answer,expected", [("Yes, for a visa or residence permit", True), ("No, not for a visa", False),
                                             ("Ναι", True), ("skip", False)])
def test_answers(answer, expected):
    out = lf.apply_discovery_answer(answer, {**BASE, "nationality": "United Kingdom", "pending_question": "residency_purpose"})
    assert out["residency_purpose"] is expected and out["residency_purpose_answered"] is True


def test_mentioned_earlier_skips_the_question():
    out = lf.apply_discovery_answer("Portugal, I need it for my D7 visa", {"pending_question": "residence"})
    assert out["residency_purpose"] is True
    state = {**BASE, "nationality": "United Kingdom", **out}
    assert lf.next_discovery_question(state)["key"] == "coverage_area"


def test_note_goes_before_country_note_and_only_once():
    state = {"residency_purpose": True, "residence_country": "Portugal", "applicant_name": "Chris"}
    result = {"reply": "Shortlist.\n\nOECD note.", "healthcare_note": "OECD note.", "quick_replies": [{"label": "x", "value": "x"}]}
    add_residency_note(result, state, greek=False)
    assert result["reply"].startswith("Shortlist.") and result["reply"].endswith("OECD note.")
    assert "consulate or immigration authority" in result["reply"] and "Chris, since" in result["reply"]
    assert [q["label"] for q in result["quick_replies"]] == ["x", "Travel cover for the visa stage"]
    again = {"reply": "Shortlist.", "quick_replies": []}
    add_residency_note(again, state, greek=False)
    assert again["reply"] == "Shortlist."


def test_quick_reply_opens_travel_journey():
    from backend.app.services.journey import classify_journey
    assert classify_journey("I need travel insurance for my visa stage") == "travel"


def test_unsupported_residence_gets_honest_reply_not_empty_shortlist():
    import asyncio
    from backend.app.services import family_live_orchestrator as live
    msgs = ["anna", "38", "female", "Portugal", "Same as residence", "british", "Yes, for a visa or residence permit",
            "Europe only", "no", "€500 deductible", "Hospital only", "No", "No maternity needed", "No dental needed",
            "No mental health cover needed", "No wellness cover needed", "No optical cover needed",
            "No evacuation priority", "No fixed budget"]

    async def go():
        st = {"pending_question": "name"}
        for m in msgs:
            r = await live.chat_turn(m, st, [])
            st = r["state"]
        return r
    r = asyncio.run(go())
    assert r["quotes"] == [] and "Here is HAL's shortlist" not in r["reply"]
    assert "residents of Portugal" in r["reply"] and "consulate or immigration authority" in r["reply"]
    assert r["followup_message"] == "" and r["lead_cta"]["show"] is True
