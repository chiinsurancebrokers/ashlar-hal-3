from backend.app.discovery.flow import apply_discovery_answer, next_discovery_question, discovery_progress


def test_full_guided_sequence_reaches_chronic_before_maternity():
    state = {"age": 30, "residence_country": "Greece", "coverage_area": "area1",
              "deductible_answered": True, "outpatient_answered": True}
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
    q = next_discovery_question({})
    assert q["key"] == "age"
    assert all(r["value"] != "skip" for r in q["quick_replies"]), "age question must not offer a skip option"


def test_optical_wellness_chronic_are_reachable_in_guided_order():
    state = {"age": 30, "residence_country": "Greece", "coverage_area": "area1",
              "deductible_answered": True, "outpatient_answered": True, "chronic_answered": True,
              "maternity_answered": True, "dental_answered": True, "mental_health_answered": True}
    q = next_discovery_question(state)
    assert q["key"] == "wellness"
    state["wellness_answered"] = True
    q2 = next_discovery_question(state)
    assert q2["key"] == "optical"


def test_discovery_progress_counts_chronic():
    state = {"age": 30, "residence_country": "Greece", "coverage_area": "area1"}
    p = discovery_progress(state)
    assert p["total"] >= 11
    state["chronic_answered"] = True
    p2 = discovery_progress(state)
    assert p2["completed"] == p["completed"] + 1
