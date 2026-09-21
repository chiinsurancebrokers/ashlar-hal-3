from uuid import UUID, uuid5, NAMESPACE_URL

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.app.cases.models import (
    AshlarCase,
    CaseClient,
    CaseStatus,
    Fact,
    FactSource,
    FactSourceType,
    FactStatus,
)
from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.cases.intelligence import build_case_intelligence
from backend.app.core.config import get_settings
from backend.app.documents.quality import case_quality
from backend.app.documents.deep_analysis import prepare_deep_analysis
from backend.app.documents.provider_library import get_proposal_library_client
from backend.app.schemas.applicant import Applicant
from backend.app.rates.quote_engine import quote_shortlist, quote_exclusions, quote_current
from backend.app.evidence.compare_matrix import build_comparison_matrix, matrix_to_dict, NOT_CONFIRMED
from backend.app.evidence.catalogue import verified_plan_catalogue
from backend.app.evidence.catalogue_plan import catalogue_plan
from backend.app.evidence.carrier_profile import carrier_profile
from backend.app.services.adviser import comparison_conclusion

router = APIRouter(prefix="/quotes", tags=["quotes"])


@router.get("/catalogue")
async def catalogue():
    """Verified benefit catalogue; pricing status is explicit and separate."""
    return {
        "plans": verified_plan_catalogue(),
        "rule": "Verified benefits do not imply a live price. Cigna remains quotation-required until verified pricing is loaded.",
    }


@router.post("/preview")
async def preview(applicant: Applicant):
    settings = get_settings()
    try:
        shortlist = quote_shortlist(applicant, settings)
        excluded = quote_exclusions(applicant, settings)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not compute a shortlist: {str(exc)[:180]}")
    return {
        "shortlist": [q.model_dump(mode="json") for q in shortlist],
        "quotes": [q.model_dump(mode="json") for q in shortlist],
        "exclusions": excluded,
    }


class CompareRequest(BaseModel):
    applicant_state: dict = Field(default_factory=dict)
    plan_keys: list[str] = Field(min_length=2, max_length=4)
    language: str = Field(default="en", pattern="^(en|el)$")
    case_id: UUID | None = None
    case_token: str | None = Field(default=None, max_length=256)


def _benefit_field(code: str, label: str) -> str | None:
    text = f"{code} {label}".casefold()
    if "hospital_accommodation" in text:
        return "inpatient"
    if "cancer" in text:
        return "cancer"
    if "chronic" in text:
        return "chronic_conditions"
    if "psychiatric" in text or "mental" in text or "behavioural" in text:
        return "mental_health"
    if "maternity" in text or "pregnan" in text or "childbirth" in text:
        return "maternity"
    if "dental" in text:
        return "dental"
    if "optical" in text or "eye test" in text:
        return "optical"
    if "evacuation" in text or "repatriation" in text:
        return "evacuation_repatriation"
    if "imaging" in text or "mri" in text or "ct scan" in text or "pet scan" in text:
        return "diagnostics_imaging"
    if "wellness" in text or "screening" in text or "physical examination" in text:
        return "preventive"
    if "outpatient" in text or "out-patient" in text:
        return "outpatient"
    return None


def _server_results(selected, matrix_dict: dict) -> list[dict]:
    """Normalize only facts rebuilt by HAL on the server.

    This intentionally does not accept a client-supplied analysis object. The
    browser selects plan keys; HAL recomputes current quotes and only then stores
    this proposal-ready evidence envelope.
    """
    rows = matrix_dict.get("rows") or []
    results: list[dict] = []
    for quote in selected:
        plan_key = quote.plan_key or ""
        benefits: dict[str, str] = {}
        benefit_evidence = []
        waiting_periods = []
        focused_rows: list[dict] = []
        for row in rows:
            value = (row.get("values") or {}).get(plan_key)
            if not value or value == NOT_CONFIRMED:
                continue
            evidence = (row.get("evidence") or {}).get(plan_key) or {}
            benefit_evidence.append({"field": "benefit." + row["benefit_code"], "value": value,
                "document": evidence.get("source"), "page": evidence.get("page"),
                "evidence": value, "version": evidence.get("version")})
            if evidence.get("waiting_period"):
                waiting_periods.append({"benefit": row["label"], "waiting_period": evidence["waiting_period"]})
            focused_rows.append({
                "page": evidence.get("page"),
                "source": evidence.get("source"),
                "benefit_code": row["benefit_code"],
                "benefit": row.get("label") or row.get("benefit_code") or "Benefit",
                "value": value,
            })
            field = _benefit_field(str(row.get("benefit_code") or ""), str(row.get("label") or ""))
            if field:
                detail = f"{row.get('label')}: {value}"
                benefits[field] = (benefits[field] + "; " + detail) if field in benefits else detail

        annual_limit = quote.card_annual_limit or "Not specified"
        deductible = quote.card_deductible or (
            f"{quote.currency} {quote.deductible:g}" if quote.deductible is not None else "Not specified"
        )
        analysis = {
            "provider": quote.insurer,
            "plan_name": quote.product_name,
            "target_plan_found": True,
            "premium": {
                "amount": quote.premium,
                "currency": quote.currency,
                "frequency": "Annual",
            },
            "deductible_or_excess": deductible,
            "annual_limit": annual_limit,
            "area_of_cover": quote.coverage_area_label or "Not specified",
            "underwriting": {
                "basis": "Subject to carrier underwriting",
                "pre_existing_conditions": "Subject to carrier underwriting and governing terms",
            },
            "benefits": benefits,
            "waiting_periods": waiting_periods,
            "optional_benefits": [],
            "critical_limitations": list(quote.warnings or []),
            "source_evidence": benefit_evidence + ([
                {
                    "field": "premium",
                    "value": quote.premium,
                    "document": quote.rate_version,
                    "page": None,
                    "evidence": "Server-recomputed rate; see rate version and warnings for official/legacy status",
                }
            ] if quote.premium is not None else []),
            "confidence": "high" if quote.evidence_confidence >= 1 else "medium",
            "carrier_adapter": {
                "carrier_id": plan_key.split(":")[0] if ":" in plan_key else plan_key,
                "carrier_name": quote.insurer,
                "adapter_level": "server_comparison",
                "benefit_strategy": "structured_tob" if focused_rows else "quote_only",
            },
        }
        results.append({
            "plan_key": plan_key,
            "provider": quote.insurer,
            "target_plan": quote.product_name,
            "focused_rows": focused_rows,
            "analysis": analysis,
            "library_source": bool(focused_rows),
            "pricing_status": getattr(quote, "pricing_status", "priced"),
        })
    return results


def _target_plan_name(quote) -> str:
    name = str(getattr(quote, "product_name", "") or "").strip()
    insurer = str(getattr(quote, "insurer", "") or "").strip()
    for prefix in (insurer, "Morgan Price", "APRIL International", "APRIL", "IMG", "Cigna", "Bupa"):
        if prefix and name.casefold().startswith(prefix.casefold()):
            name = name[len(prefix):].strip(" -–—")
            break
    return name or str(getattr(quote, "product_name", "") or "Plan")


async def _enrich_results_from_provider_library(selected, results: list[dict]) -> list[dict]:
    """Reuse Proposal Studio's persistent brochures/wordings for shortlisted plans.

    Pricing remains owned by the deterministic Quote Engine. Provider Library
    evidence only enriches benefits/terms and keeps its source metadata.
    """
    client = get_proposal_library_client()
    if not client.configured:
        return results

    enriched = []
    for quote, base in zip(selected, results):
        item = dict(base)
        try:
            context = await run_in_threadpool(
                client.plan_context,
                provider_label=quote.insurer,
                target_plan=_target_plan_name(quote),
                product_hint=str(getattr(quote, "product_family", "") or ""),
            )
        except Exception:
            context = None
        if not context:
            enriched.append(item)
            continue

        docs = context.get("documents") or []
        brochure_parts = []
        wording_parts = []
        focused_parts = []
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            text = str(doc.get("extracted_text") or "")
            doc_type = str(doc.get("doc_type") or "").casefold()
            if doc_type in {"brochure", "tob"}:
                brochure_parts.append(text)
            else:
                wording_parts.append(text)
            focused = str(doc.get("focused_table_context") or "")
            if focused:
                focused_parts.append(focused)

        envelope = await run_in_threadpool(
            prepare_deep_analysis,
            provider_label=quote.insurer,
            target_plan=_target_plan_name(quote),
            brochure_text="\n\n".join(brochure_parts),
            wording_text="\n\n".join(wording_parts),
            focused_table_context="\n\n".join(focused_parts),
        )
        library_analysis = envelope.get("analysis") or {}
        analysis = dict(item.get("analysis") or {})
        benefits = dict(analysis.get("benefits") or {})
        for key, value in (library_analysis.get("benefits") or {}).items():
            if value and str(value).strip().casefold() not in {"not mentioned", "not specified", "unknown"}:
                benefits[key] = value
        analysis["benefits"] = benefits
        for key in ("annual_limit", "deductible_or_excess", "area_of_cover"):
            current = str(analysis.get(key) or "").strip().casefold()
            value = library_analysis.get(key)
            if current in {"", "not specified", "annual limit on request"} and value and str(value).casefold() != "not specified":
                analysis[key] = value
        analysis["source_evidence"] = list(analysis.get("source_evidence") or []) + list(library_analysis.get("source_evidence") or [])
        analysis["provider_library"] = {
            "provider": context.get("provider"),
            "product": context.get("product"),
            "version": context.get("version"),
            "document_count": len(docs),
        }
        item["analysis"] = analysis
        item["focused_rows"] = envelope.get("focused_rows") or item.get("focused_rows") or []
        item["library_source"] = bool(docs)
        item["provider_library_source"] = analysis["provider_library"]
        item["evidence_documents"] = [
            {
                "document_type": str(doc.get("doc_type") or "document").casefold(),
                "title": str(doc.get("title") or doc.get("filename") or doc.get("name") or doc.get("doc_type") or "Carrier document"),
                "version": str(doc.get("version") or context.get("version") or ""),
                "official_url": str(doc.get("official_url") or "") if str(doc.get("official_url") or "").startswith("https://") else "",
                "source": "proposal_studio_provider_library",
            }
            for doc in docs if isinstance(doc, dict)
        ]
        enriched.append(item)
    return enriched


def _evidence_document_index(results: list[dict] | None) -> list[dict]:
    documents: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for result in results or []:
        plan_key = str(result.get("plan_key") or "")
        supplied = list(result.get("evidence_documents") or [])
        if not supplied:
            for row in result.get("focused_rows") or []:
                source = str(row.get("source") or "")
                if source:
                    supplied.append({"document_type": "brochure", "title": source, "version": "", "official_url": "", "source": "verified_catalogue"})
        for document in supplied:
            key = (plan_key, str(document.get("document_type") or "document"), str(document.get("title") or "Carrier document"))
            if key in seen:
                continue
            seen.add(key)
            documents.append({"plan_key": plan_key, **document})
    return documents


def _library_evidence_metadata(results: list[dict] | None) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for document in _evidence_document_index(results):
        grouped.setdefault(document["plan_key"], []).append(document)
    return grouped


def _quote_engine_facts(selected) -> list[Fact]:
    """Persist deterministic quote facts into the shared Case Brain.

    This lets later carrier-document evidence be checked against the same facts
    that produced HAL's shortlist rather than against a disconnected snapshot.
    """
    facts: list[Fact] = []
    for quote in selected:
        plan_key = str(getattr(quote, "plan_key", "") or "")
        if not plan_key:
            continue

        provider = str(getattr(quote, "insurer", "") or "") or None
        product_name = str(getattr(quote, "product_name", "") or "") or None
        rate_version = str(getattr(quote, "rate_version", "") or "") or "server_quote_engine"
        subject = f"plan:{plan_key}"
        source = FactSource(
            source_type=FactSourceType.QUOTE_ENGINE,
            source_ref=rate_version,
        )
        base = {
            "subject": subject,
            "provider": provider,
            "plan_key": plan_key,
            "status": FactStatus.VERIFIED,
            "confidence": 1.0,
            "source": source,
        }

        if provider:
            facts.append(Fact(key="provider", value=provider, **base))
        if product_name:
            facts.append(Fact(key="plan_name", value=product_name, **base))

        premium = getattr(quote, "premium", None)
        currency = getattr(quote, "currency", None)
        if premium is not None:
            facts.append(
                Fact(
                    key="premium_amount",
                    value=premium,
                    currency=currency,
                    **base,
                )
            )
            facts.append(Fact(key="premium_frequency", value="Annual", **base))

        area = getattr(quote, "coverage_area_label", None)
        if area and area != "Not specified":
            facts.append(Fact(key="area_of_cover", value=area, **base))

        annual_limit = getattr(quote, "card_annual_limit", None)
        if annual_limit and getattr(quote, "pricing_status", None) != "quotation_required":
            facts.append(Fact(key="annual_limit", value=annual_limit, **base))

        deductible = getattr(quote, "card_deductible", None)
        raw_deductible = getattr(quote, "deductible", None)
        if not deductible and raw_deductible is not None:
            deductible = f"{currency or 'EUR'} {raw_deductible:g}"
        if deductible and deductible != "Not specified":
            facts.append(Fact(key="deductible_or_excess", value=deductible, **base))
    return facts

def _comparison_evidence_facts(results: list[dict] | None) -> list[Fact]:
    """Project server-held benefit-library evidence into the shared FactLedger.

    Only results backed by the structured library are promoted. This is what
    allows uploaded carrier documents to surface a real database-vs-document
    conflict instead of comparing documents only with each other.
    """
    facts: list[Fact] = []
    for result in results or []:
        if not result.get("library_source"):
            continue
        plan_key = str(result.get("plan_key") or "")
        analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
        provider = str(analysis.get("provider") or result.get("provider") or "") or None
        if not plan_key:
            continue
        source = FactSource(
            source_type=FactSourceType.CARRIER_TOB,
            source_ref="server_benefit_library",
        )
        base = {
            "subject": f"plan:{plan_key}",
            "provider": provider,
            "plan_key": plan_key,
            "status": FactStatus.VERIFIED,
            "confidence": 1.0,
            "source": source,
        }
        for row in result.get("focused_rows") or []:
            if not row.get("benefit_code") or not row.get("source"):
                continue
            document_id = uuid5(NAMESPACE_URL, str(row["source"]))
            row_source = FactSource(source_type=FactSourceType.CARRIER_TOB,
                source_ref=row["source"], document_id=document_id, page=row.get("page"),
                quote=str(row["value"])[:800])
            facts.append(Fact(key="benefit." + row["benefit_code"], value=row["value"],
                              **{**base, "source": row_source}))
        precise_codes = {row.get("benefit_code") for row in result.get("focused_rows") or []}
        for benefit, value in (analysis.get("benefits") or {}).items():
            if benefit in precise_codes:
                continue
            if value and str(value).strip().casefold() not in {"not confirmed", "not specified", "unknown"}:
                facts.append(Fact(key=f"benefit.{benefit}", value=value, **base))
    return facts


def _server_case(req: CompareRequest, applicant: Applicant, selected, results: list[dict] | None = None) -> AshlarCase:
    # Medical free text is intentionally excluded from the proposal case store.
    sanitized_applicant = applicant.model_copy(update={"chronic_conditions_note": None}, deep=True)
    priorities = [field for field in applicant.must_have_keys()]
    name = str(req.applicant_state.get("applicant_name") or "Client").strip()[:200] or "Client"
    return AshlarCase(
        status=CaseStatus.COMPARISON,
        client=CaseClient(display_name=name, preferred_language=req.language),
        applicant=sanitized_applicant,
        needs_profile={
            "priorities": priorities,
            "medical_disclosure_present": bool(applicant.chronic_conditions_disclosed),
        },
        selected_plan_keys=[q.plan_key for q in selected if q.plan_key],
        facts=[*_quote_engine_facts(selected), *_comparison_evidence_facts(results)],
        metadata={"created_from": "server_quote_comparison", "library_evidence": _library_evidence_metadata(results)},
    )


def _reuse_market_case(
    req: CompareRequest,
    *,
    applicant: Applicant,
    selected,
    results: list[dict] | None = None,
) -> tuple[AshlarCase, str] | None:
    if req.case_id is None and not req.case_token:
        return None
    if req.case_id is None or not req.case_token:
        raise HTTPException(status_code=422, detail="case_id and case_token must be supplied together.")

    record = CASE_ANALYSIS_STORE.get(req.case_id, req.case_token)
    if record is None:
        raise HTTPException(status_code=404, detail="The active AshlarCase is unavailable or expired.")

    case = record.case.model_copy(deep=True)
    selected_keys = [q.plan_key for q in selected if q.plan_key]
    sanitized_applicant = applicant.model_copy(update={"chronic_conditions_note": None}, deep=True)
    case.status = CaseStatus.RENEWAL if case.renewal else CaseStatus.COMPARISON
    case.applicant = sanitized_applicant
    case.client.display_name = (
        str(req.applicant_state.get("applicant_name") or case.client.display_name or "Client").strip()[:200]
        or "Client"
    )
    case.client.preferred_language = req.language
    case.needs_profile = {
        "priorities": list(applicant.must_have_keys()),
        "medical_disclosure_present": bool(applicant.chronic_conditions_disclosed),
    }
    case.selected_plan_keys = selected_keys

    # Preserve non-quote evidence only for plans that remain selected. The
    # deterministic quote facts are rebuilt from the current rate engine.
    retained = [
        fact
        for fact in case.facts
        if fact.source.source_type != FactSourceType.QUOTE_ENGINE
        and (not fact.plan_key or fact.plan_key in selected_keys or fact.plan_key == "existing_policy" or bool(case.policy))
    ]
    case.facts = [
        *retained,
        *_quote_engine_facts(selected),
        *_comparison_evidence_facts(results),
    ]
    case.documents = [
        document
        for document in case.documents
        if not document.plan_key or document.plan_key in selected_keys or document.plan_key == "existing_policy" or bool(case.policy)
    ]
    case.metadata["comparison_updated_from"] = "server_quote_comparison"
    case.metadata["library_evidence"] = _library_evidence_metadata(results)
    case.touch()
    return case, req.case_token


@router.post("/compare")
async def compare(req: CompareRequest):
    """Detailed benefit-by-benefit comparison.

    Plan identity, eligibility, premium and evidence are rebuilt server-side.
    A sanitized AshlarCase + normalized analysis snapshot is then stored on the
    server and referenced by an opaque token for subsequent proposal generation.
    """
    settings = get_settings()
    try:
        fields = {k: v for k, v in req.applicant_state.items() if k in Applicant.model_fields}
        applicant = Applicant(**fields)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid applicant_state: {str(exc)[:180]}") from exc

    all_current = quote_current(applicant, settings)
    by_key = {q.plan_key: q for q in all_current if q.plan_key}
    catalogue_by_key = {p["plan_key"]: p for p in verified_plan_catalogue()}
    selected = []
    if len(set(req.plan_keys)) != len(req.plan_keys):
        raise HTTPException(status_code=422, detail="Select distinct plans for comparison.")
    for key in req.plan_keys:
        row = catalogue_by_key.get(key)
        # GPMI and Inspire are benefit-only entries. Never attach an older
        # similarly named rate product to these brochure families.
        if row and row["carrier"] in {"img", "cigna"}:
            selected.append(catalogue_plan(row))
        elif key in by_key:
            selected.append(by_key[key])
        else:
            raise HTTPException(status_code=400, detail="Unknown or currently ineligible plan_key: " + key)

    plans_for_matrix = [
        {"plan_key": q.plan_key, "carrier": ("img_legacy" if q.plan_key.startswith("img:") and getattr(q, "pricing_status", None) != "quotation_required" else q.plan_key.split(":")[0]), "product_code": q.product_code,
         "insurer": q.insurer, "product_name": q.product_name}
        for q in selected
    ]
    matrix = build_comparison_matrix(plans_for_matrix)
    matrix_dict = matrix_to_dict(matrix)

    conclusion = await comparison_conclusion(matrix_dict["rows"], matrix_dict["plan_labels"], greek=(req.language == "el"))
    carrier_meta = {q.plan_key: carrier_profile(q.plan_key.split(":")[0]) for q in selected}

    results = _server_results(selected, matrix_dict)
    results = await _enrich_results_from_provider_library(selected, results)
    reused = _reuse_market_case(
        req,
        applicant=applicant,
        selected=selected,
        results=results,
    )
    if reused is None:
        case = _server_case(req, applicant, selected, results)
        record = CASE_ANALYSIS_STORE.put(case=case, results=results)
    else:
        case, access_token = reused
        record = CASE_ANALYSIS_STORE.save_analysis(
            case=case,
            results=results,
            access_token=access_token,
        )
        if record is None:
            raise HTTPException(status_code=409, detail="The AshlarCase expired while the comparison was being saved.")
    quality = case_quality(results)
    intelligence = build_case_intelligence(record.case)

    return {
        "plans": [q.model_dump(mode="json") for q in selected],
        "matrix": matrix_dict,
        "carrier_profiles": carrier_meta,
        "conclusion": conclusion,
        "unsupported_note": (
            f"No detailed Table of Benefits is loaded yet for: {', '.join(matrix.unsupported_plan_keys)}. "
            "These plans are included in the price comparison above but not in the row-by-row benefit table."
        ) if matrix.unsupported_plan_keys else None,
        "case_id": str(record.case.case_id),
        "case_token": record.access_token,
        "case_expires_at": record.expires_at.isoformat(),
        "proposal_available": bool(intelligence.get("ready_for_proposal")),
        "proposal_quality": quality,
        "case_intelligence": intelligence,
        "evidence_documents": _evidence_document_index(results),
    }
