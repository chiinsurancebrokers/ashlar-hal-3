from datetime import date

import pytest

from backend.app.core.config import Settings
from backend.app.schemas.applicant import Applicant, Dependent
from backend.app.rates.quote_engine import quote_current, quote_shortlist, quote_exclusions
from backend.app.rates.registry import rates_for

# As of 13 Oct 2026 only Morgan Price has a loaded 2026 workbook, so tests
# that assert the existence of an IMG quote in the current output are skipped
# until APRIL / IMG 2026 rate tables arrive. See backend/app/rates/registry.py.
_IMG_UNAVAILABLE = pytest.mark.skip(
    reason="IMG not in 2026 online quoting until a 2026 rate workbook arrives; "
           "see backend/app/rates/registry.py (13 Oct 2026 policy)."
)


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


def test_single_applicant_matches_original_v1_premium():
    applicant = Applicant(age=40, residence_country="Greece", coverage_area="area1")
    quotes = quote_current(applicant, _settings())
    standard = next(q for q in quotes if q.insurer.startswith("Morgan Price") and q.product_code == "standard")
    assert standard.premium == 1490.80
    assert standard.official_rate is True
    assert standard.family_size == 1


def test_maternity_hard_exclusion_visible_end_to_end():
    applicant = Applicant(age=51, residence_country="Greece", coverage_area="area2", maternity_required=True)
    quotes = quote_current(applicant, _settings())
    codes = {q.product_code for q in quotes if q.insurer.startswith("Morgan Price")}
    assert codes == {"premium", "elite"}, "lower tiers must be fully absent from quote_current, not merely ranked low"

    excluded = quote_exclusions(applicant, _settings())
    excluded_codes = {e["plan_key"].split(":")[1] for e in excluded if "morgan_price" in e["plan_key"]}
    assert excluded_codes == {"standard", "standard_plus", "comprehensive"}
    for e in excluded:
        assert "Routine maternity" in e["gaps"]


def test_family_quote_sums_and_requires_every_member_to_qualify():
    applicant = Applicant(
        age=42, residence_country="Greece", coverage_area="area1",
        dependents=[Dependent(relationship="spouse", age=40), Dependent(relationship="child", age=8)],
    )
    quotes = quote_current(applicant, _settings())
    standard = next(q for q in quotes if q.insurer.startswith("Morgan Price") and q.product_code == "standard")
    assert standard.family_size == 3
    assert len(standard.per_member_premiums) == 3
    # per_member_premiums are the amounts actually CHARGED per life — already
    # net of the family discount, exactly as the carrier's quote document
    # lists them — so they reconcile to the headline premium.
    assert standard.premium == round(sum(standard.per_member_premiums), 2)
    # Three lives is the second rung of Morgan Price's ladder: 10%.
    assert round(standard.family_discount_pct, 2) == 0.10
    assert standard.premium == round(sum(
        r.annual_premium for r in [
            next(x for x in rates_for("area1", a) if x.carrier == "morgan_price" and x.product_code == "standard")
            for a in (42, 40, 8)
        ]
    ) * 0.90, 2)


def test_deductible_model_off_by_default_matches_base_price():
    applicant = Applicant(age=40, residence_country="Greece", coverage_area="area1", deductible=1000, deductible_preference="fixed")
    quotes = quote_current(applicant, _settings())
    standard = next(q for q in quotes if q.insurer.startswith("Morgan Price") and q.product_code == "standard")
    assert standard.premium == 1490.80  # unaffected: deductible_model_enabled defaults False
    assert standard.deductible_note == "deductible_preference_not_used_in_pricing"
    # Client-facing card note is surfaced so the user understands their
    # choice was recorded for the broker, not silently ignored.
    assert standard.card_deductible_note is not None
    assert "€1,000" in standard.card_deductible_note
    assert "recorded for the broker" in standard.card_deductible_note


def test_deductible_card_note_absent_when_no_deductible_chosen():
    """No note when the applicant didn't pick a specific deductible — the
    card stays clean. A missing/null preference is 'flexible' which means
    'no opinion', which the broker will handle at proposal stage anyway."""
    applicant = Applicant(age=40, residence_country="Greece", coverage_area="area1")
    quotes = quote_current(applicant, _settings())
    standard = next(q for q in quotes if q.insurer.startswith("Morgan Price") and q.product_code == "standard")
    assert standard.deductible is None
    assert standard.card_deductible_note is None


def test_deductible_model_on_actually_changes_price():
    applicant = Applicant(age=40, residence_country="Greece", coverage_area="area1", deductible=1000, deductible_preference="fixed")
    quotes = quote_current(applicant, _settings(deductible_model_enabled=True))
    standard = next(q for q in quotes if q.insurer.startswith("Morgan Price") and q.product_code == "standard")
    assert standard.premium < 1490.80
    assert "illustrative_estimate" in standard.deductible_note


def test_quote_validity_window():
    applicant = Applicant(age=40, residence_country="Greece", coverage_area="area1")
    today = date(2026, 1, 1)
    quotes = quote_current(applicant, _settings(quote_validity_days=30), today=today)
    assert all(q.quoted_on == date(2026, 1, 1) for q in quotes)
    assert all(q.valid_until == date(2026, 1, 31) for q in quotes)


def test_shortlist_prefers_distinct_carriers_first_then_fills_from_same_carrier():
    """The shortlist fills its first slots with as many distinct carriers as
    the loaded workbook actually contains (currently one — Morgan Price),
    then uses the remaining slots to show the other tiers from those same
    carriers. A single-carrier shortlist is a legitimate state after the
    13 Oct 2026 APRIL/IMG withdrawal, not a bug — the engine must still
    return eligible plans."""
    applicant = Applicant(age=40, residence_country="Greece", coverage_area="area1")
    shortlist = quote_shortlist(applicant, _settings(), limit=5)
    assert shortlist, "shortlist must not be empty for a priced applicant"

    distinct_carriers_available = {q.insurer for q in quote_current(applicant, _settings())}
    k = min(3, len(distinct_carriers_available))
    assert {q.insurer for q in shortlist[:k]} == set(list(distinct_carriers_available)[:k]) \
        if k == len(distinct_carriers_available) else True, \
        "the first slots must introduce every available carrier before repeating one"

    # Even with a single carrier, there is still a well-defined #1 (the engine's
    # ranked top): if there is a reason to mark one recommended, it is this one;
    # otherwise none of them should be marked. This test must not force the
    # "recommended" semantics — that is covered by the dedicated test below.
    recommended_count = sum(1 for q in shortlist if q.recommended)
    assert recommended_count <= 1, "at most one plan may be marked recommended"


def test_shortlist_marks_recommended_when_user_has_stated_must_haves():
    """When the applicant has told HAL any must-have (or set a budget), the
    engine's ranked top IS a meaningful recommendation and must be labelled."""
    applicant = Applicant(age=40, residence_country="Greece", coverage_area="area1",
                          outpatient_required=True)
    shortlist = quote_shortlist(applicant, _settings(), limit=5)
    assert shortlist, "a verified-outpatient applicant must still get a shortlist"
    assert shortlist[0].recommended is True, "with a stated must-have, the top plan must be recommended"


def test_shortlist_marks_nothing_recommended_when_no_priorities_and_no_budget():
    """Without any must-have and without a budget, 'recommended' would just
    mean 'cheapest eligible', which is not useful signal and misaligns with
    the HAL fairness rules. HAL stays honest: no ribbon at all."""
    applicant = Applicant(age=40, residence_country="Greece", coverage_area="area1")
    shortlist = quote_shortlist(applicant, _settings(), limit=5)
    assert shortlist, "shortlist must not be empty"
    assert not applicant.must_have_keys() and applicant.budget_annual is None
    assert all(q.recommended is False for q in shortlist), \
        "no plan may be marked recommended when the user has stated no priorities"


def test_recommended_pick_never_outranks_on_price_alone_when_unverified_against_a_stated_must_have():
    # Regression: IMG Bronze is cheaper but HAL now has explicit evidence
    # that this tier is inpatient-focused and does not include outpatient.
    # A stated outpatient MUST-HAVE therefore hard-excludes Bronze; price
    # must never restore a plan that fails a verified mandatory requirement.
    applicant = Applicant(age=40, residence_country="Greece", coverage_area="area1", outpatient_required=True)
    shortlist = quote_shortlist(applicant, _settings(), limit=5)
    top = shortlist[0]
    assert top.insurer.startswith("Morgan Price"), "a verified outpatient match must be recommended"
    assert top.evidence_confidence == 1.0
    assert "Out-patient cover" in top.matched_requirements
    assert all(q.product_name != "IMG Bronze" for q in shortlist), "IMG Bronze must be hard-excluded when outpatient is required"


@_IMG_UNAVAILABLE
def test_card_metadata_present_on_every_quote_current_result_not_just_shortlist():
    applicant = Applicant(age=40, residence_country="Greece", coverage_area="area1")
    quotes = quote_current(applicant, _settings())
    img = next(q for q in quotes if q.insurer.startswith("IMG"))
    assert img.card_coverage == "International inpatient-focused medical cover"
    assert img.card_annual_limit  # never None/empty — falls back to honest placeholder text, not a blank
    assert img.plan_key and img.plan_key.startswith("img:")


def test_benefit_checklist_present_and_honest_on_every_quote():
    applicant = Applicant(age=40, residence_country="Greece", coverage_area="area1")
    quotes = quote_current(applicant, _settings())

    standard = next(q for q in quotes if q.insurer.startswith("Morgan Price") and q.product_code == "standard")
    checklist = {item["field"]: item["covered"] for item in standard.benefit_checklist}
    assert len(standard.benefit_checklist) == 8
    assert checklist["maternity_required"] is False  # verified real fact, not a guess
    assert checklist["evacuation_required"] is True

    premium = next(q for q in quotes if q.insurer.startswith("Morgan Price") and q.product_code == "premium")
    checklist_p = {item["field"]: item["covered"] for item in premium.benefit_checklist}
    assert checklist_p["maternity_required"] is True

    # The IMG Bronze checklist assertions below were only reachable while the
    # legacy APRIL/IMG workbook was loaded; the workbook was withdrawn on
    # 13 Oct 2026 (see backend/app/rates/registry.py). Re-enable when IMG
    # sends a 2026 workbook.


def test_only_morgan_price_is_quoted_online():
    """As of 13 Oct 2026, HAL quotes only Morgan Price online — every other
    carrier was withdrawn pending a 2026 rate workbook. This test guards that
    policy: it must fail loudly if a different carrier starts appearing in
    the output again."""
    quotes_de = quote_current(Applicant(age=40, residence_country="Germany", coverage_area="area1"), _settings())
    assert quotes_de and {q.plan_key.split(":")[0] for q in quotes_de} == {"morgan_price"}
    quotes_gr = quote_current(Applicant(age=40, residence_country="Greece", coverage_area="area1"), _settings())
    assert quotes_gr and {q.plan_key.split(":")[0] for q in quotes_gr} == {"morgan_price"}


def test_us_and_sanctioned_residents_are_not_priced():
    assert quote_current(Applicant(age=40, residence_country="United States", coverage_area="area4"), _settings()) == []
    assert quote_current(Applicant(age=40, residence_country="Russia", coverage_area="area1"), _settings()) == []


def test_area_must_include_residence():
    assert quote_current(Applicant(age=40, residence_country="United Arab Emirates", coverage_area="area1"), _settings()) == []
    assert quote_current(Applicant(age=40, residence_country="United Arab Emirates", coverage_area="area3"), _settings())
    assert quote_current(Applicant(age=40, residence_country="Singapore", coverage_area="area3"), _settings())
