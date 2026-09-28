from backend.app.cases.models import AshlarCase, CaseClient, CaseDocument
from backend.app.schemas.applicant import Applicant
from backend.app.documents.orchestrator import analyze_and_apply_document_bundle


def test_deep_document_run_commits_only_corrected_target_plan_fact():
    case = AshlarCase(
        client=CaseClient(display_name="Test Client"),
        applicant=Applicant(age=45, residence_country="Greece"),
    )
    document = CaseDocument(
        filename="cigna_silver_brochure.pdf",
        document_type="brochure",
        provider="Cigna",
        plan_key="cigna:silver",
    )
    focused = """TARGET PLAN TABLE EVIDENCE — Silver
[Page 3] Annual overall benefit maximum => €800,000
[Page 4] Annual International Outpatient benefit maximum => €12,000
"""
    wrong_model = {
        "provider": "Cigna",
        "plan_name": "Silver",
        "premium": {"amount": "2500", "currency": "EUR", "frequency": "Annual"},
        "annual_limit": "€2,000,000",
        "deductible_or_excess": "€0",
        "area_of_cover": "Worldwide excluding USA",
        "underwriting": {"basis": "CPME", "pre_existing_conditions": "Subject to terms"},
        "benefits": {"inpatient": "Covered", "outpatient": "€25,000", "cancer": "Covered"},
        "confidence": "medium",
    }
    run = analyze_and_apply_document_bundle(
        case,
        document=document,
        provider_label="Cigna",
        target_plan="Silver",
        focused_table_context=focused,
        model_result=wrong_model,
        plan_key="cigna:silver",
    )

    annual = [fact for fact in run.case.facts if fact.key == "annual_limit"]
    outpatient = [fact for fact in run.case.facts if fact.key == "benefit.outpatient"]
    assert len(annual) == 1
    assert annual[0].value == "€800,000"
    assert len(outpatient) == 1
    assert "€12,000" in outpatient[0].value
    assert "€2,000,000" not in str([fact.value for fact in run.case.facts])
    assert run.bridge.added_fact_count > 0
