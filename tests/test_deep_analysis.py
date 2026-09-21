from backend.app.documents.deep_analysis import apply_deterministic_evidence, prepare_deep_analysis


def test_deterministic_silver_table_overrides_model_gold_leakage():
    focused = """TARGET PLAN TABLE EVIDENCE — Silver
[Page 4] Annual overall benefit maximum => €800,000
[Page 5] Annual International Outpatient benefit maximum => €12,000
[Page 6] Extensive Cancer Care => Covered (table checkmark)
[Page 7] Advanced Medical Imaging => €4,000
"""
    model = {
        "provider": "Cigna",
        "plan_name": "Silver",
        "premium": {"amount": None, "currency": None, "frequency": None},
        "annual_limit": "€2,000,000",
        "deductible_or_excess": "Not specified",
        "area_of_cover": "Not specified",
        "underwriting": {},
        "benefits": {"outpatient": "€25,000"},
        "source_evidence": [],
        "confidence": "medium",
    }
    result = apply_deterministic_evidence(
        model,
        provider_label="Cigna",
        target_plan="Silver",
        focused_table_context=focused,
    )
    assert result["annual_limit"] == "€800,000"
    assert "€12,000" in result["benefits"]["outpatient"]
    assert "€4,000" in result["benefits"]["diagnostics_imaging"]
    assert "€2,000,000" not in str(result)


def test_applicant_quote_has_priority_over_generic_model_values():
    quote = """CIGNA
Quote 1 Silver EUR 2389.83 indicative per year
EUR 0 deductible and 0% cost share
USA Cover: Not selected
"""
    model = {
        "premium": {"amount": "9999", "currency": "EUR", "frequency": "Annual"},
        "deductible_or_excess": "€500",
        "area_of_cover": "Worldwide including USA",
        "underwriting": {},
        "benefits": {},
    }
    result = apply_deterministic_evidence(
        model,
        provider_label="Cigna",
        target_plan="Silver",
        quotation_text=quote,
    )
    assert result["premium"]["amount"] == "2389.83"
    assert result["area_of_cover"] == "Worldwide excluding USA"
    assert "€0" in result["deductible_or_excess"]


def test_prepare_deep_analysis_uses_only_isolated_rows_for_deterministic_facts():
    focused = """TARGET PLAN TABLE EVIDENCE — Silver
This evidence was isolated geometrically from the selected plan column.
Do not use values from neighbouring plan columns.
[Page 1] Annual overall benefit maximum => €800,000
"""
    envelope = prepare_deep_analysis(
        provider_label="Cigna",
        target_plan="Silver",
        brochure_text="Silver €800,000 Gold €2,000,000 Platinum €3,000,000",
        focused_table_context=focused,
        model_result={"benefits": {}, "underwriting": {}, "premium": {}},
    )
    assert envelope["target_plan"] == "Silver"
    assert envelope["focused_rows"] == [
        {"page": 1, "benefit": "Annual overall benefit maximum", "value": "€800,000"}
    ]
    assert envelope["analysis"]["annual_limit"] == "€800,000"
    assert "TARGET PLAN: Silver" in envelope["analysis_prompt"]
