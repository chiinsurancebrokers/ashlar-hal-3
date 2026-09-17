import pytest

from backend.app.proposals.report_schema import ClientReportValidationError, validate_client_report


def _results():
    return [
        {"analysis": {"provider": "Carrier A", "plan_name": "Alpha"}},
        {"analysis": {"provider": "Carrier B", "plan_name": "Beta"}},
    ]


def _report():
    return {
        "report_title": "Comparison",
        "executive_summary": "Two verified options have different trade-offs.",
        "client_needs_summary": "Strong cover",
        "plans": [
            {"provider": "Carrier A", "plan_name": "Alpha", "summary": "Alpha summary"},
            {"provider": "Carrier B", "plan_name": "Beta", "summary": "Beta summary"},
        ],
        "key_differences": [
            {
                "title": "Trade-off",
                "analysis": "Different strengths",
                "client_impact": "Choice depends on priority",
            }
        ],
        "ashlar_assessment": {
            "recommended_provider": "",
            "recommended_plan": "",
            "headline": "Genuine trade-off",
            "reasoning": ["Both options satisfy the main requirements in different ways."],
        },
        "important_considerations": [],
        "next_steps": ["Review the trade-off."],
        "disclaimer": "Subject to insurer terms.",
    }


def test_schema_allows_genuine_tradeoff_without_fake_winner():
    report = _report()
    assert validate_client_report(report, _results()) is report


def test_schema_rejects_half_recommendation():
    report = _report()
    report["ashlar_assessment"]["recommended_provider"] = "Carrier A"
    with pytest.raises(ClientReportValidationError):
        validate_client_report(report, _results())
