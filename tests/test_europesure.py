from backend.app.travel.europesure import destination_scope, recommend_tier, public_catalog, looks_like_long_stay


def test_destination_scope_classification():
    assert destination_scope("Italy") == "europe"
    assert destination_scope("USA") == "usa"
    assert destination_scope("Thailand and Australia") == "worldwide"
    assert destination_scope(">>>>>>>>") == "worldwide"  # garbage never reaches here — filtered upstream in discovery


def test_age_over_legacy_max_is_ineligible_with_clear_note():
    result = recommend_tier({"travel_age": 85, "travel_destination_scope": "europe"})
    assert result["eligible_on_legacy_data"] is False
    assert "79" in result["eligibility_note"]


def test_budget_preference_in_europe_picks_silver():
    result = recommend_tier({"travel_cover_preference": "budget", "travel_destination_scope": "europe"})
    assert result["tier"] == "silver"


def test_worldwide_defaults_to_platinum():
    result = recommend_tier({"travel_destination_scope": "worldwide"})
    assert result["tier"] == "platinum"


def test_no_signal_defaults_to_gold_balanced():
    result = recommend_tier({})
    assert result["tier"] == "gold"


def test_result_always_carries_verification_status_and_portal():
    result = recommend_tier({"travel_destination_scope": "europe"})
    assert result["current_terms_confirmed"] is False
    assert result["portal_url"].startswith("https://")


def test_public_catalog_has_all_three_tiers_with_real_legacy_limits():
    catalog = public_catalog()
    tiers = {p["tier"]: p for p in catalog["plans"]}
    assert tiers["silver"]["emergency_medical"] == "€1,000,000"
    assert tiers["gold"]["emergency_medical"] == "€3,500,000"
    assert tiers["platinum"]["emergency_medical"] == "€10,000,000"


def test_long_stay_detection():
    assert looks_like_long_stay("I'm moving to Germany") is True
    assert looks_like_long_stay("relocating for work") is True
    assert looks_like_long_stay("staying for 200 days") is True
    assert looks_like_long_stay("staying for 8 months") is True
    assert looks_like_long_stay("a one year trip") is True
    assert looks_like_long_stay("a two week holiday") is False
