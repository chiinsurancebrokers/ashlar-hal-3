from __future__ import annotations

from typing import Any
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from backend.app.cases.models import AshlarCase, CaseDocument
from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.documents.orchestrator import analyze_and_apply_document_bundle

from .contracts import SpecialistName, SpecialistResponse


class DocumentAnalyst:
    """Proposal Studio's document/evidence specialist.

    Raw carrier material is normalized through the existing deterministic
    target-plan/document pipeline. The specialist does not turn browser-entered
    insurer facts into verified evidence; callers must supply server-owned case
    context and the actual extracted document material.
    """

    name = SpecialistName.DOCUMENT_ANALYST

    @staticmethod
    def _document(value: Any) -> CaseDocument | None:
        if isinstance(value, CaseDocument):
            return value
        if isinstance(value, dict):
            try:
                return CaseDocument(**value)
            except Exception:
                return None
        return None

    async def handle(
        self,
        *,
        case_id: UUID | None,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> SpecialistResponse:
        ctx = context or {}
        case = ctx.get("case")
        case_token = str(ctx.get("case_token") or "")
        stored_record = None

        if not isinstance(case, AshlarCase) and case_id is not None and case_token:
            stored_record = CASE_ANALYSIS_STORE.get(case_id, case_token)
            if stored_record is not None:
                case = stored_record.case

        document = self._document(ctx.get("document"))
        provider_label = str(ctx.get("provider_label") or "").strip()
        target_plan = str(ctx.get("target_plan") or "").strip()

        if not isinstance(case, AshlarCase) or document is None or not provider_label or not target_plan:
            return SpecialistResponse(
                specialist=self.name,
                status="needs_input",
                reply="Document analysis needs a server-owned case, a document, provider and target plan.",
                payload={
                    "required": ["case", "document", "provider_label", "target_plan"],
                    "accepts": ["quotation_text", "brochure_text", "wording_text", "focused_table_context"],
                },
            )

        run = await run_in_threadpool(
            analyze_and_apply_document_bundle,
            case,
            document=document,
            provider_label=provider_label,
            target_plan=target_plan,
            quotation_text=str(ctx.get("quotation_text") or ""),
            brochure_text=str(ctx.get("brochure_text") or ""),
            wording_text=str(ctx.get("wording_text") or ""),
            focused_table_context=str(ctx.get("focused_table_context") or ""),
            model_result=ctx.get("model_result") if isinstance(ctx.get("model_result"), dict) else None,
            plan_key=str(ctx.get("plan_key") or "") or None,
        )

        if stored_record is not None and case_token:
            CASE_ANALYSIS_STORE.save_case(case=run.case, access_token=case_token)

        return SpecialistResponse(
            specialist=self.name,
            status="completed",
            reply=f"Analysed {document.filename} for {target_plan} and committed grounded evidence to the case.",
            payload={
                "case_id": str(run.case.case_id),
                "target_plan": target_plan,
                "provider": provider_label,
                "envelope": run.envelope,
                "fact_count": len(run.case.facts),
            },
        )


_DOCUMENT_ANALYST = DocumentAnalyst()


def get_document_analyst() -> DocumentAnalyst:
    return _DOCUMENT_ANALYST
