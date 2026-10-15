"""What the client actually pays, and what the quoted figure leaves out.

Two things HAL used to get wrong about the headline premium:

  1. It showed a monthly figure as the annual premium divided by twelve.
     Morgan Price charges 8% to pay monthly, so for the Polat family the
     real instalment is EUR 324.72 and HAL would have said EUR 300.67 —
     EUR 288 a year of difference, discovered at proposal stage.

  2. It showed the premium as if it were the price. Every Morgan Price
     quote says "Taxes are not included in your quote", and for a French
     resident the plausible range runs from nothing to over 20%. HAL now
     says the figure is before tax and leaves the amount to the broker.
     It must never compute a rate.
"""
from __future__ import annotations

import pytest

from backend.app.core.config import Settings
from backend.app.schemas.applicant import Applicant, Dependent
from backend.app.rates.quote_engine import quote_current
from backend.app.rates.carriers import instalment_loading, premium_tax_treatment, policy_for


def _polat():
    applicant = Applicant(
        age=36, residence_country="France", coverage_area="area1",
        dependents=[Dependent(relationship="spouse", age=33),
                    Dependent(relationship="child", age=3)],
    )
    quotes = quote_current(applicant, Settings())
    return next(q for q in quotes if q.product_code == "standard_plus")


# The carrier's own quick-quote PDF, ref bcf5cc74, annual 3,608.04.
MORGAN_PRICE_SCHEDULE = {
    "monthly":     {"instalment": 324.72, "annual_total": 3896.68, "loading": 0.08},
    "quarterly":   {"instalment": 947.11, "annual_total": 3788.44, "loading": 0.05},
    "semi_annual": {"instalment": 1876.18, "annual_total": 3752.36, "loading": 0.04},
}


@pytest.mark.parametrize("frequency", sorted(MORGAN_PRICE_SCHEDULE))
def test_payment_schedule_matches_the_carrier_quote(frequency):
    option = next(o for o in _polat().payment_options if o["frequency"] == frequency)
    want = MORGAN_PRICE_SCHEDULE[frequency]
    assert option["instalment_amount"] == pytest.approx(want["instalment"], abs=0.01)
    assert option["annual_total"] == pytest.approx(want["annual_total"], abs=0.01)
    assert option["loading_pct"] == pytest.approx(want["loading"])


def test_paying_monthly_costs_more_than_the_annual_premium():
    """The whole point: twelve instalments are not the annual price."""
    quote = _polat()
    monthly = next(o for o in quote.payment_options if o["frequency"] == "monthly")
    assert monthly["annual_total"] > quote.premium
    assert monthly["instalment_amount"] > quote.premium / 12
    assert monthly["instalment_amount"] == pytest.approx(324.72, abs=0.01)
    assert round(quote.premium / 12, 2) == pytest.approx(300.67, abs=0.01)


def test_annual_payment_carries_the_flat_bank_transfer_fee():
    """The annual option has no percentage loading but a flat fee, so it is
    added rather than multiplied in."""
    quote = _polat()
    annual = next(o for o in quote.payment_options if o["frequency"] == "annual")
    assert annual["loading_pct"] == 0.0
    assert annual["annual_total"] == pytest.approx(quote.premium + 15, abs=0.01)
    assert annual["instalments_per_year"] == 1


def test_every_frequency_is_offered():
    options = {o["frequency"] for o in _polat().payment_options}
    assert options == {"monthly", "quarterly", "semi_annual", "annual"}


def test_a_carrier_with_no_recorded_fees_charges_none():
    """A carrier HAL holds no module for must not inherit Morgan Price's
    administration fee."""
    loading = instalment_loading("april")
    assert loading.has_loading is False
    schedule = loading.schedule(1200.0, "EUR")
    assert all(o["annual_total"] == 1200.0 for o in schedule)
    assert next(o for o in schedule if o["frequency"] == "monthly")["instalment_amount"] == 100.0


# ---------------------------------------------------------------------------
# Premium tax
# ---------------------------------------------------------------------------

def test_the_quote_says_it_is_before_tax():
    note = _polat().premium_tax_note
    assert note, "a premium quoted before tax must say so"
    assert "before insurance premium tax" in note
    assert "country of residence" in note
    assert "broker confirms" in note


def test_hal_never_states_a_tax_rate():
    """Rates depend on country and contract type, are in no rate workbook,
    and a table of guesses for forty countries would be wrong somewhere.
    Disclosure only — the number comes from the insurer."""
    note = _polat().premium_tax_note
    assert "%" not in note
    for rate in ("13.27", "20.27", "13,27", "20,27"):
        assert rate not in note


def test_tax_treatment_is_scoped_to_the_carrier():
    assert premium_tax_treatment("morgan_price").needs_disclosure is True
    assert premium_tax_treatment("april").needs_disclosure is False
    assert policy_for("april").tax.note_en == ""


def test_the_disclosure_is_available_in_greek():
    """HAL's Greek users see the same statement, not an English fallback."""
    tax = premium_tax_treatment("morgan_price")
    assert tax.note_el
    assert "φόρου ασφαλίστρων" in tax.note_el
    assert "διαμεσολαβητής" in tax.note_el


def test_the_frontend_carries_the_greek_translation_of_the_note():
    """The note is emitted by the backend in English and translated in the
    browser, so the exact string has to be in the dynamic dictionary."""
    from pathlib import Path
    html = Path(__file__).resolve().parents[1].joinpath("frontend/index.html").read_text(encoding="utf-8")
    note = premium_tax_treatment("morgan_price").note_en
    assert note in html, "the tax note has no Greek mapping in DYNAMIC_EL"
    assert "q-tax-note" in html


def test_the_card_shows_the_real_monthly_instalment():
    """Guards the rendering, not just the data: the card must read the
    monthly payment option rather than dividing the annual premium."""
    from pathlib import Path
    html = Path(__file__).resolve().parents[1].joinpath("frontend/index.html").read_text(encoding="utf-8")
    assert "payment_options||[]).find(o=>o.frequency==='monthly')" in html
    assert "const annual=Number(q.premium||0),monthly=annual/12" not in html
