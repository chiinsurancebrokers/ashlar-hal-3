"""AshlarCase adapter for the embedded Proposal Studio engine."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any

from backend.app.cases.models import AshlarCase
from backend.app.documents.quality import case_quality

from .client_analysis import generate_client_analysis
from .presentation import build_pptx_bytes
from .report_pdf import build_pdf_bytes


class ProposalGenerationBlocked(ValueError):
    """Raised when the verified extraction is not good enough for a client proposal."""


@dataclass(slots=True)
class ProposalBundle:
    report: dict[str, Any]
    pdf_bytes: bytes
    pptx_bytes: bytes
    quality: dict[str, Any]


def _language(case: AshlarCase, override: str | None = None) -> str:
    if override:
        return override
    value = str(case.client.preferred_language or "en").strip().casefold()
    return "Greek" if value.startswith(("el", "gr")) or "greek" in value else "English"


def _client_profile(case: AshlarCase) -> str:
    explicit = case.needs_profile.get("client_profile") or case.needs_profile.get("profile_summary")
    if explicit:
        return str(explicit)
    applicant = case.applicant
    if not applicant:
        return "Not supplied"
    bits = [
        f"Age {applicant.age}",
        f"resident in {applicant.residence_country}",
        f"family size {applicant.family_size() if hasattr(applicant, 'family_size') else 1 + len(applicant.dependents)}",
    ]
    if applicant.coverage_area:
        bits.append(f"requested cover area {applicant.coverage_area}")
    return "; ".join(bits) + "."


def _client_priorities(case: AshlarCase) -> str:
    explicit = case.needs_profile.get("client_priorities") or case.needs_profile.get("priorities")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    if isinstance(explicit, (list, tuple)):
        values = [str(x).strip() for x in explicit if str(x).strip()]
        if values:
            return "; ".join(values)

    applicant = case.applicant
    if not applicant:
        return "Not supplied"
    labels = {
        "outpatient_required": "out-patient cover",
        "maternity_required": "maternity",
        "dental_required": "dental",
        "mental_health_required": "mental health",
        "wellness_required": "wellness / preventive care",
        "optical_required": "optical",
        "evacuation_required": "evacuation / repatriation",
        "chronic_required": "chronic-condition benefits",
    }
    wants = [label for field, label in labels.items() if getattr(applicant, field, False)]
    if applicant.high_annual_limit_required:
        wants.append("high annual limit")
    if applicant.direct_billing_required:
        wants.append("direct billing")
    if applicant.cross_border_treatment_required:
        wants.append("cross-border treatment")
    if applicant.continuity_portability_required:
        wants.append("continuity / portability")
    return "; ".join(wants) if wants else "No specific benefit priorities supplied."


def _client_sex(case: AshlarCase) -> str:
    # Applicant schema does not yet store sex. Keep this outside medical notes and
    # use only an explicit case field when present; never infer it from name/age.
    value = case.needs_profile.get("client_sex") or case.metadata.get("client_sex") or ""
    return str(value)


def _source_documents(case: AshlarCase) -> list[dict[str, Any]]:
    return [
        {
            "provider": doc.provider,
            "filename": doc.filename,
            "doc_type": doc.document_type,
            "plan_name": doc.plan_key or "",
            "url": doc.metadata.get("source_url") if isinstance(doc.metadata, dict) else "",
        }
        for doc in case.documents
    ]


def generate_case_proposal(
    *,
    case: AshlarCase,
    results: list[dict],
    language: str | None = None,
    strict_narrative: bool = False,
) -> ProposalBundle:
    """Run Proposal Studio against one shared Ashlar case.

    The input ``results`` must already have passed the document orchestrator and
    deterministic target-plan corrections. Proposal Studio may write narrative,
    but the factual matrix remains grounded in those structured results.
    """
    quality = case_quality(results)
    if not quality.get("can_generate"):
        raise ProposalGenerationBlocked(
            "Proposal generation blocked by document quality gate: "
            + json.dumps(quality, ensure_ascii=False, default=str)
        )

    lang = _language(case, language)
    case.needs_profile.setdefault("client_profile", _client_profile(case))
    case.needs_profile.setdefault("client_priorities", _client_priorities(case))
    if _client_sex(case):
        case.needs_profile.setdefault("client_sex", _client_sex(case))

    report = generate_client_analysis(
        case=case,
        results=results,
        language=lang,
        strict=strict_narrative,
    )

    pdf_bytes = build_pdf_bytes(
        client_analysis=report,
        results=results,
        language=lang,
        source_documents=_source_documents(case),
    )
    pptx_bytes = build_pptx_bytes(
        client_analysis=report,
        results=results,
        language=lang,
    )

    assessment = dict(report.get("ashlar_assessment") or {})
    case.recommendation = assessment
    case.proposal = {
        "engine": "ashlar_proposal_studio",
        "engine_version": "v0.5.5-adviser-os",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "language": lang,
        "quality": quality,
        "report": report,
        "formats": ["pdf", "pptx"],
        "pdf_size_bytes": len(pdf_bytes),
        "pptx_size_bytes": len(pptx_bytes),
    }
    case.touch()
    return ProposalBundle(report=report, pdf_bytes=pdf_bytes, pptx_bytes=pptx_bytes, quality=quality)
