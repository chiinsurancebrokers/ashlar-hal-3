"""A quote for a policy the insurer would refuse to issue is worth nothing.

Morgan Price, EU/EVO/SI/PW/04/26 page 5, "Who can apply?":

    "We offer cover exclusively for children between the age of 10 and 17
     without any parent or guardian being covered under the policy. A
     compulsory excess applies to these policies of $/EUR/GBP 100 per claim
     ... Any children under the age of 10 have to have an adult covered on
     the policy."

Before this was encoded, HAL happily quoted a standalone policy for a
newborn, a five-year-old and a nine-year-old at the full Child rate. The
rate table matches those ages perfectly, so nothing looked wrong — the
client would have applied and been declined.
"""
from __future__ import annotations

import pytest

from backend.app.core.config import Settings
from backend.app.schemas.applicant import Applicant
from backend.app.rates.quote_engine import quote_current
from backend.app.rates.carriers import policy_issuance_rule, carrier_will_not_issue
from backend.app.services.orchestrator import _no_verified_price_reply


def _solo(age: int):
    quotes = quote_current(
        Applicant(age=age, residence_country="France", coverage_area="area1"), Settings()
    )
    return next((q for q in quotes if q.product_code == "standard_plus"), None)


def _state(age: int) -> dict:
    return {"applicant_name": "Test", "residence_country": "France",
            "coverage_area": "area1", "age": age}


@pytest.mark.parametrize("age", [0, 1, 5, 8, 9])
def test_a_child_under_ten_is_not_quoted_a_policy_of_their_own(age):
    assert _solo(age) is None, f"age {age} needs an adult on the policy"
    assert carrier_will_not_issue("morgan_price", [age]) is True


@pytest.mark.parametrize("age", [10, 12, 15, 17])
def test_children_ten_to_seventeen_may_hold_their_own_policy(age):
    quote = _solo(age)
    assert quote is not None
    assert quote.child_only_policy is True
    assert carrier_will_not_issue("morgan_price", [age]) is False


@pytest.mark.parametrize("age", [10, 12, 17])
def test_the_compulsory_excess_is_shown_not_discovered_later(age):
    """The excess is a term of the cover, not something the client chose,
    so it has to appear on the card rather than on the certificate."""
    quote = _solo(age)
    assert quote.compulsory_excess_per_claim == 100
    assert "100" in quote.card_deductible
    assert "compulsory" in quote.card_deductible.lower()


@pytest.mark.parametrize("age", [18, 19, 20, 40])
def test_adults_and_school_leavers_are_not_tagged_as_child_only(age):
    quote = _solo(age)
    assert quote is not None
    assert quote.child_only_policy is False
    assert quote.compulsory_excess_per_claim is None


def test_a_young_child_with_a_parent_on_the_policy_is_quoted_normally():
    """The rule is about who is ON the policy, not the child's age alone."""
    from backend.app.schemas.applicant import Dependent
    quotes = quote_current(
        Applicant(age=36, residence_country="France", coverage_area="area1",
                  dependents=[Dependent(relationship="child", age=3)]),
        Settings(),
    )
    assert any(q.product_code == "standard_plus" for q in quotes)


def test_the_lone_child_is_told_how_to_fix_it_not_sent_to_a_form():
    """This one is in the client's hands — adding a parent produces a quote
    immediately — so HAL asks for that instead of routing to a broker."""
    reply = _no_verified_price_reply(_state(5), [], greek=False)
    assert "aged 5" in reply
    assert "adult to be covered on the same policy" in reply
    assert "Add a parent or guardian" in reply
    assert "change one of your needs" not in reply

    greek = _no_verified_price_reply(_state(5), [], greek=True)
    assert "5 ετών" in greek
    assert "γονέα ή κηδεμόνα" in greek
    assert "αλλάξετε κάποια ανάγκη" not in greek


def test_the_issuance_rule_is_scoped_to_the_carrier_that_published_it():
    assert policy_issuance_rule("morgan_price").has_child_rules is True
    for other in ("april", "img", "bupa", ""):
        assert policy_issuance_rule(other).has_child_rules is False
        assert carrier_will_not_issue(other, [3]) is False


def test_entry_age_limits_are_recorded_from_the_wording():
    """Kept on the carrier's own module so the next person does not have to
    re-read EU/EVO/SI/PW/04/26 page 5 to check them."""
    rule = policy_issuance_rule("morgan_price")
    assert rule.max_entry_age_fmu == 74
    assert rule.max_entry_age_moratorium == 55
    assert rule.child_only_min_age == 10
    assert rule.child_only_max_age == 17
    assert rule.compulsory_excess("EUR") == 100
    assert rule.compulsory_excess("GBP") == 100


def test_an_eighteen_year_old_may_hold_a_policy_alone():
    """Confirmed by Chris on 15 Oct 2026. They price on the 0-19 Child band
    but are not a child-only policy, so no compulsory excess applies."""
    quote = _solo(18)
    assert quote is not None
    assert quote.child_only_policy is False
    assert quote.compulsory_excess_per_claim is None


def test_household_members_are_not_mistaken_for_standalone_child_policies():
    """Regression: the household flows price each member on their own to
    build a per-member breakdown. That internal step must not trip the
    child-only rule — a three-year-old priced that way still ends up on a
    policy with a parent, and blocking it broke every family saved quote."""
    from backend.app.rates.quote_engine import quote_shortlist

    toddler = Applicant(age=3, residence_country="France", coverage_area="area1")
    assert quote_shortlist(toddler, Settings(), standalone_policy=True) == []
    assert quote_shortlist(toddler, Settings(), standalone_policy=False), (
        "a household member must still be priceable individually"
    )


def test_a_household_member_does_not_pick_up_the_child_only_excess():
    """The compulsory excess belongs to a policy a child holds alone. A
    child on a parent's policy must not show it."""
    from backend.app.rates.quote_engine import quote_current

    member = quote_current(
        Applicant(age=12, residence_country="France", coverage_area="area1"),
        Settings(), standalone_policy=False,
    )
    twelve = next(q for q in member if q.product_code == "standard_plus")
    assert twelve.child_only_policy is False
    assert twelve.compulsory_excess_per_claim is None
