from __future__ import annotations

import pytest

from backend.app.agents.advice_synthesis import (
    deterministic_advice_fallback,
    safe_comparison_projection,
    safe_fact_projection,
)
from backend.app.agents.hal_adviser import HalAdviser
from backend.app.cases.models import AshlarCase, Fact, FactSource, FactSourceType, FactStatus
from backend.app.cases.store import CASE_ANALYSIS_STORE


def test_safe_comparison_projection_drops_operational_and_sensitive_fields():
    results = [{
        "provider": "Carrier",
        "target_plan": "Silver",
        "case_token": "DO-NOT-LEAK",
        "internal_prompt": "DO-NOT-LEAK",
        "analysis": {
            "provider": "Carrier",
            "plan_name": "Silver",
            "annual_limit": "EUR 1,000,000",
            "chronic_conditions_note": "sensitive free text",
            "internal_prompt": "hidden prompt",
            "case_token": "secret",
        },
        "focused_rows": [{
            "benefit": "Cancer",
            "value": "Covered",
            "source_internal_id": "secret",
        }],
    }]

    projected = safe_comparison_projection(results)
    text = repr(projected)

    assert projected[0]["analysis"]["annual_limit"] == "EUR 1,000,000"
    assert "chronic_conditions_note" not in text
    assert "internal_prompt" not in text
    assert "DO-NOT-LEAK" not in text
    assert "case_token" not in text
    assert "source_internal_id" not in text


def test_safe_fact_projection_exposes_plan_evidence_but_not_client_or_unknown_facts():
    case = AshlarCase()
    case.facts.extend([
        Fact(
            subject="plan:carrier:silver",
            key="benefit.cancer",
            value="Covered",
            plan_key="carrier:silver",
            status=FactStatus.EXTRACTED,
            source=FactSource(source_type=FactSourceType.POLICY_WORDING, source_ref="wording.pdf", document_id=None),
        ),
        Fact(
            subject="client",
            key="medical_note",
            value="PRIVATE MEDICAL FREE TEXT",
            status=FactStatus.DECLARED,
            source=FactSource(source_type=FactSourceType.CLIENT_DECLARATION),
        ),
        Fact(
            subject="plan:carrier:silver",
            key="internal_prompt",
            value="DO NOT EXPOSE",
            plan_key="carrier:silver",
            status=FactStatus.EXTRACTED,
            source=FactSource(source_type=FactSourceType.SYSTEM),
        ),
    ])

    projected = safe_fact_projection(case)
    text = repr(projected)

    assert projected[0]["key"] == "benefit.cancer"
    assert projected[0]["value"] == "Covered"
    assert "PRIVATE MEDICAL FREE TEXT" not in text
    assert "DO NOT EXPOSE" not in text
    assert "medical_note" not in text
    assert "internal_prompt" not in text


def test_deterministic_advice_fallback_refuses_to_treat_conflicted_case_as_settled():
    plan_key = "carrier:silver"
    case = AshlarCase(selected_plan_keys=[plan_key])
    case.facts.extend([
        Fact(
            subject=f"plan:{plan_key}",
            key="annual_limit",
            value="EUR 1,000,000",
            plan_key=plan_key,
            status=FactStatus.EXTRACTED,
            source=FactSource(source_type=FactSourceType.CARRIER_QUOTE, source_ref="quote.pdf"),
        ),
        Fact(
            subject=f"plan:{plan_key}",
            key="annual_limit",
            value="EUR 2,000,000",
            plan_key=plan_key,
            status=FactStatus.EXTRACTED,
            source=FactSource(source_type=FactSourceType.CARRIER_TOB, source_ref="tob.pdf"),
        ),
    ])

    result = deterministic_advice_fallback(case, [{"provider": "Carrier", "target_plan": "Silver", "analysis": {}}])

    assert "unresolved evidence conflict" in result["answer"]
    assert result["confidence"] == "low"
    assert result["advisory_only"] is True


def test_deterministic_walkthrough_explains_real_differences_and_unknown_prices():
    case = AshlarCase(needs_profile={"priorities": ["outpatient_required"]})
    results = [
        {
            "provider": "IMG",
            "target_plan": "GPMI Silver",
            "analysis": {
                "annual_limit": "EUR 3,000,000",
                "premium": {"amount": None, "currency": "EUR", "frequency": "Annual"},
                "benefits": {"outpatient": "EUR 10,000 combined limit"},
            },
        },
        {
            "provider": "Morgan Price",
            "target_plan": "Standard Plus",
            "analysis": {
                "annual_limit": "EUR 750,000",
                "premium": {"amount": 2694.72, "currency": "EUR", "frequency": "Annual"},
                "benefits": {"outpatient": "Covered subject to schedule"},
            },
        },
    ]

    result = deterministic_advice_fallback(case, results)

    assert "GPMI Silver" in result["answer"]
    assert "EUR 3,000,000" in result["answer"]
    assert "outpatient" in result["answer"].lower()
    assert "no verified current premium" in result["answer"]
    assert "Standard Plus" in result["answer"]
    assert "EUR 2,694.72" in result["answer"]
    assert result["tradeoffs"]
    assert any("carrier quotation" in item for item in result["uncertainties"])


@pytest.mark.asyncio
async def test_hal_adviser_uses_server_owned_case_mode_before_legacy_chat(monkeypatch):
    case = AshlarCase(
        selected_plan_keys=["carrier:silver"],
        needs_profile={"priorities": ["outpatient"]},
    )
    results = [{
        "provider": "Carrier",
        "target_plan": "Silver",
        "analysis": {
            "provider": "Carrier",
            "plan_name": "Silver",
            "premium": {"amount": 1200, "currency": "EUR", "frequency": "Annual"},
            "annual_limit": "EUR 1,000,000",
            "deductible_or_excess": "EUR 500",
            "area_of_cover": "Europe",
            "underwriting": {"basis": "FMU"},
            "benefits": {"outpatient": "Covered"},
        },
    }]
    record = CASE_ANALYSIS_STORE.put(case=case, results=results)
    adviser = HalAdviser()

    async def _legacy_must_not_run(*args, **kwargs):
        raise AssertionError("legacy chat must not run when an authorised AshlarCase exists")

    async def _fake_case_advice(*, case, results, question):
        return {
            "answer": "Grounded case answer",
            "tradeoffs": [],
            "uncertainties": [],
            "next_best_action": "Review the evidence.",
            "confidence": "medium",
            "status": "completed",
            "advisory_only": True,
            "authoritative_facts_source": "server_case_and_fact_ledger",
        }

    monkeypatch.setattr(adviser, "run_chat", _legacy_must_not_run)
    monkeypatch.setattr("backend.app.agents.hal_adviser.synthesize_case_advice", _fake_case_advice)

    response = await adviser.handle(
        case_id=record.case.case_id,
        message="Why are you recommending this?",
        context={"case_token": record.access_token},
    )

    assert response.reply == "Grounded case answer"
    assert response.payload["mode"] == "evidence_aware_case_advice"
    assert response.payload["advice"]["authoritative_facts_source"] == "server_case_and_fact_ledger"
