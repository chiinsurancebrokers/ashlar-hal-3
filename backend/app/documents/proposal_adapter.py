"""Translate Proposal Studio plan analysis into evidence-bearing Ashlar Facts."""
from __future__ import annotations

import re
from typing import Any

from backend.app.cases.models import CaseDocument, Fact, FactSource, FactSourceType, FactStatus
from backend.app.documents.quality import missing


_CONFIDENCE = {"high": 0.95, "medium": 0.75, "low": 0.50}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")


def _plan_key(provider: str, plan_name: str, override: str | None = None) -> str:
    if override:
        return override
    return f"{_slug(provider) or 'provider'}:{_slug(plan_name) or 'plan'}"


def _source_type(document_type: str) -> FactSourceType:
    key = str(document_type or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if key in {"quote", "quotation", "certificate", "carrier_quote"}:
        return FactSourceType.CARRIER_QUOTE
    if key in {"tob", "table_of_benefits", "brochure", "carrier_tob"}:
        return FactSourceType.CARRIER_TOB
    if key in {"wording", "policy_wording", "member_guide"}:
        return FactSourceType.POLICY_WORDING
    if key in {"schedule", "policy_schedule"}:
        return FactSourceType.POLICY_SCHEDULE
    if key == "application":
        return FactSourceType.APPLICATION
    return FactSourceType.PROPOSAL_STUDIO


def _evidence_by_field(analysis: dict) -> dict[str, dict]:
    evidence: dict[str, dict] = {}
    for row in analysis.get("source_evidence") or []:
        if not isinstance(row, dict):
            continue
        field = str(row.get("field") or "").strip().lower().replace(" ", "_")
        if field and field not in evidence:
            evidence[field] = row
    return evidence


def _fact(
    *,
    key: str,
    value: Any,
    subject: str,
    provider: str,
    plan_key: str,
    document: CaseDocument,
    confidence: float,
    evidence: dict | None = None,
    currency: str | None = None,
    note: str | None = None,
) -> Fact:
    evidence = evidence or {}
    page = evidence.get("page") or evidence.get("source_page")
    try:
        page = int(page) if page is not None else None
    except (TypeError, ValueError):
        page = None
    excerpt = str(evidence.get("evidence") or "").strip() or None
    return Fact(
        subject=subject,
        key=key,
        value=value,
        currency=currency,
        provider=provider or document.provider,
        plan_key=plan_key,
        status=FactStatus.EXTRACTED,
        confidence=confidence,
        source=FactSource(
            source_type=_source_type(document.document_type),
            source_ref=document.filename,
            document_id=document.document_id,
            page=page,
            quote=excerpt[:800] if excerpt else None,
        ),
        note=note,
    )


def analysis_to_facts(
    analysis_result: dict,
    *,
    document: CaseDocument,
    plan_key: str | None = None,
) -> list[Fact]:
    """Convert one Proposal Studio result into normalized facts.

    Missing/unknown fields are not promoted into the ledger. Explicit negative
    statements such as ``Not covered`` remain facts because they are material.
    """
    analysis = analysis_result.get("analysis") or analysis_result
    provider = str(analysis.get("provider") or analysis_result.get("provider") or document.provider or "").strip()
    plan_name = str(analysis.get("plan_name") or analysis_result.get("target_plan") or "").strip()
    resolved_plan_key = _plan_key(provider, plan_name, plan_key or document.plan_key)
    subject = f"plan:{resolved_plan_key}"
    confidence = _CONFIDENCE.get(str(analysis.get("confidence") or "medium").casefold(), 0.75)
    evidence = _evidence_by_field(analysis)
    facts: list[Fact] = []

    def add(key: str, value: Any, *, currency: str | None = None, evidence_key: str | None = None, note: str | None = None):
        if missing(value):
            return
        facts.append(_fact(
            key=key,
            value=value,
            subject=subject,
            provider=provider,
            plan_key=resolved_plan_key,
            document=document,
            confidence=confidence,
            evidence=evidence.get(evidence_key or key),
            currency=currency,
            note=note,
        ))

    add("provider", provider)
    add("plan_name", plan_name)

    premium = analysis.get("premium") or {}
    add("premium_amount", premium.get("amount"), currency=premium.get("currency"), evidence_key="premium")
    add("premium_frequency", premium.get("frequency"), evidence_key="premium")
    add("deductible_or_excess", analysis.get("deductible_or_excess"))
    add("annual_limit", analysis.get("annual_limit"))
    add("area_of_cover", analysis.get("area_of_cover"))

    underwriting = analysis.get("underwriting") or {}
    add("underwriting_basis", underwriting.get("basis"), evidence_key="underwriting")
    add("pre_existing_conditions", underwriting.get("pre_existing_conditions"), evidence_key="underwriting")

    for benefit, value in (analysis.get("benefits") or {}).items():
        if not missing(value):
            add(f"benefit.{benefit}", value, evidence_key=benefit)

    for index, row in enumerate(analysis.get("waiting_periods") or [], start=1):
        if isinstance(row, dict):
            benefit = str(row.get("benefit") or row.get("topic") or f"item_{index}")
            value = row.get("waiting_period") or row.get("period") or row.get("detail")
            if not missing(value):
                add(f"waiting_period.{_slug(benefit) or index}", value, note=benefit)
        elif not missing(row):
            add(f"waiting_period.item_{index}", row)

    for index, row in enumerate(analysis.get("optional_benefits") or [], start=1):
        if not isinstance(row, dict):
            continue
        benefit = str(row.get("benefit") or f"item_{index}")
        add(f"optional_benefit.{_slug(benefit) or index}", {
            "status": row.get("status"),
            "limit": row.get("limit"),
            "waiting_period": row.get("waiting_period"),
        }, note=benefit)

    for index, row in enumerate(analysis.get("critical_limitations") or [], start=1):
        if not isinstance(row, dict):
            continue
        topic = str(row.get("topic") or f"item_{index}")
        detail = row.get("detail")
        if not missing(detail):
            facts.append(_fact(
                key=f"limitation.{_slug(topic) or index}",
                value=detail,
                subject=subject,
                provider=provider,
                plan_key=resolved_plan_key,
                document=document,
                confidence=confidence,
                evidence=row,
                note=topic,
            ))

    return facts
