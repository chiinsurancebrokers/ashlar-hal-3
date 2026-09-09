from backend.app.knowledge.service import (
    greece_profile, greece_indicator, fairness_rules, international_vs_local,
    detect_hnwi, fairness_check,
)


def test_greece_satisfaction_figures_are_the_verified_2025_numbers():
    ind = greece_indicator("satisfaction")
    assert "27%" in ind["value"]
    assert "64%" in ind["comparator"]


def test_greece_unmet_needs_two_measures_have_distinct_denominators_documented():
    oecd = greece_indicator("unmet_needs_oecd")
    eu_profile = greece_indicator("unmet_needs_eu_profile")
    assert "12.1%" in oecd["value"]
    assert "21.9%" in eu_profile["value"]
    assert "denominator_note" in oecd
    assert "denominator_note" in eu_profile
    assert oecd["denominator_note"] != eu_profile["denominator_note"]


def test_out_of_pocket_has_a_caveat_against_overclaiming():
    ind = greece_indicator("out_of_pocket_share")
    assert "caveat" in ind
    assert "does not" in ind["caveat"].lower() or "not" in ind["caveat"].lower()


def test_fairness_rules_cover_the_required_prohibitions():
    rules = fairness_rules()
    joined = " ".join(rules["prohibited_claims"]).lower()
    assert "everyone needs" in joined
    assert "vitamins" in joined
    assert "fear-based" in joined
    assert len(rules["required_acknowledgements"]) >= 3


def test_international_vs_local_never_hardcodes_specific_benefit_figures():
    data = international_vs_local()
    rule_text = data["outpatient_first_argument"]["rule"]
    assert "evidence layer" in rule_text.lower()
    assert data["local_review_playbook"]["principle"]


def test_hnwi_detection_english_and_greek():
    assert detect_hnwi("Budget is secondary, I want the best hospitals available") is True
    assert detect_hnwi("θέλω τα καλύτερα νοσοκομεία") is True
    assert detect_hnwi("I just want a simple cheap plan") is False


def test_fairness_check_flags_prohibited_style_claims():
    flags = fairness_check("This plan covers all pre-existing conditions and is always better than local insurance.")
    assert len(flags) >= 2
    assert fairness_check("This plan offers broad outpatient cover, subject to policy terms.") == []
