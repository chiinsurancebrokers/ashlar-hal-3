from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.core.config import get_settings
from backend.app.policy.engine import PolicyEngine, get_policy_engine
from backend.app.rates.quote_engine import quote_shortlist
from backend.app.schemas.applicant import Applicant

from .contracts import (
    OrchestrationDecision,
    OrchestrationIntent,
    OrchestratorResult,
    SpecialistName,
    SpecialistResponse,
)
from .document_analyst import DocumentAnalyst, get_document_analyst
from .hal_adviser import HalAdviser, get_hal_adviser
from .health_navigator import HealthNavigator, get_health_navigator
from .proposal_writer import ProposalWriter, get_proposal_writer


_DOCUMENT_WORDS = (
    "pdf", "document", "documents", "brochure", "tob", "terms of benefits",
    "policy wording", "quotation", "quote file", "carrier file", "έγγραφο", "έγγραφα",
    "προσφορά pdf", "όρους", "ασφαλιστήριο",
)
_DOCUMENT_ACTIONS = (
    "compare", "analyse", "analyze", "review", "read", "extract", "check",
    "σύγκρι", "ανάλυσ", "διάβα", "έλεγξ",
)
_PROPOSAL_WORDS = (
    "proposal", "presentation", "client report", "powerpoint", "pptx",
    "πρόταση", "παρουσίαση", "report πελάτη",
)
_PROPOSAL_ACTIONS = (
    "create", "prepare", "generate", "make", "build", "write", "produce",
    "φτιάξ", "ετοίμα", "δημιούργ", "γράψ",
)
_QUOTE_WORDS = (
    "how much", "cost", "price", "premium", "premiums", "quotation", "quote me",
    "πόσο", "κόστος", "τιμή", "ασφάλιστρο", "ασφάλιστρα",
)
_ADVICE_WORDS = (
    "why", "recommend", "recommendation", "explain", "which plan", "difference",
    "γιατί", "προτείν", "σύσταση", "εξήγη", "ποιο πρόγραμμα", "διαφορά",
)
_COVERAGE_WORDS = (
    "covered", "coverage", "cover this", "insured", "reimburse", "reimbursement",
    "policy cover", "benefit", "eligible under", "καλύπτε", "κάλυψη", "αποζημι",
    "ασφαλιστήριο", "παροχή",
)
_CLINICAL_WORDS = (
    "ct", "ct scan", "mri", "scan", "x-ray", "ultrasound", "test", "exam",
    "surgery", "operation", "treatment", "therapy", "medication", "medicine",
    "hospital", "doctor", "specialist", "colonoscopy", "gastroscopy",
    "αξονικ", "μαγνητικ", "εξέταση", "χειρουργ", "θεραπε", "φάρμακ", "νοσοκομ",
)
_HEALTH_WORDS = (
    "asklepios", "kira", "severe pain", "pain", "fever", "vomit", "vomiting",
    "bleeding", "blood", "dizzy", "dizziness", "stomach pain", "chest pain",
    "shortness of breath", "symptom", "symptoms", "πόνο", "πόνος", "πυρετ",
    "εμετ", "αιμορραγ", "ζάλη", "σύμπτωμ", "στομάχι", "στήθος",
)


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def classify_orchestration_intent(message: str) -> OrchestrationDecision:
    """Deterministic top-level router.

    Routing is deliberately not an LLM task. A model must not decide which
    subsystem is allowed to own a request or whether unverified data can enter
    an insurance workflow.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().casefold())

    if _contains_any(text, _COVERAGE_WORDS) and (
        _contains_any(text, _CLINICAL_WORDS) or "asklepios" in text or "kira" in text
    ):
        return OrchestrationDecision(
            intent=OrchestrationIntent.HEALTH_POLICY,
            specialists=[SpecialistName.HEALTH_NAVIGATOR],
            deterministic_engines=["policy_engine"],
            reason="Clinical request plus insurance-coverage language requires Asklepios context and deterministic policy evidence.",
        )

    if _contains_any(text, _PROPOSAL_WORDS) and _contains_any(text, _PROPOSAL_ACTIONS):
        return OrchestrationDecision(
            intent=OrchestrationIntent.PROPOSAL,
            specialists=[SpecialistName.PROPOSAL_WRITER],
            deterministic_engines=[],
            reason="The user explicitly asked to create a client proposal or presentation.",
        )

    if _contains_any(text, _DOCUMENT_WORDS) and _contains_any(text, _DOCUMENT_ACTIONS):
        return OrchestrationDecision(
            intent=OrchestrationIntent.DOCUMENT,
            specialists=[SpecialistName.DOCUMENT_ANALYST],
            deterministic_engines=["document_evidence_engine"],
            reason="The request is to inspect or compare carrier documents.",
        )

    if _contains_any(text, _HEALTH_WORDS):
        return OrchestrationDecision(
            intent=OrchestrationIntent.HEALTH,
            specialists=[SpecialistName.HEALTH_NAVIGATOR],
            deterministic_engines=[],
            reason="The message is primarily a symptom or health-navigation request.",
        )

    if _contains_any(text, _QUOTE_WORDS):
        return OrchestrationDecision(
            intent=OrchestrationIntent.QUOTE,
            specialists=[],
            deterministic_engines=["quote_engine"],
            reason="Price and premium questions are answered by the deterministic quote engine, not an LLM.",
        )

    if _contains_any(text, _ADVICE_WORDS):
        return OrchestrationDecision(
            intent=OrchestrationIntent.ADVICE,
            specialists=[SpecialistName.HAL_ADVISER],
            deterministic_engines=[],
            reason="The user is asking HAL to explain, compare reasoning, or advise.",
        )

    return OrchestrationDecision(
        intent=OrchestrationIntent.ADVICE,
        specialists=[SpecialistName.HAL_ADVISER],
        deterministic_engines=[],
        reason="General insurance conversation defaults to the HAL adviser specialist.",
    )


class AshlarOrchestrator:
    """One routing surface over deterministic engines and specialist agents."""

    def __init__(
        self,
        *,
        hal_adviser: HalAdviser | None = None,
        document_analyst: DocumentAnalyst | None = None,
        proposal_writer: ProposalWriter | None = None,
        health_navigator: HealthNavigator | None = None,
        policy_engine: PolicyEngine | None = None,
    ):
        self.hal_adviser = hal_adviser or get_hal_adviser()
        self.document_analyst = document_analyst or get_document_analyst()
        self.proposal_writer = proposal_writer or get_proposal_writer()
        self.health_navigator = health_navigator or get_health_navigator()
        self.policy_engine = policy_engine or get_policy_engine()

    @staticmethod
    def _uuid(value: UUID | str | None) -> UUID | None:
        if value is None or isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _stored_record(*, case_id: UUID | None, context: dict[str, Any]):
        case_token = str(context.get("case_token") or "")
        if case_id is None or not case_token:
            return None
        return CASE_ANALYSIS_STORE.get(case_id, case_token)

    @classmethod
    def _applicant_from_context(
        cls,
        *,
        case_id: UUID | None,
        context: dict[str, Any],
    ) -> Applicant | None:
        value = context.get("applicant")
        if isinstance(value, Applicant):
            return value
        if isinstance(value, dict):
            try:
                return Applicant(**value)
            except Exception:
                pass

        record = cls._stored_record(case_id=case_id, context=context)
        return record.case.applicant if record is not None else None

    async def handle(
        self,
        *,
        case_id: UUID | str | None,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> OrchestratorResult:
        resolved_case_id = self._uuid(case_id)
        ctx = dict(context or {})
        decision = classify_orchestration_intent(message)

        if decision.intent == OrchestrationIntent.QUOTE:
            applicant = self._applicant_from_context(case_id=resolved_case_id, context=ctx)
            if applicant is not None:
                quotes = quote_shortlist(applicant, get_settings())
                return OrchestratorResult(
                    case_id=resolved_case_id,
                    decision=decision,
                    payload={"quotes": [q.model_dump(mode="json") for q in quotes]},
                )
            if "state" in ctx:
                response = await self.hal_adviser.handle(
                    case_id=resolved_case_id,
                    message=message,
                    context=ctx,
                )
                decision = decision.model_copy(update={
                    "specialists": [SpecialistName.HAL_ADVISER],
                    "reason": decision.reason + " HAL is collecting missing quote inputs first.",
                })
                return OrchestratorResult(case_id=resolved_case_id, decision=decision, responses=[response])
            return OrchestratorResult(
                case_id=resolved_case_id,
                decision=decision,
                responses=[SpecialistResponse(
                    specialist=SpecialistName.HAL_ADVISER,
                    status="needs_input",
                    reply="I need the applicant details before the quote engine can price the plans.",
                )],
            )

        if decision.intent == OrchestrationIntent.DOCUMENT:
            response = await self.document_analyst.handle(
                case_id=resolved_case_id,
                message=message,
                context=ctx,
            )
            return OrchestratorResult(case_id=resolved_case_id, decision=decision, responses=[response])

        if decision.intent == OrchestrationIntent.PROPOSAL:
            response = await self.proposal_writer.handle(
                case_id=resolved_case_id,
                message=message,
                context=ctx,
            )
            return OrchestratorResult(case_id=resolved_case_id, decision=decision, responses=[response])

        if decision.intent == OrchestrationIntent.HEALTH:
            response = await self.health_navigator.handle(
                case_id=resolved_case_id,
                message=message,
                context=ctx,
            )
            return OrchestratorResult(case_id=resolved_case_id, decision=decision, responses=[response])

        if decision.intent == OrchestrationIntent.HEALTH_POLICY:
            response = await self.health_navigator.handle(
                case_id=resolved_case_id,
                message=message,
                context=ctx,
            )
            benefit_key = str(ctx.get("benefit_key") or response.payload.get("benefit_key") or "").strip()
            payload: dict[str, Any] = {
                "next_engine": "policy_engine",
                "requires_verified_policy_evidence": True,
                "health_to_insurance_consent_required": True,
            }
            record = self._stored_record(case_id=resolved_case_id, context=ctx)
            if benefit_key and record is not None:
                coverage = self.policy_engine.check_benefit(
                    case=record.case,
                    benefit_key=benefit_key,
                    plan_key=str(ctx.get("plan_key") or "").strip() or None,
                )
                payload["policy"] = coverage.model_dump(mode="json")
                payload["next_engine"] = None
            else:
                payload["policy"] = {
                    "verdict": "unknown",
                    "reason": "A clinical benefit key and an active server-owned policy case are required before coverage can be checked.",
                }
            return OrchestratorResult(
                case_id=resolved_case_id,
                decision=decision,
                responses=[response],
                payload=payload,
            )

        response = await self.hal_adviser.handle(
            case_id=resolved_case_id,
            message=message,
            context=ctx,
        )
        return OrchestratorResult(case_id=resolved_case_id, decision=decision, responses=[response])

    async def handle_legacy_chat(
        self,
        *,
        message: str,
        state: dict[str, Any] | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Compatibility bridge for the current HAL UI.

        It intentionally preserves the existing response shape while ensuring
        the conversational model path now enters through ``hal_adviser``.
        """
        return await self.hal_adviser.run_chat(message=message, state=state, history=history)


_ASHLAR_ORCHESTRATOR = AshlarOrchestrator()


def get_ashlar_orchestrator() -> AshlarOrchestrator:
    return _ASHLAR_ORCHESTRATOR
