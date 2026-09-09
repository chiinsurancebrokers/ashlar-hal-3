from backend.app.rates.deductible_model import apply_deductible
from backend.app.rates.family_pricing import price_family
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

    quote = price_family([standard_adult.annual_premium, standard_child.annual_premium], family_discount_pct=0.05)
    assert quote.subtotal == round(standard_adult.annual_premium + standard_child.annual_premium, 2)
    assert quote.discount_applied is True
    assert quote.total == round(quote.subtotal * 0.95, 2)


def test_family_pricing_single_member_no_discount():
    quote = price_family([1490.80], family_discount_pct=0.05)
    assert quote.discount_applied is False
    assert quote.total == quote.subtotal
