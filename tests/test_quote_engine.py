from datetime import date

from backend.app.core.config import Settings
from backend.app.schemas.applicant import Applicant, Dependent
from backend.app.rates.quote_engine import quote_current, quote_shortlist, quote_exclusions


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
    assert standard.premium == round(sum(standard.per_member_premiums) * 0.95, 2)  # default 5% family discount


def test_deductible_model_off_by_default_matches_base_price():
    applicant = Applicant(age=40, residence_country="Greece", coverage_area="area1", deductible=1000, deductible_preference="fixed")
    quotes = quote_current(applicant, _settings())
    standard = next(q for q in quotes if q.insurer.startswith("Morgan Price") and q.product_code == "standard")
    assert standard.premium == 1490.80  # unaffected: deductible_model_enabled defaults False
    assert standard.deductible_note == "deductible_preference_not_used_in_pricing"


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


def test_shortlist_is_deduplicated_by_carrier_and_marks_recommended():
    applicant = Applicant(age=40, residence_country="Greece", coverage_area="area1")
    shortlist = quote_shortlist(applicant, _settings(), limit=5)
    assert shortlist[0].recommended is True
    carriers_in_top3 = {q.insurer for q in shortlist[:3]}
    assert len(carriers_in_top3) == len(shortlist[:3]), "first 3 shortlist entries must be from distinct carriers"


def test_recommended_pick_never_outranks_on_price_alone_when_unverified_against_a_stated_must_have():
    # Regression: a real reported bug — IMG Bronze (cheaper, but no loaded
    # Table of Benefits) was being shown as "HAL's top pick" even though
    # the applicant explicitly required outpatient cover, which IMG's fit
    # against is entirely unverified. A verified Morgan Price match must
    # always outrank an unverified-but-cheaper plan once a must-have is
    # stated — price alone must never win that comparison.
    applicant = Applicant(age=40, residence_country="Greece", coverage_area="area1", outpatient_required=True)
    shortlist = quote_shortlist(applicant, _settings(), limit=5)
    top = shortlist[0]
    assert top.insurer.startswith("Morgan Price"), "the verified match must be recommended, not the cheaper unverified IMG Bronze"
    assert top.evidence_confidence == 1.0
    assert "Out-patient cover" in top.matched_requirements

    img_bronze = next(q for q in shortlist if q.product_name == "IMG Bronze")
    assert img_bronze.premium < top.premium, "sanity check: IMG Bronze really is cheaper — the fix must still hold despite that"
    assert img_bronze.recommended is False


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

    img = next(q for q in quotes if q.insurer.startswith("IMG"))
    checklist_img = {item["field"]: item["covered"] for item in img.benefit_checklist}
    assert all(v is None for v in checklist_img.values()), "no TOB evidence for IMG -> every item must be honestly 'not confirmed', never guessed"


def test_unsupported_residence_returns_no_quotes():
    applicant = Applicant(age=40, residence_country="Germany", coverage_area="area1")
    assert quote_current(applicant, _settings()) == []
