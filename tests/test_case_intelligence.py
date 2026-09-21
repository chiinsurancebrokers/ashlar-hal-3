from __future__ import annotations

from backend.app.cases.intelligence import build_case_intelligence
from backend.app.cases.models import AshlarCase, Fact, FactSource, FactSourceType, FactStatus


def _fact(*, key: str, value, plan_key: str, status: FactStatus = FactStatus.EXTRACTED):
    return Fact(
        subject=f"plan:{plan_key}",
        key=key,
        value=value,
        plan_key=plan_key,
        status=status,
        source=FactSource(source_type=FactSourceType.CARRIER_QUOTE, source_ref="quote.pdf"),
    )


def test_case_intelligence_surfaces_missing_material_facts_and_conflicts():
    plan_key = "carrier:silver"
    case = AshlarCase(selected_plan_keys=[plan_key])
    case.facts.extend([
        _fact(key="premium_amount", value=1200, plan_key=plan_key),
        _fact(key="annual_limit", value="EUR 1,000,000", plan_key=plan_key),
        _fact(key="annual_limit", value="EUR 2,000,000", plan_key=plan_key),
    ])

    snapshot = build_case_intelligence(case)

    assert snapshot["conflict_count"] == 1
    assert snapshot["evidence_confidence"] == "low"
    assert snapshot["ready_for_proposal"] is False
    assert snapshot["plans"][0]["conflicting_material_keys"] == ["annual_limit"]
    assert "deductible_or_excess" in snapshot["plans"][0]["missing_material_keys"]
    assert any(item["action"] == "resolve_evidence_conflicts" for item in snapshot["next_actions"])
