from backend.app.cases.models import (
    AshlarCase,
    CaseClient,
    Fact,
    FactSource,
    FactSourceType,
    FactStatus,
)
from backend.app.policy.engine import PolicyEngine, PolicyVerdict


def _fact(value, *, status=FactStatus.VERIFIED, plan_key="carrier:plan"):
    return Fact(
        subject=f"plan:{plan_key}",
        key="benefit.ct_scan",
        value=value,
        plan_key=plan_key,
        provider="Carrier",
        status=status,
        source=FactSource(
            source_type=FactSourceType.POLICY_WORDING,
            source_ref="wording.pdf",
            page=42,
        ),
    )


def _case(*facts):
    return AshlarCase(
        client=CaseClient(display_name="Policy Test"),
        selected_plan_keys=["carrier:plan"],
        facts=list(facts),
    )


def test_policy_engine_uses_verified_positive_fact_only():
    result = PolicyEngine().check_benefit(case=_case(_fact("Covered subject to pre-authorisation")), benefit_key="ct scan")
    assert result.verdict == PolicyVerdict.COVERED
    assert result.value == "Covered subject to pre-authorisation"
    assert result.evidence[0]["page"] == 42


def test_policy_engine_recognises_explicit_not_covered():
    result = PolicyEngine().check_benefit(case=_case(_fact("Not covered")), benefit_key="ct_scan")
    assert result.verdict == PolicyVerdict.NOT_COVERED


def test_policy_engine_ignores_unverified_or_extracted_facts():
    result = PolicyEngine().check_benefit(
        case=_case(_fact("Covered", status=FactStatus.EXTRACTED)),
        benefit_key="ct_scan",
    )
    assert result.verdict == PolicyVerdict.UNKNOWN


def test_policy_engine_fails_closed_on_verified_conflict():
    result = PolicyEngine().check_benefit(
        case=_case(_fact("Covered"), _fact("Not covered")),
        benefit_key="ct_scan",
    )
    assert result.verdict == PolicyVerdict.CONFLICT
