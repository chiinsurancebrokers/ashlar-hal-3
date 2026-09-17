"""Bridge Proposal Studio evidence into the shared Ashlar Case Brain."""
from __future__ import annotations

import json
from dataclasses import dataclass

from backend.app.cases.fact_ledger import FactLedger
from backend.app.cases.models import AshlarCase, CaseDocument, CaseStatus, Fact
from backend.app.documents.proposal_adapter import analysis_to_facts
from backend.app.documents.quality import assess_result_quality


def _value_key(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))


def _identity(fact: Fact) -> tuple:
    source = fact.source
    return (
        fact.subject,
        fact.key,
        _value_key(fact.value),
        fact.plan_key,
        source.source_type.value,
        str(source.document_id or ""),
        source.page,
    )


@dataclass(frozen=True)
class ProposalBridgeResult:
    case: AshlarCase
    quality: dict
    added_fact_count: int
    skipped_duplicate_count: int
    conflict_keys: tuple[str, ...]


def apply_proposal_analysis(
    case: AshlarCase,
    analysis_result: dict,
    *,
    document: CaseDocument,
    plan_key: str | None = None,
) -> ProposalBridgeResult:
    """Apply one Proposal Studio analysis result to a case without overwrites.

    Reprocessing the same document/result is idempotent. Contradictory values
    are retained as separate facts and surfaced via ``conflict_keys``; nothing
    silently picks a winner.
    """
    working = case.model_copy(deep=True)
    if not any(d.document_id == document.document_id for d in working.documents):
        working.documents.append(document.model_copy(deep=True))

    ledger = FactLedger(working.facts)
    existing = {_identity(f) for f in ledger.facts}
    added = 0
    skipped = 0
    conflict_keys: set[str] = set()

    for fact in analysis_to_facts(analysis_result, document=document, plan_key=plan_key):
        ident = _identity(fact)
        if ident in existing:
            skipped += 1
            continue
        outcome = ledger.add(fact)
        existing.add(ident)
        added += 1
        if outcome.conflict:
            conflict_keys.add(f"{fact.subject}:{fact.key}")

    working.facts = ledger.facts
    if added and working.status in {CaseStatus.DISCOVERY, CaseStatus.MARKET_REVIEW}:
        working.status = CaseStatus.COMPARISON
    working.touch()

    return ProposalBridgeResult(
        case=working,
        quality=assess_result_quality(analysis_result),
        added_fact_count=added,
        skipped_duplicate_count=skipped,
        conflict_keys=tuple(sorted(conflict_keys)),
    )
