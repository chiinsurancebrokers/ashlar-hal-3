from backend.app.rates.deductible_model import apply_deductible
from backend.app.rates.family_pricing import price_family
from backend.app.rates.carriers import family_discount_rule
from backend.app.rates.registry import rates_for


def test_deductible_disabled_returns_base_untouched():
    price, note = apply_deductible(1490.80, 1000, "fixed", enabled=False)
    assert price == 1490.80
    assert "not_used" in note


def test_deductible_flexible_preference_no_adjustment():
    price, note = apply_deductible(1490.80, None, "flexible", enabled=True)
    assert price == 1490.80
    assert "no_fixed_deductible" in note


def test_deductible_enabled_applies_labelled_discount():
    price, note = apply_deductible(1490.80, 1000, "fixed", enabled=True)
    assert price < 1490.80
    assert price == round(1490.80 * 0.89, 2)
    assert "illustrative_estimate" in note
    assert "pending_carrier_confirmation" in note


def test_family_pricing_sums_real_morgan_price_premiums():
    # Real age40 area1 standard premium from the loaded CSV.
    adult_rows = rates_for("area1", 40)
    child_rows = rates_for("area1", 8)
    standard_adult = next(r for r in adult_rows if r.carrier == "morgan_price" and r.product_code == "standard")
    standard_child = next(r for r in child_rows if r.carrier == "morgan_price" and r.product_code == "standard")

    quote = price_family(
        [standard_adult.annual_premium, standard_child.annual_premium],
        rule=family_discount_rule("morgan_price"),
    )
    assert quote.subtotal == round(standard_adult.annual_premium + standard_child.annual_premium, 2)
    assert quote.discount_applied is True
    # Two lives is the first rung of Morgan Price's ladder: 5%.
    assert quote.discount_pct == 0.05
    assert quote.total == round(quote.subtotal * 0.95, 2)


def test_family_pricing_single_member_no_discount():
    quote = price_family([1490.80], rule=family_discount_rule("morgan_price"))
    assert quote.discount_applied is False
    assert quote.total == quote.subtotal


def test_carrier_without_recorded_rules_gets_no_family_discount():
    """A family discount is an insurer's own commercial policy. HAL must not
    lend one carrier's ladder to another — a carrier we hold no pricing
    rules for is quoted at the plain sum of its members, which is always
    safe (too high, never too low)."""
    unknown = family_discount_rule("a_carrier_we_have_no_rules_for")
    assert unknown.gives_discount is False
    quote = price_family([1000.0, 800.0, 600.0], rule=unknown)
    assert quote.discount_applied is False
    assert quote.discount_pct == 0.0
    assert quote.total == quote.subtotal == 2400.0


def test_morgan_price_ladder_steps_and_caps():
    """2 -> 5%, 3 -> 10%, 4 -> 15%, and it does NOT keep climbing."""
    rule = family_discount_rule("morgan_price")
    assert rule.pct_for(1) == 0.0
    assert rule.pct_for(2) == 0.05
    assert round(rule.pct_for(3), 2) == 0.10
    assert round(rule.pct_for(4), 2) == 0.15
    assert round(rule.pct_for(5), 2) == 0.15
    assert round(rule.pct_for(9), 2) == 0.15


def test_morgan_price_discounts_at_most_four_lives():
    """On a five-life household Morgan Price charges one member the full
    rate. Verified against two quick-quotes of the same five lives entered
    in different orders (refs in carriers/morgan_price.py) — both left the
    youngest child undiscounted, so this is a rule, not an input artefact."""
    rule = family_discount_rule("morgan_price")
    adult, child = 1628.496248580948, 952.9913222904327
    quote = price_family(
        [adult, 1427.4408880949916, child, child, child],
        rule=rule,
        member_ages=[36, 33, 10, 3, 15],
    )
    assert quote.discounted_member_count == 4
    # The youngest child (index 3, age 3) keeps the undiscounted rate.
    assert quote.per_member_premiums[3] == round(child, 2)
    assert quote.total == 5170.62
