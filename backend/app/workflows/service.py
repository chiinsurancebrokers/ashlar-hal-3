from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any

from backend.app.cases.fact_ledger import FactLedger
from backend.app.cases.models import AshlarCase, CaseStatus, FactStatus

from .models import (
    ApplicationRecord,
    ApplicationStatus,
    ClaimRecord,
    PlanSelectionRecord,
    PolicyRecord,
    PolicyWallet,
    PreauthorisationRecord,
    RenewalRecord,
    WorkflowResult,
)


class WorkflowError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_workflow_state"):
        super().__init__(message)
        self.code = code


class JourneyWorkflowService:
    """Deterministic lifecycle services for Adviser OS stages 13–20.

    These methods mutate only an in-memory AshlarCase copy supplied by the
    orchestrator. They never call an LLM and never bypass FactLedger/Policy
    Engine authority.
    """

    @staticmethod
    def _require_selected_plan(case: AshlarCase) -> str:
        plan_key = str(case.selected_plan_key or "").strip()
        if not plan_key:
            raise WorkflowError(
                "A final plan must be selected before this workflow can continue.",
                code="plan_selection_required",
            )
        return plan_key

    def select_plan(
        self,
        case: AshlarCase,
        *,
        plan_key: str,
        selected_by: str = "client",
        note: str | None = None,
    ) -> WorkflowResult:
        selected = str(plan_key or "").strip()
        if not selected or selected not in case.selected_plan_keys:
            raise WorkflowError(
                "The selected plan must belong to the active 2–4 plan shortlist.",
                code="invalid_selected_plan",
            )

        record = PlanSelectionRecord(
            plan_key=selected,
            selected_by="broker" if selected_by == "broker" else "client",
            note=note,
        )
        case.selected_plan_key = selected
        case.metadata["plan_selection"] = record.model_dump(mode="json")
        case.touch()
        return WorkflowResult(
            action="prepare_application",
            message="The final plan choice has been recorded on the AshlarCase.",
            payload={
                "selected_plan_key": selected,
                "selection": record.model_dump(mode="json"),
            },
        )

    def prepare_application(self, case: AshlarCase) -> WorkflowResult:
        plan_key = self._require_selected_plan(case)
        if case.application:
            current = ApplicationRecord.model_validate(case.application)
        else:
            required = [
                "applicant_identity",
                "contact_and_residency",
                "coverage_selection",
                "declarations",
                "signature",
            ]
            if bool(case.needs_profile.get("medical_disclosure_present")):
                required.insert(4, "medical_underwriting_questionnaire")
            current = ApplicationRecord(
                plan_key=plan_key,
                required_sections=required,
            )
            case.application = current.model_dump(mode="json")

        case.status = CaseStatus.APPLICATION
        case.touch()
        return WorkflowResult(
            action="complete_application",
            message="The application workspace is ready.",
            payload={
                "application": current.model_dump(mode="json"),
                "missing_sections": current.missing_sections,
            },
        )

    def complete_application_section(
        self,
        case: AshlarCase,
        *,
        section: str,
    ) -> WorkflowResult:
        self._require_selected_plan(case)
        if not case.application:
            raise WorkflowError(
                "Prepare the application before completing its sections.",
                code="application_not_prepared",
            )
        record = ApplicationRecord.model_validate(case.application)
        value = str(section or "").strip()
        if value not in record.required_sections:
            raise WorkflowError(
                "That section is not part of this application checklist.",
                code="unknown_application_section",
            )
        if value not in record.completed_sections:
            record.completed_sections.append(value)
        record.status = (
            ApplicationStatus.READY
            if not record.missing_sections
            else ApplicationStatus.DRAFT
        )
        case.application = record.model_dump(mode="json")
        case.touch()
        return WorkflowResult(
            action="submit_application" if record.status == ApplicationStatus.READY else "complete_application",
            message=(
                "The application is ready for submission."
                if record.status == ApplicationStatus.READY
                else "Application section completed."
            ),
            payload={
                "application": record.model_dump(mode="json"),
                "missing_sections": record.missing_sections,
            },
        )

    def submit_application(self, case: AshlarCase) -> WorkflowResult:
        if not case.application:
            raise WorkflowError("No application is prepared.", code="application_not_prepared")
        record = ApplicationRecord.model_validate(case.application)
        if record.missing_sections:
            raise WorkflowError(
                "The application still has incomplete required sections.",
                code="application_incomplete",
            )
        record.status = ApplicationStatus.SUBMITTED
        case.application = record.model_dump(mode="json")
        case.status = CaseStatus.APPLICATION
        case.touch()
        return WorkflowResult(
            action="await_policy_issue",
            message="The application is recorded as submitted.",
            payload={"application": record.model_dump(mode="json")},
        )

    def issue_policy(
        self,
        case: AshlarCase,
        *,
        policy_number: str,
        provider: str,
        start_date: date,
        renewal_date: date,
        document_refs: list[str] | None = None,
    ) -> WorkflowResult:
        plan_key = self._require_selected_plan(case)
        if not case.application:
            raise WorkflowError(
                "An application record is required before policy issue.",
                code="application_required",
            )
        application = ApplicationRecord.model_validate(case.application)
        if application.status != ApplicationStatus.SUBMITTED:
            raise WorkflowError(
                "The application must be submitted before policy issue is recorded.",
                code="application_not_submitted",
            )

        policy = PolicyRecord(
            policy_number=policy_number,
            provider=provider,
            plan_key=plan_key,
            start_date=start_date,
            renewal_date=renewal_date,
            document_refs=list(document_refs or []),
        )
        case.policy = policy.model_dump(mode="json")
        case.status = CaseStatus.ACTIVE_POLICY
        case.touch()
        return WorkflowResult(
            action="open_policy_wallet",
            message="The issued policy has been recorded on the AshlarCase.",
            payload={"policy": policy.model_dump(mode="json")},
        )

    def build_policy_wallet(self, case: AshlarCase) -> WorkflowResult:
        if not case.policy:
            raise WorkflowError("No issued policy is stored on this case.", code="policy_required")
        policy = PolicyRecord.model_validate(case.policy)
        ledger = FactLedger(case.facts)
        subject = f"plan:{policy.plan_key}"

        core_keys = (
            "annual_limit",
            "deductible_or_excess",
            "area_of_cover",
            "underwriting_basis",
            "premium_amount",
        )
        core: dict[str, Any] = {}
        for key in core_keys:
            fact = ledger.current(key, subject=subject)
            if fact is not None and fact.status == FactStatus.VERIFIED:
                core[key] = deepcopy(fact.value)

        benefits: dict[str, Any] = {}
        for fact in case.facts:
            if (
                fact.subject == subject
                and fact.status == FactStatus.VERIFIED
                and fact.key.startswith("benefit.")
            ):
                current = ledger.current(fact.key, subject=subject)
                if current is not None and current.status == FactStatus.VERIFIED:
                    benefits[fact.key.removeprefix("benefit.")] = deepcopy(current.value)

        conflicts = [
            conflict.key
            for conflict in ledger.conflicts()
            if conflict.subject == subject
        ]
        wallet = PolicyWallet(
            policy_number=policy.policy_number,
            provider=policy.provider,
            plan_key=policy.plan_key,
            start_date=policy.start_date,
            renewal_date=policy.renewal_date,
            core_facts=core,
            verified_benefits=benefits,
            unresolved_conflicts=conflicts,
        )
        case.metadata["policy_wallet"] = wallet.model_dump(mode="json")
        case.touch()
        return WorkflowResult(
            action="use_policy_wallet",
            message="The Policy Wallet has been built from issued-policy data and verified facts only.",
            payload={"wallet": wallet.model_dump(mode="json")},
        )

    def create_preauthorisation(
        self,
        case: AshlarCase,
        *,
        service_key: str,
        provider_name: str | None = None,
        facility_name: str | None = None,
        planned_date: date | None = None,
        document_refs: list[str] | None = None,
    ) -> WorkflowResult:
        plan_key = self._require_selected_plan(case)
        if not case.policy or case.status not in {CaseStatus.ACTIVE_POLICY, CaseStatus.CLAIM}:
            raise WorkflowError(
                "An active issued policy is required before pre-authorisation.",
                code="active_policy_required",
            )
        record = PreauthorisationRecord(
            plan_key=plan_key,
            service_key=service_key,
            provider_name=provider_name,
            facility_name=facility_name,
            planned_date=planned_date,
            document_refs=list(document_refs or []),
        )
        case.preauthorisations.append(record.model_dump(mode="json"))
        case.touch()
        return WorkflowResult(
            action="check_policy_and_submit_preauthorisation",
            message="A pre-authorisation request has been opened on the active policy.",
            payload={"preauthorisation": record.model_dump(mode="json")},
        )

    def create_claim(
        self,
        case: AshlarCase,
        *,
        service_date: date | None = None,
        amount: float | None = None,
        currency: str | None = None,
        document_refs: list[str] | None = None,
        note: str | None = None,
    ) -> WorkflowResult:
        plan_key = self._require_selected_plan(case)
        if not case.policy:
            raise WorkflowError(
                "An issued policy is required before a claim can be opened.",
                code="policy_required",
            )
        claim = ClaimRecord(
            plan_key=plan_key,
            service_date=service_date,
            amount=amount,
            currency=currency,
            document_refs=list(document_refs or []),
            note=note,
        )
        case.claims.append(claim.model_dump(mode="json"))
        case.status = CaseStatus.CLAIM
        case.touch()
        return WorkflowResult(
            action="collect_claim_evidence",
            message="A claim case has been opened.",
            payload={"claim": claim.model_dump(mode="json")},
        )

    def start_renewal(self, case: AshlarCase) -> WorkflowResult:
        if not case.policy:
            raise WorkflowError(
                "An issued policy is required before renewal comparison.",
                code="policy_required",
            )
        policy = PolicyRecord.model_validate(case.policy)
        renewal = RenewalRecord(
            current_plan_key=policy.plan_key,
            renewal_date=policy.renewal_date,
        )
        case.renewal = renewal.model_dump(mode="json")
        case.status = CaseStatus.RENEWAL
        case.touch()
        return WorkflowResult(
            action="refresh_renewal_quotes",
            message="The renewal review has started.",
            payload={"renewal": renewal.model_dump(mode="json")},
        )


_JOURNEY_WORKFLOW = JourneyWorkflowService()


def get_journey_workflow() -> JourneyWorkflowService:
    return _JOURNEY_WORKFLOW
