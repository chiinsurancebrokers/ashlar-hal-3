from backend.app.services.family_household_agent import HouseholdMember, assess_household, maternity_relevant


def member(member_id, relationship, age, sex="unspecified"):
    return HouseholdMember(member_id=member_id, relationship=relationship, age=age, sex=sex)


def test_single_applicant_stays_individual():
    result = assess_household(member("primary", "primary", 40, "male"), [])
    assert result.household_size == 1
    assert result.family_requested is False
    assert result.pricing_mode == "individual"


def test_family_requires_verified_family_rating():
    result = assess_household(
        member("primary", "primary", 42, "male"),
        [member("spouse", "spouse", 38, "female"), member("child-1", "child", 8)],
    )
    assert result.household_size == 3
    assert result.family_requested is True
    assert result.pricing_mode == "family_requires_verified_rating"
    assert result.maternity_member_ids == ["spouse"]


def test_maternity_relevance_is_member_specific_and_inclusive_18_to_47():
    assert maternity_relevant(member("a", "spouse", 18, "female")) is True
    assert maternity_relevant(member("b", "spouse", 47, "female")) is True
    assert maternity_relevant(member("c", "child", 17, "female")) is False
    assert maternity_relevant(member("d", "spouse", 48, "female")) is False
    assert maternity_relevant(member("e", "spouse", 35, "male")) is False
    assert maternity_relevant(member("f", "spouse", 35, "unspecified")) is False


def test_primary_female_can_be_maternity_relevant_in_family_or_single_flow():
    result = assess_household(member("primary", "primary", 32, "female"), [])
    assert result.maternity_member_ids == ["primary"]
