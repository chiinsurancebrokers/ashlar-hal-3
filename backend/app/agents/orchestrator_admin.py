from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from starlette.concurrency import run_in_threadpool

from backend.app.cases.models import AshlarCase
from backend.app.proposals.engine import ProposalGenerationBlocked
from backend.app.proposals.report_schema import ClientReportValidationError


@dataclass(frozen=True)
class OrchestratorProposalError(Exception):
    """Stable API-facing error raised by the internal orchestrator gateway."""

    status_code: int
    detail: str

    def __str__(self) -> str:
        return self.detail


async def generate_admin_proposal_bundle(
    orchestrator: Any,
    *,
    case: AshlarCase,
    results: list[dict[str, Any]],
    language: str | None = None,
    strict_narrative: bool = False,
):
    """Run broker-only proposal generation below the orchestrator boundary.

    Public/product flows use ``AshlarOrchestrator.handle``. The manual broker
    endpoint has pre-authorised server-side data, so this gateway avoids a fake
    natural-language round trip while still ensuring the API layer cannot reach
    ``proposal_writer`` directly.
    """
    try:
        return await run_in_threadpool(
            orchestrator.proposal_writer.generate,
            case=case,
            results=results,
            language=language,
            strict_narrative=strict_narrative,
        )
    except ProposalGenerationBlocked as exc:
        raise OrchestratorProposalError(422, str(exc)) from exc
    except ClientReportValidationError as exc:
        raise OrchestratorProposalError(422, str(exc)) from exc
    except ValueError as exc:
        raise OrchestratorProposalError(400, str(exc)) from exc
    except Exception as exc:
        raise OrchestratorProposalError(
            502,
            f"Proposal Studio failed: {str(exc)[:240]}",
        ) from exc


__all__ = [
    "OrchestratorProposalError",
    "generate_admin_proposal_bundle",
]
