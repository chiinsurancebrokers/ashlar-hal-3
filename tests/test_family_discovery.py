from backend.app.discovery.family_flow import apply_family_answer, next_family_question


def answer(state, value):
    update = apply_family_answer(value, state)
    state.update(update)
    return state


def test_family_flow_collects_spouse_and_routes_maternity():
    state = {"family_answered": False}
    q = next_family_question(state)
    assert q["key"] == "family_include"
    state["pending_question"] = q["key"]
    answer(state, "yes")

    q = next_family_question(state)
    assert q["key"] == "family_relationship"
    state["pending_question"] = q["key"]
    answer(state, "spouse")

    q = next_family_question(state)
    assert q["key"] == "family_age"
    state["pending_question"] = q["key"]
    answer(state, "38")

    q = next_family_question(state)
    assert q["key"] == "family_sex"
    state["pending_question"] = q["key"]
    answer(state, "female")

    q = next_family_question(state)
    assert q["key"] == "family_maternity"
    state["pending_question"] = q["key"]
    answer(state, "yes")
    assert state["household_members"][0]["maternity_required"] is True


def test_maternity_not_asked_for_male_or_outside_age_range():
    for age, sex in [(38, "male"), (17, "female"), (48, "female")]:
        state = {
            "family_answered": True,
            "family_requested": True,
            "household_member_index": 0,
            "household_members": [{"member_id": "member-1", "relationship": "spouse", "age": age, "sex": sex}],
        }
        assert next_family_question(state)["key"] == "family_add_another"


def test_family_can_add_multiple_members():
    state = {
        "family_answered": True,
        "family_requested": True,
        "household_member_index": 0,
        "household_members": [{"member_id": "member-1", "relationship": "child", "age": 8, "sex": "unspecified"}],
    }
    q = next_family_question(state)
    assert q["key"] == "family_add_another"
    state["pending_question"] = q["key"]
    answer(state, "yes")
    assert next_family_question(state)["key"] == "family_relationship"


def test_no_family_finishes_immediately():
    state = {"family_answered": False, "pending_question": "family_include"}
    answer(state, "no")
    assert state["household_complete"] is True
    assert next_family_question(state) is None
