from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from backend.app.cases.intelligence import build_case_intelligence
from backend.app.cases.models import AshlarCase, CaseClient, CaseStatus
from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.core.config import get_settings
from backend.app.policy.engine import PolicyEngine, get_policy_engine
from backend.app.rates.quote_engine import quote_shortlist
from backend.app.schemas.applicant import Applicant
from backend.app.workflows.service import JourneyWorkflowService, WorkflowError, get_journey_workflow

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
from .planner import plan_next_best_action
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

_PLAN_SELECTION_WORDS = (
    "i choose", "i select", "select this plan", "choose this plan", "go with",
    "proceed with this plan", "take this plan", "επιλέγω", "επιλέξω",
    "προχωράω με", "προχωρήσω με",
)
_APPLICATION_WORDS = (
    "application", "apply for the plan", "start the application", "insurance application",
    "application form", "αίτηση", "ξεκινήσουμε την αίτηση", "προχωρήσουμε στην αίτηση",
)
_POLICY_WALLET_WORDS = (
    "policy wallet", "show my policy", "my policy details", "policy card",
    "ασφαλιστήριο μου", "στοιχεία συμβολαίου", "policy summary",
)
_PREAUTHORISATION_WORDS = (
    "pre-authorisation", "pre-authorization", "preauthorisation", "preauthorization",
    "pre approval", "pre-approval", "guarantee of payment", "gop",
    "προέγκριση", "εγγυητική πληρωμής",
)
_CLAIM_WORDS = (
    "submit a claim", "open a claim", "make a claim", "claim reimbursement",
    "insurance claim", "αίτημα αποζημίωσης", "υποβολή αποζημίωσης",
)
_RENEWAL_WORDS = (
    "renewal", "renew my policy", "renew the policy", "renew insurance",
    "ανανέωση", "ανανεώσουμε το συμβόλαιο", "ανανεώσουμε το ασφαλιστήριο",
)

_AFFIRMATIVE_WORDS = (
    "yes", "yes please", "sure", "ok", "okay", "please do", "go ahead",
    "ναι", "βεβαίως", "φυσικά", "προχώρα", "προχωράμε",
)


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def classify_orchestration_intent(message: str) -> OrchestrationDecision:
    """Deterministic top-level router and compound-plan recogniser.

    Routing is deliberately not an LLM task. A model must not decide which
    subsystem is allowed to own a request or whether unverified data can enter
    an insurance workflow. Compound requests may select more than one
    specialist, but the orchestrator controls their order.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().casefold())
    has_document = _contains_any(text, _DOCUMENT_WORDS) and _contains_any(text, _DOCUMENT_ACTIONS)
    has_proposal = _contains_any(text, _PROPOSAL_WORDS) and _contains_any(text, _PROPOSAL_ACTIONS)

    if _contains_any(text, _PREAUTHORISATION_WORDS):
        return OrchestrationDecision(
            intent=OrchestrationIntent.PREAUTHORISATION,
            specialists=[],
            deterministic_engines=["policy_engine", "preauthorisation_workflow"],
            reason="Pre-authorisation is an active-policy workflow governed by policy evidence and case state.",
        )

    if _contains_any(text, _CLAIM_WORDS):
        return OrchestrationDecision(
            intent=OrchestrationIntent.CLAIM,
            specialists=[],
            deterministic_engines=["claim_workflow"],
            reason="Claims are recorded as deterministic lifecycle workflows; document specialists are added only when evidence is attached.",
        )

    if _contains_any(text, _RENEWAL_WORDS):
        return OrchestrationDecision(
            intent=OrchestrationIntent.RENEWAL,
            specialists=[],
            deterministic_engines=["renewal_workflow", "quote_engine"],
            reason="Renewal restarts market review on the same AshlarCase using the deterministic quote engine.",
        )

    if _contains_any(text, _POLICY_WALLET_WORDS):
        return OrchestrationDecision(
            intent=OrchestrationIntent.POLICY_WALLET,
            specialists=[],
            deterministic_engines=["policy_engine", "policy_wallet"],
            reason="Policy Wallet is built only from issued-policy state and verified policy facts.",
        )

    if _contains_any(text, _PLAN_SELECTION_WORDS):
        return OrchestrationDecision(
            intent=OrchestrationIntent.PLAN_SELECTION,
            specialists=[],
            deterministic_engines=["plan_selection_workflow"],
            reason="The client is making the human plan choice; the orchestrator records it without asking an LLM to choose.",
        )

    if _contains_any(text, _APPLICATION_WORDS):
        return OrchestrationDecision(
            intent=OrchestrationIntent.APPLICATION,
            specialists=[],
            deterministic_engines=["application_workflow"],
            reason="Application preparation is a deterministic lifecycle workflow; HAL may later explain missing sections.",
        )

    if _contains_any(text, _COVERAGE_WORDS) and (
        _contains_any(text, _CLINICAL_WORDS) or "asklepios" in text or "kira" in text
    ):
        return OrchestrationDecision(
            intent=OrchestrationIntent.HEALTH_POLICY,
            specialists=[SpecialistName.HEALTH_NAVIGATOR],
            deterministic_engines=["policy_engine"],
            reason="Clinical request plus insurance-coverage language requires Asklepios context and deterministic policy evidence.",
        )

    if has_document and has_proposal:
        return OrchestrationDecision(
            intent=OrchestrationIntent.PROPOSAL,
            specialists=[SpecialistName.DOCUMENT_ANALYST, SpecialistName.PROPOSAL_WRITER],
            deterministic_engines=["document_evidence_engine"],
            reason="The user asked for document analysis followed by a client proposal; evidence must be analysed before Proposal Studio writes anything.",
        )

    if has_proposal:
        return OrchestrationDecision(
            intent=OrchestrationIntent.PROPOSAL,
            specialists=[SpecialistName.PROPOSAL_WRITER],
            deterministic_engines=[],
            reason="The user explicitly asked to create a client proposal or presentation.",
        )

    if has_document:
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
    """One intelligent coordination surface over deterministic engines and specialists."""

    def __init__(
        self,
        *,
        hal_adviser: HalAdviser | None = None,
        document_analyst: DocumentAnalyst | None = None,
        proposal_writer: ProposalWriter | None = None,
        health_navigator: HealthNavigator | None = None,
        policy_engine: PolicyEngine | None = None,
        journey_workflow: JourneyWorkflowService | None = None,
    ):
        self.hal_adviser = hal_adviser or get_hal_adviser()
        self.document_analyst = document_analyst or get_document_analyst()
        self.proposal_writer = proposal_writer or get_proposal_writer()
        self.health_navigator = health_navigator or get_health_navigator()
        self.policy_engine = policy_engine or get_policy_engine()
        self.journey_workflow = journey_workflow or get_journey_workflow()

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
    def _case_intelligence(cls, *, case_id: UUID | None, context: dict[str, Any]) -> dict[str, Any] | None:
        record = cls._stored_record(case_id=case_id, context=context)
        return build_case_intelligence(record.case) if record is not None else None

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

    @staticmethod
    def _market_case_from_discovery(response: SpecialistResponse):
        """Create the shared case as soon as HAL completes the applicant interview.

        This keeps the A-to-Z journey case-centred before the client chooses the
        2–4 plans that will move into detailed comparison.
        """
        payload = response.payload if isinstance(response.payload, dict) else {}
        state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
        quotes = payload.get("quotes") if isinstance(payload.get("quotes"), list) else []
        if not state.get("discovery_complete") or not quotes:
            return None

        fields = {
            key: value
            for key, value in state.items()
            if key in Applicant.model_fields
        }
        try:
            applicant = Applicant(**fields)
        except Exception:
            return None

        sanitized = applicant.model_copy(
            update={"chronic_conditions_note": None},
            deep=True,
        )
        priorities = list(applicant.must_have_keys())
        name = str(state.get("applicant_name") or "Client").strip()[:200] or "Client"
        language = str(state.get("language") or "en")
        if language not in {"en", "el"}:
            language = "en"

        case = AshlarCase(
            status=CaseStatus.MARKET_REVIEW,
            client=CaseClient(display_name=name, preferred_language=language),
            applicant=sanitized,
            needs_profile={
                "priorities": priorities,
                "medical_disclosure_present": bool(applicant.chronic_conditions_disclosed),
            },
            metadata={"created_from": "hal_completed_discovery"},
        )
        return CASE_ANALYSIS_STORE.put(case=case, results=[])

    @staticmethod
    def _workflow_record(*, case_id: UUID | str, case_token: str):
        resolved = AshlarOrchestrator._uuid(case_id)
        token = str(case_token or "").strip()
        if resolved is None or not token:
            raise WorkflowError("An active case_id and case_token are required.", code="active_case_required")
        record = CASE_ANALYSIS_STORE.get(resolved, token)
        if record is None:
            raise WorkflowError("The AshlarCase is unavailable, expired, or unauthorised.", code="case_unavailable")
        return record, token

    @staticmethod
    def _save_workflow_case(*, case: AshlarCase, case_token: str):
        saved = CASE_ANALYSIS_STORE.save_case(case=case, access_token=case_token)
        if saved is None:
            raise WorkflowError("The AshlarCase expired while the workflow was being saved.", code="case_expired")
        return saved

    @staticmethod
    def _workflow_error_response(exc: WorkflowError) -> SpecialistResponse:
        status = "needs_input" if exc.code in {
            "active_case_required",
            "plan_selection_required",
            "application_not_prepared",
            "application_incomplete",
            "policy_required",
            "active_policy_required",
        } else "blocked"
        return SpecialistResponse(
            specialist=SpecialistName.HAL_ADVISER,
            status=status,
            reply=str(exc),
            payload={"workflow_error": exc.code},
        )

    def select_final_plan(
        self,
        *,
        case_id: UUID | str,
        case_token: str,
        plan_key: str,
        selected_by: str = "client",
        note: str | None = None,
    ) -> dict[str, Any]:
        record, token = self._workflow_record(case_id=case_id, case_token=case_token)
        case = record.case.model_copy(deep=True)
        result = self.journey_workflow.select_plan(
            case,
            plan_key=plan_key,
            selected_by=selected_by,
            note=note,
        )
        saved = self._save_workflow_case(case=case, case_token=token)
        return {
            **result.model_dump(mode="json"),
            "case_id": str(saved.case.case_id),
            "case_intelligence": build_case_intelligence(saved.case),
        }

    def prepare_application_workflow(
        self,
        *,
        case_id: UUID | str,
        case_token: str,
    ) -> dict[str, Any]:
        record, token = self._workflow_record(case_id=case_id, case_token=case_token)
        case = record.case.model_copy(deep=True)
        result = self.journey_workflow.prepare_application(case)
        saved = self._save_workflow_case(case=case, case_token=token)
        return {
            **result.model_dump(mode="json"),
            "case_id": str(saved.case.case_id),
            "case_intelligence": build_case_intelligence(saved.case),
        }

    def complete_application_section_workflow(
        self,
        *,
        case_id: UUID | str,
        case_token: str,
        section: str,
    ) -> dict[str, Any]:
        record, token = self._workflow_record(case_id=case_id, case_token=case_token)
        case = record.case.model_copy(deep=True)
        result = self.journey_workflow.complete_application_section(case, section=section)
        saved = self._save_workflow_case(case=case, case_token=token)
        return {
            **result.model_dump(mode="json"),
            "case_id": str(saved.case.case_id),
            "case_intelligence": build_case_intelligence(saved.case),
        }

    def submit_application_workflow(
        self,
        *,
        case_id: UUID | str,
        case_token: str,
    ) -> dict[str, Any]:
        record, token = self._workflow_record(case_id=case_id, case_token=case_token)
        case = record.case.model_copy(deep=True)
        result = self.journey_workflow.submit_application(case)
        saved = self._save_workflow_case(case=case, case_token=token)
        return {
            **result.model_dump(mode="json"),
            "case_id": str(saved.case.case_id),
            "case_intelligence": build_case_intelligence(saved.case),
        }

    def record_policy_issue(
        self,
        *,
        case_id: UUID | str,
        case_token: str,
        policy_number: str,
        provider: str,
        start_date: date,
        renewal_date: date,
        document_refs: list[str] | None = None,
        broker_authorized: bool = False,
    ) -> dict[str, Any]:
        if not broker_authorized:
            raise WorkflowError("Policy issue can only be recorded by an authorised broker workflow.", code="broker_authorisation_required")
        record, token = self._workflow_record(case_id=case_id, case_token=case_token)
        case = record.case.model_copy(deep=True)
        result = self.journey_workflow.issue_policy(
            case,
            policy_number=policy_number,
            provider=provider,
            start_date=start_date,
            renewal_date=renewal_date,
            document_refs=document_refs,
        )
        saved = self._save_workflow_case(case=case, case_token=token)
        return {
            **result.model_dump(mode="json"),
            "case_id": str(saved.case.case_id),
            "case_intelligence": build_case_intelligence(saved.case),
        }

    def policy_wallet(
        self,
        *,
        case_id: UUID | str,
        case_token: str,
    ) -> dict[str, Any]:
        record, token = self._workflow_record(case_id=case_id, case_token=case_token)
        case = record.case.model_copy(deep=True)
        result = self.journey_workflow.build_policy_wallet(case)
        saved = self._save_workflow_case(case=case, case_token=token)
        return {
            **result.model_dump(mode="json"),
            "case_id": str(saved.case.case_id),
            "case_intelligence": build_case_intelligence(saved.case),
        }

    def open_preauthorisation(
        self,
        *,
        case_id: UUID | str,
        case_token: str,
        service_key: str,
        provider_name: str | None = None,
        facility_name: str | None = None,
        planned_date: date | None = None,
        document_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        record, token = self._workflow_record(case_id=case_id, case_token=case_token)
        case = record.case.model_copy(deep=True)
        plan_key = case.selected_plan_key
        coverage = self.policy_engine.check_benefit(
            case=case,
            benefit_key=service_key,
            plan_key=plan_key,
        )
        result = self.journey_workflow.create_preauthorisation(
            case,
            service_key=service_key,
            provider_name=provider_name,
            facility_name=facility_name,
            planned_date=planned_date,
            document_refs=document_refs,
        )
        saved = self._save_workflow_case(case=case, case_token=token)
        return {
            **result.model_dump(mode="json"),
            "policy_evidence": coverage.model_dump(mode="json"),
            "case_id": str(saved.case.case_id),
            "case_intelligence": build_case_intelligence(saved.case),
        }

    def open_claim(
        self,
        *,
        case_id: UUID | str,
        case_token: str,
        service_date: date | None = None,
        amount: float | None = None,
        currency: str | None = None,
        document_refs: list[str] | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        record, token = self._workflow_record(case_id=case_id, case_token=case_token)
        case = record.case.model_copy(deep=True)
        result = self.journey_workflow.create_claim(
            case,
            service_date=service_date,
            amount=amount,
            currency=currency,
            document_refs=document_refs,
            note=note,
        )
        saved = self._save_workflow_case(case=case, case_token=token)
        return {
            **result.model_dump(mode="json"),
            "case_id": str(saved.case.case_id),
            "case_intelligence": build_case_intelligence(saved.case),
        }

    def start_renewal_workflow(
        self,
        *,
        case_id: UUID | str,
        case_token: str,
    ) -> dict[str, Any]:
        record, token = self._workflow_record(case_id=case_id, case_token=case_token)
        case = record.case.model_copy(deep=True)
        result = self.journey_workflow.start_renewal(case)
        quotes = []
        if case.applicant is not None:
            quotes = [
                quote.model_dump(mode="json")
                for quote in quote_shortlist(case.applicant, get_settings())
            ]
        saved = self._save_workflow_case(case=case, case_token=token)
        return {
            **result.model_dump(mode="json"),
            "quotes": quotes,
            "case_id": str(saved.case.case_id),
            "case_intelligence": build_case_intelligence(saved.case),
        }

    def _record_health_navigation(
        self,
        *,
        case_id: UUID | None,
        context: dict[str, Any],
        response: SpecialistResponse,
    ) -> None:
        """Advance stage 17 without copying health narrative into insurance state."""
        if response.status != "completed":
            return
        record = self._stored_record(case_id=case_id, context=context)
        if record is None:
            return
        case = record.case.model_copy(deep=True)
        case.metadata["health_navigation"] = {
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "provider": "asklepios",
        }
        case.touch()
        CASE_ANALYSIS_STORE.save_case(
            case=case,
            access_token=str(context.get("case_token") or ""),
        )

    def _finalize(
        self,
        *,
        case_id: UUID | None,
        decision: OrchestrationDecision,
        context: dict[str, Any],
        responses: list[SpecialistResponse] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> OrchestratorResult:
        final_payload = dict(payload or {})
        intelligence = final_payload.get("case_intelligence")
        if intelligence is None:
            intelligence = self._case_intelligence(case_id=case_id, context=context)
            if intelligence is not None:
                final_payload["case_intelligence"] = intelligence
        final_responses = list(responses or [])
        next_action = plan_next_best_action(
            decision=decision,
            responses=final_responses,
            case_intelligence=intelligence if isinstance(intelligence, dict) else None,
            payload=final_payload,
        )
        return OrchestratorResult(
            case_id=case_id,
            decision=decision,
            responses=final_responses,
            next_best_action=next_action,
            payload=final_payload,
        )

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
        has_document_refs = bool(ctx.get("document_refs"))

        # Context-aware planning: a user can upload documents and simply ask
        # "what do you think?". The orchestrator analyses those server-owned
        # refs before HAL explains them, even if the message did not literally
        # contain the word PDF/document.
        if has_document_refs and decision.intent == OrchestrationIntent.ADVICE:
            decision = decision.model_copy(update={
                "specialists": [SpecialistName.DOCUMENT_ANALYST, SpecialistName.HAL_ADVISER],
                "deterministic_engines": ["document_evidence_engine"],
                "reason": "Server-owned carrier documents are attached, so document evidence is analysed before HAL gives advice.",
            })
            document_response = await self.document_analyst.handle(
                case_id=resolved_case_id,
                message=message,
                context=ctx,
            )
            if document_response.status != "completed":
                return self._finalize(
                    case_id=resolved_case_id,
                    decision=decision,
                    context=ctx,
                    responses=[document_response],
                )
            intelligence = self._case_intelligence(case_id=resolved_case_id, context=ctx)
            if intelligence:
                ctx["case_intelligence"] = intelligence
            advice_response = await self.hal_adviser.handle(
                case_id=resolved_case_id,
                message=message,
                context=ctx,
            )
            return self._finalize(
                case_id=resolved_case_id,
                decision=decision,
                context=ctx,
                responses=[document_response, advice_response],
                payload={"case_intelligence": intelligence} if intelligence else {},
            )

        # Likewise, uploaded document refs imply an evidence-analysis step before
        # a proposal even if the user simply says "prepare the proposal".
        if has_document_refs and decision.intent == OrchestrationIntent.PROPOSAL and SpecialistName.DOCUMENT_ANALYST not in decision.specialists:
            decision = decision.model_copy(update={
                "specialists": [SpecialistName.DOCUMENT_ANALYST, SpecialistName.PROPOSAL_WRITER],
                "deterministic_engines": ["document_evidence_engine"],
                "reason": "Uploaded carrier evidence must be analysed before Proposal Studio prepares the client pack.",
            })

        if decision.intent == OrchestrationIntent.PLAN_SELECTION:
            plan_key = str(ctx.get("plan_key") or "").strip()
            if not plan_key:
                return self._finalize(
                    case_id=resolved_case_id,
                    decision=decision,
                    context=ctx,
                    responses=[SpecialistResponse(
                        specialist=SpecialistName.HAL_ADVISER,
                        status="needs_input",
                        reply="Tell me which plan you want to proceed with.",
                        payload={"required": ["plan_key"]},
                    )],
                )
            try:
                workflow = self.select_final_plan(
                    case_id=resolved_case_id,
                    case_token=str(ctx.get("case_token") or ""),
                    plan_key=plan_key,
                    selected_by=str(ctx.get("selected_by") or "client"),
                )
            except WorkflowError as exc:
                return self._finalize(
                    case_id=resolved_case_id,
                    decision=decision,
                    context=ctx,
                    responses=[self._workflow_error_response(exc)],
                )
            return self._finalize(
                case_id=resolved_case_id,
                decision=decision,
                context=ctx,
                payload={
                    "workflow": workflow,
                    "case_intelligence": workflow.get("case_intelligence"),
                },
            )

        if decision.intent == OrchestrationIntent.APPLICATION:
            try:
                workflow = self.prepare_application_workflow(
                    case_id=resolved_case_id,
                    case_token=str(ctx.get("case_token") or ""),
                )
            except WorkflowError as exc:
                return self._finalize(
                    case_id=resolved_case_id,
                    decision=decision,
                    context=ctx,
                    responses=[self._workflow_error_response(exc)],
                )
            return self._finalize(
                case_id=resolved_case_id,
                decision=decision,
                context=ctx,
                payload={
                    "workflow": workflow,
                    "case_intelligence": workflow.get("case_intelligence"),
                },
            )

        if decision.intent == OrchestrationIntent.POLICY_WALLET:
            try:
                workflow = self.policy_wallet(
                    case_id=resolved_case_id,
                    case_token=str(ctx.get("case_token") or ""),
                )
            except WorkflowError as exc:
                return self._finalize(
                    case_id=resolved_case_id,
                    decision=decision,
                    context=ctx,
                    responses=[self._workflow_error_response(exc)],
                )
            return self._finalize(
                case_id=resolved_case_id,
                decision=decision,
                context=ctx,
                payload={
                    "workflow": workflow,
                    "case_intelligence": workflow.get("case_intelligence"),
                },
            )

        if decision.intent == OrchestrationIntent.PREAUTHORISATION:
            service_key = str(ctx.get("benefit_key") or ctx.get("service_key") or "").strip()
            if not service_key:
                return self._finalize(
                    case_id=resolved_case_id,
                    decision=decision,
                    context=ctx,
                    responses=[SpecialistResponse(
                        specialist=SpecialistName.HAL_ADVISER,
                        status="needs_input",
                        reply="Tell me which treatment, examination or service needs pre-authorisation.",
                        payload={"required": ["benefit_key"]},
                    )],
                )
            try:
                workflow = self.open_preauthorisation(
                    case_id=resolved_case_id,
                    case_token=str(ctx.get("case_token") or ""),
                    service_key=service_key,
                    provider_name=str(ctx.get("provider_name") or "").strip() or None,
                    facility_name=str(ctx.get("facility_name") or "").strip() or None,
                    document_refs=list(ctx.get("document_refs") or []),
                )
            except WorkflowError as exc:
                return self._finalize(
                    case_id=resolved_case_id,
                    decision=decision,
                    context=ctx,
                    responses=[self._workflow_error_response(exc)],
                )
            return self._finalize(
                case_id=resolved_case_id,
                decision=decision,
                context=ctx,
                payload={
                    "workflow": workflow,
                    "policy": workflow.get("policy_evidence"),
                    "case_intelligence": workflow.get("case_intelligence"),
                },
            )

        if decision.intent == OrchestrationIntent.CLAIM:
            try:
                workflow = self.open_claim(
                    case_id=resolved_case_id,
                    case_token=str(ctx.get("case_token") or ""),
                    document_refs=list(ctx.get("document_refs") or []),
                )
            except WorkflowError as exc:
                return self._finalize(
                    case_id=resolved_case_id,
                    decision=decision,
                    context=ctx,
                    responses=[self._workflow_error_response(exc)],
                )
            return self._finalize(
                case_id=resolved_case_id,
                decision=decision,
                context=ctx,
                payload={
                    "workflow": workflow,
                    "case_intelligence": workflow.get("case_intelligence"),
                },
            )

        if decision.intent == OrchestrationIntent.RENEWAL:
            try:
                workflow = self.start_renewal_workflow(
                    case_id=resolved_case_id,
                    case_token=str(ctx.get("case_token") or ""),
                )
            except WorkflowError as exc:
                return self._finalize(
                    case_id=resolved_case_id,
                    decision=decision,
                    context=ctx,
                    responses=[self._workflow_error_response(exc)],
                )
            return self._finalize(
                case_id=resolved_case_id,
                decision=decision,
                context=ctx,
                payload={
                    "workflow": workflow,
                    "quotes": workflow.get("quotes") or [],
                    "case_intelligence": workflow.get("case_intelligence"),
                },
            )

        if decision.intent == OrchestrationIntent.QUOTE:
            applicant = self._applicant_from_context(case_id=resolved_case_id, context=ctx)
            if applicant is not None:
                quotes = quote_shortlist(applicant, get_settings())
                return self._finalize(
                    case_id=resolved_case_id,
                    decision=decision,
                    context=ctx,
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
                if resolved_case_id is None:
                    market_record = self._market_case_from_discovery(response)
                    if market_record is not None:
                        resolved_case_id = market_record.case.case_id
                        state_payload = response.payload.get("state")
                        if isinstance(state_payload, dict):
                            state_payload["_adviser_os_case_id"] = str(market_record.case.case_id)
                            state_payload["_adviser_os_case_token"] = market_record.access_token
                        response.payload["case_id"] = str(market_record.case.case_id)
                        response.payload["case_token"] = market_record.access_token
                        ctx["case_token"] = market_record.access_token
                return self._finalize(
                    case_id=resolved_case_id,
                    decision=decision,
                    context=ctx,
                    responses=[response],
                )
            return self._finalize(
                case_id=resolved_case_id,
                decision=decision,
                context=ctx,
                responses=[SpecialistResponse(
                    specialist=SpecialistName.HAL_ADVISER,
                    status="needs_input",
                    reply="I need the applicant details before the quote engine can price the plans.",
                    payload={"required": ["applicant"]},
                )],
            )

        if decision.intent == OrchestrationIntent.DOCUMENT:
            response = await self.document_analyst.handle(
                case_id=resolved_case_id,
                message=message,
                context=ctx,
            )
            intelligence = self._case_intelligence(case_id=resolved_case_id, context=ctx)
            return self._finalize(
                case_id=resolved_case_id,
                decision=decision,
                context=ctx,
                responses=[response],
                payload={"case_intelligence": intelligence} if intelligence else {},
            )

        if decision.intent == OrchestrationIntent.PROPOSAL:
            responses: list[SpecialistResponse] = []
            if SpecialistName.DOCUMENT_ANALYST in decision.specialists:
                document_response = await self.document_analyst.handle(
                    case_id=resolved_case_id,
                    message=message,
                    context=ctx,
                )
                responses.append(document_response)
                intelligence = self._case_intelligence(case_id=resolved_case_id, context=ctx)
                if document_response.status != "completed":
                    return self._finalize(
                        case_id=resolved_case_id,
                        decision=decision,
                        context=ctx,
                        responses=responses,
                        payload={
                            "case_intelligence": intelligence,
                            "proposal_step": "blocked_until_document_analysis_completes",
                        },
                    )

            intelligence = self._case_intelligence(case_id=resolved_case_id, context=ctx)
            if intelligence and int(intelligence.get("conflict_count") or 0):
                responses.append(SpecialistResponse(
                    specialist=SpecialistName.PROPOSAL_WRITER,
                    status="blocked",
                    reply="The proposal is paused because the active case contains unresolved evidence conflicts.",
                    payload={"required": ["resolve_evidence_conflicts"]},
                ))
                return self._finalize(
                    case_id=resolved_case_id,
                    decision=decision,
                    context=ctx,
                    responses=responses,
                    payload={"case_intelligence": intelligence, "proposal_step": "blocked_by_evidence_conflict"},
                )

            manual_authorised = bool(ctx.get("_authorised_manual_proposal"))
            if intelligence and not intelligence.get("ready_for_proposal") and not manual_authorised:
                responses.append(SpecialistResponse(
                    specialist=SpecialistName.PROPOSAL_WRITER,
                    status="blocked",
                    reply="Before I prepare the client proposal, upload and analyse the applicant-specific carrier quotation for each selected plan.",
                    payload={"required": ["carrier_quotation_evidence"]},
                ))
                return self._finalize(
                    case_id=resolved_case_id,
                    decision=decision,
                    context=ctx,
                    responses=responses,
                    payload={
                        "case_intelligence": intelligence,
                        "proposal_step": "blocked_until_carrier_quotations_are_analysed",
                    },
                )

            proposal_response = await self.proposal_writer.handle(
                case_id=resolved_case_id,
                message=message,
                context=ctx,
            )
            responses.append(proposal_response)
            intelligence = self._case_intelligence(case_id=resolved_case_id, context=ctx)
            return self._finalize(
                case_id=resolved_case_id,
                decision=decision,
                context=ctx,
                responses=responses,
                payload={"case_intelligence": intelligence} if intelligence else {},
            )

        if decision.intent == OrchestrationIntent.HEALTH:
            response = await self.health_navigator.handle(
                case_id=resolved_case_id,
                message=message,
                context=ctx,
            )
            self._record_health_navigation(
                case_id=resolved_case_id,
                context=ctx,
                response=response,
            )
            return self._finalize(
                case_id=resolved_case_id,
                decision=decision,
                context=ctx,
                responses=[response],
            )

        if decision.intent == OrchestrationIntent.HEALTH_POLICY:
            response = await self.health_navigator.handle(
                case_id=resolved_case_id,
                message=message,
                context=ctx,
            )
            self._record_health_navigation(
                case_id=resolved_case_id,
                context=ctx,
                response=response,
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
            return self._finalize(
                case_id=resolved_case_id,
                decision=decision,
                context=ctx,
                responses=[response],
                payload=payload,
            )

        intelligence = self._case_intelligence(case_id=resolved_case_id, context=ctx)
        if intelligence:
            ctx["case_intelligence"] = intelligence

        # Discovery has already created an AshlarCase, but a market-review case
        # is not yet an evidence comparison. A short affirmative such as "Yes"
        # must therefore continue the visible journey instead of falling into
        # evidence-aware advice with an empty comparison snapshot.
        record = self._stored_record(case_id=resolved_case_id, context=ctx)
        state = ctx.get("state") if isinstance(ctx.get("state"), dict) else {}
        normalized_message = re.sub(r"\\s+", " ", str(message or "").strip().casefold())
        if (
            record is not None
            and state.get("discovery_complete")
            and not record.case.selected_plan_keys
            and normalized_message in _AFFIRMATIVE_WORDS
        ):
            applicant = record.case.applicant
            quotes = quote_shortlist(applicant, get_settings()) if applicant is not None else []
            response = SpecialistResponse(
                specialist=SpecialistName.HAL_ADVISER,
                status="completed",
                reply=(
                    "Absolutely. The shortlist is the market-discovery step. "
                    "Now choose 2–4 plans using + Compare. I will create the grounded comparison on this same AshlarCase; "
                    "after that you can attach the actual carrier quotations, brochure/Table of Benefits and policy wording "
                    "for document analysis, conflict checking and the Ashlar Assessment."
                ),
                payload={
                    "state": dict(state),
                    "quotes": [q.model_dump(mode="json") for q in quotes],
                    "excluded_plans": [],
                    "quick_replies": [],
                    "journey": "ipmi",
                    "followup_message": "Select 2–4 plans below, then open Compare. The evidence and Proposal Studio workflow starts from that comparison.",
                    "mode": "adviser_os_market_review_continuation",
                },
            )
            return self._finalize(
                case_id=resolved_case_id,
                decision=decision,
                context=ctx,
                responses=[response],
                payload={"case_intelligence": intelligence} if intelligence else {},
            )

        response = await self.hal_adviser.handle(
            case_id=resolved_case_id,
            message=message,
            context=ctx,
        )

        if resolved_case_id is None:
            market_record = self._market_case_from_discovery(response)
            if market_record is not None:
                resolved_case_id = market_record.case.case_id
                state_payload = response.payload.get("state")
                if isinstance(state_payload, dict):
                    state_payload["_adviser_os_case_id"] = str(market_record.case.case_id)
                    state_payload["_adviser_os_case_token"] = market_record.access_token
                response.payload["case_id"] = str(market_record.case.case_id)
                response.payload["case_token"] = market_record.access_token
                ctx["case_token"] = market_record.access_token
                intelligence = build_case_intelligence(market_record.case)

        return self._finalize(
            case_id=resolved_case_id,
            decision=decision,
            context=ctx,
            responses=[response],
            payload={"case_intelligence": intelligence} if intelligence else {},
        )

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
