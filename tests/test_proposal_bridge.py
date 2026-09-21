from backend.app.cases.fact_ledger import FactLedger
from backend.app.cases.models import AshlarCase, CaseDocument, CaseStatus
from backend.app.documents.bridge import apply_proposal_analysis


def _result(limit="€2,000,000"):
    return {
        "provider": "Cigna",
        "target_plan": "Executive Care",
        "analysis": {
            "provider": "Cigna",
            "plan_name": "Executive Care",
            "premium": {"amount": 8500, "currency": "EUR", "frequency": "annual"},
            "deductible_or_excess": "€0",
            "annual_limit": limit,
            "area_of_cover": "Worldwide excluding USA",
            "underwriting": {"basis": "CPME", "pre_existing_conditions": "Continuity subject to CPME terms"},
            "benefits": {
                "inpatient": "Covered",
                "outpatient": "Covered",
                "cancer": "Covered in full within policy terms",
                "dental": "Not covered",
            },
            "waiting_periods": [{"benefit": "Dental", "waiting_period": "8 months"}],
            "critical_limitations": [{"topic": "USA", "detail": "USA treatment excluded", "source_page": 12}],
            "source_evidence": [
                {"field": "annual_limit", "value": limit, "document": "quote.pdf", "page": 4, "evidence": "Overall annual maximum"}
            ],
            "confidence": "high",
        },
    }


def test_proposal_analysis_enters_shared_case_and_keeps_provenance():
    case = AshlarCase()
    doc = CaseDocument(filename="quote.pdf", document_type="quotation", provider="Cigna")
    outcome = apply_proposal_analysis(case, _result(), document=doc)

    assert outcome.case.status == CaseStatus.COMPARISON
    assert outcome.added_fact_count > 8
    assert len(outcome.case.documents) == 1
    ledger = FactLedger(outcome.case.facts)
    fact = ledger.current("annual_limit", subject="plan:cigna:executive_care")
    assert fact is not None
    assert fact.value == "€2,000,000"
    assert fact.source.document_id == doc.document_id
    assert fact.source.page == 4
    assert fact.source.source_type.value == "carrier_quote"


def test_reprocessing_same_result_is_idempotent():
    case = AshlarCase()
    doc = CaseDocument(filename="quote.pdf", document_type="quotation", provider="Cigna")
    first = apply_proposal_analysis(case, _result(), document=doc)
    second = apply_proposal_analysis(first.case, _result(), document=doc)
    assert second.added_fact_count == 0
    assert second.skipped_duplicate_count == first.added_fact_count
    assert len(second.case.facts) == len(first.case.facts)


def test_conflicting_carrier_fact_is_never_silently_overwritten():
    case = AshlarCase()
    doc1 = CaseDocument(filename="quote-v1.pdf", document_type="quotation", provider="Cigna")
    doc2 = CaseDocument(filename="quote-v2.pdf", document_type="quotation", provider="Cigna")
    first = apply_proposal_analysis(case, _result("€2,000,000"), document=doc1)
    second = apply_proposal_analysis(first.case, _result("€1,500,000"), document=doc2)

    assert "plan:cigna:executive_care:annual_limit" in second.conflict_keys
    ledger = FactLedger(second.case.facts)
    assert ledger.current("annual_limit", subject="plan:cigna:executive_care") is None
    assert ledger.conflicts()


def test_explicit_not_covered_is_kept_as_material_fact():
    case = AshlarCase()
    doc = CaseDocument(filename="quote.pdf", document_type="quotation", provider="Cigna")
    outcome = apply_proposal_analysis(case, _result(), document=doc)
    ledger = FactLedger(outcome.case.facts)
    dental = ledger.current("benefit.dental", subject="plan:cigna:executive_care")
    assert dental is not None
    assert dental.value == "Not covered"
