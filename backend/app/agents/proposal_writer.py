from __future__ import annotations

from typing import Any
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from backend.app.cases.models import AshlarCase, CaseStatus
from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.proposals.engine import (
    ProposalBundle,
    ProposalGenerationBlocked,
    generate_case_proposal,
)

from .contracts import SpecialistName, SpecialistResponse


class ProposalWriter:
    """Embedded Proposal Studio proposal specialist.

    Narrative generation and rendering are reached through this specialist;
    factual plan data still comes only from the verified server-owned analysis.
    """

    name = SpecialistName.PROPOSAL_WRITER

    def generate(
        self,
        *,
        case: AshlarCase,
        results: list[dict[str, Any]],
        language: str | None = None,
        strict_narrative: bool = False,
    ) -> ProposalBundle:
        return generate_case_proposal(
            case=case,
            results=results,
            language=language,
            strict_narrative=strict_narrative,
        )

    async def handle(
        self,
        *,
        case_id: UUID | None,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> SpecialistResponse:
        ctx = context or {}
        if case_id is None:
            return SpecialistResponse(
                specialist=self.name,
                status="needs_input",
                reply="A case_id is required before a proposal can be prepared.",
            )

        case_token = str(ctx.get("case_token") or "")
        record = CASE_ANALYSIS_STORE.get(case_id, case_token) if case_token else None
        if record is None:
            return SpecialistResponse(
                specialist=self.name,
                status="needs_input",
                reply="The proposal writer needs an active server-owned case and access token.",
                payload={"required": ["case_id", "case_token"]},
            )

        bundle = await run_in_threadpool(
            self.generate,
            case=record.case.model_copy(deep=True),
            results=record.results,
            language=ctx.get("language"),
            strict_narrative=bool(ctx.get("strict_narrative", False)),
        )
        case = record.case.model_copy(deep=True)
        # generate_case_proposal mutates the copy it receives, so repeat on the
        # saved case only through the report metadata we actually need here.
        case.status = CaseStatus.PROPOSAL
        case.recommendation = dict(bundle.report.get("ashlar_assessment") or {})
        case.proposal = {
            "engine": "ashlar_proposal_studio",
            "quality": bundle.quality,
            "report": bundle.report,
            "formats": ["pdf", "pptx"],
            "pdf_size_bytes": len(bundle.pdf_bytes),
            "pptx_size_bytes": len(bundle.pptx_bytes),
        }
        case.touch()
        CASE_ANALYSIS_STORE.save_case(case=case, access_token=case_token)

        return SpecialistResponse(
            specialist=self.name,
            status="completed",
            reply="Proposal Studio prepared the grounded client proposal.",
            payload={
                "case_id": str(case.case_id),
                "quality": bundle.quality,
                "report": bundle.report,
                "pdf_size_bytes": len(bundle.pdf_bytes),
                "pptx_size_bytes": len(bundle.pptx_bytes),
            },
        )


_PROPOSAL_WRITER = ProposalWriter()


def get_proposal_writer() -> ProposalWriter:
    return _PROPOSAL_WRITER


__all__ = [
    "ProposalBundle",
    "ProposalGenerationBlocked",
    "ProposalWriter",
    "get_proposal_writer",
]
