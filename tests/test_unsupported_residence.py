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


# ---------- Age ceiling: routed to the broker fallback form, not told to
# "change your needs". The Morgan Price 2026 workbook caps at 74 and HAL
# must not pretend the problem is a benefits mismatch. ----------

def test_over_74_applicant_gets_fallback_form_url_not_a_needs_blame():
    from backend.app.services.orchestrator import _no_verified_price_reply, PERSONAL_HEALTH_FALLBACK_URL
    state = {"applicant_name": "Giorgos", "age": 78, "residence_country": "Greece",
             "coverage_area": "area1", "currency": "EUR"}
    msg = _no_verified_price_reply(state, [], greek=False)
    assert PERSONAL_HEALTH_FALLBACK_URL in msg
    assert "above the upper age limit" in msg
    assert "You can change one of your needs" not in msg
    assert "age (78)" in msg

    msg_el = _no_verified_price_reply({**state, "language": "el"}, [], greek=True)
    assert PERSONAL_HEALTH_FALLBACK_URL in msg_el
    assert "με το χέρι" in msg_el   # broker reviews it by hand
    assert "ηλικία σας (78)" in msg_el


def test_helper_detects_dependent_outside_bands():
    """The orchestrator's single-applicant path doesn't carry dependents on
    state (family discovery routes through family_live_orchestrator), but
    the helper itself must handle dependents correctly for callers that do
    pass a full household Applicant — otherwise a future caller silently
    reverts to blaming the applicant's needs."""
    from backend.app.services.orchestrator import _age_outside_loaded_bands
    from backend.app.schemas.applicant import Applicant, Dependent
    ap = Applicant(age=42, residence_country="Greece", coverage_area="area1",
                   dependents=[Dependent(relationship="spouse", age=80)])
    issue = _age_outside_loaded_bands(ap)
    assert issue is not None
    assert issue["age"] == 80 and issue["who"] == "spouse"


def test_inside_bands_without_quotes_keeps_the_generic_needs_message():
    """If the applicant IS within the loaded age bands but still gets zero
    quotes (every plan hard-excluded by a must-have for example), the
    original 'change one of your needs' guidance is still correct."""
    from backend.app.services.orchestrator import _no_verified_price_reply, PERSONAL_HEALTH_FALLBACK_URL
    state = {"applicant_name": "Elena", "age": 40, "residence_country": "Greece",
             "coverage_area": "area1", "currency": "EUR"}
    msg = _no_verified_price_reply(state, [], greek=False)
    assert PERSONAL_HEALTH_FALLBACK_URL not in msg
    assert "change one of your needs" in msg
