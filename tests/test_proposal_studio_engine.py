from backend.app.cases.models import AshlarCase, CaseClient, CaseDocument
from backend.app.schemas.applicant import Applicant
from backend.app.proposals.engine import generate_case_proposal


def _result(provider: str, plan: str, premium: float, annual: str, outpatient: str):
    return {
        "provider": provider,
        "target_plan": plan,
        "analysis": {
            "provider": provider,
            "plan_name": plan,
            "premium": {"amount": premium, "currency": "EUR", "frequency": "annual"},
            "annual_limit": annual,
            "deductible_or_excess": "EUR 500",
            "area_of_cover": "Worldwide excluding USA",
            "underwriting": {"basis": "FMU", "pre_existing_conditions": "Subject to underwriting"},
            "benefits": {
                "inpatient": "Covered in full",
                "outpatient": outpatient,
                "cancer": "Covered in full",
                "chronic_conditions": "Covered subject to terms",
                "mental_health": "EUR 2,000",
                "evacuation_repatriation": "Covered",
                "diagnostics_imaging": "Covered",
            },
            "waiting_periods": [],
            "optional_benefits": [],
            "critical_limitations": [],
            "confidence": "high",
            "source_evidence": [],
        },
    }


def test_proposal_studio_generates_pdf_pptx_and_updates_case(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    case = AshlarCase(
        client=CaseClient(display_name="Test Client", preferred_language="en"),
        applicant=Applicant(age=51, residence_country="Greece", outpatient_required=True),
        needs_profile={"client_priorities": "Strong in-patient and out-patient cover."},
        documents=[
            CaseDocument(
                filename="quote.pdf",
                document_type="quote",
                provider="Carrier A",
                plan_key="carrier_a:alpha",
            )
        ],
    )
    results = [
        _result("Carrier A", "Alpha", 5000, "EUR 1,000,000", "EUR 10,000"),
        _result("Carrier B", "Beta", 4600, "EUR 2,000,000", "EUR 7,500"),
    ]
    bundle = generate_case_proposal(case=case, results=results)
    assert bundle.pdf_bytes.startswith(b"%PDF")
    assert bundle.pptx_bytes.startswith(b"PK")
    assert bundle.quality["can_generate"] is True
    assert case.proposal["engine"] == "ashlar_proposal_studio"
    assert case.proposal["formats"] == ["pdf", "pptx"]
    assert case.recommendation["recommended_provider"] == ""
    assert case.recommendation["recommended_plan"] == ""
    assert "comparison_matrix" in bundle.report


def test_proposal_studio_does_not_leak_medical_free_text(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    case = AshlarCase(
        client=CaseClient(display_name="Medical Privacy Test", preferred_language="en"),
        applicant=Applicant(
            age=50,
            residence_country="Greece",
            chronic_conditions_disclosed=True,
            chronic_conditions_note="PRIVATE MEDICAL DETAIL MUST NOT APPEAR",
        ),
    )
    bundle = generate_case_proposal(
        case=case,
        results=[_result("Carrier A", "Alpha", 5000, "EUR 1,000,000", "EUR 10,000")],
    )
    serialized = str(bundle.report)
    assert "PRIVATE MEDICAL DETAIL MUST NOT APPEAR" not in serialized
