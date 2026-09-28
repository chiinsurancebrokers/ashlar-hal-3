"""Orchestrate document evidence into an Ashlar case.

This is the first end-to-end Proposal Studio -> HAL path: a selected carrier
plan is analysed, deterministic evidence is re-applied, quality is assessed,
and normalized facts are committed to the Case Brain.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.app.cases.models import AshlarCase, CaseDocument
from backend.app.documents.bridge import ProposalBridgeResult, apply_proposal_analysis
from backend.app.documents.deep_analysis import prepare_deep_analysis


@dataclass(frozen=True)
class DocumentAnalysisRun:
    envelope: dict
    bridge: ProposalBridgeResult

    @property
    def case(self) -> AshlarCase:
        return self.bridge.case


def analyze_and_apply_document_bundle(
    case: AshlarCase,
    *,
    document: CaseDocument,
    provider_label: str,
    target_plan: str,
    quotation_text: str = "",
    brochure_text: str = "",
    wording_text: str = "",
    focused_table_context: str = "",
    model_result: dict | None = None,
    plan_key: str | None = None,
) -> DocumentAnalysisRun:
    envelope = prepare_deep_analysis(
        provider_label=provider_label,
        target_plan=target_plan,
        quotation_text=quotation_text,
        brochure_text=brochure_text,
        wording_text=wording_text,
        focused_table_context=focused_table_context,
        model_result=model_result,
    )
    bridge = apply_proposal_analysis(
        case,
        envelope,
        document=document,
        plan_key=plan_key,
    )
    return DocumentAnalysisRun(envelope=envelope, bridge=bridge)
