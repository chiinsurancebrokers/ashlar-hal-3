from backend.app.discovery.flow import apply_discovery_answer, next_discovery_question, discovery_progress


def test_full_guided_sequence_reaches_chronic_before_maternity():
    state = {"name_asked": True, "age": 30, "residence_country": "Greece",
              "primary_healthcare_country": "Greece", "primary_healthcare_country_answered": True,
              "coverage_area": "area1", "deductible_answered": True, "outpatient_answered": True}
    q = next_discovery_question(state)
    assert q["key"] == "chronic", "chronic must be asked before maternity/dental, per audit priority"


def test_chronic_disclosure_distinct_from_chronic_preference():
    state = {"pending_question": "chronic"}
    out = apply_discovery_answer("I have a diagnosed condition", state)
    assert out["chronic_conditions_disclosed"] is True
    assert out["chronic_required"] is True

    state2 = {"pending_question": "chronic"}
    out2 = apply_discovery_answer("no", state2)
    assert out2["chronic_required"] is False
    assert "chronic_conditions_disclosed" not in out2


def test_skip_never_leaves_the_flow_stuck_on_optional_questions():
    state = {"pending_question": "optical"}
    out = apply_discovery_answer("not sure", state)
    assert out["optical_answered"] is True
    assert out["optical_required"] is False
    assert out["pending_question"] is None


def test_skip_on_greek_phrasing():
    state = {"pending_question": "wellness"}
    out = apply_discovery_answer("δεν ξέρω", state)
    assert out["wellness_answered"] is True


def test_age_and_residence_are_not_skippable_since_no_safe_default_exists():
    name_q = next_discovery_question({})
    assert name_q["key"] == "name"
    assert any(r["value"] == "skip" for r in name_q["quick_replies"]), "name is a nice-to-have and should remain skippable"

    q = next_discovery_question({"name_asked": True})
    assert q["key"] == "age"
    assert all(r["value"] != "skip" for r in q["quick_replies"]), "age question must not offer a skip option"


def test_optical_wellness_chronic_are_reachable_in_guided_order():
    state = {"name_asked": True, "age": 30, "residence_country": "Greece",
              "primary_healthcare_country": "Greece", "primary_healthcare_country_answered": True,
              "coverage_area": "area1", "deductible_answered": True, "outpatient_answered": True, "chronic_answered": True,
              "maternity_answered": True, "dental_answered": True, "mental_health_answered": True}
    q = next_discovery_question(state)
    assert q["key"] == "wellness"
    state["wellness_answered"] = True
    q2 = next_discovery_question(state)
    assert q2["key"] == "optical"


def test_discovery_progress_counts_chronic():
    state = {"age": 30, "residence_country": "Greece", "primary_healthcare_country_answered": True, "coverage_area": "area1"}
    p = discovery_progress(state)
    assert p["total"] >= 11
    state["chronic_answered"] = True
    p2 = discovery_progress(state)
    assert p2["completed"] == p["completed"] + 1


def test_bundled_message_extracts_country_cleanly_and_catches_the_extra_preference():
    # Regression: a real reported bug — the whole sentence was previously
    # stored as 'residence_country' instead of just the country name.
    state = {"pending_question": "residence"}
    out = apply_discovery_answer("greece and i am looking for in patient and outpatient insurance coverage", state)
    assert out["residence_country"] == "Greece"
    assert out["outpatient_required"] is True
    assert out["outpatient_answered"] is True


def test_opportunistic_scan_never_overrides_an_already_answered_field():
    state = {"pending_question": "residence", "outpatient_answered": True, "outpatient_required": False}
    out = apply_discovery_answer("greece, i definitely want outpatient cover", state)
    assert "outpatient_required" not in out, "an earlier explicit answer must never be silently overridden"


def test_a_genuinely_long_answer_never_gets_stored_as_a_country_name():
    state = {"pending_question": "residence"}
    out = apply_discovery_answer("I really am not sure yet, need to think about this some more please", state)
    assert "residence_country" not in out, "a long free-text sentence must never be accepted as a country name"


def test_name_step_is_first_and_feeds_a_personalised_age_prompt():
    q = next_discovery_question({})
    assert q["key"] == "name"
    out = apply_discovery_answer("Christos", {"pending_question": "name"})
    assert out["applicant_name"] == "Christos"
    assert out["name_asked"] is True
    q2 = next_discovery_question({"name_asked": True, "applicant_name": "Christos"})
    assert q2["key"] == "age"
    assert "Christos" in q2["reply"]


def test_greek_quick_replies_are_localised_but_machine_values_stay_stable():
    # Eligibility identity step has already been completed; this test targets coverage quick replies.
    state = {"name_asked": True, "age": 51, "residence_country": "Greece",
             "primary_healthcare_country": "Greece", "primary_healthcare_country_answered": True,
             "nationality_answered": True}
    q = next_discovery_question(state, greek=True)
    assert q["key"] == "coverage_area"
    labels = [r["label"] for r in q["quick_replies"]]
    values = [r["value"] for r in q["quick_replies"]]
    assert "Ευρώπη" in labels
    assert "Δεν είμαι σίγουρος / Παράλειψη" in labels
    assert "Europe only" in values
    assert "skip" in values


def test_greek_outpatient_choices_are_not_shown_in_english():
    state = {
        "name_asked": True, "age": 51, "residence_country": "Greece",
        "primary_healthcare_country": "Greece", "primary_healthcare_country_answered": True,
        "coverage_area": "area1", "deductible_answered": True,
    }
    q = next_discovery_question(state, greek=True)
    assert q["key"] == "outpatient"
    labels = [r["label"] for r in q["quick_replies"]]
    assert "Μόνο νοσοκομειακή" in labels
    assert "Με εξωνοσοκομειακή κάλυψη" in labels


def test_new_guided_flow_asks_permanent_residence_then_nationality():
    state = {"name_asked": True, "age": 40}
    q1 = next_discovery_question(state, greek=True)
    assert q1["key"] == "residence"
    assert "μόνιμης κατοικίας" in q1["reply"]

    state["residence_country"] = "Greece"
    q2 = next_discovery_question(state, greek=True)
    assert q2["key"] == "primary_healthcare_country"
    assert "έξι μήνες" in q2["reply"]

    state["primary_healthcare_country"] = "Greece"
    state["primary_healthcare_country_answered"] = True
    q3 = next_discovery_question(state, greek=True)
    assert q3["key"] == "nationality"
    assert "υπηκοότητά" in q3["reply"]


def test_nationality_answer_is_parsed_independently_from_residence():
    state = {"pending_question": "nationality"}
    out = apply_discovery_answer("Είμαι Έλληνας", state)
    assert out["nationality"] == "Greece"
    assert out["nationality_answered"] is True


def test_legacy_session_with_coverage_area_is_not_forced_back_to_nationality():
    state = {
        "name_asked": True, "age": 40, "residence_country": "Greece",
        "primary_healthcare_country": "Greece", "primary_healthcare_country_answered": True,
        "coverage_area": "area1", "deductible_answered": True,
        "outpatient_answered": True,
    }
    q = next_discovery_question(state)
    assert q["key"] == "chronic"


def test_primary_healthcare_country_same_as_residence_is_stored_separately():
    state = {"pending_question": "primary_healthcare_country", "residence_country": "Greece"}
    out = apply_discovery_answer("same as residence", state)
    assert out["primary_healthcare_country"] == "Greece"
    assert out["primary_healthcare_country_answered"] is True


def test_primary_healthcare_country_parses_greek_country_answer():
    state = {"pending_question": "primary_healthcare_country", "residence_country": "Greece"}
    out = apply_discovery_answer("Θα μένω κυρίως στην Κύπρο", state)
    assert out["primary_healthcare_country"] == "Cyprus"
    assert out["primary_healthcare_country_answered"] is True
