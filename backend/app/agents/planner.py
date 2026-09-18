from __future__ import annotations

from typing import Any

from .contracts import (
    NextBestAction,
    OrchestrationDecision,
    OrchestrationIntent,
    SpecialistName,
    SpecialistResponse,
)


def _first_response_with_status(
    responses: list[SpecialistResponse],
    *statuses: str,
) -> SpecialistResponse | None:
    return next((item for item in responses if item.status in statuses), None)


def plan_next_best_action(
    *,
    decision: OrchestrationDecision,
    responses: list[SpecialistResponse],
    case_intelligence: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> NextBestAction:
    """Choose the next useful action from deterministic orchestration state.

    This is intentionally rule-based. The model may explain a next step, but it
    cannot decide which specialist is authorised to act or silently skip an
    unresolved evidence problem.
    """

    intelligence = case_intelligence or {}
    result_payload = payload or {}

    blocked = _first_response_with_status(responses, "blocked")
    if blocked is not None:
        return NextBestAction(
            action="resolve_specialist_blocker",
            owner=blocked.specialist.value,
            reason=blocked.reply or "A specialist step is blocked and must be resolved before the workflow can continue.",
            blocked=True,
        )

    unavailable = _first_response_with_status(responses, "unavailable")
    if unavailable is not None:
        return NextBestAction(
            action="retry_or_handoff",
            owner=unavailable.specialist.value,
            reason=unavailable.reply or "A required specialist is currently unavailable.",
            blocked=True,
        )

    needs_input = _first_response_with_status(responses, "needs_input")
    if needs_input is not None:
        required = [str(value) for value in (needs_input.payload.get("required") or []) if str(value)]
        return NextBestAction(
            action="collect_required_input",
            owner=needs_input.specialist.value,
            reason=needs_input.reply or "More information is required before the specialist can continue.",
            blocked=True,
            required=required,
        )

    if decision.intent == OrchestrationIntent.HEALTH_POLICY:
        policy = result_payload.get("policy") if isinstance(result_payload.get("policy"), dict) else {}
        verdict = str(policy.get("verdict") or "unknown").casefold()
        if verdict == "conflict":
            return NextBestAction(
                action="resolve_policy_evidence_conflict",
                owner="policy_engine",
                reason="Verified policy evidence conflicts, so coverage must not be presented as settled.",
                blocked=True,
            )
        if verdict == "unknown":
            return NextBestAction(
                action="obtain_verified_policy_evidence",
                owner="document_analyst",
                reason="The Policy Engine does not yet have enough verified policy evidence to answer the coverage question.",
                blocked=True,
                required=["policy_schedule_or_wording"],
            )

    conflict_count = int(intelligence.get("conflict_count") or 0)
    if conflict_count:
        return NextBestAction(
            action="resolve_evidence_conflicts",
            owner=SpecialistName.DOCUMENT_ANALYST.value,
            reason=f"The active case contains {conflict_count} unresolved evidence conflict(s).",
            blocked=True,
        )

    if intelligence.get("ready_for_proposal") and decision.intent != OrchestrationIntent.PROPOSAL:
        return NextBestAction(
            action="prepare_proposal",
            owner=SpecialistName.PROPOSAL_WRITER.value,
            reason="Applicant-specific carrier quotations have been analysed and the material evidence is conflict-free.",
        )

    next_actions = intelligence.get("next_actions") or []
    if next_actions:
        first = next_actions[0] if isinstance(next_actions[0], dict) else {}
        action = str(first.get("action") or "strengthen_case_evidence")
        reason = str(first.get("reason") or "The case needs stronger evidence before moving forward.")
        owner = SpecialistName.DOCUMENT_ANALYST.value if action in {
            "upload_carrier_documents",
            "complete_plan_evidence",
            "verify_material_plan_facts",
        } else SpecialistName.HAL_ADVISER.value
        return NextBestAction(
            action=action,
            owner=owner,
            reason=reason,
            blocked=action in {
                "select_shortlist_plans",
                "upload_carrier_documents",
                "complete_plan_evidence",
            },
        )

    if decision.intent == OrchestrationIntent.QUOTE and result_payload.get("quotes"):
        return NextBestAction(
            action="explain_shortlist",
            owner=SpecialistName.HAL_ADVISER.value,
            reason="The Quote Engine has produced a shortlist; HAL can now explain the trade-offs without recalculating price or eligibility.",
        )

    if decision.intent == OrchestrationIntent.PROPOSAL:
        completed = any(item.specialist == SpecialistName.PROPOSAL_WRITER and item.status == "completed" for item in responses)
        if completed:
            return NextBestAction(
                action="present_proposal_to_client",
                owner=SpecialistName.HAL_ADVISER.value,
                reason="The proposal is generated; HAL can explain it and answer client questions using the same case evidence.",
            )

    if decision.intent == OrchestrationIntent.DOCUMENT:
        return NextBestAction(
            action="explain_document_findings",
            owner=SpecialistName.HAL_ADVISER.value,
            reason="Document analysis is complete; HAL can now explain the grounded findings and trade-offs to the user.",
        )

    return NextBestAction(
        action="continue_adviser_conversation",
        owner=SpecialistName.HAL_ADVISER.value,
        reason="No higher-priority evidence, policy, proposal, or specialist action is pending.",
    )


__all__ = ["plan_next_best_action"]
