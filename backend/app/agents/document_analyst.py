from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from backend.app.cases.models import AshlarCase, CaseDocument
from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.documents.orchestrator import analyze_and_apply_document_bundle
from backend.app.documents.store import DOCUMENT_EVIDENCE_STORE

from .contracts import SpecialistName, SpecialistResponse
from .document_extraction_model import extract_candidate_analysis
from .document_synthesis import synthesize_server_documents



_MISSING = {
    "",
    "not specified",
    "not mentioned",
    "unknown",
    "not confirmed",
    "n/a",
    "none",
    "null",
}


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, dict) and "amount" in value:
        return _missing(value["amount"])
    if isinstance(value, str):
        return value.strip().casefold() in _MISSING
    return False


def _merge_unique(base: list[Any] | None, extra: list[Any] | None) -> list[Any]:
    merged: list[Any] = []
    signatures: set[str] = set()
    for item in list(base or []) + list(extra or []):
        signature = repr(item)
        if signature in signatures:
            continue
        signatures.add(signature)
        merged.append(deepcopy(item))
    return merged


def _merge_document_analysis(
    results: list[dict[str, Any]],
    *,
    plan_key: str | None,
    envelope: dict[str, Any],
    role: str,
) -> list[dict[str, Any]]:
    """Merge document findings without weakening deterministic quote authority."""
    merged_results = deepcopy(results)
    if not plan_key:
        return merged_results

    document_analysis = deepcopy(envelope.get("analysis") or {})
    focused_rows = deepcopy(envelope.get("focused_rows") or [])
    target_index = next(
        (
            index
            for index, item in enumerate(merged_results)
            if str(item.get("plan_key") or "") == str(plan_key)
        ),
        None,
    )

    if target_index is None:
        merged_results.append({
            "plan_key": plan_key,
            "provider": document_analysis.get("provider") or envelope.get("provider"),
            "target_plan": document_analysis.get("plan_name") or envelope.get("target_plan"),
            "focused_rows": focused_rows,
            "analysis": document_analysis,
            "library_source": bool(focused_rows),
            "document_evidence_present": True,
        })
        return merged_results

    target = deepcopy(merged_results[target_index])
    base_analysis = deepcopy(target.get("analysis") or {})
    combined = deepcopy(base_analysis)

    for key, value in document_analysis.items():
        if key in {"provider", "plan_name", "premium", "benefits", "source_evidence"}:
            continue
        if key in {"waiting_periods", "optional_benefits", "critical_limitations"}:
            combined[key] = _merge_unique(
                base_analysis.get(key),
                value if isinstance(value, list) else [],
            )
            continue
        if key == "underwriting" and isinstance(value, dict):
            underwriting = deepcopy(base_analysis.get("underwriting") or {})
            for subkey, subvalue in value.items():
                if not _missing(subvalue):
                    underwriting[subkey] = deepcopy(subvalue)
            combined["underwriting"] = underwriting
            continue
        if _missing(combined.get(key)) and not _missing(value):
            combined[key] = deepcopy(value)

    for protected in (
        "provider",
        "plan_name",
        "premium",
        "deductible_or_excess",
        "annual_limit",
        "area_of_cover",
    ):
        base_value = base_analysis.get(protected)
        doc_value = document_analysis.get(protected)
        combined[protected] = deepcopy(
            base_value if not _missing(base_value) else doc_value
        )

    benefits = deepcopy(base_analysis.get("benefits") or {})
    for benefit, value in (document_analysis.get("benefits") or {}).items():
        if _missing(value):
            continue
        if role.casefold() in {"quotation", "quote", "carrier_quote"} or _missing(benefits.get(benefit)):
            benefits[benefit] = deepcopy(value)
    combined["benefits"] = benefits
    combined["source_evidence"] = _merge_unique(
        base_analysis.get("source_evidence"),
        document_analysis.get("source_evidence")
        if isinstance(document_analysis.get("source_evidence"), list)
        else [],
    )

    target["analysis"] = combined
    target["focused_rows"] = _merge_unique(target.get("focused_rows"), focused_rows)
    target["library_source"] = bool(target.get("library_source") or focused_rows)
    target["document_evidence_present"] = True
    merged_results[target_index] = target
    return merged_results

class DocumentAnalyst:
    """Proposal Studio's document/evidence specialist.

    Public Adviser OS flows pass only opaque ``document_refs``. Those references
    are resolved against the server-owned document store using the same case
    token that authorised the upload. Raw extracted carrier text and model
    output are therefore never trusted when they arrive from a browser.

    Each source is analysed independently so provenance stays attached to the
    real CaseDocument. A constrained model may extract candidate facts from
    difficult wording, but deterministic quote/table evidence is reapplied
    afterwards and every committed model-derived fact remains EXTRACTED rather
    than becoming VERIFIED merely because an LLM returned it.
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

    async def _handle_server_documents(
        self,
        *,
        case_id: UUID | None,
        case_token: str,
        document_refs: list[str],
    ) -> SpecialistResponse:
        if case_id is None or not case_token:
            return SpecialistResponse(
                specialist=self.name,
                status="needs_input",
                reply="Document analysis needs an active case before carrier documents can be analysed.",
                payload={"required": ["case_id", "case_token", "document_refs"]},
            )

        stored_record = CASE_ANALYSIS_STORE.get(case_id, case_token)
        if stored_record is None:
            return SpecialistResponse(
                specialist=self.name,
                status="needs_input",
                reply="The case is unavailable, expired, or the access token is invalid.",
                payload={"required": ["active_case"]},
            )

        records = []
        for document_ref in document_refs:
            item = DOCUMENT_EVIDENCE_STORE.get(
                document_ref,
                case_id=case_id,
                case_token=case_token,
            )
            if item is None:
                # Fail closed. Silently skipping a missing document could make a
                # comparison appear complete when material carrier evidence was
                # actually absent or belonged to another case.
                return SpecialistResponse(
                    specialist=self.name,
                    status="blocked",
                    reply="One or more document references are invalid, expired, or belong to another case.",
                    payload={"invalid_document_ref": document_ref},
                )
            records.append(item)

        if not records:
            return SpecialistResponse(
                specialist=self.name,
                status="needs_input",
                reply="Upload at least one carrier document before asking me to compare the PDFs.",
                payload={"required": ["document_refs"]},
            )

        case = stored_record.case.model_copy(deep=True)
        proposal_results = deepcopy(stored_record.results)
        analyses: list[dict[str, Any]] = []

        # Analyse each source independently so every Fact retains the real
        # originating CaseDocument. The FactLedger can then surface genuine
        # quote/brochure/wording conflicts instead of hiding provenance.
        for item in records:
            role = item.role.casefold()
            kwargs = {
                "quotation_text": item.extracted_text if role == "quotation" else "",
                "brochure_text": item.extracted_text if role == "brochure" else "",
                "wording_text": item.extracted_text if role in {"wording", "existing_policy"} else "",
                "focused_table_context": item.focused_table_context if role == "brochure" else "",
            }

            candidate = await extract_candidate_analysis(item)
            run = await run_in_threadpool(
                analyze_and_apply_document_bundle,
                case,
                document=item.document,
                provider_label=item.provider_label,
                target_plan=item.target_plan,
                model_result=candidate,
                plan_key=item.plan_key,
                **kwargs,
            )
            case = run.case
            proposal_results = _merge_document_analysis(
                proposal_results,
                plan_key=item.plan_key,
                envelope=run.envelope,
                role=item.role,
            )
            if role == "existing_policy":
                for result in proposal_results:
                    if str(result.get("plan_key") or "") == "existing_policy":
                        result["comparison_role"] = "current_policy"
                        result["client_supplied_baseline"] = True
            # Do not return run.envelope here. It contains the deep-analysis
            # prompt and therefore extracted document text. Public clients only
            # receive metadata and the separately sanitised synthesis below.
            analyses.append({
                "document_ref": item.document_ref,
                "document_id": str(item.document.document_id),
                "filename": item.document.filename,
                "role": item.role,
                "provider": item.provider_label,
                "target_plan": item.target_plan,
                "plan_key": item.plan_key,
                "target_plan_table_isolated": bool(item.focused_table_context),
                "candidate_model_used": candidate is not None,
                "quality": run.bridge.quality,
                "added_fact_count": run.bridge.added_fact_count,
                "conflict_keys": list(run.bridge.conflict_keys),
                "fact_count_after_document": len(case.facts),
            })

        saved = CASE_ANALYSIS_STORE.save_analysis(
            case=case,
            results=proposal_results,
            access_token=case_token,
        )
        if saved is None:
            return SpecialistResponse(
                specialist=self.name,
                status="unavailable",
                reply="The case expired while the carrier documents were being analysed. Please rebuild the comparison.",
            )

        synthesis = await synthesize_server_documents(records, case=case)
        summary = str(synthesis.get("executive_summary") or "").strip()
        reply = summary or f"Analysed {len(records)} carrier document(s) and committed grounded evidence to the active case."

        return SpecialistResponse(
            specialist=self.name,
            status="completed",
            reply=reply,
            payload={
                "case_id": str(case.case_id),
                "document_count": len(records),
                "fact_count": len(case.facts),
                "analysis_result_count": len(proposal_results),
                "analyses": analyses,
                "model_synthesis": synthesis,
            },
        )

    async def handle(
        self,
        *,
        case_id: UUID | None,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> SpecialistResponse:
        ctx = context or {}
        case_token = str(ctx.get("case_token") or "")
        raw_refs = ctx.get("document_refs")
        if isinstance(raw_refs, list):
            document_refs = [str(value).strip() for value in raw_refs if str(value).strip()]
            return await self._handle_server_documents(
                case_id=case_id,
                case_token=case_token,
                document_refs=document_refs,
            )

        # Internal/broker compatibility path. Public Adviser OS request models do
        # not expose these raw evidence fields.
        case = ctx.get("case")
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
            proposal_results = _merge_document_analysis(
                stored_record.results,
                plan_key=str(ctx.get("plan_key") or "") or document.plan_key,
                envelope=run.envelope,
                role=document.document_type,
            )
            CASE_ANALYSIS_STORE.save_analysis(
                case=run.case,
                results=proposal_results,
                access_token=case_token,
            )

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
