"""HAL prices residents across Europe and worldwide (Morgan Price wording 2a / area definitions)."""
import asyncio

from backend.app.discovery import legacy_flow as lf
from backend.app.services import family_live_orchestrator as live

TAIL = ["no", "€500 deductible", "Hospital only", "No", "No maternity needed", "No dental needed",
        "No mental health cover needed", "No wellness cover needed", "No optical cover needed",
        "No evacuation priority", "No fixed budget"]


def _run(residence, area_answer):
    msgs = ["anna", "38", "female", residence, "Same as residence", "british", area_answer, *TAIL]

    async def go():
        st = {"pending_question": "name"}
        for m in msgs:
            r = await live.chat_turn(m, st, [])
            st = r["state"]
        return r
    return asyncio.run(go())


def test_portugal_resident_gets_priced_shortlist():
    r = _run("Portugal", "Europe only")
    assert r["quotes"] and all(q["plan_key"].startswith("morgan_price:") for q in r["quotes"])
    assert "Here is HAL's shortlist" in r["reply"] and "Portugal" in r["reply"]   # OECD note for Portugal
    assert "Greece's public healthcare" not in r["followup_message"]


def test_us_resident_gets_honest_reply():
    r = _run("United States", "Worldwide including USA")
    assert r["quotes"] == [] and "not available to people living in the United States" in r["reply"]
    assert r["followup_message"] == "" and r["lead_cta"]["show"] is True


def test_europe_only_is_not_offered_outside_europe():
    q = lf.next_discovery_question({"name_asked": True, "age": 40, "residence_country": "United Arab Emirates",
                                    "primary_healthcare_country_answered": True, "nationality_answered": True})
    assert q["key"] == "coverage_area" and "Europe only" not in [c["value"] for c in q["quick_replies"]]


def test_europe_answer_from_outside_europe_is_asked_again():
    state = {"pending_question": "coverage_area", "residence_country": "United Arab Emirates"}
    out = lf.apply_discovery_answer("Europe only", state)
    assert "coverage_area" not in out and out["coverage_area_mismatch"] is True
    q = lf.next_discovery_question({"name_asked": True, "age": 40, "primary_healthcare_country_answered": True,
                                    "nationality_answered": True, **state, **out})
    assert "doesn't include the country where you live" in q["reply"]
    assert lf.apply_discovery_answer("skip", state)["coverage_area"] == "area3"
