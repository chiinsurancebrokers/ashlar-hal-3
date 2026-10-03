from backend.app.discovery.flow import apply_discovery_answer, next_discovery_question


def family_state(**values):
    return {"household_discovery_enabled": True, **values}


def test_primary_sex_is_asked_after_age_and_before_residence():
    state = family_state(name_asked=True, age=35)
    q = next_discovery_question(state)
    assert q["key"] == "primary_sex"


def test_male_primary_never_gets_maternity_question():
    state = family_state(
        name_asked=True, age=35, sex="male", primary_sex_answered=True,
        residence_country="Greece", primary_healthcare_country_answered=True,
        nationality_answered=True, coverage_area="area1",
        family_answered=True, family_requested=False, household_complete=True,
        deductible_answered=True, outpatient_answered=True, chronic_answered=True,
    )
    q = next_discovery_question(state)
    assert q["key"] != "maternity"
    assert state["maternity_answered"] is True
    assert state["maternity_required"] is False


def test_female_primary_47_gets_maternity_question():
    state = family_state(
        name_asked=True, age=47, sex="female", primary_sex_answered=True,
        residence_country="Greece", primary_healthcare_country_answered=True,
        nationality_answered=True, coverage_area="area1",
        family_answered=True, family_requested=False, household_complete=True,
        deductible_answered=True, outpatient_answered=True, chronic_answered=True,
    )
    assert next_discovery_question(state)["key"] == "maternity"


def test_family_stage_occurs_after_area_before_benefit_preferences():
    state = family_state(
        name_asked=True, age=40, sex="male", primary_sex_answered=True,
        residence_country="Greece", primary_healthcare_country_answered=True,
        nationality_answered=True, coverage_area="area1",
    )
    assert next_discovery_question(state)["key"] == "family_include"


def test_family_member_maternity_is_member_specific():
    state = family_state(
        name_asked=True, age=42, sex="male", primary_sex_answered=True,
        residence_country="Greece", primary_healthcare_country_answered=True,
        nationality_answered=True, coverage_area="area1",
        family_answered=True, family_requested=True,
        household_member_index=0,
        household_members=[{"member_id": "member-1", "relationship": "spouse", "age": 38, "sex": "female"}],
    )
    assert next_discovery_question(state)["key"] == "family_maternity"
