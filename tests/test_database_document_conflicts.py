from backend.app.api.quotes import _comparison_evidence_facts
from backend.app.cases.fact_ledger import FactLedger
from backend.app.cases.models import CaseDocument, FactSourceType, FactStatus
from backend.app.documents.proposal_adapter import analysis_to_facts


def test_carrier_document_conflict_is_detected_against_verified_benefit_library():
    plan_key = "carrier:test_plan"
    database_facts = _comparison_evidence_facts([
        {
            "plan_key": plan_key,
            "provider": "Carrier",
            "target_plan": "Test Plan",
            "library_source": True,
            "analysis": {
                "provider": "Carrier",
                "plan_name": "Test Plan",
                "benefits": {"cancer": "Covered in full"},
            },
        }
    ])
    assert database_facts
    assert database_facts[0].status == FactStatus.VERIFIED
    assert database_facts[0].source.source_type == FactSourceType.CARRIER_TOB

    document = CaseDocument(
        filename="carrier-quotation.txt",
        document_type="quotation",
        provider="Carrier",
        plan_key=plan_key,
    )
    document_facts = analysis_to_facts(
        {
            "provider": "Carrier",
            "plan_name": "Test Plan",
            "benefits": {"cancer": "Not covered"},
            "confidence": "high",
        },
        document=document,
        plan_key=plan_key,
    )

    ledger = FactLedger([*database_facts, *document_facts])
    conflicts = ledger.conflicts()

    assert any(
        conflict.subject == f"plan:{plan_key}" and conflict.key == "benefit.cancer"
        for conflict in conflicts
    )
