from backend.app.documents.carriers import get_carrier_adapter
from backend.app.documents.headline import analyze_quote_headlines
from backend.app.documents.plan_selector import identify_selected_plan


def test_adapter_registry_detects_supported_carriers():
    assert get_carrier_adapter("CIGNA").carrier_id == "cigna"
    assert get_carrier_adapter("IMG (International Medical Group)").carrier_id == "img"
    assert get_carrier_adapter("Bupa Global").carrier_id == "bupa"
    assert get_carrier_adapter("NOW Health International").carrier_id == "now_health"
    assert get_carrier_adapter("Unknown Carrier").carrier_id == "generic"


def test_explicit_selected_plan_is_locked_without_llm():
    result = identify_selected_plan("Selected plan: Executive\nAnnual premium EUR 5,000", "Cigna")
    assert result["plan_name"] == "Executive"
    assert result["confidence"] == "high"


def test_generic_quote_headlines_extract_price_deductible_and_area():
    text = """Bupa Global
Selected plan: Select
Annual premium EUR 4,250.00
Excess EUR 500
Area of cover Worldwide excluding USA
"""
    result = analyze_quote_headlines(text, provider_label="Bupa Global")
    analysis = result["analysis"]
    assert result["target_plan"] == "Select"
    assert analysis["premium"]["amount"] == "4250.00"
    assert "€500" in analysis["deductible_or_excess"]
    assert analysis["area_of_cover"] == "Worldwide excluding USA"
    assert analysis["carrier_adapter"]["carrier_id"] == "bupa"


def test_now_health_underwriting_basis_is_deterministic():
    text = """NOW Health International
Plan Selected: SimpleCare 250
Final Total Premium: EUR 1092.07
Underwriting Basis: Full Medical Underwriting
Coverage area Worldwide excluding USA
"""
    result = analyze_quote_headlines(text, provider_label="NOW Health International")
    assert result["target_plan"] == "SimpleCare 250"
    assert result["analysis"]["underwriting"]["basis"] == "Full Medical Underwriting"
