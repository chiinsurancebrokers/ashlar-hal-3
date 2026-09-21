from backend.app.analysis.client_comparison import (
    build_comparison_matrix,
    build_grounded_case_payload,
    validate_client_report,
)
from backend.app.cases.models import AshlarCase, CaseClient
from backend.app.schemas.applicant import Applicant


def _results():
    return [
        {"provider": "Cigna", "target_plan": "Silver", "analysis": {
            "provider": "Cigna", "plan_name": "Silver",
            "premium": {"amount": "2389.83", "currency": "EUR", "frequency": "Annual"},
            "annual_limit": "€800,000", "deductible_or_excess": "€0", "area_of_cover": "Worldwide excluding USA",
            "underwriting": {"basis": "CPME", "pre_existing_conditions": "Subject to terms"},
            "benefits": {"inpatient": "Covered", "outpatient": "€12,000", "cancer": "Covered", "maternity": "€7,500"},
            "confidence": "high", "source_evidence": []}},
        {"provider": "IMG", "target_plan": "Gold", "analysis": {
            "provider": "IMG", "plan_name": "Gold",
            "premium": {"amount": "2100", "currency": "EUR", "frequency": "Annual"},
            "annual_limit": "€1,500,000", "deductible_or_excess": "€500", "area_of_cover": "Worldwide excluding USA",
            "underwriting": {"basis": "FMU", "pre_existing_conditions": "Subject to underwriting"},
            "benefits": {"inpatient": "Covered", "outpatient": "€8,000", "cancer": "Covered", "maternity": "Not covered"},
            "confidence": "high", "source_evidence": []}},
    ]


def test_matrix_is_deterministic_and_omits_irrelevant_maternity():
    case = AshlarCase(client=CaseClient(display_name="Client"), applicant=Applicant(age=45))
    matrix = build_comparison_matrix(_results(), case=case)
    topics = [row["topic"] for row in matrix]
    assert "Premium" in topics
    assert "Maternity" not in topics
    annual = next(row for row in matrix if row["topic"] == "Annual policy limit")
    assert annual["values"]["Cigna - Silver"] == "€800,000"
    assert annual["values"]["IMG - Gold"] == "€1,500,000"


def test_maternity_is_included_when_it_is_a_declared_must_have():
    case = AshlarCase(client=CaseClient(display_name="Client"), applicant=Applicant(age=35, maternity_required=True))
    topics = [row["topic"] for row in build_comparison_matrix(_results(), case=case)]
    assert "Maternity" in topics


def test_grounded_payload_does_not_copy_free_text_medical_note():
    case = AshlarCase(
        client=CaseClient(display_name="Client"),
        applicant=Applicant(age=45, chronic_conditions_disclosed=True, chronic_conditions_note="private medical detail"),
        needs_profile={"priority": "international treatment"},
    )
    payload = build_grounded_case_payload(case, _results())
    assert "private medical detail" not in str(payload)
    assert payload["applicant"]["medical_disclosure_flag"] is True


def test_report_validator_allows_genuine_tradeoff_without_forced_winner():
    report = {
        "report_title": "Comparison",
        "executive_summary": "Both plans meet the core brief with different trade-offs.",
        "plans": [
            {"provider": "Cigna", "plan_name": "Silver", "summary": "Strong fit.", "strengths": [], "considerations": []},
            {"provider": "IMG", "plan_name": "Gold", "summary": "Strong alternative.", "strengths": [], "considerations": []},
        ],
        "key_differences": [{"title": "Limits", "analysis": "Different limits", "client_impact": "Trade-off"}],
        "ashlar_assessment": {"recommended_provider": "", "recommended_plan": "", "headline": "Two credible fits", "reasoning": ["Each leads on a different priority."]},
        "important_considerations": [],
        "next_steps": ["Review the trade-off."],
        "disclaimer": "Subject to policy terms and underwriting.",
    }
    assert validate_client_report(report, _results()) is report
