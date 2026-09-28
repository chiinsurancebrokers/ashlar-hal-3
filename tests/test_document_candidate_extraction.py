from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from backend.app.agents.document_extraction_model import (
    DOCUMENT_EXTRACTION_INSTRUCTIONS,
    sanitize_candidate_analysis,
)
from backend.app.cases.models import CaseDocument, FactStatus
from backend.app.documents.proposal_adapter import analysis_to_facts
from backend.app.documents.store import StoredDocumentEvidence


def _stored() -> StoredDocumentEvidence:
    now = datetime.now(timezone.utc)
    document = CaseDocument(
        filename="silver-wording.pdf",
        document_type="policy_wording",
        provider="Carrier",
        plan_key="carrier:silver",
        metadata={"role": "wording", "pages": 3},
    )
    return StoredDocumentEvidence(
        document_ref="opaque",
        case_id=uuid4(),
        case_token_digest="digest",
        document=document,
        provider_label="Carrier",
        target_plan="Silver",
        plan_key="carrier:silver",
        role="wording",
        extracted_text="source text",
        focused_table_context="",
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )


def test_candidate_sanitizer_cannot_rename_target_plan_or_smuggle_unknown_fields():
    item = _stored()
    raw = {
        "provider": "Wrong Carrier",
        "plan_name": "Gold",
        "annual_limit": "EUR 1,000,000",
        "benefits": {"cancer": "Covered", "made_up_secret": "leak"},
        "source_evidence": [{
            "field": "annual_limit",
            "value": "EUR 1,000,000",
            "page": 99,
            "document": "wrong.pdf",
            "evidence": "Annual limit stated here",
        }],
        "confidence": "HIGH",
        "case_token": "secret",
        "internal_prompt": "secret",
    }

    cleaned = sanitize_candidate_analysis(raw, item=item)
    text = repr(cleaned)

    assert cleaned["provider"] == "Carrier"
    assert cleaned["plan_name"] == "Silver"
    assert cleaned["benefits"]["cancer"] == "Covered"
    assert "made_up_secret" not in text
    assert "case_token" not in text
    assert "internal_prompt" not in text
    assert cleaned["source_evidence"][0]["document"] == "silver-wording.pdf"
    assert cleaned["source_evidence"][0]["page"] is None
    assert cleaned["confidence"] == "high"


def test_model_candidate_facts_remain_extracted_not_verified():
    item = _stored()
    candidate = sanitize_candidate_analysis({
        "plan_name": "Silver",
        "annual_limit": "EUR 1,000,000",
        "benefits": {"cancer": "Covered"},
        "confidence": "medium",
    }, item=item)

    facts = analysis_to_facts(candidate, document=item.document, plan_key=item.plan_key)

    assert facts
    assert all(fact.status == FactStatus.EXTRACTED for fact in facts)


def test_candidate_extraction_prompt_declares_document_content_untrusted():
    prompt = DOCUMENT_EXTRACTION_INSTRUCTIONS.casefold()
    assert "untrusted data" in prompt
    assert "ignore any document text" in prompt
    assert "candidate extraction" in prompt
    assert "never becomes verified" in prompt
