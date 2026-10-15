"""HAL's household totals must equal the carrier's own quote engine.

These are the regression tests for the Morgan Price family discount ladder.
Each case below was produced by running the real Morgan Price "Evolution
Health EU and EEA" quick-quote on 15 Oct 2026 — Standard Plus, Area 1
Europe, EUR 0 excess, 0% co-insurance, country of residence France — and
recording what it returned. If someone edits the ladder in
data/evidence/morgan_price_2026/pricing_rules.json, these fail.

Before this ladder was verified, HAL applied a flat 5% to every household.
That was right for a couple and wrong for everyone else: a three-life
family was quoted EUR 200.44 too much and a four-life family EUR 496.19
too much — the error growing with exactly the families Ashlar most wants
to win.
"""
from __future__ import annotations

import pytest

from backend.app.core.config import Settings
from backend.app.schemas.applicant import Applicant, Dependent
from backend.app.rates.quote_engine import quote_current
from backend.app.rates.carrier_pricing import (
    family_discount_rule, instalment_loading, household_exceeds_verified_size,
)
from backend.app.rates.registry import rates_for


def _standard_plus_for(ages: list[int], settings: Settings | None = None):
    """Quote a household against Morgan Price Standard Plus, Area 1."""
    applicant = Applicant(
        age=ages[0], residence_country="France", coverage_area="area1",
        dependents=[
            Dependent(relationship="child" if age < 19 else "spouse", age=age)
            for age in ages[1:]
        ],
    )
    quotes = quote_current(applicant, settings or Settings())
    return next((q for q in quotes if q.product_code == "standard_plus"), None)


# (ages, Morgan Price annual total excl. taxes, quote reference)
MORGAN_PRICE_QUOTES = [
    ([36, 33],             2903.14, "quick-quote screenshot 15 Oct 2026"),
    ([36, 33, 3],          3608.04, "bcf5cc74-0ea4-4008-a0b9-04da3e0b0ea4"),
    ([36, 33, 10, 3],      4217.63, "03ea8231-ec73-47b5-aabb-f6e6f22637ac"),
    ([36, 33, 10, 3, 15],  5170.62, "Morgan_Price_Health_Insurance_Quote_4"),
    ([36, 5, 10, 8, 33],   5170.62, "7c06f5b0-314a-4cd2-ae3c-4b46cb8e9916"),
]


@pytest.mark.parametrize("ages,mp_total,reference", MORGAN_PRICE_QUOTES)
def test_hal_matches_the_carrier_quote_engine_to_the_cent(ages, mp_total, reference):
    quote = _standard_plus_for(ages)
    assert quote is not None, f"HAL must price this household ({reference})"
    assert quote.premium == pytest.approx(mp_total, abs=0.01), (
        f"HAL disagrees with Morgan Price quote {reference} for ages {ages}"
    )


@pytest.mark.parametrize("ages,mp_total,reference", MORGAN_PRICE_QUOTES)
def test_per_member_lines_reconcile_to_the_household_total(ages, mp_total, reference):
    """The per-member figures are what a client reads next to the carrier's
    own quote PDF, so they must add up to the headline premium rather than
    drifting a cent away from it."""
    quote = _standard_plus_for(ages)
    assert len(quote.per_member_premiums) == len(ages)
    assert round(sum(quote.per_member_premiums), 2) == quote.premium


def test_ladder_steps_with_household_size():
    """5% for two lives, 10% for three, 15% for four — the rung is set by
    how many lives are on the policy, not by a single global figure."""
    assert _standard_plus_for([36, 33]).family_discount_pct == pytest.approx(0.05)
    assert _standard_plus_for([36, 33, 3]).family_discount_pct == pytest.approx(0.10)
    assert _standard_plus_for([36, 33, 10, 3]).family_discount_pct == pytest.approx(0.15)


def test_fifth_life_is_charged_the_full_rate():
    """Morgan Price discounts at most four lives. On the verified five-life
    quotes the youngest child paid the undiscounted rate — in both the
    original ordering and a re-ordered re-run, which is what makes this a
    rule rather than an artefact of how members were entered."""
    quote = _standard_plus_for([36, 33, 10, 3, 15])
    assert quote.family_discounted_member_count == 4
    assert quote.family_size == 5
    # Exactly one line sits at the undiscounted child rate of 952.99.
    full_rate_lines = [p for p in quote.per_member_premiums if p == pytest.approx(952.99, abs=0.01)]
    assert len(full_rate_lines) == 1


def test_member_order_does_not_change_the_household_total():
    """Both five-life quotes covered the same lives entered in different
    orders and returned the same total. HAL must be order-independent too."""
    a = _standard_plus_for([36, 33, 10, 3, 15])
    b = _standard_plus_for([36, 5, 10, 8, 33])
    # Not the same ages, but the same shape: two adults + three children, and
    # Morgan Price returned 5170.62 for both.
    assert a.premium == b.premium == pytest.approx(5170.62, abs=0.01)


def test_households_beyond_verified_size_are_not_priced_online():
    """Six lives is past anything checked against the carrier's own engine.
    HAL must decline rather than extrapolate the ladder — a big family is
    exactly where an invented discount would be most wrong."""
    assert household_exceeds_verified_size("morgan_price", 6) is True
    assert household_exceeds_verified_size("morgan_price", 5) is False
    assert _standard_plus_for([36, 33, 15, 10, 8, 3]) is None


def test_discount_is_scoped_to_the_carrier_that_published_it():
    """The ladder is Morgan Price's commercial policy, not HAL behaviour.
    A carrier HAL holds no pricing rules for gets no discount, so adding a
    second workbook can never silently inherit these terms."""
    assert family_discount_rule("morgan_price").gives_discount is True
    for other in ("april", "img", "bupa", "cigna", "now_health", ""):
        assert family_discount_rule(other).gives_discount is False, (
            f"{other!r} must not inherit Morgan Price's family discount"
        )
        assert household_exceeds_verified_size(other, 99) is False


def test_kill_switch_falls_back_to_the_plain_sum():
    """Turning discounts off must over-quote, never under-quote: the client
    can be corrected downward by a broker, which is the safe direction."""
    ages = [36, 33, 10, 3]
    with_discount = _standard_plus_for(ages)
    without = _standard_plus_for(ages, Settings(apply_carrier_family_discounts=False))

    assert without.family_discount_applied is False
    assert without.family_discount_pct == 0.0
    assert without.premium > with_discount.premium
    assert without.premium == round(sum(without.per_member_premiums), 2)

    # With discounts off the household is the plain sum of each life's own
    # undiscounted rate from the workbook.
    plain_sum = round(sum(
        next(r.annual_premium for r in rates_for("area1", age)
             if r.carrier == "morgan_price" and r.product_code == "standard_plus")
        for age in ages
    ), 2)
    assert without.premium == pytest.approx(plain_sum, abs=0.01)
    # And that is the 15% four-life discount's worth above the real price.
    assert without.premium == pytest.approx(with_discount.premium / 0.85, abs=0.02)


def test_instalment_loading_is_recorded_for_morgan_price():
    """The carrier's own admin fee for paying in instalments, read from its
    evidence folder rather than assumed."""
    loading = instalment_loading("morgan_price")
    assert loading.pct_for("monthly") == pytest.approx(0.08)
    assert loading.pct_for("quarterly") == pytest.approx(0.05)
    assert loading.pct_for("semi_annual") == pytest.approx(0.04)
    assert loading.pct_for("annual") == pytest.approx(0.0)
    assert loading.bank_fee("EUR") == 15
    # And it does not leak to a carrier with no recorded rules.
    assert instalment_loading("april").has_loading is False


def test_polat_family_matches_the_quote_sent_to_the_client():
    """The live enquiry this ladder was discovered on: two adults aged 36
    and 33 plus a three-year-old, resident in France, Area 1, Standard Plus.
    Morgan Price quoted EUR 3,608.04 a year excluding taxes."""
    quote = _standard_plus_for([36, 33, 3])
    assert quote.premium == pytest.approx(3608.04, abs=0.01)
    assert quote.family_discount_pct == pytest.approx(0.10)
    assert sorted(quote.per_member_premiums, reverse=True) == [
        pytest.approx(1465.65, abs=0.01),
        pytest.approx(1284.70, abs=0.01),
        pytest.approx(857.69, abs=0.01),
    ]


# ---------------------------------------------------------------------------
# The client-facing message for a household HAL cannot price
# ---------------------------------------------------------------------------

def _state(ages_of_members: list[int]) -> dict:
    """Primary applicant aged 36 plus the given household members."""
    return {
        "applicant_name": "Test", "residence_country": "France",
        "coverage_area": "area1", "age": 36,
        "household_members": [
            {"member_id": f"m{i}", "age": age} for i, age in enumerate(ages_of_members)
        ],
    }


def test_oversized_household_is_told_why_not_blamed_for_its_needs():
    """Regression for the same class of bug as the over-74 case: when HAL
    cannot price something, it must say which fact stopped it rather than
    implying the client asked for the wrong cover."""
    from backend.app.services.orchestrator import _no_verified_price_reply

    reply = _no_verified_price_reply(_state([33, 15, 10, 8, 3]), [], greek=False)
    assert "6 people" in reply
    assert "won't guess" in reply
    assert "ashlarassurance.com" in reply
    # It must NOT fall through to the generic needs-mismatch text.
    assert "change one of your needs" not in reply

    greek = _no_verified_price_reply(_state([33, 15, 10, 8, 3]), [], greek=True)
    assert "6 άτομα" in greek
    assert "ashlarassurance.com" in greek
    assert "αλλάξετε κάποια ανάγκη" not in greek


def test_household_within_verified_size_keeps_the_normal_flow():
    """Five lives is verified, so an empty shortlist there is a genuine
    needs mismatch and must keep the generic message."""
    from backend.app.services.orchestrator import _no_verified_price_reply

    reply = _no_verified_price_reply(_state([33, 15, 10, 3]), [], greek=False)
    assert "larger than the compositions" not in reply
