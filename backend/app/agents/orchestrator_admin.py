from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.cases.models import AshlarCase
from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.proposals.artifacts import PROPOSAL_ARTIFACT_STORE
from backend.app.proposals.engine import ProposalBundle

from .contracts import SpecialistName


@dataclass(frozen=True)
class OrchestratorProposalError(Exception):
    """Stable API-facing error raised by the internal orchestrator gateway."""

    status_code: int
    detail: str

    def __str__(self) -> str:
        return self.detail


def _raise_for_response(response) -> None:
    if response.status == "blocked":
        raise OrchestratorProposalError(422, response.reply or "Proposal generation is blocked.")
    if response.status == "needs_input":
        raise OrchestratorProposalError(422, response.reply or "More case information is required.")
    if response.status == "unavailable":
        raise OrchestratorProposalError(409, response.reply or "Proposal generation is unavailable.")
    if response.status != "completed":
        raise OrchestratorProposalError(502, response.reply or "Proposal generation did not complete.")


async def generate_admin_proposal_bundle(
    orchestrator: Any,
    *,
    case: AshlarCase,
    results: list[dict[str, Any]],
    language: str | None = None,
    strict_narrative: bool = False,
) -> ProposalBundle:
    """Run broker proposal generation through the same AshlarOrchestrator path.

    The broker endpoint starts with already-authorised server data, but it still
    creates a short-lived server-owned case and enters ``orchestrator.handle``.
    No API/helper outside AshlarOrchestrator may reach a concrete specialist.
    """
    record = CASE_ANALYSIS_STORE.put(case=case, results=results)
    result = await orchestrator.handle(
        case_id=record.case.case_id,
        message="Create the proposal.",
        context={
            "case_token": record.access_token,
            "language": language,
            "strict_narrative": strict_narrative,
        },
    )
    response = next(
        (
            item
            for item in reversed(result.responses)
            if item.specialist == SpecialistName.PROPOSAL_WRITER
        ),
        None,
    )
    if response is None:
        raise OrchestratorProposalError(502, "Ashlar Orchestrator did not return a proposal specialist result.")
    _raise_for_response(response)

    proposal_id = str((response.payload or {}).get("proposal_id") or "").strip()
    if not proposal_id:
        raise OrchestratorProposalError(502, "Proposal writer completed without an artifact reference.")

    artifact = PROPOSAL_ARTIFACT_STORE.get(proposal_id)
    saved = CASE_ANALYSIS_STORE.get(record.case.case_id, record.access_token)
    if artifact is None or saved is None:
        raise OrchestratorProposalError(409, "The generated proposal or temporary case expired.")

    # Preserve the historical broker API contract: callers supplied a case
    # object and expect the generated recommendation/proposal state on it.
    case.recommendation = dict(saved.case.recommendation or {})
    case.proposal = dict(saved.case.proposal or {})
    case.status = saved.case.status
    case.touch()

    quality = dict((response.payload or {}).get("quality") or {})
    if not quality and isinstance(case.proposal, dict):
        quality = dict(case.proposal.get("quality") or {})

    return ProposalBundle(
        report=dict(artifact.report),
        pdf_bytes=artifact.pdf_bytes,
        pptx_bytes=artifact.pptx_bytes,
        quality=quality,
    )


__all__ = [
    "OrchestratorProposalError",
    "generate_admin_proposal_bundle",
]
